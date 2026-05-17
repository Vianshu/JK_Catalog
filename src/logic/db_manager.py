"""
Database Manager — Centralized SQL Server connection layer.

Replaces all direct sqlite3.connect() calls across the codebase.
Handles:
  - Connection string building (from config)
  - Database creation with MDF/LDF in specified folders
  - Connection caching per logical database name
  - SQL Server ↔ SQLite syntax translation helpers

Usage:
    from src.logic.db_manager import get_db_manager
    db = get_db_manager()
    conn = db.get_connection("JK_CompanyA_Catalog")
"""

import os
import re
import json
import threading
import getpass
import pyodbc
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# ─── SINGLETON ────────────────────────────────────────────────────────────────

_instance = None

def get_db_manager():
    """Get the singleton DBManager instance."""
    global _instance
    if _instance is None:
        _instance = DBManager()
    return _instance


def reset_db_manager():
    """Reset the singleton (used when server config changes)."""
    global _instance
    if _instance:
        _instance.close_all()
    _instance = None


# ─── LOGICAL NAME HELPERS ─────────────────────────────────────────────────────

def sanitize_db_name(name):
    """Convert a display name to a safe SQL Server database name.
    
    'HW Divison 082083' → 'HW_Divison_082083'
    """
    # Replace spaces and special chars with underscores
    safe = "".join(c if c.isalnum() or c == '_' else '_' for c in name)
    # Remove consecutive underscores
    while '__' in safe:
        safe = safe.replace('__', '_')
    return safe.strip('_')


def build_logical_name(company_name, db_type=None):
    """Build a SQL Server logical database name.
    
    One database per company — all tables (stock_items, catalog, cheques,
    godown_stock, ledger, etc.) live in the same database.
    
    Args:
        company_name: Company display name (e.g., 'HW Divison 082083')
        db_type: Ignored (kept for backward compatibility).
    
    Returns:
        str: e.g., 'JK_HW_Divison_082083'
    """
    return f"JK_{sanitize_db_name(company_name)}"


# ─── SHARED (ROOT-LEVEL) DATABASE NAMES ──────────────────────────────────────

DB_SECURITY    = "JK_Security"
DB_SUPER       = "JK_SuperMaster"
DB_CALENDAR    = "JK_CalendarData"


# ─── CORE MANAGER ────────────────────────────────────────────────────────────

class DBManager:
    """Centralized SQL Server connection manager.
    
    Manages connections to all databases (shared and per-company).
    Handles database creation with MDF/LDF files in specified folders.
    """

    def __init__(self):
        self._server_name = ""
        self._connections = {}  # {logical_name: pyodbc.Connection}
        self._lock = threading.Lock()  # Thread-safe connection access
        self._load_server_config()
        self._ensure_login()

    # ─── CONFIG ───────────────────────────────────────────────────────────────

    def _load_server_config(self):
        """Load SQL Server instance name from config.json.
        
        Checks (in order):
          1. User-specific config: %APPDATA%/JK_Catalog/config.json
          2. Global config: next to the EXE
          3. Dev fallback: project root config.json
        """
        from src.utils.path_utils import get_app_dir, get_exe_dir

        # 1. User config
        user_config = os.path.join(get_app_dir(), "config.json")
        server = self._read_server_from_config(user_config)
        if server:
            self._server_name = server
            return

        # 2. Global config (next to EXE)
        global_config = os.path.join(get_exe_dir(), "config.json")
        if global_config != user_config:
            server = self._read_server_from_config(global_config)
            if server:
                self._server_name = server
                return

        # 3. Fallback: local SQLEXPRESS
        self._server_name = r".\SQLEXPRESS"
        logger.warning(f"No SQL Server config found, using default: {self._server_name}")

    @staticmethod
    def _safe_sql_ident(value):
        """Sanitize a value for DDL contexts where parameterized queries aren't supported."""
        if not re.match(r'^[A-Za-z0-9_ \\\.$\-]+$', value):
            raise ValueError(f"Unsafe SQL identifier rejected: {value!r}")
        return value.replace("'", "''"), value.replace("]", "]]")

    def _ensure_login(self):
        """Ensure the current Windows user has a SQL Server login.
        
        Attempts to:
        1. Create a Windows login for the current user
        2. Add them to dbcreator role (requires sysadmin — may fail for non-admin users)
        3. Ensure BUILTIN\Users login exists (so _grant_db_owner can grant per-DB access)
        """
        conn = self.get_master_connection()
        if not conn:
            return
        try:
            win_login = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
            safe_q, safe_b = self._safe_sql_ident(win_login)
            cursor = conn.cursor()
            
            # Create login (if not exists)
            cursor.execute(f"""
                IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'{safe_q}')
                    CREATE LOGIN [{safe_b}] FROM WINDOWS;
            """)
            logger.info(f"Ensured SQL Server login for '{win_login}'")
            
            # Try dbcreator role (will fail for non-admin users — that's OK)
            try:
                cursor.execute(f"ALTER SERVER ROLE dbcreator ADD MEMBER [{safe_b}];")
            except Exception:
                pass  # Non-admin users rely on BUILTIN\Users grants instead
            
            # Ensure BUILTIN\Users login exists at server level
            try:
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'BUILTIN\Users')
                        CREATE LOGIN [BUILTIN\Users] FROM WINDOWS;
                """)
            except Exception:
                pass
                
            conn.close()
        except ValueError as e:
            logger.warning(f"Skipping _ensure_login: {e}")
        except Exception as e:
            logger.warning(f"Could not ensure SQL Server login: {e}")

    def _read_server_from_config(self, config_path):
        """Read sql_server_name from a config.json file."""
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("sql_server_name", "")
        except Exception:
            pass
        return ""

    @property
    def server_name(self):
        return self._server_name

    @server_name.setter
    def server_name(self, value):
        if value != self._server_name:
            self.close_all()
            self._server_name = value

    # ─── CONNECTION STRING ────────────────────────────────────────────────────

    def _build_connection_string(self, database_name=None):
        """Build a pyodbc connection string for SQL Server.
        
        Uses Windows Authentication (Trusted_Connection) so no
        SQL credentials are needed — the Windows login is enough.
        """
        parts = [
            "DRIVER={ODBC Driver 17 for SQL Server}",
            f"SERVER={self._server_name}",
            "Trusted_Connection=yes",
        ]
        if database_name:
            parts.append(f"DATABASE={database_name}")
        return ";".join(parts)

    # ─── CONNECTION MANAGEMENT ────────────────────────────────────────────────

    def get_connection(self, logical_name):
        """Get a connection to a SQL Server database by its logical name.
        
        Thread-safe: each thread gets its own cached connection to avoid
        pyodbc cross-thread issues.
        
        Args:
            logical_name: e.g., 'JK_Security', 'JK_CompanyA_Catalog'
        
        Returns:
            pyodbc.Connection or None if connection fails.
        """
        # Per-thread cache key
        tid = threading.current_thread().ident
        cache_key = f"{logical_name}_{tid}"
        
        with self._lock:
            # Return cached connection if still alive
            if cache_key in self._connections:
                conn = self._connections[cache_key]
                try:
                    conn.execute("SELECT 1")
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._connections.pop(cache_key, None)

            # Create new connection
            try:
                conn_str = self._build_connection_string(logical_name)
                conn = pyodbc.connect(conn_str, autocommit=False)
                self._connections[cache_key] = conn
                return conn
            except pyodbc.Error as e:
                logger.error(f"Failed to connect to '{logical_name}': {e}")
                return None

    def get_master_connection(self):
        """Get a connection to the 'master' database (for CREATE DATABASE commands)."""
        try:
            conn_str = self._build_connection_string("master")
            conn = pyodbc.connect(conn_str, autocommit=True)
            return conn
        except pyodbc.Error as e:
            logger.error(f"Failed to connect to master DB: {e}")
            return None

    def close_connection(self, logical_name):
        """Close and remove a specific connection from the cache."""
        with self._lock:
            if logical_name in self._connections:
                try:
                    self._connections[logical_name].close()
                except Exception:
                    pass
                del self._connections[logical_name]

    def close_all(self):
        """Close all cached connections."""
        with self._lock:
            for name, conn in list(self._connections.items()):
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()

    # ─── DATABASE CREATION ────────────────────────────────────────────────────

    def ensure_database_exists(self, logical_name, mdf_folder):
        """Create a SQL Server database if it doesn't already exist.
        
        The MDF and LDF files will be placed in `mdf_folder`, matching
        the existing folder structure used by SQLite.
        
        Args:
            logical_name: e.g., 'JK_CompanyA_Catalog'
            mdf_folder: e.g., 'D:\\SharedData\\CompanyA\\'
        
        Returns:
            bool: True if database exists or was created successfully.
        """
        if self.database_exists(logical_name):
            return True

        return self.create_database(logical_name, mdf_folder)

    def database_exists(self, logical_name):
        """Check if a database exists on the SQL Server instance."""
        conn = self.get_master_connection()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DB_ID(?) AS dbid", logical_name
            )
            row = cursor.fetchone()
            return row and row.dbid is not None
        except Exception as e:
            logger.error(f"database_exists check failed for '{logical_name}': {e}")
            return False
        finally:
            conn.close()

    def _grant_sql_server_permissions(self, folder_path):
        """Grant SQL Server service account write access to a folder.
        
        SQL Server runs as 'NT Service\\MSSQL$<INSTANCE>' and cannot write to
        user profile folders by default. This runs icacls to grant full control.
        Only needs to succeed once per folder.
        """
        import subprocess
        
        # Determine service account name from server instance
        instance = "MSSQLSERVER"  # default instance
        if '\\' in self._server_name:
            instance = "MSSQL$" + self._server_name.split('\\')[-1]
        
        service_account = f"NT Service\\{instance}"
        
        try:
            result = subprocess.run(
                ['icacls', folder_path, '/grant',
                 f'{service_account}:(OI)(CI)F', '/T'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                logger.info(f"Granted SQL Server permissions on '{folder_path}' to '{service_account}'")
            else:
                logger.warning(f"icacls failed (rc={result.returncode}): {result.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Could not grant SQL Server folder permissions: {e}")

    def create_database(self, logical_name, mdf_folder):
        """Create a new SQL Server database with MDF/LDF in the specified folder.
        
        Args:
            logical_name: e.g., 'JK_CompanyA_Catalog'
            mdf_folder: e.g., 'D:\\SharedData\\CompanyA\\'
        
        Returns:
            bool: True on success.
        """
        # Normalize to backslashes — SQL Server FILENAME rejects forward slashes
        mdf_folder = os.path.normpath(mdf_folder)
        os.makedirs(mdf_folder, exist_ok=True)

        # Grant SQL Server service write access (no-op if already granted)
        self._grant_sql_server_permissions(mdf_folder)

        mdf_path = os.path.join(mdf_folder, f"{logical_name}.mdf")
        ldf_path = os.path.join(mdf_folder, f"{logical_name}_log.ldf")

        # If MDF already exists on disk (copied/moved from another machine), ATTACH it
        if os.path.exists(mdf_path):
            return self._attach_database(logical_name, mdf_path, ldf_path)

        conn = self.get_master_connection()
        if not conn:
            return False

        try:
            safe_q, safe_b = self._safe_sql_ident(logical_name)
            cursor = conn.cursor()
            sql = f"""
                CREATE DATABASE [{safe_b}]
                ON PRIMARY (
                    NAME = N'{safe_q}_Data',
                    FILENAME = N'{mdf_path}',
                    SIZE = 4MB,
                    FILEGROWTH = 2MB
                )
                LOG ON (
                    NAME = N'{safe_q}_Log',
                    FILENAME = N'{ldf_path}',
                    SIZE = 2MB,
                    FILEGROWTH = 1MB
                )
            """
            cursor.execute(sql)
            logger.info(f"Created database '{logical_name}' -> MDF: {mdf_path}")
            
            # Grant the current Windows login full access to the new database
            self._grant_db_owner(cursor, logical_name)
            
            return True
        except pyodbc.Error as e:
            logger.error(f"Failed to create database '{logical_name}': {e}")
            return False
        finally:
            conn.close()

    def _grant_db_owner(self, cursor, logical_name):
        """Grant db_owner to the current Windows user AND all local users on a database.
        
        Granting BUILTIN\\Users ensures all RDP users can access the database
        without manual per-user SQL commands. The app's RBAC system handles
        actual access control (roles, permissions).
        """
        _, db_b = self._safe_sql_ident(logical_name)
        
        # Grant current user
        try:
            win_login = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
            safe_q, safe_b = self._safe_sql_ident(win_login)
            cursor.execute(f"""
                USE [{db_b}];
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = N'{safe_q}')
                BEGIN
                    CREATE USER [{safe_b}] FOR LOGIN [{safe_b}];
                END
                ALTER ROLE db_owner ADD MEMBER [{safe_b}];
            """)
            logger.info(f"Granted db_owner to '{win_login}' on '{logical_name}'")
        except Exception as e:
            logger.warning(f"Could not grant db_owner to current user on '{logical_name}': {e}")
        
        # Grant BUILTIN\Users (all Windows users on this machine)
        try:
            cursor.execute(f"""
                USE [{db_b}];
                IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'BUILTIN\Users')
                    CREATE LOGIN [BUILTIN\Users] FROM WINDOWS;
            """)
            cursor.execute(f"""
                USE [{db_b}];
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = N'BuiltinUsers')
                BEGIN
                    CREATE USER [BuiltinUsers] FOR LOGIN [BUILTIN\Users];
                END
                ALTER ROLE db_owner ADD MEMBER [BuiltinUsers];
            """)
            logger.info(f"Granted db_owner to BUILTIN\\Users on '{logical_name}'")
        except Exception as e:
            logger.warning(f"Could not grant BUILTIN\\Users on '{logical_name}': {e}")

    def _attach_database(self, logical_name, mdf_path, ldf_path):
        """Attach an existing MDF file as a database.
        
        Used when data folders are copied/moved from another machine.
        The MDF file exists on disk but isn't registered with this SQL Server instance.
        """
        conn = self.get_master_connection()
        if not conn:
            return False

        try:
            safe_q, safe_b = self._safe_sql_ident(logical_name)
            cursor = conn.cursor()

            if os.path.exists(ldf_path):
                sql = f"""
                    CREATE DATABASE [{safe_b}]
                    ON PRIMARY (NAME = N'{safe_q}_Data', FILENAME = N'{mdf_path}')
                    LOG ON (NAME = N'{safe_q}_Log', FILENAME = N'{ldf_path}')
                    FOR ATTACH
                """
            else:
                # LDF missing — SQL Server will rebuild it
                sql = f"""
                    CREATE DATABASE [{safe_b}]
                    ON PRIMARY (NAME = N'{safe_q}_Data', FILENAME = N'{mdf_path}')
                    FOR ATTACH_REBUILD_LOG
                """

            cursor.execute(sql)
            logger.info(f"Attached database '{logical_name}' from MDF: {mdf_path}")

            # Grant db_owner to current user on the attached database
            self._grant_db_owner(cursor, logical_name)

            return True
        except pyodbc.Error as e:
            logger.error(f"Failed to attach database '{logical_name}': {e}")
            return False
        finally:
            conn.close()

    # ─── TABLE CREATION HELPERS ───────────────────────────────────────────────

    def ensure_table(self, logical_name, table_name, create_sql):
        """Create a table if it doesn't exist in the specified database.
        
        Args:
            logical_name: Database logical name
            table_name: Table name to check/create
            create_sql: Full CREATE TABLE SQL statement (SQL Server syntax)
        
        Returns:
            bool: True on success
        """
        conn = self.get_connection(logical_name)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            # Check if table exists
            cursor.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME = ?
            """, table_name)
            if cursor.fetchone()[0] == 0:
                cursor.execute(create_sql)
                conn.commit()
                logger.info(f"Created table '{table_name}' in '{logical_name}'")
            return True
        except pyodbc.Error as e:
            logger.error(f"ensure_table failed for '{table_name}' in '{logical_name}': {e}")
            return False

    def table_has_column(self, logical_name, table_name, column_name):
        """Check if a column exists in a table."""
        conn = self.get_connection(logical_name)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = ? AND COLUMN_NAME = ?
            """, table_name, column_name)
            return cursor.fetchone()[0] > 0
        except Exception:
            return False

    def add_column(self, logical_name, table_name, column_name, column_type="NVARCHAR(MAX)"):
        """Add a column to an existing table if it doesn't exist."""
        if self.table_has_column(logical_name, table_name, column_name):
            return True
        conn = self.get_connection(logical_name)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute(f"ALTER TABLE [{table_name}] ADD [{column_name}] {column_type}")
            conn.commit()
            logger.info(f"Added column '{column_name}' to '{table_name}' in '{logical_name}'")
            return True
        except pyodbc.Error as e:
            logger.error(f"add_column failed: {e}")
            return False

    # ─── QUERY HELPERS ────────────────────────────────────────────────────────

    def execute_query(self, logical_name, sql, params=None, fetch=True):
        """Execute a query and optionally fetch results.
        
        Args:
            logical_name: Database logical name
            sql: SQL query string (use ? for parameters)
            params: Tuple of parameters
            fetch: If True, return fetchall() results
        
        Returns:
            List of rows if fetch=True, else row count affected.
        """
        conn = self.get_connection(logical_name)
        if not conn:
            return [] if fetch else 0
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            if fetch:
                return cursor.fetchall()
            else:
                conn.commit()
                return cursor.rowcount
        except pyodbc.Error as e:
            logger.error(f"Query failed on '{logical_name}': {e}\nSQL: {sql[:200]}")
            try:
                conn.rollback()
            except Exception:
                pass
            return [] if fetch else 0

    # ─── UTILITY ──────────────────────────────────────────────────────────────

    def get_all_tables(self, logical_name):
        """List all user tables in a database."""
        rows = self.execute_query(
            logical_name,
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'"
        )
        return [r[0] for r in rows] if rows else []

    def get_table_columns(self, logical_name, table_name):
        """List all column names in a table."""
        rows = self.execute_query(
            logical_name,
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (table_name,)
        )
        return [r[0] for r in rows] if rows else []
