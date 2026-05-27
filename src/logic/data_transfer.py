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
    
    # Create a temp directory INSIDE the data path (SQL Server already has permissions here)
    temp_dir = os.path.join(data_path, ".jk_export_temp")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        manifest = {
            "version": 1,
            "source_path": data_path,
            "shared_databases": [],
            "company_databases": [],
            "companies": []
        }
        
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
                manifest["company_databases"].append({
                    "folder_name": entry,
                    "display_name": display_name,
                    "db_name": logical_name,
                    "bak_file": bak_file
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
    
    # Extract to temp directory INSIDE target path (SQL Server needs read access)
    temp_dir = os.path.join(target_data_path, ".jk_import_temp")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Grant SQL Server read access to the temp dir
    db._grant_sql_server_permissions(temp_dir)
    
    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
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
