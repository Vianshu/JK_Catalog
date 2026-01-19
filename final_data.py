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
from data_processor import DataProcessor

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
            "Image_Path", "Length", "Image_Date", "True/False", "Update_date"
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
        side_layout.setContentsMargins(0, 0, 0, 0)
        # side_layout.setSpacing(10)

        # 1. Sync Time (Top)
        self.sync_lbl = QLabel("Last Sync: N/A")
        self.sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_lbl.setStyleSheet("font-weight: bold; color: #555;")
        side_layout.addWidget(self.sync_lbl)

        # 2. Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Item Name...")
        self.search_input.textChanged.connect(self.filter_table)
        side_layout.addWidget(self.search_input)

        # 3. Image (Expanded)
        self.img_preview = QLabel("NO IMAGE")
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet("background-color: #f0f0f0;")
        self.img_preview.setMinimumSize(250, 250) 
        from PyQt6.QtWidgets import QSizePolicy
        self.img_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.img_preview.setScaledContents(True)
        side_layout.addWidget(self.img_preview, 1) # Takes available space

        # 4. Stats / Info
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setWordWrap(True)
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
            
            if "no_need" in str(img_path_val).lower():
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
                
            conn.commit()
            conn.close()

            item.setData(Qt.ItemDataRole.UserRole, new_val) # Update memory

            if should_update_date:
                self.table.blockSignals(True)
                self.table.setItem(row, self.col_index("Update_date"), QTableWidgetItem(now))
                self.table.blockSignals(False)
            
            self.status_lbl.setText(f"Updated: {col_name}" + (f" & Date at {now}" if should_update_date else ""))
            
            # Refresh stats if needed
            # self.calculate_stats() 

        except Exception as e:
            print(f"Update Error: {e}")

    def load_and_sync_data(self, company_name):
        try:
            # 1. Path Setup
            base_dir = os.path.dirname(os.path.abspath(__file__))
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
                    SELECT Item_Name, Alias, Part_No, Categori, Unit, 
                           MRP, Stock, MG_SN, [Group], SG_SN, Sub_Group
                    FROM catalog WHERE GUID=?
                """, (guid,))
                old_row_db = cur.fetchone()
                
                new_row = tuple("" if v is None else str(v) for v in (
                    r[1],          # Item_Name
                    r[2],          # Alias
                    r[3],          # Part_No
                    r[4],          # Categori
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
                            Item_Name=?, Alias=?, Part_No=?, Categori=?, Unit=?, 
                            MRP=?, Stock=?, MG_SN=?, [Group]=?, SG_SN=?, Sub_Group=?, 
                            Update_date=? 
                            WHERE GUID=?"""
                        cur.execute(query, (*new_row, now, guid))
                    else:
                        query = """UPDATE catalog SET 
                            Item_Name=?, Alias=?, Part_No=?, Categori=?, Unit=?, 
                            MRP=?, Stock=?, MG_SN=?, [Group]=?, SG_SN=?, Sub_Group=?
                            WHERE GUID=?"""
                        cur.execute(query, (*new_row, guid))
                else:
                    # Bilkul naya item (Insert)
                    f_row = [None] * len(self.headers)
                    f_row[self.col_index("GUID")] = guid
                    f_row[self.col_index("Item_Name")] = r[1]
                    f_row[self.col_index("Alias")] = r[2]
                    f_row[self.col_index("Part_No")] = r[3]
                    f_row[self.col_index("Categori")] = r[4]
                    f_row[self.col_index("Unit")] = r[5]
                    f_row[self.col_index("MRP")] = r[7]
                    f_row[self.col_index("Stock")] = r[8]
                    f_row[self.col_index("MG_SN")] = s_data[0]
                    f_row[self.col_index("Group")] = s_data[1]
                    f_row[self.col_index("SG_SN")] = s_data[2]
                    f_row[self.col_index("Sub_Group")] = r[6]
                    f_row[self.col_index("Update_date")] = now
                    cur.execute(f"INSERT INTO catalog VALUES ({','.join(['?']*len(self.headers))})", f_row)

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
        """Processor ke kaam ke baad image paths update karne ke liye"""
        try:
            conn = sqlite3.connect(self.db_path)
            img_map = self.get_image_mapping()
            for rid, img_name in conn.execute("SELECT rowid, Image_Name FROM catalog"):
                clean = img_name.lower().strip() if img_name else ""
                if clean in img_map:
                    path = img_map[clean]
                    date = self.get_file_modify_date(path)
                    conn.execute("UPDATE catalog SET Image_Path=?, Image_Date=? WHERE rowid=?", (path, date, rid))
                else:
                    conn.execute("UPDATE catalog SET Image_Path='', Image_Date='' WHERE rowid=?", (rid,))
            conn.commit()
            conn.close()
        except: pass

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
        except Exception as e: 
            print(f"Refresh Error: {e}")

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
                self.img_preview.setPixmap(QPixmap(p))
                return
        self.img_preview.setText("NO IMAGE"); self.img_preview.setPixmap(QPixmap())

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