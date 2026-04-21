# JK Catalog — Developer Documentation

---

## Table of Contents

**Foundation**
1. [Project Structure](#1-project-structure)
2. [Technology Stack & Dependencies](#2-technology-stack-dependencies)
3. [Environment & Path Resolution](#3-environment-path-resolution)
4. [Configuration Files](#4-configuration-files)
5. [Build & Packaging](#5-build-packaging)

**Data Layer**
6. [Data Models & Schema](#6-data-models-schema)
7. [Column Constants](#7-column-constants)

**Application Core**
8. [Application Entry Point & Crash Handling](#8-application-entry-point-crash-handling)
9. [Logging Architecture](#9-logging-architecture)
10. [Security & Authorization](#10-security-authorization)
11. [Session Management](#11-session-management)

**UI Layer**
12. [UI Architecture](#12-ui-architecture)
13. [Company Login & Selection](#13-company-login-selection)
14. [Full Catalog UI](#14-full-catalog-ui)
15. [A4 Page Renderer](#15-a4-page-renderer)
16. [Print & PDF Export Pipeline](#16-print-pdf-export-pipeline)
17. [Reports Pipeline](#17-reports-pipeline)

**Data Pipelines**
18. [Tally Sync Pipeline](#18-tally-sync-pipeline)
19. [Data Processing Pipeline](#19-data-processing-pipeline)
20. [Final Data Sync Pipeline](#20-final-data-sync-pipeline)
21. [Date Conversion Pipeline](#21-date-conversion-pipeline)

**Catalog Engine**
22. [Catalog Engine](#22-catalog-engine)
23. [Layout Engine — Grid Placement](#23-layout-engine-grid-placement)
24. [Change Detection — Snapshot System](#24-change-detection-snapshot-system)
25. [CRM & Dirty Page Tracking](#25-crm-dirty-page-tracking)
26. [Serial Shift Handling](#26-serial-shift-handling)

**Reference**
27. [Key Invariants & Edge Cases](#27-key-invariants-edge-cases)

---

## 1. Project Structure

```
backup code/
├── main.py                         # Application entry point
├── JK_Catalog.spec                 # PyInstaller build spec
├── config/
│   ├── catalog_config.json         # Per-company layout overrides
│   └── cleaning_rules.json         # Regex patterns for product normalization
├── src/
│   ├── logic/
│   │   ├── catalog_logic.py        # Core engine (2251 lines) — layout, change detection, CRM
│   │   ├── data_processor.py       # Regex-based product name/size extraction
│   │   ├── text_utils.py           # Fuzzy similarity matching and clustering
│   │   ├── security_manager.py     # RBAC, SHA-256 hashing, company registration
│   │   ├── session_manager.py      # Declarative page initialization on login
│   │   └── column_constants.py     # Named column indices for final_data table
│   ├── ui/
│   │   ├── main_window.py          # Root window, sidebar menus, navigation
│   │   ├── company_login_ui.py     # Company selection, creation, login dialog
│   │   ├── full_catalog.py         # Catalog viewer, builder, page management
│   │   ├── final_data.py           # Final data table, cell editing, sync worker
│   │   ├── reports.py              # CRM performance reports, print/PDF flow
│   │   ├── print_export.py         # Unified print preview & PDF export dialog
│   │   ├── a4_renderer.py          # A4 page widget for rendering catalog pages
│   │   ├── settings.py             # CRM/User/Security dialogs, JSON helpers
│   │   ├── welcome.py              # Welcome splash label
│   │   ├── row_data.py             # Raw Tally data viewer
│   │   ├── super_master.py         # Super master editor
│   │   ├── ledger_row_data.py      # Ledger data viewer
│   │   ├── cheque_list.py          # Cheque list management
│   │   ├── calendar_mapping.py     # AD-to-BS date mapping editor
│   │   ├── group_test_tab.py       # Group testing/preview
│   │   ├── catalog_price_list.py   # Catalog price list dialog
│   │   ├── price_list.py           # Price list viewer
│   │   ├── payment_list.py         # Payment list viewer
│   │   ├── godown_list.py          # Godown list viewer
│   │   ├── sales_chat.py           # Sales chat viewer
│   │   ├── supp_payment.py         # Supplier payment viewer
│   │   ├── pur_import.py           # Purchase import dialog
│   │   ├── int_cost_sheet.py       # Internal cost sheet dialog
│   │   └── vat_pages.py            # Balance and stock VAT views
│   ├── services/
│   │   └── tally_sync.py           # ODBC connection to Tally ERP
│   └── utils/
│       ├── path_utils.py           # Bundled vs. writable path resolution
│       ├── app_logger.py           # Centralized logger factory
│       └── date_utils.py           # Footer date calculation, AD→BS conversion
├── assets/
│   └── style.qss                   # Global Qt stylesheet
└── resources/
    ├── splash.png                  # PyInstaller splash screen image
    └── icon.ico                    # Application icon
```

---

## 2. Technology Stack & Dependencies

| Component | Technology | Why |
|---|---|---|
| GUI Framework | PyQt6 | Desktop UI. We force the `Fusion` style so it looks the same on every Windows version. |
| Data Processing | pandas | Only used in `tally_sync.py` to handle ODBC result sets. Everything else talks to SQLite directly. |
| Database (Local) | SQLite | One DB file per company. WAL journal mode is turned on for every connection so reads don't block writes. |
| Database (ERP) | ODBC via pyodbc | Talks to Tally Prime's ODBC driver to pull stock items and ledger data. |
| Excel Export | openpyxl | Price list and cost sheet dialogs use this for `.xlsx` export. |
| Packaging | PyInstaller | Bundles everything into a single `.exe`. Bundled assets land in a temp `_MEIPASS` folder at runtime. |
| Hashing | hashlib (MD5) | MD5 for page change detection, SHA-256 for passwords in `security_manager.py`. |

---

## 3. Environment & Path Resolution

**File**: `src/utils/path_utils.py` (118 lines)

The app runs in two very different modes, and paths work differently in each:

### 3.1 Script Mode (Development)

Running as `python main.py`:
- `sys.frozen` isn't set.
- `get_base_dir()` gives you the folder where `main.py` lives.
- Everything resolves relative to the project root.

### 3.2 Frozen Mode (PyInstaller `.exe`)

Running as a compiled executable:
- `sys.frozen` is `True`.
- `sys._MEIPASS` points to a temp folder where PyInstaller extracted the bundled files. This folder is **read-only**.
- `get_base_dir()` returns `sys._MEIPASS`.

### 3.3 Path Functions

| Function | Returns | What it's for |
|---|---|---|
| `get_base_dir()` | `sys._MEIPASS` or script directory | Where bundled assets live (config files, QSS, splash image). Read-only in frozen mode. |
| `get_app_dir()` | `%APPDATA%/JK_Catalog` | Writable folder for user settings (`config.json`, `company_history.json`). Auto-created on first call. |
| `get_secure_data_dir()` | `%APPDATA%/JK_Catalog/secure` | Writable folder for `security.db`. Kept in its own subfolder to keep credentials separate. |
| `get_data_file_path(filename)` | Full path to `filename` | Checks `get_app_dir()` first for a writable copy, falls back to `get_base_dir()` for the bundled read-only version. |
| `get_writable_data_path(filename)` | `get_app_dir()/filename` | Always gives you the writable path, even if the file doesn't exist yet. Used when you need to create something new. |

### 3.4 Why Some Files Live in `%APPDATA%`

Anything bundled inside `_MEIPASS` gets **deleted** when the app closes. So:
- `security.db` has to live in `%APPDATA%` — otherwise all user accounts would vanish on every restart.
- `calendar_data.db` loads through `get_data_file_path()`, which checks `%APPDATA%` first, then falls back to the bundled copy. That way users can override the default calendar if they need to.
- `config.json` (the user's selected data path) also lives in `%APPDATA%`.

---

## 4. Configuration Files

### 4.1 `config/catalog_config.json`

```json
{
    "page_layout": {
        "rows_per_page": 5,
        "cols_per_page": 4,
        "image_column_width": 1,
        "data_column_width": 1
    },
    "header": {
        "show_company_prefix": true,
        "show_serial_number": true,
        "show_group_name": true
    },
    "footer": {
        "show_crm_name": true,
        "show_date": true,
        "date_format": "nepali"
    }
}
```

Per-company layout overrides. Used by the A4 renderer to customize page appearance.

### 4.2 `config/cleaning_rules.json`

```json
{
    "cleaning_patterns": [
        {"pattern": "\\bW/O\\s*PEDESTAL\\b", "replacement": ""},
        {"pattern": "\\bSET\\s*OF\\s*\\d+\\b", "replacement": ""},
        ...
    ],
    "similarity_threshold": 0.75
}
```

The `similarity_threshold` controls how aggressively products get clustered - 0.75 means names need to be 75% similar. Lower values create bigger clusters.

### 4.3 `%APPDATA%/JK_Catalog/config.json`

```json
{
    "default_path": "C:\\Data"
}
```

Stores the user's selected data directory path. Changed via "Change Data Path" in the company selection screen.

### 4.4 `%APPDATA%/JK_Catalog/company_history.json`

```json
["C:\\Data\\Company_A", "C:\\Data\\Company_B"]
```

List of company folder paths that have been logged into. Used for "Recent Companies" functionality.

---

## 5. Build & Packaging

**File**: `JK_Catalog.spec`

### 5.1 PyInstaller Configuration

```python
a = Analysis(
    ['main.py'],
    pathex=[],
    datas=[
        ('config', 'config'),    # Bundled config files
        ('assets', 'assets'),    # QSS, icons
        ('resources', 'resources'), # Splash image
    ],
    hiddenimports=['pyodbc'],   # ODBC driver not auto-detected
    excludes=['matplotlib', 'numpy', 'scipy'], # Reduce bundle size
)
```

### 5.2 Splash Screen

```python
splash = Splash(
    'resources/splash.png',
    binaries=a.binaries,
    datas=a.datas,
)
```

Uses `pyi_splash` to show a splash image during the initial extraction phase. Closed after `MainWindow` is shown via `pyi_splash.close()`.

### 5.3 Build Command

```bash
pyinstaller JK_Catalog.spec --noconfirm
```

Output: `dist/JK_Catalog/JK_Catalog.exe` (single-directory mode, not one-file).

---

## 6. Data Models & Schema

### 6.1 `super_master.db` — Group Hierarchy (Shared)

**Location**: Parent directory of the company folder (e.g., `C:\Data\super_master.db`).
**Shared by**: All companies under the same parent directory.

#### Table: `super_master`

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `MG_SN` | TEXT | No | Main Group Serial Number. Integer stored as text. Groups with `MG_SN >= 90` are hidden from the index sidebar — used for internal/system groups. |
| `Group_Name` | TEXT | No | Display name of the main group (e.g., "SANITARY", "TILES"). |
| `SG_SN` | TEXT | No | Sub-Group Serial Number within the main group. `00` entries are filtered out as dummy/placeholder rows. |
| `Sub_Group` | TEXT | Yes | Display name of the sub-group (e.g., "WASH BASIN", "FLOOR TILES"). This is what Tally calls `$Parent`. |

**Why `MG_SN >= 90` is hidden**: Groups numbered 90+ are reserved for system categories like "Price List" that should not appear in the catalog index but still need to exist in the mapping for data processing.


### 6.2 `row_data.db` — Raw Tally Data (Per-Company)

**Location**: `{company_path}/row_data.db`
**Created by**: `tally_sync.py`

#### Table: `stock_items`

| Column | Tally ODBC Column | Type | Purpose |
|---|---|---|---|
| `GUID` | `$GUID` | TEXT | Tally's globally unique identifier for each stock item. Primary key for cross-referencing. |
| `Item_Name` | `$Name` | TEXT | Full item name as defined in Tally. |
| `FirstAlias` | `$_FirstAlias` | TEXT | Item's first alias in Tally. |
| `Part_No` | `$MailingName` | TEXT | Mailing name, used as a part number field. |
| `Category` | `$Category` | TEXT | Item category (e.g., "China", "India"). Determines the category display code in the catalog. |
| `Unit` | `$BaseUnits` | TEXT | Base unit of measurement (e.g., "Pcs", "Nos"). |
| `SubGroup` | `$Parent` | TEXT | Parent group in Tally's hierarchy. Maps to `super_master.Sub_Group`. |
| `MRP` | `$StandardPrice` | TEXT | Maximum retail price. Stored as text because Tally can return comma-separated values for multi-rate items. |
| `Closing_Qty` | `$_ClosingBalance` | TEXT | Current closing stock quantity. Used to determine catalog inclusion (stock > 0). |

**Column Name Variance**: Tally's ODBC driver returns columns prefixed with `$` (e.g., `$GUID`, `$Name`). The sync code handles both `$GUID` and `GUID` column names via `col_or_fallback()` — this is because different Tally versions or ODBC driver configurations may or may not include the `$` prefix.

#### Table: `ledger_data`

| Column | Tally ODBC Column | Type | Purpose |
|---|---|---|---|
| `GUID` | `$GUID` | TEXT | Ledger GUID. |
| `Name` | `$Name` | TEXT | Ledger name. |
| `Parent` | `$Parent` | TEXT | Parent group. |
| `ClosingBalance` | `$_ClosingBalance` | TEXT | Current balance. |

### 6.3 `final_data.db` — Processed Catalog Data (Per-Company)

**Location**: `{company_path}/final_data.db`
**Created by**: `final_data.py` sync pipeline

#### Table: `catalog`

| Column | Index | Type | Nullable | Default | Auto-Populated | Purpose |
|---|---|---|---|---|---|---|
| `GUID` | 0 | TEXT | No | — | From Tally | Unique identifier. Hidden in UI (`setColumnHidden(0, True)`). |
| `ID` | 1 | TEXT | Yes | — | By `DataProcessor.generate_complex_ids()` | Hierarchical sort key encoding the full product hierarchy. Format: `{MG}_{SG}_{cluster}_{item}_{variant}` (e.g., `03_15_01_02_03`). Built using the same fuzzy clustering logic (`cluster_products`) as the catalog engine and Final Data tab. |
| `Item_Name` | 2 | TEXT | Yes | — | From Tally | Raw item name from Tally. |
| `Alias` | 3 | TEXT | Yes | — | From Tally | First alias. |
| `Part_No` | 4 | TEXT | Yes | — | From Tally | Mailing name (part number). |
| `Product Name` | 5 | TEXT | Yes | — | By `DataProcessor.process_and_save_final_data()` | Cleaned product name after regex rules strip sizes, units, and noise. This is the **primary display name** used by the catalog engine. |
| `Product_Size` | 6 | TEXT | Yes | — | By `DataProcessor` | Extracted size string (e.g., "24x24", "600x600 MM"). |
| `Category` | 7 | TEXT | Yes | — | From Tally | Raw category. Translated to display codes: `"China" → "चा."`, `"India" → "ई."`, else `""`. |
| `Unit` | 8 | TEXT | Yes | — | From Tally | Base unit of measurement. |
| `MOQ` | 9 | TEXT | Yes | — | Manual or inferred | Minimum Order Quantity. |
| `M_Packing` | 10 | TEXT | Yes | — | Manual or inferred | Master packing information. Regex-extracted integers are consolidated per product group. |
| `MRP` | 11 | TEXT | Yes | — | From Tally | Price. Can be comma-separated for multi-rate items. |
| `Stock` | 12 | TEXT | Yes | — | From Tally | Closing stock quantity. Items with `Stock <= 0` AND `True/False` not explicitly `true` are excluded from catalog rendering. |
| `MG_SN` | 13 | TEXT | Yes | — | From `super_master` lookup | Main group serial number. |
| `Group` | 14 | TEXT | Yes | — | From `super_master` lookup | Main group name. |
| `SG_SN` | 15 | TEXT | Yes | — | From `super_master` lookup | Sub-group serial number. |
| `Sub_Group` | 16 | TEXT | Yes | — | From Tally (`$Parent`) | Sub-group name. |
| `Image_Name` | 17 | TEXT | Yes | — | By `DataProcessor` via `clean_for_img()` | Cleaned, lowercase name used to match image files on disk. |
| `Image_Path` | 18 | TEXT | Yes | `""` | By `sync_images_after_processing()` | Full filesystem path to the matched image file. Special value `"no_need"` forces `True/False = false`. |
| `Lenth` | 19 | TEXT | Yes | `"1\|0"` | Auto or manual | Grid dimensions string. Format: `"ImgWidth\|Height"` or `"Img:Data\|Height"`. See [Layout Engine](#13-layout-engine--grid-placement) for full format spec. Note: The column name is intentionally misspelled ("Lenth" not "Length") — preserved for backward compatibility. |
| `Image_Date` | 20 | TEXT | Yes | `""` | By `sync_images_after_processing()` | File modification timestamp of the matched image. |
| `True/False` | 21 | TEXT | Yes | `""` | By `sync_true_false_values()` | Catalog inclusion flag. `"1"` or `"true"` = force-include. `"false"` = force-exclude. `""` (empty) = auto-decide based on stock. See [Inclusion Logic](#114-truefalse-inclusion-logic). |
| `Update_date` | 22 | TEXT | Yes | — | Auto on any change | Timestamp (`DD-MM-YYYY HH:MM:SS`) of last modification. Updated by `save_cell_to_db()` for trigger columns, and by the sync pipeline for Tally-sourced changes. |

**Unique Index**: `idx_guid ON catalog (GUID)` — enforces one row per Tally stock item.

### 6.4 `catalog.db` — Catalog Layout State (Per-Company)

**Location**: `{company_path}/catalog.db`
**Created by**: `CatalogLogic.init_catalog_db()`

#### Table: `catalog_pages`

| Column | Type | Nullable | Default | Purpose |
|---|---|---|---|---|
| `id` | INTEGER | No | AUTOINCREMENT | Internal row ID. |
| `mg_sn` | INTEGER | Yes | — | Main group serial. Copied from `super_master`. |
| `group_name` | TEXT | Yes | — | Main group name. Used in all queries as the human-readable group identifier. |
| `sg_sn` | INTEGER | Yes | — | Sub-group serial. |
| `page_no` | INTEGER | Yes | — | Page number within the subgroup (1-indexed, renumbered by `rebuild_serial_numbers()`). |
| `serial_no` | INTEGER | Yes | — | **Global serial number** across all pages. Assigned sequentially by `rebuild_serial_numbers()`. This is the number that appears on the catalog page header and is referenced by CRM tracking. |
| `is_printable` | INTEGER | Yes | `1` | Reserved for future use. Currently always `1`. |
| `product_list` | TEXT | Yes | `NULL` | **JSON array of lowercase product names** assigned to this page. This is the **Single Source of Truth** for page content. Added via schema migration. |

**Key invariant**: `product_list` is the authoritative record. When the engine runs, it reads `product_list` to determine what's on each page. The layout engine only computes grid positions — it does NOT decide which products go where (that's determined by `_sort_dirty_pages`).

#### Table: `subgroup_display_order`

| Column | Type | Purpose |
|---|---|---|
| `cache_key` | TEXT (PK) | Format: `"GroupName\|SG_SN"` (e.g., `"SANITARY\|1"`). |
| `product_order` | TEXT | JSON array of lowercase product names in display order. Maintained for backward compatibility. Updated every time page assignments change. |

**Why this exists**: Before `product_list` was added to `catalog_pages`, this table was the only record of product ordering. It's kept in sync as a fallback and for migration support.

#### Table: `page_snapshots`

| Column | Type | Purpose |
|---|---|---|
| `serial_no` | TEXT (PK) | Page serial number (as string). |
| `content_hash` | TEXT | MD5 hash of the page's rendered content. Used for change detection. |
| `product_list` | TEXT | JSON array of product names (for debugging and legacy migration). |

#### Table: `build_config`

| Column | Type | Purpose |
|---|---|---|
| `key` | TEXT (PK) | Config key name. |
| `value` | TEXT | Config value. |

Currently stores one key: `last_build_date` — timestamp of the most recent catalog build.

### 6.5 `security.db` — Authentication & RBAC (Global)

**Location**: `%APPDATA%/JK_Catalog/secure/security.db`
**Created by**: `SecurityManager.__init__()`

#### Table: `companies`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | INTEGER | PK, AUTOINCREMENT | Internal ID. |
| `name` | TEXT | NOT NULL | Company display name. |
| `folder_path` | TEXT | UNIQUE, NOT NULL | Absolute path to company data folder. Uniqueness constraint prevents duplicate registrations of the same folder. |
| `image_path` | TEXT | — | Path to the company's image folder. |

#### Table: `users`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | INTEGER | PK, AUTOINCREMENT | Internal ID. |
| `company_id` | INTEGER | FK → `companies.id` | Which company this user belongs to. |
| `username` | TEXT | NOT NULL | Login username. |
| `password_hash` | TEXT | NOT NULL | SHA-256 hash of the password. Never stored in plain text. |
| `role` | TEXT | DEFAULT `'user'` | Role identifier. No predefined RBAC enforcement in code — stored for future use. |

**UNIQUE constraint**: `(company_id, username)` — each username must be unique within a company.


### 6.6 `calendar_data.db` — Date Conversion (Global)

**Location**: `%APPDATA%/JK_Catalog/calendar_data.db` (writable copy) or bundled in `_MEIPASS` (read-only fallback).

#### Table: `calendar`

| Column | Type | Purpose |
|---|---|---|
| `ad_date` | TEXT | Gregorian date in `DD-MM-YYYY` format. |
| `bs_date` | TEXT | Nepali (Bikram Sambat) date in `YYYY-MM-DD` format. |

Used by `CatalogLogic.get_nepali_date()` to convert footer dates to Nepali calendar format.

### 6.7 JSON Data Files (Per-Company)

#### `company_info.json`

```json
{
    "display_name": "HW Division (2081/82)",
    "image_path": "D:\\Product Images"
}
```

Stored in each company folder. Read during login to get the display name and image folder path. Credentials are **not** stored here (moved to `security.db`).

#### `crm_data.json`

```json
["Raju", "Mohan", "Krishna"]
```

Simple JSON array of CRM representative names. Stored in each company folder.

#### `REPORT_DATA.JSON`

```json
{
    "Raju": {
        "pending": ["1", "2", "5", "12"],
        "recent": ["3", "4"]
    },
    "Mohan": {
        "pending": ["1", "2", "5"],
        "recent": []
    }
}
```

Per-CRM tracking of dirty (pending) and recently printed pages. Serial numbers are stored as strings. See [CRM & Dirty Page Tracking](#15-crm--dirty-page-tracking).

---

## 7. Column Constants

**File**: `src/logic/column_constants.py` (59 lines)

Provides a singleton `COL` object with named indices:

```python
COL.GUID = 0
COL.PRODUCT_NAME = 5
COL.TRUE_FALSE = 21
COL.COUNT = 23
```

Also provides `COL.DB_NAMES` — list of 23 column names as they appear in the database. Used for building SQL queries programmatically.

The codebase used to use hardcoded indices like `self.table.item(row, 5)` everywhere. That breaks the moment you reorder columns. Named constants make it obvious what you are accessing.

---

## 8. Application Entry Point & Crash Handling

**File**: `main.py` (141 lines)

### 8.1 `setup_crash_logger()`

This runs before anything else — even before Qt starts:

1. Creates `%APPDATA%/JK_Catalog/logs/`.
2. Opens `error.log` in append mode.
3. Redirects `sys.stderr` to this file, so uncaught exceptions and PyQt internal errors get captured.
4. Hooks `sys.excepthook` to log crashes with full tracebacks.

We need this because PyQt6 swallows exceptions in signal handlers silently. Without it, the app crashes in production and you'd have zero output to debug with.

### 8.2 `main()`

```python
app = QApplication(sys.argv)
app.setStyle("Fusion")  # Force Fusion for cross-platform consistency
```

We use Fusion because Windows' native style looks different on Win10 vs Win11. Fusion looks the same everywhere and plays nice with QSS customization.

A custom `QPalette` is applied with light mode colors (white windows, light gray bases, blue highlights). This is just the base — `style.qss` overrides specific widgets on top of it.

The splash screen uses PyInstaller's `pyi_splash` module. In the compiled `.exe`, it shows a splash during extraction and gets closed after the main window appears. In dev mode, the import just silently fails and we move on.

For window sizing, we don't use `showMaximized()`. Instead, `maximize_window()` reads `primaryScreen().availableGeometry()` and calls `setFixedSize()` to snap exactly to the available area. This stops the window from hiding behind the taskbar.

### 8.3 Taskbar-Aware Sizing

```python
avail = screen.availableGeometry()  # Excludes taskbar
full = screen.geometry()            # Includes taskbar

if avail == full:
    # Auto-hide taskbar: Leave 2px gap so the taskbar can still be triggered
    self.setFixedSize(full.width(), full.height() - 2)
else:
    # Visible taskbar: Snap exactly to available space
    self.setFixedSize(avail.width(), avail.height())
```

We use `setFixedSize` instead of `showMaximized` because tables and charts can request more space than what's available, pushing the window past the screen edge. `setFixedSize` locks it down.

The app also listens for `screen.availableGeometryChanged` so it re-adjusts if the user shows/hides the taskbar while using the app.

---

## 9. Logging Architecture

**File**: `src/utils/app_logger.py` (50 lines)

### 9.1 Factory Pattern

```python
from src.utils.app_logger import get_logger
logger = get_logger(__name__)
```

`get_logger(name)` grabs or creates a logger, adds a `StreamHandler(sys.stdout)` if there are no handlers yet, and sets the format to `HH:MM:SS | module.name | LEVEL | message`. Level defaults to `DEBUG`.

The `if not logger.handlers` check prevents duplicate output when the same module calls `get_logger()` multiple times.

### 9.2 File Logging

`main.py` → `setup_crash_logger()`:
1. Creates `%APPDATA%/JK_Catalog/logs/error.log`.
2. Configures `logging.basicConfig` with `FileHandler`.
3. Redirects `sys.stderr` to this file.
4. Sets `sys.excepthook` to log uncaught exceptions.

This means all `logger.error()` calls AND uncaught crashes end up in the same file.

---

## 10. Security & Authorization

**File**: `src/logic/security_manager.py` (184 lines)

### 10.1 Password Hashing

```python
hashlib.sha256(password.encode('utf-8')).hexdigest()
```

Passwords are hashed with SHA-256 before storage. No salt is used.

We skip the salt because this is a local desktop app, not a web service. The threat model is "someone at the office should not see another company's data" - not "the database was stolen and someone is running rainbow tables." Salt would just add complexity for no real benefit here.

### 10.2 Company Registration

`register_company(name, folder_path, image_path, username, password)`:

1. Checks if `folder_path` already exists in `companies` table (it has a UNIQUE constraint).
2. If it is new, inserts into `companies` and grabs the auto-incremented `id`.
3. If `username` and `password` are provided, creates a user with role `"owner"`.
4. Returns the `company_id`, or `None` if the path was already registered.

The `folder_path` UNIQUE constraint prevents the same physical folder from being registered twice - you would end up with duplicate company entries pointing at the same data.

### 10.3 Login Verification

`verify_login(folder_path, username, password)`:

```sql
SELECT u.id, u.username, u.role
FROM users u
JOIN companies c ON u.company_id = c.id
WHERE c.folder_path = ?
  AND u.username = ?
  AND u.password_hash = ?
```

1. Joins `users` with `companies` on `company_id`.
2. Filters by `folder_path` (not company name - names could be duplicated across folders).
3. Compares `password_hash` directly.
4. Returns a user dict `{"id", "username", "role"}` or `None`.

We filter by `folder_path` instead of company name because a company might get renamed, but its folder path is its real identity.

### 10.4 User Management

`UserManagerDialog` (`settings.py`):
- Shows a 10-row table with columns: `User Roles`, `Username`, `Password`.
- Loads existing users via `get_users_for_company()` - returns `[{"username", "role"}]`.
- Passwords are never shown (they are hashed). The password field always starts empty.
- On save, only rows where all three fields are filled get processed. So:
  - If you leave the password blank for an existing user, their hash stays untouched.
  - To change a password, you have to re-enter all three fields.

---

## 11. Session Management

**File**: `src/logic/session_manager.py` (126 lines)

### 11.1 What It Does

Instead of one giant `handle_login_success()` method that sets up every page, we use a registry pattern. Each UI page registers its own setup function. When a company is activated, all the registered pages get initialized in order.

### 11.2 Registration Pattern

```python
session = SessionManager()
session.register("Final Data", self.final_data_page,
    lambda page, path: (
        page.load_and_sync_data(comp_name, path),
        page.set_company_path(path)
    ))
```

Each registration provides:
- `name`: Human-readable label for error reporting.
- `page_widget`: The QWidget instance.
- `setup_fn`: `Callable(page_widget, company_path)` that initializes the page.

### 11.3 Activation

`session.activate(company_name, company_path)`:

1. Checks that `company_path` actually exists on disk.
2. Loops through all registered pages in order.
3. Calls `setup_fn(page_widget, company_path)` for each one.
4. Catches exceptions per-page - if one page crashes, the others still get initialized.
5. Returns `{"success": bool, "errors": [(page_name, error_msg), ...]}`.

The per-page error isolation matters. If the ledger database is corrupt, that should not stop the catalog from loading. Each failure gets logged but the session keeps going.

### 11.4 Registration Order

The pages are registered in this order in `handle_login_success()`:
1. Final Data
2. Super Master
3. Godown
4. Calendar
5. Cheque List
6. Reports
7. Full Catalog
8. Group Test
9. Row Data
10. Ledger Row Data

Final Data goes first because other pages (like Godown) depend on its `final_df` attribute being loaded.

---

## 12. UI Architecture

### 12.1 Root Window

**File**: `src/ui/main_window.py` (752 lines)

`MainWindow` is a frameless `QWidget` (`Qt.WindowType.FramelessWindowHint`). 

### 12.2 Navigation Stack (`nav_stack`)

A `QStackedWidget` with 7 pages (indices 0-6):

| Index | Menu | Contents |
|---|---|---|
| 0 | Blank | Empty widget. Shown when no company is logged in. |
| 1 | Main Menu | Catalog, Vat Working, Tally Internal, Settings |
| 2 | Catalog Menu | Sync Tally, Super Master, Final Data, Full Catalog, Reports, Cat/Price List, Preview Rows, Create CRM, Alter CRM |
| 3 | Settings Menu | Alter Company, Switch Co., Create User, Alter User, Security, Calendar |
| 4 | Tally Internal | Sync Ledger, Ledger Rows, On Account, Chq. List, Godown List, Sales Chat, Supp. Payment, Price List, Pur Import, Cost Sheet, For Branch |
| 5 | Vat Working | Balance, Stock |
| 6 | Branch Menu | BTM Order, NGT Order, BTM Receive, NGT Receive (all `None` — not yet implemented) |

### 12.3 Content Stack (`main_stack`)

A `QStackedWidget` with 19 pages (indices 0-18):

| Index | Widget | When Shown |
|---|---|---|
| 0 | `CompanyLoginUI` | Before login, or on "Switch Company" |
| 1 | `WelcomeUI` | After login, default landing page |
| 2 | `FullCatalogUI` | Catalog viewer and builder |
| 3 | `QLabel("Sync...")` | Placeholder during Tally sync |
| 4 | `RowDataUI` | Raw Tally data viewer |
| 5 | `FinalDataUI` | Processed catalog data editor |
| 6 | `SuperMasterUI` | Super master editor |
| 7 | `ReportsUI` | CRM performance reports |
| 8 | `PriceListUI` | Price list viewer |
| 9 | `QLabel("On Account")` | Placeholder |
| 10 | `GodownListUI` | Godown list |
| 11 | `SalesChatUI` | Sales chat |
| 12 | `SuppPaymentUI` | Supplier payment |
| 13 | `BalanceUI` | VAT balance |
| 14 | `StockUI` | VAT stock |
| 15 | `ChequeListUI` | Cheque list |
| 16 | `CalendarMappingUI` | AD-to-BS date mapping |
| 17 | `GroupTestTab` | Group testing/preview |
| 18 | `LedgerRowDataUI` | Ledger data viewer |

### 12.4 Hotkey System

**Tally-style mnemonics**: Menu buttons use `&` syntax (e.g., `"📁 &Catalog"`). The `&` marks the hotkey character.

**Implementation**:
1. `MenuButtonWidget` parses the `&` to extract the hotkey character.
2. The character is stored in `self.hotkey_char` (uppercased).
3. When the user presses `Alt`, `AltKeyFilter` (global event filter) calls `toggle_hotkey_hints(True)`, which shows red badge-style hints (e.g., `[C] Catalog`).
4. When `Alt+Key` is pressed, `keyPressEvent` scans ALL visible `MenuButtonWidget` children of the current nav page and triggers `animateClick()` on the matching one.
5. When `Alt` is released, badges are hidden and plain text is restored.

The alt-key scan only looks at buttons on the **currently visible** nav page (`nav_stack.currentWidget()`). So you can reuse the same hotkey letter across different menus without conflict.

### 12.5 Auto-Save on Tab Switch

```python
def on_main_stack_change(self, idx):
    if idx in [2, 7]:  # Full Catalog or Reports
        self.full_catalog_page.build_catalog(silent=True)
```

Switching to the Catalog or Reports tab triggers a **silent build** to pick up any changes you made in Final Data.

---

## 13. Company Login & Selection

**File**: `src/ui/company_login_ui.py` (526 lines)

### 13.1 Company Discovery

On load, the UI scans a data root directory for company folders:

1. Read `default_path` from `%APPDATA%/JK_Catalog/config.json`.
2. List all subdirectories in that path.
3. For each subdirectory, check if `company_info.json` exists.
4. If yes: read `display_name` from it and add to the company list.
5. If no: skip (not a registered company folder).

We scan the filesystem instead of keeping a registry because companies can be added outside the app (by copying a folder from another machine). Scanning makes sure they always show up.

### 13.2 Company Creation

`create_company()`:
1. Prompts for company name and image folder path.
2. Creates the company folder under `default_path`.
3. Writes `company_info.json` with `display_name` and `image_path`.
4. Registers in `security.db` via `SecurityManager.register_company()`.
5. Creates a default admin user if credentials are provided.

### 13.3 Login Flow

1. User selects a company from the list.
2. If `security.db` has users for this company: show login dialog.
3. If no users exist: auto-login (legacy mode for backward compatibility).
4. On success: emit `login_success(company_name, company_path)` signal.
5. `MainWindow.handle_login_success()` initializes all pages via `SessionManager`.

### 13.4 Data Path Switching

"Change Data Path" button:
1. Opens a folder picker dialog.
2. Saves the selected path to `config.json`.
3. Rescans the new directory for companies.
4. Refreshes the company list.

---

## 14. Full Catalog UI

**File**: `src/ui/full_catalog.py` (881 lines)

### 14.1 Page Data Structure

`all_pages_data` — list of tuples:
```python
[(mg_sn, group_name, sg_sn, page_no, serial_no), ...]
```

Loaded from `CatalogLogic.get_all_pages()`. Ordered by `serial_no`.

### 14.2 Index Sidebar

Left panel with expandable group tree:
- Top level: Main groups from `get_index_data()`.
- Expanded: Subgroups from `get_subgroups(group_name)`.
- Click on subgroup: navigate to first page of that subgroup.
- `expanded_groups` dict tracks which groups are expanded.

### 14.3 Page Navigation

- **Arrow buttons**: Previous/Next page.
- **Page counter**: `"{current} / {total}"`.
- **Direct jump**: Click a page number in the index sidebar.
- **Keyboard**: Left/Right arrows in `keyPressEvent`.

### 14.4 Build System

`build_catalog(silent=False)`:

1. If `silent=True`: no progress UI (used for auto-builds on tab switch).
2. If `silent=False`: show progress dialog, start `CatalogBuildWorker`.

`CatalogBuildWorker(QThread)`:
1. Calls `logic.engine_run(company_path)`.
2. Emits `finished(result_dict)` on completion.
3. Main thread receives result and refreshes the page display.

There is a concurrency guard: `if self._build_worker and self._build_worker.isRunning(): return` - this prevents accidentally kicking off multiple builds at the same time.

### 14.5 Reshuffle

`reshuffle_catalog()`:
1. Prompts the user to confirm (destructive operation).
2. Calls `logic._build_layout(group_name, sg_sn, reshuffle=True)` — clusters all products by similarity and re-sorts by price.
3. Clears existing page assignments.
4. Saves new assignments from the reshuffled layout.
5. Invalidates subgroup cache.
6. Refreshes the page display.

### 14.6 Page Management

- **Add Page**: Creates a new page at the end of the current subgroup. Triggers serial shift forward.
- **Remove Page**: Deletes empty pages. Verifies the page has no products and is not the last one. Triggers serial shift backward.
- **Find Empty Pages**: Scans all pages and lists those with no products assigned.

### 14.7 showEvent Auto-Build

```python
def showEvent(self, event):
    self.expanded_groups = {}
    self._load_index_data()
    if self.logic.catalog_db_path:
        self.logic.engine_run(self.company_path)  # Silent build
    self.refresh_catalog_data()
```

Every time the Catalog tab becomes visible, the engine runs a silent build. This way, any changes you made in Final Data are immediately reflected without you having to manually rebuild.

### 14.8 Length Change Handler

When the user right-clicks a product in the renderer and changes its dimensions:
1. `A4PageRenderer.length_changed` signal fires with `(product_name, new_length)`.
2. `_handle_length_change()` calls `logic.update_product_length()` which updates `final_data.db`.
3. Cache is invalidated and the page is refreshed.

---

*End of documentation.*

## 15. A4 Page Renderer

**File**: `src/ui/a4_renderer.py` (1038 lines)

This is the visual rendering engine that converts product data into a printable A4 catalog page widget.

### 15.1 Physical Page Constants

```python
page_w_mm = 210.0    # A4 width
page_h_mm = 297.0    # A4 height
header_h_mm = 9.0    # Header strip height
footer_h_mm = 9.0    # Footer strip height
margin_l/r/t/b = 0.0 # Zero margins by default (printer provides its own)
target_dpi = 96      # Widget layout DPI
```

All mm values are converted to pixels via:
```python
def mm_to_px(mm, dpi): return int(round(mm * dpi / 25.4))
```

At 96 DPI: page = 794×1123 px, header = 34 px, footer = 34 px.

### 15.2 Grid Metrics Calculation

`_compute_fixed_grid_metrics()`:

```
usable_h = page_h - margins - header_h - footer_h - border_width
usable_w = page_w - margins
```

Column widths: `usable_w // 4` for each column. Remainder pixels go to the **last column** to prevent sub-pixel gaps.

Row heights: `usable_h // 5` for each row. Remainder pixels go to the **last row**.

When dividing pixels among columns/rows, integer division can leave 1-3 leftover pixels. These go to the last cell so the grid fills the full page without any visible gap at the bottom or right edge.

### 15.3 Widget Hierarchy

```
A4PageRenderer (QWidget, 794×1123)
├── header_frame (QFrame, content_w × 34)
│   ├── header_left  (QLabel) → Company prefix ("HWD")
│   ├── header_center (QLabel) → Group name ("SANITARY")
│   └── header_right (QLabel) → Serial number ("42")
├── grid_wrap (QFrame)
│   ├── grid_widget (QWidget)
│   │   └── grid_layout (QGridLayout, 5 rows × 4 cols)
│   │       ├── [r,c] InteractiveProductFrame (image block)
│   │       ├── [r,c+H] InteractiveProductFrame (data block)
│   │       └── [r,c] QFrame (empty cell)
│   └── grid_bottom_line (QFrame, 2px blue line)
└── footer_frame (QFrame, content_w × 34)
    ├── footer_left  (QLabel) → CRM name
    ├── footer_center (QLabel) → Empty
    └── footer_right (QLabel) → Date (Nepali DD/MM)
```

### 15.4 Product Cell Layout

Each product occupies `cspan` columns in the grid. This space is split into two blocks:

| Variable | Meaning | Default |
|---|---|---|
| `H` | Number of columns for the **image** block | `cspan - 1` |
| `D` | Number of columns for the **data** block | `1` |
| Total | `H + D` must equal `cspan` | Always true |

**Split parsing from `Lenth` field**:
- `"1:1|2"` → `H=1` (image 1 col), `D=1` (data 1 col), `rspan=2`
- `"2:2|3"` → `H=2`, `D=2`, `rspan=3`
- If `H + D > cspan` (doesn't fit): fall back to `H = cspan - 1, D = 1` (image priority).
- If `H + D == cspan`: use as-is.

### 15.5 Image Block (`_img_block`)

1. Creates an `InteractiveProductFrame` (right-click → dimension dialog).
2. Loads image via `QImageReader` with auto-transform (EXIF rotation).
3. **Large image optimization**: If the source image is > 3× the display size, pre-scales during read via `reader.setScaledSize()`. This prevents loading a 4000×3000 pixel image for a 200×150 pixel slot.
4. Scales to fill with `IgnoreAspectRatio` + `SmoothTransformation`. Aspect ratio is NOT preserved — the image stretches to fill the cell.
5. Border: blue top/left, none on bottom (continuous with row below). Right border only if at page edge.

### 15.6 Data Block (`_data_block`)

Built by `_build_info_container()`:

```
┌─────────────────────────────┐
│  PRODUCT NAME (white/black) │  ← Word-wrapped, centered, bold
├─────────────────────────────┤
│  प्रति Pcs                   │  ← Base units in Nepali prefix
├─────────────────────────────┤
│  Size │ MRP │ MOQ           │  ← Header row (blue bg, white text)
│  24x24│ 450 │ 10            │  ← Data rows (red bg, white text)
│  18x18│ 350 │ 10            │  ← Sorted by database order (NOT by price)
├─────────────────────────────┤
│  चा.           6,12 Pcs     │  ← Category (left) + Master Packing (right)
└─────────────────────────────┘
```

The internal table explicitly does NOT sort rows by price (the `combined.sort(...)` line is commented out). Rows stay in the order from the database query, which matches the original Tally insertion order. This was a deliberate fix after a sorting bug was causing confusing row reordering.

### 15.7 Color Theme

| Element | Color | Hex |
|---|---|---|
| Grid lines | Blue | `#1511FF` |
| Image/data divider | Red | `#FF1A1A` |
| Product name background | Black | `#000000` |
| Product name text | White | `#ffffff` |
| Table header background | Blue | `#1511FF` |
| Table header text | White | `#ffffff` |
| Table cell background | Red | `#FF1A1A` |
| Table cell text | White | `#ffffff` |
| Footer date | Green | `#28a745` |

### 15.8 Product Size Dialog

`ProductSizeDialog` — opens on right-click of any product cell:

- **Image Width (Cols)**: SpinBox, range 1-4.
- **Data Width (Cols)**: SpinBox, range 1-4.
- **Vertical Height (Rows)**: SpinBox, range 1-5.
- **Automatic Height** checkbox: When checked, saves `0` for height (auto-calculated from size count).

**Width constraint**: `Image + Data ≤ 4`. If one spinner exceeds the limit, the other is auto-reduced. The last-changed spinner has priority.

**Keyboard flow**: Enter advances through fields in order: Image → Data → Height → Auto checkbox → Apply button.

**Output format**: `"{img}:{data}|{height}"` (e.g., `"2:1|0"` for auto-height with 2-col image).

### 15.9 Money Formatting

`_fmt_money(v)`:
1. Strip commas.
2. Extract first numeric match via regex `[-]?\d+(?:\.\d+)?`.
3. If integer: return without decimals (e.g., `450`).
4. If float: return with 2 decimals (e.g., `450.50`).
5. If no match: return raw string.

---

## 16. Print & PDF Export Pipeline

**File**: `src/ui/print_export.py` (546 lines)

### 16.1 DPI Strategy

```python
RENDER_DPI = 96           # Widget layout DPI (must match screen)
PDF_SAFE_MARGIN_MM = 2.0  # Each side — protects borders in reprinted PDFs
```

We use 96 DPI because the `A4PageRenderer` is a QWidget, and Qt resolves CSS font sizes against screen DPI. If you used printer DPI (600-1200), text rendering would go haywire. So the renderer always lays out at screen DPI, then gets scaled to fill the printer's page area.

### 16.2 Margin Strategy

| Output Mode | Margins | Why |
|---|---|---|
| PDF | `PDF_SAFE_MARGIN_MM` (2mm each side) | Ensures borders survive when the PDF is later printed on different printers with different non-printable zones. |
| Print/Preview | 0mm (zero margins) | Qt automatically uses the printer's hardware minimum. Zero-margin requests let Qt handle the physical constraints. |

### 16.3 Unified Rendering Loop

`_render_pages(painter, printer, page_indices, mode)`:

1. Create renderer via `create_print_renderer()`.
2. Get `page_rect` from `printer.pageRect(QPrinter.Unit.DevicePixel)`.
3. Calculate uniform scale: `min(target_w / renderer.width(), target_h / renderer.height())`.
4. Center if aspect ratios differ.
5. For each page:
   - `painter.save()` → translate → scale → render → `painter.restore()`.
   - Update progress bar.
   - Check for cancellation.
6. Clean up renderer.

### 16.4 Company Prefix

The renderer header shows a 3-letter company code. Derived by:
1. Read `company_info.json` → `display_name`.
2. Take first 3 characters, uppercased.
3. Fallback: first 3 characters of the folder name.

### 16.5 PDF Filename Format

```
{PREFIX}_{CRM}_{DD-MM}_{HH-MM-SS}.pdf
```

Example: `HWD_Raju_21-04_14-30-00.pdf`

If a `download_path` is set (via Reports → Set Location), the file is saved there automatically without a file dialog.

---

## 17. Reports Pipeline

**File**: `src/ui/reports.py` (318 lines)

### 17.1 Data Flow

```
[REPORT_DATA.JSON] → [CRM table in Reports tab]
                          ↓
[User selects CRM] → [CRMSelectDialog: shows pending pages]
                          ↓
[PrintExportDialog: renders selected pages]
                          ↓
[Confirmation: "Did you print successfully?"]
   ├── Yes → Move pending → recent, clear pending
   └── No → Keep pending
```

### 17.2 `CRMSelectDialog`

- Dropdown of CRM names from `crm_data.json`.
- List of pending page serial numbers from `REPORT_DATA.JSON`.
- Pages are sorted by numeric value (with non-numeric fallback to `float('inf')`).

### 17.3 Renderer Callback

Reports use a custom renderer callback instead of the default catalog rendering:

```python
def render_report_page(self, painter, serial_no, renderer, crm_name):
    page_info = self.logic.get_page_info_by_serial(serial_no)
    products = self.logic.get_items_for_page_dynamic(...)
    renderer.set_header_data(group_name, serial_no)
    renderer.fill_products(products)
    renderer.set_footer_data(crm_name, footer_date)
    renderer.render(painter)
```

We need a separate callback because Reports render pages by serial number (from the pending list), while the catalog renders by index into `all_pages_data`. The callback hides this difference.

### 17.4 `ensure_logic_init()`

Reports create their own `CatalogLogic` instance if one does not already exist. This handles the case where you open Reports without visiting the Catalog tab first.

---

## 18. Tally Sync Pipeline

**File**: `src/services/tally_sync.py` (341 lines)

### 18.1 Connection

```python
conn_str = (
    "DRIVER={Tally ODBC Driver 64};SERVER=localhost;PORT=9000;"
    f"DATABASE={company_name};OPTION=3;"
)
connection = pyodbc.connect(conn_str, timeout=10)
```

- Connects to Tally's ODBC server on `localhost:9000`.
- The `DATABASE` parameter is the company name as it appears in Tally.
- Timeout is 10 seconds - Tally ODBC has a habit of hanging if the company is not loaded yet.

### 18.2 `fetch_tally_data(company_name, company_path)`

1. Builds a pandas query: `SELECT * FROM StockItem`.
2. Maps Tally's `$`-prefixed columns to internal names via `column_mapping`:
   ```python
   column_mapping = {
       "$GUID": "GUID",
       "$Name": "Item_Name",
       "$_FirstAlias": "FirstAlias",
       "$MailingName": "Part_No",
       "$Category": "Category",
       "$BaseUnits": "Unit",
       "$Parent": "SubGroup",
       "$StandardPrice": "MRP",
       "$_ClosingBalance": "Closing_Qty"
   }
   ```
3. Saves to `{company_path}/row_data.db` table `stock_items` (wipes and replaces the entire table).
4. Returns `(DataFrame, error_string)`.

We do a full replace every time because the ODBC query returns the entire stock list. Trying to do incremental sync is unreliable - items in Tally can be renamed, merged, or deleted, and there is no change tracking.

### 18.3 `fetch_tally_ledger_data(company_path)`

Same pattern but queries `SELECT * FROM Ledger`. Saves to `{company_path}/ledger_data.db` → table `ledger_data`.

### 18.4 Error Handling

If `pyodbc.connect()` fails, the error message comes back as a string. The usual suspects:
- `"Tally not running"` - the ODBC server is not started in Tally.
- `"Company not loaded"` - you need to open the company in Tally first.
- `"Driver not found"` - the 64-bit ODBC driver is not installed on the machine.

---

## 19. Data Processing Pipeline

**File**: `src/logic/data_processor.py` (527 lines)

### 19.1 What It Does

Takes the raw `Item_Name` from Tally and produces two clean fields:
- `Product Name`: A readable name for display in the catalog.
- `Product_Size`: The extracted size/dimension string.

Also generates `Image_Name` (an even more aggressively cleaned version used for matching image files on disk).

### 19.2 `process_and_save_final_data()`

For each row in `catalog` table:

1. **Read** `Item_Name`.
2. **Clean** via `clean_product_name(name)`:
   - Apply 20+ regex substitution rules from `cleaning_rules.json`.
   - Strip trailing sizes, units, and measurement markers.
   - Normalize whitespace.
3. **Extract size** via `extract_size(name)`:
   - Match patterns like `24X24`, `600x600 MM`, `"18 INCH"`.
   - Handle edge cases: `QUATER SIZE`, `HALF SIZE`, etc.
4. **Generate image name** via `clean_for_img(product_name)`:
   - Further strip sub-variants and decorative suffixes.
   - Convert to lowercase.
   - This is stored in `Image_Name` column.
5. **Write** `Product Name`, `Product_Size`, `Image_Name` back to the DB.

### 19.3 Regex Rules Architecture

**File**: `config/cleaning_rules.json`

```json
{
    "cleaning_patterns": [
        {"pattern": "\\bW/O\\s*PEDESTAL\\b", "replacement": ""},
        {"pattern": "\\bSET\\s*OF\\s*\\d+\\b", "replacement": ""},
        {"pattern": "\\bHEAVY\\s*BODY\\b", "replacement": ""},
        ...
    ],
    "similarity_threshold": 0.75
}
```

Each rule is a `{pattern, replacement}` pair applied in order. The output of one rule feeds into the next.

We use regex instead of NLP because product names from Tally follow predictable manufacturing nomenclature like `"WASH BASIN 24X24 W/O PEDESTAL HEAVY BODY SET OF 1"`. Regex is faster, deterministic, and handles these exact patterns well.

### 19.4 `clean_for_img()` — Image Name Generation

Over 20 hardcoded regex rules that strip:
- Size patterns: `\d+\s*[xX×]\s*\d+`, `\d+\s*(MM|CM|INCH)`
- Color patterns: `\b(WHITE|IVORY|BONE|CREAM)\b`
- Grade patterns: `\b(A|B|C)\s*GRADE\b`
- Finishing patterns: `\b(GLOSSY|MATT|MATTE|SATIN)\b`
- Surface patterns: `\b(PUNCH|SUGAR)\s*FINISH\b`
- Model suffixes: `\b(BIG|SMALL|MINI|JUMBO)\b`
- Set patterns: `\bSET\s*OF\s*\d+\b`

The stripping is this aggressive because image names need to match across size variants. For example, `"WASH BASIN 24X24 WHITE GLOSSY"` and `"WASH BASIN 18X18 IVORY MATT"` should both match the same image file `"wash basin.jpg"`.

### 19.5 `generate_complex_ids()`

```python
final_id = f"{mg_sn}_{sg_sn}_{ci:02d}_{ii:02d}_{vi:02d}"
```

Generates a hierarchical ID encoding the full product taxonomy using **fuzzy clustering**:

| Segment | Meaning | Example |
|---|---|---|
| `mg_sn` | Master Group Serial Number | `03` |
| `sg_sn` | Sub Group Serial Number | `15` |
| `ci` | Fuzzy cluster index (via `cluster_products`) | `01` |
| `ii` | Item index — unique product name within cluster | `02` |
| `vi` | Variant index — size/price variant within item | `03` |

Example: `03_15_01_02_03` = MG 03, SG 15, fuzzy cluster 01, item 02 (Jk), variant 03.

The clustering uses the same shared `cluster_products()` and `normalize_name()` from `text_utils.py` that the catalog engine and Final Data tab use, so `ORDER BY [ID]` naturally produces the same grouping as the Python-level sorting.

---

## 20. Final Data Sync Pipeline

**File**: `src/ui/final_data.py` (1068 lines)

### 20.1 Pipeline Overview

Triggered by: `load_and_sync_data(company_name, company_path)`

```
[Tally row_data.db] → [Super Master Mapping] → [UPSERT into final_data.db]
                                                      ↓
                                              [DataProcessor: Name/Size/Image cleanup]
                                                      ↓
                                              [Image Sync: Match files on disk]
                                                      ↓
                                              [True/False Sync: Set inclusion flags]
                                                      ↓
                                              [Refresh Table UI]
```

### 20.2 Background Worker

`FinalDataSyncWorker` extends `QThread`. The heavy pipeline runs off the main thread so the UI does not freeze. **No widget access is allowed inside the worker** - all UI updates go through signals:

- `progress(str)` - updates the progress dialog label.
- `finished(str)` - tells the main thread to refresh the table.
- `error(str)` - logs the error.

### 20.3 `_run_sync_pipeline()` Step-by-Step

**Step 1: Create table**
```sql
CREATE TABLE IF NOT EXISTS catalog (
    [GUID] TEXT, [ID] TEXT, [Item_Name] TEXT, ...
)
CREATE UNIQUE INDEX IF NOT EXISTS idx_guid ON catalog (GUID)
```

**Step 2: Super Master lookup**
Reads `super_master.db` into a dict: `{Sub_Group → (MG_SN, Group_Name, SG_SN)}`.

**Step 3: Read Tally data**
Reads `row_data.db/stock_items`. Handles column name variance via `col_or_fallback()`:
```python
def col_or_fallback(expected, fallback):
    if expected in col_names: return expected
    if fallback in col_names: return f'[{fallback}] AS [{expected}]'
    return f"NULL AS [{expected}]"
```
This handles both `GUID` and `$GUID` column names.

**Step 4: Delete removed items**
```python
tally_guids_set = {r[0] for r in rows}
catalog_guids = [row[0] for row in cur.execute("SELECT GUID FROM catalog")]
guids_to_delete = [g for g in catalog_guids if g not in tally_guids_set]
for g in guids_to_delete:
    cur.execute("DELETE FROM catalog WHERE GUID=?", (g,))
```
Any item that was removed from Tally also gets removed from the catalog.

**Step 5: UPSERT loop**
For each Tally row:
1. Build `new_row` tuple from Tally data + super_master mapping.
2. Fetch `old_row` from catalog by GUID.
3. Compare field-by-field (both normalized to empty-string-for-None).
4. If changed: `UPDATE` with new values + set `Update_date` to now.
5. If new: `INSERT` with all fields. Default `Lenth = "1"`.

**Step 6: Data Processor**
```python
processor = DataProcessor(self.db_path)
processor.process_and_save_final_data()  # Clean names, extract sizes
processor.generate_complex_ids()         # Build composite IDs
```

**Step 7: Image Sync**
`sync_images_after_processing()`:
1. Builds a mapping of `{clean_image_name → file_path}` by scanning the image folder.
2. For each catalog row, looks up `Image_Name` in the mapping.
3. If found: sets `Image_Path` and `Image_Date`.
4. If not found: clears both fields.

**Step 8: True/False Sync**
`sync_true_false_values()`: See next section.

### 20.4 True/False Inclusion Logic

The `True/False` column controls whether a product appears in the catalog. Three states:

| Value | Meaning | How Set |
|---|---|---|
| `"1"` or `"true"` | Force-include, even if stock is 0 | Manual edit by user |
| `"false"` | Force-exclude, even if stock > 0 | Manual edit, or auto-set by rules |
| `""` (empty) | Auto-decide based on stock at render time | Default for new items |

**Auto-exclusion rules** (in `sync_true_false_values()`):
1. If `Image_Path` contains `"no_need"` → force `"false"`.
2. If `Group` is `"Price List"` → force `"false"`.
3. All other cases: **preserve existing value**. dont auto-sets `"false"` for missing images 

**Render-time inclusion** (in `get_sorted_products_from_db()`):
```sql
WHERE (
    [True/False] IS NULL
    OR TRIM([True/False]) = ''
    OR LOWER(TRIM(CAST([True/False] AS TEXT))) NOT IN ('false', '0', 'no')
)
AND (
    CAST(REPLACE(IFNULL([Stock], '0'), ',', '') AS REAL) > 0
    OR LOWER(TRIM(CAST([True/False] AS TEXT))) IN ('1', 'true', 'yes')
)
```

Translation:
- Include if `True/False` is NOT explicitly false, AND stock > 0.
- OR include if `True/False` is explicitly true (force-include overrides zero stock).

**Lenth normalization**: After True/False sync, all NULL or empty `Lenth` values are set to `"1|0"`, and bare `"1"` is upgraded to `"1|0"` for auto-height calculation.

### 20.5 Cell Edit Pipeline

`save_cell_to_db(item)` — triggered by `itemChanged` signal:

1. Reads old value from `Qt.ItemDataRole.UserRole` (stored at load time).
2. If column is `True/False` (index 21): normalizes input:
   - Leading `f` or `n` or `0` → `"false"`
   - Leading `t` or `y` or `1` → `"1"`
   - `Image_Path` contains `"no_need"` → force `"false"`
3. If `True/False` set to `"false"`: deletes the product from `known_layout_products` in `catalog.db` so it won't be included in future layouts.
4. If column is in `trigger_cols` list: also updates `Update_date` to current timestamp.
5. Special: If `Image_Path` is set to `"no_need"` → auto-sets `True/False` to `"false"`.
6. Special: If `Product_Size` changes → recalculates `Lenth` to `"1|0"`.

---

## 21. Date Conversion Pipeline

**File**: `src/utils/date_utils.py` (96 lines)

### 21.1 Footer Date Calculation

`get_footer_date(products, logic)`:

1. Find `max_update_date` across all products on the page by parsing `DD-MM-YYYY HH:MM:SS` strings.
2. If `logic` has `get_nepali_date()`: convert to BS date (returns `DD/MM` format).
3. Fallback: return AD date as `DD/MM`.

### 21.2 Nepali Date Conversion

`CatalogLogic.get_nepali_date(ad_date_str)`:

1. Extract date-only part (before space).
2. Look up in `calendar.calendar` table: `SELECT bs_date FROM calendar WHERE ad_date=?`.
3. Parse BS date (`YYYY-MM-DD`) → return `DD/MM`.

We use a lookup table instead of an algorithm because Nepali calendar months have irregular lengths that change every year. A lookup table is more reliable than trying to compute it.

---

## 22. Catalog Engine

**File**: `src/logic/catalog_logic.py` (2251 lines)

### 22.1 Connection Manager

All database access goes through `_get_conn(db_key)`:

```python
_DB_SUPER = "super"      # super_master.db
_DB_CATALOG = "catalog"  # catalog.db
_DB_FINAL = "final"      # final_data.db
_DB_CALENDAR = "calendar" # calendar_data.db
```

Connections are kept alive in `self._connections` and reused. Before reuse, a health check (`SELECT 1`) verifies the connection is still good. If it is stale, it gets recreated.

Every new connection runs `PRAGMA journal_mode=WAL`. WAL lets readers and writers work at the same time - important because the background build worker writes to the DB while the UI is reading from it.

### 22.2 Schema Initialization

`init_catalog_db()` creates four tables in `catalog.db`:
1. `catalog_pages` — page metadata and product assignments.
2. `subgroup_display_order` — product ordering (legacy + backup).
3. `page_snapshots` — content hashes for change detection.
4. `build_config` — key-value store (currently: `last_build_date`).

**Schema migration**: The code checks if the `product_list` column exists in `catalog_pages`. If not, it adds it via `ALTER TABLE` and runs `_migrate_to_explicit_assignments()` to backfill `product_list` from the old `page_snapshots` data.

### 22.3 `engine_run(company_path)` — Main Build Cycle

This is the heart of the whole application. It runs when you:
- Click the Build button
- Switch to the Catalog or Reports tab
- Finish a Tally sync

**8-Step Pipeline**:

```
Step 1: sync_pages_with_content()
   ├── Remove orphaned pages (group/subgroup deleted from super_master)
   └── Ensure ≥1 page for subgroups with products

Step 2: rebuild_serial_numbers()
   └── Assign sequential serial_no and renumber page_no per subgroup

Step 3: detect_changed_pages()
   └── Compare MD5 hashes of current page content vs. stored snapshots

Step 3.5: _detect_unassigned_products()
   └── Find products in final_data.db not in any page's product_list
   └── Force-dirty the last page of affected subgroups

Step 4: Merge CRM dirty set
   └── Union of all CRM reps' pending serial numbers (via _get_all_dirty_serials)

Step 5: _sort_dirty_pages(group, sg_sn, dirty_pages)
   └── Re-sort products across dirty page ranges via grid simulation

Step 6: rebuild_serial_numbers() (again)
   └── Pages may have been created during Step 5

Step 7: Update CRM
   ├── Remap shifted serial numbers in all CRM pending lists
   └── Add all dirty pages to all CRM pending lists

Step 8: save_all_page_snapshots()
   └── Store current MD5 hashes for future diff
```

**Return value**: `{"dirty_count": int, "dirty_serials": [str], "pages_created": int}`

### 22.4 `sync_pages_with_content()`

**Phase 1 — Remove orphaned pages**:
1. Build set of valid `(group_name.UPPER, sg_sn)` pairs from `super_master`.
2. Query all distinct `(group_name, sg_sn)` from `catalog_pages`.
3. Delete any that aren't in the valid set.

**Phase 2 — Ensure minimum pages**:
1. For each valid subgroup, check `COUNT(*)` in `catalog_pages`.
2. If zero AND the subgroup has products in `final_data.db`, insert one page.

### 22.5 Product Fetching & Grouping

`get_sorted_products_from_db(group_name, sg_sn)`:

**SQL filter**:
- Group matching uses `REPLACE(TRIM([Group]), '.', '')` to handle dots in group names.
- Case-insensitive via `COLLATE NOCASE`.
- Inclusion logic: see [True/False Inclusion Logic](#114-truefalse-inclusion-logic).

**Variant grouping**: Products with the same normalized name (lowercase, hyphens/underscores → spaces) are merged:
```python
norm_key = " ".join(raw_name.lower().replace("-", " ").replace("_", " ").strip().split())
```

For each group of variants:
- `sizes`: List of all variant sizes.
- `mrps`: List of all variant MRPs.
- `moqs`: List of all variant MOQs.
- `master_packing`: Consolidated from regex-extracted integers, formatted as `"6,12 Pcs"`.
- `sort_price`: First MRP value, parsed as float. Used for within-cluster sorting.
- `category`: Translated: `"China" → "चा."`, `"India" → "ई."`.
- `max_update_date`: Latest update date across all variants.

---

## 23. Layout Engine — Grid Placement

### 23.1 Grid Dimensions

```python
GRID_ROWS = 5  # 5 rows per page
GRID_COLS = 4  # 4 columns per page
```

Each catalog page is a 5×4 grid. Each product occupies a rectangular block defined by `(rspan, cspan)`.

### 23.2 Product Dimensions Calculation

`_get_product_dims(p_data)` → `(rspan, cspan)`

**From size count**:
| Sizes Count | rspan |
|---|---|
| > 10 | 3 |
| > 5 | 2 |
| ≤ 5 | 1 |

`cspan` defaults to 2 (1 column for image + 1 column for data).

**From `Lenth` field** (overrides size-based defaults):

| Format | Meaning | Result |
|---|---|---|
| `"2"` | Raw height | rspan=2, cspan=2 (default) |
| `"1\|2"` | `ImgWidth\|Height` | cspan = ImgWidth + 1 = 2, rspan = 2 |
| `"1:1\|2"` | `Img:Data\|Height` | cspan = 1+1 = 2, rspan = 2 |
| `"2:2\|3"` | Wide product | cspan = 2+2 = 4, rspan = 3 |
| `"1\|0"` | Auto height | cspan = 2, rspan = size-based |

**Clamping**: Both rspan and cspan are clamped to `[1, GRID_ROWS]` and `[1, GRID_COLS]` respectively.

### 23.3 Slot Finding

`_find_slot(grid, rspan, cspan)`:

Top-left scan: iterates row by row, column by column. For each position `(r, c)`:
1. Check if the starting cell is free.
2. Check if `r + rspan <= GRID_ROWS` (fits vertically).
3. Check all cells in the `rspan × cspan` block are free.
4. Return first valid position, or `(-1, -1)` if no slot found.

**When -1 is returned**: The product doesn't fit on the current page. The caller creates a new page.

### 23.4 `_build_layout()` — Initial Layout

Used for:
- First-time layout (no page assignments exist yet).
- Full reshuffle requested by user.

**Sorting**:
- If reshuffle: `_cluster_and_sort()` — clusters by name similarity, sorts by price within clusters.
- If first run with saved order: `_apply_saved_order()` — re-applies previous ordering, appends new products at end.
- If first run without saved order: `_cluster_and_sort()`.

**Placement**: Simple sequential. Products fill pages left-to-right, top-to-bottom. When a page is full (no slot found), a new page starts.

**Post-processing**: `_distribute_products_evenly()` — vertical visual balancing. Groups products by row, then spaces rows evenly across the page height.

### 23.5 Clustering Algorithm

`_cluster_and_sort(products)` → `text_utils.cluster_and_sort()`:

1. For each product, compute a "clean" name via `clean_cat_name()`.
2. Compare all pairs using `is_similar()` (Levenshtein ratio or token overlap).
3. Group products with similarity > threshold (default 0.75).
4. Sort products within each cluster by `(normalize_name(name), price)` — name first, then price.
5. Sort clusters by minimum price in the cluster.
6. Flatten clusters back into a single list.

This is the **unified sorting function** shared across three call sites: `generate_complex_ids()`, `refresh_table()`, and `_cluster_and_sort()`. The getter functions differ per caller (different data shapes), but the algorithm is identical.

### 23.6 Visual Balancing

`_distribute_products_evenly(layout_map)`:

For each page:
1. Group placements by their row number.
2. Calculate total height (sum of max rspan per row).
3. If total height < GRID_ROWS - 1 (there's free space):
   - Compute `empty_space = GRID_ROWS - total_height`.
   - Distribute gaps evenly between product rows.
   - Reassign row positions with gaps.

Without balancing, two small products on a page would both be crammed at the top. Balancing spaces them out across the full page height so it looks better.

### 23.7 `get_items_for_page_dynamic()` — Rendering API

Primary API for getting products for a specific page:

1. Read `product_list` from `catalog_pages` for this page.
2. If found: Load product data (cached per subgroup), compute grid positions on-the-fly.
3. If not found (first run): Fall back to `_build_layout()` and use relative page mapping.

Returns: `[{"data": product_dict, "row": int, "col": int, "rspan": int, "cspan": int}]`

---

## 24. Change Detection — Snapshot System

### 24.1 Hash Computation

`_compute_page_hash(serial_no)`:

1. Get all products for the page via `get_items_for_page_dynamic()`.
2. For each product, build a dict: `{name, row, col, rspan, cspan, mrps, sort_price, img, sizes}`.
3. Sort by `(row, col, name)` for determinism.
4. Serialize to JSON with `sort_keys=True`.
5. Compute `hashlib.md5(json_bytes).hexdigest()`.

**Empty pages**: Return the string `"empty_page"` (not a hash).

### 24.2 Change Detection

`detect_changed_pages()`:

1. Load all stored hashes from `page_snapshots`.
2. For each page, compute current hash.
3. If stored hash is missing (new page) or different (changed content) → add to changed set.

### 24.3 Snapshot Save

`save_all_page_snapshots()`:

After a build, save the current hash and product list for every page. This establishes the baseline for the next diff.

---

## 25. CRM & Dirty Page Tracking

### 25.1 Data Structure

`REPORT_DATA.JSON`:
```json
{
    "CRM_Name": {
        "pending": ["1", "5", "12"],  // Pages that need to be printed for this CRM
        "recent": ["3", "4"]          // Pages that were most recently printed
    }
}
```

### 25.2 Engine Integration

During `engine_run()`:

1. **Read dirty set from CRM**: The code calls `_get_all_dirty_serials()`, which loops through **every CRM** in `REPORT_DATA.JSON` and combines all their `pending` lists into one set. In practice this gives you the same result as just reading the latest unprinted CRM's pending list, because `_add_serials_to_all_crms()` always broadcasts dirty pages to every CRM at the same time - the only difference between CRMs is that the ones who already printed have their pending cleared.

2. **Merge with snapshot changes**: The engine combines CRM-pending pages with snapshot-detected changes to form the complete dirty set.
3. **After sorting**: All newly-dirty pages are added to ALL CRM reps' pending lists via `_add_serials_to_all_crms()`.

**Important**: The engine never clears CRM pending lists. Only the print/export flow clears them, and only after the user confirms they actually printed successfully.

### 25.3 Print/Export Flow

1. User opens Reports → selects a CRM → sees pending pages.
2. Clicks Print/PDF → `PrintExportDialog` renders those pages.
3. After dialog closes with `Accepted`: confirmation dialog asks "Did you successfully print?"
4. If Yes: `update_pages_logic(crm_name)` moves pending → recent and clears pending.
5. If No: pending list is preserved.

### 25.4 Dirty Page Sorting

`_sort_dirty_pages(group_name, sg_sn, dirty_page_list)`:

1. Group dirty pages into **contiguous ranges** (e.g., `[1,2,3], [5], [7,8]`).
2. For each range:
   a. Pool all products from those pages' `product_list`.
   b. Cluster and sort the pool.
   c. Simulate grid placement to fill pages densely.
   d. Update `product_list` for each page.
3. Handle **overflow cascade**: If products overflow past the range, merge with the next page and repeat. Auto-create pages as needed.
4. Handle **new products**: Products in the DB but not assigned to any page are appended to the last page of the subgroup.
5. Save all updated assignments.

Clean pages are never touched - only pages in the dirty set get their `product_list` modified.

---

## 26. Serial Shift Handling

### 26.1 Forward Shift (Page Insertion)

`handle_serial_shift_forward(company_path, insertion_serial, old_max_serial)`:

When a new page is inserted at serial position `N`:
1. All serials from `N` to `old_max_serial` shift to `N+1` ... `old_max_serial+1`.
2. Build remap: `{str(s): str(s+1) for s in range(N, old_max_serial+1)}`.
3. Call `_remap_crm_serials()` to update all CRM pending lists.
4. Add all shifted serials + the new serial to all CRM pending lists (they all need reprinting since their page number changed).

### 26.2 Backward Shift (Page Deletion)

`handle_serial_shift_backward(company_path, deleted_serial, old_max_serial)`:

When a page at serial position `N` is deleted:
1. All serials from `N+1` to `old_max_serial` shift to `N` ... `old_max_serial-1`.
2. Build remap: `{str(s): str(s-1) for s in range(N+1, old_max_serial+1)}`.
3. Map the deleted serial to `"__DELETED__"`.
4. Call `_remap_crm_serials()`.
5. Remove `"__DELETED__"` entries from all CRM pending lists.
6. Add all shifted serials to CRM pending lists.

### 26.3 Why This Matters

Serial numbers are what get printed on the actual catalog pages. If you delete page 5, what used to be page 6 becomes page 5. Any CRM rep who was told to print "page 6" now needs to reprint because the serial changed. The shift handlers keep CRM tracking in sync when pages move around.

---

## 27. Key Invariants & Edge Cases

### 27.1 Data Integrity Invariants

1. **GUID uniqueness**: Every product has a unique GUID from Tally. The `idx_guid` unique index enforces this. Duplicate GUIDs cause UPSERT behavior (update instead of insert).

2. **Serial number continuity**: After every `rebuild_serial_numbers()`, serials are 1-indexed with no gaps. Page numbers per subgroup are also renumbered consecutively.

3. **Product list is source of truth**: `catalog_pages.product_list` (JSON array) determines which products are on which page. The layout engine only computes grid positions from this list.

4. **CRM is never cleared by the engine**: Only the print confirmation flow clears CRM pending lists. The engine only adds to them.

5. **Clean pages are never touched**: `_sort_dirty_pages()` only modifies pages in the dirty set. Clean pages' `product_list` remains frozen.

### 27.2 Edge Cases

| Scenario | Behavior |
|---|---|
| Product removed from Tally | Deleted from `final_data.db` during sync. On next engine run, its name in `product_list` will not match any DB product, so it's silently skipped during rendering. |
| Product renamed in Tally | Old name remains in `product_list`. New name appears as unassigned. Engine detects this in `_detect_unassigned_products()`, forces the subgroup dirty, and `_sort_dirty_pages()` picks up the new product. Old name is skipped (no match). |
| Subgroup deleted from super_master | `sync_pages_with_content()` removes orphaned pages for this subgroup. |
| Stock drops to zero | Product is excluded from rendering by the SQL filter in `get_sorted_products_from_db()` unless `True/False` is explicitly `"1"`. The product stays in `product_list` but renders as an empty slot. On next build, the engine detects the content change and re-sorts. |
| Multiple CRM reps | Each CRM rep has independent pending/recent lists. The engine adds dirty pages to ALL reps. Each rep's list is cleared independently after their print confirmation. |
| Image file missing | `Image_Path` is set to `""`. Product still appears in catalog but without an image. `True/False` is NOT auto-set to `"false"` (changed per user request). |
| `Image_Path` set to "no_need" | `True/False` is auto-set to `"false"`. Product is excluded from catalog rendering. |
| Overflow cascade | If dirty page sorting causes products to overflow past the dirty range, the engine cascades: merges overflow with the next page's products, simulates grid placement, and repeats until everything fits. New pages are created as needed. |
| Concurrent access | WAL mode allows multiple readers. The UI reads while the build worker writes. However, only one build worker can run at a time (`if self._build_worker and self._build_worker.isRunning(): return`). |
| Company folder moved | Login fails because `security.db` stores `folder_path` as absolute. The user must re-register the company at the new path. |



---
