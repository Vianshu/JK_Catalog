"""
Catalog Logic — Core engine for catalog page layout, change detection, and data access.

Responsibilities:
  - DB connection management (single persistent connections per DB)
  - Product fetching & grouping from final_data.db
  - Page layout engine (5×4 grid, clustering, overflow, visual balancing)
  - Page CRUD (add/remove/sync pages in catalog.db)
  - CRM-driven dirty page sorting with grid-simulated placement
  - Serial shift handling (forward on page creation, backward on deletion)
  - Snapshot-based change detection
  - Explicit page assignments (product_list on catalog_pages)

Engine Architecture:
  - Each catalog_pages row has a product_list column (JSON array of product names)
  - This is the SINGLE SOURCE OF TRUTH for which products are on which page
  - CRM stores dirty page serials (per CRM rep, in REPORT_DATA.JSON)
  - Engine reads union of all CRM dirty pages to determine sort scope
  - Only dirty pages in contiguous ranges are re-sorted via grid simulation
  - Clean pages are NEVER touched — their assignments remain frozen
  - CRM is NEVER cleared by the engine — only print/export clears it
  - Products added go to last page of subgroup
  - Products removed only dirty the source page (no cascade)
  - Serial shifts add all shifted pages to CRM for reprinting

External API (used by reports.py, print_export.py):
  - CatalogLogic(db_path)
  - set_paths(catalog_db, final_db, super_db)
  - get_page_info_by_serial(serial_no)
  - get_items_for_page_dynamic(group_name, sg_sn, page_no)
  - get_nepali_date(ad_date_str)
  - invalidate_cache()
  - engine_run(company_path)
"""

import os
import re
import json
import hashlib
import sqlite3
from datetime import datetime

from src.utils.path_utils import get_data_file_path
from src.logic.text_utils import cluster_products, clean_cat_name, is_similar
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
GRID_ROWS = 5
GRID_COLS = 4

# DB keys
_DB_SUPER = "super"
_DB_CATALOG = "catalog"
_DB_FINAL = "final"
_DB_CALENDAR = "calendar"


class CatalogLogic:
    """Core logic engine for catalog layout, page management, and change detection."""

    # ───────────────────────────────────────────────────────────────────────────
    # INIT & PATH MANAGEMENT
    # ───────────────────────────────────────────────────────────────────────────

    def __init__(self, db_path):
        self.db_path = db_path  # super_master.db path
        self.catalog_db_path = None
        self.final_db_path = None
        self.calendar_db_path = get_data_file_path("calendar_data.db")

        # Layout cache: {cache_key -> layout_map}
        self._layout_cache = {}

        # Product lookup cache: {cache_key -> {name_lower: product_dict}}
        self._product_lookup_cache = {}

        # Persistent DB connections (lazy-initialized)
        self._connections = {}

    def set_paths(self, catalog_db, final_db, super_db=None):
        """Set all database paths. Closes existing connections and resets cache."""
        self._close_all_connections()
        self.catalog_db_path = catalog_db
        self.final_db_path = final_db
        if super_db:
            self.db_path = super_db
        self._layout_cache = {}

    def invalidate_cache(self):
        """Clear all cached layouts and product lookups."""
        self._layout_cache = {}
        self._product_lookup_cache = {}

    def invalidate_subgroup_cache(self, group_name, sg_sn):
        """Clear cache for a single subgroup."""
        cache_key = f"{group_name}|{sg_sn}"
        self._layout_cache.pop(cache_key, None)
        self._product_lookup_cache.pop(cache_key, None)

    def close(self):
        """Clean up all DB connections. Call on application shutdown."""
        self._close_all_connections()

    # ───────────────────────────────────────────────────────────────────────────
    # CONNECTION MANAGER
    # ───────────────────────────────────────────────────────────────────────────

    def _get_conn(self, db_key):
        """Get or create a persistent connection for the given DB key.
        
        Args:
            db_key: One of _DB_SUPER, _DB_CATALOG, _DB_FINAL, _DB_CALENDAR
            
        Returns:
            sqlite3.Connection or None if path is not set/doesn't exist.
        """
        path_map = {
            _DB_SUPER: self.db_path,
            _DB_CATALOG: self.catalog_db_path,
            _DB_FINAL: self.final_db_path,
            _DB_CALENDAR: self.calendar_db_path,
        }
        path = path_map.get(db_key)
        if not path or not os.path.exists(path):
            return None

        # Reuse existing connection if still valid
        if db_key in self._connections:
            conn = self._connections[db_key]
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                # Connection is stale, recreate
                try:
                    conn.close()
                except Exception:
                    pass
                del self._connections[db_key]

        try:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._connections[db_key] = conn
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to {db_key} ({path}): {e}")
            return None

    def _get_catalog_conn(self):
        """Convenience: get catalog.db connection, creating the file if needed."""
        if self.catalog_db_path and not os.path.exists(self.catalog_db_path):
            # Create the file so _get_conn can open it
            try:
                os.makedirs(os.path.dirname(self.catalog_db_path), exist_ok=True)
                conn = sqlite3.connect(self.catalog_db_path)
                conn.close()
            except Exception as e:
                logger.error(f"Failed to create catalog DB: {e}")
                return None
        return self._get_conn(_DB_CATALOG)

    def _close_all_connections(self):
        """Close all persistent connections."""
        for key, conn in list(self._connections.items()):
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    # ───────────────────────────────────────────────────────────────────────────
    # SCHEMA INITIALIZATION
    # ───────────────────────────────────────────────────────────────────────────

    def init_catalog_db(self):
        """Create all required tables in catalog.db if they don't exist.
        Also runs one-time migration to populate product_list column."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS catalog_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mg_sn INTEGER,
                    group_name TEXT,
                    sg_sn INTEGER,
                    page_no INTEGER,
                    serial_no INTEGER,
                    is_printable INTEGER DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subgroup_display_order (
                    cache_key TEXT PRIMARY KEY,
                    product_order TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS page_snapshots (
                    serial_no TEXT PRIMARY KEY,
                    content_hash TEXT,
                    product_list TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS build_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # ── Schema migration: add product_list column ──
            cursor.execute("PRAGMA table_info(catalog_pages)")
            columns = [col[1] for col in cursor.fetchall()]
            if "product_list" not in columns:
                cursor.execute("ALTER TABLE catalog_pages ADD COLUMN product_list TEXT")
                logger.info("Schema migration: added product_list column to catalog_pages")

            conn.commit()

            # Run one-time data migration from snapshots
            self._migrate_to_explicit_assignments()

        except Exception as e:
            logger.error(f"init_catalog_db error: {e}")

    def _migrate_to_explicit_assignments(self):
        """One-time migration: populate catalog_pages.product_list from page_snapshots.
        Only runs if no page has product_list set yet."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            # Check if any page already has product_list
            cursor.execute(
                "SELECT COUNT(*) FROM catalog_pages WHERE product_list IS NOT NULL AND TRIM(product_list) != ''"
            )
            if cursor.fetchone()[0] > 0:
                return  # Already migrated

            # Populate from page_snapshots
            cursor.execute("""
                SELECT cp.id, ps.product_list
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps
                    ON CAST(cp.serial_no AS TEXT) = CAST(ps.serial_no AS TEXT)
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
    # ───────────────────────────────────────────────────────────────────────────
    # SUPER MASTER QUERIES (Index & Subgroups)
    # ───────────────────────────────────────────────────────────────────────────

    def _get_master_table_name(self):
        """Find the table in super_master.db that contains MG_SN column."""
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            for (tbl,) in cursor.fetchall():
                cursor.execute(f"PRAGMA table_info({tbl})")
                columns = [col[1] for col in cursor.fetchall()]
                if "MG_SN" in columns or "mg_sn" in columns:
                    return tbl
        except Exception as e:
            logger.error(f"_get_master_table_name error: {e}")
        return None

    def get_index_data(self):
        """Get main group list for the index sidebar.
        
        Returns:
            List of (MG_SN, Group_Name) tuples, ordered by MG_SN.
            Groups with MG_SN >= 90 or blank names are excluded.
        """
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT DISTINCT [MG_SN], [Group_Name] FROM {table}
                WHERE [MG_SN] IS NOT NULL
                  AND TRIM(CAST([MG_SN] AS TEXT)) NOT IN ('', '0', '00')
                  AND CAST([MG_SN] AS INTEGER) < 90
                  AND TRIM(IFNULL([Group_Name], '')) != ''
                ORDER BY CAST([MG_SN] AS INTEGER)
            """)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_index_data error: {e}")
            return []

    def get_subgroups(self, group_name):
        """Get subgroups for a given main group.
        
        Returns:
            List of (SG_SN, Sub_Group) tuples.
        """
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            # Check MG_SN isn't hidden (>= 90)
            cursor.execute(
                f"SELECT DISTINCT CAST([MG_SN] AS INTEGER) FROM {table} WHERE TRIM([Group_Name])=? COLLATE NOCASE",
                (group_name.strip(),)
            )
            mg_row = cursor.fetchone()
            if mg_row and mg_row[0] is not None and mg_row[0] >= 90:
                return []

            cursor.execute(f"""
                SELECT DISTINCT [SG_SN], [Sub_Group] FROM {table}
                WHERE TRIM([Group_Name])=? COLLATE NOCASE
                  AND [Sub_Group] IS NOT NULL AND [Sub_Group]!=''
                ORDER BY CAST([SG_SN] AS INTEGER)
            """, (group_name.strip(),))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_subgroups error: {e}")
            return []

    def get_page_data_list(self):
        """Get all valid (MG_SN, Group_Name, SG_SN) combinations for page generation.
        
        Filters out hidden groups (MG_SN >= 90) and dummy serials (00).
        """
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT DISTINCT [MG_SN], [Group_Name], [SG_SN] FROM {table}
                WHERE [Group_Name] IS NOT NULL AND [SG_SN] IS NOT NULL
                  AND CAST([MG_SN] AS INTEGER) < 90
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

    # ───────────────────────────────────────────────────────────────────────────
    # DATE CONVERSION
    # ───────────────────────────────────────────────────────────────────────────

    def get_nepali_date(self, ad_date_str):
        """Convert AD date (DD-MM-YYYY ...) to BS date (DD/MM)."""
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

    # ───────────────────────────────────────────────────────────────────────────
    # PAGE CRUD (catalog.db)
    # ───────────────────────────────────────────────────────────────────────────

    def get_all_pages(self):
        """Get all catalog pages ordered by serial_no.
        
        Returns:
            List of (mg_sn, group_name, sg_sn, page_no, serial_no) tuples.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mg_sn, group_name, sg_sn, page_no, serial_no
                FROM catalog_pages ORDER BY serial_no
            """)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_all_pages error: {e}")
            return []

    def rebuild_serial_numbers(self):
        """Reassign sequential serial numbers and renumber page_no consecutively per subgroup."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, group_name, sg_sn FROM catalog_pages
                ORDER BY CAST(mg_sn AS INTEGER), CAST(sg_sn AS INTEGER), CAST(page_no AS INTEGER)
            """)
            rows = cursor.fetchall()
            sg_page_counters = {}
            for idx, (rid, group_name, sg_sn) in enumerate(rows, 1):
                key = (group_name, sg_sn)
                sg_page_counters[key] = sg_page_counters.get(key, 0) + 1
                new_page_no = sg_page_counters[key]
                cursor.execute(
                    "UPDATE catalog_pages SET serial_no=?, page_no=? WHERE id=?", 
                    (idx, new_page_no, rid)
                )
            conn.commit()
        except Exception as e:
            logger.error(f"rebuild_serial_numbers error: {e}")

    def add_page(self, mg_sn, group_name, sg_sn):
        """Add a new page at the end of a subgroup.
        
        Returns:
            The new page_no, or None on failure.
        """
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
        """Remove a specific page. Returns True on success.
        
        Caller should verify the page is empty and not the last one.
        """
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
        """Get number of pages in a subgroup."""
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
        """Delete a list of empty pages. empty_list = [(group_name, sg_sn, page_no), ...]"""
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
        """Get page details by global serial number.
        
        Returns:
            Dict with keys: mg_sn, group_name, sg_sn, page_no, serial_no.
            Or None if not found.
        """
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
        """Convert (group_name, sg_sn, page_no) to serial_no."""
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
            return str(row[0]) if row else None
        except Exception:
            return None

    def _get_serial_map(self):
        """Get mapping of (group_name, sg_sn, page_no) -> serial_no for all pages."""
        conn = self._get_catalog_conn()
        if not conn:
            return {}
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT group_name, sg_sn, page_no, serial_no FROM catalog_pages")
            return {(r[0], str(r[1]), r[2]): str(r[3]) for r in cursor.fetchall()}
        except Exception:
            return {}

    # ───────────────────────────────────────────────────────────────────────────
    # CRM MANAGER (REPORT_DATA.JSON)
    # ───────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_report_path(company_path):
        """Get REPORT_DATA.JSON path for a company."""
        if company_path:
            return os.path.join(company_path, "REPORT_DATA.JSON")
        return "REPORT_DATA.JSON"

    @staticmethod
    def _read_report_data(report_path):
        """Read REPORT_DATA.JSON."""
        if os.path.exists(report_path):
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _write_report_data(report_path, data):
        """Write REPORT_DATA.JSON."""
        try:
            folder = os.path.dirname(report_path)
            if folder and not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"_write_report_data error: {e}")

    def _get_all_dirty_serials(self, company_path):
        """Get union of all CRM reps' pending page serials."""
        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)
        dirty = set()
        for crm_name, crm_data in report_data.items():
            pending = crm_data.get("pending", [])
            if isinstance(pending, list):
                dirty.update(str(s) for s in pending)
        return dirty

    def _add_serials_to_all_crms(self, company_path, serial_numbers):
        """Add page serial numbers to ALL CRM reps' pending lists."""
        if not serial_numbers or not company_path:
            return 0

        from src.ui.settings import load_crm_list

        pages_to_add = [str(s) for s in serial_numbers]
        crm_path = os.path.join(company_path, "crm_data.json")
        crm_list = load_crm_list(crm_path)
        if not crm_list:
            return 0

        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)
        updated = 0

        for crm_name in crm_list:
            if crm_name not in report_data:
                report_data[crm_name] = {"pending": [], "recent": []}
            current = report_data[crm_name].get("pending", [])
            if not isinstance(current, list):
                current = []
            added = False
            for page in pages_to_add:
                if page not in current:
                    current.append(page)
                    added = True
            if added:
                report_data[crm_name]["pending"] = current
                updated += 1

        self._write_report_data(report_path, report_data)
        return updated

    def _remap_crm_serials(self, company_path, old_to_new):
        """Remap serial numbers in all CRM pending lists.

        Args:
            old_to_new: Dict mapping old_serial_str -> new_serial_str
        """
        if not old_to_new or not company_path:
            return
        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)

        for crm_name, crm_data in report_data.items():
            pending = crm_data.get("pending", [])
            if not isinstance(pending, list):
                continue
            new_pending = []
            for s in pending:
                new_pending.append(old_to_new.get(str(s), str(s)))
            # Deduplicate
            report_data[crm_name]["pending"] = list(dict.fromkeys(new_pending))

        self._write_report_data(report_path, report_data)

    # ───────────────────────────────────────────────────────────────────────────
    # SERIAL SHIFT HANDLER
    # ───────────────────────────────────────────────────────────────────────────

    def handle_serial_shift_forward(self, company_path, insertion_serial, old_max_serial=None):
        """Handle serial shift when a new page is inserted.

        All serials >= insertion_serial shift forward by 1.
        Remaps existing CRM entries and adds all shifted pages to CRM.

        Args:
            old_max_serial: The max serial BEFORE the new page was created.
                            If None, reads from catalog_pages (may be post-creation).
        """
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

        # Add the new page itself
        shifted_serials.append(str(insertion))

        if company_path:
            self._remap_crm_serials(company_path, old_to_new)
            self._add_serials_to_all_crms(company_path, shifted_serials)

        logger.info(f"Serial shift forward from {insertion}: {len(shifted_serials)} pages affected")

    def handle_serial_shift_backward(self, company_path, deleted_serial, old_max_serial=None):
        """Handle serial shift when a page is deleted.

        All serials > deleted_serial shift backward by 1.
        Remaps existing CRM entries and adds shifted pages to CRM.

        Args:
            old_max_serial: The max serial BEFORE the page was deleted.
                            If None, reads from catalog_pages (may be post-deletion).
        """
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
                max_serial = (cursor.fetchone()[0] or 0) + 1  # +1 since page already deleted
            except Exception:
                max_serial = deleted

        old_to_new = {str(deleted): "__DELETED__"}
        shifted_serials = []
        for s in range(deleted + 1, max_serial + 1):
            old_to_new[str(s)] = str(s - 1)
            shifted_serials.append(str(s - 1))

        if company_path:
            self._remap_crm_serials(company_path, old_to_new)
            # Remove the __DELETED__ entry
            report_path = self._get_report_path(company_path)
            report_data = self._read_report_data(report_path)
            for crm_name in report_data:
                pending = report_data[crm_name].get("pending", [])
                report_data[crm_name]["pending"] = [s for s in pending if s != "__DELETED__"]
            self._write_report_data(report_path, report_data)
            # Add shifted pages to CRM
            if shifted_serials:
                self._add_serials_to_all_crms(company_path, shifted_serials)

        logger.info(f"Serial shift backward from {deleted}: {len(shifted_serials)} pages affected")

    # ───────────────────────────────────────────────────────────────────────────
    # PAGE SYNC (Ensure catalog.db matches super_master subgroups)
    # ───────────────────────────────────────────────────────────────────────────

    def sync_pages_with_content(self):
        """Synchronize catalog_pages with super_master subgroups.

        - Removes orphaned pages whose group/subgroup no longer exists
        - Ensures at least 1 page exists for each subgroup with products
        - Does NOT compute layouts or adjust page counts.
          Page creation for overflow is handled by _sort_dirty_pages.
          Page removal for empties is handled by the Clean button.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return

        try:
            all_subgroups = self.get_page_data_list()

            # Build set of valid (group_name UPPER, sg_sn normalized) pairs
            valid_pairs = set()
            for _, group_name, sg_sn in all_subgroups:
                g_key = str(group_name).strip().upper()
                try:
                    s_key = str(int(str(sg_sn).strip()))
                except ValueError:
                    s_key = str(sg_sn).strip()
                valid_pairs.add((g_key, s_key))

            cursor = conn.cursor()

            # Phase 1: Remove orphaned pages
            cursor.execute("SELECT DISTINCT group_name, sg_sn FROM catalog_pages")
            for db_group, db_sg in cursor.fetchall():
                g_key = str(db_group).strip().upper()
                try:
                    s_key = str(int(str(db_sg).strip()))
                except ValueError:
                    s_key = str(db_sg).strip()
                if (g_key, s_key) not in valid_pairs:
                    cursor.execute(
                        "DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                        (db_group, db_sg)
                    )
                    logger.info(f"Removed orphan pages: group='{db_group}', sg_sn='{db_sg}'")

            # Phase 2: Ensure at least 1 page for subgroups that have products
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
        except Exception as e:
            logger.error(f"sync_pages_with_content error: {e}")

    # ───────────────────────────────────────────────────────────────────────────
    # DISPLAY ORDER PERSISTENCE
    # ───────────────────────────────────────────────────────────────────────────

    def _load_display_order(self, cache_key):
        """Load saved product display order for a subgroup.
        
        Falls back to legacy snapshot-based ordering for migration.
        Returns list of lowercase product names, or None if no order saved.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT product_order FROM subgroup_display_order WHERE cache_key=?",
                (cache_key,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                order = json.loads(row[0])
                if isinstance(order, list) and len(order) > 0:
                    return order

            # Migration fallback: extract order from legacy page_snapshots
            parts = cache_key.split("|", 1)
            if len(parts) == 2:
                old_order = self._get_legacy_product_order(parts[0], parts[1])
                if old_order:
                    self._save_display_order(cache_key, old_order)
                    logger.info(f"Migrated {len(old_order)} items from snapshots for '{cache_key}'")
                    return old_order
        except Exception as e:
            logger.warning(f"_load_display_order error for '{cache_key}': {e}")
        return None

    def _save_display_order(self, cache_key, ordered_names):
        """Save product display order for a subgroup."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO subgroup_display_order (cache_key, product_order)
                VALUES (?, ?)
            """, (cache_key, json.dumps(ordered_names)))
            conn.commit()
        except Exception as e:
            logger.warning(f"_save_display_order error for '{cache_key}': {e}")

    def _get_legacy_product_order(self, group_name, sg_sn):
        """Extract product order from legacy page_snapshots table."""
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ps.product_list
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps ON CAST(cp.serial_no AS TEXT) = CAST(ps.serial_no AS TEXT)
                WHERE cp.group_name=? AND cp.sg_sn=?
                ORDER BY cp.page_no, cp.serial_no
            """, (group_name, sg_sn))

            ordered = []
            for (p_list,) in cursor.fetchall():
                if not p_list:
                    continue
                # Support both JSON and comma-separated formats
                try:
                    names = json.loads(p_list)
                    if isinstance(names, list):
                        ordered.extend(str(n).strip().lower() for n in names)
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                # Legacy comma-separated
                ordered.extend(n.strip().lower() for n in p_list.split(",") if n.strip())
            return ordered
        except Exception as e:
            logger.warning(f"_get_legacy_product_order error: {e}")
            return []

    # ───────────────────────────────────────────────────────────────────────────
    # PAGE ASSIGNMENT I/O (Explicit product_list on catalog_pages)
    # ───────────────────────────────────────────────────────────────────────────

    def _get_page_product_list(self, group_name, sg_sn, page_no):
        """Read product_list for a specific page from catalog_pages.
        Returns list of lowercase product names, or empty list."""
        conn = self._get_catalog_conn()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT product_list FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE NOCASE
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                  AND page_no=?
            """, (group_name.strip(), sg_sn, page_no))
            row = cursor.fetchone()
            if row and row[0]:
                parsed = json.loads(row[0])
                if isinstance(parsed, list):
                    return [str(n).strip().lower() for n in parsed if str(n).strip()]
            return []
        except Exception as e:
            logger.warning(f"_get_page_product_list error: {e}")
            return []

    def _load_all_page_assignments(self, group_name, sg_sn):
        """Read all page assignments for a subgroup.
        Returns dict: {page_no: [lowercase_product_names]}."""
        conn = self._get_catalog_conn()
        if not conn:
            return {}
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_no, product_list FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE NOCASE
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
            return assignments
        except Exception as e:
            logger.warning(f"_load_all_page_assignments error: {e}")
            return {}

    def _save_page_assignments(self, group_name, sg_sn, assignments):
        """Save page assignments to catalog_pages.product_list.
        assignments = {page_no: [lowercase_product_names]}.
        Also updates subgroup_display_order for backward compatibility."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            for page_no, names in assignments.items():
                product_list_json = json.dumps(names)
                cursor.execute("""
                    UPDATE catalog_pages SET product_list=?
                    WHERE TRIM(group_name)=? COLLATE NOCASE
                      AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                      AND page_no=?
                """, (product_list_json, group_name.strip(), sg_sn, page_no))
            conn.commit()

            # Also update display order for backward compatibility
            cache_key = f"{group_name}|{sg_sn}"
            all_names = []
            for page_no in sorted(assignments.keys()):
                all_names.extend(assignments[page_no])
            if all_names:
                self._save_display_order(cache_key, all_names)

        except Exception as e:
            logger.error(f"_save_page_assignments error: {e}")

    def _ensure_page_exists(self, group_name, sg_sn, page_no):
        """Ensure a catalog page exists for the given page_no. Creates if missing."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE NOCASE
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                  AND page_no=?
            """, (group_name.strip(), sg_sn, page_no))
            if cursor.fetchone()[0] == 0:
                # Get mg_sn from existing pages
                cursor.execute("""
                    SELECT mg_sn FROM catalog_pages
                    WHERE TRIM(group_name)=? COLLATE NOCASE
                      AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                    LIMIT 1
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

    # ───────────────────────────────────────────────────────────────────────────
    # PRODUCT FETCHING & GROUPING
    # ───────────────────────────────────────────────────────────────────────────

    def get_sorted_products_from_db(self, group_name, sg_sn):
        """Fetch and group product variants from final_data.db.
        
        Products with the same normalized name are merged into a single dict
        with combined sizes, MRPs, and MOQs.
        
        Returns:
            List of product dicts with keys: product_name, image_path, length,
            sizes, mrps, moqs, base_units, category, master_packing,
            max_update_date, sort_price, min_id.
        """
        conn = self._get_conn(_DB_FINAL)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT [Product Name], [Item_Name], [Image_Path], [Lenth], [MRP],
                       [Product_Size], [MOQ], [Category], [M_Packing], [Unit],
                       [Update_date], [ID]
                FROM catalog
                WHERE REPLACE(TRIM([Group]), '.', '') = REPLACE(TRIM(?), '.', '') COLLATE NOCASE
                  AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)
                  AND (
                      [True/False] IS NULL
                      OR TRIM([True/False]) = ''
                      OR LOWER(TRIM(CAST([True/False] AS TEXT))) NOT IN ('false', '0', 'no')
                  )
                  AND (
                      CAST(REPLACE(IFNULL([Stock], '0'), ',', '') AS REAL) > 0
                      OR LOWER(TRIM(CAST([True/False] AS TEXT))) IN ('1', 'true', 'yes')
                  )
                ORDER BY [ID] COLLATE NOCASE ASC
            """, (group_name.strip(), sg_sn))

            rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"get_sorted_products_from_db error: {e}")
            return []

        # Group variants by normalized product name
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

                # Category display
                cat_val = str(r[7] or "").lower()
                if "china" in cat_val:
                    cat_display = "चा."
                elif "india" in cat_val:
                    cat_display = "ई."
                else:
                    cat_display = ""

                grouped[norm_key] = {
                    "product_name": raw_name,
                    "image_path": r[2],
                    "length": r[3] if r[3] else "1|0",
                    "sizes": [],
                    "mrps": [],
                    "moqs": [],
                    "base_units": r[9] if r[9] else "",
                    "category": cat_display,
                    "master_packing": "",
                    "_mp_set": set(),
                    "max_update_date": "",
                    "sort_price": sort_price,
                    "min_id": str(r[11]) if len(r) > 11 and r[11] else "ZZZZZZ"
                }

            g = grouped[norm_key]

            # Append variant data
            g["sizes"].append(r[5] if r[5] else "")
            g["mrps"].append(str(r[4]) if r[4] else "")
            g["moqs"].append(r[6] if r[6] else "")

            # Track max update date
            u_date = str(r[10]) if len(r) > 10 and r[10] else ""
            if u_date and u_date > g["max_update_date"]:
                g["max_update_date"] = u_date

            # Master packing consolidation
            if r[8]:
                match = mp_regex.search(str(r[8]))
                if match:
                    g["_mp_set"].add(int(match.group(0)))

            # Fill missing image
            if not g["image_path"] and r[2]:
                g["image_path"] = r[2]

        # Finalize: build master_packing strings and clean up
        final_list = []
        for g in grouped.values():
            base = str(g.get("base_units", "")).strip()
            mp_list = sorted(g.pop("_mp_set", []))
            if mp_list:
                g["master_packing"] = f'{",".join(map(str, mp_list))} {base}'.strip()
            final_list.append(g)

        return final_list

    # ───────────────────────────────────────────────────────────────────────────
    # LAYOUT ENGINE
    # ───────────────────────────────────────────────────────────────────────────

    def get_items_for_page_dynamic(self, group_name, sg_sn, page_no):
        """Get products for a specific page using explicit page assignments.

        Primary API for rendering a page. Reads product_list from
        catalog_pages and computes grid positions for that single page
        on the fly.

        Falls back to full layout computation if no assignments exist
        (first run before initial build).

        Returns:
            List of placement dicts: {data, row, col, rspan, cspan}
        """
        # Try explicit assignments first
        product_names = self._get_page_product_list(group_name, sg_sn, page_no)

        if product_names:
            # Load product data (cached per subgroup for performance)
            cache_key = f"{group_name}|{sg_sn}"
            if cache_key not in self._product_lookup_cache:
                all_products = self.get_sorted_products_from_db(group_name, sg_sn)
                self._product_lookup_cache[cache_key] = {
                    (p.get("product_name", "") or p.get("name", "")).strip().lower(): p
                    for p in all_products
                }
            product_lookup = self._product_lookup_cache[cache_key]

            # Compute grid positions for this page
            grid = self._empty_grid()
            result = []

            for name in product_names:
                p_data = product_lookup.get(name)
                if not p_data:
                    continue

                rspan, cspan = self._get_product_dims(p_data)
                r, c = self._find_slot(grid, rspan, cspan)

                if r != -1:
                    self._mark_slot(grid, r, c, rspan, cspan)
                    result.append({
                        "data": p_data, "row": r, "col": c,
                        "rspan": rspan, "cspan": cspan
                    })

            # Visual balancing for single page
            if result:
                balanced = self._distribute_products_evenly({1: result})
                result = balanced.get(1, result)

            return result

        # Fallback: no assignments yet — use full layout (first run before build)
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
        """Simulate product layout across pages.

        Uses explicit page assignments when available.
        Falls back to _build_layout for first run or reshuffle.

        Returns:
            Dict mapping page_number -> list of placement dicts.
        """
        cache_key = f"{group_name}|{sg_sn}"

        if use_cache and not reshuffle and cache_key in self._layout_cache:
            return self._layout_cache[cache_key]

        if reshuffle:
            layout_map = self._build_layout(group_name, sg_sn, reshuffle=True)
            self._layout_cache[cache_key] = layout_map
            if save_known:
                self._save_layout_order(cache_key, layout_map)
            return layout_map

        # Try to build from explicit page assignments
        assignments = self._load_all_page_assignments(group_name, sg_sn)
        has_assignments = any(names for names in assignments.values())

        if has_assignments:
            # Build layout map from assignments
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

                for name in assignments[page_no]:
                    p_data = product_lookup.get(name)
                    if not p_data:
                        continue

                    rspan, cspan = self._get_product_dims(p_data)
                    r, c = self._find_slot(grid, rspan, cspan)

                    if r != -1:
                        self._mark_slot(grid, r, c, rspan, cspan)
                        placements.append({
                            "data": p_data, "row": r, "col": c,
                            "rspan": rspan, "cspan": cspan
                        })

                layout_map[relative_page] = placements

            # Visual balancing
            layout_map = self._distribute_products_evenly(layout_map)
            self._layout_cache[cache_key] = layout_map
            return layout_map

        # Fallback: no assignments — full layout
        layout_map = self._build_layout(group_name, sg_sn, reshuffle=False)
        self._layout_cache[cache_key] = layout_map
        if save_known:
            self._save_layout_order(cache_key, layout_map)
        return layout_map

    def _save_layout_order(self, cache_key, layout_map):
        """Extract and persist product display order from a layout map."""
        all_names = []
        for page_num in sorted(layout_map.keys()):
            for pl in layout_map[page_num]:
                p_name = pl.get("data", {}).get("product_name", "")
                if p_name:
                    all_names.append(p_name.strip().lower())
        if all_names:
            self._save_display_order(cache_key, all_names)

    def _compute_layout(self, group_name, sg_sn):
        """Internal: compute layout via simulate_page_layout."""
        return self.simulate_page_layout(group_name, sg_sn)

    def _get_min_page_no(self, group_name, sg_sn):
        """Get the minimum page_no for a subgroup in catalog.db."""
        conn = self._get_catalog_conn()
        if not conn:
            return 1
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(page_no) FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE NOCASE
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
            """, (group_name.strip(), sg_sn))
            res = cursor.fetchone()
            return res[0] if res and res[0] else 1
        except Exception:
            return 1

    # ─── Layout Builder ───────────────────────────────────────────────────────

    def _build_layout(self, group_name, sg_sn, reshuffle=False):
        """Core layout algorithm. Places products on a 5×4 grid across pages.

        Used ONLY for:
          - First-time layout (no assignments exist yet)
          - Full reshuffle requested by user

        Simple sequential placement: products fill pages top-left first,
        overflow to the next page when full. No floor/anti-backshift logic.
        Final layout is visually balanced via _distribute_products_evenly.
        """
        products = self.get_sorted_products_from_db(group_name, sg_sn)
        if not products:
            return {}

        cache_key = f"{group_name}|{sg_sn}"

        # ── SORTING ──────────────────────────────────────────────────
        if reshuffle:
            products = self._cluster_and_sort(products)
            logger.info(f"RESHUFFLE: {len(products)} products re-sorted for {group_name}|{sg_sn}")
        else:
            saved_order = self._load_display_order(cache_key)
            if saved_order:
                products = self._apply_saved_order(products, saved_order)
            else:
                products = self._cluster_and_sort(products)
                logger.info(f"FIRST-TIME: {len(products)} products clustered for {group_name}|{sg_sn}")

        # ── PLACEMENT (simple sequential, no floor logic) ────────────
        layout_map = {}
        page_num = 1
        grid = self._empty_grid()
        layout_map[page_num] = []

        for p_data in products:
            rspan, cspan = self._get_product_dims(p_data)
            r, c = self._find_slot(grid, rspan, cspan)

            if r == -1:
                # Page full — start next page
                page_num += 1
                grid = self._empty_grid()
                layout_map[page_num] = []
                r, c = self._find_slot(grid, rspan, cspan)

            if r != -1:
                self._mark_slot(grid, r, c, rspan, cspan)
                layout_map[page_num].append({
                    "data": p_data, "row": r, "col": c,
                    "rspan": rspan, "cspan": cspan
                })

        # ── POST-PROCESSING: Visual balancing ────────────────────────
        layout_map = self._distribute_products_evenly(layout_map)

        return layout_map

    def _cluster_and_sort(self, products):
        """Cluster products by name similarity, sort by price within clusters,
        sort clusters by minimum price. Uses text_utils.cluster_products()."""

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

        clusters = cluster_products(products, get_name_fn=get_name, get_price_fn=get_price)
        return [item for cluster in clusters for item in cluster]

    def _apply_saved_order(self, products, saved_order):
        """Re-order products according to saved display order.
        New products (not in saved order) are appended at the end."""
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

    # ─── Grid Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _empty_grid():
        return [[False] * GRID_COLS for _ in range(GRID_ROWS)]

    @staticmethod
    def _find_slot(grid, rspan, cspan):
        """Find first available slot in the grid (top-left scan)."""
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
        """Find slot starting from cursor position (linear scan, no backtracking)."""
        # Try rest of current row
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

        # Try subsequent rows
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
        """Calculate grid dimensions (rspan, cspan) for a product.
        
        The 'length' field supports formats:
          - "2"         → rspan=2, cspan=2 (default img+data)
          - "1|2"       → img_width=1, rspan=2 → cspan=2
          - "1:1|2"     → img:data width, rspan=2 → cspan=2
          - "2:2|3"     → cspan=4, rspan=3
          
        Size count also affects rspan: >10 sizes → 3, >5 → 2.
        """
        if isinstance(p_data, dict):
            p_len = p_data.get("length")
            num_sizes = len(p_data.get("sizes", []))
        else:
            p_len = p_data[3] if len(p_data) > 3 else 1
            num_sizes = 1

        # Base dimensions from size count
        cspan = 2  # Default: 1 col image + 1 col data
        rspan = 3 if num_sizes > 10 else (2 if num_sizes > 5 else 1)

        # Override from length field
        if p_len and str(p_len).strip():
            s_len = str(p_len).strip()
            if "|" in s_len:
                parts = s_len.split("|")
                h_str = parts[0].strip()
                v_str = parts[1].strip() if len(parts) > 1 else ""

                if ":" in h_str:
                    # Format: "Img:Data|Height"
                    h_parts = h_str.split(":")
                    iw = int(h_parts[0]) if h_parts[0].isdigit() else 1
                    dw = int(h_parts[1]) if len(h_parts) > 1 and h_parts[1].isdigit() else 1
                    cspan = iw + dw
                else:
                    # Format: "ImgWidth|Height"
                    if h_str and h_str.isdigit() and int(h_str) > 0:
                        cspan = int(h_str) + 1

                if v_str and v_str.isdigit() and int(v_str) > 0:
                    rspan = int(v_str)
            elif s_len.isdigit() and int(s_len) > 0:
                rspan = int(s_len)

        return max(1, min(rspan, GRID_ROWS)), max(1, min(cspan, GRID_COLS))

    # ─── Visual Balancing ─────────────────────────────────────────────────────

    @staticmethod
    def _distribute_products_evenly(layout_map):
        """Redistribute products vertically for visual balance on each page.
        
        Groups products by row, then spaces the rows evenly across the page height.
        Products within a row maintain their left-to-right order.
        """
        for page_num, placements in layout_map.items():
            if not placements:
                continue

            # Group by current row
            row_groups = {}
            for pl in placements:
                row_groups.setdefault(pl["row"], []).append(pl)

            used_rows = sorted(row_groups.keys())
            num_product_rows = len(used_rows)

            if num_product_rows <= 1 or num_product_rows >= GRID_ROWS:
                continue

            # Calculate row heights
            row_heights = {}
            for row_num in used_rows:
                row_heights[row_num] = max(pl.get("rspan", 1) for pl in row_groups[row_num])

            total_height = sum(row_heights.values())
            if total_height >= GRID_ROWS - 1:
                continue

            # Distribute gaps evenly
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

    # ═══════════════════════════════════════════════════════════════════════════
    # ENGINE — Main orchestrator (Phase 1-3)
    # ═══════════════════════════════════════════════════════════════════════════

    def engine_run(self, company_path=None):
        """Main engine cycle. Called on Build button or tab switch.

        Flow:
          1. Sync pages (orphan cleanup, ensure minimum pages)
          2. Rebuild serial numbers
          3. Detect dirty pages (snapshot hashing + CRM merge)
          3.5 Detect unassigned products (new/renamed/moved) → force dirty
          4. Sort dirty pages (grid-simulated placement → explicit assignments)
          5. Rebuild serials, update CRM, save snapshots

        Returns:
            Dict with: dirty_count, dirty_serials, pages_created
        """
        if not self.catalog_db_path or not self.final_db_path:
            return {"dirty_count": 0, "dirty_serials": [], "pages_created": 0}

        # Step 1: Sync pages (minimal — no layout computation)
        old_serial_map = self._get_serial_map()
        self.sync_pages_with_content()
        self.rebuild_serial_numbers()

        # Clear caches to ensure fresh data
        self.invalidate_cache()

        # Step 2: Detect dirty pages via snapshot hashing
        changed_serials = self.detect_changed_pages()

        # Step 3: Merge CRM pending pages into dirty set
        if company_path:
            crm_serials = self._get_all_dirty_serials(company_path)
            if crm_serials:
                valid_crm = set()
                for s in crm_serials:
                    if self.get_page_info_by_serial(s):
                        valid_crm.add(s)
                if valid_crm:
                    newly_detected = len(changed_serials - valid_crm)
                    from_crm_only = len(valid_crm - changed_serials)
                    changed_serials = changed_serials | valid_crm
                    logger.info(
                        f"Dirty scope: {newly_detected} new from snapshots, "
                        f"{from_crm_only} from CRM pending, "
                        f"{len(changed_serials)} total"
                    )

        # Step 3.5: Detect unassigned products (new, renamed, moved, toggled True)
        # Products in final_data.db but not in any page's product_list
        # → force the last page of their subgroup dirty so _sort_dirty_pages
        #   picks them up via its "new products" handler.
        unassigned_serials = self._detect_unassigned_products()
        if unassigned_serials:
            before = len(changed_serials)
            changed_serials = changed_serials | unassigned_serials
            logger.info(
                f"Unassigned products: {len(unassigned_serials)} subgroups need re-sort "
                f"(dirty set: {before} → {len(changed_serials)})"
            )

        # Step 4: Sort dirty pages (grid-simulated placement)
        if changed_serials:
            dirty_by_sg = {}
            for serial in changed_serials:
                page_info = self.get_page_info_by_serial(serial)
                if page_info:
                    key = (page_info["group_name"], str(page_info["sg_sn"]))
                    dirty_by_sg.setdefault(key, []).append(page_info["page_no"])

            for (group_name, sg_sn), dirty_pages in dirty_by_sg.items():
                self._sort_dirty_pages(group_name, sg_sn, sorted(set(dirty_pages)))

        # Step 5: Rebuild serial numbers (pages may have been added)
        self.rebuild_serial_numbers()
        new_serial_map = self._get_serial_map()

        # Step 6: Determine CRM dirty set
        all_dirty = set()
        for key, new_serial in new_serial_map.items():
            old_serial = old_serial_map.get(key)
            if old_serial and str(old_serial) in changed_serials:
                all_dirty.add(new_serial)
            elif not old_serial:
                all_dirty.add(new_serial)
        for key in new_serial_map:
            old_s = old_serial_map.get(key)
            new_s = new_serial_map[key]
            if old_s and str(old_s) != str(new_s):
                all_dirty.add(new_s)

        # Step 7: Update CRM
        if company_path and all_dirty:
            remap = {}
            for key in old_serial_map:
                old_s = str(old_serial_map[key])
                new_s = new_serial_map.get(key)
                if new_s and old_s != str(new_s):
                    remap[old_s] = str(new_s)
            if remap:
                self._remap_crm_serials(company_path, remap)
            self._add_serials_to_all_crms(company_path, list(all_dirty))

        # Step 8: Save snapshots
        self.invalidate_cache()
        self.save_all_page_snapshots()

        result = {
            "dirty_count": len(all_dirty),
            "dirty_serials": sorted(all_dirty, key=lambda x: int(x) if x.isdigit() else 0),
            "pages_created": len(new_serial_map) - len(old_serial_map)
        }
        logger.info(f"Engine run complete: {result}")
        return result

    def _detect_unassigned_products(self):
        """Find subgroups that have products in final_data.db but not in any
        page's product_list. Returns a set of serial_no values (the last page
        of each affected subgroup) to inject into the dirty set.

        Covers: new products, renamed products, subgroup moves, True→False toggles.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return set()

        force_dirty_serials = set()

        try:
            cursor = conn.cursor()
            # Get all subgroups that have pages
            cursor.execute("""
                SELECT DISTINCT TRIM(group_name), CAST(sg_sn AS INTEGER)
                FROM catalog_pages
            """)
            subgroups = cursor.fetchall()

            for group_name, sg_sn in subgroups:
                # Load all DB products for this subgroup
                all_products = self.get_sorted_products_from_db(group_name, str(sg_sn))
                if not all_products:
                    continue

                db_names = set()
                for p in all_products:
                    name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    if name:
                        db_names.add(name)

                # Load all assigned product names across all pages
                assignments = self._load_all_page_assignments(group_name, str(sg_sn))
                assigned_names = set()
                for names in assignments.values():
                    assigned_names.update(names)

                # Find unassigned products
                unassigned = db_names - assigned_names
                if unassigned:
                    # Get the last page's serial for this subgroup
                    cursor.execute("""
                        SELECT serial_no FROM catalog_pages
                        WHERE TRIM(group_name)=? COLLATE NOCASE
                          AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                        ORDER BY page_no DESC LIMIT 1
                    """, (group_name.strip(), sg_sn))
                    row = cursor.fetchone()
                    if row and row[0]:
                        force_dirty_serials.add(str(row[0]))
                        logger.info(
                            f"Unassigned products in {group_name}|{sg_sn}: "
                            f"{len(unassigned)} (e.g. {list(unassigned)[:3]})"
                        )

        except Exception as e:
            logger.error(f"_detect_unassigned_products error: {e}")

        return force_dirty_serials

    @staticmethod
    def _group_into_contiguous_ranges(sorted_pages):
        """Group a sorted list of page numbers into maximal contiguous ranges.

        Example: [1, 2, 3, 5, 7, 8] -> [[1,2,3], [5], [7,8]]
        """
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

    def _sort_dirty_pages(self, group_name, sg_sn, dirty_page_list):
        """Re-sort products across dirty pages using grid-simulated placement.

        Algorithm:
          1. Load current page assignments from catalog_pages.product_list
          2. Group dirty pages into contiguous ranges
          3. For each range:
             a. Pool products from those pages
             b. Cluster+sort the pool
             c. Simulate 5×4 grid placement to fill pages densely
             d. Update assignments for those pages
          4. Handle new products (not assigned to any page)
          5. Save updated assignments to catalog_pages.product_list

        ONLY dirty pages are modified. Clean pages are NEVER touched.
        """
        # Load current page assignments
        assignments = self._load_all_page_assignments(group_name, sg_sn)

        # If no assignments exist yet, compute initial layout
        if not assignments or not any(names for names in assignments.values()):
            layout_map = self._build_layout(group_name, sg_sn, reshuffle=False)
            if not layout_map:
                return

            # Get database page numbers to map layout pages
            conn = self._get_catalog_conn()
            if not conn:
                return
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_no FROM catalog_pages
                WHERE TRIM(group_name)=? COLLATE NOCASE
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                ORDER BY page_no
            """, (group_name.strip(), sg_sn))
            db_pages = [r[0] for r in cursor.fetchall()]
            if not db_pages:
                return

            # Map relative layout pages to database page numbers
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
            return

        product_lookup = {}
        for p in all_products:
            name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
            if name:
                product_lookup[name] = p

        dirty_set = set(dirty_page_list)
        ranges = self._group_into_contiguous_ranges(sorted(dirty_set))

        # Process each contiguous range
        for page_range in ranges:
            # Pool products from dirty pages in this range
            pool = []
            for pno in page_range:
                for name in assignments.get(pno, []):
                    if name in product_lookup:
                        pool.append(product_lookup[name])

            if not pool:
                continue

            # Sort the pool
            sorted_pool = self._cluster_and_sort(pool)

            # Simulate grid placement — fill pages densely
            pool_idx = 0
            for pno in page_range:
                grid = self._empty_grid()
                page_products = []

                while pool_idx < len(sorted_pool):
                    p = sorted_pool[pool_idx]
                    rspan, cspan = self._get_product_dims(p)
                    r, c = self._find_slot(grid, rspan, cspan)

                    if r == -1:
                        break  # Page full, move to next

                    self._mark_slot(grid, r, c, rspan, cspan)
                    p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    page_products.append(p_name)
                    pool_idx += 1

                assignments[pno] = page_products

            # Handle overflow with CASCADE validation
            # If products overflow into the next page, we must validate that
            # the next page can actually hold all its products. If not, cascade.
            if pool_idx < len(sorted_pool):
                overflow_products = sorted_pool[pool_idx:]
                last_dirty = page_range[-1]
                next_page = last_dirty + 1

                # Cascade loop: keep pushing overflow until everything fits
                while overflow_products:
                    overflow_names = [
                        (p.get("product_name", "") or p.get("name", "")).strip().lower()
                        for p in overflow_products
                    ]

                    if next_page not in assignments:
                        # Brand new page — just place overflow
                        self._ensure_page_exists(group_name, sg_sn, next_page)
                        assignments[next_page] = []

                    # Merge: overflow + existing products on next_page
                    existing_on_next = assignments.get(next_page, [])
                    merged_names = overflow_names + existing_on_next

                    # Build lookup for merged products
                    merged_products = []
                    for name in merged_names:
                        if name in product_lookup:
                            merged_products.append(product_lookup[name])

                    # Simulate grid for next_page
                    grid = self._empty_grid()
                    fits = []
                    new_overflow = []
                    for p in merged_products:
                        rspan, cspan = self._get_product_dims(p)
                        r, c = self._find_slot(grid, rspan, cspan)
                        if r != -1:
                            self._mark_slot(grid, r, c, rspan, cspan)
                            p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                            fits.append(p_name)
                        else:
                            new_overflow.append(p)

                    assignments[next_page] = fits

                    if new_overflow:
                        logger.info(
                            f"Overflow cascade: {len(new_overflow)} products from "
                            f"page {next_page} → page {next_page + 1}"
                        )
                        overflow_products = new_overflow
                        next_page += 1
                    else:
                        overflow_products = []  # Everything fits — stop

                logger.info(
                    f"Overflow: products from range "
                    f"{page_range[0]}-{page_range[-1]} cascaded to page {next_page}"
                )

        # Handle NEW products (not assigned to any page)
        all_assigned = set()
        for names in assignments.values():
            all_assigned.update(names)

        new_products = []
        for name, p in product_lookup.items():
            if name not in all_assigned:
                new_products.append(p)

        if new_products:
            sorted_new = self._cluster_and_sort(new_products)
            all_pages = sorted(assignments.keys())
            last_page = all_pages[-1] if all_pages else 1

            # Build grid for last page to check remaining capacity
            grid = self._empty_grid()
            for name in assignments.get(last_page, []):
                p = product_lookup.get(name)
                if p:
                    rspan, cspan = self._get_product_dims(p)
                    r, c = self._find_slot(grid, rspan, cspan)
                    if r != -1:
                        self._mark_slot(grid, r, c, rspan, cspan)

            for p in sorted_new:
                rspan, cspan = self._get_product_dims(p)
                r, c = self._find_slot(grid, rspan, cspan)

                if r == -1:
                    # Page full, create next page
                    last_page += 1
                    self._ensure_page_exists(group_name, sg_sn, last_page)
                    assignments[last_page] = []
                    grid = self._empty_grid()
                    r, c = self._find_slot(grid, rspan, cspan)

                if r != -1:
                    self._mark_slot(grid, r, c, rspan, cspan)
                    p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                    assignments.setdefault(last_page, []).append(p_name)

        # Save all updated assignments
        self._save_page_assignments(group_name, sg_sn, assignments)
        self.invalidate_subgroup_cache(group_name, sg_sn)

        logger.info(
            f"Sorted {len(ranges)} dirty range(s) in {group_name}|{sg_sn}: "
            f"{len(dirty_page_list)} dirty pages, {len(new_products)} new products"
        )

    # ───────────────────────────────────────────────────────────────────────────
    # CHANGE DETECTION (Snapshot System)
    # ───────────────────────────────────────────────────────────────────────────

    def get_last_build_date(self):
        """Get timestamp of last catalog build."""
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
        """Save current build timestamp."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO build_config (key, value)
                VALUES ('last_build_date', ?)
            """, (date_str,))
            conn.commit()
        except Exception as e:
            logger.error(f"save_last_build_date error: {e}")

    def detect_changed_pages(self):
        """Compare current page content with stored snapshots.
        
        Returns:
            Set of serial_no values for pages whose content has changed.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return set()

        changed = set()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no FROM catalog_pages ORDER BY serial_no")
            all_serials = [str(row[0]) for row in cursor.fetchall()]

            # Load all existing snapshots in one query
            cursor.execute("SELECT serial_no, content_hash FROM page_snapshots")
            stored_hashes = {str(r[0]): r[1] for r in cursor.fetchall()}

            for serial_no in all_serials:
                current_hash = self._compute_page_hash(serial_no)
                stored_hash = stored_hashes.get(serial_no)

                if stored_hash is None or stored_hash != current_hash:
                    changed.add(serial_no)

            logger.info(f"Change detection: {len(changed)} changed out of {len(all_serials)} pages")
        except Exception as e:
            logger.error(f"detect_changed_pages error: {e}")

        return changed

    def save_all_page_snapshots(self):
        """Save content snapshots for all pages (batch operation)."""
        conn = self._get_catalog_conn()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no FROM catalog_pages ORDER BY serial_no")
            all_serials = [str(row[0]) for row in cursor.fetchall()]

            for serial_no in all_serials:
                content_hash = self._compute_page_hash(serial_no)

                # Get product names for debugging
                page_info = self.get_page_info_by_serial(serial_no)
                product_names = []
                if page_info:
                    products = self.get_items_for_page_dynamic(
                        page_info["group_name"], page_info["sg_sn"], page_info["page_no"]
                    )
                    product_names = [p.get("data", {}).get("product_name", "") for p in (products or [])]

                product_list_json = json.dumps(product_names)
                cursor.execute("""
                    INSERT OR REPLACE INTO page_snapshots (serial_no, content_hash, product_list)
                    VALUES (?, ?, ?)
                """, (serial_no, content_hash, product_list_json))

            conn.commit()
            logger.info(f"Saved snapshots for {len(all_serials)} pages")
        except Exception as e:
            logger.error(f"save_all_page_snapshots error: {e}")

    def _compute_page_hash(self, serial_no):
        """Generate MD5 hash of a page's content for change detection."""
        page_info = self.get_page_info_by_serial(serial_no)
        if not page_info:
            return ""

        products = self.get_items_for_page_dynamic(
            page_info["group_name"], page_info["sg_sn"], page_info["page_no"]
        )
        if not products:
            return "empty_page"

        # Build deterministic content signature
        parts = []
        for item in products:
            data = item.get("data", {})
            parts.append({
                "name": data.get("product_name", ""),
                "row": item.get("row", 0),
                "col": item.get("col", 0),
                "rspan": item.get("rspan", 1),
                "cspan": item.get("cspan", 2),
                "mrps": str(data.get("mrps", [])),
                "sort_price": str(data.get("sort_price", "")),
                "img": data.get("image_path", ""),
                "sizes": str(data.get("sizes", []))
            })
        parts.sort(key=lambda x: (x["row"], x["col"], x["name"]))
        return hashlib.md5(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    # ───────────────────────────────────────────────────────────────────────────
    # EMPTY PAGE DETECTION
    # ───────────────────────────────────────────────────────────────────────────

    def find_empty_pages(self):
        """Find pages that have no products assigned.

        Uses explicit page assignments (product_list column) when available.
        Falls back to get_items_for_page_dynamic for pages without assignments.

        Returns:
            List of (group_name, sg_sn, page_no) tuples for empty pages.
        """
        conn = self._get_catalog_conn()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT group_name, sg_sn, page_no, product_list FROM catalog_pages "
                "ORDER BY group_name, sg_sn, page_no"
            )
            rows = cursor.fetchall()

            empty = []
            for g, s, p, p_list in rows:
                has_products = False
                if p_list:
                    try:
                        parsed = json.loads(p_list)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            has_products = True
                    except (json.JSONDecodeError, TypeError):
                        pass

                if not has_products:
                    # Double-check with actual rendering
                    items = self.get_items_for_page_dynamic(g, s, p)
                    if not items:
                        empty.append((g, s, p))

            return empty
        except Exception as e:
            logger.error(f"find_empty_pages error: {e}")
            return []

    # ───────────────────────────────────────────────────────────────────────────
    # PRODUCT LENGTH UPDATE (from UI context menu)
    # ───────────────────────────────────────────────────────────────────────────

    def update_product_length(self, product_name, new_length, group_name=None, sg_sn=None):
        """Update a product's display length in final_data.db.
        
        Args:
            product_name: The name of the product.
            new_length: The new dimensions (e.g. "1|0", "2|2").
            group_name: (Optional) Limit update to this group.
            sg_sn: (Optional) Limit update to this subgroup serial.

        Returns:
            Number of rows affected.
        """
        conn = self._get_conn(_DB_FINAL)
        if not conn:
            return 0
        try:
            now = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            cursor = conn.cursor()

            query = "UPDATE catalog SET [Lenth] = ?, [Update_date] = ? WHERE ([Product Name] = ? OR [Item_Name] = ?)"
            params = [str(new_length), now, product_name, product_name]

            if group_name and sg_sn:
                query += " AND REPLACE(TRIM([Group]), '.', '') = REPLACE(TRIM(?), '.', '') COLLATE NOCASE AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)"
                params.extend([group_name.strip(), sg_sn])

            cursor.execute(query, tuple(params))
            affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception as e:
            logger.error(f"update_product_length error: {e}")
            return 0