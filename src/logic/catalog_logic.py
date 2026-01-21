import sqlite3
import os

class CatalogLogic:
    def __init__(self, db_path):
        self.db_path = db_path
        self.catalog_db_path = None
        self.final_db_path = None
        
        # Layout cache to avoid recomputing layouts repeatedly
        self._layout_cache = {}
        self._cache_valid = False
        
        # Derive calendar path (assuming 'data/calendar_data.db' relative to app root)
        # Derive calendar path (assuming 'data/calendar_data.db' relative to app root)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # backup code/
        self.calendar_db_path = os.path.join(base_dir, "data", "calendar_data.db")
        if not os.path.exists(self.calendar_db_path):
            # Fallback for testing environment
            self.calendar_db_path = "data/calendar_data.db"

    def set_paths(self, catalog_db, final_db):
        self.catalog_db_path = catalog_db
        self.final_db_path = final_db
        # Invalidate cache when paths change
        self._layout_cache = {}
        self._cache_valid = False
    
    def invalidate_cache(self):
        """Call this when product data changes."""
        self._layout_cache = {}
        self._cache_valid = False
        
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
            query = f"SELECT DISTINCT [MG_SN], [Group_Name] FROM {table} WHERE [MG_SN] IS NOT NULL ORDER BY CAST([MG_SN] AS INTEGER)"
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
            query = f"SELECT DISTINCT [MG_SN], [Group_Name], [SG_SN] FROM {table} WHERE [Group_Name] IS NOT NULL AND [SG_SN] IS NOT NULL ORDER BY CAST([MG_SN] AS INTEGER), CAST([SG_SN] AS INTEGER)"
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        except: return []

    # =========================================================
    # DYNAMIC LAYOUT ENGINE
    # =========================================================

    def sync_pages_with_content(self):
        """Checks all subgroups and auto-creates pages if content overflows."""
        if not self.catalog_db_path: return
        try:
            # 1. Get all master subgroups
            all_subgroups = self.get_page_data_list() 
            
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            
            for mg_sn, group_name, sg_sn in all_subgroups:
                # Run layout simulation
                layout_map = self.simulate_page_layout(group_name, sg_sn)
                max_required_page = max(layout_map.keys()) if layout_map else 1
                
                # Check existing pages in DB
                cursor.execute("SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?", (group_name, sg_sn))
                res = cursor.fetchone()
                current_max = res[0] if res and res[0] else 0
                
                # If we need more pages, add them
                if max_required_page > current_max:
                    for p in range(current_max + 1, max_required_page + 1):
                        cursor.execute("""
                            INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no)
                            VALUES (?, ?, ?, ?)
                        """, (mg_sn, group_name, sg_sn, p))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Sync Pages Error: {e}")

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
        """Internal method to compute layout without caching."""
        return self._simulate_page_layout_internal(group_name, sg_sn, allow_backward, printable_pages)

    def simulate_page_layout(self, group_name, sg_sn, allow_backward=False, printable_pages=None, use_cache=True):
        """Simulate product layout across pages with optional caching.
        
        Args:
            group_name: Group name
            sg_sn: Subgroup serial number
            allow_backward: If True, products can move to earlier pages. 
                           If False (default), products stay on same or later pages.
            printable_pages: Set of page numbers that are marked for print/reflow.
                            Products can only move backward to printable pages.
            use_cache: If True, use cached layout if available.
        """
        if use_cache:
            cache_key = f"{group_name}|{sg_sn}"
            if cache_key in self._layout_cache:
                return self._layout_cache[cache_key]
            layout_map = self._simulate_page_layout_internal(group_name, sg_sn, allow_backward, printable_pages)
            self._layout_cache[cache_key] = layout_map
            return layout_map
        else:
            return self._simulate_page_layout_internal(group_name, sg_sn, allow_backward, printable_pages)
    
    def _simulate_page_layout_internal(self, group_name, sg_sn, allow_backward=False, printable_pages=None):
        """Internal layout computation without caching."""
        products = self.get_sorted_products_from_db(group_name, sg_sn)
        layout_map = {}
        current_page = 1
        
        ROWS = 5
        COLS = 4
        PRODUCT_CSPAN = 2  # Each product takes 2 columns (1 image + 1 data)
        
        def get_empty_grid(): 
            return [[False]*COLS for _ in range(ROWS)]
            
        # State tracking: grids[page_num] = boolean matrix
        grids = {}
        
        # Product page tracking for stability (prevent backward movement)
        product_page_tracking = {}
        
        # Initialize Page 1
        current_page = 1
        grids[current_page] = get_empty_grid()
        layout_map[current_page] = []
        
        def find_slot(g_state, rspan, cspan):
            """Find first available slot that fits rspan rows x cspan columns."""
            for r in range(ROWS):
                for c in range(COLS - cspan + 1):  # Must fit cspan columns
                    if g_state[r][c]:
                        continue
                    if r + rspan > ROWS:
                        continue
                    # Check all cells in the block
                    fits = True
                    for dr in range(rspan):
                        for dc in range(cspan):
                            if g_state[r + dr][c + dc]:
                                fits = False
                                break
                        if not fits:
                            break
                    if fits:
                        return r, c
            return -1, -1

        def mark_slot(g_state, r, c, rspan, cspan):
            """Mark all cells in the block as occupied."""
            for dr in range(rspan):
                for dc in range(cspan):
                    g_state[r + dr][c + dc] = True

        if not products: 
            return {}
        layout_map[current_page] = []
        
        for p_data in products:
            # Handle Dict or Tuple
            if isinstance(p_data, dict):
                p_name = p_data.get("product_name") or p_data.get("name")
                p_len = p_data.get("length")
                # Auto-length based on number of sizes
                num_sizes = len(p_data.get("sizes", []))
            else:
                p_name = p_data[0]
                p_len = p_data[2] if len(p_data) > 2 else 1
                num_sizes = 1
            
            # Default Dimensions
            # Default: 1 Image Col + 1 Data Col = 2 cspan
            img_cols = 1  
            cspan = img_cols + 1 
            
            # Auto-length logic (Vertical / rspan): 
            if num_sizes > 10:
                rspan = 3
            elif num_sizes > 5:
                rspan = 2
            else:
                rspan = 1
            
            # Process Manual Length Column (p_len)
            # Supported Formats:
            # 1. "V" (Integer) -> rspan=V, img_cols=1 (default)
            # 2. "H|V" (ImageCols|Rows) -> img_cols=H, rspan=V
            #    (Total cspan = H + 1)
            
            if p_len and str(p_len).strip():
                s_len = str(p_len).strip()
                if "|" in s_len:
                    parts = s_len.split("|")
                    h_str = parts[0].strip()
                    v_str = parts[1].strip() if len(parts) > 1 else ""
                    
                    # Parse H (Image Width)
                    if h_str:
                        try:
                            h_val = int(h_str)
                            if h_val > 0:
                                img_cols = h_val
                                cspan = img_cols + 1
                        except: pass
                    
                    # Parse V (Vertical Rows)
                    if v_str:
                        try:
                             v_val = int(v_str)
                             if v_val > 0:
                                 rspan = v_val
                        except: pass
                        
                elif s_len.isdigit() and int(s_len) > 0:
                     # Just V provided (Legacy integers are treated as Vertical override)
                     rspan = int(s_len)
            
            # Clamping
            rspan = max(1, min(rspan, ROWS))
            cspan = max(1, min(cspan, COLS))  # COLS=4
            
            # Smart Placement Logic: Place product on page with MOST FREE SPACE
            # But respect stability rules - don't move products backward unless allowed
            placed = False
            
            def count_free_cells(g_state):
                """Count unoccupied cells in a grid."""
                return sum(1 for row in g_state for cell in row if not cell)
            
            # Get product's last known page (if any) from tracking
            product_key = p_name.lower().strip() if p_name else ""
            last_page = product_page_tracking.get(product_key, 0)
            
            # Find page with most free space that can fit this product
            best_page = None
            best_free_count = -1
            best_slot = (-1, -1)
            
            for page_num in sorted(layout_map.keys()):
                # Stability check: Don't move product backward unless allowed
                if not allow_backward and page_num < last_page:
                    # Can only go back if that page is marked for printing/reflow
                    if printable_pages and page_num not in printable_pages:
                        continue  # Skip this page - can't go backward
                
                grid = grids[page_num]
                r, c = find_slot(grid, rspan, cspan)
                if r != -1:
                    # Can fit here - check free space
                    free_count = count_free_cells(grid)
                    if free_count > best_free_count:
                        best_free_count = free_count
                        best_page = page_num
                        best_slot = (r, c)
            
            if best_page is not None:
                # Place on page with most space
                r, c = best_slot
                mark_slot(grids[best_page], r, c, rspan, cspan)
                layout_map[best_page].append({
                    "data": p_data,
                    "row": r,
                    "col": c,
                    "rspan": rspan,
                    "cspan": cspan
                })
                # Update tracking
                product_page_tracking[product_key] = best_page
                placed = True
            
            if not placed:
                # Page full or no slot big enough found in any existing page
                # Create NEW page
                current_page = max(layout_map.keys()) + 1 if layout_map else 1
                grid = get_empty_grid()
                grids[current_page] = grid
                layout_map[current_page] = []
                
                # We know it's a fresh page, so it goes to 0,0 (unless item > page??)
                # But find_slot is safer.
                r, c = find_slot(grid, rspan, cspan)
                
                if r != -1:
                    mark_slot(grid, r, c, rspan, cspan)
                    layout_map[current_page].append({
                        "data": p_data,
                        "row": r,
                        "col": c,
                        "rspan": rspan,
                        "cspan": cspan
                    })
                else:
                    print(f"CRITICAL: Product '{p_name}' too big for empty page! ({rspan}x{cspan})")
                    
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
                       [MOQ], [Categori], [M_Packing], [Unit], [Update_date]
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
                        "length": r[3] if r[3] else "1",
                        "sizes": [],
                        "mrps": [],
                        "moqs": [],
                        "base_units": r[9] if r[9] else "",
                        "category": cat_display,
                        "master_packing": "",
                        "_mp_set": set(),
                        "max_update_date": "",
                        "sort_price": p_val
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
            
            # Sort by price
            final_list.sort(key=lambda x: x["sort_price"])
            
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