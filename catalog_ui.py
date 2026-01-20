import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, 
    QPushButton, QLineEdit, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QPixmap
import sqlite3
from PyQt6.QtWidgets import QMessageBox

class FullCatalogUI(QWidget):
    def __init__(self):
        super().__init__()
        self.db_path = os.path.join("data", "super_master.db")
        
        self.expanded_groups = {}
        self.current_page_index = 0
        
        self.setup_ui()
        
        # DEBUG LOG
        try:
            with open("catalog_path.log", "w") as f:
                f.write(f"DB Path: {self.db_path}\nAbs Path: {os.path.abspath(self.db_path)}\n")
        except: pass

        self.load_index_data()
        
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
        
        self.catalog_page.setObjectName("CatalogPage")
        # self.catalog_page.setStyleSheet("background-color: white; border: none;")
        
        self.page_main_layout = QVBoxLayout(self.catalog_page)
        self.page_main_layout.setContentsMargins(0, 0, 0, 0)
        self.page_main_layout.setSpacing(0)

        # HEADER (Touch Top, 3 Parts)
        self.header_frame = QFrame()
        self.header_frame.setFixedHeight(30)
        
        self.header_frame.setObjectName("CatalogHeader")
        # self.header_frame.setStyleSheet(...) # Moved to QSS
        header_h_layout = QHBoxLayout(self.header_frame)
        header_h_layout.setContentsMargins(15, 0, 15, 0)

        self.lbl_comp_code = QLabel("")
        self.lbl_header_mid = QLabel("GROUP NAME")
        self.lbl_page_no = QLabel("Page: 1")
        
        for lbl in [self.lbl_comp_code, self.lbl_header_mid, self.lbl_page_no]:
            lbl.setFont(QFont("Arial", 9))
            lbl.setProperty("cssClass", "CatalogMetaLabel")
            # lbl.setStyleSheet("border: none;")
            
        self.lbl_header_mid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_no.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_h_layout.addWidget(self.lbl_comp_code)
        header_h_layout.addWidget(self.lbl_header_mid, stretch=1)
        header_h_layout.addWidget(self.lbl_page_no)
        self.page_main_layout.addWidget(self.header_frame)

        # CONTENT AREA (4x5 Grid)
        self.content_area = QFrame()
        self.content_area.setObjectName("CatalogContentArea")
        # self.content_area.setStyleSheet("border: none; background-color: white;")
        
        # Grid layout mein spacing 0 karni hogi taaki lines jud jayein
        self.grid_layout = QGridLayout(self.content_area)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0) # Taaki boxes ke beech gap na rahe
        
        # ग्रिड को अभी खाली छोड़ें, यह load_products_to_grid से भरेगा
        self.page_main_layout.addWidget(self.content_area, stretch=1) #jitu इसको देखो 
        
        # 4x5 Grid (Total 20 Cells)
        for r in range(5):
            for c in range(4):
                cell = QFrame()
                # केवल दाईं और नीचे की लाइन (ताकि डबल लाइन न बने)
                style = "border-bottom: 1px solid black; border-right: 1px solid black;"
                # आख़िरी कॉलम का राइट बॉर्डर हटाना चाहें तो हटा सकते हैं, 
                # लेकिन यहाँ हमने सिंपल रखा है
                cell.setStyleSheet(f"border: none; {style}")
                self.grid_layout.addWidget(cell, r, c)
                self.grid_layout.setRowStretch(r, 1)
                self.grid_layout.setColumnStretch(c, 1)
                
        self.page_main_layout.addWidget(self.content_area, stretch=1)

        # FOOTER (Touch Bottom, 2 Parts)
        self.footer_frame = QFrame()
        self.footer_frame.setFixedHeight(30)
        
        self.footer_frame.setObjectName("CatalogFooter")
        # self.footer_frame.setStyleSheet(...) # Moved to QSS
        footer_h_layout = QHBoxLayout(self.footer_frame)
        footer_h_layout.setContentsMargins(15, 0, 15, 0)

        self.lbl_crm_name = QLabel("CRM:Name")
        self.lbl_update_date = QLabel("03/01/26")
        for lbl in [self.lbl_crm_name, self.lbl_update_date]:
            lbl.setFont(QFont("Arial", 9))
            lbl.setProperty("cssClass", "CatalogMetaLabel")
            # lbl.setStyleSheet("border: none;")
        self.lbl_update_date.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        footer_h_layout.addWidget(self.lbl_crm_name)
        footer_h_layout.addStretch()
        footer_h_layout.addWidget(self.lbl_update_date)
        self.page_main_layout.addWidget(self.footer_frame)

        page_v_center_layout.addWidget(self.catalog_page, alignment=Qt.AlignmentFlag.AlignCenter)
        main_h_layout.addLayout(page_v_center_layout)

        # --- 3. RIGHT PANEL (Navigation & Buttons) ---
        right_panel_widget = QWidget()
        right_panel_widget.setFixedWidth(150)
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
    
    def set_company_path(self, company_path):
        self.company_path = company_path
        
        # फोल्डर के नाम से कंपनी का नाम निकालें (जैसे 'ALFA_STEEL')
        folder_name = os.path.basename(self.company_path)
        
        # शुरू के 3 अक्षर लें (अगर नाम छोटा है तो भी यह 3 तक ही गिनेगा)
        self.company_prefix = folder_name[:3].upper()
        
        # लेबल को अपडेट करें
        if hasattr(self, 'lbl_comp_code'):
            self.lbl_comp_code.setText(self.company_prefix)
            
        self.catalog_db_path = os.path.join(self.company_path, "catalog.db")
        self.final_db_path = os.path.join(self.company_path, "final_data.db")
        self.init_catalog_db()
        self.refresh_catalog_data()
    
    def init_catalog_db(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS catalog_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mg_sn INTEGER,        -- नया कॉलम
                group_name TEXT NOT NULL,
                sg_sn INTEGER NOT NULL,
                page_no INTEGER NOT NULL,
                serial_no INTEGER
            )
        """)

        # 🔑 पुराने DB के लिए safe check
        try:
            cursor.execute("ALTER TABLE catalog_pages ADD COLUMN mg_sn INTEGER")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def load_index_data(self):
        # लॉजिक फाइल से डेटा मंगवाएं (बिना SQL के)
        data = self.get_index_data()
        
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
        # STEP 0: Init connection
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()

        # STEP 1: Check if empty
        cursor.execute("SELECT COUNT(*) FROM catalog_pages")
        count = cursor.fetchone()[0]

        if count == 0:
            # Init Pages
            base_pages = self.get_page_data_list() 
            for m_sn, g_name, s_sn in base_pages:
                cursor.execute("""
                    INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no)
                    VALUES (?, ?, ?, 1)
                """, (m_sn, g_name, s_sn))
            conn.commit()
        conn.close()

        # STEP 1.5: Sync Pages with Dynamic Content (Layout Engine)
        self.sync_pages_with_content()

        # STEP 2: Rebuild Serial Numbers
        self.rebuild_serial_numbers()

        # STEP 3: Load Data for UI
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mg_sn, group_name, sg_sn, page_no, serial_no 
            FROM catalog_pages 
            ORDER BY serial_no
        """)
        self.all_pages_data = cursor.fetchall()
        conn.close()

        # UI अपडेट करें
        self.total_lbl.setText(f"/{len(self.all_pages_data)}")
        
        if self.current_page_index >= len(self.all_pages_data):
            self.current_page_index = max(0, len(self.all_pages_data) - 1)
            
        self.update_catalog_page()

    def find_first_page_of_subgroup(self, group_name, sg_sn):
        clean = "".join(filter(str.isdigit, str(sg_sn)))

        for idx, data in enumerate(self.all_pages_data):
            # डेटा को सही से अनपैक करें (5 वैल्यू)
            m_sn, g, s, pno, _serial = data 
            
            if g.upper().strip() == group_name.upper().strip() and \
               str(s).zfill(2) == clean.zfill(2) and \
               pno == 1:
                return idx
        return -1

    def update_catalog_page(self):
        if not self.all_pages_data:
            return

        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]

        self.lbl_header_mid.setText(group_name.upper())
        self.page_input.setText(str(serial_no))
        self.lbl_page_no.setText(f"Page: {serial_no}")

        self.load_products_to_grid(group_name, sg_sn, page_no)

    
    def load_products_to_grid(self, group_name, sg_sn, page_no):
        # Clear Grid
        if self.grid_layout is not None:
            while self.grid_layout.count():
                item = self.grid_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        # Fetch Data via Dynamic Layout
        products = self.get_items_for_page_dynamic(group_name, sg_sn, page_no)

        # 4x5 Grid State
        occupied = [[False]*4 for _ in range(5)]
        
        def find_slot(h):
            for r in range(5):
                for c in range(4):
                    if not occupied[r][c]:
                        if r + h <= 5:
                            fits = True
                            for k in range(h):
                                if occupied[r+k][c]: fits = False; break
                            if fits: return r, c
            return -1, -1

        # Place Products
        for p_name, img_path, p_len in products:
            try: h = int(p_len) if str(p_len).isdigit() else 1
            except: h = 1
            
            r, c = find_slot(h)
            
            if r != -1:
                # Mark occupied
                for k in range(h):
                    occupied[r+k][c] = True
                
                # Create Card
                cell = QFrame()
                # Restore Original Border Logic: Right and Bottom on ALL cells
                style = "border-bottom: 1px solid black; border-right: 1px solid black;"
                cell.setStyleSheet(f"QFrame {{ border: none; {style} background-color: white; }}")
                
                v_layout = QVBoxLayout(cell)
                v_layout.setContentsMargins(5, 5, 5, 5) # Restore Original Margins
                
                # Image
                if img_path and os.path.exists(img_path):
                    img_lbl = QLabel()
                    img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    pix = QPixmap(img_path).scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    img_lbl.setPixmap(pix)
                    v_layout.addWidget(img_lbl, stretch=1)
                
                # Name
                name_lbl = QLabel(p_name)
                name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                name_lbl.setWordWrap(True)
                name_lbl.setStyleSheet("border: none; font-size: 8pt;")
                name_lbl.setFont(QFont("Arial", 8))
                v_layout.addWidget(name_lbl)
                
                self.grid_layout.addWidget(cell, r, c, h, 1)

        # Fill Empty Spots
        for r in range(5):
            for c in range(4):
                if not occupied[r][c]:
                    cell = QFrame()
                    # Restore Original Border Logic
                    style = "border-bottom: 1px solid black; border-right: 1px solid black;"
                    cell.setStyleSheet(f"QFrame {{ border: none; {style} background-color: white; }}")
                    self.grid_layout.addWidget(cell, r, c)
            
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

            target_idx = self.find_first_page_of_subgroup(main_group, sn_text)

            if target_idx != -1:
                self.current_page_index = target_idx
                self.update_catalog_page()
            return

        # 🔹 CASE 2: Main Group click → ONLY expand/collapse
        if group_text in self.expanded_groups:
            self.collapse_group(group_text)
        else:
            self.expand_group(row, group_text)

    def add_page(self):
        if not self.all_pages_data: return

        # अब हमारे पास mg_sn भी है (Refresh Catalog Data के बाद)
        # ध्यान दें: refresh_catalog_data में SQL SELECT में mg_sn जोड़ना होगा
        mg_sn, group_name, sg_sn, page_no, _ = self.all_pages_data[self.current_page_index]

        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()

        # Shift page_no within same subgroup
        cursor.execute("""
            UPDATE catalog_pages SET page_no = page_no + 1 
            WHERE group_name=? AND sg_sn=? AND page_no > ?
        """, (group_name, sg_sn, page_no))

        # Insert with mg_sn
        cursor.execute("""
            INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) 
            VALUES (?, ?, ?, ?)
        """, (mg_sn, group_name, sg_sn, page_no + 1))

        conn.commit()
        conn.close()

        self.refresh_catalog_data()
        self.current_page_index += 1
        self.update_catalog_page()

    def remove_page(self):
        if not self.all_pages_data or len(self.all_pages_data) == 1:
            return

        m_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]

        # Check products via Dynamic Layout (if layout puts items here, forbidden)
        products = self.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        if products:
            QMessageBox.warning(self, "Warning", "This page contains data.\nRemove is not allowed.")
            return

        reply = QMessageBox.question(self, "Confirm", "Do you want to remove this page?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    
        if reply == QMessageBox.StandardButton.Yes:
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM catalog_pages 
                WHERE group_name=? AND sg_sn=? AND page_no=?
            """, (group_name, sg_sn, page_no))

            conn.commit()
            conn.close()

            self.refresh_catalog_data()
            
            if self.current_page_index >= len(self.all_pages_data):
                self.current_page_index = max(0, len(self.all_pages_data) - 1)
            
            self.update_catalog_page()
        
    def expand_group(self, row, group_name):
        try:
            sub_data = self.get_subgroups(group_name)
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
    
    # =========================================================
    # DATA / LOGIC SECTION (TEMPORARILY INSIDE UI)
    # =========================================================

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
        if not table:
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = f"""
                SELECT DISTINCT [MG_SN], [Group_Name]
                FROM {table}
                WHERE [MG_SN] IS NOT NULL
                ORDER BY CAST([MG_SN] AS INTEGER)
            """
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        except Exception as e:
            with open("catalog_error.log", "a") as f: f.write(f"Index Data Error: {e}\n")
            return []

    def get_page_data_list(self):
        table = self.get_table_name()
        if not table: return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = f"""
                SELECT DISTINCT MG_SN, Group_Name, SG_SN
                FROM {table}
                WHERE Group_Name IS NOT NULL AND SG_SN IS NOT NULL
                ORDER BY CAST(MG_SN AS INTEGER), CAST(SG_SN AS INTEGER)
            """
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        except:
            return []

    def get_subgroups(self, group_name):
        table = self.get_table_name()
        if not table:
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = f"""
                SELECT DISTINCT SG_SN, Sub_Group
                FROM {table}
                WHERE TRIM(Group_Name)=? COLLATE NOCASE
                AND Sub_Group IS NOT NULL AND Sub_Group!=''
                ORDER BY CAST(SG_SN AS INTEGER)
            """
            cursor.execute(query, (group_name.strip(),))
            data = cursor.fetchall()
            conn.close()
            return data
        except:
            return []
    
    def rebuild_serial_numbers(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM catalog_pages
            ORDER BY 
            CAST(mg_sn AS INTEGER), 
            CAST(sg_sn AS INTEGER), 
            CAST(page_no AS INTEGER)
        """)

        rows = cursor.fetchall()
        for idx, (row_id,) in enumerate(rows, start=1):
            cursor.execute("UPDATE catalog_pages SET serial_no=? WHERE id=?", (idx, row_id))

        conn.commit()
        conn.close()
    


    # =========================================================
    # NEW DYNAMIC LAYOUT ENGINE (Auto-Page & Sorting)
    # =========================================================

    def sync_pages_with_content(self):
        """Checks all subgroups and auto-creates pages if content overflows."""
        try:
            # 1. Get all subgroups
            all_subgroups = self.get_page_data_list() # Returns (MG, Group, SG)
            
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
                        print(f"✅ Auto-Added Page {p} for {group_name} - {sg_sn}")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Sync Pages Error: {e}")

    def get_items_for_page_dynamic(self, group_name, sg_sn, page_no):
        """Returns the specific items for a page based on flow layout."""
        layout_map = self.simulate_page_layout(group_name, sg_sn)
        return layout_map.get(page_no, [])

    def simulate_page_layout(self, group_name, sg_sn):
        """
        Simulates sorting and packing to determine which item goes to which page.
        Returns: { page_no: [(ItemName, ImagePath, Length), ...] }
        """
        products = self.get_sorted_products_from_db(group_name, sg_sn)
        layout_map = {}
        current_page = 1
        
        def get_empty_grid():
            return [[False]*4 for _ in range(5)] # 5 rows, 4 cols

        grid = get_empty_grid()
        
        # Helper to find slot
        def find_slot(g_state, h):
            for r in range(5):
                for c in range(4):
                    if not g_state[r][c]:
                        # Check vertical availability
                        if r + h <= 5:
                            fits = True
                            for k in range(h):
                                if g_state[r+k][c]: fits = False
                                if not fits: break
                            if fits: return r, c
            return -1, -1

        def mark_slot(g_state, r, c, h):
            for k in range(h):
                g_state[r+k][c] = True

        if not products:
            return {}
            
        layout_map[current_page] = []
        
        for p_name, img_path, p_len in products:
            try:
                h = int(p_len) if str(p_len).isdigit() else 1
            except: h = 1
            
            # Try to fit in current page
            r, c = find_slot(grid, h)
            
            if r == -1:
                # Page Full -> New Page
                current_page += 1
                grid = get_empty_grid()
                layout_map[current_page] = []
                # Try new page
                r, c = find_slot(grid, h)
                
            if r != -1:
                mark_slot(grid, r, c, h)
                layout_map[current_page].append((p_name, img_path, h))
            else:
                layout_map[current_page].append((p_name + " (TOO BIG)", img_path, h))
                
        return layout_map

    def get_sorted_products_from_db(self, group_name, sg_sn):
        """Fetches products sorted by Price (MRP) asc."""
        try:
            conn = sqlite3.connect(self.final_db_path)
            cursor = conn.cursor()
            
            # Sort by MRP (Lowest first)
            cursor.execute("""
                SELECT [Product Name], [Item_Name], [Image_Path], [Length], [MRP]
                FROM catalog
                WHERE [Group]=? AND [SG_SN]=? AND ([True/False] IS NULL OR [True/False] != 'false')
                ORDER BY CAST(REPLACE([MRP], ',', '') AS REAL) ASC
            """, (group_name, sg_sn))
            
            rows = cursor.fetchall()
            conn.close()
            
            clean_list = []
            for r in rows:
                p_name = r[0] if r[0] and r[0].strip() else r[1]
                img = r[2]
                length = r[3]
                clean_list.append((p_name, img, length))
                
            return clean_list
        except Exception as e:
            print(f"Data Fetch Error: {e}")
            return []