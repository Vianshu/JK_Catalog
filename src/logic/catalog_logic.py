import sqlite3
import os

from src.utils.path_utils import get_data_file_path
from src.logic.text_utils import clean_cat_name, has_long_common_word, is_similar
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

class CatalogLogic:
    def __init__(self, db_path):
        self.db_path = db_path
        self.catalog_db_path = None
        self.final_db_path = None
        
        # Layout cache to avoid recomputing layouts repeatedly
        self._layout_cache = {}
        self._cache_valid = False
        
        # Derive calendar path using utility
        self.calendar_db_path = get_data_file_path("calendar_data.db")

    def set_paths(self, catalog_db, final_db):
        self.catalog_db_path = catalog_db
        self.final_db_path = final_db
        # Invalidate cache when paths change
        self._layout_cache = {}
        self._cache_valid = False
    
    def invalidate_cache(self):
        """Call this when product data changes. Does NOT clear known products."""
        self._layout_cache = {}
        self._cache_valid = False
    
    def _load_display_order(self, cache_key):
        """Load the saved display order for a subgroup. Returns list of lowercase product names or None."""
        if not self.catalog_db_path or not os.path.exists(self.catalog_db_path):
            return None
        try:
            import json
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subgroup_display_order (
                    cache_key TEXT PRIMARY KEY,
                    product_order TEXT
                )
            """)
            conn.commit()
            cursor.execute("SELECT product_order FROM subgroup_display_order WHERE cache_key=?", (cache_key,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                order = json.loads(row[0])
                if isinstance(order, list) and len(order) > 0:
                    print(f"[ORDER] Loaded {len(order)} items for '{cache_key}'")
                    return order
            
            # --- MIGRATION FALLBACK ---
            # No entry in new table. Check if we have data from the OLD system
            # (page_snapshots.product_list). This handles existing catalogs upgraded
            # to the new ordering system.
            parts = cache_key.split("|", 1)
            if len(parts) == 2:
                group_name, sg_sn = parts
                old_order = self.get_ordered_product_names(group_name, sg_sn)
                if old_order:
                    # Migrate: save old order into the new table
                    self._save_display_order(cache_key, old_order)
                    print(f"[ORDER] Migrated {len(old_order)} items from snapshots for '{cache_key}'")
                    return old_order
            
            print(f"[ORDER] No saved order for '{cache_key}'")
            return None
        except Exception as e:
            print(f"[ORDER] Load error for '{cache_key}': {e}")
            return None
    
    def _save_display_order(self, cache_key, ordered_names):
        """Save the display order for a subgroup. ordered_names = list of lowercase product names."""
        if not self.catalog_db_path:
            return
        try:
            import json
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subgroup_display_order (
                    cache_key TEXT PRIMARY KEY,
                    product_order TEXT
                )
            """)
            cursor.execute("""
                INSERT OR REPLACE INTO subgroup_display_order (cache_key, product_order)
                VALUES (?, ?)
            """, (cache_key, json.dumps(ordered_names)))
            conn.commit()
            conn.close()
            print(f"[ORDER] Saved {len(ordered_names)} items for '{cache_key}'")
        except Exception as e:
            print(f"[ORDER] Save FAILED for '{cache_key}': {e}")
        
    def get_nepali_date(self, ad_date_str):
        """Convert AD date (DD-MM-YYYY) to BS date (DD/MM)."""
        if not os.path.exists(self.calendar_db_path): return ""
        try:
            # Parse DD-MM-YYYY from input (e.g. "20-01-2026 23:55:25" -> "20-01-2026")
            if " " in ad_date_str:
                ad_date_str = ad_date_str.split(" ")[0]
            
            conn = sqlite3.connect(self.calendar_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT bs_date FROM calendar WHERE ad_date=?", (ad_date_str,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                # bs_date format: YYYY-MM-DD (e.g. 2082-03-17)
                bs_full = row[0]
                parts = bs_full.split("-")
                if len(parts) == 3:
                    # Return DD/MM
                    return f"{parts[2]}/{parts[1]}"
            return ""
        except: return ""

    def get_table_name(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            rows = cursor.fetchall()
            
            valid_table = None
            for r in rows:
                tbl = r[0]
                # Check for MG_SN column to be sure it's the right table
                try:
                    cursor.execute(f"PRAGMA table_info({tbl})")
                    columns = [col[1] for col in cursor.fetchall()]
                    if "MG_SN" in columns or "mg_sn" in columns:
                        valid_table = tbl
                        break
                except:
                    continue
            
            conn.close()
            if not valid_table:
                with open("catalog_error.log", "a") as f: f.write(f"No valid table with MG_SN found in {self.db_path}\n")
            return valid_table
        except Exception as e:
            with open("catalog_error.log", "a") as f: f.write(f"Get Table Error: {e}\n")
            return None

    def get_index_data(self):
        table = self.get_table_name()
        if not table: return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Block groups with MG_SN >= 90 from catalog index (hidden/internal groups)
            # Also exclude blank/zero MG_SN and blank Group_Name entries
            # Sort: valid numbered groups first (1,2,3...), blanks at bottom
            query = f"""SELECT DISTINCT [MG_SN], [Group_Name] FROM {table} 
                WHERE [MG_SN] IS NOT NULL 
                AND TRIM(CAST([MG_SN] AS TEXT)) != '' 
                AND TRIM(CAST([MG_SN] AS TEXT)) != '0' 
                AND TRIM(CAST([MG_SN] AS TEXT)) != '00' 
                AND CAST([MG_SN] AS INTEGER) < 90
                AND TRIM(IFNULL([Group_Name], '')) != ''
                ORDER BY CAST([MG_SN] AS INTEGER)"""
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        except Exception as e:
            with open("catalog_error.log", "a") as f: f.write(f"Index Data Error: {e}\n")
            return []

    def get_subgroups(self, group_name):
        table = self.get_table_name()
        if not table: return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Block groups with MG_SN >= 90 from showing subgroups
            mg_check = f"SELECT DISTINCT CAST([MG_SN] AS INTEGER) FROM {table} WHERE TRIM([Group_Name])=? COLLATE NOCASE"
            cursor.execute(mg_check, (group_name.strip(),))
            mg_row = cursor.fetchone()
            if mg_row and mg_row[0] is not None and mg_row[0] >= 90:
                conn.close()
                return []
            query = f"SELECT DISTINCT [SG_SN], [Sub_Group] FROM {table} WHERE TRIM([Group_Name])=? COLLATE NOCASE AND [Sub_Group] IS NOT NULL AND [Sub_Group]!='' ORDER BY CAST([SG_SN] AS INTEGER)"
            cursor.execute(query, (group_name.strip(),))
            data = cursor.fetchall()
            conn.close()
            return data
        except Exception as e:
            with open("catalog_error.log", "a") as f: f.write(f"Subgroups Error: {e}\n")
            return []

    def get_page_data_list(self):
        """Used for Initializing Pages from Master DB"""
        table = self.get_table_name()
        if not table: return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Block groups with MG_SN >= 90 from page generation
            query = f"SELECT DISTINCT [MG_SN], [Group_Name], [SG_SN] FROM {table} WHERE [Group_Name] IS NOT NULL AND [SG_SN] IS NOT NULL AND CAST([MG_SN] AS INTEGER) < 90 ORDER BY CAST([MG_SN] AS INTEGER), CAST([SG_SN] AS INTEGER)"
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            
            # Filter out invalid or dummy '00' serials ensuring no extra page creation
            valid_results = []
            for row in data:
                mg_sn, group_name, sg_sn = row
                m_str = str(mg_sn).strip()
                s_str = str(sg_sn).strip()
                
                # Logic: Skip empty or '00' serials
                if not m_str or m_str == '00': continue
                if not s_str or s_str == '00': continue
                
                valid_results.append(row)
                
            return valid_results
        except: return []

    # =========================================================
    # DYNAMIC LAYOUT ENGINE
    # =========================================================

    def sync_pages_with_content(self):
        """Checks all subgroups and auto-creates pages if content overflows.
        Also removes orphaned catalog_pages entries whose (group_name, sg_sn)
        no longer exists in super_master (handles group renames in Super Master).
        """
        if not self.catalog_db_path: return
        try:
            # 1. Get all master subgroups (authoritative list)
            all_subgroups = self.get_page_data_list()

            # Build a set of valid (group_name UPPER, sg_sn str) pairs
            valid_pairs = set()
            for _, group_name, sg_sn in all_subgroups:
                g_key = str(group_name).strip().upper()
                try:
                    s_key = str(int(str(sg_sn).strip()))
                except ValueError:
                    s_key = str(sg_sn).strip()
                valid_pairs.add((g_key, s_key))

            # Phase 1: Compute all layouts FIRST (no open DB connection)
            # This allows simulate_page_layout → _save_display_order to write freely
            page_requirements = []
            for mg_sn, group_name, sg_sn in all_subgroups:
                layout_map = self.simulate_page_layout(group_name, sg_sn)
                max_required_page = max(layout_map.keys()) if layout_map else 1
                page_requirements.append((mg_sn, group_name, sg_sn, max_required_page))

            # Phase 2: Update page counts (single connection, no conflicts)
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()

            # ── ORPHAN CLEANUP ────────────────────────────────────────────────
            # Remove catalog_pages rows whose group/subgroup no longer exists
            # in super_master. This handles cases like renaming "Price List" → "MOP":
            # the old "Price List" pages become orphans and must be removed so
            # they don't appear alongside the new "MOP" pages.
            cursor.execute("SELECT DISTINCT group_name, sg_sn FROM catalog_pages")
            existing_pairs = cursor.fetchall()
            for (db_group, db_sg) in existing_pairs:
                g_key = str(db_group).strip().upper()
                try:
                    s_key = str(int(str(db_sg).strip()))
                except ValueError:
                    s_key = str(db_sg).strip()
                
                key = (g_key, s_key)
                if key not in valid_pairs:
                    cursor.execute(
                        "DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=?",
                        (db_group, db_sg)
                    )
                    print(f"[SYNC] Removed orphan pages for group='{db_group}', sg_sn='{db_sg}'")
            # ─────────────────────────────────────────────────────────────────

            for mg_sn, group_name, sg_sn, max_required_page in page_requirements:
                cursor.execute("SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?", (group_name, sg_sn))
                res = cursor.fetchone()
                current_max = res[0] if res and res[0] else 0

                if max_required_page > current_max:
                    for p in range(current_max + 1, max_required_page + 1):
                        cursor.execute("""
                            INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no)
                            VALUES (?, ?, ?, ?)
                        """, (mg_sn, group_name, sg_sn, p))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SYNC] Error in sync_pages_with_content: {e}")  # Surface errors for debugging
    
    # =========================================================
    # CRM CHANGE TRACKING
    # =========================================================
    
    def init_build_config(self):
        """Initialize build_config table if not exists."""
        if not self.catalog_db_path: return
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS build_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
            conn.close()
        except:
            pass
    
    def get_last_build_date(self):
        """Get timestamp of last catalog build."""
        if not self.catalog_db_path: return None
        try:
            self.init_build_config()
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM build_config WHERE key='last_build_date'")
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except:
            return None
    
    def save_last_build_date(self, date_str):
        """Save current build timestamp."""
        if not self.catalog_db_path: return
        try:
            self.init_build_config()
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO build_config (key, value)
                VALUES ('last_build_date', ?)
            """, (date_str,))
            conn.commit()
            conn.close()
        except:
            pass
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE SNAPSHOT SYSTEM - Comprehensive change detection
    # ═══════════════════════════════════════════════════════════════════════════
    
    def init_page_snapshots_table(self):
        """Initialize page_snapshots table to store page content hashes."""
        if not self.catalog_db_path: return
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS page_snapshots (
                    serial_no TEXT PRIMARY KEY,
                    content_hash TEXT,
                    product_list TEXT
                )
            """)
            conn.commit()
            conn.close()
        except:
            pass
    
    def get_page_content_hash(self, serial_no):
        """Generate a hash of page content for change detection.
        
        The hash includes:
        - Product names on the page
        - Product positions (row, col)
        - Product sizes (rspan, cspan)
        - Key product data (MRP, stock status, image path)
        """
        import hashlib
        import json
        
        page_info = self.get_page_info_by_serial(serial_no)
        if not page_info:
            return ""
        
        group_name = page_info["group_name"]
        sg_sn = page_info["sg_sn"]
        page_no = page_info["page_no"]
        
        # Get products for this page
        products = self.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        
        if not products:
            return "empty_page"
        
        # Build content signature
        content_parts = []
        for item in products:
            data = item.get("data", {})
            signature = {
                "name": data.get("product_name", ""),
                "row": item.get("row", 0),
                "col": item.get("col", 0),
                "rspan": item.get("rspan", 1),
                "cspan": item.get("cspan", 2),
                "mrp": str(data.get("mrp", "")),
                "img": data.get("image_path", ""),
                "sizes": str(data.get("sizes", []))
            }
            content_parts.append(signature)
        
        # Sort by position for consistent hashing
        content_parts.sort(key=lambda x: (x["row"], x["col"], x["name"]))
        
        # Generate hash
        content_str = json.dumps(content_parts, sort_keys=True)
        return hashlib.md5(content_str.encode()).hexdigest()
    
    def save_page_snapshot(self, serial_no, content_hash, product_list):
        """Save a page's content snapshot. Supports list (saved as JSON) or string."""
        if not self.catalog_db_path: return
        try:
            import json
            if isinstance(product_list, list):
                product_list = json.dumps(product_list)
                
            self.init_page_snapshots_table()
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO page_snapshots (serial_no, content_hash, product_list)
                VALUES (?, ?, ?)
            """, (str(serial_no), content_hash, product_list))
            conn.commit()
            conn.close()
        except:
            pass
    
    def get_page_snapshot(self, serial_no):
        """Get stored snapshot for a page."""
        if not self.catalog_db_path: return None
        try:
            self.init_page_snapshots_table()
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT content_hash, product_list FROM page_snapshots WHERE serial_no=?
            """, (str(serial_no),))
            row = cursor.fetchone()
            conn.close()
            return {"hash": row[0], "products": row[1]} if row else None
        except:
            return None
    
    def detect_changed_pages(self):
        """Compare current page layouts with stored snapshots.
        
        Returns:
            Set of serial_no values for pages that have changed.
            
        Detects:
        - Products added to a page
        - Products removed from a page
        - Product positions shifted
        - Product data changed (MRP, image, sizes)
        """
        changed_pages = set()
        
        if not self.catalog_db_path:
            return changed_pages
        
        try:
            # Get all page serial numbers
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no FROM catalog_pages ORDER BY serial_no")
            all_pages = [str(row[0]) for row in cursor.fetchall()]
            conn.close()
            
            for serial_no in all_pages:
                # Get current content hash
                current_hash = self.get_page_content_hash(serial_no)
                
                # Get stored snapshot
                snapshot = self.get_page_snapshot(serial_no)
                
                if snapshot is None:
                    # New page (no snapshot) - consider changed
                    changed_pages.add(serial_no)
                elif snapshot["hash"] != current_hash:
                    # Content changed
                    changed_pages.add(serial_no)
                # else: Page unchanged, don't add
            
            print(f"[SNAPSHOT] Detected {len(changed_pages)} changed pages out of {len(all_pages)}")
            return changed_pages
            
        except Exception as e:
            print(f"[SNAPSHOT] Error detecting changes: {e}")
            return changed_pages
    
    def save_all_page_snapshots(self):
        """Save snapshots for all pages after a build."""
        if not self.catalog_db_path:
            return
        
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT serial_no FROM catalog_pages ORDER BY serial_no")
            all_pages = [str(row[0]) for row in cursor.fetchall()]
            conn.close()
            
            for serial_no in all_pages:
                content_hash = self.get_page_content_hash(serial_no)
                
                # Also store product names list for debugging
                page_info = self.get_page_info_by_serial(serial_no)
                product_names = []
                if page_info:
                    products = self.get_items_for_page_dynamic(
                        page_info["group_name"], 
                        page_info["sg_sn"], 
                        page_info["page_no"]
                    )
                    product_names = [p.get("data", {}).get("product_name", "") for p in (products or [])]
                
                self.save_page_snapshot(serial_no, content_hash, product_names)
            
            print(f"[SNAPSHOT] Saved snapshots for {len(all_pages)} pages")
            
        except Exception as e:
            print(f"[SNAPSHOT] Error saving snapshots: {e}")
    
    def save_layout_snapshots(self, layout_map, group_name, sg_sn):
        """Force save snapshots from a computed layout map (used after Reshuffle)."""
        if not self.catalog_db_path: return
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            
            # 1. Get Serial Numbers for this group/subgroup (Robust Match)
            cursor.execute("""
                SELECT page_no, serial_no FROM catalog_pages 
                WHERE TRIM(group_name) = TRIM(?) COLLATE NOCASE 
                AND (sg_sn = ? OR CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER))
            """, (group_name, sg_sn, sg_sn))
            page_serial_map = {row[0]: row[1] for row in cursor.fetchall()}
            
            if not page_serial_map:
                print(f"[SNAPSHOT] Warning: No pages found for {group_name} > {sg_sn} to save snapshots.")
            
            # 2. Iterate layout and save
            import json, hashlib
            
            for page_no, items in layout_map.items():
                serial_no = page_serial_map.get(page_no)
                if not serial_no: continue
                
                product_names = [p.get("data", {}).get("product_name", "") for p in items]
                
                # Compute Hash manually since we have the items
                content_parts = []
                for item in items:
                    data = item.get("data", {})
                    signature = {
                        "name": data.get("product_name", ""),
                        "row": item.get("row", 0),
                        "col": item.get("col", 0),
                        "rspan": item.get("rspan", 1),
                        "cspan": item.get("cspan", 2),
                        "mrp": str(data.get("mrp", "")),
                        "img": data.get("image_path", ""),
                        "sizes": str(data.get("sizes", []))
                    }
                    content_parts.append(signature)
                content_parts.sort(key=lambda x: (x["row"], x["col"], x["name"]))
                content_hash = hashlib.md5(json.dumps(content_parts, sort_keys=True).encode()).hexdigest()
                
                # Use JSON list instead of comma-join to handle names with commas
                self.save_page_snapshot(serial_no, content_hash, product_names)
                
            conn.close()
            print("[SNAPSHOT] Force-saved snapshots from Reshuffle layout.")
        except Exception as e:
            print(f"[SNAPSHOT] Error force-saving snapshots: {e}")

    def get_changed_products_since(self, since_date):
        """Get list of products changed since the given date.
        
        Args:
            since_date: Date string in format "DD-MM-YYYY HH:MM:SS"
            
        Returns:
            List of dicts with product info (product_name, group, sg_sn)
        """
        if not self.final_db_path: return []
        
        try:
            from datetime import datetime
            
            conn = sqlite3.connect(self.final_db_path)
            cursor = conn.cursor()
            
            # Parse since_date properly
            since_dt = None
            if since_date:
                try:
                    # Try parsing the expected format
                    since_dt = datetime.strptime(since_date, "%d-%m-%Y %H:%M:%S")
                except:
                    try:
                        # Alternative format without time
                        since_dt = datetime.strptime(since_date, "%d-%m-%Y")
                    except:
                        since_dt = None
            
            # Fetch all products with their update dates
            cursor.execute("""
                SELECT [Product Name], [Group], [SG_SN], [Update_date]
                FROM catalog
                WHERE [Group] IS NOT NULL
                AND [SG_SN] IS NOT NULL
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            changed = []
            for r in rows:
                product_name, group, sg_sn, update_date = r
                
                # If no since_date provided (first build), include all
                if since_dt is None:
                    changed.append({"product_name": product_name, "group": group, "sg_sn": sg_sn})
                    continue
                
                # Parse product's update date
                if update_date:
                    try:
                        prod_dt = datetime.strptime(str(update_date).strip(), "%d-%m-%Y %H:%M:%S")
                        if prod_dt > since_dt:
                            changed.append({"product_name": product_name, "group": group, "sg_sn": sg_sn})
                    except:
                        try:
                            prod_dt = datetime.strptime(str(update_date).strip(), "%d-%m-%Y")
                            if prod_dt > since_dt:
                                changed.append({"product_name": product_name, "group": group, "sg_sn": sg_sn})
                        except:
                            # If date parsing fails, include product (safer)
                            pass
            
            return changed
        except Exception as e:
            print(f"Error in get_changed_products_since: {e}")
            return []
    
    def find_pages_for_products(self, changed_products):
        """Find which pages the changed products are on.
        
        Args:
            changed_products: List from get_changed_products_since()
            
        Returns:
            Set of page serial_no values from catalog_pages
        """
        if not changed_products or not self.catalog_db_path:
            return set()
        
        affected_pages = set()
        
        # Group products by (group, sg_sn) to minimize layout simulations
        groups = {}
        for p in changed_products:
            key = (p["group"], p["sg_sn"])
            if key not in groups:
                groups[key] = []
            groups[key].append(p["product_name"])
        
        # For each group/subgroup, simulate layout and find pages
        for (group_name, sg_sn), product_names in groups.items():
            layout_map = self.simulate_page_layout(group_name, sg_sn)
            
            for page_num, items in layout_map.items():
                for item in items:
                    item_data = item.get("data", {})
                    item_name = item_data.get("product_name", "")
                    if item_name in product_names:
                        # Find the serial_no for this page
                        serial_no = self._get_page_serial_no(group_name, sg_sn, page_num)
                        if serial_no:
                            affected_pages.add(serial_no)
        
        return affected_pages
    
    def _get_page_serial_no(self, group_name, sg_sn, page_no):
        """Get serial_no for a specific page."""
        if not self.catalog_db_path: return None
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT serial_no FROM catalog_pages
                WHERE group_name=? AND sg_sn=? AND page_no=?
            """, (group_name, sg_sn, page_no))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except:
            return None

    def get_page_info_by_serial(self, serial_no):
        """Get page details (mg_sn, group_name, sg_sn, page_no) by global serial number."""
        if not self.catalog_db_path: return None
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mg_sn, group_name, sg_sn, page_no 
                FROM catalog_pages 
                WHERE serial_no=?
            """, (serial_no,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "mg_sn": row[0],
                    "group_name": row[1],
                    "sg_sn": row[2],
                    "page_no": row[3],
                    "serial_no": serial_no
                }
            return None
        except:
            return None

    def get_items_for_page_dynamic(self, group_name, sg_sn, page_no):
        """Get products for a specific page with caching."""
        if not self.catalog_db_path: return []
        
        # Create cache key
        cache_key = f"{group_name}|{sg_sn}"
        
        # Check cache first
        if cache_key in self._layout_cache:
            layout_map = self._layout_cache[cache_key]
        else:
            # Compute and cache
            layout_map = self._compute_layout(group_name, sg_sn)
            self._layout_cache[cache_key] = layout_map
        
        # Calculate relative page offset
        min_page = 1
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(page_no) FROM catalog_pages 
                WHERE TRIM(group_name)=? COLLATE NOCASE 
                  AND CAST(sg_sn AS INTEGER) = CAST(? AS INTEGER)
            """, (group_name.strip(), sg_sn))
            res = cursor.fetchone()
            conn.close()
            if res and res[0]: min_page = res[0]
        except:
            pass

        relative_page = page_no - min_page + 1
        return layout_map.get(relative_page, [])
    
    def _compute_layout(self, group_name, sg_sn, allow_backward=False, printable_pages=None):
        """Internal method to compute layout (routes through simulate_page_layout for consistency)."""
        return self.simulate_page_layout(group_name, sg_sn, allow_backward, printable_pages)

    def simulate_page_layout(self, group_name, sg_sn, allow_backward=False, printable_pages=None, use_cache=True, reshuffle=False, save_known=True):
        """Simulate product layout across pages with optional caching.
        
        Args:
            group_name: Group name
            sg_sn: Subgroup serial number
            allow_backward: If True, products can move to earlier pages. 
                           If False (default), products stay on same or later pages.
            printable_pages: Set of page numbers that are marked for print/reflow.
                            Products can only move backward to printable pages.
            use_cache: If True, use cached layout if available.
            reshuffle: If True, force full re-clustering/sorting of all products.
                      If False (default), new products are appended at the end.
            save_known: If True, persist display order to DB after computation.
                       Set to False for intermediate computations (e.g. sync_pages).
        """
        cache_key = f"{group_name}|{sg_sn}"
        
        if use_cache and not reshuffle:
            if cache_key in self._layout_cache:
                return self._layout_cache[cache_key]
        
        layout_map = self._simulate_page_layout_internal(group_name, sg_sn, allow_backward, printable_pages, reshuffle=reshuffle)
        self._layout_cache[cache_key] = layout_map
        
        # After layout, save the final product order (single source of truth)
        if save_known:
            all_product_names = []
            # Collect in page order → placement order
            for page_num in sorted(layout_map.keys()):
                for pl in layout_map[page_num]:
                    p_data = pl.get("data", {})
                    p_name = p_data.get("product_name", "") or p_data.get("name", "")
                    if p_name:
                        all_product_names.append(p_name.strip().lower())
            self._save_display_order(cache_key, all_product_names)
        
        return layout_map
    
    def get_existing_product_mapping(self, group_name, sg_sn):
        if not self.catalog_db_path: return {}
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cp.page_no, ps.product_list 
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps ON cp.serial_no = ps.serial_no
                WHERE cp.group_name=? AND cp.sg_sn=?
            """, (group_name, sg_sn))
            rows = cursor.fetchall()
            conn.close()
            
            mapping = {} # Name -> PageNo
            for page_no, p_list in rows:
                if p_list:
                    names = p_list.split(",")
                    for n in names:
                        if n.strip():
                            mapping[n.strip().lower()] = page_no
            return mapping
        except:
            return {}


    def get_ordered_product_names(self, group_name, sg_sn):
        """Get product names in order from previous snapshots (to preserve layout)."""
        if not self.catalog_db_path: return []
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ps.product_list 
                FROM catalog_pages cp
                LEFT JOIN page_snapshots ps ON cp.serial_no = ps.serial_no
                WHERE cp.group_name=? AND cp.sg_sn=?
                ORDER BY cp.page_no, cp.serial_no
            """, (group_name, sg_sn))
            rows = cursor.fetchall()
            conn.close()
            
            ordered = []
            import json
            for (p_list,) in rows:
                if p_list:
                    # Support both JSON (new) and Comma-Separated (old)
                    try:
                        # Try parsing as JSON list
                        names = json.loads(p_list)
                        if isinstance(names, list):
                            ordered.extend([str(n).strip().lower() for n in names])
                            continue
                    except:
                        pass
                        
                    # Fallback to legacy comma splitting
                    names = [n.strip().lower() for n in p_list.split(",") if n.strip()]
                    ordered.extend(names)
            return ordered
        except:
            return []

    def _simulate_page_layout_internal(self, group_name, sg_sn, allow_backward=False, printable_pages=None, reshuffle=False):
        """Internal layout computation with Incremental Logic (Lock Existing, Insert New, Sort Per Page)."""
        products = self.get_sorted_products_from_db(group_name, sg_sn)
        
        # --- SORTING LOGIC (Smart Grouping) ---
        # 1. Clustering with Bracket/Long-Word Heuristics
        # 2. Sort Clusters by Min Price
        # 3. Sort Items within by Price
        # Text cleaning & similarity functions imported from text_utils at module level


        def get_p_name(x):
            if isinstance(x, dict): return x.get("product_name", "") or x.get("name", "")
            return x[0] if x else ""

        def get_p_price(x):
            if isinstance(x, dict): return x.get("sort_price", 0)
            try: return float(str(x[4]).replace(",", "").strip()) if len(x)>4 else 0
            except: return 0

        def get_p_id(x):
            if isinstance(x, dict): return x.get("min_id", "ZZZZZZ")
            try: return str(x[11]) if len(x)>11 and x[11] else "ZZZZZZ"
            except: return "ZZZZZZ"

        # --- TWO-MODE SORTING ---
        cache_key = f"{group_name}|{sg_sn}"
        
        def do_full_clustering(items):
            """Full clustering+sorting (used for FIRST TIME and RESHUFFLE)."""
            clusters = []
            for item in items:
                name = get_p_name(item)
                clean_n = clean_cat_name(name)
                added = False
                for cluster in clusters:
                    rep_name = get_p_name(cluster[0])
                    rep_clean = clean_cat_name(rep_name)
                    if is_similar(clean_n, rep_clean):
                        cluster.append(item)
                        added = True
                        break
                if not added:
                    clusters.append([item])
            for cluster in clusters:
                cluster.sort(key=get_p_price)
            clusters.sort(key=lambda c: min(get_p_price(x) for x in c) if c else 0)
            return [item for cluster in clusters for item in cluster]
        
        if reshuffle:
            # RESHUFFLE MODE: Full clustering and sorting for ALL products
            products = do_full_clustering(products)
            print(f"[LAYOUT] RESHUFFLE mode: {len(products)} products fully re-sorted")
        else:
            # DEFAULT MODE: Use saved display order as the single source of truth
            saved_order = self._load_display_order(cache_key)
            
            if saved_order:
                # We have a saved order — separate existing vs new
                saved_set = set(saved_order)
                order_map = {name: i for i, name in enumerate(saved_order)}
                
                existing_products = []
                new_products = []
                for item in products:
                    p_name = get_p_name(item).strip().lower()
                    if p_name in saved_set:
                        existing_products.append(item)
                    else:
                        new_products.append(item)
                
                # Sort existing by their saved display order
                existing_products.sort(key=lambda x: order_map.get(get_p_name(x).strip().lower(), 999999))
                
                # Append new at end (unsorted — user must Reshuffle to sort)
                products = existing_products + new_products
                print(f"[LAYOUT] DEFAULT mode: {len(existing_products)} existing (saved order) + {len(new_products)} new (appended at end)")
            else:
                # No saved order = FIRST TIME catalog creation → full clustering
                products = do_full_clustering(products)
                print(f"[LAYOUT] FIRST-TIME mode: {len(products)} products fully clustered & sorted")
        
        # Inject Sort Order to Preserve Clustering during Reflow
        for i, p in enumerate(products):
            if isinstance(p, dict):
                p["exact_sort_order"] = i
        
        def get_sort_order(x):
            if isinstance(x, dict): return x.get("exact_sort_order", 999999)
            return 999999
        
        # ------------------------------------------

        layout_map = {}
        
        ROWS = 5
        COLS = 4
        
        def get_empty_grid(): 
            return [[False]*COLS for _ in range(ROWS)]
            
        # 1. Load Existing Mapping
        mapping = {} # Positions are determined by sort order above
        
        # 2. Assign Pages
        # We use temporary grids to determine available space for new items
        temp_grids = {} 
        assignments = [] # List of (p_data, page_no)
        
        # Helper Helpers
        def count_free_cells(g_state):
             return sum(1 for row in g_state for cell in row if not cell)

        # Helper: Dimension Calc
        def get_dims(p_data):
            if isinstance(p_data, dict):
                p_len = p_data.get("length")
                num_sizes = len(p_data.get("sizes", []))
            else:
                p_len = p_data[3] if len(p_data) > 3 else 1
                num_sizes = 1
            
            img_cols = 1  
            cspan = img_cols + 1 
            rspan = 3 if num_sizes > 10 else (2 if num_sizes > 5 else 1)
            
            if p_len and str(p_len).strip():
                s_len = str(p_len).strip()
                if "|" in s_len:
                    parts = s_len.split("|")
                    h_str = parts[0].strip()
                    v_str = parts[1].strip() if len(parts) > 1 else ""
                    
                    # Handle "Img:Data" format
                    if ":" in h_str:
                        h_parts = h_str.split(":")
                        iw = int(h_parts[0]) if h_parts[0].isdigit() else 1
                        dw = int(h_parts[1]) if len(h_parts) > 1 and h_parts[1].isdigit() else 1
                        cspan = iw + dw
                    else:
                        # Old format: h_str is Image Width, assume Data=1
                        if h_str and h_str.isdigit() and int(h_str) > 0:
                            cspan = int(h_str) + 1
                            
                    if v_str and v_str.isdigit() and int(v_str) > 0:
                        rspan = int(v_str)
                elif s_len.isdigit() and int(s_len) > 0:
                     rspan = int(s_len)
            return max(1, min(rspan, ROWS)), max(1, min(cspan, COLS))

        def find_slot(g_state, rspan, cspan):
            for r in range(ROWS):
                for c in range(COLS - cspan + 1):
                    if g_state[r][c]: continue
                    if r + rspan > ROWS: continue
                    fits = True
                    for dr in range(rspan):
                        for dc in range(cspan):
                            if g_state[r + dr][c + dc]:
                                fits = False; break
                        if not fits: break
                    if fits: return r, c
            return -1, -1

        # Helper for Linear Search (Moved Up for Phase 2 access)
        def find_slot_linear(g_state, rspan, cspan, start_r, start_c):
            # 1. Try rest of the start_row
            for c in range(start_c, COLS - cspan + 1):
                # Check fit
                fits = True
                for ir in range(start_r, start_r + rspan):
                    if ir >= ROWS: 
                        fits = False; break
                    for ic in range(c, c + cspan):
                        if g_state[ir][ic]: 
                            fits = False; break
                    if not fits: break
                if fits: return start_r, c
            
            # 2. Try subsequent rows
            for r in range(start_r + 1, ROWS):
                for c in range(0, COLS - cspan + 1):
                    # Check fit
                    fits = True
                    for ir in range(r, r + rspan):
                        if ir >= ROWS: 
                            fits = False; break
                        for ic in range(c, c + cspan):
                            if g_state[ir][ic]: 
                                fits = False; break
                        if not fits: break
                    if fits: return r, c
            return -1, -1

        def mark_slot(g_state, r, c, rspan, cspan):
            for dr in range(rspan):
                for dc in range(cspan):
                    g_state[r + dr][c + dc] = True

        def place_temp(page_num, rspan, cspan):
            if page_num not in temp_grids: temp_grids[page_num] = get_empty_grid()
            grid = temp_grids[page_num]
            r, c = find_slot(grid, rspan, cspan)
            if r != -1:
                mark_slot(grid, r, c, rspan, cspan)
                return True
            return False

        # Phase 2a: Assign Locked Products
        locked_items = []
        new_items = []
        
        for p_data in products:
            if isinstance(p_data, dict): p_name = p_data.get("product_name") or p_data.get("name")
            else: p_name = p_data[0]
            
            key = str(p_name).strip().lower()
            if key in mapping:
                page_no = mapping[key]
                rspan, cspan = get_dims(p_data)
                # Try to reserve space in temp grid (to block it for new items)
                # Note: We don't care about sort order here, just space reservation
                if place_temp(page_no, rspan, cspan):
                    assignments.append((p_data, page_no))
                else:
                    # Locked item no longer fits in its page? Treat as new.
                    new_items.append(p_data)
            else:
                new_items.append(p_data)
        
        # Phase 2b: Assign Products Sequentially (Respects Sort Order)
        # Fill pages in order: page 1, then 2, then 3...
        # This ensures products at the end of the list (new products) land on later pages
        pages_touched = set()
        current_page = 1
        
        for p_data in new_items:
            rspan, cspan = get_dims(p_data)
            placed = False
            
            # Try current page first, then subsequent pages
            while not placed:
                if place_temp(current_page, rspan, cspan):
                    assignments.append((p_data, current_page))
                    pages_touched.add(current_page)
                    placed = True
                else:
                    # Current page is full, move to next
                    current_page += 1
            
        # (Consecutive Reflow removed — sequential fill already handles ordering correctly)
            
        # Phase 3: Layout Each Page (Sorted) with Ripple Overflow
        # Group assignments
        page_groups = {}
        for p_data, page_no in assignments:
            if page_no not in page_groups: page_groups[page_no] = []
            page_groups[page_no].append(p_data)
            
        grids = {} # Reset grids for final clean layout
        
        # Dynamic processing queue for Ripple Effect
        page_queue = sorted(page_groups.keys())
        idx = 0
        
        while idx < len(page_queue):
            page_num = page_queue[idx]
            
            # Sort items on this page BY ORDER INDEX (Preserve Clustering)
            items = page_groups[page_num]
            items.sort(key=get_sort_order)
            
            grids[page_num] = get_empty_grid()
            layout_map[page_num] = []
            
            grid = grids[page_num]
            cursor_r, cursor_c = 0, 0
            
            overflow_items = []
            
            for p_data in items:
                rspan, cspan = get_dims(p_data)
                
                if page_num not in grids: grids[page_num] = get_empty_grid()
                grid = grids[page_num]
                
                # Strict Linear Search (Start from cursor)
                # NO FALLBACK allowed to prevent "Hole Jumping"
                r, c = find_slot_linear(grid, rspan, cspan, cursor_r, cursor_c)
                
                if r != -1:
                    mark_slot(grid, r, c, rspan, cspan)
                    layout_map[page_num].append({
                        "data": p_data, "row": r, "col": c,
                        "rspan": rspan, "cspan": cspan
                    })
                    cursor_r, cursor_c = r, c
                else:
                    # Overflow: Push to next page in the chain
                    overflow_items.append(p_data)
            
            # Handle Overflow
            if overflow_items:
                target_page = page_num + 1
                if target_page not in page_groups:
                    page_groups[target_page] = []
                    # Identify if we need to insert this page into our queue
                    if target_page not in page_queue:
                         page_queue.append(target_page)
                         page_queue.sort() # Reshuffle queue to ensure we visit target_page in order
                
                page_groups[target_page].extend(overflow_items)
            
            idx += 1
            
        # ═══════════════════════════════════════════════════════════════════════
        # POST-PROCESSING: Distribute empty spaces evenly across each page
        # This makes pages with fewer products look more balanced
        # ═══════════════════════════════════════════════════════════════════════
        layout_map = self._distribute_products_evenly(layout_map, ROWS, COLS)
                    
        return layout_map
    
    def _distribute_products_evenly(self, layout_map, ROWS, COLS):
        """
        Redistribute products on each page for visual balance.
        
        Strategy: Row-based distribution
        1. Group products by their rows
        2. Calculate how many physical rows products occupy
        3. Distribute those rows evenly across the page height
        4. Products within a row maintain their left-to-right order
        
        Example: 2 product-rows on 5-row page → rows 1 and 3 (centered)
        """
        for page_num, placements in layout_map.items():
            if not placements:
                continue
            
            # Group products by their current row
            row_groups = {}  # row_number -> list of placements
            for pl in placements:
                r = pl["row"]
                if r not in row_groups:
                    row_groups[r] = []
                row_groups[r].append(pl)
            
            # Get list of used rows (sorted)
            used_rows = sorted(row_groups.keys())
            num_product_rows = len(used_rows)
            
            # Skip if only 1 row or page is full
            if num_product_rows <= 1 or num_product_rows >= ROWS:
                continue
            
            # Calculate the maximum row span in each product row
            row_heights = {}
            for row_num in used_rows:
                max_rspan = max(pl.get("rspan", 1) for pl in row_groups[row_num])
                row_heights[row_num] = max_rspan
            
            # Total vertical space needed by products
            total_product_height = sum(row_heights.values())
            
            # If products already fill most rows, skip redistribution
            if total_product_height >= ROWS - 1:
                continue
            
            # Calculate new row positions - distribute evenly
            empty_space = ROWS - total_product_height
            
            # Distribute gaps evenly (including before first and after last)
            # For N product-rows, we have N+1 gap positions
            num_gaps = num_product_rows + 1
            base_gap = empty_space // num_gaps
            extra = empty_space % num_gaps  # Distribute extra to middle gaps
            
            # Build new positions
            new_placements = []
            current_row = base_gap  # Start after first gap
            
            # Add extra space to first gap to center content
            if extra > 0:
                current_row += extra // 2
            
            for orig_row in used_rows:
                products_in_row = row_groups[orig_row]
                row_height = row_heights[orig_row]
                
                # Sort products in this row by column (left to right)
                products_in_row_sorted = sorted(products_in_row, key=lambda p: p["col"])
                
                for pl in products_in_row_sorted:
                    rspan = pl.get("rspan", 1)
                    
                    # Ensure we don't go off page
                    new_row = min(current_row, ROWS - rspan)
                    new_row = max(0, new_row)
                    
                    new_placements.append({
                        **pl,
                        "row": new_row
                        # col stays the same - products stay in their horizontal position
                    })
                
                # Move to next position: current products + gap
                current_row += row_height + base_gap
            
            # Update layout
            layout_map[page_num] = new_placements
        
        return layout_map

    def get_sorted_products_from_db(self, group_name, sg_sn):
        if not self.final_db_path: return []
        try:
            conn = sqlite3.connect(self.final_db_path)
            cursor = conn.cursor()
            
            # Robust Query: Handle Spaces, Case, and SG_SN
            # Fetch ALL fields needed by A4CatalogPage
            # True/False Logic: Include if NULL, empty, or not explicitly 'false'/'0'
            # Stock Logic: Must have Stock > 0 OR True/False = 1
            cursor.execute("""
                SELECT [Product Name], [Item_Name], [Image_Path], [Lenth], [MRP], [Product_Size],
                       [MOQ], [Category], [M_Packing], [Unit], [Update_date], [ID]
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
                      OR 
                      LOWER(TRIM(CAST([True/False] AS TEXT))) IN ('1', 'true', 'yes')
                  )
                ORDER BY [ID] COLLATE NOCASE ASC
            """, (group_name.strip(), sg_sn))
            
            rows = cursor.fetchall()
            conn.close()
            
            # Grouping Logic (Mimic catalog.py)
            grouped_map = {}
            
            for r in rows:
                # 0:Name, 1:ItemName, 2:Img, 3:Len, 4:MRP, 5:Size, 6:MOQ, 7:Category, 8:M_Packing, 9:Unit
                raw_name = r[0] if r[0] and r[0].strip() else r[1]
                if not raw_name: continue
                
                # Normalize Key (Match catalog.py logic)
                norm_key = " ".join(raw_name.lower().replace("-", " ").replace("_", " ").strip().split())
                
                if norm_key not in grouped_map:
                    mrp_raw = str(r[4]) if r[4] else "0"
                    try:
                        p_val = float(mrp_raw.split(',')[0].strip())
                    except:
                        p_val = 99999999.0
                    
                    # Category processing (like catalog.py)
                    cat_val = str(r[7] or "").lower()
                    if "china" in cat_val:
                        cat_display = "चा."
                    elif "india" in cat_val:
                        cat_display = "ई."
                    else:
                        cat_display = ""
                        
                    grouped_map[norm_key] = {
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
                        "sort_price": p_val,
                        "min_id": str(r[11]) if len(r) > 11 and r[11] else "ZZZZZZ"
                    }
                
                g = grouped_map[norm_key]
                
                # Append variant data
                s_val = r[5] if r[5] else ""
                m_val = str(r[4]) if r[4] else ""
                moq_val = r[6] if r[6] else ""
                
                g["sizes"].append(s_val)
                g["mrps"].append(m_val)
                g["moqs"].append(moq_val)
                
                # Update Date Tracking
                u_date = str(r[10]) if len(r) > 10 and r[10] else ""
                if u_date and u_date > g["max_update_date"]:
                    g["max_update_date"] = u_date
                
                # Master Packing consolidation
                mp_raw = r[8]
                if mp_raw:
                    try:
                        import re
                        mp_match = re.search(r'\d+', str(mp_raw))
                        if mp_match:
                            g["_mp_set"].add(int(mp_match.group(0)))
                    except: pass
                
                # Update image if missing
                if not g["image_path"] and r[2]:
                     g["image_path"] = r[2]

            # Finalize groups
            final_list = []
            for g in grouped_map.values():
                # Build master_packing string
                base = str(g.get("base_units", "")).strip()
                mp_list = sorted(g.get("_mp_set", []))
                if mp_list:
                    g["master_packing"] = f'{",".join(map(str, mp_list))} {base}'.strip()
                g.pop("_mp_set", None)
                final_list.append(g)
            
            # NOTE: Do NOT sort here. Sorting is handled by the layout engine
            # only on first catalog creation or when Reshuffle is pressed.
            # final_list.sort(key=lambda x: x["sort_price"])
            
            return final_list

        except Exception as e:
            try:
                with open("catalog_error.log", "a") as f: f.write(f"Fetch Error: {e}\n")
            except: pass
            return []

    def find_page_index_by_subgroup(self, main_group, sg_text):
        # Implementation for finding index in all_pages_data list
        # Note: Logic needs access to all_pages_data or DB. 
        # Easier to handle in UI or pass DB path.
        # Returning -1 as placeholder if logic depends on UI list state.
        return -1

    def find_empty_pages(self):
        """Returns a list of (group_name, sg_sn, page_no) that are empty."""
        if not self.catalog_db_path: return []
        
        empty_pages = []
        try:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            
            # Get all defined pages
            cursor.execute("SELECT group_name, sg_sn, page_no FROM catalog_pages ORDER BY group_name, sg_sn, page_no")
            rows = cursor.fetchall()
            conn.close()
            
            # Organize by subgroup
            pages_by_subgroup = {}
            for g, s, p in rows:
                key = (g, s)
                if key not in pages_by_subgroup:
                    pages_by_subgroup[key] = []
                pages_by_subgroup[key].append(p)
                
            # Check each subgroup
            for (g, s), pages in pages_by_subgroup.items():
                layout_map = self.simulate_page_layout(g, s)
                
                for p in pages:
                    # If page not in layout map -> Empty
                    # OR if page in layout map but empty list -> Empty
                    if p not in layout_map or not layout_map[p]:
                        empty_pages.append((g, s, p))
                        
            return empty_pages
            
        except Exception as e:
            print(f"Error finding empty pages: {e}")
            return []