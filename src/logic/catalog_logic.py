"""
Catalog Logic v2 — Rewritten engine for catalog page layout, change detection, and data access.

Key design decisions:
  - Hash from assignments + product data only (no grid positions)
  - CRM read for sort scope, write for actual changes only
  - Idempotent builds: second run with no data changes = dirty_count: 0
"""

import os
import re
import json
import hashlib
import pyodbc
from datetime import datetime

from src.logic.db_manager import get_db_manager, build_logical_name, DB_SUPER, DB_CALENDAR, build_shared_db_name
from src.logic.text_utils import cluster_products, cluster_and_sort, clean_cat_name, is_similar
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

GRID_ROWS = 5
GRID_COLS = 4

MAX_MG_SN = 90  # Groups >= 90 are internal/system groups

_DB_SUPER = "super"
_DB_CATALOG = "catalog"
_DB_FINAL = "final"
_DB_CALENDAR = "calendar"


class CatalogLogic:
    """Core logic engine for catalog layout, page management, and change detection."""

    # ─── INIT & PATH MANAGEMENT ───────────────────────────────────────────────

    def __init__(self, db_path):
        """Initialize CatalogLogic.
        
        Args:
            db_path: Company folder path (used to derive logical DB names).
                     e.g., 'D:\\SharedData\\CompanyA\\'
        """
        self.db_path = db_path  # Company folder path
        self.company_name = os.path.basename(db_path) if db_path else ""
        self.db = get_db_manager()
        
        # Logical DB names (derived from company folder name)
        _data_path = os.path.dirname(db_path) if db_path else ""
        self.super_db_name = build_shared_db_name(DB_SUPER, _data_path) if _data_path else DB_SUPER
        self.catalog_db_name = build_logical_name(self.company_name, company_path=db_path) if self.company_name else ""
        self.final_db_name = build_logical_name(self.company_name, company_path=db_path) if self.company_name else ""
        self.calendar_db_name = build_shared_db_name(DB_CALENDAR, _data_path) if _data_path else DB_CALENDAR
        
        # Legacy path fields (kept for compatibility during transition)
        self.catalog_db_path = None
        self.final_db_path = None
        self.calendar_db_path = None
        self._layout_cache = {}
        self._product_lookup_cache = {}
        self._last_clean_check_time = None  # Timestamp guard for detect_changed_pages
        self._db_ensured = set()  # Track which DBs we've already verified exist
        self._post_sync_detected = False  # Set when post_sync_snapshot_reset flag found

    def set_paths(self, catalog_db, final_db, super_db=None):
        """Update database paths and derive logical names.
        
        During migration, this method bridges the old path-based approach
        and the new logical-name approach.
        """
        self.catalog_db_path = catalog_db
        self.final_db_path = final_db
        if super_db:
            self.db_path = super_db
        
        # Derive company name from final_db path (company folder)
        if final_db:
            # Safely handle both file paths and directory paths
            if final_db.lower().endswith('.db'):
                company_folder = os.path.dirname(final_db)
            else:
                company_folder = final_db
            self.company_name = os.path.basename(company_folder)
            _data_path = os.path.dirname(company_folder) if company_folder else ""
            self.catalog_db_name = build_logical_name(self.company_name, company_path=company_folder)
            self.final_db_name = build_logical_name(self.company_name, company_path=company_folder)
            self.super_db_name = build_shared_db_name(DB_SUPER, _data_path) if _data_path else DB_SUPER
            self.calendar_db_name = build_shared_db_name(DB_CALENDAR, _data_path) if _data_path else DB_CALENDAR
        
        self._layout_cache = {}

    def invalidate_cache(self):
        self._layout_cache = {}
        self._product_lookup_cache = {}

    def invalidate_subgroup_cache(self, group_name, sg_sn):
        cache_key = f"{group_name}|{sg_sn}"
        self._layout_cache.pop(cache_key, None)
        self._product_lookup_cache.pop(cache_key, None)

    def close(self):
        pass  # connections managed by db_manager singleton

    # ─── CONNECTION MANAGER ───────────────────────────────────────────────────

    def _get_conn(self, db_key):
        """Return a SQL Server connection for the specified database key."""
        name_map = {
            _DB_SUPER: self.super_db_name,
            _DB_CATALOG: self.catalog_db_name,
            _DB_FINAL: self.final_db_name,
            _DB_CALENDAR: self.calendar_db_name,
        }
        logical_name = name_map.get(db_key)
        if not logical_name:
            return None

        try:
            conn = self.db.get_connection(logical_name)
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to {db_key} ({logical_name}): {e}")
            return None

    def _get_catalog_conn(self):
        """Get connection to the catalog database, creating it if needed."""
        if self.catalog_db_name and self.catalog_db_name not in self._db_ensured:
            company_folder = self.db_path
            self.db.ensure_database_exists(self.catalog_db_name, company_folder)
            self._db_ensured.add(self.catalog_db_name)
        return self._get_conn(_DB_CATALOG)

    def _close_all_connections(self):
        pass  # connections managed by db_manager singleton

    # ─── SCHEMA INITIALIZATION ────────────────────────────────────────────────

    def init_catalog_db(self):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            # Ensure tables exist using INFORMATION_SCHEMA checks
            self.db.ensure_table(self.catalog_db_name, "catalog_pages", """
                CREATE TABLE catalog_pages (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    mg_sn INT,
                    group_name NVARCHAR(255),
                    sg_sn INT,
                    page_no INT,
                    serial_no INT,
                    is_printable INT DEFAULT 1,
                    product_list NVARCHAR(MAX)
                )
            """)
            self.db.ensure_table(self.catalog_db_name, "subgroup_display_order", """
                CREATE TABLE subgroup_display_order (
                    cache_key NVARCHAR(500) PRIMARY KEY,
                    product_order NVARCHAR(MAX)
                )
            """)
            self.db.ensure_table(self.catalog_db_name, "page_snapshots", """
                CREATE TABLE page_snapshots (
                    serial_no NVARCHAR(50) PRIMARY KEY,
                    content_hash NVARCHAR(255),
                    product_list NVARCHAR(MAX)
                )
            """)
            self.db.ensure_table(self.catalog_db_name, "build_config", """
                CREATE TABLE build_config (
                    [key] NVARCHAR(255) PRIMARY KEY,
                    [value] NVARCHAR(MAX)
                )
            """)
            # Check if product_list column exists in catalog_pages
            if not self.db.table_has_column(self.catalog_db_name, "catalog_pages", "product_list"):
                self.db.add_column(self.catalog_db_name, "catalog_pages", "product_list", "NVARCHAR(MAX)")
                logger.info("Schema migration: added product_list column to catalog_pages")
            self._migrate_to_explicit_assignments()
        except Exception as e:
            logger.error(f"init_catalog_db error: {e}")

    def _migrate_to_explicit_assignments(self):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM catalog_pages WHERE product_list IS NOT NULL AND LTRIM(RTRIM(product_list)) != ''"
            )
            if cursor.fetchone()[0] > 0:
                return
            cursor.execute("""
                SELECT cp.id, ps.product_list
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps
                    ON CAST(cp.serial_no AS NVARCHAR(50)) = CAST(ps.serial_no AS NVARCHAR(50))
                WHERE ps.product_list IS NOT NULL
            """)
            updates = 0
            for page_id, product_list_raw in cursor.fetchall():
                if product_list_raw:
                    try:
                        parsed = json.loads(product_list_raw)
                        if isinstance(parsed, list) and parsed:
                            normalized = json.dumps(
                                [str(n).strip().lower() for n in parsed if str(n).strip()]
                            )
                            cursor.execute(
                                "UPDATE catalog_pages SET product_list=? WHERE id=?",
                                (normalized, page_id)
                            )
                            updates += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
            conn.commit()
            if updates:
                logger.info(f"Migrated product_list for {updates} pages from snapshots")
        except Exception as e:
            logger.warning(f"_migrate_to_explicit_assignments error: {e}")

    # ─── SUPER MASTER QUERIES ─────────────────────────────────────────────────

    def _get_master_table_name(self):
        if getattr(self, "_cached_master_table", None) is not None:
            return self._cached_master_table
            
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
            """)
            for (tbl,) in cursor.fetchall():
                cols = self.db.get_table_columns(self.super_db_name, tbl)
                if "MG_SN" in cols or "mg_sn" in cols:
                    self._cached_master_table = tbl
                    return tbl
        except Exception as e:
            logger.error(f"_get_master_table_name error: {e}")
        return None

    def get_index_data(self):
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT [MG_SN], [Group_Name] FROM {table}
                WHERE [MG_SN] IS NOT NULL
                  AND LTRIM(RTRIM(CAST([MG_SN] AS NVARCHAR(50)))) NOT IN ('', '0', '00')
                  AND CAST([MG_SN] AS INTEGER) < {MAX_MG_SN}
                  AND TRIM(ISNULL([Group_Name], '')) != ''
                GROUP BY [MG_SN], [Group_Name]
                ORDER BY CAST([MG_SN] AS INTEGER)
            """)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_index_data error: {e}")
            return []

    def get_subgroups(self, group_name):
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT DISTINCT CAST([MG_SN] AS INTEGER) FROM {table} WHERE TRIM([Group_Name])=? COLLATE Latin1_General_CI_AI",
                (group_name.strip(),)
            )
            mg_row = cursor.fetchone()
            if mg_row and mg_row[0] is not None and mg_row[0] >= MAX_MG_SN:
                return []
            cursor.execute(f"""
                SELECT [SG_SN], [Sub_Group] FROM {table}
                WHERE TRIM([Group_Name])=? COLLATE Latin1_General_CI_AI
                  AND [Sub_Group] IS NOT NULL AND [Sub_Group]!=''
                GROUP BY [SG_SN], [Sub_Group]
                ORDER BY CAST([SG_SN] AS INTEGER)
            """, (group_name.strip(),))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_subgroups error: {e}")
            return []

    def get_page_data_list(self):
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT [MG_SN], [Group_Name], [SG_SN] FROM {table}
                WHERE [Group_Name] IS NOT NULL AND [SG_SN] IS NOT NULL
                  AND CAST([MG_SN] AS INTEGER) < {MAX_MG_SN}
                GROUP BY [MG_SN], [Group_Name], [SG_SN]
                ORDER BY CAST([MG_SN] AS INTEGER), CAST([SG_SN] AS INTEGER)
            """)
            results = []
            for mg_sn, group_name, sg_sn in cursor.fetchall():
                m_str = str(mg_sn).strip()
                s_str = str(sg_sn).strip()
                if not m_str or m_str == '00' or not s_str or s_str == '00':
                    continue
                results.append((mg_sn, group_name, sg_sn))
            return results
        except Exception as e:
            logger.error(f"get_page_data_list error: {e}")
            return []

    # ─── DATE CONVERSION ──────────────────────────────────────────────────────

    def get_nepali_date(self, ad_date_str):
        conn = self._get_conn(_DB_CALENDAR)
        if not conn:
            return ""
        try:
            date_only = ad_date_str.split(" ")[0] if " " in ad_date_str else ad_date_str
            cursor = conn.cursor()
            cursor.execute("SELECT bs_date FROM calendar WHERE ad_date=?", (date_only,))
            row = cursor.fetchone()
            if row:
                parts = row[0].split("-")
                if len(parts) == 3:
                    return f"{parts[2]}/{parts[1]}"
            return ""
        except Exception as e:
            logger.warning(f"get_nepali_date error: {e}")
            return ""

    # ─── PAGE CRUD ────────────────────────────────────────────────────────────

    def get_all_pages(self):
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mg_sn, group_name, sg_sn, page_no, serial_no
                FROM catalog_pages ORDER BY ISNULL(serial_no, 999999)
            """)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_all_pages error: {e}")
            return []

    def rebuild_serial_numbers(self):
        """Rebuild serial_no and page_no using a single batched SQL UPDATE.

        Uses sp_getapplock to serialize concurrent builds across machines.
        Two simultaneous builds on different clients cannot both re-number
        serials at the same time — the second waits for the first to commit.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            # Acquire exclusive application lock (held until commit/rollback).
            # LockTimeout=30000ms — fail-safe if another machine holds the lock
            # longer than 30 seconds (e.g. due to crash).
            try:
                cursor.execute("""
                    EXEC sp_getapplock
                        @Resource    = 'JKCatalog_RebuildSerials',
                        @LockMode    = 'Exclusive',
                        @LockOwner   = 'Transaction',
                        @LockTimeout = 30000
                """)
            except Exception as lock_err:
                logger.warning(f"rebuild_serial_numbers: sp_getapplock unavailable ({lock_err}) — proceeding without lock")

            # Single CTE-based UPDATE — far cheaper than N individual UPDATEs
            cursor.execute("""
                WITH numbered AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY CAST(mg_sn AS INTEGER),
                                        CAST(sg_sn AS INTEGER),
                                        CAST(page_no AS INTEGER)
                           ) AS new_serial,
                           ROW_NUMBER() OVER (
                               PARTITION BY group_name, sg_sn
                               ORDER BY CAST(page_no AS INTEGER)
                           ) AS new_page_no
                    FROM catalog_pages
                )
                UPDATE catalog_pages
                SET serial_no = numbered.new_serial,
                    page_no   = numbered.new_page_no
                FROM catalog_pages
                INNER JOIN numbered ON catalog_pages.id = numbered.id
                WHERE ISNULL(catalog_pages.serial_no, -1) != numbered.new_serial
                   OR ISNULL(catalog_pages.page_no, -1)   != numbered.new_page_no
            """)
            conn.commit()  # releases the sp_getapplock automatically
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"rebuild_serial_numbers error: {e}")


    def add_page(self, mg_sn, group_name, sg_sn):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                (group_name, sg_sn)
            )
            res = cursor.fetchone()
            next_page = (res[0] or 0) + 1
            cursor.execute(
                "INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) VALUES (?, ?, ?, ?)",
                (mg_sn, group_name, sg_sn, next_page)
            )
            conn.commit()
            return next_page
        except Exception as e:
            logger.error(f"add_page error: {e}")
            return None

    def remove_page(self, group_name, sg_sn, page_no):
        conn = self._get_catalog_conn()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?",
                (group_name, sg_sn, page_no)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"remove_page error: {e}")
            return False

    def get_page_count_for_subgroup(self, group_name, sg_sn):
        conn = self._get_catalog_conn()
        if not conn:
            return 0
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                (group_name, sg_sn)
            )
            return cursor.fetchone()[0]
        except Exception:
            return 0

    def delete_empty_pages(self, empty_list):
        conn = self._get_catalog_conn()
        if not conn or not empty_list:
            return
        try:
            cursor = conn.cursor()
            for g, s, p in empty_list:
                cursor.execute(
                    "DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?",
                    (g, s, p)
                )
            conn.commit()
        except Exception as e:
            logger.error(f"delete_empty_pages error: {e}")

    def get_page_info_by_serial(self, serial_no):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mg_sn, group_name, sg_sn, page_no
                FROM catalog_pages WHERE serial_no=?
            """, (serial_no,))
            row = cursor.fetchone()
            if row:
                return {
                    "mg_sn": row[0], "group_name": row[1],
                    "sg_sn": row[2], "page_no": row[3],
                    "serial_no": serial_no
                }
        except Exception as e:
            logger.error(f"get_page_info_by_serial error: {e}")
        return None

    def _page_to_serial(self, group_name, sg_sn, page_no):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT serial_no FROM catalog_pages
                WHERE group_name=? AND sg_sn=? AND page_no=?
            """, (group_name, sg_sn, page_no))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] is not None else None
        except Exception:
            return None

    def _get_serial_map(self):
        conn = self._get_catalog_conn()
        if not conn:
            return {}
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT group_name, sg_sn, page_no, serial_no FROM catalog_pages WHERE serial_no IS NOT NULL")
            return {(r[0], str(r[1]), r[2]): str(r[3]) for r in cursor.fetchall()}
        except Exception:
            return {}

    # ─── CRM MANAGER ──────────────────────────────────────────────────────────

    @staticmethod
    def _read_report_data(company_path):
        """Read report data from SQL Server via settings module."""
        from src.logic.report_store import load_report_json
        return load_report_json(company_path)

    @staticmethod
    def _write_report_data(company_path, data):
        """Write report data to SQL Server via settings module."""
        from src.logic.report_store import save_report_json
        save_report_json(data, company_path)

    def _get_all_dirty_serials(self, company_path):
        report_data = self._read_report_data(company_path)
        dirty = set()
        for crm_name, crm_data in report_data.items():
            pending = crm_data.get("pending", [])
            if isinstance(pending, list):
                dirty.update(str(s) for s in pending)
        return dirty

    def _get_least_pending_crm_serials(self, company_path):
        """Get pending list from CRM with fewest pending pages (most recently printed).

        Only considers CRMs that exist in crm_data.json (active CRMs).
        Falls back to empty set if no active CRMs exist.
        """
        report_data = self._read_report_data(company_path)
        if not report_data:
            return set()

        from src.ui.settings import load_crm_list
        active_crms = load_crm_list(company_path) if company_path else []
        if not active_crms:
            return set()

        best = None
        for crm_name, crm_data in report_data.items():
            if crm_name not in active_crms:
                continue
            pending = crm_data.get("pending", [])
            if not isinstance(pending, list):
                pending = []
            if best is None or len(pending) < len(best):
                best = pending
        return set(str(s) for s in best) if best is not None else set()

    def _add_serials_to_all_crms(self, company_path, serial_numbers):
        """Add dirty serial numbers to all CRM pending lists.

        Uses a pure SQL IF NOT EXISTS / INSERT pattern — no Python
        read-modify-write round-trip, naturally atomic, eliminates the
        multi-user race where two concurrent builds could overwrite each
        other's report_data writes.
        """
        if not serial_numbers or not company_path:
            return 0
        from src.ui.settings import load_crm_list
        crm_list = load_crm_list(company_path)
        if not crm_list:
            return 0

        conn = self._get_catalog_conn()
        if not conn:
            logger.warning("_add_serials_to_all_crms: no catalog connection — falling back to JSON write")
            # Fallback: legacy Python read-modify-write
            pages_to_add = [str(s) for s in serial_numbers]
            report_data = self._read_report_data(company_path)
            updated = 0
            for crm_name in crm_list:
                if crm_name not in report_data:
                    report_data[crm_name] = {"pending": [], "recent": []}
                current = report_data[crm_name].get("pending", [])
                if not isinstance(current, list):
                    current = []
                added = any(p not in current for p in pages_to_add)
                for page in pages_to_add:
                    if page not in current:
                        current.append(page)
                if added:
                    report_data[crm_name]["pending"] = current
                    updated += 1
            self._write_report_data(company_path, report_data)
            return updated

        pages_to_add = [str(s) for s in serial_numbers]
        updated = 0
        try:
            cursor = conn.cursor()
            for crm_name in crm_list:
                for serial in pages_to_add:
                    cursor.execute("""
                        IF NOT EXISTS (
                            SELECT 1 FROM report_data
                            WHERE crm_name=? AND serial_no=? AND status='pending'
                        )
                        INSERT INTO report_data (crm_name, serial_no, status)
                        VALUES (?, ?, 'pending')
                    """, (crm_name, serial, crm_name, serial))
                updated += 1
            conn.commit()
            logger.info(
                f"_add_serials_to_all_crms: {len(pages_to_add)} serial(s) → "
                f"{updated} CRM(s) via SQL INSERT"
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"_add_serials_to_all_crms SQL error: {e}", exc_info=True)
            # Fallback to legacy write so data isn't silently lost
            pages_to_add_fb = [str(s) for s in serial_numbers]
            report_data = self._read_report_data(company_path)
            for crm_name in crm_list:
                if crm_name not in report_data:
                    report_data[crm_name] = {"pending": [], "recent": []}
                current = report_data[crm_name].get("pending", [])
                if not isinstance(current, list):
                    current = []
                for page in pages_to_add_fb:
                    if page not in current:
                        current.append(page)
                report_data[crm_name]["pending"] = current
            self._write_report_data(company_path, report_data)
        return updated

    def _remap_crm_serials(self, company_path, old_to_new):
        if not old_to_new or not company_path:
            return
        report_data = self._read_report_data(company_path)
        for crm_name, crm_data in report_data.items():
            pending = crm_data.get("pending", [])
            if not isinstance(pending, list):
                continue
            new_pending = [old_to_new.get(str(s), str(s)) for s in pending]
            report_data[crm_name]["pending"] = list(dict.fromkeys(new_pending))
        self._write_report_data(company_path, report_data)

    # ─── SERIAL SHIFT HANDLER ─────────────────────────────────────────────────

    def handle_serial_shift_forward(self, company_path, insertion_serial, old_max_serial=None):
        insertion = int(insertion_serial)
        if old_max_serial is not None:
            max_serial = int(old_max_serial)
        else:
            conn = self._get_catalog_conn()
            if not conn:
                return
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(serial_no) FROM catalog_pages")
                max_serial = cursor.fetchone()[0] or 0
            except Exception:
                max_serial = 0

        old_to_new = {}
        shifted_serials = []
        for s in range(insertion, max_serial + 1):
            old_to_new[str(s)] = str(s + 1)
            shifted_serials.append(str(s + 1))
        shifted_serials.append(str(insertion))

        if company_path:
            self._remap_crm_serials(company_path, old_to_new)
            self._add_serials_to_all_crms(company_path, shifted_serials)
        logger.info(f"Serial shift forward from {insertion}: {len(shifted_serials)} pages affected")

    def handle_serial_shift_backward(self, company_path, deleted_serial, old_max_serial=None):
        deleted = int(deleted_serial)
        if old_max_serial is not None:
            max_serial = int(old_max_serial)
        else:
            conn = self._get_catalog_conn()
            if not conn:
                return
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(serial_no) FROM catalog_pages")
                max_serial = (cursor.fetchone()[0] or 0) + 1
            except Exception:
                max_serial = deleted

        old_to_new = {str(deleted): "__DELETED__"}
        shifted_serials = []
        for s in range(deleted + 1, max_serial + 1):
            old_to_new[str(s)] = str(s - 1)
            shifted_serials.append(str(s - 1))

        if company_path:
            self._remap_crm_serials(company_path, old_to_new)
            report_data = self._read_report_data(company_path)
            for crm_name in report_data:
                pending = report_data[crm_name].get("pending", [])
                report_data[crm_name]["pending"] = [s for s in pending if s != "__DELETED__"]
            self._write_report_data(company_path, report_data)
            if shifted_serials:
                self._add_serials_to_all_crms(company_path, shifted_serials)
        logger.info(f"Serial shift backward from {deleted}: {len(shifted_serials)} pages affected")

    # ─── PAGE SYNC ────────────────────────────────────────────────────────────

    def sync_pages_with_content(self):
        """Sync catalog_pages with the current super_master subgroup list.

        Orphan deletion safety guard:
          A page group is only deleted as an 'orphan' if it is ABSENT from
          super_master AND has NO products remaining in the catalog table.
          This prevents accidentally wiping pages when super_master returns
          fewer subgroups than expected (network glitch, partial sync, etc.).
        """
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            all_subgroups = self.get_page_data_list()

            # Safety: if super_master returned nothing, do not touch existing pages
            if not all_subgroups:
                logger.warning(
                    "sync_pages_with_content: super_master returned 0 subgroups — "
                    "skipping entirely to prevent accidental page deletion"
                )
                return

            valid_pairs = set()
            for _, group_name, sg_sn in all_subgroups:
                g_key = str(group_name).strip().upper()
                try:
                    s_key = str(int(str(sg_sn).strip()))
                except ValueError:
                    s_key = str(sg_sn).strip()
                valid_pairs.add((g_key, s_key))

            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT group_name, sg_sn FROM catalog_pages")
            db_pairs = cursor.fetchall()
            for db_group, db_sg in db_pairs:
                g_key = str(db_group).strip().upper()
                try:
                    s_key = str(int(str(db_sg).strip()))
                except ValueError:
                    s_key = str(db_sg).strip()
                if (g_key, s_key) not in valid_pairs:
                    # Safety guard: only delete if the catalog table also has no products
                    # for this group. If products exist, super_master lookup may have
                    # transiently failed — skip deletion to avoid data loss.
                    try:
                        products = self.get_sorted_products_from_db(db_group, db_sg)
                    except Exception:
                        products = None
                    if products:
                        logger.warning(
                            f"sync_pages_with_content: '{db_group}' sg={db_sg} absent from "
                            f"super_master but {len(products)} products still in catalog — "
                            f"skipping orphan deletion (super_master may be stale)"
                        )
                        continue
                    cursor.execute(
                        "DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                        (db_group, db_sg)
                    )
                    logger.info(f"Removed orphan pages: group='{db_group}', sg_sn='{db_sg}'")

            for mg_sn, group_name, sg_sn in all_subgroups:
                cursor.execute(
                    "SELECT COUNT(*) FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                    (group_name, sg_sn)
                )
                if cursor.fetchone()[0] == 0:
                    products = self.get_sorted_products_from_db(group_name, sg_sn)
                    if products:
                        cursor.execute(
                            "INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) VALUES (?, ?, ?, ?)",
                            (mg_sn, group_name, sg_sn, 1)
                        )
            conn.commit()
            # Always rebuild serial numbers after page changes
            self.rebuild_serial_numbers()
        except Exception as e:
            logger.error(f"sync_pages_with_content error: {e}")

    # ─── DISPLAY ORDER PERSISTENCE ────────────────────────────────────────────

    def _load_display_order(self, cache_key):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT product_order FROM subgroup_display_order WHERE cache_key=?", (cache_key,))
            row = cursor.fetchone()
            if row and row[0]:
                order = json.loads(row[0])
                if isinstance(order, list) and len(order) > 0:
                    return order
            parts = cache_key.split("|", 1)
            if len(parts) == 2:
                old_order = self._get_legacy_product_order(parts[0], parts[1])
                if old_order:
                    self._save_display_order(cache_key, old_order)
                    return old_order
        except Exception as e:
            logger.warning(f"_load_display_order error for '{cache_key}': {e}")
        return None

    def _save_display_order(self, cache_key, ordered_names):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                MERGE subgroup_display_order AS target
                USING (SELECT ? AS cache_key, ? AS product_order) AS source
                ON target.cache_key = source.cache_key
                WHEN MATCHED THEN UPDATE SET product_order = source.product_order
                WHEN NOT MATCHED THEN INSERT (cache_key, product_order) VALUES (source.cache_key, source.product_order);
            """, (cache_key, json.dumps(ordered_names)))
            conn.commit()
        except Exception as e:
            logger.warning(f"_save_display_order error for '{cache_key}': {e}")

    def _get_legacy_product_order(self, group_name, sg_sn):
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ps.product_list
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps ON CAST(cp.serial_no AS NVARCHAR(50)) = CAST(ps.serial_no AS NVARCHAR(50))
                WHERE cp.group_name=? AND cp.sg_sn=?
                ORDER BY cp.page_no, cp.serial_no
            """, (group_name, sg_sn))
            ordered = []
            for (p_list,) in cursor.fetchall():
                if not p_list:
                    continue
                try:
                    names = json.loads(p_list)
                    if isinstance(names, list):
                        ordered.extend(str(n).strip().lower() for n in names)
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                ordered.extend(n.strip().lower() for n in p_list.split(",") if n.strip())
            return ordered
        except Exception as e:
            logger.warning(f"_get_legacy_product_order error: {e}")
            return []

    # ─── PAGE ASSIGNMENTS I/O ─────────────────────────────────────────────────

    def _get_page_product_list(self, group_name, sg_sn, page_no):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT product_list FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                  AND page_no=?
            """, (group_name.strip(), sg_sn, page_no))
            row = cursor.fetchone()
            if row:
                if row[0]:
                    parsed = json.loads(row[0])
                    if isinstance(parsed, list):
                        return [str(n).strip().lower() for n in parsed if str(n).strip()]
                return []
            return None
        except Exception as e:
            logger.warning(f"_get_page_product_list failed: group='{group_name}', sg={sg_sn}, page={page_no}, error={e}")
            return None

    def _load_all_page_assignments(self, group_name, sg_sn):
        """Load product_list assignments for all pages in a subgroup.

        Returns:
            dict  {page_no: [product_names]}  on success (may be empty dict for new subgroup)
            None  on DB error — callers MUST check for None and bail out.
                  Returning None distinguishes a real DB failure from a
                  legitimately empty subgroup; only an empty subgroup should
                  trigger the initial-layout path.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return None  # DB error — signal to caller: do NOT rebuild layout
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_no, product_list FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                ORDER BY page_no
            """, (group_name.strip(), sg_sn))
            assignments = {}
            for page_no, p_list in cursor.fetchall():
                names = []
                if p_list:
                    try:
                        parsed = json.loads(p_list)
                        if isinstance(parsed, list):
                            names = [str(n).strip().lower() for n in parsed if str(n).strip()]
                    except (json.JSONDecodeError, TypeError):
                        pass
                assignments[page_no] = names
            return assignments  # empty dict {} is valid (new subgroup, no assignments yet)
        except Exception as e:
            logger.warning(f"_load_all_page_assignments error: {e}")
            return None  # DB error — do NOT treat as empty

    def _save_page_assignments(self, group_name, sg_sn, assignments):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            for page_no, names in assignments.items():
                product_list_json = json.dumps(names)
                cursor.execute("""
                    UPDATE catalog_pages SET product_list=?
                    WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                      AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                      AND page_no=?
                """, (product_list_json, group_name.strip(), sg_sn, page_no))
            conn.commit()
            cache_key = f"{group_name}|{sg_sn}"
            all_names = []
            for page_no in sorted(assignments.keys()):
                all_names.extend(assignments[page_no])
            if all_names:
                self._save_display_order(cache_key, all_names)
        except Exception as e:
            logger.error(f"_save_page_assignments error: {e}")

    def _ensure_page_exists(self, group_name, sg_sn, page_no):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                  AND page_no=?
            """, (group_name.strip(), sg_sn, page_no))
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    SELECT TOP 1 mg_sn FROM catalog_pages
                    WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                      AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                """, (group_name.strip(), sg_sn))
                mg_row = cursor.fetchone()
                mg_sn = mg_row[0] if mg_row else 1
                cursor.execute(
                    "INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) VALUES (?, ?, ?, ?)",
                    (mg_sn, group_name, sg_sn, page_no)
                )
                conn.commit()
                logger.info(f"Created overflow page: {group_name}|{sg_sn} page {page_no}")
        except Exception as e:
            logger.error(f"_ensure_page_exists error: {e}")

    # ─── PRODUCT FETCHING ─────────────────────────────────────────────────────

    def get_sorted_products_from_db(self, group_name, sg_sn):
        conn = self._get_conn(_DB_FINAL)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT [Product Name], [Item_Name], [Image_Path], [Lenth], [MRP],
                       [Product_Size], [MOQ], [Category], [M_Packing], [Unit],
                       [Update_date], [ID], [Image_Date]
                FROM catalog
                WHERE REPLACE(TRIM([Group]), '.', '') = REPLACE(TRIM(?), '.', '') COLLATE Latin1_General_CI_AI
                  AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)
                  AND (
                      [True/False] IS NULL
                      OR TRIM([True/False]) = ''
                      OR LOWER(TRIM(CAST([True/False] AS NVARCHAR(MAX)))) NOT IN ('false', '0', 'no')
                  )
                  AND (
                      CAST(REPLACE(ISNULL([Stock], '0'), ',', '') AS FLOAT) > 0
                      OR LOWER(TRIM(CAST([True/False] AS NVARCHAR(MAX)))) IN ('1', 'true', 'yes')
                  )
                ORDER BY TRY_CAST(REPLACE(ISNULL([MRP], '0'), ',', '') AS FLOAT) ASC,
                         [GUID] ASC
            """, (group_name.strip(), sg_sn))
            rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"get_sorted_products_from_db failed: group='{group_name}', sg={sg_sn}, error={e}")
            return []

        grouped = {}
        mp_regex = re.compile(r'\d+')
        for r in rows:
            raw_name = r[0] if r[0] and r[0].strip() else r[1]
            if not raw_name:
                continue
            norm_key = " ".join(raw_name.lower().replace("-", " ").replace("_", " ").strip().split())
            if norm_key not in grouped:
                mrp_raw = str(r[4]) if r[4] else "0"
                try:
                    sort_price = float(mrp_raw.split(',')[0].strip())
                except (ValueError, IndexError):
                    sort_price = 99999999.0
                cat_val = str(r[7] or "").lower()
                if "china" in cat_val:
                    cat_display = "चा."
                elif "india" in cat_val:
                    cat_display = "ई."
                else:
                    cat_display = ""
                grouped[norm_key] = {
                    "product_name": raw_name, "image_path": r[2],
                    "length": r[3] if r[3] else "1|0",
                    "sizes": [], "mrps": [], "moqs": [],
                    "base_units": r[9] if r[9] else "",
                    "category": cat_display, "master_packing": "",
                    "_mp_list": [], "max_update_date": "",
                    "sort_price": sort_price,
                    "min_id": str(r[11]) if len(r) > 11 and r[11] else "ZZZZZZ",
                    "img_date": ""  # will be updated to MAX across all variants below
                }
            g = grouped[norm_key]
            g["sizes"].append(r[5] if r[5] else "")
            g["mrps"].append(str(r[4]) if r[4] else "")
            g["moqs"].append(r[6] if r[6] else "")
            u_date = str(r[10]) if len(r) > 10 and r[10] else ""
            if u_date and u_date > g["max_update_date"]:
                g["max_update_date"] = u_date
            if r[8]:
                match = mp_regex.search(str(r[8]))
                if match:
                    g["_mp_list"].append(int(match.group(0)))
                else:
                    g["_mp_list"].append(0)
            else:
                g["_mp_list"].append(0)
            if not g["image_path"] and r[2]:
                g["image_path"] = r[2]
            # img_date: always keep the MAX (most recent) across all variants
            # so that the hash is insensitive to which variant is "first" in the query.
            row_img_date = str(r[12]) if len(r) > 12 and r[12] else ""
            if row_img_date > g["img_date"]:
                g["img_date"] = row_img_date

        final_list = []
        for g in grouped.values():
            base = str(g.get("base_units", "")).strip()
            mp_list = g.pop("_mp_list", [])
            # Only show packing if at least one variant has a non-zero value
            if mp_list and any(v != 0 for v in mp_list):
                g["master_packing"] = f'{",".join(map(str, mp_list))} {base}'.strip()
            final_list.append(g)
        return final_list

    # ─── GRID HELPERS ─────────────────────────────────────────────────────────

    @staticmethod
    def _empty_grid():
        return [[False] * GRID_COLS for _ in range(GRID_ROWS)]

    @staticmethod
    def _find_slot(grid, rspan, cspan):
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS - cspan + 1):
                if grid[r][c]:
                    continue
                if r + rspan > GRID_ROWS:
                    continue
                fits = True
                for dr in range(rspan):
                    for dc in range(cspan):
                        if grid[r + dr][c + dc]:
                            fits = False
                            break
                    if not fits:
                        break
                if fits:
                    return r, c
        return -1, -1

    @staticmethod
    def _find_slot_linear(grid, rspan, cspan, start_r, start_c):
        # Clamp start_r if it would overshoot for remaining rows scan
        if start_r >= GRID_ROWS:
            return -1, -1
        for c in range(start_c, GRID_COLS - cspan + 1):
            fits = True
            for ir in range(start_r, start_r + rspan):
                if ir >= GRID_ROWS:
                    fits = False
                    break
                for ic in range(c, c + cspan):
                    if grid[ir][ic]:
                        fits = False
                        break
                if not fits:
                    break
            if fits:
                return start_r, c
        for r in range(start_r + 1, GRID_ROWS):
            for c in range(GRID_COLS - cspan + 1):
                fits = True
                for ir in range(r, r + rspan):
                    if ir >= GRID_ROWS:
                        fits = False
                        break
                    for ic in range(c, c + cspan):
                        if grid[ir][ic]:
                            fits = False
                            break
                    if not fits:
                        break
                if fits:
                    return r, c
        return -1, -1

    @staticmethod
    def _mark_slot(grid, r, c, rspan, cspan):
        for dr in range(rspan):
            for dc in range(cspan):
                grid[r + dr][c + dc] = True

    @staticmethod
    def _get_product_dims(p_data):
        if isinstance(p_data, dict):
            p_len = p_data.get("length")
            num_sizes = len(p_data.get("sizes", []))
        else:
            p_len = p_data[3] if len(p_data) > 3 else 1
            num_sizes = 1
        cspan = 2
        rspan = 3 if num_sizes > 10 else (2 if num_sizes > 5 else 1)
        if p_len and str(p_len).strip():
            s_len = str(p_len).strip()
            if "|" in s_len:
                parts = s_len.split("|")
                h_str = parts[0].strip()
                v_str = parts[1].strip() if len(parts) > 1 else ""
                if ":" in h_str:
                    h_parts = h_str.split(":")
                    iw = int(h_parts[0]) if h_parts[0].isdigit() else 1
                    dw = int(h_parts[1]) if len(h_parts) > 1 and h_parts[1].isdigit() else 1
                    cspan = iw + dw
                else:
                    if h_str and h_str.isdigit() and int(h_str) > 0:
                        cspan = int(h_str) + 1
                if v_str and v_str.isdigit() and int(v_str) > 0:
                    rspan = int(v_str)
            elif s_len.isdigit() and int(s_len) > 0:
                rspan = int(s_len)
        return max(1, min(rspan, GRID_ROWS)), max(1, min(cspan, GRID_COLS))

    @staticmethod
    def _distribute_products_evenly(layout_map):
        for page_num, placements in layout_map.items():
            if not placements:
                continue
            row_groups = {}
            for pl in placements:
                row_groups.setdefault(pl["row"], []).append(pl)
            used_rows = sorted(row_groups.keys())
            num_product_rows = len(used_rows)
            if num_product_rows <= 1 or num_product_rows >= GRID_ROWS:
                continue
            row_heights = {}
            for row_num in used_rows:
                row_heights[row_num] = max(pl.get("rspan", 1) for pl in row_groups[row_num])
            total_height = sum(row_heights.values())
            if total_height >= GRID_ROWS - 1:
                continue
            empty_space = GRID_ROWS - total_height
            num_gaps = num_product_rows + 1
            base_gap = empty_space // num_gaps
            extra = empty_space % num_gaps
            new_placements = []
            current_row = base_gap + (extra // 2 if extra > 0 else 0)
            for orig_row in used_rows:
                for pl in sorted(row_groups[orig_row], key=lambda p: p["col"]):
                    rspan = pl.get("rspan", 1)
                    new_row = max(0, min(current_row, GRID_ROWS - rspan))
                    new_placements.append({**pl, "row": new_row})
                current_row += row_heights[orig_row] + base_gap
            layout_map[page_num] = new_placements
        return layout_map

    # ─── LAYOUT ENGINE ────────────────────────────────────────────────────────

    def get_items_for_page_dynamic(self, group_name, sg_sn, page_no):
        product_names = self._get_page_product_list(group_name, sg_sn, page_no)
        if product_names is not None:
            if not product_names:
                return []
            cache_key = f"{group_name}|{sg_sn}"
            if cache_key not in self._product_lookup_cache:
                all_products = self.get_sorted_products_from_db(group_name, sg_sn)
                self._product_lookup_cache[cache_key] = {
                    (p.get("product_name", "") or p.get("name", "")).strip().lower(): p
                    for p in all_products
                }
            product_lookup = self._product_lookup_cache[cache_key]
            grid = self._empty_grid()
            result = []
            cursor_r, cursor_c = 0, 0
            for name in product_names:
                p_data = product_lookup.get(name)
                if not p_data:
                    continue
                rspan, cspan = self._get_product_dims(p_data)
                r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                if r != -1:
                    self._mark_slot(grid, r, c, rspan, cspan)
                    result.append({"data": p_data, "row": r, "col": c, "rspan": rspan, "cspan": cspan})
                    cursor_r = r
                    cursor_c = c + cspan
                    if cursor_c >= GRID_COLS:
                        cursor_r += 1
                        cursor_c = 0
            if result:
                balanced = self._distribute_products_evenly({1: result})
                result = balanced.get(1, result)
            return result

        cache_key = f"{group_name}|{sg_sn}"
        if cache_key not in self._layout_cache:
            self._layout_cache[cache_key] = self._build_layout(group_name, sg_sn)
        layout_map = self._layout_cache[cache_key]
        min_page = self._get_min_page_no(group_name, sg_sn)
        relative_page = page_no - min_page + 1
        return layout_map.get(relative_page, [])

    def simulate_page_layout(self, group_name, sg_sn, allow_backward=False,
                             printable_pages=None, use_cache=True, reshuffle=False,
                             save_known=True):
        cache_key = f"{group_name}|{sg_sn}"
        if use_cache and not reshuffle and cache_key in self._layout_cache:
            return self._layout_cache[cache_key]
        if reshuffle:
            layout_map = self._build_layout(group_name, sg_sn, reshuffle=True)
            self._layout_cache[cache_key] = layout_map
            if save_known:
                self._save_layout_order(cache_key, layout_map)
            return layout_map
        assignments = self._load_all_page_assignments(group_name, sg_sn)
        has_assignments = any(names for names in assignments.values())
        if has_assignments:
            all_products = self.get_sorted_products_from_db(group_name, sg_sn)
            product_lookup = {
                (p.get("product_name", "") or p.get("name", "")).strip().lower(): p
                for p in all_products
            }
            min_page = min(assignments.keys()) if assignments else 1
            layout_map = {}
            for page_no in sorted(assignments.keys()):
                relative_page = page_no - min_page + 1
                grid = self._empty_grid()
                placements = []
                cursor_r, cursor_c = 0, 0
                for name in assignments[page_no]:
                    p_data = product_lookup.get(name)
                    if not p_data:
                        continue
                    rspan, cspan = self._get_product_dims(p_data)
                    r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                    if r != -1:
                        self._mark_slot(grid, r, c, rspan, cspan)
                        placements.append({"data": p_data, "row": r, "col": c, "rspan": rspan, "cspan": cspan})
                        cursor_r = r
                        cursor_c = c + cspan
                        if cursor_c >= GRID_COLS:
                            cursor_r += 1
                            cursor_c = 0
                layout_map[relative_page] = placements
            layout_map = self._distribute_products_evenly(layout_map)
            self._layout_cache[cache_key] = layout_map
            return layout_map
        layout_map = self._build_layout(group_name, sg_sn, reshuffle=False)
        self._layout_cache[cache_key] = layout_map
        if save_known:
            self._save_layout_order(cache_key, layout_map)
        return layout_map

    def _save_layout_order(self, cache_key, layout_map):
        all_names = []
        for page_num in sorted(layout_map.keys()):
            for pl in layout_map[page_num]:
                p_name = pl.get("data", {}).get("product_name", "")
                if p_name:
                    all_names.append(p_name.strip().lower())
        if all_names:
            self._save_display_order(cache_key, all_names)

    def _get_min_page_no(self, group_name, sg_sn):
        conn = self._get_catalog_conn()
        if not conn:
            return 1
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(page_no) FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
            """, (group_name.strip(), sg_sn))
            res = cursor.fetchone()
            return res[0] if res and res[0] else 1
        except Exception:
            return 1

    # ─── LAYOUT BUILDER ───────────────────────────────────────────────────────

    def _build_layout(self, group_name, sg_sn, reshuffle=False):
        products = self.get_sorted_products_from_db(group_name, sg_sn)
        if not products:
            return {}
        cache_key = f"{group_name}|{sg_sn}"
        if reshuffle:
            products = self._cluster_and_sort(products)
        else:
            saved_order = self._load_display_order(cache_key)
            if saved_order:
                products = self._apply_saved_order(products, saved_order)
            else:
                products = self._cluster_and_sort(products)
        layout_map = {}
        page_num = 1
        grid = self._empty_grid()
        layout_map[page_num] = []
        for p_data in products:
            rspan, cspan = self._get_product_dims(p_data)
            r, c = self._find_slot(grid, rspan, cspan)
            if r == -1:
                page_num += 1
                grid = self._empty_grid()
                layout_map[page_num] = []
                r, c = self._find_slot(grid, rspan, cspan)
            if r != -1:
                self._mark_slot(grid, r, c, rspan, cspan)
                layout_map[page_num].append({"data": p_data, "row": r, "col": c, "rspan": rspan, "cspan": cspan})
        layout_map = self._distribute_products_evenly(layout_map)
        return layout_map

    def _cluster_and_sort(self, products):
        def get_name(x):
            if isinstance(x, dict):
                return x.get("product_name", "") or x.get("name", "")
            return x[0] if x else ""
        def get_price(x):
            if isinstance(x, dict):
                return x.get("sort_price", 0)
            try:
                return float(str(x[4]).replace(",", "").strip()) if len(x) > 4 else 0
            except (ValueError, IndexError):
                return 0
        return cluster_and_sort(products, get_name_fn=get_name, get_price_fn=get_price)

    def _apply_saved_order(self, products, saved_order):
        saved_set = set(saved_order)
        order_map = {name: i for i, name in enumerate(saved_order)}
        existing = []
        new = []
        for item in products:
            p_name = (item.get("product_name", "") or item.get("name", "")).strip().lower()
            if p_name in saved_set:
                existing.append(item)
            else:
                new.append(item)
        existing.sort(key=lambda x: order_map.get(
            (x.get("product_name", "") or x.get("name", "")).strip().lower(), 999999
        ))
        return existing + new

    # ═══════════════════════════════════════════════════════════════════════════
    # SORTING ENGINE
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _group_into_contiguous_ranges(sorted_pages):
        if not sorted_pages:
            return []
        ranges = []
        current = [sorted_pages[0]]
        for i in range(1, len(sorted_pages)):
            if sorted_pages[i] == current[-1] + 1:
                current.append(sorted_pages[i])
            else:
                ranges.append(current)
                current = [sorted_pages[i]]
        ranges.append(current)
        return ranges

    def _detect_unassigned_products(self):
        """Find products in final_data.db not assigned to any page.
        Returns set of serial_no values whose last page should be forced dirty."""
        conn = self._get_catalog_conn()
        if not conn:
            return set()
        force_dirty = set()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT TRIM(group_name), CAST(sg_sn AS INTEGER) FROM catalog_pages")
            subgroups = cursor.fetchall()
            for group_name, sg_sn in subgroups:
                all_products = self.get_sorted_products_from_db(group_name, str(sg_sn))
                if not all_products:
                    continue
                db_names = set()
                for p in all_products:
                    name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    if name:
                        db_names.add(name)
                assignments = self._load_all_page_assignments(group_name, str(sg_sn))
                assigned_names = set()
                for names in assignments.values():
                    assigned_names.update(names)
                unassigned = db_names - assigned_names
                if unassigned:
                    cursor.execute("""
                        SELECT serial_no FROM catalog_pages
                        WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                          AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                        ORDER BY page_no DESC
                    """, (group_name.strip(), sg_sn))
                    row = cursor.fetchone()
                    if row and row[0]:
                        force_dirty.add(str(row[0]))
                        logger.info(f"Unassigned products in {group_name}|{sg_sn}: {len(unassigned)}")
        except Exception as e:
            logger.error(f"_detect_unassigned_products error: {e}")
        return force_dirty

    def _sort_dirty_pages(self, group_name, sg_sn, dirty_page_list):
        """Re-sort products across dirty pages using grid-simulated placement.

        Two-phase approach:
          Phase A: INSERT new/unassigned products at their correct sorted position
                   (determined by cluster-sort comparison against existing order).
                   Reflow uses ALL subgroup pages — overflow goes to existing pages
                   before creating new ones.
          Phase B: SORT only the CRM-dirty contiguous ranges.
                   Overflow cascades to existing subgroup pages, not new pages.

        Returns: set of page_no values that were actually modified.
        """
        modified_pages = set()
        assignments = self._load_all_page_assignments(group_name, sg_sn)

        # Guard: None means DB error (not empty subgroup).  Bail out immediately
        # to prevent the initial-layout path from overwriting manual customizations.
        if assignments is None:
            logger.error(
                f"_sort_dirty_pages: DB error loading assignments for "
                f"'{group_name}'|{sg_sn} — skipping sort to prevent layout reset"
            )
            return modified_pages

        # If no assignments exist yet → initial layout
        if not assignments or not any(names for names in assignments.values()):
            layout_map = self._build_layout(group_name, sg_sn, reshuffle=False)
            if not layout_map:
                return modified_pages
            conn = self._get_catalog_conn()
            if not conn:
                return modified_pages
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_no FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                ORDER BY page_no
            """, (group_name.strip(), sg_sn))
            db_pages = [r[0] for r in cursor.fetchall()]
            if not db_pages:
                return modified_pages
            for rel_page, placements in layout_map.items():
                if rel_page <= len(db_pages):
                    abs_page = db_pages[rel_page - 1]
                    assignments[abs_page] = [
                        (p.get("data", {}).get("product_name", "") or "").strip().lower()
                        for p in placements
                    ]
            self._save_page_assignments(group_name, sg_sn, assignments)

        # Get all products for this subgroup
        all_products = self.get_sorted_products_from_db(group_name, sg_sn)
        if not all_products:
            return modified_pages
        product_lookup = {}
        for p in all_products:
            name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
            if name:
                product_lookup[name] = p

        # Get ALL pages in this subgroup (for overflow into existing pages)
        all_subgroup_pages = self._get_subgroup_pages(group_name, sg_sn)
        if not all_subgroup_pages:
            all_subgroup_pages = sorted(assignments.keys())

        # ─── Phase A: APPEND new products at end of subgroup ───
        # New products go to the last page. CRM sorting (Phase B) will
        # later move them to their correct cluster-sorted position when
        # those pages enter the print queue.
        all_assigned = set()
        for names in assignments.values():
            all_assigned.update(names)
        new_products = [p for name, p in product_lookup.items() if name not in all_assigned]

        if new_products:
            sorted_new = self._cluster_and_sort(new_products)
            last_page = all_subgroup_pages[-1] if all_subgroup_pages else 1

            # Build grid for last page to check available space
            grid = self._empty_grid()
            cursor_r, cursor_c = 0, 0
            for name in assignments.get(last_page, []):
                p = product_lookup.get(name)
                if p:
                    rspan, cspan = self._get_product_dims(p)
                    r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                    if r != -1:
                        self._mark_slot(grid, r, c, rspan, cspan)
                        cursor_r = r
                        cursor_c = c + cspan
                        if cursor_c >= GRID_COLS:
                            cursor_r += 1
                            cursor_c = 0

            # Try to fit new products on the last page
            placed_on_last = []
            remaining = []
            for p in sorted_new:
                rspan, cspan = self._get_product_dims(p)
                r, c = self._find_slot(grid, rspan, cspan)
                if r != -1:
                    self._mark_slot(grid, r, c, rspan, cspan)
                    p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    placed_on_last.append(p_name)
                else:
                    remaining.append(p)

            if placed_on_last:
                assignments.setdefault(last_page, []).extend(placed_on_last)
                modified_pages.add(last_page)

            if remaining:
                # Last page is full — resort the ENTIRE subgroup to try
                # to fit all products without creating new pages.
                # Cluster-sort ALL products (existing + new) and reflow.
                all_sorted = self._cluster_and_sort(list(product_lookup.values()))
                flat_order = [
                    (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    for p in all_sorted
                ]
                reflow_modified = self._reflow_products_to_pages(
                    flat_order, assignments, all_subgroup_pages,
                    group_name, sg_sn, product_lookup
                )
                modified_pages.update(reflow_modified)
                logger.info(
                    f"Subgroup {group_name}|{sg_sn}: full reflow for "
                    f"{len(remaining)} overflow products, "
                    f"{len(reflow_modified)} pages modified"
                )
            else:
                logger.info(
                    f"Appended {len(placed_on_last)} new products to last page "
                    f"of {group_name}|{sg_sn}"
                )

        # ─── Phase B: SORT CRM-dirty contiguous ranges ───
        dirty_set = set(dirty_page_list)
        # Remove pages that only had unassigned products (already handled in Phase A)
        # Keep pages with actual snapshot/CRM changes
        ranges = self._group_into_contiguous_ranges(sorted(dirty_set))

        for page_range in ranges:
            pool = []
            for pno in page_range:
                for name in assignments.get(pno, []):
                    if name in product_lookup:
                        pool.append(product_lookup[name])
            if not pool:
                continue

            sorted_pool = self._cluster_and_sort(pool)

            # Grid placement with LINEAR cursor
            pool_idx = 0
            for pno in page_range:
                grid = self._empty_grid()
                page_products = []
                cursor_r, cursor_c = 0, 0
                while pool_idx < len(sorted_pool):
                    p = sorted_pool[pool_idx]
                    rspan, cspan = self._get_product_dims(p)
                    r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                    if r == -1:
                        break
                    self._mark_slot(grid, r, c, rspan, cspan)
                    p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    page_products.append(p_name)
                    pool_idx += 1
                    cursor_r = r
                    cursor_c = c + cspan
                    if cursor_c >= GRID_COLS:
                        cursor_r += 1
                        cursor_c = 0
                if assignments.get(pno, []) != page_products:
                    modified_pages.add(pno)
                assignments[pno] = page_products

            # Handle overflow — cascade to EXISTING subgroup pages first
            if pool_idx < len(sorted_pool):
                overflow_products = sorted_pool[pool_idx:]
                last_dirty = page_range[-1]
                overflow_modified = self._cascade_overflow(
                    overflow_products, last_dirty, assignments,
                    all_subgroup_pages, group_name, sg_sn, product_lookup
                )
                modified_pages.update(overflow_modified)

        self._save_page_assignments(group_name, sg_sn, assignments)
        self.invalidate_subgroup_cache(group_name, sg_sn)
        logger.info(
            f"Sorted {len(ranges)} range(s) in {group_name}|{sg_sn}: "
            f"{len(dirty_page_list)} dirty, {len(modified_pages)} modified, "
            f"{len(new_products)} new"
        )
        return modified_pages

    def _get_subgroup_pages(self, group_name, sg_sn):
        """Get sorted list of all page_no values for a subgroup."""
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_no FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                ORDER BY page_no
            """, (group_name.strip(), sg_sn))
            return [r[0] for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"_get_subgroup_pages error: {e}")
            return []

    def _reflow_products_to_pages(self, flat_order, assignments, all_pages,
                                   group_name, sg_sn, product_lookup):
        """Reflow a flat product list across existing pages using grid simulation.

        Products are placed page by page. If a page fills up, overflow goes to
        the next EXISTING page. Only creates a new page if the LAST page overflows.

        Returns: set of modified page_no values.
        """
        modified = set()
        product_idx = 0

        for pg in all_pages:
            grid = self._empty_grid()
            page_products = []
            cursor_r, cursor_c = 0, 0

            while product_idx < len(flat_order):
                name = flat_order[product_idx]
                p = product_lookup.get(name)
                if not p:
                    product_idx += 1
                    continue
                rspan, cspan = self._get_product_dims(p)
                r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                if r == -1:
                    break  # Page full → overflow to next page
                self._mark_slot(grid, r, c, rspan, cspan)
                page_products.append(name)
                product_idx += 1
                cursor_r = r
                cursor_c = c + cspan
                if cursor_c >= GRID_COLS:
                    cursor_r += 1
                    cursor_c = 0

            if assignments.get(pg, []) != page_products:
                modified.add(pg)
            assignments[pg] = page_products

        # Handle remaining products — create new pages at end of subgroup
        while product_idx < len(flat_order):
            new_pg = all_pages[-1] + 1 if all_pages else 1
            self._ensure_page_exists(group_name, sg_sn, new_pg)
            all_pages.append(new_pg)
            assignments[new_pg] = []

            grid = self._empty_grid()
            page_products = []
            cursor_r, cursor_c = 0, 0

            while product_idx < len(flat_order):
                name = flat_order[product_idx]
                p = product_lookup.get(name)
                if not p:
                    product_idx += 1
                    continue
                rspan, cspan = self._get_product_dims(p)
                r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                if r == -1:
                    break
                self._mark_slot(grid, r, c, rspan, cspan)
                page_products.append(name)
                product_idx += 1
                cursor_r = r
                cursor_c = c + cspan
                if cursor_c >= GRID_COLS:
                    cursor_r += 1
                    cursor_c = 0

            assignments[new_pg] = page_products
            modified.add(new_pg)

        return modified

    def _cascade_overflow(self, overflow_products, after_page, assignments,
                           all_subgroup_pages, group_name, sg_sn, product_lookup):
        """Cascade overflow products into existing subgroup pages.

        Starts from the page AFTER after_page. Uses existing pages first.
        Only creates a new page if the LAST page of the subgroup overflows.

        Returns: set of modified page_no values.
        """
        modified = set()

        # Find pages after the overflow source
        remaining_pages = [p for p in all_subgroup_pages if p > after_page]

        while overflow_products:
            if remaining_pages:
                next_page = remaining_pages.pop(0)
            else:
                # Last resort: create new page at end of subgroup
                next_page = all_subgroup_pages[-1] + 1 if all_subgroup_pages else after_page + 1
                self._ensure_page_exists(group_name, sg_sn, next_page)
                all_subgroup_pages.append(next_page)
                assignments[next_page] = []

            # Merge overflow with existing products on the target page
            overflow_names = [
                (p.get("product_name", "") or p.get("name", "")).strip().lower()
                for p in overflow_products
            ]
            existing_on_page = assignments.get(next_page, [])
            merged_names = overflow_names + existing_on_page
            merged_products = [product_lookup[n] for n in merged_names if n in product_lookup]

            # Grid-place merged products
            grid = self._empty_grid()
            fits = []
            new_overflow = []
            cursor_r, cursor_c = 0, 0
            for p in merged_products:
                rspan, cspan = self._get_product_dims(p)
                r, c = self._find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                if r != -1:
                    self._mark_slot(grid, r, c, rspan, cspan)
                    p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    fits.append(p_name)
                    cursor_r = r
                    cursor_c = c + cspan
                    if cursor_c >= GRID_COLS:
                        cursor_r += 1
                        cursor_c = 0
                else:
                    new_overflow.append(p)

            if assignments.get(next_page, []) != fits:
                modified.add(next_page)
            assignments[next_page] = fits
            overflow_products = new_overflow

        return modified

    # ═══════════════════════════════════════════════════════════════════════════
    # CHANGE DETECTION (Snapshot System)
    # ═══════════════════════════════════════════════════════════════════════════

    def _compute_page_hash(self, serial_no, return_json=False):
        """Generate MD5 hash of a page's content for change detection.

        Hashes from product_list (assignments) + resolved product data.
        Order-sensitive: reordering products = different hash.
        Includes: product names, order, length, sizes, mrps, price, image.
        Does NOT call grid placement — no rspan/cspan in the hash.

        If the product lookup returns empty for a non-empty product_names list,
        this almost certainly indicates a transient DB failure.  In that case
        we return a sentinel hash unique to this serial so the page always
        appears "changed" — a safe false-positive that forces a re-sort rather
        than silently skipping an update.
        """
        page_info = self.get_page_info_by_serial(serial_no)
        if not page_info:
            return ("", "") if return_json else ""
        product_names = self._get_page_product_list(
            page_info["group_name"], page_info["sg_sn"], page_info["page_no"]
        )
        if not product_names:
            return ("empty_page", "") if return_json else "empty_page"

        # Resolve product data
        cache_key = f"{page_info['group_name']}|{page_info['sg_sn']}"
        if cache_key not in self._product_lookup_cache:
            all_products = self.get_sorted_products_from_db(
                page_info["group_name"], page_info["sg_sn"]
            )
            self._product_lookup_cache[cache_key] = {
                (p.get("product_name", "") or p.get("name", "")).strip().lower(): p
                for p in all_products
            }
        product_lookup = self._product_lookup_cache[cache_key]

        # Guard: if the lookup is entirely empty but the page has products,
        # get_sorted_products_from_db almost certainly failed.  Return a unique
        # sentinel so this page always appears dirty (safe false-positive).
        if not product_lookup and product_names:
            logger.warning(
                f"_compute_page_hash: product lookup empty for serial {serial_no} "
                f"({len(product_names)} products expected) — returning fetch_error sentinel"
            )
            return ("fetch_error_empty_catalog", "") if return_json else "fetch_error_empty_catalog"

        # Build content signature — ORDER MATTERS (no sorting)
        def _norm_num(v):
            """Normalize '23.0' → '23' so mrps hash is insensitive to float formatting."""
            s = str(v).strip()
            if not s: return ""
            try:
                f = float(s.replace(",", ""))
                if f == int(f):
                    return str(int(f))
                return str(f)
            except (ValueError, TypeError):
                return s

        def _norm_str(v):
            """Remove invisible trailing/multiple spaces that cause false positives."""
            return " ".join(str(v).strip().lower().split()) if v else ""

        parts = []
        for name in product_names:
            p = product_lookup.get(name)
            if p:
                parts.append({
                    "name": _norm_str(name),
                    "length": _norm_str(p.get("length", "1|0")),
                    "sizes": [_norm_str(v) for v in p.get("sizes", [])],
                    "mrps": [_norm_num(v) for v in p.get("mrps", [])],
                    "moqs": [_norm_str(v) for v in p.get("moqs", [])],
                    # sort_price omitted — redundant with mrps, was causing false-positive
                    # hash changes when variant ordering shifted due to MRP updates.
                    "img": _norm_str(p.get("image_path", "")),
                    "img_date": _norm_str(p.get("img_date", "")),  # MAX across all variants
                    "category": _norm_str(p.get("category", "")),
                    "base_units": _norm_str(p.get("base_units", "")),
                    "master_packing": _norm_str(p.get("master_packing", "")),
                })
            else:
                parts.append({"name": _norm_str(name), "_missing": True})
                
        json_dump = json.dumps(parts, indent=2, sort_keys=True)
        md5_hash = hashlib.md5(json.dumps(parts, sort_keys=True).encode()).hexdigest()
        
        if return_json:
            return md5_hash, json_dump
        return md5_hash

    def detect_changed_pages(self):
        """Compare current page content with stored snapshots.
        Returns set of serial_no values for pages whose content has changed."""
        conn = self._get_catalog_conn()
        if not conn:
            return set()
        
        # ── Post-sync guard ──────────────────────────────────────────────
        # After sync_to_sqlserver.ps1 pushes SQLite data to SQL Server,
        # the pre-existing page_snapshots (computed from SQLite) won't match
        # hashes computed from SQL Server data (different NULL/float/collation).
        # The sync script sets a flag; we detect it here, regenerate correct
        # snapshots from SQL Server, and return 0 changes to prevent CRM flood.
        # Also sets _post_sync_detected so the engine skips sorting (no page creation).
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM build_config WHERE [key]='post_sync_snapshot_reset'")
            flag_row = cursor.fetchone()
            if flag_row and str(flag_row[0]).strip() == '1':
                logger.info("Post-sync flag detected — regenerating snapshots from SQL Server (no CRM flood)")
                cursor.execute("UPDATE build_config SET [value]='0' WHERE [key]='post_sync_snapshot_reset'")
                conn.commit()
                self._post_sync_detected = True
                self.invalidate_cache()
                self.save_all_page_snapshots()
                return set()
        except Exception:
            pass  # build_config may not exist yet (first run)

        # ── Hash-version guard ────────────────────────────────────────────
        # When the hash algorithm changes (ORDER BY, fields included, etc.),
        # stored snapshots computed with the old algorithm would cause every
        # page to appear "changed" on the first build — flooding the CRM.
        # We bump CURRENT_HASH_VERSION whenever the algorithm changes and
        # auto-regenerate all snapshots silently on first run, returning 0
        # changes so the CRM is not polluted.
        CURRENT_HASH_VERSION = 3  # v2: ORDER BY MRP,GUID  v3: img_date=MAX, sort_price removed
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT [value] FROM build_config WHERE [key]='hash_version'")
            ver_row = cursor.fetchone()
            stored_ver = int(ver_row[0]) if (ver_row and ver_row[0] and str(ver_row[0]).strip().isdigit()) else 0
            if stored_ver < CURRENT_HASH_VERSION:
                logger.info(
                    f"Hash algorithm updated (v{stored_ver}\u2192v{CURRENT_HASH_VERSION}) "
                    f"\u2014 regenerating all snapshots silently (no CRM flood)."
                )
                cursor.execute("""
                    MERGE build_config AS t
                    USING (SELECT 'hash_version' AS [key], ? AS [value]) AS s
                    ON t.[key] = s.[key]
                    WHEN MATCHED THEN UPDATE SET [value] = s.[value]
                    WHEN NOT MATCHED THEN INSERT ([key],[value]) VALUES (s.[key],s.[value]);
                """, (str(CURRENT_HASH_VERSION),))
                conn.commit()
                self._post_sync_detected = True
                self.invalidate_cache()
                self.save_all_page_snapshots()
                return set()
        except Exception as ver_err:
            logger.warning(f"detect_changed_pages: hash_version check failed ({ver_err}) — proceeding normally")

        # FAST PATH removed: SQL Server string comparison of DD-MM-YYYY dates
        # causes alphabetical sort bugs, leading to falsely skipping dirty pages.
        # Fall back to 100% accurate snapshot hashing.
        
        changed = set()
        try:
            cursor = conn.cursor()
            # Guard: if catalog table is empty (Tally sync race), skip detection
            # to prevent sentinel hash from flooding all pages to CRM.
            cursor.execute("SELECT COUNT(*) FROM catalog")
            if cursor.fetchone()[0] == 0:
                logger.warning("detect_changed_pages: catalog table is empty — skipping (Tally sync race?)")
                return set()
            cursor.execute("SELECT serial_no FROM catalog_pages WHERE serial_no IS NOT NULL ORDER BY serial_no")
            all_serials = [str(row[0]) for row in cursor.fetchall()]
            
            # Add json_dump column if it doesn't exist yet (for older DBs)
            try:
                cursor.execute("ALTER TABLE page_snapshots ADD json_dump NVARCHAR(MAX)")
                conn.commit()
            except Exception:
                pass
                
            cursor.execute("SELECT serial_no, content_hash, json_dump FROM page_snapshots")
            stored_hashes = {str(r[0]): (r[1], r[2] if len(r) > 2 else "") for r in cursor.fetchall()}
            
            import difflib
            for serial_no in all_serials:
                current_hash, current_json = self._compute_page_hash(serial_no, return_json=True)
                stored_data = stored_hashes.get(serial_no)
                
                if stored_data is None:
                    changed.add(serial_no)
                    logger.info(f"Page {serial_no} is newly created (no previous snapshot).")
                elif stored_data[0] != current_hash:
                    changed.add(serial_no)
                    old_json = stored_data[1] or ""
                    
                    diff = "\n".join(difflib.unified_diff(
                        old_json.splitlines(),
                        current_json.splitlines(),
                        fromfile=f'Page {serial_no} (Before Sync)',
                        tofile=f'Page {serial_no} (After Sync)',
                        lineterm=''
                    ))
                    logger.info(f"Page {serial_no} Hash Mismatch! Exact Diff:\n{diff}")
                    
            logger.info(f"Change detection: {len(changed)} changed out of {len(all_serials)} pages")
        except Exception as e:
            logger.error(f"detect_changed_pages error: {e}")
        return changed

    def save_all_page_snapshots(self):
        """Save content snapshots for all pages. Uses same _compute_page_hash()
        as detect_changed_pages() to ensure hash consistency."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            # Ensure json_dump column exists before saving
            try:
                cursor.execute("ALTER TABLE page_snapshots ADD json_dump NVARCHAR(MAX)")
                conn.commit()
            except Exception:
                pass
                
            cursor.execute("SELECT serial_no, group_name, sg_sn, page_no FROM catalog_pages WHERE serial_no IS NOT NULL ORDER BY serial_no")
            all_pages = cursor.fetchall()
            for serial_no, group_name, sg_sn, page_no in all_pages:
                sn = str(serial_no)
                content_hash, json_dump = self._compute_page_hash(sn, return_json=True)
                product_names = self._get_page_product_list(group_name, sg_sn, page_no)
                cursor.execute("""
                    MERGE page_snapshots AS target
                    USING (SELECT ? AS serial_no, ? AS content_hash, ? AS product_list, ? AS json_dump) AS source
                    ON target.serial_no = source.serial_no
                    WHEN MATCHED THEN UPDATE SET content_hash = source.content_hash, product_list = source.product_list, json_dump = source.json_dump
                    WHEN NOT MATCHED THEN INSERT (serial_no, content_hash, product_list, json_dump) VALUES (source.serial_no, source.content_hash, source.product_list, source.json_dump);
                """, (sn, content_hash, json.dumps(product_names), json_dump))
            conn.commit()
            logger.info(f"Saved snapshots for {len(all_pages)} pages")
        except Exception as e:
            logger.error(f"save_all_page_snapshots error: {e}")

    def get_last_build_date(self):
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM build_config WHERE key='last_build_date'")
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def save_last_build_date(self, date_str):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                MERGE build_config AS target
                USING (SELECT 'last_build_date' AS [key], ? AS [value]) AS source
                ON target.[key] = source.[key]
                WHEN MATCHED THEN UPDATE SET [value] = source.[value]
                WHEN NOT MATCHED THEN INSERT ([key], [value]) VALUES (source.[key], source.[value]);
            """, (date_str,))
            conn.commit()
        except Exception as e:
            logger.error(f"save_last_build_date error: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ENGINE — Main orchestrator
    # ═══════════════════════════════════════════════════════════════════════════

    def engine_run(self, company_path=None):
        """Main engine cycle. Called on Build button or tab switch.

        Flow:
          1. Sync pages + rebuild serials (capture old serial map)
          2. Detect changes via snapshot hashing
          3. Read least-pending CRM (most recently printed rep's pending list)
          4. Detect unassigned products → force their last page dirty
          5. Build SORT SET = snapshot-dirty ∪ CRM-pending ∪ unassigned
          6. Sort dirty pages (contiguous ranges per subgroup)
             Validity guard skips re-sort if assignments already fit
          7. Rebuild serials (capture new serial map)
          8. Compute CRM WRITE SET = snapshot-dirty ∪ actually-modified ∪ new ∪ shifted
             CRM-sourced pages that sorting didn't change are EXCLUDED
          9. Write CRM + save snapshots

        Returns: dict with dirty_count, dirty_serials, pages_created
        """
        if not self.catalog_db_path or not self.final_db_path:
            return {"dirty_count": 0, "dirty_serials": [], "pages_created": 0}

        # ── Cross-machine build lock ─────────────────────────────────────
        # Prevents two users from sorting the same pages simultaneously.
        # The second user's build waits (up to 30s) for the first to finish.
        # Lock is released automatically when the connection commits/rollbacks.
        _engine_lock_conn = self._get_catalog_conn()
        if _engine_lock_conn:
            try:
                _engine_lock_conn.cursor().execute("""
                    EXEC sp_getapplock
                        @Resource    = 'JKCatalog_EngineBuild',
                        @LockMode    = 'Exclusive',
                        @LockOwner   = 'Transaction',
                        @LockTimeout = 30000
                """)
            except Exception as lock_err:
                logger.warning(f"engine_run: sp_getapplock unavailable ({lock_err}) — proceeding without lock")

        # Step 1: Sync + rebuild serials
        old_serial_map = self._get_serial_map()
        self.sync_pages_with_content()
        self.rebuild_serial_numbers()
        self.invalidate_cache()

        # Step 2: Detect changes via snapshots
        self._post_sync_detected = False
        snapshot_changed = self.detect_changed_pages()  # set of serial_no strings

        # If this was the first build after a sync, snapshots were just regenerated.
        # Skip sorting entirely — page assignments are already correct from SQLite.
        if self._post_sync_detected:
            logger.info("Engine: post-sync build — skipping sort/page-creation to preserve synced layout")
            self._post_sync_detected = False
            # Release cross-machine build lock before early return
            if _engine_lock_conn:
                try:
                    _engine_lock_conn.commit()
                except Exception:
                    pass
            return {"dirty_count": 0, "dirty_serials": [], "pages_created": 0}

        # Step 3: Read least-pending CRM for sort scope
        # CRM defines which pages need reprinting → those pages should be
        # re-sorted to ensure print output is correct. The validity guard
        # in _sort_dirty_pages skips re-sorting pages whose assignments
        # are already valid, preventing unnecessary reordering.
        crm_pending = set()
        if company_path:
            crm_pending = self._get_least_pending_crm_serials(company_path)

        # Step 4: Detect unassigned products → force their last page dirty
        unassigned_serials = self._detect_unassigned_products()

        # Build SORT SET: snapshot changes + CRM pending + unassigned
        sort_serials = snapshot_changed | crm_pending | unassigned_serials

        if not sort_serials:
            logger.info("Engine: no dirty pages detected — nothing to do")
            # Release cross-machine build lock before early return
            if _engine_lock_conn:
                try:
                    _engine_lock_conn.commit()
                except Exception:
                    pass
            return {"dirty_count": 0, "dirty_serials": [], "pages_created": 0}

        logger.info(
            f"Engine: sort set = {len(sort_serials)} pages "
            f"(snapshot={len(snapshot_changed)}, crm={len(crm_pending)}, "
            f"unassigned={len(unassigned_serials)})"
        )

        # Step 5: Sort dirty pages (grouped by subgroup → contiguous ranges)
        # Build serial→page_info mapping
        serial_to_page = {}
        conn = self._get_catalog_conn()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT serial_no, group_name, sg_sn, page_no FROM catalog_pages WHERE serial_no IS NOT NULL")
                for sn, g, s, p in cursor.fetchall():
                    serial_to_page[str(sn)] = (g.strip(), str(s), p)
            except Exception as e:
                logger.error(f"Engine: serial mapping error: {e}")

        # Group dirty pages by subgroup
        subgroup_dirty = {}
        for serial in sort_serials:
            info = serial_to_page.get(serial)
            if info:
                g, s, p = info
                key = (g, s)
                subgroup_dirty.setdefault(key, []).append(p)

        all_sort_modified = set()  # (group_name, sg_sn, page_no) tuples
        pages_created = 0

        for (group_name, sg_sn), dirty_pages in subgroup_dirty.items():
            modified = self._sort_dirty_pages(group_name, sg_sn, dirty_pages)
            for pno in modified:
                all_sort_modified.add((group_name, sg_sn, pno))

        # Step 6: Rebuild serials (pages may have been created by overflow)
        self.rebuild_serial_numbers()
        new_serial_map = self._get_serial_map()

        # Count new pages
        old_keys = set(old_serial_map.keys())
        new_keys = set(new_serial_map.keys())
        pages_created = len(new_keys - old_keys)

        # Step 7: Compute CRM WRITE SET
        # = snapshot_changed ∪ actually_modified ∪ new_pages ∪ serial_shifted
        # EXCLUDES: CRM-sourced pages that sorting didn't modify

        # Map modified (group, sg_sn, page_no) back to serial_no
        modified_serials = set()
        for key, serial in new_serial_map.items():
            g, s, p = key
            if (g.strip(), str(s), p) in all_sort_modified:
                modified_serials.add(serial)

        # Detect serial shifts (serial number changed for same page)
        shifted_serials = set()
        for key in new_keys & old_keys:
            if old_serial_map[key] != new_serial_map[key]:
                shifted_serials.add(new_serial_map[key])

        # New page serials
        new_page_serials = set()
        for key in new_keys - old_keys:
            new_page_serials.add(new_serial_map[key])

        # CRM write set: real changes only (no CRM feedback loop)
        crm_dirty = snapshot_changed | modified_serials | new_page_serials | shifted_serials

        logger.info(
            f"Engine: CRM write set = {len(crm_dirty)} "
            f"(snapshot={len(snapshot_changed)}, sort_modified={len(modified_serials)}, "
            f"new={len(new_page_serials)}, shifted={len(shifted_serials)})"
        )

        # Step 8: Write CRM + save snapshots
        if company_path and crm_dirty:
            self._add_serials_to_all_crms(company_path, list(crm_dirty))
        elif not company_path and crm_dirty:
            logger.warning(
                f"engine_run: {len(crm_dirty)} dirty pages detected but company_path is "
                f"None — CRM report_data NOT updated. Build was triggered before company loaded?"
            )

        # Invalidate cache BEFORE saving snapshots to ensure fresh product
        # data is hashed (sort may have changed assignments since detection)
        self.invalidate_cache()
        self.save_all_page_snapshots()

        # Build delta for undo history (crm_adds only — page content captured by snapshot diff)
        from src.ui.settings import load_crm_list
        crm_list_for_delta = load_crm_list(company_path) if company_path and crm_dirty else []
        build_delta = {
            "crm_adds": {crm: sorted(crm_dirty, key=lambda x: int(x) if str(x).isdigit() else 0)
                         for crm in crm_list_for_delta} if crm_dirty else {},
            "affected_count": len(crm_dirty),
            "pages_created": pages_created,
            "serial_shifts": [
                {"key": f"{k[0]}|{k[1]}|{k[2]}",
                 "old_serial": old_serial_map[k],
                 "new_serial": new_serial_map[k]}
                for k in (new_keys & old_keys)
                if old_serial_map[k] != new_serial_map[k]
            ],
        }

        return {
            "dirty_count": len(crm_dirty),
            "dirty_serials": sorted(crm_dirty, key=lambda x: int(x) if str(x).isdigit() else 0),
            "pages_created": pages_created,
            "delta": build_delta,
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════════

    def find_empty_pages(self):
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT group_name, sg_sn, page_no, product_list FROM catalog_pages "
                "ORDER BY group_name, sg_sn, page_no"
            )
            empty = []
            for g, s, p, p_list in cursor.fetchall():
                has_products = False
                if p_list:
                    try:
                        parsed = json.loads(p_list)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            has_products = True
                    except (json.JSONDecodeError, TypeError):
                        pass
                if not has_products:
                    items = self.get_items_for_page_dynamic(g, s, p)
                    if not items:
                        empty.append((g, s, p))
            return empty
        except Exception as e:
            logger.error(f"find_empty_pages error: {e}")
            return []

    def update_product_length(self, product_name, new_length, group_name=None, sg_sn=None):
        conn = self._get_conn(_DB_FINAL)
        if not conn:
            return 0
        try:
            now = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            cursor = conn.cursor()
            query = "UPDATE catalog SET [Lenth] = ?, [Update_date] = ? WHERE ([Product Name] = ? OR [Item_Name] = ?)"
            params = [str(new_length), now, product_name, product_name]
            if group_name and sg_sn:
                query += " AND REPLACE(TRIM([Group]), '.', '') = REPLACE(TRIM(?), '.', '') COLLATE Latin1_General_CI_AI AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)"
                params.extend([group_name.strip(), sg_sn])
            cursor.execute(query, tuple(params))
            affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception as e:
            logger.error(f"update_product_length error: {e}")
            return 0
