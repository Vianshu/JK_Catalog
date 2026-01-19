import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, 
    QPushButton, QLineEdit, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from catalog_logic import CatalogLogic

class FullCatalogUI(QWidget):
    def __init__(self):
        super().__init__()
        db_path = os.path.join("data", "super_master.db")
        print(db_path)
        self.logic = CatalogLogic(db_path)
        
        self.expanded_groups = {}
        self.current_page_index = 0
        #self.all_pages_data = []
        
        self.setup_ui()
        self.load_index_data()
        self.refresh_catalog_data()
        
        # Connections
        self.index_table.itemClicked.connect(self.handle_item_click)
        self.btn_next.clicked.connect(self.next_page)
        self.btn_prev.clicked.connect(self.prev_page)
        
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
    
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

        # --- 2. CENTER: Catalog Page (A4) ---
        page_v_center_layout = QVBoxLayout()
        self.catalog_page = QFrame()
        self.catalog_page.setFixedSize(595, 842)
        self.catalog_page.setStyleSheet("background-color: white; border: 2px solid #3498db;")
        
        self.page_main_layout = QVBoxLayout(self.catalog_page)
        self.page_main_layout.setContentsMargins(0, 0, 0, 0)
        self.page_main_layout.setSpacing(0)

        # HEADER (Touch Top, 3 Parts)
        self.header_frame = QFrame()
        self.header_frame.setFixedHeight(28)
        self.header_frame.setStyleSheet("border-bottom: 1px solid black;")
        header_h_layout = QHBoxLayout(self.header_frame)
        header_h_layout.setContentsMargins(15, 2, 15, 2)

        self.lbl_comp_code = QLabel("NGT")
        self.lbl_header_mid = QLabel("GROUP NAME")
        self.lbl_page_no = QLabel("Page: 1")
        
        for lbl in [self.lbl_comp_code, self.lbl_header_mid, self.lbl_page_no]:
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet("border: none;")
            
        self.lbl_header_mid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_no.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_h_layout.addWidget(self.lbl_comp_code)
        header_h_layout.addWidget(self.lbl_header_mid, stretch=1)
        header_h_layout.addWidget(self.lbl_page_no)
        self.page_main_layout.addWidget(self.header_frame)

        # CONTENT AREA (4x5 Grid)
        self.content_area = QFrame()
        self.content_area.setStyleSheet("background-color: white;")
        
        # Grid layout mein spacing 0 karni hogi taaki lines jud jayein
        self.grid_layout = QGridLayout(self.content_area)
        self.grid_layout.setContentsMargins(15, 15, 15, 15)
        self.grid_layout.setSpacing(0) # Taaki boxes ke beech gap na rahe

        # 4x5 Grid (Total 20 Cells)
        for r in range(5):
            for c in range(4):
                cell = QFrame()
                style = "border-bottom: 1px solid black; border-right: 1px solid black;"
                if r == 0: style += "border-top: 1px solid black;"
                if c == 0: style += "border-left: 1px solid black;"
                
                cell.setStyleSheet(f"QFrame {{ {style} background-color: white; }}")
                # Yeh line cells ko barabar failne mein madad karegi
                self.grid_layout.addWidget(cell, r, c)
                self.grid_layout.setRowStretch(r, 1)
                self.grid_layout.setColumnStretch(c, 1)
        self.page_main_layout.addWidget(self.content_area, stretch=1)

        # FOOTER (Touch Bottom, 2 Parts)
        self.footer_frame = QFrame()
        self.footer_frame.setFixedHeight(28)
        self.footer_frame.setStyleSheet("border-top: 1px solid black;")
        footer_h_layout = QHBoxLayout(self.footer_frame)
        footer_h_layout.setContentsMargins(15, 2, 15, 2)

        self.lbl_crm_name = QLabel("CRM:Name")
        self.lbl_update_date = QLabel("03/01/26")
        for lbl in [self.lbl_crm_name, self.lbl_update_date]:
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet("border: none;")
        self.lbl_update_date.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        footer_h_layout.addWidget(self.lbl_crm_name)
        footer_h_layout.addStretch()
        footer_h_layout.addWidget(self.lbl_update_date)
        self.page_main_layout.addWidget(self.footer_frame)

        page_v_center_layout.addWidget(self.catalog_page, alignment=Qt.AlignmentFlag.AlignCenter)
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

        right_vbox.addWidget(self.btn_add_page)
        right_vbox.addWidget(self.btn_remove_page)
        
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
        """लॉजिक फाइल से डेटा मंगाना"""
        self.all_pages_data = self.logic.get_page_data_list()
        if self.all_pages_data:
            self.total_lbl.setText(f"/{len(self.all_pages_data)}")
            self.update_catalog_page()
    
    def update_catalog_page(self):
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
            
        # Current page ka data (Group Name aur uska SG_SN)
        group_name, sg_sn = self.all_pages_data[self.current_page_index]
        
        # --- HEADER (Sirf Group Name) ---
        self.lbl_header_mid.setText(group_name.upper())
        
        # --- PAGE INFO ---
        self.page_input.setText(str(self.current_page_index + 1))
        self.lbl_page_no.setText(f" {self.current_page_index + 1}")

        # Ab yahan hum Grid bharne ka logic trigger karenge
        self.load_products_to_grid(group_name, sg_sn)
   
    def load_products_to_grid(self, group_name, sg_sn):
        # ग्रिड साफ करना
        for i in reversed(range(self.grid_layout.count())): 
            if self.grid_layout.itemAt(i).widget():
                self.grid_layout.itemAt(i).widget().setParent(None)

        # लॉजिक फाइल से प्रोडक्ट्स मंगाना
        products = self.logic.get_products_for_page(group_name, sg_sn)

        # 4x5 ग्रिड भरना
        for i in range(20):
            row, col = i // 4, i % 4
            cell = QFrame()
            style = "border-bottom: 1px solid black; border-right: 1px solid black;"
            if row == 0: style += "border-top: 1px solid black;"
            if col == 0: style += "border-left: 1px solid black;"
            cell.setStyleSheet(f"QFrame {{ {style} background-color: white; }}")
            
            # अगर प्रोडक्ट है, तो यहाँ उसका नाम/फोटो दिखा सकते हैं
            if i < len(products):
                name_label = QLabel(products[i][0], cell) # उदाहरण के लिए नाम
                name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            self.grid_layout.addWidget(cell, row, col)
            self.grid_layout.setRowStretch(row, 1)
            self.grid_layout.setColumnStretch(col, 1)
            
    def handle_item_click(self, item):
        row = item.row()
        sn_item = self.index_table.item(row, 0)
        name_item = self.index_table.item(row, 1)

        if not sn_item or not name_item:
            return

        sn_text = sn_item.text()
        group_text = name_item.text().strip()

        # 🔹 CASE 1: Sub Group click (↳)
        if "↳" in sn_text:
            main_group = ""
            for r in range(row - 1, -1, -1):
                if "↳" not in self.index_table.item(r, 0).text():
                    main_group = self.index_table.item(r, 1).text().strip()
                    break

            target_idx = self.logic.find_page_index_by_subgroup(
                main_group, sn_text
            )

            if target_idx != -1:
                self.current_page_index = target_idx
                self.update_catalog_page()
            return   # 🔴 VERY IMPORTANT

        # 🔹 CASE 2: Main Group click → ONLY expand/collapse
        if group_text in self.expanded_groups:
            self.collapse_group(group_text)
        else:
            self.expand_group(row, group_text)

    def add_page(self):
        # Temporary empty page
        self.all_pages_data.append(("NEW PAGE", None))
        self.current_page_index = len(self.all_pages_data) - 1

        self.total_lbl.setText(f"/{len(self.all_pages_data)}")
        self.update_catalog_page()

    def remove_page(self):
        if not self.all_pages_data:
            return

        # Last page remove करने से बचाव
        if len(self.all_pages_data) == 1:
            return

        self.all_pages_data.pop(self.current_page_index)

        if self.current_page_index >= len(self.all_pages_data):
            self.current_page_index = len(self.all_pages_data) - 1

        self.total_lbl.setText(f"/{len(self.all_pages_data)}")
        self.update_catalog_page()

    def expand_group(self, row, group_name):
        try:
            sub_data = self.logic.get_subgroups(group_name)
            if not sub_data:
                return

            self.index_table.blockSignals(True)
            
            # डेटा को टेबल में डालना (नीचे से ऊपर की तरफ)
            for sg_sn, sg_name in reversed(sub_data):
                next_row = row + 1
                self.index_table.insertRow(next_row)
                
                # SN को लुक दें ↳ 01
                sn_str = f"      ↳ {str(sg_sn).zfill(2)}"
                item_sn = QTableWidgetItem(sn_str)
                item_name = QTableWidgetItem(str(sg_name).upper())
                
                # 🔹 VERY IMPORTANT: group tag
                item_sn.setData(Qt.ItemDataRole.UserRole, group_name)
                item_name.setData(Qt.ItemDataRole.UserRole, group_name)
                
                # स्टाइलिंग
                sub_font = QFont("Arial", 9)
                item_sn.setFont(sub_font)
                item_name.setFont(sub_font)
                item_sn.setForeground(QColor("#666666"))
                item_name.setForeground(QColor("#666666"))
                
                self.index_table.setItem(next_row, 0, item_sn)
                self.index_table.setItem(next_row, 1, item_name)
            
            self.expanded_groups[group_name] = True
            
            self.index_table.blockSignals(False)
            self.index_table.resizeColumnToContents(0)
        
        except Exception as e:
            print(f"❌ UI Expand Error: {e}")
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
        # Debugging ke liye print lagaya hai taaki pata chale click kaam kar raha hai
        print(f"DEBUG: Next Clicked. Current Index: {self.current_page_index}")
        if hasattr(self, 'all_pages_data') and self.current_page_index < len(self.all_pages_data) - 1:
            self.current_page_index += 1
            self.update_catalog_page()

    def prev_page(self):
        if hasattr(self, 'all_pages_data') and self.current_page_index > 0:
            self.current_page_index -= 1
            self.update_catalog_page()
    