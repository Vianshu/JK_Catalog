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
from datetime import datetime, timedelta
import bcrypt
import pyodbc
from src.logic.db_manager import get_db_manager, DB_SECURITY, DB_SUPER, DB_CALENDAR
from src.logic.session import UserSession, DEFAULT_ROLES
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class SecurityManager:
    def __init__(self, data_path=""):
        self.data_path = data_path
        self.db = get_db_manager()
        self._init_schema()

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
            self.db.ensure_database_exists(DB_SECURITY, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure security DB: {e}")
            return

        self.db.ensure_table(DB_SECURITY, "companies", """
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

        self.db.ensure_table(DB_SECURITY, "roles", """
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

        self.db.ensure_table(DB_SECURITY, "role_permissions", """
            CREATE TABLE role_permissions (
                id INT IDENTITY(1,1) PRIMARY KEY,
                role_id INT NOT NULL,
                permission_key NVARCHAR(100) NOT NULL,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE(role_id, permission_key)
            )
        """)

        self.db.ensure_table(DB_SECURITY, "users", """
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

        self.db.ensure_table(DB_SECURITY, "audit_log", """
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
            self.db.ensure_database_exists(DB_SUPER, mdf_folder)
            self.db.ensure_database_exists(DB_CALENDAR, mdf_folder)
        except Exception as e:
            logger.warning(f"Could not ensure shared DBs: {e}")

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

        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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

        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
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
        conn = self.db.get_connection(DB_SECURITY)
        if not conn:
            return
        try:
            cursor = conn.cursor()
            self._log_audit(cursor, session.user_id, session.username,
                            session.company_id, action, module, detail)
            conn.commit()
        except Exception:
            pass
