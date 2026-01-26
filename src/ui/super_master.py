import os
import sqlite3
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QHeaderView, QMessageBox, QLabel, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt, QEvent

class SuperMasterUI(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperMasterMain") # QSS: #SuperMasterMain
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.project_root = self.base_dir 
        self.db_path = self.get_data_folder_db_path()
        self.setup_db()
        self.init_ui()

    def get_data_folder_db_path(self):
        try:
            vault_path = os.path.join(self.base_dir, "company_vault.json")
            print(vault_path)
            if os.path.exists(vault_path):
                with open(vault_path, 'r', encoding='utf-8') as f:
                    vault = json.load(f)
            if vault:
                    # Attempt to use the first company's data path
                    first_comp_path = list(vault.values())[0]['path']
                    # Assuming sibling to company folder? or just "Data" folder usage
                    # Better default: Just use the local Data folder in the project
                    pass
            
            # Default to local Data folder if vault logic is complex/unreliable for Master DB
            return os.path.join(self.base_dir, "Data", "super_master.db")
        except:
            return os.path.join(self.base_dir, "Data", "super_master.db")

    def setup_db(self):
        # Ensure Data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        print(f"Super Master DB Path: {self.db_path}")
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS super_master 
                      (id TEXT, MG_SN TEXT, Group_Name TEXT, SG_SN TEXT, Sub_Group TEXT PRIMARY KEY)""")
        conn.close()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)
        
        # --- LEFT SIDE ---
        left_side = QVBoxLayout()
        left_side.setSpacing(2)

        self.headers = ["ID", "MG_SN", "Group", "SG_SN", "Sub_Group"]
        self.table = QTableWidget(0, len(self.headers))
        self.table.setObjectName("DetailedMappingTable") # QSS: #DetailedMappingTable
        self.table.setHorizontalHeaderLabels(self.headers)
        
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.verticalHeader().setVisible(False)

        # Filter Container
        self.filter_container = QFrame()
        self.filter_container.setObjectName("FilterBar") # QSS: #FilterBar
        self.filter_layout = QHBoxLayout(self.filter_container)
        self.filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_layout.setSpacing(2)
        
        self.filters = []
        widths = [60, 90, 150, 90, 300] 
        
        for i in range(len(self.headers)):
            search_box = QLineEdit()
            search_box.setObjectName(f"FilterInput_{i}")
            search_box.setPlaceholderText("🔍")
            search_box.setFixedWidth(widths[i])
            search_box.setFixedHeight(35)
            search_box.textChanged.connect(self.apply_filters)
            self.filter_layout.addWidget(search_box)
            self.filters.append(search_box)
            self.table.setColumnWidth(i, widths[i])

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.viewport().installEventFilter(self)

        left_side.addWidget(QLabel("<b>Detailed Mapping</b>"))
        left_side.addWidget(self.filter_container, alignment=Qt.AlignmentFlag.AlignLeft)
        left_side.addWidget(self.table)
        main_layout.addLayout(left_side, 3)

        # --- RIGHT SIDE: SUMMARY ---
        right_side = QVBoxLayout()
        right_side.setContentsMargins(0, 0, 0, 0)
        
        self.summary_table = QTableWidget(0, 3)
        self.summary_table.setObjectName("SummaryTable") # QSS: #SummaryTable
        self.summary_table.setHorizontalHeaderLabels(["SN", "Group", "Count"])
        
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setFixedWidth(280)
        self.summary_table.setMinimumHeight(600)
        
        self.summary_table.setColumnWidth(0, 45)
        self.summary_table.setColumnWidth(1, 160)
        self.summary_table.setColumnWidth(2, 55)

        right_side.addWidget(QLabel("<b>Summary</b>"))
        right_side.addWidget(self.summary_table)
        right_side.addStretch()
        main_layout.addLayout(right_side, 1)

    # --- बाकी फंक्शन जो आपने दिए थे (अपरिवर्तित) ---

    def apply_filters(self):
        for i in range(self.table.rowCount()):
            show_row = True
            for j in range(len(self.filters)):
                txt = self.filters[j].text().lower()
                item = self.table.item(i, j)
                if item and txt not in item.text().lower():
                    show_row = False
                    break
            self.table.setRowHidden(i, not show_row)

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F2:
            item = self.table.currentItem()
            if item and item.column() in [1, 2, 3]: 
                self.table.editItem(item)
                return True
        return super().eventFilter(source, event)

    def hideEvent(self, event):
        self.sync_all_to_db()
        super().hideEvent(event)

    def sync_all_to_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            for r in range(self.table.rowCount()):
                row_data = [self.table.item(r, i).text().strip() if self.table.item(r, i) else "" for i in range(5)]
                new_id = row_data[1] + row_data[3]
                conn.execute("""INSERT OR REPLACE INTO super_master VALUES (?, ?, ?, ?, ?)""",
                             (new_id if new_id else None, row_data[1], row_data[2], row_data[3], row_data[4]))
            conn.commit()
            conn.close()
        except Exception as e: print(f"Sync Error: {e}")

    def save_single_row_to_db(self, row):
        try:
            conn = sqlite3.connect(self.db_path)
            data = [self.table.item(row, i).text().strip() if self.table.item(row, i) else "" for i in range(5)]
            conn.execute("""INSERT OR REPLACE INTO super_master VALUES (?, ?, ?, ?, ?)""",
                         (data[0] if data[0] else None, data[1], data[2], data[3], data[4]))
            conn.commit()
            conn.close()
        except Exception as e: print(f"DB Save Error: {e}")

    def on_item_changed(self, item):
        if item.column() == 0: return
        row = item.row()
        col = item.column()
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False) 
        try:
            val = item.text().strip()
            if col in [1, 3] and len(val) == 1 and val.isdigit():
                item.setText(val.zfill(2))
            mg = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else ""
            sg = self.table.item(row, 3).text().strip() if self.table.item(row, 3) else ""
            new_id = mg + sg
            id_item = self.table.item(row, 0)
            if not id_item:
                id_item = QTableWidgetItem()
                self.table.setItem(row, 0, id_item)
            id_item.setText(new_id)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable) 
            id_item.setBackground(Qt.GlobalColor.lightGray)
            self.save_single_row_to_db(row)
            self.update_summary()
        except Exception as e: print(f"Change Error: {e}")
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)

    def load_super_master_data(self, company_path):
        if not company_path or not os.path.exists(company_path): return
        try:
            # Removed redundant vault lookup; use passed path directly
            row_db = os.path.join(company_path, "row_data.db")
            unique_subs = []
            if os.path.exists(row_db):
                conn = sqlite3.connect(row_db)
                unique_subs = [r[0] for r in conn.execute("SELECT DISTINCT SubGroup FROM stock_items WHERE SubGroup != ''").fetchall()]
                conn.close()
            conn_s = sqlite3.connect(self.db_path)
            saved = {r[4]: r for r in conn_s.execute("SELECT * FROM super_master").fetchall()}
            self.table.blockSignals(True)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            for sub in unique_subs:
                row = self.table.rowCount()
                self.table.insertRow(row)
                data = saved.get(sub) or (None, "", "", "", sub)
                mg_sn = str(data[1]) if data[1] else ""
                sg_sn = str(data[3]) if data[3] else ""
                cur_id = str(data[0]) if data[0] else (mg_sn + sg_sn)
                display = [cur_id, mg_sn, str(data[2]) if data[2] else "", sg_sn, sub]
                for c in range(5):
                    it = QTableWidgetItem(display[c])
                    if c in [0, 4]: 
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        it.setBackground(Qt.GlobalColor.lightGray)
                    self.table.setItem(row, c, it)
            conn_s.close()
            self.table.setSortingEnabled(True)
            self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
            self.table.blockSignals(False)
            self.update_summary()
        except Exception as e: print(f"Load Error: {e}")

    def update_summary(self):
        stats = {}
        total_count = 0
        for r in range(self.table.rowCount()):
            mg_sn = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            gp = self.table.item(r, 2).text().strip() if self.table.item(r, 2) else ""
            sub_g = self.table.item(r, 4).text().strip() if self.table.item(r, 4) else ""
            if gp:
                if gp not in stats: stats[gp] = {"sn": mg_sn, "subs": set()}
                stats[gp]["subs"].add(sub_g)
        self.summary_table.setRowCount(0)
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]["sn"])
        for gp, data in sorted_stats:
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
            count_val = len(data["subs"])
            total_count += count_val
            sn_it = QTableWidgetItem(data["sn"])
            sn_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.summary_table.setItem(row, 0, sn_it)
            self.summary_table.setItem(row, 1, QTableWidgetItem(gp))
            c_it = QTableWidgetItem(str(count_val))
            c_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.summary_table.setItem(row, 2, c_it)
        total_row = self.summary_table.rowCount()
        self.summary_table.insertRow(total_row)
        t_label = QTableWidgetItem("TOTAL")
        t_label.setBackground(Qt.GlobalColor.yellow)
        t_label.setFont(self.get_bold_font())
        self.summary_table.setItem(total_row, 1, t_label)
        t_count = QTableWidgetItem(str(total_count))
        t_count.setBackground(Qt.GlobalColor.yellow)
        t_count.setFont(self.get_bold_font())
        t_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_table.setItem(total_row, 2, t_count)

    def get_bold_font(self):
        font = self.summary_table.font()
        font.setBold(True)
        return font