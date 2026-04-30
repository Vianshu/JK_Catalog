import sqlite3
import hashlib
import os
from datetime import datetime
import hmac
import ctypes
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

APP_SECRET = b"JK_Catalog_v2_secure_key"  # compiled into the EXE
    
class SecurityManager:
    def __init__(self, db_path):
        """
        Initialize SecurityManager with the path to the security database.
        
        Args:
            db_path (str): Absolute path to security.db
        """
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize the database tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            # Hide the DB file from Windows File Explorer
            try:
                # FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(self.db_path, 0x02)
            except Exception:
                pass
            
            cursor = conn.cursor()
            
            # 1. Companies Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    folder_path TEXT UNIQUE NOT NULL,
                    image_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. Users Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, username)
                )
            """)
            
            conn.commit()

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
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                # 1. Try Insert Company
                cursor.execute("""
                    INSERT INTO companies (display_name, folder_path, image_path)
                    VALUES (?, ?, ?)
                """, (display_name, folder_path, image_path))
                company_id = cursor.lastrowid
                
            except sqlite3.IntegrityError:
                # Company already exists -> Get ID and Update details
                cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (folder_path,))
                row = cursor.fetchone()
                if not row: return None # Should not happen
                company_id = row[0]
                
                # Update Company Details
                cursor.execute("""
                    UPDATE companies 
                    SET display_name = ?, image_path = ?
                    WHERE id = ?
                """, (display_name, image_path, company_id))

            # 2. Upsert Admin User (Ensure Admin exists and has new password)
            # Check if admin exists for this company
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

    def verify_login(self, folder_path, username, password):
        """
        Verify credentials for a specific company (identified by folder path).
        
        Returns:
            dict: User info if valid, else None.
        """
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        pass_hash = self._hash_password(password)
        
        with sqlite3.connect(self.db_path) as conn:
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

    def get_users_for_company(self, folder_path):
        """List all users for a company."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.username, u.role 
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE c.folder_path = ?
            """, (folder_path,))
            return [{"username": r[0], "role": r[1]} for r in cursor.fetchall()]

    def add_user(self, folder_path, username, password, role="user"):
        """Add a secondary user to an existing company."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        
        # First, find the company ID
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (folder_path,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Company not found")
            
            company_id = row[0]
            pass_hash = self._hash_password(password)
            
            try:
                cursor.execute("""
                    INSERT INTO users (company_id, username, password_hash, role)
                    VALUES (?, ?, ?, ?)
                """, (company_id, username, pass_hash, role))
                conn.commit()
                logger.info(f"User created: username='{username}', role='{role}', company_id={company_id}")
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"User creation failed (duplicate): username='{username}', company_id={company_id}")
                return False # User likely exists
