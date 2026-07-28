"""
Year End Logic - Creates a new company from the current one.

Workflow:
  1. Create new company folder (sibling of current company)
  2. BACKUP current company DB to temp .bak
  3. RESTORE .bak under new logical DB name
  4. Copy non-DB files (images, config) to new company folder
  5. Apply Option A cheque processing:
       - Delete cleared cheques (clear_date not blank)
       - Keep pending cheques with their ORIGINAL SN values
       - Buffer rows are regenerated automatically by sync_cheque_rows on load
"""

import os
import shutil
import tempfile

from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

_DB_EXTENSIONS = {'.mdf', '.ldf', '.bak', '.db', '.db-wal', '.db-shm'}
_SKIP_PREFIXES  = {'.jk_'}


def perform_year_end(company_path, new_company_name, progress_cb=None):
    """Perform Year End: create a new company from the current one.

    Args:
        company_path (str): Absolute path to the current company folder.
        new_company_name (str): Name for the new company (folder name).
        progress_cb: Optional callable(step_text, current, total).

    Returns:
        (success: bool, message: str, new_company_path: str)
    """
    TOTAL = 6

    def emit(text, n):
        if progress_cb:
            try: progress_cb(text, n, TOTAL)
            except Exception: pass

    db = get_db_manager()

    company_path     = os.path.normpath(os.path.abspath(company_path))
    data_path        = os.path.dirname(company_path)
    new_company_path = os.path.join(data_path, new_company_name)

    if os.path.exists(new_company_path):
        return (False,
                f"A folder named '{new_company_name}' already exists at:\n{data_path}\n\n"
                "Please choose a different name.", "")

    old_name    = os.path.basename(company_path)
    old_db_name = build_logical_name(old_name, company_path=company_path)
    new_db_name = build_logical_name(new_company_name, company_path=new_company_path)

    if not db.database_exists(old_db_name):
        return (False,
                f"Source database not found: {old_db_name}\n\n"
                "Make sure the current company is fully loaded.", "")

    emit("Creating new company folder...", 1)
    try:
        os.makedirs(new_company_path, exist_ok=False)
    except OSError as e:
        return False, f"Could not create folder:\n{new_company_path}\n\n{e}", ""

    temp_dir = tempfile.mkdtemp(prefix=".jk_ye_", dir=data_path)
    bak_path = os.path.join(temp_dir, "year_end.bak")

    try:
        emit("Backing up current database...", 2)
        db._grant_sql_server_permissions(temp_dir)
        if not db.backup_database(old_db_name, bak_path):
            return False, "Database backup failed.\nCheck SQL Server has write access to the data folder.", ""

        emit("Restoring database for new company...", 3)
        if not db.restore_database(new_db_name, bak_path, new_company_path):
            return False, "Database restore failed.\nSee the application log for details.", ""

        emit("Copying company files...", 4)
        _copy_company_files(company_path, new_company_path)

        emit("Processing cheque list for Year End...", 5)
        _process_cheque_year_end(db, new_db_name)

        emit("Year End complete!", 6)
        return (True,
                f"Year End completed successfully!\n\nNew company '{new_company_name}' is ready.",
                new_company_path)

    except Exception as exc:
        logger.error(f"perform_year_end failed: {exc}", exc_info=True)
        return False, f"Year End encountered an unexpected error:\n{exc}", ""

    finally:
        try: shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception: pass


def _copy_company_files(src_path, dst_path):
    """Copy non-database files (images, config) from old to new company folder."""
    for item in os.listdir(src_path):
        if any(item.startswith(p) for p in _SKIP_PREFIXES):
            continue
        src = os.path.join(src_path, item)
        dst = os.path.join(dst_path, item)
        if os.path.isfile(src):
            if os.path.splitext(item)[1].lower() not in _DB_EXTENSIONS:
                try: shutil.copy2(src, dst)
                except Exception as e: logger.warning(f"Could not copy {src}: {e}")
        elif os.path.isdir(src):
            try: shutil.copytree(src, dst, dirs_exist_ok=True)
            except Exception as e: logger.warning(f"Could not copy folder {src}: {e}")


def _process_cheque_year_end(db, db_name):
    """Option A: remove cleared cheques, keep pending cheques with original SNs.

    Buffer rows (empty placeholders) are NOT recreated here; sync_cheque_rows()
    regenerates them automatically when the new company is first loaded.
    """
    conn = db.get_connection(db_name)
    if not conn:
        logger.warning(f"[YearEnd] No connection to {db_name} - skipping cheque processing")
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='cheques'"
        )
        if not (cursor.fetchone() or [0])[0]:
            logger.info("[YearEnd] No cheques table - skipping")
            return

        cursor.execute("""
            SELECT sn, date, party, bank, chq_no, crm, amount, status, clear_date, narration
            FROM   cheques
            WHERE  ISNULL(LTRIM(RTRIM(CAST(clear_date AS NVARCHAR(MAX)))), '') = ''
            ORDER  BY TRY_CAST(sn AS INT) ASC
        """)
        pending = cursor.fetchall()

        cursor.execute("DELETE FROM cheques")
        for chq in pending:
            cursor.execute(
                "INSERT INTO cheques"
                " (sn, date, party, bank, chq_no, crm, amount, status, clear_date, narration)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(chq)
            )
        conn.commit()
        logger.info(f"[YearEnd] Kept {len(pending)} pending cheque(s), removed cleared rows")
    except Exception as exc:
        logger.error(f"[YearEnd] _process_cheque_year_end failed: {exc}", exc_info=True)
        try: conn.rollback()
        except Exception: pass
