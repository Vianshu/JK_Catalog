"""
Security Manager — Authentication, Roles & Permissions (SQL Server).

Manages:
  - Company registration + admin user creation
  - User CRUD (create, list, deactivate, reset password)
  - Role CRUD (create, edit, delete, assign permissions)
  - Login verification with bcrypt + lockout
  - Permission resolution for UserSession
  - Audit logging

All data lives in the shared JK_Security database.
"""

import os
import json
import glob
import shutil
from datetime import datetime, timedelta
import bcrypt
import pyodbc
from src.logic.db_manager import (
    get_db_manager, DB_SECURITY, DB_SUPER, DB_CALENDAR, build_shared_db_name,
    build_logical_name, check_data_origin, save_data_origin
)
from src.logic.session import UserSession, DEFAULT_ROLES
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class SecurityManager:
    def __init__(self, data_path=""):
        self.data_path = data_path
        self.db = get_db_manager()
        self.is_copy = False
        self._original_path = ""
        
        has_valid_path = data_path and os.path.isdir(data_path)
        
        if has_valid_path:
            # Check if this data was copied from somewhere else
            origin = check_data_origin(data_path)
            self.is_copy = origin["is_copy"]
            self._original_path = origin.get("original_path", "")
            if self.is_copy:
                logger.info(f"Data copy detected! Original: {self._original_path} -> Current: {data_path}")
            
            # Path-aware shared DB names (isolated per data path)
            self._db_security = build_shared_db_name(DB_SECURITY, data_path)
            self._db_super = build_shared_db_name(DB_SUPER, data_path)
            self._db_calendar = build_shared_db_name(DB_CALENDAR, data_path)
            
            # NOTE: MDF migration and auto-registration are disabled.
            # Users must use the in-app Import/Export to move data.
            # self._migrate_mdf_files(data_path)
        else:
            self._db_security = DB_SECURITY
            self._db_super = DB_SUPER
            self._db_calendar = DB_CALENDAR
        
        self._init_schema()
        
        if has_valid_path:
            # self._auto_register_disk_companies()
            save_data_origin(data_path)

    # ═══════════════════════════════════════════════════════════════════════════
    # MDF FILE MIGRATION (for copied data folders)
    # ═══════════════════════════════════════════════════════════════════════════

    def _migrate_mdf_files(self, data_path):
        """Rename old-hash MDF/LDF files to match the new path hash.
        
        When a data folder is copied to a new location, the MDF/LDF files
        on disk still have the old path's hash in their filenames. SQL Server
        can't find them because it looks for the new hash. This renames them
        so the existing database (with all companies, users, roles) is preserved.
        
        NOTE: We do NOT detach the old-hash DB from SQL Server — that DB belongs
        to the original location. The copied MDF is just a file on disk.
        """

        
        # Map: (base_name, new_db_name) for each shared database
        shared_dbs = [
            (DB_SECURITY, self._db_security),
            (DB_SUPER, self._db_super),
            (DB_CALENDAR, self._db_calendar),
        ]
        
        for base_name, new_name in shared_dbs:
            new_mdf = os.path.join(data_path, f"{new_name}.mdf")
            
            if os.path.exists(new_mdf):
                continue  # New-hash file already exists, no migration needed
            
            # Look for old-hash MDF files: e.g., JK_Security_*.mdf
            pattern = os.path.join(data_path, f"{base_name}_*.mdf")
            old_mdfs = glob.glob(pattern)
            
            if not old_mdfs:
                continue  # No old files to migrate
            
            # Use the first match (there should only be one per base_name)
            old_mdf = old_mdfs[0]
            old_name = os.path.splitext(os.path.basename(old_mdf))[0]
            old_ldf = os.path.join(data_path, f"{old_name}_log.ldf")
            new_ldf = os.path.join(data_path, f"{new_name}_log.ldf")
            
            try:
                # Just rename the files — the old DB in SQL Server belongs
                # to the original location and must NOT be touched
                os.rename(old_mdf, new_mdf)
                logger.info(f"Renamed MDF: {os.path.basename(old_mdf)} -> {os.path.basename(new_mdf)}")
                
                if os.path.exists(old_ldf):
                    os.rename(old_ldf, new_ldf)
                    logger.info(f"Renamed LDF: {os.path.basename(old_ldf)} -> {os.path.basename(new_ldf)}")
                    
            except Exception as e:
                logger.error(f"MDF migration failed for {base_name}: {e}", exc_info=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # SCHEMA INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════════

    def _init_schema(self):
        """Create all security tables if they don't exist."""
        if not self.data_path or not os.path.isdir(self.data_path):
            logger.warning("SecurityManager: No valid data_path — skipping DB creation")
            return
        mdf_folder = self.data_path
        try:
            self.db.ensure_database_exists(self._db_security, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure security DB: {e}")
            return

        self.db.ensure_table(self._db_security, "companies", """
            CREATE TABLE companies (
                id INT IDENTITY(1,1) PRIMARY KEY,
                display_name NVARCHAR(255) NOT NULL,
                folder_path NVARCHAR(500) UNIQUE NOT NULL,
                image_path NVARCHAR(500),
                session_timeout_min INT DEFAULT 30,
                max_login_attempts INT DEFAULT 5,
                created_at DATETIME DEFAULT GETDATE()
            )
        """)

        self.db.ensure_table(self._db_security, "roles", """
            CREATE TABLE roles (
                id INT IDENTITY(1,1) PRIMARY KEY,
                company_id INT NOT NULL,
                role_name NVARCHAR(100) NOT NULL,
                description NVARCHAR(500),
                is_system BIT DEFAULT 0,
                created_at DATETIME DEFAULT GETDATE(),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, role_name)
            )
        """)

        self.db.ensure_table(self._db_security, "role_permissions", """
            CREATE TABLE role_permissions (
                id INT IDENTITY(1,1) PRIMARY KEY,
                role_id INT NOT NULL,
                permission_key NVARCHAR(100) NOT NULL,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE(role_id, permission_key)
            )
        """)

        self.db.ensure_table(self._db_security, "users", """
            CREATE TABLE users (
                id INT IDENTITY(1,1) PRIMARY KEY,
                company_id INT NOT NULL,
                username NVARCHAR(255) NOT NULL,
                password_hash NVARCHAR(255) NOT NULL,
                is_admin BIT DEFAULT 0,
                role_id INT NULL,
                is_active BIT DEFAULT 1,
                failed_attempts INT DEFAULT 0,
                locked_until DATETIME NULL,
                last_login_at DATETIME NULL,
                created_at DATETIME DEFAULT GETDATE(),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id),
                UNIQUE(company_id, username)
            )
        """)

        self.db.ensure_table(self._db_security, "audit_log", """
            CREATE TABLE audit_log (
                id BIGINT IDENTITY(1,1) PRIMARY KEY,
                timestamp DATETIME DEFAULT GETDATE(),
                user_id INT NULL,
                username NVARCHAR(255),
                company_id INT NULL,
                action NVARCHAR(50) NOT NULL,
                module NVARCHAR(50),
                detail NVARCHAR(MAX)
            )
        """)

        # Ensure shared databases exist
        try:
            self.db.ensure_database_exists(self._db_super, mdf_folder)
            self.db.ensure_database_exists(self._db_calendar, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure shared DBs: {e}")

    def _auto_register_disk_companies(self):
        """Fallback: register companies from disk if not already in the security DB.
        
        After MDF migration, the old data is normally preserved. This handles
        the edge case where no old MDF existed (fresh copy without prior DB)
        by scanning for company folders with company_info.json and registering
        them with default admin (empty username/password).
        """
        if not self.data_path or not os.path.isdir(self.data_path):
            return
        
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return
        
        try:
            cursor = conn.cursor()
            # Get all already-registered company display_names
            cursor.execute("SELECT display_name FROM companies")
            registered = {r[0] for r in cursor.fetchall()}
            
            # Scan disk for company folders
            registered_count = 0
            for d in os.listdir(self.data_path):
                full = os.path.join(self.data_path, d)
                if not os.path.isdir(full):
                    continue
                info_file = os.path.join(full, "company_info.json")
                if not os.path.exists(info_file):
                    continue
                
                try:

                    with open(info_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    display_name = data.get("display_name", d)
                    image_path = data.get("image_path", "")
                except Exception:
                    display_name = d
                    image_path = ""
                
                if display_name in registered:
                    continue  # Already registered
                
                # Register with empty admin credentials (default access)
                cid = self.register_company(
                    display_name=display_name,
                    folder_path=full,
                    image_path=image_path,
                    admin_user="",
                    admin_pass=""
                )
                if cid:
                    registered_count += 1
                    logger.info(f"Auto-registered company from disk: '{display_name}' (id={cid})")
            
            if registered_count > 0:
                logger.info(f"Auto-registered {registered_count} companies from disk")
                
        except Exception as e:
            logger.error(f"_auto_register_disk_companies error: {e}", exc_info=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # PASSWORD HASHING
    # ═══════════════════════════════════════════════════════════════════════════

    def _hash_password(self, password):
        """Hash password with bcrypt. Empty passwords are allowed."""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def _verify_password(self, password, stored_hash):
        """Verify password against bcrypt hash."""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # COMPANY MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    def register_company(self, display_name, folder_path, image_path, admin_user, admin_pass):
        """Register a new company with its admin user + default roles.

        If company exists (same path), updates details.
        Only updates admin credentials if admin_user and admin_pass are provided.
        Returns company_id on success, None on failure.
        """
        folder_path = os.path.normpath(os.path.abspath(folder_path))

        conn = self.db.get_connection(self._db_security)
        if not conn:
            logger.error("Cannot connect to Security DB")
            return None

        cursor = conn.cursor()
        try:
            # Check if company exists
            cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (folder_path,))
            row = cursor.fetchone()
            is_new_company = row is None

            if row:
                company_id = row[0]
                cursor.execute("""
                    UPDATE companies SET display_name = ?, image_path = ? WHERE id = ?
                """, (display_name, image_path, company_id))
            else:
                cursor.execute("""
                    INSERT INTO companies (display_name, folder_path, image_path)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?)
                """, (display_name, folder_path, image_path))
                company_id = int(cursor.fetchone()[0])

                # Create default roles for new company
                self._create_default_roles(cursor, company_id)

            # For NEW companies: always create admin (even with empty credentials)
            # For EXISTING companies: only update admin if credentials are provided
            if is_new_company or (admin_user or admin_pass):
                pass_hash = self._hash_password(admin_pass)
                cursor.execute("SELECT id FROM users WHERE company_id = ? AND is_admin = 1", (company_id,))
                admin_row = cursor.fetchone()

                if admin_row:
                    cursor.execute("""
                        UPDATE users SET username = ?, password_hash = ? WHERE id = ?
                    """, (admin_user, pass_hash, admin_row[0]))
                else:
                    # Get Full Access role for this company
                    cursor.execute("""
                        SELECT id FROM roles WHERE company_id = ? AND role_name = 'Full Access'
                    """, (company_id,))
                    fa_row = cursor.fetchone()
                    fa_role_id = fa_row[0] if fa_row else None

                    cursor.execute("""
                        INSERT INTO users (company_id, username, password_hash, is_admin, role_id)
                        VALUES (?, ?, ?, 1, ?)
                    """, (company_id, admin_user, pass_hash, fa_role_id))

            conn.commit()
            logger.info(f"Company registered: id={company_id}, name='{display_name}'")
            return company_id

        except pyodbc.IntegrityError as e:
            logger.warning(f"IntegrityError in register_company: {e}")
            conn.rollback()
            return None
        except Exception as e:
            logger.error(f"register_company error: {e}", exc_info=True)
            conn.rollback()
            return None

    def _create_default_roles(self, cursor, company_id):
        """Create default roles and their permissions for a new company."""
        for role_name, role_def in DEFAULT_ROLES.items():
            try:
                cursor.execute("""
                    INSERT INTO roles (company_id, role_name, description, is_system)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?)
                """, (company_id, role_name, role_def["description"],
                      1 if role_def["is_system"] else 0))
                role_id = int(cursor.fetchone()[0])

                for perm_key in role_def["permissions"]:
                    cursor.execute("""
                        INSERT INTO role_permissions (role_id, permission_key) VALUES (?, ?)
                    """, (role_id, perm_key))
            except pyodbc.IntegrityError:
                pass  # Role already exists

    def get_company_id_by_path(self, folder_path):
        """Look up company ID by its folder path.
        
        Centralised helper — replaces duplicated _get_company_id() in dialogs.
        Returns company_id (int) or None.
        """
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            fp = os.path.normpath(os.path.abspath(folder_path))
            cursor.execute("SELECT id FROM companies WHERE folder_path = ?", (fp,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def get_company_id_by_name(self, display_name):
        """Look up company ID by display name.
        
        Company names are unique within a data path. Used as the primary
        lookup for login (survives folder copy/move).
        Returns company_id (int) or None.
        """
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM companies WHERE display_name = ?", (display_name,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # LIVE PERMISSION REFRESH
    # ═══════════════════════════════════════════════════════════════════════════

    def refresh_session_permissions(self, session):
        """Re-read a user's role & permissions from SQL and update the session in-place.

        Called periodically (every 60s) by MainWindow to pick up admin changes
        without requiring re-login.

        Returns True if permissions actually changed, False otherwise.
        """
        if not session or session.is_admin:
            return False  # Admins bypass everything, nothing to refresh

        conn = self.db.get_connection(self._db_security)
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.role_id, u.is_active, r.role_name
                FROM users u
                LEFT JOIN roles r ON u.role_id = r.id
                WHERE u.id = ?
            """, (session.user_id,))
            row = cursor.fetchone()

            if not row:
                return False

            role_id, is_active, role_name = row

            # If user was deactivated, signal a forced logout
            if not is_active:
                session.permissions = set()
                session.role_name = "Deactivated"
                return True

            # Fetch current permissions for the role
            new_perms = set()
            if role_id:
                cursor.execute(
                    "SELECT permission_key FROM role_permissions WHERE role_id = ?",
                    (role_id,))
                new_perms = {r[0] for r in cursor.fetchall()}

            # Compare with existing session
            old_perms = session.permissions
            old_role = session.role_name

            if new_perms != old_perms or role_name != old_role:
                session.permissions = new_perms
                session.role_name = role_name or "No Role"
                logger.info(f"Permissions refreshed for '{session.username}': "
                            f"role='{session.role_name}', perms={len(new_perms)}")
                return True

            return False

        except Exception as e:
            logger.error(f"refresh_session_permissions error: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # LOGIN & SESSION
    # ═══════════════════════════════════════════════════════════════════════════

    def verify_login(self, folder_path, username, password, company_name=None):
        """Verify credentials and return a UserSession on success.

        Handles: bcrypt verification, lockout check, failed attempt tracking.
        
        Lookup strategy:
          1. Find company by display_name (unique within the data path)
          2. Fallback: find company by folder_path
          3. Then verify user within that company
        
        This design survives folder copy/move since display_name is portable.
        Returns UserSession on success, None on failure.
        """
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            
            # Step 1: Resolve company_id
            company_id = None
            
            # Primary: lookup by display_name (portable, survives copy/move)
            if company_name:
                cursor.execute("SELECT id FROM companies WHERE display_name = ?",
                               (company_name,))
                crow = cursor.fetchone()
                if crow:
                    company_id = crow[0]
            
            # Fallback: lookup by folder_path
            if company_id is None and folder_path:
                norm_path = os.path.normpath(os.path.abspath(folder_path))
                cursor.execute("SELECT id FROM companies WHERE folder_path = ?",
                               (norm_path,))
                crow = cursor.fetchone()
                if crow:
                    company_id = crow[0]
            
            if company_id is None:
                self._log_audit(cursor, None, username, None, "failed_login",
                                detail=f"Company not found: {company_name or folder_path}")
                conn.commit()
                return None
            
            # Step 2: Find the user within this company
            cursor.execute("""
                SELECT u.id, u.username, u.password_hash, u.is_admin, u.role_id,
                       u.failed_attempts, u.locked_until,
                       c.id AS company_id, c.display_name, c.max_login_attempts
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE u.company_id = ? AND u.username = ? AND u.is_active = 1
            """, (company_id, username))
            row = cursor.fetchone()
            
            if not row:
                self._log_audit(cursor, None, username, company_id, "failed_login",
                                detail=f"User not found: {username}")
                conn.commit()
                return None

            (user_id, db_username, stored_hash, is_admin, role_id,
             failed_attempts, locked_until, company_id, company_name_db,
             max_attempts) = row

            # Check lockout
            if locked_until and datetime.now() < locked_until:
                remaining = (locked_until - datetime.now()).seconds // 60
                logger.warning(f"Account locked: {username}, {remaining}min remaining")
                return None

            # Verify password
            if not self._verify_password(password, stored_hash):
                new_failures = (failed_attempts or 0) + 1
                lock_time = None
                if new_failures >= (max_attempts or 5):
                    lock_time = datetime.now() + timedelta(minutes=15)
                    logger.warning(f"Account locked due to {new_failures} failed attempts: {username}")

                cursor.execute("""
                    UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?
                """, (new_failures, lock_time, user_id))

                self._log_audit(cursor, user_id, username, company_id,
                                "failed_login", detail=f"Attempt #{new_failures}")
                conn.commit()
                return None

            # Success — reset failures, update last_login
            cursor.execute("""
                UPDATE users SET failed_attempts = 0, locked_until = NULL,
                                 last_login_at = GETDATE() WHERE id = ?
            """, (user_id,))

            # Resolve permissions
            permissions = set()
            role_name = None
            if role_id:
                cursor.execute("SELECT role_name FROM roles WHERE id = ?", (role_id,))
                rn = cursor.fetchone()
                role_name = rn[0] if rn else None

                cursor.execute("""
                    SELECT permission_key FROM role_permissions WHERE role_id = ?
                """, (role_id,))
                permissions = {r[0] for r in cursor.fetchall()}

            self._log_audit(cursor, user_id, username, company_id, "login")
            conn.commit()

            session = UserSession(
                user_id=user_id, username=db_username,
                is_admin=bool(is_admin), company_id=company_id,
                company_name=company_name_db, company_path=folder_path,
                role_name=role_name, permissions=permissions,
            )
            logger.info(f"Login successful: {session}")
            return session

        except Exception as e:
            logger.error(f"verify_login error: {e}", exc_info=True)
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # USER MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    def add_user(self, folder_path, username, password, role_id=None):
        """Add a user to a company. Returns True on success."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        conn = self.db.get_connection(self._db_security)
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
                INSERT INTO users (company_id, username, password_hash, is_admin, role_id)
                VALUES (?, ?, ?, 0, ?)
            """, (company_id, username, pass_hash, role_id))
            conn.commit()
            logger.info(f"User created: '{username}', company_id={company_id}")
            return True
        except pyodbc.IntegrityError:
            logger.warning(f"User already exists: '{username}'")
            conn.rollback()
            return False
        except Exception as e:
            logger.error(f"add_user error: {e}")
            conn.rollback()
            return False

    def get_users_for_company(self, folder_path):
        """List all users for a company with role info."""
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.is_admin, u.is_active,
                       r.role_name, u.last_login_at
                FROM users u
                JOIN companies c ON u.company_id = c.id
                LEFT JOIN roles r ON u.role_id = r.id
                WHERE c.folder_path = ?
                ORDER BY u.is_admin DESC, u.username
            """, (folder_path,))
            return [{
                "id": r[0], "username": r[1], "is_admin": bool(r[2]),
                "is_active": bool(r[3]), "role_name": r[4] or "No Role",
                "last_login": r[5],
            } for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_users_for_company error: {e}")
            return []

    def update_user(self, user_id, username=None, password=None, role_id=None, is_active=None):
        """Update user fields. Only non-None values are changed."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            updates, params = [], []
            if username is not None:
                updates.append("username = ?"); params.append(username)
            if password is not None:
                updates.append("password_hash = ?"); params.append(self._hash_password(password))
            if role_id is not None:
                updates.append("role_id = ?"); params.append(role_id)
            if is_active is not None:
                updates.append("is_active = ?"); params.append(1 if is_active else 0)
            if not updates:
                return True
            params.append(user_id)
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_user error: {e}")
            conn.rollback()
            return False

    def delete_user(self, user_id):
        """Delete a user (cannot delete admins)."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row and row[0]:
                logger.warning("Cannot delete admin user")
                return False
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"delete_user error: {e}")
            conn.rollback()
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # ROLE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    def get_roles_for_company(self, company_id):
        """Get all roles for a company."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, role_name, description, is_system FROM roles
                WHERE company_id = ? ORDER BY is_system DESC, role_name
            """, (company_id,))
            return [{
                "id": r[0], "role_name": r[1],
                "description": r[2], "is_system": bool(r[3]),
            } for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_roles error: {e}")
            return []

    def create_role(self, company_id, role_name, description, permission_keys):
        """Create a custom role with permissions. Returns role_id."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO roles (company_id, role_name, description)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?)
            """, (company_id, role_name, description))
            role_id = int(cursor.fetchone()[0])

            for key in permission_keys:
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, permission_key) VALUES (?, ?)
                """, (role_id, key))

            conn.commit()
            logger.info(f"Role created: '{role_name}' with {len(permission_keys)} permissions")
            return role_id
        except pyodbc.IntegrityError:
            conn.rollback()
            return None
        except Exception as e:
            logger.error(f"create_role error: {e}")
            conn.rollback()
            return None

    def update_role(self, role_id, role_name=None, description=None, permission_keys=None):
        """Update role name/description and/or replace permissions."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            if role_name is not None or description is not None:
                updates, params = [], []
                if role_name:
                    updates.append("role_name = ?"); params.append(role_name)
                if description is not None:
                    updates.append("description = ?"); params.append(description)
                params.append(role_id)
                cursor.execute(f"UPDATE roles SET {', '.join(updates)} WHERE id = ?", params)

            if permission_keys is not None:
                cursor.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
                for key in permission_keys:
                    cursor.execute("""
                        INSERT INTO role_permissions (role_id, permission_key) VALUES (?, ?)
                    """, (role_id, key))

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_role error: {e}")
            conn.rollback()
            return False

    def delete_role(self, role_id):
        """Delete a role (cannot delete system roles)."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT is_system FROM roles WHERE id = ?", (role_id,))
            row = cursor.fetchone()
            if row and row[0]:
                return False  # Cannot delete system role
            # Unassign users from this role first
            cursor.execute("UPDATE users SET role_id = NULL WHERE role_id = ?", (role_id,))
            cursor.execute("DELETE FROM roles WHERE id = ?", (role_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"delete_role error: {e}")
            conn.rollback()
            return False

    def get_role_permissions(self, role_id):
        """Get permission keys for a role."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return set()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT permission_key FROM role_permissions WHERE role_id = ?", (role_id,))
            return {r[0] for r in cursor.fetchall()}
        except Exception as e:
            logger.error(f"get_role_permissions error: {e}")
            return set()

    # ═══════════════════════════════════════════════════════════════════════════
    # AUDIT LOGGING
    # ═══════════════════════════════════════════════════════════════════════════

    def _log_audit(self, cursor, user_id, username, company_id, action,
                   module=None, detail=None):
        """Write an audit log entry.
        
        NOTE: Does NOT commit — the caller is responsible for committing.
        This prevents mid-transaction commits from flushing unrelated changes.
        """
        try:
            cursor.execute("""
                INSERT INTO audit_log (user_id, username, company_id, action, module, detail)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, company_id, action, module, detail))
        except Exception:
            pass  # Audit logging must never crash the app

    def log_action(self, session, action, module=None, detail=None):
        """Public audit logger — used by UI code after login."""
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return
        try:
            cursor = conn.cursor()
            self._log_audit(cursor, session.user_id, session.username,
                            session.company_id, action, module, detail)
            conn.commit()
        except Exception:
            pass

    # ─── SUPER ADMIN ─────────────────────────────────────────────────────────

    @staticmethod
    def _admin_config_path():
        """Path to the super admin config file (next to the EXE)."""
        from src.utils.path_utils import get_exe_dir
        return os.path.join(get_exe_dir(), "config", "admin.json")

    @staticmethod
    def super_admin_exists():
        """Check if a super admin has been configured."""
        path = SecurityManager._admin_config_path()
        return os.path.exists(path)

    @staticmethod
    def setup_super_admin(username, password):
        """Create the super admin account (first-time setup).
        
        Stored in config/admin.json next to the EXE, NOT in SQL Server.
        This ensures it works regardless of which data path is active.
        """
        path = SecurityManager._admin_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        pass_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        data = {
            "username": username,
            "password_hash": pass_hash.decode('utf-8')
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Super admin created: '{username}'")

    @staticmethod
    def verify_super_admin(username, password):
        """Verify super admin credentials.
        
        Returns:
            bool: True if credentials match.
        """
        path = SecurityManager._admin_config_path()
        if not os.path.exists(path):
            return False
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if data.get('username', '') != username:
                return False
            
            stored_hash = data.get('password_hash', '')
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception as e:
            logger.error(f"Super admin verification failed: {e}")
            return False

    # ─── DELETE OPERATIONS ────────────────────────────────────────────────────

    def delete_company(self, folder_path):
        """Safely delete a company: drop DB → remove from Security → delete folder.
        
        Args:
            folder_path: Absolute path to the company folder.
        
        Returns:
            tuple: (success: bool, message: str)
        """
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        
        try:
            # 1. Get company info from Security DB
            company_id = self.get_company_id_by_path(folder_path)
            
            # 2. Drop the company's SQL Server database
            logical_name = build_logical_name(company_path=folder_path)
            if self.db.database_exists(logical_name):
                self.db.drop_database(logical_name)
                logger.info(f"Dropped company DB: {logical_name}")
            
            # 3. Delete from Security DB (users, roles, permissions, company)
            if company_id:
                conn = self.db.get_connection(self._db_security)
                if conn:
                    cursor = conn.cursor()
                    # audit_log has no CASCADE, delete manually
                    cursor.execute("DELETE FROM audit_log WHERE company_id = ?", (company_id,))
                    # companies → roles, users, role_permissions all have ON DELETE CASCADE
                    cursor.execute("DELETE FROM companies WHERE id = ?", (company_id,))
                    conn.commit()
                    logger.info(f"Removed company from Security DB: id={company_id}")
            
            # 4. Delete the company folder from disk
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path, ignore_errors=True)
                logger.info(f"Deleted company folder: {folder_path}")
            
            return True, f"Company deleted successfully."
        
        except Exception as e:
            logger.error(f"delete_company failed for '{folder_path}': {e}")
            return False, f"Error: {e}"

    def delete_data_path(self, data_path):
        """Delete ALL databases and folders for a data path.
        
        This is a destructive operation that removes:
        - All company databases
        - All shared databases (Security, SuperMaster, Calendar)
        - The entire data path folder
        
        Args:
            data_path: Root data path to delete.
        
        Returns:
            tuple: (success: bool, message: str)
        """
        data_path = os.path.normpath(os.path.abspath(data_path))
        errors = []
        
        try:
            # 1. Drop all company databases
            if os.path.isdir(data_path):
                for entry in os.listdir(data_path):
                    company_path = os.path.join(data_path, entry)
                    if os.path.isdir(company_path):
                        logical_name = build_logical_name(company_path=company_path)
                        if self.db.database_exists(logical_name):
                            if not self.db.drop_database(logical_name):
                                errors.append(f"Failed to drop: {logical_name}")
            
            # 2. Drop shared databases (Security, SuperMaster, Calendar)
            for base in [DB_SECURITY, DB_SUPER, DB_CALENDAR]:
                shared_name = build_shared_db_name(base, data_path)
                if self.db.database_exists(shared_name):
                    if not self.db.drop_database(shared_name):
                        errors.append(f"Failed to drop: {shared_name}")
            
            # 3. Delete the entire data path folder
            if os.path.exists(data_path):
                shutil.rmtree(data_path, ignore_errors=True)
                logger.info(f"Deleted data path folder: {data_path}")
            
            if errors:
                return False, f"Partial deletion. Errors: {'; '.join(errors)}"
            
            return True, "Data path deleted successfully."
        
        except Exception as e:
            logger.error(f"delete_data_path failed for '{data_path}': {e}")
            return False, f"Error: {e}"

    def get_companies_list(self):
        """Get all companies for the current data path.
        
        Returns:
            list of dicts: [{id, display_name, folder_path, image_path}, ...]
        """
        conn = self.db.get_connection(self._db_security)
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, display_name, folder_path, image_path FROM companies ORDER BY display_name")
            rows = cursor.fetchall()
            return [
                {"id": r[0], "display_name": r[1], "folder_path": r[2], "image_path": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"get_companies_list failed: {e}")
            return []
