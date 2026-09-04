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


def _get_sql_data_path(db):
    """Return SQL Server's default data directory.

    Falls back to a temp subfolder inside the data_path root if the
    registry / SQL query is unavailable.
    """
    try:
        conn = db.get_master_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT SERVERPROPERTY('InstanceDefaultDataPath')"
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return str(row[0]).rstrip("\\/")
            finally:
                conn.close()
    except Exception:
        pass
    return None


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

    # Bug 2 fix: place MDF/LDF in SQL Server's data directory, NOT the company
    # folder. Falling back to a temp sub-dir next to the company data if the
    # SQL Server data path is unavailable.
    sql_data_dir = _get_sql_data_path(db)
    if not sql_data_dir or not os.path.isdir(sql_data_dir):
        # Fallback: use a hidden staging folder next to the company folders
        sql_data_dir = os.path.join(data_path, ".jk_sql_data")
        os.makedirs(sql_data_dir, exist_ok=True)
        db._grant_sql_server_permissions(sql_data_dir)

    temp_dir = tempfile.mkdtemp(prefix=".jk_ye_", dir=data_path)
    bak_path = os.path.join(temp_dir, "year_end.bak")
    _new_folder_created = True  # track so we can clean up on failure

    try:
        emit("Backing up current database...", 2)
        # backup_database() calls _grant_sql_server_permissions internally —
        # no need to call it again here (Bug 1 fix: removed duplicate call).
        if not db.backup_database(old_db_name, bak_path):
            return False, "Database backup failed.\nCheck SQL Server has write access to the data folder.", ""

        emit("Restoring database for new company...", 3)
        # Bug 2 fix: restore MDF/LDF into sql_data_dir, not new_company_path
        if not db.restore_database(new_db_name, bak_path, sql_data_dir):
            return False, "Database restore failed.\nSee the application log for details.", ""

        emit("Copying company files...", 4)
        _copy_company_files(company_path, new_company_path)

        emit("Processing cheque list for Year End...", 5)
        _process_cheque_year_end(db, new_db_name)

        emit("Year End complete!", 6)
        _new_folder_created = False  # success — do not clean up
        return (True,
                f"Year End completed successfully!\n\nNew company '{new_company_name}' is ready.",
                new_company_path)

    except Exception as exc:
        logger.error(f"perform_year_end failed: {exc}", exc_info=True)
        return False, f"Year End encountered an unexpected error:\n{exc}", ""

    finally:
        try: shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception: pass
        # Bug 5 fix: remove the half-created company folder on failure so the
        # user doesn't have to manually delete it before retrying.
        if _new_folder_created and os.path.exists(new_company_path):
            try:
                shutil.rmtree(new_company_path, ignore_errors=True)
                logger.info(f"[YearEnd] Cleaned up failed company folder: {new_company_path}")
            except Exception:
                pass


def _copy_company_files(src_path, dst_path):
    """Copy non-database files (images, config) from old to new company folder.

    Bug 3 fix: the DB extension filter is applied recursively so no .mdf/.ldf
    files inside sub-folders can accidentally collide with the restored DB.
    """
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
            # Copy directory tree but skip any DB files inside sub-folders
            try:
                _copy_dir_filtered(src, dst)
            except Exception as e:
                logger.warning(f"Could not copy folder {src}: {e}")


def _copy_dir_filtered(src_dir, dst_dir):
    """Recursively copy src_dir -> dst_dir, skipping DB extension files."""
    os.makedirs(dst_dir, exist_ok=True)
    for item in os.listdir(src_dir):
        if any(item.startswith(p) for p in _SKIP_PREFIXES):
            continue
        src = os.path.join(src_dir, item)
        dst = os.path.join(dst_dir, item)
        if os.path.isfile(src):
            if os.path.splitext(item)[1].lower() not in _DB_EXTENSIONS:
                try: shutil.copy2(src, dst)
                except Exception as e: logger.warning(f"Could not copy {src}: {e}")
        elif os.path.isdir(src):
            _copy_dir_filtered(src, dst)


def _process_cheque_year_end(db, db_name):
    """Option A: remove cleared cheques, keep pending cheques with original SNs.

    Preserves party_guid (Tally GUID) and bank_ref (UUID) so that all Tally
    ledger links and bank identity references survive the year-end rollover.

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

        # Detect whether the cheques table has the party_guid / bank_ref columns
        # (added in the Tally sync migration). Older DBs will not have them yet.
        cursor.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME='cheques' ORDER BY ORDINAL_POSITION"
        )
        existing_cols = [r[0] for r in cursor.fetchall()]
        has_guid = "party_guid" in existing_cols
        has_bref = "bank_ref"   in existing_cols

        if has_guid and has_bref:
            # ── Full schema (12-column) ──────────────────────────────────────
            # Select ALL columns including Tally GUIDs so they survive rollover.
            cursor.execute("""
                SELECT sn, date, party, bank, chq_no, crm, amount,
                       status, clear_date, narration, party_guid, bank_ref
                FROM   cheques
                WHERE  ISNULL(LTRIM(RTRIM(CAST(clear_date AS NVARCHAR(MAX)))), '') = ''
                ORDER  BY TRY_CAST(sn AS INT) ASC
            """)
            pending = cursor.fetchall()
            insert_sql = (
                "INSERT INTO cheques"
                " (sn, date, party, bank, chq_no, crm, amount,"
                "  status, clear_date, narration, party_guid, bank_ref)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            )
        else:
            # ── Legacy schema (10-column) — migration not yet applied ────────
            cursor.execute("""
                SELECT sn, date, party, bank, chq_no, crm, amount, status, clear_date, narration
                FROM   cheques
                WHERE  ISNULL(LTRIM(RTRIM(CAST(clear_date AS NVARCHAR(MAX)))), '') = ''
                ORDER  BY TRY_CAST(sn AS INT) ASC
            """)
            pending = cursor.fetchall()
            insert_sql = (
                "INSERT INTO cheques"
                " (sn, date, party, bank, chq_no, crm, amount, status, clear_date, narration)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)"
            )

        cursor.execute("DELETE FROM cheques")

        if pending:
            # Single batch insert — avoids N individual round-trips to SQL Server.
            cursor.executemany(insert_sql, [tuple(row) for row in pending])

        conn.commit()
        logger.info(f"[YearEnd] Kept {len(pending)} pending cheque(s), removed cleared rows")
    except Exception as exc:
        logger.error(f"[YearEnd] _process_cheque_year_end failed: {exc}", exc_info=True)
        try: conn.rollback()
        except Exception: pass
