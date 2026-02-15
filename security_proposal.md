# Security & Authentication Overhaul Proposal

## Current State
Currently, the application stores sensitive information in plain text JSON files:
1. **`company_info.json`** (inside each company folder): Stores the company's admin username and password in plain text.
2. **`users_data.json`** (in the app root): Stores additional users and their roles for each company, also in plain text.
3. **`crm_data.json`**, **`company_history.json`**: Store paths and names without centralized validation.

### Risks
*   **Security Risk**: Passwords are visible to anyone who opens the JSON files.
*   **Data Integrity**: JSON files can be easily edited or corrupted by users, leading to broken logins.
*   **Scalability**: Managing users across multiple files is difficult and error-prone.

---

## Proposed Solution: Centralized SQLite Security Database (`security.db`)

We propose moving all authentication and company configuration to a secure, centralized SQLite database.

### 1. Database Location
The database `security.db` will be stored in the application's root directory (next to the EXE), ensuring it persists and can be backed up easily.
*   **Path**: `get_app_dir() + "/security.db"`

### 2. Database Schema

#### A. Table: `companies`
Stores the registry of all known companies. This replaces `company_history.json` and part of `company_info.json`.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER PK | Auto-increment ID |
| `display_name` | TEXT | The name shown in the login list |
| `folder_path` | TEXT | Absolute path to the company data folder (Unique) |
| `image_path` | TEXT | Path to the company's product images |
| `created_at` | DATETIME | Timestamp of creation |

#### B. Table: `users`
Stores all users (Admin and Staff) for all companies. **Passwords will be HASHED.**

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | INTEGER PK | Auto-increment ID |
| `company_id` | INTEGER FK | Links to `companies.id` |
| `username` | TEXT | Username (e.g., "admin", "sales") |
| `password_hash` | TEXT | **SHA-256 Hash** of the password (Salted) |
| `role` | TEXT | Role name (e.g., "Admin", "User", "Viewer") |
| `is_active` | BOOLEAN | To enable/disable users without deleting |

#### C. Table: `security_levels` (Optional/Future)
Can replace the hardcoded roles logic in `settings.py` to allow dynamic permission sets.

---

## Key Changes in Workflow

### 1. Creating a New Company
*   **Old**: Creates folder -> Writes `company_info.json` with plain password.
*   **New**: 
    1. Creates folder.
    2. Inserts record into `companies` table in `security.db`.
    3. Hashes the admin password.
    4. Inserts "Admin" user into `users` table linked to the new company.

### 2. Login Process
*   **Old**: Reads `company_info.json` -> Checks `if input == json_password`.
*   **New**: 
    1. User selects Company.
    2. System queries `users` table for that `company_id`.
    3. Hashes the input password and compares it with the stored `password_hash`.
    4. **Result**: Zero plain-text passwords in the system.

### 3. User Management (Settings)
*   **Old**: Reads/Writes `users_data.json`.
*   **New**: 
    1. Admin opens User Manager.
    2. App queries `users` table for current company.
    3. Admin adds/removes users -> Updates DB directly.

---

## Implementation Plan
1.  **Create `src/logic/security_manager.py`**:
    *   Handles DB connection (`security.db`).
    *   Functions: `create_company()`, `verify_user(user, pass)`, `add_user()`, `list_companies()`.
    *   Includes hashing utility `hash_password(text)`.
2.  **Update `company_login_ui.py`**:
    *   Replace JSON reading/writing with calls to `security_manager`.
3.  **Update `settings.py`**:
    *   Redirect user management to use `security_manager`.
4.  **Migration Script (One-time)**:
    *   Run once to read existing `company_history.json` and `users_data.json`.
    *   Insert them into the new `security.db` with simple hashing.

## Benefits
*   ✅ **Secure**: No plain text passwords.
*   ✅ **Robust**: SQLite is ACID compliant; less chance of corruption than JSON.
*   ✅ **Clean**: Centralizes all "Meta" data (Users, Companies, Paths) in one place.
