import os
# --- CRM & Report Data Functions (SQL Server via db_manager) ---

from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

def _get_catalog_db(company_path):
    """Resolve the Catalog DB logical name from a company_path.
    
    Accepts either:
      - A company folder path (e.g., 'D:\\Data\\HW Divison 082083')
      - A legacy file_path (e.g., 'D:\\Data\\HW Divison 082083\\crm_data.json') — extracts dirname
    """
    if not company_path:
        return ""
    # If caller passed a file path, extract the directory
    if os.path.splitext(company_path)[1]:  # has file extension
        company_path = os.path.dirname(company_path)
    company_name = os.path.basename(company_path)
    return build_logical_name(company_name, company_path=company_path)

def _ensure_crm_table(db, db_name):
    """Ensure the crm_names table exists, seeded with 'Office' for new companies."""
    db.ensure_table(db_name, "crm_names", """
        CREATE TABLE crm_names (
            id INT IDENTITY(1,1) PRIMARY KEY,
            crm_name NVARCHAR(255) NOT NULL UNIQUE
        )
    """)
    # Seed default "Office" CRM for new companies
    try:
        conn = db.get_connection(db_name)
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM crm_names")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO crm_names (crm_name) VALUES (?)", "Office")
                conn.commit()
    except Exception:
        pass

def _ensure_report_table(db, db_name):
    """Ensure the report_data table exists."""
    db.ensure_table(db_name, "report_data", """
        CREATE TABLE report_data (
            id INT IDENTITY(1,1) PRIMARY KEY,
            crm_name NVARCHAR(255) NOT NULL,
            serial_no NVARCHAR(50) NOT NULL,
            status NVARCHAR(20) DEFAULT 'pending'
        )
    """)


def load_crm_list(company_path=""):
    """Load all CRM names from the Catalog DB's crm_names table.
    
    Args:
        company_path: Company folder path, or legacy file path (e.g., crm_data.json)
    
    Returns:
        List of CRM name strings.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return []
    db = get_db_manager()
    _ensure_crm_table(db, db_name)
    rows = db.execute_query(db_name, "SELECT crm_name FROM crm_names ORDER BY id")
    return [r[0] for r in rows] if rows else []


def save_crm_to_json(name, company_path=""):
    """Add a new CRM name to the Catalog DB's crm_names table.
    
    Args:
        name: CRM name to add
        company_path: Company folder path, or legacy file path
    
    Returns:
        True on success, False on failure.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return False
    db = get_db_manager()
    _ensure_crm_table(db, db_name)
    try:
        conn = db.get_connection(db_name)
        if not conn:
            return False
        cursor = conn.cursor()
        # Check if already exists (case-insensitive)
        cursor.execute("SELECT COUNT(*) FROM crm_names WHERE crm_name = ?", name)
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO crm_names (crm_name) VALUES (?)", name)
            conn.commit()
        return True
    except Exception:
        return False


def update_crm_in_json(old_name, new_name, company_path=""):
    """Rename a CRM in the Catalog DB's crm_names table.
    
    Args:
        old_name: Current CRM name
        new_name: New CRM name
        company_path: Company folder path, or legacy file path
    
    Returns:
        True on success, False on failure.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return False
    db = get_db_manager()
    try:
        conn = db.get_connection(db_name)
        if not conn:
            return False
        cursor = conn.cursor()
        cursor.execute("UPDATE crm_names SET crm_name = ? WHERE crm_name = ?", (new_name, old_name))
        # Also update report_data references
        cursor.execute("UPDATE report_data SET crm_name = ? WHERE crm_name = ?", (new_name, old_name))
        conn.commit()
        return True
    except Exception:
        return False

    
def load_report_json(company_path=""):
    """Load report data from the Catalog DB's report_data table.
    
    Returns a dict matching the legacy JSON structure:
        { "CRM_Name": { "pending": [...], "recent": [...] }, ... }
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return {}
    db = get_db_manager()
    _ensure_report_table(db, db_name)
    rows = db.execute_query(db_name,
        "SELECT crm_name, serial_no, status FROM report_data ORDER BY crm_name, id")
    if not rows:
        return {}
    result = {}
    for crm_name, serial_no, status in rows:
        if crm_name not in result:
            result[crm_name] = {"pending": [], "recent": []}
        bucket = "pending" if status == "pending" else "recent"
        result[crm_name][bucket].append(serial_no)
    return result


def save_report_json(data, company_path=""):
    """Save report data to the Catalog DB's report_data table.
    
    Args:
        data: Dict matching legacy structure { "CRM_Name": {"pending": [...], "recent": [...]} }
        company_path: Company folder path, or legacy file path
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return
    db = get_db_manager()
    _ensure_report_table(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    cursor = conn.cursor()
    try:
        # ── Cross-machine lock ──────────────────────────────────────────
        # Serializes the read-modify-write cycle so two concurrent builds
        # on different machines don't overwrite each other's CRM changes.
        try:
            cursor.execute("""
                EXEC sp_getapplock
                    @Resource    = 'JKCatalog_ReportData',
                    @LockMode    = 'Exclusive',
                    @LockOwner   = 'Transaction',
                    @LockTimeout = 10000
            """)
        except Exception:
            pass  # proceed without lock if unavailable

        # Crash-safe replacement: INSERT new rows first, THEN delete old ones.
        # If we crash after insert but before delete, we get duplicates (harmless,
        # cleaned up on next save) rather than total data loss.
        
        # 1. Record the highest existing ID (everything at or below this is "old")
        cursor.execute("SELECT ISNULL(MAX(id), 0) FROM report_data")
        old_max_id = cursor.fetchone()[0]
        
        # 2. Insert all new rows (they get IDs > old_max_id)
        for crm_name, buckets in data.items():
            if not isinstance(buckets, dict):
                continue
            for serial_no in buckets.get("pending", []):
                cursor.execute(
                    "INSERT INTO report_data (crm_name, serial_no, status) VALUES (?, ?, 'pending')",
                    (crm_name, str(serial_no)))
            for serial_no in buckets.get("recent", []):
                cursor.execute(
                    "INSERT INTO report_data (crm_name, serial_no, status) VALUES (?, ?, 'completed')",
                    (crm_name, str(serial_no)))
        
        # 3. Delete old rows (safe — new rows are already written)
        if old_max_id > 0:
            cursor.execute("DELETE FROM report_data WHERE id <= ?", (old_max_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"save_report_json failed: {e}", exc_info=True)


def add_pages_to_all_crms(page_serial_numbers, company_path):
    """Add page serial numbers to all CRMs' pending lists.
    
    Args:
        page_serial_numbers: List of page serial numbers (from catalog_pages.serial_no)
        company_path: Path to company folder
    
    Returns:
        Number of CRMs updated
    """
    if not page_serial_numbers:
        return 0
    
    pages_to_add = [str(p) for p in page_serial_numbers]
    crm_list = load_crm_list(company_path)
    
    if not crm_list:
        return 0
    
    report_data = load_report_json(company_path)
    
    updated_count = 0
    
    for crm_name in crm_list:
        if crm_name not in report_data:
            report_data[crm_name] = {"pending": [], "recent": []}
        
        current_pending = report_data[crm_name].get("pending", [])
        if not isinstance(current_pending, list):
            current_pending = []
        
        added_any = False
        for page in pages_to_add:
            if page not in current_pending:
                current_pending.append(page)
                added_any = True
        
        if added_any:
            report_data[crm_name]["pending"] = current_pending
            updated_count += 1
    
    save_report_json(report_data, company_path)
    
    return updated_count