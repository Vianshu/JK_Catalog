import sys
import sqlite3
import os  # Added global import
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, 
    QPushButton, QLineEdit, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QGridLayout, QMessageBox, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QPixmap
from src.logic.catalog_logic import CatalogLogic
from src.ui.a4_renderer import A4PageRenderer
from src.ui.settings import EmptyPagesDialog
import sqlite3

class FullCatalogUI(QWidget):
    def __init__(self):
        super().__init__()
        db_path = os.path.join("data", "super_master.db")
        # Ensure Logic gets correct DB path
        self.logic = CatalogLogic(db_path)
        
        self.catalog_db_path = None
        self.final_db_path = None
        
        self.expanded_groups = {}
        self.current_page_index = 0
        self.all_pages_data = []
        
        self.setup_ui()
        self.load_index_data()
        self.connect_signals()
        
        try:
            with open("ui_interaction.log", "w") as f: f.write("FullCatalog UI Init - Connections Complete\n")
        except: pass

        
    def set_company_path(self, company_path):
        self.company_path = company_path
        self.catalog_db_path = os.path.join(self.company_path, "catalog.db")
        self.final_db_path = os.path.join(self.company_path, "final_data.db")
        
        
        # Pass to Logic
        self.logic.set_paths(self.catalog_db_path, self.final_db_path)
        
        # Init DB
        self.init_catalog_db()
        self.refresh_catalog_data()
        
        folder_name = os.path.basename(self.company_path)
        prefix = folder_name[:3].upper()
        if hasattr(self, 'lbl_comp_code'): self.lbl_comp_code.setText(prefix)

    def init_catalog_db(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS catalog_pages (id INTEGER PRIMARY KEY AUTOINCREMENT, mg_sn INTEGER, group_name TEXT, sg_sn INTEGER, page_no INTEGER, serial_no INTEGER)")
        try: cursor.execute("ALTER TABLE catalog_pages ADD COLUMN mg_sn INTEGER"); 
        except: pass
        conn.commit(); conn.close()
        
    def rebuild_serial_numbers(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM catalog_pages ORDER BY CAST(mg_sn AS INTEGER), CAST(sg_sn AS INTEGER), CAST(page_no AS INTEGER)")
        rows = cursor.fetchall()
        for idx, (rid,) in enumerate(rows, 1):
            cursor.execute("UPDATE catalog_pages SET serial_no=? WHERE id=?", (idx, rid))
        conn.commit(); conn.close()
    
    def connect_signals(self):
        # Index Table - Use only cellClicked (not itemClicked to avoid double-fire)
        self.index_table.cellClicked.connect(self.handle_cell_click)
        
        # Navigation
        self.btn_next.clicked.connect(self.next_page)
        self.btn_prev.clicked.connect(self.prev_page)
        self.page_input.returnPressed.connect(self.go_to_page)
        
        # Page Management
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.btn_check_empty.clicked.connect(self.check_empty_pages)
        
        # Build & Export
        self.btn_build.clicked.connect(self.build_catalog)
        self.btn_export.clicked.connect(self.export_pdf)
        
        # Length change from right-click context menu
        self.renderer.length_changed.connect(self.handle_length_change)
    
    def handle_length_change(self, product_name, new_length):
        """Handle product size change from context menu."""
        if not self.final_db_path:
            return
        
        try:
            conn = sqlite3.connect(self.final_db_path)
            cursor = conn.cursor()
            
            # Update length in catalog table (as text to support H|V)
            cursor.execute("""
                UPDATE catalog SET [Lenth] = ? 
                WHERE [Product Name] = ? OR [Item_Name] = ?
            """, (str(new_length), product_name, product_name))
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            print(f"DEBUG: Updated {affected} rows with new size '{new_length}'")
            
            # Refresh current page to show updated layout
            self.refresh_catalog_data()
            
        except Exception as e:
            print(f"ERROR updating length: {e}")
    
    def go_to_page(self):
        """Navigate to global page number entered in the input field."""
        print(f"DEBUG go_to_page: Input='{self.page_input.text()}'")
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            print("DEBUG go_to_page: No pages data")
            return
        
        try:
            target_page = int(self.page_input.text())
        except ValueError:
            print("DEBUG go_to_page: Invalid input")
            return
        
        total_pages = len(self.all_pages_data)
        
        # Navigate to global page (1-indexed)
        if 1 <= target_page <= total_pages:
            self.current_page_index = target_page - 1
            self.update_catalog_page()
            print(f"DEBUG go_to_page: Navigated to global page {target_page}")
    
    def build_catalog(self):
        """Build/refresh the catalog."""
        self.refresh_catalog_data()
        QMessageBox.information(self, "Build Complete", "Catalog has been built successfully!")
    
    def export_pdf(self):
        """Export catalog to PDF."""
        QMessageBox.information(self, "Export", "PDF Export feature coming soon!")
    
    def setup_ui(self):
        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(10, 10, 10, 10)
        main_h_layout.setSpacing(20)

        # --- 1. LEFT SIDE: Index List ---
        index_container = QVBoxLayout()
        self.index_table = QTableWidget()
        self.index_table.setFixedWidth(320)
        self.index_table.setColumnCount(2)
        self.index_table.setHorizontalHeaderLabels(["SN", "NAME"])
        
        # >>> यह लाइन जिससे EDIT होना बंद हो जाएगा <<<
        self.index_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        header = self.index_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        self.index_table.verticalHeader().setVisible(False)
        self.index_table.setShowGrid(False)
        self.index_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        index_container.addWidget(self.index_table)
        main_h_layout.addLayout(index_container)

        # --- 2. CENTER: Catalog Page (A4 Renderer) ---
        page_v_center_layout = QVBoxLayout()
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("background-color: #e0e0e0;")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.renderer = A4PageRenderer()
        # Default DPI for Screen Preview (approx)
        self.renderer.set_target_dpi(96) 
        
        self.scroll_area.setWidget(self.renderer)
        # self.scroll_area.setWidgetResizable(True) # Fixed size widget better not resize
        
        page_v_center_layout.addWidget(self.scroll_area)
        main_h_layout.addLayout(page_v_center_layout)

        # --- 3. RIGHT PANEL (Navigation & Buttons) ---
        right_panel_widget = QWidget()
        right_panel_widget.setFixedWidth(160)
        right_vbox = QVBoxLayout(right_panel_widget)
        
        # Navigation Box
        nav_box = QFrame()
        nav_l = QHBoxLayout(nav_box)
        nav_l.setContentsMargins(0, 0, 0, 0)
        
        self.btn_prev = QPushButton("⏴")
        self.btn_next = QPushButton("⏵")
        
        self.page_input = QLineEdit("1")
        self.page_input.setFixedWidth(35)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # ERROR YAHAN THA: total_lbl ko class variable banana zaroori hai
        self.total_lbl = QLabel("/1") 
        
        nav_l.addWidget(self.btn_prev)
        nav_l.addWidget(self.page_input)
        nav_l.addWidget(self.total_lbl)
        nav_l.addWidget(self.btn_next)
        
        right_vbox.addWidget(nav_box)
        
        # Buttons
        self.btn_build = QPushButton("🔨 Build")
        self.btn_build.setFixedHeight(40)
        self.btn_export = QPushButton("📄 Export PDF")
        self.btn_export.setFixedHeight(40)
        
        right_vbox.addWidget(self.btn_build)
        right_vbox.addWidget(self.btn_export)
        right_vbox.addStretch()
        
        self.btn_add_page = QPushButton("➕ Add Page")
        self.btn_add_page.setFixedHeight(36)

        self.btn_remove_page = QPushButton("➖ Remove Page")
        self.btn_remove_page.setFixedHeight(36)
        
        self.btn_check_empty = QPushButton("🔍 Check Empty")
        self.btn_check_empty.setFixedHeight(36)

        right_vbox.addWidget(self.btn_add_page)
        right_vbox.addWidget(self.btn_remove_page)
        right_vbox.addWidget(self.btn_check_empty)
        
        main_h_layout.addWidget(right_panel_widget)
    
    def load_index_data(self):
        # लॉजिक फाइल से डेटा मंगवाएं (बिना SQL के)
        data = self.logic.get_index_data()
        
        if not data: return

        self.index_table.setRowCount(len(data))
        self.all_groups = [] # बहुत जरूरी: इसे यहाँ खाली करें

        for row_idx, (sn, group) in enumerate(data):
            g_name = str(group).upper().strip()
            self.all_groups.append(g_name) # क्लिक पहचानने के लिए लिस्ट भरें
            
            # SN को 01, 02 फॉर्मेट में बदलें
            sn_val = "".join(filter(str.isdigit, str(sn)))
            sn_str = sn_val.zfill(2) if sn_val else "00"
            
            item_sn = QTableWidgetItem(sn_str)
            item_name = QTableWidgetItem(g_name)
            
            # स्टाइलिंग (फोंट और कलर)
            font = QFont("Arial", 11)
            item_sn.setFont(font)
            item_name.setFont(font)
            
            if row_idx % 2 == 0:
                bg = QColor("#F8F9FA")
                item_sn.setBackground(bg)
                item_name.setBackground(bg)
                
            self.index_table.setItem(row_idx, 0, item_sn)
            self.index_table.setItem(row_idx, 1, item_name)
    
    def refresh_catalog_data(self):
        if not self.catalog_db_path: return
        
        # 1. Sync Pages (Auto Add)
        self.logic.sync_pages_with_content()
        
        # 2. Rebuild Serials
        self.rebuild_serial_numbers()
        
        # 3. Load Data
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT mg_sn, group_name, sg_sn, page_no, serial_no FROM catalog_pages ORDER BY serial_no")
        self.all_pages_data = cursor.fetchall()
        conn.close()
        
        if self.all_pages_data:
            self.total_lbl.setText(f"/{len(self.all_pages_data)}")
            if self.current_page_index >= len(self.all_pages_data):
                self.current_page_index = 0
        
        self.update_catalog_page()
    
    def update_catalog_page(self):
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
            
        # Current page data
        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]
        
        # Global page numbering (1-indexed)
        current_global_page = self.current_page_index + 1
        total_pages = len(self.all_pages_data)
        
        # Update navigation display with global numbers
        self.page_input.setText(str(current_global_page))
        self.total_lbl.setText(f"/{total_pages}")
        
        self.renderer.set_header_data(group_name, serial_no)

        # Grid Load
        self.load_products_to_grid(group_name, sg_sn, page_no)
   
    def load_products_to_grid(self, group_name, sg_sn, page_no):
        # 1. Fetch
        products = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        
        # 2. Render (empty list will show empty cells)
        self.renderer.fill_products(products if products else [])
        
        # 3. Footer Logic (CRM & Date)
        crm_name = "CRM_NAME" # Placeholder for now, later customizable
        
        # Calculate Max Date for this page
        max_date_str = ""
        max_dt_obj = None
        
        from datetime import datetime
        
        if products:
            for p in products:
                # p is a dict from layout_map containing "data" key which is the product dict
                p_data = p.get("data", {})
                p_date = p_data.get("max_update_date", "")
                if p_date:
                    try:
                        # Extract date part
                        date_part = p_date.split(" ")[0]
                        # Parse DD-MM-YYYY
                        dt = datetime.strptime(date_part, "%d-%m-%Y")
                        if max_dt_obj is None or dt > max_dt_obj:
                            max_dt_obj = dt
                            max_date_str = p_date # Keep original string for display/conversion
                    except:
                        # Fallback for string comparison if format fails
                        if p_date > max_date_str:
                            max_date_str = p_date
        
        # Convert to Nepali Date (DD/MM)
        footer_date = ""
        if max_date_str:
            # max_date_str is YYYY-MM-DD HH:MM:SS (from DB)
            try:
                # We need DD-MM-YYYY for our helper function logic? 
                # Helper expects "DD-MM-YYYY" or "YYYY-MM-DD"?
                # logic.get_nepali_date code: 
                # if " " in ad_date_str: ad_date_str = ad_date_str.split(" ")[0]
                # cursor.execute("SELECT bs_date FROM calendar WHERE ad_date=?", (ad_date_str,))
                # The calendar DB has "DD-MM-YYYY" (e.g. 01-07-2025).
                # But our DB Update_date is likely "YYYY-MM-DD" or "DD-MM-YYYY"?
                # Check check_date_format output: "20-01-2026 23:55:25"
                # If it's DD-MM-YYYY, then 20 is Day.
                # If it's YYYY-MM-DD, then 20 is Year? No, 2026 is Year.
                # So "20-01-2026" is likely DD-MM-YYYY? Or YYYY-MM-DD?
                # Actually standard SQLite is YYYY-MM-DD. 3rd sample was "20-01-2026". That looks like DD-MM-YYYY.
                # Wait, check_date_format output: ('20-01-2026 23:55:25',)
                # Verify if 20 is day. Yes likely.
                # The helper function handles "splitted by space".
                # It passes "20-01-2026" to Query.
                # Calendar DB uses "01-07-2025". So it matches format DD-MM-YYYY.
                # So just passing the date part is correct.
                
                footer_date = self.logic.get_nepali_date(max_date_str)
            except: pass
            
        self.renderer.set_footer_data(crm_name, footer_date)
    
    def find_page_index_by_subgroup(self, group_name, sn_text):
        """Find the first page index for a given group and subgroup."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return -1
        
        # Extract sg_sn from sn_text (format: "      -> 01")
        sg_sn = sn_text.replace("->", "").strip()
        
        # Remove leading zeros for comparison if needed
        try:
            sg_sn_int = int(sg_sn)
        except:
            sg_sn_int = sg_sn
        
        for i, page in enumerate(self.all_pages_data):
            page_group = page[1]
            page_sg = page[2]
            
            # Compare group names (case insensitive)
            if page_group.upper().strip() == group_name.upper().strip():
                # Compare sg_sn
                try:
                    page_sg_int = int(page_sg)
                    if page_sg_int == sg_sn_int:
                        return i
                except:
                    if str(page_sg).strip() == str(sg_sn).strip():
                        return i
        
        return -1
    def handle_cell_click(self, row, col):
        item = self.index_table.item(row, col)
        if item: self.handle_item_click(item)

    def handle_item_click(self, item):
        print(f"DEBUG handle_item_click: item={item.text()}")
        try:
            with open("ui_interaction.log", "a", encoding="utf-8") as f: f.write(f"Click: {item.text()}\n")
        except: pass
        row = item.row()
        sn_item = self.index_table.item(row, 0)
        name_item = self.index_table.item(row, 1)

        if not sn_item or not name_item:
            print("DEBUG: sn_item or name_item is None")
            return

        sn_text = sn_item.text()
        group_text = name_item.text().strip()
        print(f"DEBUG: sn_text='{sn_text}', group_text='{group_text}'")

        # 🔹 CASE 1: Sub Group click (->)
        if "->" in sn_text:
            print("DEBUG: Subgroup click detected")
            main_group = ""
            for r in range(row - 1, -1, -1):
                if "->" not in self.index_table.item(r, 0).text():
                    main_group = self.index_table.item(r, 1).text().strip()
                    break

            target_idx = self.find_page_index_by_subgroup(main_group, sn_text)
            print(f"DEBUG: main_group='{main_group}', target_idx={target_idx}")

            if target_idx != -1:
                self.current_page_index = target_idx
                self.update_catalog_page()
            return   # 🔴 VERY IMPORTANT

        # 🔹 CASE 2: Main Group click → ONLY expand/collapse
        print(f"DEBUG: Main Group click. expanded_groups={self.expanded_groups}")
        if group_text in self.expanded_groups:
            print(f"DEBUG: Collapsing {group_text}")
            self.collapse_group(group_text)
        else:
            print(f"DEBUG: Expanding {group_text}")
            self.expand_group(row, group_text)

    def add_page(self):
        if not self.catalog_db_path or not self.all_pages_data: return

        # Get current context
        mg_sn, group_name, sg_sn, page_no, _ = self.all_pages_data[self.current_page_index]
        
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        
        # Find next page number for this subgroup
        cursor.execute("SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?", (group_name, sg_sn))
        res = cursor.fetchone()
        next_page = (res[0] or 0) + 1
        
        # Insert new page
        cursor.execute("INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) VALUES (?, ?, ?, ?)", 
                       (mg_sn, group_name, sg_sn, next_page))
        conn.commit()
        conn.close()
        
        self.refresh_catalog_data()
        
        # Navigate to the newly created page
        for i, row in enumerate(self.all_pages_data):
            if row[1] == group_name and row[2] == sg_sn and row[3] == next_page:
                self.current_page_index = i
                break
        
        self.update_catalog_page()

    def showEvent(self, event):
        self.refresh_catalog_data()
        super().showEvent(event)

    def handle_build(self):
        if not self.catalog_db_path: return
        try:
            self.logic.sync_pages_with_content()
            self.refresh_catalog_data()
            QMessageBox.information(self, "Success", "Catalog built successfully!\nPages synced with content.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Build failed: {e}")

    def remove_page(self):
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data or len(self.all_pages_data) <= 1: return

        m_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]
        
        # Check if safe to delete
        items = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        if items:
            QMessageBox.warning(self, "Warning", "Page contains data. Cannot remove.")
            return

        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?", (group_name, sg_sn, page_no))
        conn.commit(); conn.close()
        
        self.refresh_catalog_data()
        
    def find_page_index_by_subgroup(self, group, sg_sn_text):
        clean = "".join(filter(str.isdigit, str(sg_sn_text)))
        if not hasattr(self, 'all_pages_data'): return -1
        for idx, (m, g, s, p, seq) in enumerate(self.all_pages_data):
            if g.upper().strip() == group.upper().strip() and str(s).zfill(2) == clean.zfill(2) and p == 1:
                return idx
        return -1

    def expand_group(self, row, group_name):
        try:
            print(f"DEBUG expand_group: row={row}, group_name='{group_name}'")
            try:
                with open("ui_interaction.log", "a", encoding="utf-8") as f: f.write(f"Expanding: {group_name}\n")
            except: pass
            sub_data = self.logic.get_subgroups(group_name)
            print(f"DEBUG expand_group: sub_data={sub_data}")
            try:
                with open("ui_interaction.log", "a", encoding="utf-8") as f: f.write(f"Subgroups Found: {len(sub_data) if sub_data else 0}\n")
            except: pass
            
            if not sub_data:
                print("DEBUG expand_group: No sub_data returned!")
                return

            self.index_table.blockSignals(True)
            
            # Insert subgroups below the group row (in reverse order)
            for sg_sn, sg_name in reversed(sub_data):
                next_row = row + 1
                self.index_table.insertRow(next_row)
                print(f"DEBUG expand_group: Inserted row {next_row} for sg_sn={sg_sn}, sg_name={sg_name}")
                
                # SN format: "      -> 01"
                sn_str = f"      -> {str(sg_sn).zfill(2)}"
                item_sn = QTableWidgetItem(sn_str)
                item_name = QTableWidgetItem(str(sg_name).upper())
                
                # Tag items with parent group
                item_sn.setData(Qt.ItemDataRole.UserRole, group_name)
                item_name.setData(Qt.ItemDataRole.UserRole, group_name)
                
                # Styling
                sub_font = QFont("Arial", 9)
                item_sn.setFont(sub_font)
                item_name.setFont(sub_font)
                item_sn.setForeground(QColor("#666666"))
                item_name.setForeground(QColor("#666666"))
                
                self.index_table.setItem(next_row, 0, item_sn)
                self.index_table.setItem(next_row, 1, item_name)
                self.index_table.setRowHeight(next_row, 28)  # Ensure visible height
            
            self.expanded_groups[group_name] = True
            print(f"DEBUG expand_group: expanded_groups now={self.expanded_groups}")
            
            self.index_table.blockSignals(False)
            self.index_table.resizeColumnToContents(0)
            self.index_table.viewport().update()
            self.index_table.update()
            print(f"DEBUG expand_group: Table row count now={self.index_table.rowCount()}")
        
        except Exception as e:
            print(f"❌ UI Expand Error: {e}")
            import traceback
            traceback.print_exc()
            self.index_table.blockSignals(False)
            
    def collapse_group(self, group_name):
        self.index_table.blockSignals(True)

        # Bottom से top scan (safe removal)
        for row in range(self.index_table.rowCount() - 1, -1, -1):
            item = self.index_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == group_name:
                self.index_table.removeRow(row)

        if group_name in self.expanded_groups:
            del self.expanded_groups[group_name]

        self.index_table.blockSignals(False)
    
    def next_page(self):
        """Navigate to next page globally."""
        print(f"DEBUG: Next Clicked. Current Index: {self.current_page_index}")
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
        
        if self.current_page_index < len(self.all_pages_data) - 1:
            self.current_page_index += 1
            self.update_catalog_page()

    def prev_page(self):
        """Navigate to previous page globally."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
        
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.update_catalog_page()

    def check_empty_pages(self):
        if not self.catalog_db_path: return
        
        QMessageBox.information(self, "Checking", "Scanning for empty pages... This may take a moment.")
        
        empty_list = self.logic.find_empty_pages()
        
        dlg = EmptyPagesDialog(empty_list, self)
        if dlg.exec():
            # Delete if accepted
            if empty_list:
                reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(empty_list)} pages?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    conn = sqlite3.connect(self.catalog_db_path)
                    cursor = conn.cursor()
                    for g, s, p in empty_list:
                        cursor.execute("DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?", (g, s, p))
                    conn.commit()
                    conn.close()
                    
                    self.refresh_catalog_data()
                    QMessageBox.information(self, "Success", "Empty pages deleted.")
    