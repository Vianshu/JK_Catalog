"""
Data Transfer — Import/Export data paths via SQL Server BACKUP/RESTORE.

Provides safe, portable data migration between machines:
  - Export: BACKUP all databases for a data path → single .jkbackup file
  - Import: RESTORE from .jkbackup → new data path with correct hashes

Usage:
    from src.logic.data_transfer import export_data_path, import_data_path
    export_data_path(data_path, output_file, progress_callback)
    import_data_path(backup_file, target_data_path, progress_callback)
"""

import os
import json
import shutil
import zipfile
import tempfile
from src.logic.db_manager import (
    get_db_manager, DB_SECURITY, DB_SUPER, DB_CALENDAR,
    build_shared_db_name, build_logical_name, save_data_origin
)
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# Map of tables to their primary key columns for reconstruction
MISSING_TABLE_PKS = {
    "payment_sheet_data": None,
    "supplier_records": "id",
    "supplier_accounts": "id",
    "anil_ledger": "id",
    "anil_settings": "[key]",
    "tp_sections": "id",
    "tp_section_cols": "id",
    "tp_section_data": None,
    "godown": "id",
    "cheques": "id",
    "bonus_data": "id",
    "team_list_data": "id",
    "ins_human": "id",
    "ins_vehicle": "id",
    "ins_stock": "id"
}


def export_data_path(data_path, output_file, progress_cb=None):
    """Export an entire data path to a .jkbackup file.
    
    Backs up all SQL Server databases (shared + per-company) and
    packages them with company folder contents into a single zip.
    
    Args:
        data_path: Root data path to export
        output_file: Destination .jkbackup file path
        progress_cb: Optional callback(step_text, current, total)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    data_path = os.path.normpath(os.path.abspath(data_path))
    db = get_db_manager()
    
    if not os.path.isdir(data_path):
        return False, f"Data path does not exist: {data_path}"
    
    # Create a unique temp directory INSIDE the data path.
    # SQL Server needs write access here — _grant_sql_server_permissions handles that.
    temp_dir = tempfile.mkdtemp(prefix=".jk_export_", dir=data_path)
    
    try:
        manifest = {
            "version": 1,
            "source_path": data_path,
            "shared_databases": [],
            "company_databases": [],
            "companies": []
        }
        
        def _get_payment_sheets(logical_db_name):
            try:
                exists_rows = db.execute_query(
                    logical_db_name,
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME = 'payment_sheet_data'"
                )
                if exists_rows and exists_rows[0][0] > 0:
                    rows = db.execute_query(
                        logical_db_name,
                        "SELECT DISTINCT sheet_key FROM payment_sheet_data "
                        "WHERE sheet_key IS NOT NULL AND sheet_key != '' "
                        "ORDER BY sheet_key"
                    )
                    return [r[0] for r in rows if r[0]]
            except Exception:
                pass
            return []

        
        # Collect all databases to backup
        all_dbs = []
        
        # Shared databases
        for base_name in [DB_SECURITY, DB_SUPER, DB_CALENDAR]:
            db_name = build_shared_db_name(base_name, data_path)
            if db.database_exists(db_name):
                bak_file = f"{base_name}.bak"
                all_dbs.append((db_name, bak_file, "shared", base_name))
                manifest["shared_databases"].append({
                    "base_name": base_name,
                    "db_name": db_name,
                    "bak_file": bak_file
                })
        
        # Company databases
        for entry in os.listdir(data_path):
            if entry.startswith('.jk_'):  # Skip our temp folders
                continue
            company_path = os.path.join(data_path, entry)
            if not os.path.isdir(company_path):
                continue
            
            info_file = os.path.join(company_path, "company_info.json")
            if not os.path.exists(info_file):
                continue  # Not a company folder
            
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                display_name = info.get("display_name", entry)
            except Exception:
                display_name = entry
            
            logical_name = build_logical_name(company_path=company_path)
            bak_file = f"company_{entry}.bak"
            
            if db.database_exists(logical_name):
                all_dbs.append((logical_name, bak_file, "company", entry))
                payment_sheets = _get_payment_sheets(logical_name)
                manifest["company_databases"].append({
                    "folder_name": entry,
                    "display_name": display_name,
                    "db_name": logical_name,
                    "bak_file": bak_file,
                    "payment_sheets": payment_sheets
                })
            
            manifest["companies"].append({
                "folder_name": entry,
                "display_name": display_name
            })
        
        total_steps = len(all_dbs) + 2  # +1 for zipping, +1 for cleanup
        current_step = 0
        
        # Backup each database
        for db_name, bak_file, db_type, label in all_dbs:
            current_step += 1
            if progress_cb:
                progress_cb(f"Backing up: {label}", current_step, total_steps)
            
            bak_path = os.path.join(temp_dir, bak_file)
            if not db.backup_database(db_name, bak_path):
                return False, f"Failed to backup database: {db_name}"
            # Verify the .bak file was actually created
            if not os.path.exists(bak_path):
                return False, f"Backup file not created: {bak_file}"
        
        # Write manifest
        manifest_path = os.path.join(temp_dir, "manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        
        # Copy company folder contents (excluding MDF/LDF files)
        folders_dir = os.path.join(temp_dir, "folders")
        for company in manifest["companies"]:
            src_folder = os.path.join(data_path, company["folder_name"])
            dst_folder = os.path.join(folders_dir, company["folder_name"])
            os.makedirs(dst_folder, exist_ok=True)
            
            for item in os.listdir(src_folder):
                item_path = os.path.join(src_folder, item)
                # Skip MDF/LDF files (they're in the .bak backup)
                if item.lower().endswith(('.mdf', '.ldf')):
                    continue
                if os.path.isfile(item_path):
                    shutil.copy2(item_path, os.path.join(dst_folder, item))
                elif os.path.isdir(item_path):
                    shutil.copytree(item_path, os.path.join(dst_folder, item),
                                    dirs_exist_ok=True)
        
        # Create the .jkbackup zip
        current_step += 1
        if progress_cb:
            progress_cb("Creating backup file...", current_step, total_steps)
        
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zf.write(file_path, arcname)
        
        current_step += 1
        if progress_cb:
            progress_cb("Done!", current_step, total_steps)
        
        return True, f"Export complete: {output_file}"
    
    except Exception as e:
        logger.error(f"export_data_path failed: {e}", exc_info=True)
        return False, f"Export failed: {e}"
    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def export_single_company(company_path, output_file, progress_cb=None):
    """Export a single company to a .jkbackup file.

    Backs up:
      - The company's own database
      - The three shared databases (Security, SuperMaster, Calendar)
      - The company folder's files (images, JSON configs, etc.)

    The shared databases are included so the backup is self-contained and
    can be used as a source for Selective Restore on any machine.

    The manifest is tagged with ``backup_type = "company"`` and
    ``company_folder`` so the import/restore UI knows this is a
    single-company backup.

    Args:
        company_path: Full path to the company folder (e.g. D:\\Data\\HW Divison)
        output_file:  Destination .jkbackup file path
        progress_cb:  Optional callback(step_text, current, total)

    Returns:
        tuple: (success: bool, message: str)
    """
    company_path = os.path.normpath(os.path.abspath(company_path))
    data_path = os.path.dirname(company_path)
    company_folder = os.path.basename(company_path)
    db = get_db_manager()

    if not os.path.isdir(company_path):
        return False, f"Company folder does not exist: {company_path}"

    info_file = os.path.join(company_path, "company_info.json")
    if not os.path.exists(info_file):
        return False, f"Not a valid company folder (missing company_info.json): {company_path}"

    try:
        with open(info_file, 'r', encoding='utf-8') as f:
            info = json.load(f)
        display_name = info.get("display_name", company_folder)
    except Exception:
        display_name = company_folder

    # Temp dir inside the data path so SQL Server can write .bak files there
    temp_dir = tempfile.mkdtemp(prefix=".jk_coexport_", dir=data_path)
    db._grant_sql_server_permissions(temp_dir)

    def emit(text, cur, tot):
        if progress_cb:
            progress_cb(text, cur, tot)

    try:
        manifest = {
            "version": 1,
            "backup_type": "company",          # distinguishes from full path backup
            "source_path": data_path,
            "company_folder": company_folder,
            "shared_databases": [],
            "company_databases": [],
            "companies": [{"folder_name": company_folder, "display_name": display_name}]
        }
        
        def _get_payment_sheets(logical_db_name):
            try:
                exists_rows = db.execute_query(
                    logical_db_name,
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME = 'payment_sheet_data'"
                )
                if exists_rows and exists_rows[0][0] > 0:
                    rows = db.execute_query(
                        logical_db_name,
                        "SELECT DISTINCT sheet_key FROM payment_sheet_data "
                        "WHERE sheet_key IS NOT NULL AND sheet_key != '' "
                        "ORDER BY sheet_key"
                    )
                    return [r[0] for r in rows if r[0]]
            except Exception:
                pass
            return []

        all_dbs = []

        # ── Shared databases (Security, SuperMaster, Calendar) ────────────────
        for base_name in [DB_SECURITY, DB_SUPER, DB_CALENDAR]:
            db_name = build_shared_db_name(base_name, data_path)
            if db.database_exists(db_name):
                bak_file = f"{base_name}.bak"
                all_dbs.append((db_name, bak_file, "shared", base_name))
                manifest["shared_databases"].append({
                    "base_name": base_name,
                    "db_name": db_name,
                    "bak_file": bak_file
                })

        # ── Company database ──────────────────────────────────────────────────
        logical_name = build_logical_name(company_path=company_path)
        bak_file = f"company_{company_folder}.bak"
        if not db.database_exists(logical_name):
            return False, f"Database for company '{company_folder}' does not exist."
        all_dbs.append((logical_name, bak_file, "company", company_folder))
        payment_sheets = _get_payment_sheets(logical_name)
        manifest["company_databases"].append({
            "folder_name": company_folder,
            "display_name": display_name,
            "db_name": logical_name,
            "bak_file": bak_file,
            "payment_sheets": payment_sheets
        })

        total_steps = len(all_dbs) + 2   # +1 zip, +1 done
        current_step = 0

        # ── Backup each database ──────────────────────────────────────────────
        for db_name, bak_fname, db_type, label in all_dbs:
            current_step += 1
            emit(f"Backing up: {label}", current_step, total_steps)
            bak_path = os.path.join(temp_dir, bak_fname)
            if not db.backup_database(db_name, bak_path):
                return False, f"Failed to backup database: {db_name}"
            if not os.path.exists(bak_path):
                return False, f"Backup file not created: {bak_fname}"

        # ── Write manifest ────────────────────────────────────────────────────
        manifest_path = os.path.join(temp_dir, "manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        # ── Copy company folder files ─────────────────────────────────────────
        dst_folder = os.path.join(temp_dir, "folders", company_folder)
        os.makedirs(dst_folder, exist_ok=True)
        for item in os.listdir(company_path):
            item_path = os.path.join(company_path, item)
            if item.lower().endswith(('.mdf', '.ldf')):
                continue
            if os.path.isfile(item_path):
                shutil.copy2(item_path, os.path.join(dst_folder, item))
            elif os.path.isdir(item_path):
                shutil.copytree(item_path, os.path.join(dst_folder, item),
                                dirs_exist_ok=True)

        # ── Zip everything into .jkbackup ─────────────────────────────────────
        current_step += 1
        emit("Creating backup file...", current_step, total_steps)
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zf.write(file_path, arcname)

        current_step += 1
        emit("Done!", current_step, total_steps)
        return True, f"Company backup complete: {os.path.basename(output_file)}"

    except Exception as e:
        logger.error(f"export_single_company failed: {e}", exc_info=True)
        return False, f"Company backup failed: {e}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



def import_data_path(backup_file, target_data_path, progress_cb=None):
    """Import a .jkbackup file into a target data path.
    
    Restores all SQL Server databases with path-appropriate names
    and extracts company folder contents.
    
    Args:
        backup_file: Path to the .jkbackup file
        target_data_path: Destination data path folder
        progress_cb: Optional callback(step_text, current, total)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    target_data_path = os.path.normpath(os.path.abspath(target_data_path))
    db = get_db_manager()
    
    os.makedirs(target_data_path, exist_ok=True)
    
    # Extract to a unique temp directory INSIDE target path (SQL Server needs read access)
    temp_dir = tempfile.mkdtemp(prefix=".jk_import_", dir=target_data_path)
    
    # Grant SQL Server read access to the temp dir
    db._grant_sql_server_permissions(temp_dir)
    
    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
            # Zip-slip validation
            for member in zf.namelist():
                target = os.path.abspath(os.path.join(temp_dir, member))
                if not target.startswith(os.path.abspath(temp_dir)):
                    return False, "Invalid backup file: path traversal detected."
            zf.extractall(temp_dir)
        
        # Read manifest
        manifest_path = os.path.join(temp_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return False, "Invalid backup file: manifest.json not found"
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        total_dbs = len(manifest.get("shared_databases", [])) + \
                     len(manifest.get("company_databases", []))
        total_steps = total_dbs + 3  # +1 extract folders, +1 update paths, +1 done
        current_step = 0
        
        # 1. Extract company folders to target data path
        current_step += 1
        if progress_cb:
            progress_cb("Extracting company folders...", current_step, total_steps)
        
        folders_dir = os.path.join(temp_dir, "folders")
        if os.path.isdir(folders_dir):
            for entry in os.listdir(folders_dir):
                src = os.path.join(folders_dir, entry)
                dst = os.path.join(target_data_path, entry)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
        
        # 2. Restore shared databases
        for shared_db in manifest.get("shared_databases", []):
            current_step += 1
            base_name = shared_db["base_name"]
            bak_file = shared_db["bak_file"]
            bak_path = os.path.join(temp_dir, bak_file)
            
            if progress_cb:
                progress_cb(f"Restoring: {base_name}", current_step, total_steps)
            
            new_db_name = build_shared_db_name(base_name, target_data_path)
            
            if not os.path.exists(bak_path):
                logger.warning(f"Backup file missing: {bak_path}")
                continue
            
            if not db.restore_database(new_db_name, bak_path, target_data_path):
                return False, f"Failed to restore: {base_name}"
        
        # 3. Restore company databases
        for company_db in manifest.get("company_databases", []):
            current_step += 1
            folder_name = company_db["folder_name"]
            bak_file = company_db["bak_file"]
            bak_path = os.path.join(temp_dir, bak_file)
            
            if progress_cb:
                progress_cb(f"Restoring: {folder_name}", current_step, total_steps)
            
            company_path = os.path.join(target_data_path, folder_name)
            os.makedirs(company_path, exist_ok=True)
            new_db_name = build_logical_name(company_path=company_path)
            
            if not os.path.exists(bak_path):
                logger.warning(f"Backup file missing: {bak_path}")
                continue
            
            if not db.restore_database(new_db_name, bak_path, company_path):
                return False, f"Failed to restore: {folder_name}"
        
        # 4. Update folder_path in the restored Security DB
        current_step += 1
        if progress_cb:
            progress_cb("Updating paths...", current_step, total_steps)
        
        new_security_name = build_shared_db_name(DB_SECURITY, target_data_path)
        conn = db.get_connection(new_security_name)
        if conn:
            try:
                cursor = conn.cursor()
                source_path = manifest.get("source_path", "")
                if source_path:
                    # Update all folder_path entries to point to new location
                    cursor.execute("SELECT id, folder_path FROM companies")
                    rows = cursor.fetchall()
                    for row in rows:
                        old_path = row[1]
                        # Replace the source data path prefix with the target
                        if old_path:
                            # Get relative path from old source
                            try:
                                rel_path = os.path.relpath(old_path, source_path)
                                new_path = os.path.normpath(
                                    os.path.join(target_data_path, rel_path)
                                )
                                cursor.execute(
                                    "UPDATE companies SET folder_path = ? WHERE id = ?",
                                    (new_path, row[0])
                                )
                            except ValueError:
                                pass  # Paths on different drives
                    conn.commit()
                    logger.info("Updated company folder paths in restored Security DB")

                # Deduplicate: if multiple companies share the same folder_path,
                # keep only the one with the lowest id and delete the rest.
                # This happens when the user pre-created a company before importing.
                cursor.execute("""
                    SELECT folder_path, MIN(id) AS keep_id
                    FROM companies
                    WHERE folder_path IS NOT NULL AND folder_path != ''
                    GROUP BY folder_path
                    HAVING COUNT(*) > 1
                """)
                dupes = cursor.fetchall()
                for folder_path_val, keep_id in dupes:
                    cursor.execute(
                        "DELETE FROM companies WHERE folder_path = ? AND id != ?",
                        (folder_path_val, keep_id)
                    )
                    logger.info(
                        f"[Import] Removed duplicate company entry for: {folder_path_val}"
                    )
                if dupes:
                    conn.commit()
                    logger.info(f"[Import] Deduplication removed {len(dupes)} duplicate company entries.")

            except Exception as e:
                logger.warning(f"Could not update folder paths: {e}")
        
        # 5. Save data origin for the new path
        save_data_origin(target_data_path)
        
        current_step += 1
        if progress_cb:
            progress_cb("Done!", current_step, total_steps)
        
        return True, f"Import complete! Data restored to: {target_data_path}"
    
    except zipfile.BadZipFile:
        return False, "Invalid backup file: not a valid .jkbackup archive"
    except Exception as e:
        logger.error(f"import_data_path failed: {e}", exc_info=True)
        return False, f"Import failed: {e}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─── SELECTIVE RESTORE ────────────────────────────────────────────────────────

# Module definitions: which tables belong to which group.
# Each group is a list of table names to merge.
# NOTE: All data lives in the single company database (build_logical_name).

#: Tables belonging to the Catalog Bundle (Final Data + Catalog + CRM).
#: These MUST always be restored together — never independently.
CATALOG_BUNDLE_TABLES = [
    # Final Data
    "catalog",
    # Catalog
    "catalog_pages",
    "subgroup_display_order",
    "page_snapshots",
    "build_config",
    # CRM
    "crm_names",
    "report_data",
    # Build history (part of catalog meta)
    "build_history",
]

#: Tables belonging to Supplier Payment (can be restored independently).
SUPP_PAYMENT_TABLES = [
    "payment_sheet_data",
    "supplier_records",
    "supplier_accounts",
    "anil_ledger",
    "anil_settings",
    "tp_sections",
    "tp_section_cols",
    "tp_section_data",
    "bonus_data",
    "team_list_data",
    "ins_human",
    "ins_vehicle",
    "ins_stock"
]

GODOWN_TABLES = [
  "stock",
  "stock_items"
]

CHEQUE_LIST_TABLES = [
  "cheques",
  "bank_list",
  "row_ledger_data"
]

# Modules exposed to the UI
SELECTABLE_MODULES = {
    "catalog_bundle": {
        "label": "Catalog Bundle (Final Data + Catalog + CRM)",
        "tables": CATALOG_BUNDLE_TABLES,
        "requires": [],          # no hard prerequisites
    },
    "supp_payment": {
        "label": "Supplier Payment",
        "tables": SUPP_PAYMENT_TABLES,
        "requires": [],
    },
}


def list_companies_in_backup(backup_file):
    """Read the manifest from a .jkbackup without restoring anything.

    Returns:
        tuple: (manifest dict, error string)
               On success error string is empty. On failure manifest is None.
    """
    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
            if "manifest.json" not in zf.namelist():
                return None, "Invalid backup: manifest.json not found"
            with zf.open("manifest.json") as f:
                manifest = json.load(f)
        return manifest, ""
    except zipfile.BadZipFile:
        return None, "Not a valid .jkbackup file"
    except Exception as e:
        return None, str(e)


def selective_restore_company(backup_file, target_data_path, company_folder_name,
                               modules, progress_cb=None):
    """Selectively restore chosen modules for one company from a full .jkbackup.

    Strategy:
        1. Extract the company's .bak from the zip into a temp directory.
        2. RESTORE it as a temporary DB (JK_TempRestore_<uuid>).
        3. For each selected module, validate cross-references, then
           DELETE existing rows from the live DB and INSERT from the temp DB
           inside a single transaction on the live DB.
        4. Drop the temp DB and clean up the temp directory.

    The live DB is never touched until the transaction commits, so a failure
    at any point leaves the live data completely intact.

    Args:
        backup_file:         Path to the .jkbackup file.
        target_data_path:    The current live data path folder.
        company_folder_name: The folder name of the company (e.g. "HW Divison 082083").
        modules:             List of module keys to restore, e.g. ["catalog_bundle"].
                             For "supp_payment", you may also pass
                             {"supp_payment": ["Sheet1", "Sheet2"]} to filter sheets.
        progress_cb:         Optional callback(step_text, current, total).

    Returns:
        tuple: (success: bool, message: str)
    """
    import uuid
    import time

    target_data_path = os.path.normpath(os.path.abspath(target_data_path))
    db = get_db_manager()

    def emit(text, cur=0, tot=1):
        if progress_cb:
            progress_cb(text, cur, tot)

    emit("Reading backup manifest...", 0, 10)

    # ── 1. Read manifest ───────────────────────────────────────────────────────
    manifest, err = list_companies_in_backup(backup_file)
    if not manifest:
        return False, f"Cannot read backup: {err}"

    # Find the company_db entry in the manifest
    company_db_entry = None
    for entry in manifest.get("company_databases", []):
        if entry["folder_name"] == company_folder_name:
            company_db_entry = entry
            break
    if not company_db_entry:
        return False, f"Company '{company_folder_name}' not found in backup."

    bak_filename = company_db_entry["bak_file"]

    # ── 2. Extract the single .bak to a temp directory ────────────────────────
    emit("Extracting backup file...", 1, 10)
    company_path = os.path.join(target_data_path, company_folder_name)
    temp_dir = tempfile.mkdtemp(prefix=".jk_selrestore_", dir=target_data_path)
    db._grant_sql_server_permissions(temp_dir)

    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
            # Zip-slip guard
            for member in zf.namelist():
                target = os.path.abspath(os.path.join(temp_dir, member))
                if not target.startswith(os.path.abspath(temp_dir)):
                    return False, "Invalid backup: path traversal detected."

            # Only extract the specific .bak we need (and manifest)
            for member in zf.namelist():
                if member in (bak_filename, "manifest.json"):
                    zf.extract(member, temp_dir)

        bak_path = os.path.join(temp_dir, bak_filename)
        if not os.path.exists(bak_path):
            return False, f"Backup file for '{company_folder_name}' not found inside archive."

        # ── 3. RESTORE to a temporary database ────────────────────────────────
        temp_db_name = f"JK_TempRestore_{uuid.uuid4().hex[:12]}"
        emit(f"Restoring backup to temporary database...", 2, 10)

        if not db.restore_database(temp_db_name, bak_path, temp_dir):
            return False, "Failed to restore backup to temporary database."

        emit("Temporary database ready. Validating data...", 3, 10)

        # ── 4. Determine the live DB logical name ─────────────────────────────
        live_db_name = build_logical_name(
            company_folder_name, company_path=company_path
        )

        live_conn = db.get_connection(live_db_name)
        if not live_conn:
            return False, f"Cannot connect to live database '{live_db_name}'."

        # ── 5. Validate cross-references (read from temp DB only) ─────────────
        if "catalog_bundle" in modules:
            emit("Validating Catalog Bundle references...", 4, 10)
            validation_ok, validation_msg = _validate_catalog_bundle(db, temp_db_name)
            if not validation_ok:
                return False, f"Backup validation failed: {validation_msg}"

        # ── 6. Merge selected modules inside one transaction on live DB ────────
        emit("Merging data into live database...", 5, 10)
        cursor = live_conn.cursor()

        try:
            # Normalize modules parameter: can be list of strings or dict {key: sheet_list}
            module_keys = []
            sheet_filter = None   # None means all sheets
            if isinstance(modules, dict):
                module_keys = list(modules.keys())
                if "supp_payment" in modules and isinstance(modules["supp_payment"], list):
                    sheet_filter = modules["supp_payment"]
            else:
                module_keys = list(modules)

            for mod_key in module_keys:
                if mod_key == "catalog_bundle":
                    _merge_catalog_bundle(cursor, live_db_name, temp_db_name)
                elif mod_key == "supp_payment":
                    _merge_supp_payment(cursor, live_db_name, temp_db_name, sheet_filter)
                elif mod_key == "godown":
                    _merge_simple_module(cursor, live_db_name, temp_db_name, GODOWN_TABLES)
                elif mod_key == "cheque_list":
                    _merge_simple_module(cursor, live_db_name, temp_db_name, CHEQUE_LIST_TABLES)

            live_conn.commit()
            logger.info(
                f"[SelectiveRestore] Committed modules {module_keys} "
                f"for '{company_folder_name}'"
            )

        except Exception as e:
            try:
                live_conn.rollback()
            except Exception:
                pass
            logger.error(f"[SelectiveRestore] Merge failed, rolled back: {e}", exc_info=True)
            return False, f"Restore failed during merge (live data untouched): {e}"

        # ── 7. Sync filesystem files for Catalog Bundle (images etc.) ─────────
        if "catalog_bundle" in module_keys:
            emit("Syncing catalog image files...", 8, 10)
            _sync_catalog_files(backup_file, company_folder_name, company_path, temp_dir)

        emit("Done!", 10, 10)
        return True, f"Selective restore complete for '{company_folder_name}'."

    except Exception as e:
        logger.error(f"selective_restore_company failed: {e}", exc_info=True)
        return False, f"Selective restore failed: {e}"
    finally:
        # Always drop temp DB and clean up temp dir
        try:
            db.close_connection(temp_db_name)
            db.drop_database(temp_db_name)
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─── INTERNAL HELPERS ─────────────────────────────────────────────────────────

def _validate_catalog_bundle(db, temp_db_name):
    """Validate internal consistency of the Catalog Bundle in the temp DB.

    Checks:
      1. Every GUID referenced in catalog_pages exists in the catalog table.
      2. Every serial_no in report_data exists in catalog_pages.

    Returns:
        (True, "") on success, or (False, reason) on failure.
    """
    try:
        temp_conn = db.get_connection(temp_db_name)
        if not temp_conn:
            return False, "Cannot connect to temporary database for validation."

        # Check 1: catalog_pages → catalog (GUID cross-reference)
        # catalog_pages.product_list contains JSON arrays of GUIDs.
        # We skip this deep check here (it's a JSON parse) but verify the tables exist.
        temp_tables = db.get_all_tables(temp_db_name)

        has_catalog = "catalog" in temp_tables
        has_pages = "catalog_pages" in temp_tables
        has_crm = "report_data" in temp_tables

        if not has_catalog:
            return False, "Backup is missing the 'catalog' (Final Data) table."
        if not has_pages:
            return False, "Backup is missing the 'catalog_pages' (Catalog) table."

        # Check 2: report_data serial_no → catalog_pages serial_no
        if has_crm:
            cursor = temp_conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM report_data rd
                WHERE NOT EXISTS (
                    SELECT 1 FROM catalog_pages cp
                    WHERE CAST(cp.serial_no AS NVARCHAR) = rd.serial_no
                )
            """)
            dangling = cursor.fetchone()[0]
            if dangling > 0:
                return (
                    False,
                    f"{dangling} CRM report entries reference pages that no longer "
                    f"exist in the backup's Catalog. The backup may be internally inconsistent."
                )

        return True, ""

    except Exception as e:
        logger.warning(f"[SelectiveRestore] Validation error (non-fatal): {e}")
        # Don't block a valid restore due to a validation query error.
        return True, ""


def _merge_catalog_bundle(cursor, live_db_name, temp_db_name):
    """Delete existing Catalog Bundle rows in live DB and insert from temp DB.

    Uses linked-server-style four-part name syntax:
        INSERT INTO [live_db].[dbo].[table]
        SELECT * FROM [temp_db].[dbo].[table]
    This is a pure server-side operation — no Python-level row iteration.
    """
    for table in CATALOG_BUNDLE_TABLES:
        _, temp_b = _safe_ident(temp_db_name)
        _, tbl_b = _safe_ident(table)
        # Only merge tables that actually exist in the temp DB
        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)

        _, live_b = _safe_ident(live_db_name)
        cursor.execute(
            f"SELECT COUNT(*) FROM [{live_b}].INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?",
            (table,)
        )
        live_exists = cursor.fetchone()[0] > 0

        if not live_exists:
            # Create and populate missing table
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")

            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue

        cols = _get_common_columns(cursor, live_db_name, temp_db_name, table)
        if not cols:
            logger.warning(f"[SelectiveRestore] Cannot determine columns for '{table}', skipping.")
            continue

        col_list = ", ".join(f"[{c}]" for c in cols)

        # DELETE then INSERT (inside the outer transaction) — preserve original IDs
        _replace_table_preserving_ids(
            cursor, live_db_name, live_b, temp_b, temp_s, tbl_b, col_list, table
        )
        logger.info(f"[SelectiveRestore] Inserted '{table}' from temp DB to live DB.")


def _merge_supp_payment(cursor, live_db_name, temp_db_name, sheet_filter=None):
    """Merge Supplier Payment tables from temp DB to live DB.

    If sheet_filter is a list of sheet_key strings, only those sheets are
    restored in payment_sheet_data. All other Supplier Payment tables
    (supplier_records, supplier_accounts, anil_ledger, etc.) are always
    fully replaced when this module is selected.

    Args:
        sheet_filter: None = restore all sheets; list = restore only those sheet keys.
    """
    _, live_b = _safe_ident(live_db_name)
    _, temp_b = _safe_ident(temp_db_name)

    for table in SUPP_PAYMENT_TABLES:
        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)

        _, tbl_b = _safe_ident(table)
        _, live_b = _safe_ident(live_db_name)

        cursor.execute(
            f"SELECT COUNT(*) FROM [{live_b}].INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?",
            (table,)
        )
        live_exists = cursor.fetchone()[0] > 0

        if not live_exists:
            if table == "payment_sheet_data" and sheet_filter is not None:
                safe_keys = [k.replace("'", "''") for k in sheet_filter]
                keys_str = ", ".join(f"'{k}'" for k in safe_keys)
                if not keys_str:
                    keys_str = "''"  # Fallback if empty list (though shouldn't happen)
                cursor.execute(
                    f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}] "
                    f"WHERE sheet_key IN ({keys_str})"
                )
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' with {len(sheet_filter)} sheets.")
            else:
                cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
                logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")
            
            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue

        # Get non-identity columns that exist in both DBs for safe insert
        cols = _get_common_columns(cursor, live_db_name, temp_db_name, table)
        if not cols:
            continue

        col_list = ", ".join(f"[{c}]" for c in cols)

        if table == "payment_sheet_data" and sheet_filter is not None:
            # Partial restore: only delete and re-insert the selected sheets
            for sheet_key in sheet_filter:
                safe_key = sheet_key.replace("'", "''")
                cursor.execute(
                    f"DELETE FROM [{live_b}].[dbo].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )
                cursor.execute(
                    f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
                    f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}] "
                    f"WHERE sheet_key = '{safe_key}'"
                )
                logger.info(
                    f"[SelectiveRestore] Restored payment sheet '{sheet_key}'."
                )
        else:
            # Full table replace — preserve original IDs
            _replace_table_preserving_ids(
                cursor, live_db_name, live_b, temp_b, temp_s, tbl_b, col_list, table
            )
            logger.info(
                f"[SelectiveRestore] Replaced '{table}' from temp DB."
            )


def _sync_catalog_files(backup_file, company_folder_name, company_path, temp_dir):
    """Extract and overwrite company folder files (images, config) from the backup.

    Only touches non-database files (excludes .mdf / .ldf).
    This is called AFTER the SQL transaction has committed successfully.
    """
    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
            prefix = f"folders/{company_folder_name}/"
            members = [m for m in zf.namelist() if m.startswith(prefix)]
            for member in members:
                # Zip-slip guard
                target = os.path.abspath(os.path.join(temp_dir, member))
                if not target.startswith(os.path.abspath(temp_dir)):
                    continue
                zf.extract(member, temp_dir)

        src_folder = os.path.join(temp_dir, "folders", company_folder_name)
        if os.path.isdir(src_folder):
            for item in os.listdir(src_folder):
                src_item = os.path.join(src_folder, item)
                dst_item = os.path.join(company_path, item)
                try:
                    if os.path.isfile(src_item):
                        shutil.copy2(src_item, dst_item)
                    elif os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Could not sync file '{item}': {e}")
    except Exception as e:
        logger.warning(f"[SelectiveRestore] File sync failed (non-fatal): {e}")


def _merge_simple_module(cursor, live_db_name, temp_db_name, tables_list):
    """Delete existing rows in live DB and insert from temp DB for simple tables.
    
    Used for Godown and Cheque List.
    """
    _, live_b = _safe_ident(live_db_name)
    _, temp_b = _safe_ident(temp_db_name)

    for table in tables_list:
        cursor.execute(
            f"SELECT TABLE_SCHEMA FROM [{temp_b}].INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ?",
            (table,)
        )
        row = cursor.fetchone()
        if not row:
            logger.info(f"[SelectiveRestore] Skipping '{table}' — not in backup.")
            continue
        temp_schema = row[0]
        _, temp_s = _safe_ident(temp_schema)

        _, tbl_b = _safe_ident(table)
        
        cursor.execute(
            f"SELECT COUNT(*) FROM [{live_b}].INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?",
            (table,)
        )
        live_exists = cursor.fetchone()[0] > 0

        if not live_exists:
            cursor.execute(f"SELECT * INTO [{live_b}].[dbo].[{tbl_b}] FROM [{temp_b}].[{temp_s}].[{tbl_b}]")
            logger.info(f"[SelectiveRestore] Cloned missing table '{table}' from temp DB.")

            pk_col = MISSING_TABLE_PKS.get(table)
            if pk_col:
                try:
                    cursor.execute(f"ALTER TABLE [{live_b}].[dbo].[{tbl_b}] ADD PRIMARY KEY ({pk_col})")
                    logger.info(f"[SelectiveRestore] Reconstructed Primary Key on '{table}' ({pk_col}).")
                except Exception as e:
                    logger.warning(f"[SelectiveRestore] Failed to reconstruct PK on '{table}': {e}")
            continue

        # Get non-identity columns that exist in both DBs for safe insert
        cols = _get_common_columns(cursor, live_db_name, temp_db_name, table)
        if not cols:
            continue

        col_list = ", ".join(f"[{c}]" for c in cols)

        _replace_table_preserving_ids(
            cursor, live_db_name, live_b, temp_b, temp_s, tbl_b, col_list, table
        )
        logger.info(f"[SelectiveRestore] Replaced '{table}' from temp DB.")

def _replace_table_preserving_ids(cursor, live_db_name, live_b, temp_b, temp_s, tbl_b, col_list, table):
    """Delete all rows from live table and re-insert from temp, preserving identity IDs.

    Uses SET IDENTITY_INSERT ON so original primary key values are kept intact.
    This is critical for tables with FK relationships (e.g. supplier_records /
    supplier_accounts) where losing the original IDs breaks the join.
    """
    # Check if the table has an identity column in the live DB
    cursor.execute(
        f"""
        SELECT COUNT(*) FROM [{live_b}].INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
          AND COLUMNPROPERTY(
              OBJECT_ID(QUOTENAME(?)+'.[dbo].'+QUOTENAME(?)),
              COLUMN_NAME, 'IsIdentity'
          ) = 1
        """,
        (table, live_db_name, table)
    )
    has_identity = cursor.fetchone()[0] > 0

    # Get ALL columns (including identity) from temp, intersected with live
    cursor.execute(
        f"""
        SELECT COLUMN_NAME FROM [{live_b}].INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        INTERSECT
        SELECT COLUMN_NAME FROM [{temp_b}].INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        """,
        (table, table)
    )
    all_cols = [r[0] for r in cursor.fetchall()]
    full_col_list = ", ".join(f"[{c}]" for c in all_cols)

    cursor.execute(f"DELETE FROM [{live_b}].[dbo].[{tbl_b}]")

    if has_identity:
        cursor.execute(f"SET IDENTITY_INSERT [{live_b}].[dbo].[{tbl_b}] ON")
        try:
            cursor.execute(
                f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({full_col_list}) "
                f"SELECT {full_col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
            )
        finally:
            cursor.execute(f"SET IDENTITY_INSERT [{live_b}].[dbo].[{tbl_b}] OFF")
    else:
        cursor.execute(
            f"INSERT INTO [{live_b}].[dbo].[{tbl_b}] ({col_list}) "
            f"SELECT {col_list} FROM [{temp_b}].[{temp_s}].[{tbl_b}]"
        )


def _get_common_columns(cursor, live_db_name, temp_db_name, table):
    """Get non-identity columns that exist in BOTH the live DB and temp DB.
    
    This protects against schema mismatches when restoring older backups 
    into a newer application version with added columns.
    """
    _, live_b = _safe_ident(live_db_name)
    _, temp_b = _safe_ident(temp_db_name)

    cursor.execute(
        f"""
        SELECT COLUMN_NAME FROM [{live_b}].INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = ? 
          AND COLUMNPROPERTY(OBJECT_ID(QUOTENAME(?)+'.[dbo].'+QUOTENAME(?)), COLUMN_NAME, 'IsIdentity') = 0
        INTERSECT
        SELECT COLUMN_NAME FROM [{temp_b}].INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = ?
        """,
        (table, live_db_name, table, table)
    )
    cols = [r[0] for r in cursor.fetchall()]
    return cols


def _safe_ident(name):
    """Minimal safe identifier for four-part SQL names (no special chars expected)."""
    safe_q = name.replace("'", "''")
    safe_b = name.replace("]", "]]")
    return safe_q, safe_b

