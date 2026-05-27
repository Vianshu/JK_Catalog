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
import glob
import time
import threading
import getpass
import pyodbc
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# ─── SINGLETON ────────────────────────────────────────────────────────────────

_instance = None
_instance_lock = threading.Lock()

def get_db_manager():
    """Get the singleton DBManager instance (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:  # Double-checked locking
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


def build_logical_name(company_name=None, db_type=None, company_path=None):
    """Build a SQL Server logical database name.
    
    One database per company per location — all tables (stock_items, catalog,
    cheques, godown_stock, ledger, etc.) live in the same database.
    
    Args:
        company_name: Company display name (e.g., 'HW Divison 082083').
                      If not provided, extracted from company_path.
        db_type: Ignored (kept for backward compatibility).
        company_path: Full path to the company folder. When provided,
                      a short hash is appended to make the DB name unique
                      per location (so copies get separate databases).
    
    Returns:
        str: e.g., 'JK_HW_Divison_082083_a3f2b1c0'
    """
    import hashlib
    
    # Extract company name from path if not provided
    if not company_name and company_path:
        company_name = os.path.basename(os.path.normpath(company_path))
    
    base = f"JK_{sanitize_db_name(company_name)}"
    
    if company_path:
        # Normalize path for consistent hashing across runs
        norm_path = os.path.normpath(company_path).lower()
        path_hash = hashlib.md5(norm_path.encode()).hexdigest()[:8]
        return f"{base}_{path_hash}"
    
    # Fallback: no path provided → old-style name (shared DBs like JK_Security)
    return base


# ─── ORIGIN TRACKING ─────────────────────────────────────────────────────────

ORIGIN_FILE = ".jk_origin.json"

def check_data_origin(data_path):
    """Check if the data folder was copied from a different location.
    
    Reads .jk_origin.json from the data folder. If the stored path
    differs from the current path, the data was copied.
    
    Returns:
        dict with keys:
            'is_copy': bool — True if this is a copied data folder
            'original_path': str — the original path (empty if first time)
            'current_path': str — the current path
    """
    origin_file = os.path.join(data_path, ORIGIN_FILE)
    current = os.path.normpath(data_path)
    
    if not os.path.exists(origin_file):
        # First time — not a copy
        return {"is_copy": False, "original_path": "", "current_path": current}
    
    try:
        with open(origin_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        stored = os.path.normpath(data.get("data_path", ""))
        if stored.lower() == current.lower():
            return {"is_copy": False, "original_path": stored, "current_path": current}
        else:
            return {"is_copy": True, "original_path": stored, "current_path": current}
    except Exception:
        return {"is_copy": False, "original_path": "", "current_path": current}


def save_data_origin(data_path):
    """Save the current path as the origin in .jk_origin.json.
    
    Called after first-time setup or after the user acknowledges a copy.
    """
    origin_file = os.path.join(data_path, ORIGIN_FILE)
    try:
        data = {"data_path": os.path.normpath(data_path)}
        with open(origin_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved data origin: {data_path}")
    except Exception as e:
        logger.warning(f"Could not save origin file: {e}")

# ─── SHARED (ROOT-LEVEL) DATABASE NAMES ──────────────────────────────────────

# Default names (used only as fallback before data_path is known)
DB_SECURITY    = "JK_Security"
DB_SUPER       = "JK_SuperMaster"
DB_CALENDAR    = "JK_CalendarData"


def build_shared_db_name(base_name, data_path):
    """Build a path-aware shared DB name (Security, SuperMaster, Calendar).
    
    Each data path folder gets its own isolated set of shared databases.
    
    Args:
        base_name: e.g., 'JK_Security'
        data_path: Root data path (parent of company folders)
    
    Returns:
        str: e.g., 'JK_Security_a3f2b1c0'
    """
    import hashlib
    norm_path = os.path.normpath(data_path).lower()
    path_hash = hashlib.md5(norm_path.encode()).hexdigest()[:8]
    return f"{base_name}_{path_hash}"


# ─── CORE MANAGER ────────────────────────────────────────────────────────────

class DBManager:
    """Centralized SQL Server connection manager.
    
    Manages connections to all databases (shared and per-company).
    Handles database creation with MDF/LDF files in specified folders.
    """

    def __init__(self):
        self._server_name = ""
        self._connections = {}  # {logical_name: pyodbc.Connection}
        self._health_timestamps = {}  # {cache_key: last_healthy_epoch}
        self._HEALTH_TTL = 30  # seconds — skip SELECT 1 if verified recently
        self._lock = threading.Lock()  # Protects _connections dict mutations
        self._db_locks = {}  # {cache_key: Lock} — per-database locks reduce contention
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
        2. Add them to dbcreator role (requires sysadmin, may fail for non-admin users)
        3. Ensure BUILTIN Users login exists (so _grant_db_owner can grant per-DB access)
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
                cursor.execute(
                    "IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'BUILTIN\\Users')"
                    " CREATE LOGIN [BUILTIN\\Users] FROM WINDOWS;"
                )
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
        
        # Get or create a per-database lock (avoids global contention)
        with self._lock:
            if cache_key not in self._db_locks:
                self._db_locks[cache_key] = threading.Lock()
            db_lock = self._db_locks[cache_key]
        
        with db_lock:
            # Return cached connection if still alive
            if cache_key in self._connections:
                conn = self._connections[cache_key]
                # Skip health check if verified recently (saves ~5ms per call)
                last_healthy = self._health_timestamps.get(cache_key, 0)
                if time.time() - last_healthy < self._HEALTH_TTL:
                    return conn
                try:
                    conn.execute("SELECT 1")
                    self._health_timestamps[cache_key] = time.time()
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._connections.pop(cache_key, None)
                    self._health_timestamps.pop(cache_key, None)

            # Create new connection
            try:
                conn_str = self._build_connection_string(logical_name)
                conn = pyodbc.connect(conn_str, autocommit=False)
                self._connections[cache_key] = conn
                return conn
            except pyodbc.Error as e:
                # Connection failed — try fixing permissions from master and retry
                if self._try_fix_db_permissions(logical_name):
                    try:
                        conn = pyodbc.connect(conn_str, autocommit=False)
                        self._connections[cache_key] = conn
                        logger.info(f"Connected to '{logical_name}' after permission fix")
                        return conn
                    except pyodbc.Error:
                        pass
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
            self._health_timestamps.clear()

    # ─── DATABASE CREATION ────────────────────────────────────────────────────

    def ensure_database_exists(self, logical_name, mdf_folder, company_name=None):
        """Create a SQL Server database if it doesn't already exist.
        
        The MDF and LDF files will be placed in `mdf_folder`, matching
        the existing folder structure used by SQLite.
        
        Args:
            logical_name: e.g., 'JK_CompanyA_Catalog_a3f2b1c0'
            mdf_folder: e.g., 'D:\\SharedData\\CompanyA\\'
            company_name: If provided, attempts to migrate old-style DB first.
        
        Returns:
            bool: True if database exists or was created successfully.
        """
        # Try migrating old-style DB name if applicable
        if company_name:
            self.migrate_old_db_name(logical_name, company_name)
        
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

    def migrate_old_db_name(self, new_name, company_name):
        """Migrate an old-style DB (without path hash) to the new name.
        
        If the new-style DB doesn't exist but the old-style one does,
        rename it. This provides seamless backward compatibility.
        
        Args:
            new_name: New-style DB name (e.g., 'JK_HW_Divison_082083_a3f2b1c0')
            company_name: Company folder name (e.g., 'HW Divison 082083')
        
        Returns:
            bool: True if migration happened or wasn't needed.
        """
        if self.database_exists(new_name):
            return True  # New-style already exists, nothing to do
        
        old_name = f"JK_{sanitize_db_name(company_name)}"
        if not self.database_exists(old_name):
            return True  # Neither exists, fresh install
        
        # Old exists, new doesn't → rename
        conn = self.get_master_connection()
        if not conn:
            return False
        try:
            _, old_b = self._safe_sql_ident(old_name)
            _, new_b = self._safe_sql_ident(new_name)
            cursor = conn.cursor()
            cursor.execute(f"ALTER DATABASE [{old_b}] MODIFY NAME = [{new_b}];")
            logger.info(f"Migrated database '{old_name}' -> '{new_name}'")
            return True
        except Exception as e:
            logger.warning(f"Could not migrate DB '{old_name}' -> '{new_name}': {e}")
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
        
        # Check for old-hash MDF files (data folder was copied to a new location)
        # e.g., logical_name = 'JK_HW_Divison_082083_newHash'
        #        old file    = 'JK_HW_Divison_082083_oldHash.mdf'
        # Extract the base prefix (everything before the last _hash segment)
        parts = logical_name.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 8:
            prefix = parts[0]  # e.g., 'JK_HW_Divison_082083'
            pattern = os.path.join(mdf_folder, f"{prefix}_*.mdf")
            old_mdfs = glob.glob(pattern)
            for old_mdf in old_mdfs:
                old_basename = os.path.splitext(os.path.basename(old_mdf))[0]
                if old_basename == logical_name:
                    continue  # Already checked above
                old_ldf = os.path.join(mdf_folder, f"{old_basename}_log.ldf")
                try:
                    # Just rename — do NOT detach old DB (it belongs to the original location)
                    os.rename(old_mdf, mdf_path)
                    logger.info(f"Renamed MDF: {os.path.basename(old_mdf)} -> {os.path.basename(mdf_path)}")
                    if os.path.exists(old_ldf):
                        os.rename(old_ldf, ldf_path)
                    
                    return self._attach_database(logical_name, mdf_path, ldf_path)
                except Exception as re:
                    logger.warning(f"Could not rename old MDF '{old_basename}': {re}")

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
        
        Granting BUILTIN Users ensures all RDP users can access the database
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
            cursor.execute(
                f"USE [{db_b}]; "
                f"IF NOT EXISTS (SELECT * FROM sys.server_principals WHERE name = N'BUILTIN\\Users') "
                f"CREATE LOGIN [BUILTIN\\Users] FROM WINDOWS;"
            )
            cursor.execute(
                f"USE [{db_b}]; "
                "IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = N'BuiltinUsers') "
                "BEGIN "
                "CREATE USER [BuiltinUsers] FOR LOGIN [BUILTIN\\Users]; "
                "END; "
                "ALTER ROLE db_owner ADD MEMBER [BuiltinUsers];"
            )
            logger.info(f"Granted db_owner to BUILTIN\\Users on '{logical_name}'")
        except Exception as e:
            logger.warning(f"Could not grant BUILTIN\\Users on '{logical_name}': {e}")

    def _try_fix_db_permissions(self, logical_name):
        """Fix permissions on a database we can't connect to.
        
        Called by get_connection when the initial connection fails. Uses the
        master connection (which is always accessible) to set the current
        Windows user as the DB owner via ALTER AUTHORIZATION, then grants
        BUILTIN\\Users access.
        
        Returns:
            bool: True if permissions were fixed, False otherwise.
        """
        if not self.database_exists(logical_name):
            return False
        
        conn = self.get_master_connection()
        if not conn:
            return False
        
        try:
            _, safe_b = self._safe_sql_ident(logical_name)
            win_login = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
            _, login_b = self._safe_sql_ident(win_login)
            cursor = conn.cursor()
            
            # Set current user as DB owner (runs from master, no USE needed)
            cursor.execute(f"ALTER AUTHORIZATION ON DATABASE::[{safe_b}] TO [{login_b}];")
            logger.info(f"Fixed DB owner: '{win_login}' on '{logical_name}'")
            
            # Now grant BUILTIN\Users too
            self._grant_db_owner(cursor, logical_name)
            return True
        except Exception as e:
            logger.warning(f"Could not fix permissions on '{logical_name}': {e}")
            return False
        finally:
            conn.close()

    def _attach_database(self, logical_name, mdf_path, ldf_path):
        """Attach an existing MDF file as a database.
        
        Used when data folders are copied/moved from another machine.
        The MDF file exists on disk but isn't registered with this SQL Server instance.
        
        After attaching, we must fix permissions because the DB's internal dbo
        is mapped to a login from the original machine that doesn't exist here.
        We use ALTER AUTHORIZATION (runs from master, no USE needed) to set the
        current login as DB owner, then grant BUILTIN\\Users.
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

            # Fix ownership: the old dbo is orphaned (mapped to original machine's login).
            # ALTER AUTHORIZATION runs from master context — no USE needed.
            try:
                win_login = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
                _, login_b = self._safe_sql_ident(win_login)
                cursor.execute(f"ALTER AUTHORIZATION ON DATABASE::[{safe_b}] TO [{login_b}];")
                logger.info(f"Set DB owner to '{win_login}' on attached '{logical_name}'")
            except Exception as e:
                logger.warning(f"ALTER AUTHORIZATION failed on '{logical_name}': {e}")

            # Now grant db_owner to current user and BUILTIN\Users
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

    # ─── DATA MANAGEMENT ─────────────────────────────────────────────────────

    def drop_database(self, logical_name):
        """Safely drop a SQL Server database.
        
        Kicks out all active connections first, then drops the database.
        Also deletes the MDF/LDF files from disk (SQL Server does this
        automatically when dropping a database it created).
        
        Returns:
            bool: True if dropped successfully, False otherwise.
        """
        # Close any cached connections to this DB first
        self.close_connection(logical_name)
        
        conn = self.get_master_connection()
        if not conn:
            return False
        
        try:
            _, safe_b = self._safe_sql_ident(logical_name)
            cursor = conn.cursor()
            
            # Try normal: force disconnect all users, then drop
            try:
                cursor.execute(f"""
                    IF EXISTS (SELECT name FROM sys.databases WHERE name = N'{safe_b}')
                    BEGIN
                        ALTER DATABASE [{safe_b}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
                        DROP DATABASE [{safe_b}];
                    END
                """)
            except pyodbc.Error:
                # Fallback: DB may be in Restoring/Offline state where ALTER is blocked
                # but direct DROP still works
                cursor.execute(f"""
                    IF EXISTS (SELECT name FROM sys.databases WHERE name = N'{safe_b}')
                        DROP DATABASE [{safe_b}];
                """)
            logger.info(f"Dropped database '{logical_name}'")
            return True
        except pyodbc.Error as e:
            logger.error(f"Failed to drop database '{logical_name}': {e}")
            return False
        finally:
            conn.close()

    def backup_database(self, logical_name, backup_path):
        """Backup a SQL Server database to a .bak file.
        
        Args:
            logical_name: Database name (e.g., 'JK_Security_abc123')
            backup_path: Full path for the .bak file
        
        Returns:
            bool: True if backup succeeded.
        """
        # Ensure backup folder exists and SQL Server can write to it
        backup_dir = os.path.dirname(backup_path)
        os.makedirs(backup_dir, exist_ok=True)
        self._grant_sql_server_permissions(backup_dir)
        
        conn = self.get_master_connection()
        if not conn:
            return False
        
        try:
            _, safe_b = self._safe_sql_ident(logical_name)
            safe_backup_path = backup_path.replace("'", "''")
            cursor = conn.cursor()
            cursor.execute(f"""
                BACKUP DATABASE [{safe_b}]
                TO DISK = N'{safe_backup_path}'
                WITH FORMAT, INIT,
                     NAME = N'{safe_b}_Backup'
            """)
            # BACKUP produces informational result sets — consume them all
            while cursor.nextset():
                pass
            logger.info(f"Backed up '{logical_name}' -> {backup_path}")
            return True
        except pyodbc.Error as e:
            logger.error(f"Failed to backup '{logical_name}': {e}")
            return False
        finally:
            conn.close()
            # Grant current user read access to the .bak file
            # (SQL Server service account owns it)
            if os.path.exists(backup_path):
                import subprocess
                try:
                    subprocess.run(
                        ['icacls', backup_path, '/grant',
                         f'{os.environ.get("USERDOMAIN", "BUILTIN")}\\Users:(R)'],
                        capture_output=True, timeout=10
                    )
                except Exception:
                    pass

    def get_backup_file_list(self, backup_path):
        """Get the logical file names from a .bak backup file.
        
        Returns:
            list of tuples: [(logical_name, physical_name, type), ...]
            type is 'D' for data (MDF) or 'L' for log (LDF)
        """
        conn = self.get_master_connection()
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            safe_backup_path = backup_path.replace("'", "''")
            cursor.execute(f"RESTORE FILELISTONLY FROM DISK = N'{safe_backup_path}'")
            rows = cursor.fetchall()
            result = []
            for row in rows:
                result.append((row[0], row[1], row[2]))  # LogicalName, PhysicalName, Type
            return result
        except pyodbc.Error as e:
            logger.error(f"Failed to read backup file list from '{backup_path}': {e}")
            return []
        finally:
            conn.close()

    def restore_database(self, logical_name, backup_path, mdf_folder):
        """Restore a SQL Server database from a .bak file.
        
        Uses WITH MOVE to place MDF/LDF files in the specified folder
        with the correct logical name. This handles path changes
        (different data path on a different machine).
        
        Args:
            logical_name: New database name (e.g., 'JK_Security_newHash')
            backup_path: Path to the .bak file
            mdf_folder: Where to place the restored MDF/LDF files
        
        Returns:
            bool: True if restore succeeded.
        """
        os.makedirs(mdf_folder, exist_ok=True)
        self._grant_sql_server_permissions(mdf_folder)
        
        # Get logical file names from the backup
        file_list = self.get_backup_file_list(backup_path)
        if not file_list:
            logger.error(f"No file list in backup: {backup_path}")
            return False
        
        # Build MOVE clauses
        mdf_path = os.path.join(mdf_folder, f"{logical_name}.mdf")
        ldf_path = os.path.join(mdf_folder, f"{logical_name}_log.ldf")
        
        move_clauses = []
        for logical_file, _, file_type in file_list:
            if file_type == 'D':
                move_clauses.append(f"MOVE N'{logical_file}' TO N'{mdf_path}'")
            elif file_type == 'L':
                move_clauses.append(f"MOVE N'{logical_file}' TO N'{ldf_path}'")
        
        if not move_clauses:
            logger.error(f"Could not build MOVE clauses for restore")
            return False
        
        # Drop existing DB with same name if it exists
        if self.database_exists(logical_name):
            self.drop_database(logical_name)
        
        conn = self.get_master_connection()
        if not conn:
            return False
        
        _, safe_b = self._safe_sql_ident(logical_name)
        safe_backup_path = backup_path.replace("'", "''")
        move_sql = ", ".join(move_clauses)
        
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                RESTORE DATABASE [{safe_b}]
                FROM DISK = N'{safe_backup_path}'
                WITH {move_sql}, REPLACE
            """)
            # RESTORE produces informational result sets — consume them all
            while cursor.nextset():
                pass
            logger.info(f"Restored '{logical_name}' from {backup_path} -> {mdf_folder}")
        except pyodbc.Error as e:
            logger.error(f"Failed to restore '{logical_name}': {e}")
            return False
        finally:
            conn.close()
        
        # Use a FRESH master connection for permission grants
        # (the old connection may have stale state after RESTORE)
        import time
        time.sleep(1)  # Brief pause to let SQL Server finish recovery
        
        conn2 = self.get_master_connection()
        if conn2:
            try:
                cursor2 = conn2.cursor()
                # Fix permissions for current user
                try:
                    win_login = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
                    _, login_b = self._safe_sql_ident(win_login)
                    cursor2.execute(f"ALTER AUTHORIZATION ON DATABASE::[{safe_b}] TO [{login_b}];")
                except Exception as e:
                    logger.warning(f"ALTER AUTHORIZATION after restore failed: {e}")
                
                # Grant BUILTIN\Users
                self._grant_db_owner(cursor2, logical_name)
            except Exception as e:
                logger.warning(f"Post-restore permission grants failed: {e}")
            finally:
                conn2.close()
        
        return True

