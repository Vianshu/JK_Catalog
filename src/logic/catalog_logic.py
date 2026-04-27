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
import sqlite3
from datetime import datetime

from src.utils.path_utils import get_data_file_path
from src.logic.text_utils import cluster_products, cluster_and_sort, clean_cat_name, is_similar
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

GRID_ROWS = 5
GRID_COLS = 4

_DB_SUPER = "super"
_DB_CATALOG = "catalog"
_DB_FINAL = "final"
_DB_CALENDAR = "calendar"


class CatalogLogic:
    """Core logic engine for catalog layout, page management, and change detection."""

    # ─── INIT & PATH MANAGEMENT ───────────────────────────────────────────────

    def __init__(self, db_path):
        self.db_path = db_path
        self.catalog_db_path = None
        self.final_db_path = None
        self.calendar_db_path = get_data_file_path("calendar_data.db")
        self._layout_cache = {}
        self._product_lookup_cache = {}
        self._connections = {}

    def set_paths(self, catalog_db, final_db, super_db=None):
        self._close_all_connections()
        self.catalog_db_path = catalog_db
        self.final_db_path = final_db
        if super_db:
            self.db_path = super_db
        self._layout_cache = {}

    def invalidate_cache(self):
        self._layout_cache = {}
        self._product_lookup_cache = {}

    def invalidate_subgroup_cache(self, group_name, sg_sn):
        cache_key = f"{group_name}|{sg_sn}"
        self._layout_cache.pop(cache_key, None)
        self._product_lookup_cache.pop(cache_key, None)

    def close(self):
        self._close_all_connections()

    # ─── CONNECTION MANAGER ───────────────────────────────────────────────────

    def _get_conn(self, db_key):
        path_map = {
            _DB_SUPER: self.db_path,
            _DB_CATALOG: self.catalog_db_path,
            _DB_FINAL: self.final_db_path,
            _DB_CALENDAR: self.calendar_db_path,
        }
        path = path_map.get(db_key)
        if not path or not os.path.exists(path):
            return None

        if db_key in self._connections:
            conn = self._connections[db_key]
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
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
        if self.catalog_db_path and not os.path.exists(self.catalog_db_path):
            try:
                os.makedirs(os.path.dirname(self.catalog_db_path), exist_ok=True)
                conn = sqlite3.connect(self.catalog_db_path)
                conn.close()
            except Exception as e:
                logger.error(f"Failed to create catalog DB: {e}")
                return None
        return self._get_conn(_DB_CATALOG)

    def _close_all_connections(self):
        for key, conn in list(self._connections.items()):
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    # ─── SCHEMA INITIALIZATION ────────────────────────────────────────────────

    def init_catalog_db(self):
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
            cursor.execute("PRAGMA table_info(catalog_pages)")
            columns = [col[1] for col in cursor.fetchall()]
            if "product_list" not in columns:
                cursor.execute("ALTER TABLE catalog_pages ADD COLUMN product_list TEXT")
                logger.info("Schema migration: added product_list column to catalog_pages")
            conn.commit()
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
                "SELECT COUNT(*) FROM catalog_pages WHERE product_list IS NOT NULL AND TRIM(product_list) != ''"
            )
            if cursor.fetchone()[0] > 0:
                return
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

    # ─── SUPER MASTER QUERIES ─────────────────────────────────────────────────

    def _get_master_table_name(self):
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
        table = self._get_master_table_name()
        if not table:
            return []
        conn = self._get_conn(_DB_SUPER)
        if not conn:
            return []
        try:
            cursor = conn.cursor()
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
                FROM catalog_pages ORDER BY serial_no
            """)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"get_all_pages error: {e}")
            return []

    def rebuild_serial_numbers(self):
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
                cursor.execute(
                    "UPDATE catalog_pages SET serial_no=?, page_no=? WHERE id=?",
                    (idx, sg_page_counters[key], rid)
                )
            conn.commit()
        except Exception as e:
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
            return str(row[0]) if row else None
        except Exception:
            return None

    def _get_serial_map(self):
        conn = self._get_catalog_conn()
        if not conn:
            return {}
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT group_name, sg_sn, page_no, serial_no FROM catalog_pages")
            return {(r[0], str(r[1]), r[2]): str(r[3]) for r in cursor.fetchall()}
        except Exception:
            return {}

    # ─── CRM MANAGER ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_report_path(company_path):
        if company_path:
            return os.path.join(company_path, "REPORT_DATA.JSON")
        return "REPORT_DATA.JSON"

    @staticmethod
    def _read_report_data(report_path):
        if os.path.exists(report_path):
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _write_report_data(report_path, data):
        try:
            folder = os.path.dirname(report_path)
            if folder and not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"_write_report_data error: {e}")

    def _get_all_dirty_serials(self, company_path):
        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)
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
        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)
        if not report_data:
            return set()

        from src.ui.settings import load_crm_list
        crm_path = os.path.join(company_path, "crm_data.json") if company_path else ""
        active_crms = load_crm_list(crm_path) if crm_path else []
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
        if not old_to_new or not company_path:
            return
        report_path = self._get_report_path(company_path)
        report_data = self._read_report_data(report_path)
        for crm_name, crm_data in report_data.items():
            pending = crm_data.get("pending", [])
            if not isinstance(pending, list):
                continue
            new_pending = [old_to_new.get(str(s), str(s)) for s in pending]
            report_data[crm_name]["pending"] = list(dict.fromkeys(new_pending))
        self._write_report_data(report_path, report_data)

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
            report_path = self._get_report_path(company_path)
            report_data = self._read_report_data(report_path)
            for crm_name in report_data:
                pending = report_data[crm_name].get("pending", [])
                report_data[crm_name]["pending"] = [s for s in pending if s != "__DELETED__"]
            self._write_report_data(report_path, report_data)
            if shifted_serials:
                self._add_serials_to_all_crms(company_path, shifted_serials)
        logger.info(f"Serial shift backward from {deleted}: {len(shifted_serials)} pages affected")

    # ─── PAGE SYNC ────────────────────────────────────────────────────────────

    def sync_pages_with_content(self):
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            all_subgroups = self.get_page_data_list()
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
                INSERT OR REPLACE INTO subgroup_display_order (cache_key, product_order)
                VALUES (?, ?)
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
                LEFT JOIN page_snapshots ps ON CAST(cp.serial_no AS TEXT) = CAST(ps.serial_no AS TEXT)
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
                WHERE TRIM(group_name)=? COLLATE NOCASE
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                  AND page_no=?
            """, (group_name.strip(), sg_sn, page_no))
            if cursor.fetchone()[0] == 0:
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
                    "img_date": str(r[12]) if len(r) > 12 and r[12] else ""
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
        if product_names:
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
                WHERE TRIM(group_name)=? COLLATE NOCASE
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
                        WHERE TRIM(group_name)=? COLLATE NOCASE
                          AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
                        ORDER BY page_no DESC LIMIT 1
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

        Groups dirty pages into contiguous ranges. For each range:
        pools products, clusters+sorts, simulates grid placement.
        Handles overflow cascade. Places new unassigned products on last page.

        Returns: set of page_no values that were actually modified.
        """
        modified_pages = set()
        assignments = self._load_all_page_assignments(group_name, sg_sn)

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
                WHERE TRIM(group_name)=? COLLATE NOCASE
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

        dirty_set = set(dirty_page_list)
        ranges = self._group_into_contiguous_ranges(sorted(dirty_set))

        # Process each contiguous range
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

            # Handle overflow cascade
            if pool_idx < len(sorted_pool):
                overflow_products = sorted_pool[pool_idx:]
                next_page = page_range[-1] + 1
                while overflow_products:
                    overflow_names = [
                        (p.get("product_name", "") or p.get("name", "")).strip().lower()
                        for p in overflow_products
                    ]
                    if next_page not in assignments:
                        self._ensure_page_exists(group_name, sg_sn, next_page)
                        assignments[next_page] = []
                    existing_on_next = assignments.get(next_page, [])
                    merged_names = overflow_names + existing_on_next
                    merged_products = [product_lookup[n] for n in merged_names if n in product_lookup]
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
                        modified_pages.add(next_page)
                    assignments[next_page] = fits
                    overflow_products = new_overflow
                    next_page += 1 if new_overflow else 0
                    if not new_overflow:
                        break

        # Handle NEW products (not assigned to any page)
        all_assigned = set()
        for names in assignments.values():
            all_assigned.update(names)
        new_products = [p for name, p in product_lookup.items() if name not in all_assigned]
        if new_products:
            sorted_new = self._cluster_and_sort(new_products)
            all_pages = sorted(assignments.keys())
            if not all_pages:
                all_pages = [1]
                self._ensure_page_exists(group_name, sg_sn, 1)
                assignments[1] = []

            # Build grids for all existing pages to find available space
            page_grids = {}
            for pg in all_pages:
                grid = self._empty_grid()
                cursor_r, cursor_c = 0, 0
                for name in assignments.get(pg, []):
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
                page_grids[pg] = grid

            # Place each new product on the first page with space
            for p in sorted_new:
                rspan, cspan = self._get_product_dims(p)
                placed = False
                for pg in all_pages:
                    r, c = self._find_slot(page_grids[pg], rspan, cspan)
                    if r != -1:
                        self._mark_slot(page_grids[pg], r, c, rspan, cspan)
                        p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                        assignments.setdefault(pg, []).append(p_name)
                        modified_pages.add(pg)
                        placed = True
                        break
                if not placed:
                    # No space on any existing page — create a new one
                    new_pg = all_pages[-1] + 1
                    self._ensure_page_exists(group_name, sg_sn, new_pg)
                    assignments[new_pg] = []
                    page_grids[new_pg] = self._empty_grid()
                    all_pages.append(new_pg)
                    r, c = self._find_slot(page_grids[new_pg], rspan, cspan)
                    if r != -1:
                        self._mark_slot(page_grids[new_pg], r, c, rspan, cspan)
                        p_name = (p.get("product_name", "") or p.get("name", "")).strip().lower()
                        assignments[new_pg].append(p_name)
                        modified_pages.add(new_pg)

        self._save_page_assignments(group_name, sg_sn, assignments)
        self.invalidate_subgroup_cache(group_name, sg_sn)
        logger.info(
            f"Sorted {len(ranges)} range(s) in {group_name}|{sg_sn}: "
            f"{len(dirty_page_list)} dirty, {len(modified_pages)} modified, "
            f"{len(new_products)} new"
        )
        return modified_pages

    # ═══════════════════════════════════════════════════════════════════════════
    # CHANGE DETECTION (Snapshot System)
    # ═══════════════════════════════════════════════════════════════════════════

    def _compute_page_hash(self, serial_no):
        """Generate MD5 hash of a page's content for change detection.

        Hashes from product_list (assignments) + resolved product data.
        Order-sensitive: reordering products = different hash.
        Includes: product names, order, length, sizes, mrps, price, image.
        Does NOT call grid placement — no rspan/cspan in the hash.
        """
        page_info = self.get_page_info_by_serial(serial_no)
        if not page_info:
            return ""
        product_names = self._get_page_product_list(
            page_info["group_name"], page_info["sg_sn"], page_info["page_no"]
        )
        if not product_names:
            return "empty_page"

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

        # Build content signature — ORDER MATTERS (no sorting)
        parts = []
        for name in product_names:
            p = product_lookup.get(name)
            if p:
                parts.append({
                    "name": name,
                    "length": p.get("length", "1|0"),
                    "sizes": p.get("sizes", []),
                    "mrps": p.get("mrps", []),
                    "moqs": p.get("moqs", []),
                    "sort_price": str(p.get("sort_price", "")),
                    "img": p.get("image_path", ""),
                    "img_date": p.get("img_date", ""),
                    "category": p.get("category", ""),
                    "base_units": p.get("base_units", ""),
                    "master_packing": p.get("master_packing", ""),
                })
            else:
                parts.append({"name": name, "_missing": True})
        return hashlib.md5(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    def detect_changed_pages(self):
        """Compare current page content with stored snapshots.
        Returns set of serial_no values for pages whose content has changed."""
        conn = self._get_catalog_conn()
        if not conn:
            return set()
        changed = set()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no FROM catalog_pages ORDER BY serial_no")
            all_serials = [str(row[0]) for row in cursor.fetchall()]
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
        """Save content snapshots for all pages. Uses same _compute_page_hash()
        as detect_changed_pages() to ensure hash consistency."""
        conn = self._get_catalog_conn()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no, group_name, sg_sn, page_no FROM catalog_pages ORDER BY serial_no")
            all_pages = cursor.fetchall()
            for serial_no, group_name, sg_sn, page_no in all_pages:
                sn = str(serial_no)
                content_hash = self._compute_page_hash(sn)
                product_names = self._get_page_product_list(group_name, sg_sn, page_no)
                cursor.execute("""
                    INSERT OR REPLACE INTO page_snapshots (serial_no, content_hash, product_list)
                    VALUES (?, ?, ?)
                """, (sn, content_hash, json.dumps(product_names)))
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
                INSERT OR REPLACE INTO build_config (key, value)
                VALUES ('last_build_date', ?)
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

        # Step 1: Sync + rebuild serials
        old_serial_map = self._get_serial_map()
        self.sync_pages_with_content()
        self.rebuild_serial_numbers()
        self.invalidate_cache()

        # Step 2: Detect changes via snapshots
        snapshot_changed = self.detect_changed_pages()  # set of serial_no strings

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
                cursor.execute("SELECT serial_no, group_name, sg_sn, page_no FROM catalog_pages")
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

        # Invalidate cache BEFORE saving snapshots to ensure fresh product
        # data is hashed (sort may have changed assignments since detection)
        self.invalidate_cache()
        self.save_all_page_snapshots()

        return {
            "dirty_count": len(crm_dirty),
            "dirty_serials": sorted(crm_dirty, key=lambda x: int(x) if str(x).isdigit() else 0),
            "pages_created": pages_created,
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
                query += " AND REPLACE(TRIM([Group]), '.', '') = REPLACE(TRIM(?), '.', '') COLLATE NOCASE AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)"
                params.extend([group_name.strip(), sg_sn])
            cursor.execute(query, tuple(params))
            affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception as e:
            logger.error(f"update_product_length error: {e}")
            return 0
