import hashlib
import os
from datetime import datetime
import hmac
import pyodbc
from src.logic.db_manager import get_db_manager, DB_SECURITY, DB_SUPER, DB_CALENDAR
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

APP_SECRET = b"JK_Catalog_v2_secure_key"  # compiled into the EXE
    
class SecurityManager:
    def __init__(self, data_path=""):
        """
        Initialize SecurityManager using SQL Server.
        
        Args:
            data_path (str): The shared data root folder where security MDF/LDF
                             files will be stored (e.g., 'D:\\SharedData\\').
                             Only needed for first-time database creation.
        """
        self.data_path = data_path
        self.db = get_db_manager()
        self.init_db()

    def init_db(self):
        """Initialize the Security database and tables if they don't exist.
        
        If the database already exists on the SQL Server, this is a no-op
        (no write permissions needed for read-only users).
        """
        # Ensure the database exists on SQL Server
        mdf_folder = self.data_path if self.data_path else os.getcwd()
        try:
            self.db.ensure_database_exists(DB_SECURITY, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure security DB (read-only user?): {e}")
            return

        # Create tables if they don't exist
        self.db.ensure_table(DB_SECURITY, "companies", """
            CREATE TABLE companies (
                id INT IDENTITY(1,1) PRIMARY KEY,
                display_name NVARCHAR(255) NOT NULL,
                folder_path NVARCHAR(500) UNIQUE NOT NULL,
                image_path NVARCHAR(500),
                created_at DATETIME DEFAULT GETDATE()
            )
        """)

        self.db.ensure_table(DB_SECURITY, "users", """
            CREATE TABLE users (
                id INT IDENTITY(1,1) PRIMARY KEY,
                company_id INT,
                username NVARCHAR(255) NOT NULL,
                password_hash NVARCHAR(255) NOT NULL,
                role NVARCHAR(50) DEFAULT 'user',
                is_active BIT DEFAULT 1,
                FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, username)
            )
        """)

        # Also ensure shared databases exist (SuperMaster, Calendar)
        try:
            self.db.ensure_database_exists(DB_SUPER, mdf_folder)
            self.db.ensure_database_exists(DB_CALENDAR, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure shared DBs: {e}")

    def _hash_password(self, password):
        return hmac.new(APP_SECRET, password.encode(), hashlib.sha256).hexdigest()


    def register_company(self, display_name, folder_path, image_path, admin_user, admin_pass):
        """
        Register a new company and its admin user.
        If company exists (same path), UPDATE its details and RESET admin password.
        
        Returns:
            int: The company ID on success.
        """
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        pass_hash = self._hash_password(admin_pass)
        
        conn = self.db.get_connection(DB_SECURITY)
        if not conn:
            logger.error("Cannot connect to Security DB for register_company")
            return None

        cursor = conn.cursor()
        try:
            # Check if company already exists
            cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (folder_path,))
            row = cursor.fetchone()

            if row:
                # Company exists → Update details
                company_id = row[0]
                cursor.execute("""
                    UPDATE companies 
                    SET display_name = ?, image_path = ?
                    WHERE id = ?
                """, (display_name, image_path, company_id))
            else:
                # New company → Insert
                cursor.execute("""
                    INSERT INTO companies (display_name, folder_path, image_path)
                    VALUES (?, ?, ?)
                """, (display_name, folder_path, image_path))
                # Get the newly inserted ID
                cursor.execute("SELECT SCOPE_IDENTITY()")
                company_id = int(cursor.fetchone()[0])

            # 2. Upsert Admin User (Ensure Admin exists and has new password)
            cursor.execute("SELECT id FROM users WHERE company_id = ? AND role = 'admin'", (company_id,))
            admin_row = cursor.fetchone()
            
            if admin_row:
                # Update existing admin
                cursor.execute("""
                    UPDATE users 
                    SET username = ?, password_hash = ?
                    WHERE id = ?
                """, (admin_user, pass_hash, admin_row[0]))
            else:
                # Create new admin
                cursor.execute("""
                    INSERT INTO users (company_id, username, password_hash, role)
                    VALUES (?, ?, ?, 'admin')
                """, (company_id, admin_user, pass_hash))
            
            conn.commit()
            logger.info(f"Company registered: id={company_id}, name='{display_name}', admin='{admin_user}'")
            return company_id

        except pyodbc.IntegrityError as e:
            logger.warning(f"IntegrityError in register_company: {e}")
            conn.rollback()
            return None
        except Exception as e:
            logger.error(f"register_company error: {e}")
            conn.rollback()
            return None

    def verify_login(self, folder_path, username, password):
        """
        Verify credentials for a specific company (identified by folder path).
        
        Returns:
            dict: User info if valid, else None.
        """
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        pass_hash = self._hash_password(password)
        
        conn = self.db.get_connection(DB_SECURITY)
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            
            # Join query to find user by Company Path + Username + Password
            cursor.execute("""
                SELECT u.id, u.username, u.role, c.display_name
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE c.folder_path = ? AND u.username = ? AND u.password_hash = ? AND u.is_active = 1
            """, (folder_path, username, pass_hash))
            
            row = cursor.fetchone()
            
            if row:
                return {
                    "user_id": row[0],
                    "username": row[1],
                    "role": row[2],
                    "company_name": row[3]
                }
            return None
        except Exception as e:
            logger.error(f"verify_login error: {e}")
            return None

    def get_users_for_company(self, folder_path):
        """List all users for a company."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        
        conn = self.db.get_connection(DB_SECURITY)
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.username, u.role 
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE c.folder_path = ?
            """, (folder_path,))
            return [{"username": r[0], "role": r[1]} for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_users_for_company error: {e}")
            return []

    def add_user(self, folder_path, username, password, role="user"):
        """Add a secondary user to an existing company."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        
        conn = self.db.get_connection(DB_SECURITY)
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (folder_path,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Company not found")
            
            company_id = row[0]
            pass_hash = self._hash_password(password)
            
            cursor.execute("""
                INSERT INTO users (company_id, username, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, (company_id, username, pass_hash, role))
            conn.commit()
            logger.info(f"User created: username='{username}', role='{role}', company_id={company_id}")
            return True
        except pyodbc.IntegrityError:
            logger.warning(f"User creation failed (duplicate): username='{username}'")
            conn.rollback()
            return False # User likely exists
        except Exception as e:
            logger.error(f"add_user error: {e}")
            conn.rollback()
            return False
