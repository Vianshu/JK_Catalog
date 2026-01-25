import os
import json
import sqlite3
import datetime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor
# Aapka original processor
from src.logic.data_processor import DataProcessor

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)
        
class FinalDataUI(QWidget):
    def __init__(self):
        super().__init__()
        self.db_path = ""
        self.image_folder = ""
        self.headers = [
            "GUID", "ID", "Item_Name", "Alias", "Part_No", "Product Name", 
            "Product_Size", "Category", "Unit", "MOQ", "M_Packing", "MRP", 
            "Stock", "MG_SN", "Group", "SG_SN", "Sub_Group", "Image_Name", 
            "Image_Path", "Lenth", "Image_Date", "True/False", "Update_date"
        ]
        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        self.table = QTableWidget(0, len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        
        # 1. GUID ko hide karna (Pehle se shayad tha)
        self.table.setColumnHidden(0, True)
        
        # 3. Side wale row numbers (1,2,3...) ko hatane ke liye:
        self.table.verticalHeader().setVisible(False)
        
        # --- NAYA: Database mein save karne ke liye signal ---
        self.table.itemChanged.connect(self.save_cell_to_db)

        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        
        self.table.cellClicked.connect(self.show_preview)
        self.table.cellDoubleClicked.connect(self.show_path_popup)
        
        main_layout.addWidget(self.table, 1)

        # Side Panel Logic (Aapke backup se same)
        main_layout.addWidget(self.table, 4) # Table gets 4 parts weight

        # --- RIGHT SIDE PANEL (Updated Layout) ---
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(5, 5, 5, 5)
        side_layout.setSpacing(8)

        # 1. Sync Time (Top)
        self.sync_lbl = QLabel("Last Sync: N/A")
        self.sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_lbl.setStyleSheet("font-weight: bold; color: #555; padding: 5px;")
        side_layout.addWidget(self.sync_lbl)

        # 2. Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Item Name...")
        self.search_input.textChanged.connect(self.filter_table)
        side_layout.addWidget(self.search_input)

        # 3. Image Preview (NOW ON TOP)
        from PyQt6.QtWidgets import QFrame, QGridLayout, QSizePolicy
        img_container = QFrame()
        img_container.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #007bff;
                border-radius: 8px;
            }
        """)
        img_container_layout = QVBoxLayout(img_container)
        img_container_layout.setContentsMargins(5, 5, 5, 5)
        
        img_title = QLabel("🖼️ Image Preview")
        img_title.setStyleSheet("font-weight: bold; color: #333; border: none;")
        img_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_container_layout.addWidget(img_title)
        
        self.img_preview = QLabel("NO IMAGE")
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 4px;")
        self.img_preview.setMinimumSize(200, 200)
        self.img_preview.setMaximumSize(400, 400)
        self.img_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        img_container_layout.addWidget(self.img_preview, 1)
        
        side_layout.addWidget(img_container, 1) # Takes available space

        # 4. Summary Statistics Panel (BELOW IMAGE)
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        summary_grid = QGridLayout(summary_frame)
        summary_grid.setSpacing(5)
        
        # Summary Title
        summary_title = QLabel("📊 Summary")
        summary_title.setStyleSheet("font-weight: bold; font-size: 12pt; color: #333; border: none;")
        summary_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_grid.addWidget(summary_title, 0, 0, 1, 2)
        
        # Catalog Total Items (True/False = 1)
        self.lbl_catalog_total = QLabel("Catalog Total:")
        self.lbl_catalog_total.setStyleSheet("font-weight: 500; color: #333; border: none;")
        self.lbl_catalog_total_val = QLabel("0")
        self.lbl_catalog_total_val.setStyleSheet("font-weight: bold; color: #28a745; border: none;")
        self.lbl_catalog_total_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_catalog_total, 1, 0)
        summary_grid.addWidget(self.lbl_catalog_total_val, 1, 1)
        
        # Out of Stock (Stock=0 but True/False != false)
        self.lbl_out_stock = QLabel("Out of Stock:")
        self.lbl_out_stock.setStyleSheet("font-weight: 500; color: #333; border: none;")
        self.lbl_out_stock_val = QLabel("0")
        self.lbl_out_stock_val.setStyleSheet("font-weight: bold; color: #fd7e14; border: none;")
        self.lbl_out_stock_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_out_stock, 2, 0)
        summary_grid.addWidget(self.lbl_out_stock_val, 2, 1)
        
        # False Items
        self.lbl_false = QLabel("False Items:")
        self.lbl_false.setStyleSheet("font-weight: 500; color: #333; border: none;")
        self.lbl_false_val = QLabel("0")
        self.lbl_false_val.setStyleSheet("font-weight: bold; color: #dc3545; border: none;")
        self.lbl_false_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_false, 3, 0)
        summary_grid.addWidget(self.lbl_false_val, 3, 1)
        
        # Separator
        sep_line = QLabel("─" * 20)
        sep_line.setStyleSheet("color: #ccc; border: none;")
        sep_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_grid.addWidget(sep_line, 4, 0, 1, 2)
        
        # Final Data Total
        self.lbl_final_total = QLabel("Final Data Total:")
        self.lbl_final_total.setStyleSheet("font-weight: 500; color: #333; border: none;")
        self.lbl_final_total_val = QLabel("0")
        self.lbl_final_total_val.setStyleSheet("font-weight: bold; color: #007bff; border: none;")
        self.lbl_final_total_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_final_total, 5, 0)
        summary_grid.addWidget(self.lbl_final_total_val, 5, 1)
        
        # Item Mismatch
        self.lbl_mismatch = QLabel("Item Mismatch:")
        self.lbl_mismatch.setStyleSheet("font-weight: 500; color: #333; border: none;")
        self.lbl_mismatch_val = QLabel("0")
        self.lbl_mismatch_val.setStyleSheet("font-weight: bold; color: #6f42c1; border: none;")
        self.lbl_mismatch_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_mismatch, 6, 0)
        summary_grid.addWidget(self.lbl_mismatch_val, 6, 1)
        
        side_layout.addWidget(summary_frame)

        # 5. Status Label
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        side_layout.addWidget(self.status_lbl)

        main_layout.addWidget(side_panel, 1) # Side panel gets 1 part weight
        
        # Connect Selection Change for Arrow Keys
        self.table.selectionModel().currentRowChanged.connect(self.on_row_changed)


    def col_index(self, name):
        return self.headers.index(name)

    def current_datetime(self):
        return datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')

    def get_file_modify_date(self, file_path):
        try:
            if file_path and os.path.exists(file_path):
                # File ki modification date nikalna
                mtime = os.path.getmtime(file_path)
                return datetime.datetime.fromtimestamp(mtime).strftime('%d-%m-%Y %H:%M:%S')
        except:
            pass
        return ""

    # --- HELPER: Calc Length ---
    def calc_length_from_size(self, size_str):
        # Always default to "1|0" (Auto Height)
        # 1 = One extra column (total 2 cols)
        # 0 = Auto Vertical Height (calculated based on num sizes in Logic)
        return "1|0"

    # --- NAYA: Manual Edit Save karne ka logic ---
    def on_row_changed(self, current, previous):
        if current.isValid():
            self.show_preview(current.row(), current.column())

    def save_cell_to_db(self, item):
        if self.table.signalsBlocked(): return
        
        new_val = item.text().strip()
        old_val = item.data(Qt.ItemDataRole.UserRole)
        row, col = item.row(), item.column()
        col_name = self.headers[col]

        # --- VALIDATION: True/False Column (Index 21) ---
        if col == 21: # True/False Column
            lower_val = new_val.lower()
            
            # Check for Image Path "no_need" condition
            img_path_item = self.table.item(row, self.col_index("Image_Path"))
            img_path_val = img_path_item.data(Qt.ItemDataRole.UserRole) if img_path_item else ""
            
            if "no_need" in str(img_path_val).lower() or "no need" in str(img_path_val).lower():
                final_bool_val = "false"
            elif lower_val in ["f", "false", "flase", "0", "no"]:
                final_bool_val = "false"
            elif lower_val in ["1", "true", "t", "yes"]:
                 final_bool_val = "1"
            else:
                 # "For all other valid cases... print true" -> Default to "1"
                 final_bool_val = "1"
            
            # If value changed due to auto-correct, update UI immediately
            if final_bool_val != new_val:
                self.table.blockSignals(True)
                item.setText(final_bool_val)
                self.table.blockSignals(False)
                new_val = final_bool_val

        # --- NAYA: Auto-Update Length if Product_Size changes ---
        if col_name == "Product_Size":
             # Recalculate Length
             new_len = self.calc_length_from_size(new_val)
             
             # Setup Update for Length too
             # We need to update DB for Length AND Product_Size
             # Doing separate update for Length to keep simple logic or combine?
             # Simple: Update Product_Size first (below), then Update Length.
             pass 

        # Check if actual change happened (after normalization)
        if str(new_val) == str(old_val):
            return 

            # --- UPDATE DATE TRIGGER ---
        # List of columns that trigger update_date
        trigger_cols = [
            "Product Name", "Product_Size", "Category", "Unit", "MOQ", 
            "M_Packing", "MRP", "MG_SN", "Group", "SG_SN", "Sub_Group", 
            "Image_Path", "Length", "Image_Date", "True/False"
        ]
        
        should_update_date = col_name in trigger_cols
        
        try:
            guid_item = self.table.item(row, 0)
            if not guid_item: return
            guid = guid_item.text()

            now = self.current_datetime()

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            if should_update_date:
                cur.execute(f"UPDATE catalog SET [{col_name}]=?, Update_date=? WHERE GUID=?", (new_val, now, guid))
            else:
                cur.execute(f"UPDATE catalog SET [{col_name}]=? WHERE GUID=?", (new_val, guid))
            
            # --- If Image_Path was just set to 'no need', force True/False to 'false' ---
            if col_name == "Image_Path":
                if "no_need" in new_val.lower() or "no need" in new_val.lower() or "noneed" in new_val.lower():
                    cur.execute("UPDATE catalog SET [True/False]='false' WHERE GUID=?", (guid,))
                    # Also update the UI
                    tf_col = self.col_index("True/False")
                    self.table.blockSignals(True)
                    tf_item = self.table.item(row, tf_col)
                    if tf_item:
                        tf_item.setText("false")
                    self.table.blockSignals(False)
                
            conn.commit()
            conn.close()

            item.setData(Qt.ItemDataRole.UserRole, new_val) # Update memory

            if should_update_date:
                self.table.blockSignals(True)
                self.table.setItem(row, self.col_index("Update_date"), QTableWidgetItem(now))
                self.table.blockSignals(False)
            
            self.status_lbl.setText(f"Updated: {col_name}" + (f" & Date at {now}" if should_update_date else ""))
            
            self.status_lbl.setText(f"Updated: {col_name}" + (f" & Date at {now}" if should_update_date else ""))
            
            # --- Post-Update Logic: Update Length if Size Changed ---
            if col_name == "Product_Size":
                 new_len = self.calc_length_from_size(new_val)
                 cur = conn.cursor()
                 conn = sqlite3.connect(self.db_path) # Reconnect/Reuse? Conn closed above.
                 cursor = conn.cursor()
                 cursor.execute("UPDATE catalog SET Lenth=? WHERE GUID=?", (new_len, guid))
                 conn.commit()
                 conn.close()
                 
                 # UI Update
                 len_col = self.col_index("Lenth")
                 self.table.blockSignals(True)
                 self.table.setItem(row, len_col, QTableWidgetItem(new_len))
                 self.table.blockSignals(False)
                 self.status_lbl.setText(f"Updated: Size & Lenth ({new_len})")

            # Refresh stats if needed
            # self.calculate_stats() 

        except Exception as e:
            print(f"Update Error: {e}")

    def load_and_sync_data(self, company_name):
        try:
            # 1. Path Setup
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            vault_path = os.path.join(base_dir, "company_vault.json")
            with open(vault_path, 'r', encoding='utf-8') as f:
                vault = json.load(f)

            comp_data = vault[company_name]
            self.image_folder = comp_data.get('image_path', "")
            self.db_path = os.path.join(comp_data['path'], "final_data.db")
            row_db_path = os.path.join(comp_data['path'], "row_data.db")
            
            final_conn = sqlite3.connect(self.db_path)
            cur = final_conn.cursor()
            
            # Ensure Table Exists
            cur.execute(f"CREATE TABLE IF NOT EXISTS catalog ({', '.join([f'[{h}] TEXT' for h in self.headers])})")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_guid ON catalog (GUID)")

            # 3. Super Master Mapping (ID banane ke liye zaroori)
            super_mapping = {}
            super_db = os.path.join(os.path.dirname(comp_data['path']), "super_master.db")
            if os.path.exists(super_db):
                with sqlite3.connect(super_db) as s_conn:
                    for r in s_conn.execute("SELECT Sub_Group, MG_SN, Group_Name, SG_SN FROM super_master"):
                        # Mapping: SubGroup -> (MG_SN, GroupName, SG_SN)
                        super_mapping[r[0]] = (r[1], r[2], r[3])
            
            # 4. Tally Data Fetch
            with sqlite3.connect(row_db_path) as row_conn:
                rows = row_conn.execute("SELECT GUID, Item_Name, FirstAlias, Part_No, Category, Unit, SubGroup, MRP, Closing_Qty FROM stock_items").fetchall()

            now = self.current_datetime()
            self.sync_lbl.setText(f"Last Sync: {now}")
            
            for r in rows:
                guid = r[0]
                sub_group_name = r[6]
                
                # Sahi jagah s_data nikalne ki
                s_data = super_mapping.get(sub_group_name, ("", "", ""))
                
                cur.execute("""
                    SELECT Item_Name, Alias, Part_No, Category, Unit, 
                           MRP, Stock, MG_SN, [Group], SG_SN, Sub_Group, [Product_Size]
                    FROM catalog WHERE GUID=?
                """, (guid,))
                old_row_db = cur.fetchone()
                
                new_row = tuple("" if v is None else str(v) for v in (
                    r[1],          # Item_Name
                    r[2],          # Alias
                    r[3],          # Part_No
                    r[4],          # Category
                    r[5],          # Unit
                    r[7],          # MRP
                    r[8],          # Stock
                    s_data[0],     # MG_SN
                    s_data[1],     # Group
                    s_data[2],     # SG_SN
                    r[6],          # Sub_Group
                ))

                # DB se aayi purani row ko bhi normalize karo
                old_row_norm = tuple("" if v is None else str(v) for v in old_row_db) if old_row_db else None

                data_changed = old_row_norm != new_row
                
                new_mrp = str(r[7])
                new_stock = str(r[8])

                if old_row_db:
                    if data_changed:
                        query = """UPDATE catalog SET 
                            Item_Name=?, Alias=?, Part_No=?, Category=?, Unit=?, 
                            MRP=?, Stock=?, MG_SN=?, [Group]=?, SG_SN=?, Sub_Group=?, 
                            Update_date=? 
                            WHERE GUID=?"""
                        cur.execute(query, (*new_row, now, guid))
                    else:
                        # Data unchanged. Do NOT touch Lenth.
                        # This preserves manual edits (e.g. 1|0, 2|2) in the catalog.
                        pass
                else:
                    # Bilkul naya item (Insert)
                    f_row = [None] * len(self.headers)
                    f_row[self.col_index("GUID")] = guid
                    f_row[self.col_index("Item_Name")] = r[1]
                    f_row[self.col_index("Alias")] = r[2]
                    f_row[self.col_index("Part_No")] = r[3]
                    f_row[self.col_index("Category")] = r[4]
                    f_row[self.col_index("Unit")] = r[5]
                    f_row[self.col_index("MRP")] = r[7]
                    f_row[self.col_index("Stock")] = r[8]
                    f_row[self.col_index("MG_SN")] = s_data[0]
                    f_row[self.col_index("Group")] = s_data[1]
                    f_row[self.col_index("SG_SN")] = s_data[2]
                    f_row[self.col_index("Sub_Group")] = r[6]
                    f_row[self.col_index("Lenth")] = "1"
                    f_row[self.col_index("Update_date")] = now
                    
                    # Insert Query
                    placeholders = ', '.join(['?'] * len(self.headers))
                    cols = ', '.join([f"[{h}]" for h in self.headers])
                    query = f"INSERT INTO catalog ({cols}) VALUES ({placeholders})"
                    cur.execute(query, f_row)

            final_conn.commit()
            final_conn.close()

            # --- STEP B: AAPKA PROCESSOR TRIGGER KARNA (Yahan se Product Name banega) ---
            processor = DataProcessor(self.db_path)
            # 1. Product Name, Size, MOQ, Image Name generate karein
            processor.process_and_save_final_data() 
            # 2. Sahi format mein Complex IDs generate karein
            processor.generate_complex_ids()

            # 4. Image Sync (Files check karna)
            self.sync_images_after_processing()
            
            self.refresh_table()
            # self.status_lbl.setText("Sync Complete! All Processor logic applied.")

        except Exception as e:
            print(f"Sync Error: {e}")
            
    def sync_images_after_processing(self):
        # Processor ke kaam ke baad image paths update karne ke liye
        try:
            conn = sqlite3.connect(self.db_path)
            img_map = self.get_image_mapping()
            for rid, img_name in conn.execute("SELECT rowid, Image_Name FROM catalog"):
                clean = img_name.lower().strip() if img_name else ""
                
                # Check for "no need" in Image Name
                if "no_need" in clean or "no need" in clean or "noneed" in clean:
                     conn.execute("UPDATE catalog SET Image_Path='no_need', [True/False]='false' WHERE rowid=?", (rid,))
                     continue

                if clean in img_map:
                    path = img_map[clean]
                    date = self.get_file_modify_date(path)
                    conn.execute("UPDATE catalog SET Image_Path=?, Image_Date=? WHERE rowid=?", (path, date, rid))
                else:
                    conn.execute("UPDATE catalog SET Image_Path='', Image_Date='' WHERE rowid=?", (rid,))
            conn.commit()
            conn.close()
            
            # After image sync, update True/False values
            self.sync_true_false_values()
        except Exception as e:
            print(f"Image Sync Error: {e}")
    
    def sync_true_false_values(self):
        """
        Update True/False column based on business logic:
        - If Stock = 0 AND True/False is already '1' -> keep as '1' (user override)
        - If Stock = 0 AND True/False is not '1' -> 'false'
        - If Image_Path contains 'no_need' -> 'false'
        - If Group = 'Price List' -> depends only on stock
        - Otherwise -> '1'
        """
        try:
            if not self.db_path or not os.path.exists(self.db_path):
                return
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get all rows with relevant columns
            cursor.execute("""
                SELECT rowid, Stock, Image_Path, [Group], [True/False]
                FROM catalog
            """)
            rows = cursor.fetchall()
            
            for row in rows:
                rid, stock, img_path, group_name, current_tf = row
                
                # Normalize current True/False value
                current_tf_str = str(current_tf).strip().lower() if current_tf else ""
                current_is_true = current_tf_str in ["1", "true", "yes"]
                
                # Determine new True/False value
                new_tf = "1"  # Default to True (1)
                
                # Check Stock - if 0 or empty
                try:
                    stock_val = float(str(stock).replace(",", "").strip()) if stock else 0
                    if stock_val <= 0:
                        # KEY CHANGE: If True/False is already "1", keep it (user override)
                        if current_is_true:
                            new_tf = "1"  # Preserve user's manual override
                        else:
                            new_tf = "false"
                except:
                    # Invalid stock - check if already true
                    if current_is_true:
                        new_tf = "1"
                    else:
                        new_tf = "false"
                
                # Price List group doesn't need images, keep as is based on stock
                group_str = str(group_name).lower().strip() if group_name else ""
                if group_str == "price list":
                    # Price list items only depend on stock
                    try:
                        stock_val = float(str(stock).replace(",", "").strip()) if stock else 0
                        if stock_val > 0:
                            new_tf = "1"
                        elif current_is_true:
                            new_tf = "1"  # Preserve user override
                        else:
                            new_tf = "false"
                    except:
                        new_tf = "1" if current_is_true else "false"
                else:
                    # For NON-Price List items:
                    # 1. If Image Path is empty (Missing), MUST be False
                    if not img_path or not str(img_path).strip():
                        new_tf = "false"

                # Check Image_Path for 'no_need' - overrides everything including user override AND Price List
                img_path_str = str(img_path).lower().strip() if img_path else ""
                if "no_need" in img_path_str or "noneed" in img_path_str or "no need" in img_path_str:
                    new_tf = "false"
                
                # Update only if changed
                if current_tf_str != new_tf and not (current_tf_str == "1" and new_tf == "1"):
                    cursor.execute("UPDATE catalog SET [True/False]=? WHERE rowid=?", (new_tf, rid))
            
            # --- FORCE DEFAULT LENGTH 1|0 ---
            cursor.execute("UPDATE catalog SET Lenth='1|0' WHERE Lenth IS NULL OR TRIM(Lenth)=''")
            # Also fix existing '1' entries to auto-height '1|0'
            cursor.execute("UPDATE catalog SET Lenth='1|0' WHERE TRIM(Lenth)='1'")
            
            conn.commit()
            conn.close()
            print(f"True/False sync completed for {len(rows)} items")
            
        except Exception as e:
            print(f"True/False Sync Error: {e}")

    def refresh_table(self):
        if not self.db_path: return
        try:
            self.table.blockSignals(True)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            
            with sqlite3.connect(self.db_path) as conn:
                data = conn.execute("SELECT * FROM catalog").fetchall()

            # Python-level Sorting (Missing Images on Top) - Aapka Original Logic
            missing_rows, found_rows = [], []
            id_idx = self.col_index("ID")
            grp_idx = self.col_index("Group")
            path_idx = self.col_index("Image_Path")

            for r in data:
                is_missing = False
                grp = str(r[grp_idx]).lower().strip() if r[grp_idx] else ""
                path = str(r[path_idx]) if r[path_idx] else ""
                if grp != "price list" and (not path or not os.path.exists(path)):
                    is_missing = True
                
                (missing_rows if is_missing else found_rows).append(r)

            missing_rows.sort(key=lambda x: str(x[id_idx]))
            found_rows.sort(key=lambda x: str(x[id_idx]))
            
            final_display_data = missing_rows + found_rows
            #self.table.blockSignals(True)
            
            # Columns to right align
            right_align_cols = ["Unit", "MOQ", "M_Packing", "MRP", "Stock", "MG_SN", "SG_SN"]
            right_align_indices = [self.col_index(c) for c in right_align_cols if c in self.headers]

            for r_idx, r_val in enumerate(final_display_data):
                self.table.insertRow(r_idx)
                
                # Image missing color logic
                is_row_missing = False
                grp_name = str(r_val[grp_idx]).lower().strip()
                path_val = str(r_val[path_idx]) if r_val[path_idx] else ""
                if grp_name != "price list" and (not path_val or not os.path.exists(path_val)):
                    is_row_missing = True
                    
                for c_idx, val in enumerate(r_val):
                    clean_val = str(val if val is not None else "")
                    
                    # Numeric sorting logic (MRP aur Stock ke liye)
                    if c_idx in [11, 12]:
                        item = NumericTableWidgetItem(clean_val)
                    else:
                        item = QTableWidgetItem(clean_val)
                    
                    # --- SMART LOGIC: Purani value ko UserRole mein save karna ---
                    # Yeh line save_cell_to_db ko comparison karne mein madad karegi
                    item.setData(Qt.ItemDataRole.UserRole, clean_val)
                    
                    # --- EDITABLE FLAGS ---
                    editable_indices = [19, 21] # Lenth aur True/False column
                    if c_idx in editable_indices:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    
                    # Image Status Display (Column 18)
                    if c_idx == path_idx:
                        item.setData(Qt.ItemDataRole.UserRole, path_val)
                        if grp_name == "price list":
                            item.setText("NO NEED"); item.setForeground(QColor("green"))
                        elif is_row_missing:
                            item.setText("❌ NOT FOUND"); item.setForeground(QColor("red"))
                        else:
                            item.setText("✅ FOUND"); item.setForeground(QColor("green"))

                    if is_row_missing:
                        item.setBackground(QColor(255, 0, 0))
                        item.setForeground(QColor(255, 255, 255))
                    
                    if c_idx in right_align_indices:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    
                    self.table.setItem(r_idx, c_idx, item)
            
            self.table.blockSignals(False)
            self.table.resizeColumnsToContents()
            
            # Update summary statistics
            self.update_summary_stats()
        except Exception as e: 
            print(f"Refresh Error: {e}")

    def update_summary_stats(self):
        """Calculate and update the summary statistics in the side panel.
        
        Statistics:
        - Catalog Total: Items with True/False = '1' (items that will appear in catalog)
        - Out of Stock: Items with Stock <= 0, BUT excluding items marked as 'false'
        - False Items: Items with True/False = 'false'
        - Final Data Total: Total rows in the database
        - Item Mismatch: Difference between Final Data Total and Catalog Total
        """
        try:
            if not self.db_path or not os.path.exists(self.db_path):
                return
            
            with sqlite3.connect(self.db_path) as conn:
                # Final Data Total (all rows in catalog table)
                final_data_total = conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] or 0
                
                # Catalog Total (True/False column = "1" - items that appear in catalog)
                catalog_total = conn.execute("""
                    SELECT COUNT(*) FROM catalog 
                    WHERE [True/False] IN ('1', 'true', 'True', 'TRUE')
                """).fetchone()[0] or 0
                
                # Out of Stock (Stock <= 0 or empty, BUT not counting items marked as false)
                # This counts items that are in catalog (True/False=1) but have no stock
                out_of_stock = conn.execute("""
                    SELECT COUNT(*) FROM catalog 
                    WHERE (Stock IS NULL OR Stock = '' OR CAST(Stock AS REAL) <= 0)
                    AND [True/False] NOT IN ('false', 'False', 'FALSE', 'f', '0')
                """).fetchone()[0] or 0
                
                # False Items (True/False = false)
                false_items = conn.execute("""
                    SELECT COUNT(*) FROM catalog 
                    WHERE [True/False] IN ('false', 'False', 'FALSE', 'f', '0')
                """).fetchone()[0] or 0
                
                # Item Mismatch (Final Data Total - Catalog Total)
                item_mismatch = final_data_total - catalog_total
            
            # Update labels with new field names
            self.lbl_catalog_total_val.setText(str(catalog_total))
            self.lbl_out_stock_val.setText(str(out_of_stock))
            self.lbl_false_val.setText(str(false_items))
            self.lbl_final_total_val.setText(str(final_data_total))
            self.lbl_mismatch_val.setText(str(item_mismatch))
            
        except Exception as e:
            print(f"Summary Stats Error: {e}")

    # Aapke baaki functions (get_image_mapping, show_preview, show_path_popup, filter_table) 
    # backup code ke jaise hi kaam karenge...
    def get_image_mapping(self):
        image_map = {}
        if not self.image_folder or not os.path.exists(self.image_folder): return image_map
        for root, _, files in os.walk(self.image_folder):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    image_map[os.path.splitext(file)[0].lower().strip()] = os.path.join(root, file)
        return image_map

    def filter_table(self):
        txt = self.search_input.text().lower()
        
        # Charo columns ke sahi index nikaalein
        idx_alias = self.col_index("Alias")
        idx_cat = self.col_index("Category")
        idx_group = self.col_index("Group")
        idx_subgroup = self.col_index("Sub_Group")

        for i in range(self.table.rowCount()):
            it_alias = self.table.item(i, idx_alias)
            it_cat = self.table.item(i, idx_cat)
            it_group = self.table.item(i, idx_group)
            it_subgroup = self.table.item(i, idx_subgroup)
            
            # Text values (None check ke saath)
            val_alias = it_alias.text().lower() if it_alias else ""
            val_cat = it_cat.text().lower() if it_cat else ""
            val_group = it_group.text().lower() if it_group else ""
            val_subgroup = it_subgroup.text().lower() if it_subgroup else ""
            
            # Logic: Agar kisi bhi ek column mein search text mil jaye
            match = (txt in val_alias) or \
                    (txt in val_cat) or \
                    (txt in val_group) or \
                    (txt in val_subgroup)
            
            # Agar match hai toh row dikhayein (setRowHidden = False)
            self.table.setRowHidden(i, not match)
            
    def show_preview(self, row, col):
        it = self.table.item(row, self.col_index("Image_Path"))
        if it:
            p = it.data(Qt.ItemDataRole.UserRole)
            if p and os.path.exists(p):
                pix = QPixmap(p)
                # Scale to fit within the image preview container (max 350x350)
                preview_size = self.img_preview.size()
                max_w = min(preview_size.width() - 10, 350)
                max_h = min(preview_size.height() - 10, 350)
                scaled = pix.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.img_preview.setPixmap(scaled)
                return
        self.img_preview.setText("NO IMAGE")
        self.img_preview.setPixmap(QPixmap())

    def show_path_popup(self, row, col):
        if col == self.col_index("Image_Path"):
            it = self.table.item(row, col)
            path = it.data(Qt.ItemDataRole.UserRole) if it else None
            
            if path and os.path.exists(path):
                # Open with system default viewer
                try:
                    os.startfile(path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not open image: {e}")
            else:
                 QMessageBox.information(self, "Info", f"No valid image path found.")