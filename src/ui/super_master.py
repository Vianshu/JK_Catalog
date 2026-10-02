import os
import json
import pyodbc
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QHeaderView, QMessageBox, QLabel, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt, QEvent
from src.logic.db_manager import get_db_manager, DB_SUPER, build_shared_db_name
from src.utils.app_logger import get_logger
from src.ui.table_nav_mixin import ExcelTableMixin

logger = get_logger(__name__)

class SuperMasterUI(ExcelTableMixin, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperMasterMain") # QSS: #SuperMasterMain
        self.db = get_db_manager()
        self.data_path = ""  # Set when company is loaded
        self.company_path = ""
        self._super_db = ""  # Set by setup_db() with path-aware name
        self.init_ui()

    def setup_db(self):
        """Create super_master table in SQL Server."""
        self._super_db = build_shared_db_name(DB_SUPER, self.data_path) if self.data_path else DB_SUPER
        self.db.ensure_database_exists(self._super_db, self.data_path)
        self.db.ensure_table(self._super_db, "super_master", """
            CREATE TABLE super_master (
                id NVARCHAR(50),
                MG_SN NVARCHAR(50),
                Group_Name NVARCHAR(255),
                SG_SN NVARCHAR(50),
                Sub_Group NVARCHAR(255) PRIMARY KEY
            )
        """)

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
        self.table.verticalHeader().setDefaultSectionSize(28)
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
            search_box.setPlaceholderText("Filter...")
            search_box.setFixedWidth(widths[i])
            search_box.setFixedHeight(35)
            search_box.textChanged.connect(self.apply_filters)
            self.filter_layout.addWidget(search_box)
            self.filters.append(search_box)
            self.table.setColumnWidth(i, widths[i])

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.itemChanged.connect(self.on_item_changed)

        # Excel-like navigation (Mode 1 / Mode 2) — replaces old manual F2 handler
        self._init_excel_table(self.table)

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
        
        self.summary_table.setColumnWidth(0, 45)
        self.summary_table.setColumnWidth(1, 160)
        self.summary_table.setColumnWidth(2, 55)

        right_side.addWidget(QLabel("<b>Summary</b>"))
        right_side.addWidget(self.summary_table, 1)  # stretch=1 fills vertical space
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


    def hideEvent(self, event):
        self.sync_all_to_db()
        super().hideEvent(event)

    def sync_all_to_db(self):
        """Sync all table rows to SQL Server using MERGE (upsert)."""
        if not self._super_db:
            return  # setup_db hasn't run yet
        try:
            conn = self.db.get_connection(self._super_db)
            if not conn:
                return
            cursor = conn.cursor()
            for r in range(self.table.rowCount()):
                row_data = [self.table.item(r, i).text().strip() if self.table.item(r, i) else "" for i in range(5)]
                new_id = row_data[1] + row_data[3]
                sub_group = row_data[4]
                if not sub_group:
                    continue
                # MERGE = SQL Server's upsert (replaces INSERT OR REPLACE)
                cursor.setinputsizes([(pyodbc.SQL_WVARCHAR, 255)] * 10)
                cursor.execute("""
                    MERGE super_master AS target
                    USING (SELECT ? AS Sub_Group) AS source
                    ON target.Sub_Group = source.Sub_Group
                    WHEN MATCHED THEN
                        UPDATE SET id = ?, MG_SN = ?, Group_Name = ?, SG_SN = ?
                    WHEN NOT MATCHED THEN
                        INSERT (id, MG_SN, Group_Name, SG_SN, Sub_Group)
                        VALUES (?, ?, ?, ?, ?);
                """, (sub_group,
                      new_id if new_id else None, row_data[1], row_data[2], row_data[3],
                      new_id if new_id else None, row_data[1], row_data[2], row_data[3], sub_group))
            conn.commit()
        except Exception as e:
            logger.error(f"SuperMaster sync_all_to_db error: {e}")

    def save_single_row_to_db(self, row):
        """Save a single row to SQL Server using MERGE (upsert)."""
        try:
            conn = self.db.get_connection(self._super_db)
            if not conn:
                return
            cursor = conn.cursor()
            data = [self.table.item(row, i).text().strip() if self.table.item(row, i) else "" for i in range(5)]
            sub_group = data[4]
            if not sub_group:
                return
            cursor.setinputsizes([(pyodbc.SQL_WVARCHAR, 255)] * 10)
            cursor.execute("""
                MERGE super_master AS target
                USING (SELECT ? AS Sub_Group) AS source
                ON target.Sub_Group = source.Sub_Group
                WHEN MATCHED THEN
                    UPDATE SET id = ?, MG_SN = ?, Group_Name = ?, SG_SN = ?
                WHEN NOT MATCHED THEN
                    INSERT (id, MG_SN, Group_Name, SG_SN, Sub_Group)
                    VALUES (?, ?, ?, ?, ?);
            """, (sub_group,
                  data[0] if data[0] else None, data[1], data[2], data[3],
                  data[0] if data[0] else None, data[1], data[2], data[3], sub_group))
            conn.commit()
        except Exception as e:
            logger.error(f"SuperMaster save_single_row error: {e}")

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
            # Resolve data_path (parent of company folder — shared across companies)
            self.data_path = os.path.dirname(company_path)
            self.company_path = company_path
            self.setup_db()  # Ensure DB and table exist on SQL Server
            logger.info(f"[SuperMaster] Using SQL Server DB: {self._super_db}")

            # Show the full shared super_master table — all subgroups across all companies
            saved_rows = self.db.execute_query(self._super_db, "SELECT id, MG_SN, Group_Name, SG_SN, Sub_Group FROM super_master")

            self.table.blockSignals(True)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            for r in (saved_rows or []):
                sub = r[4]
                if not sub:
                    continue
                row = self.table.rowCount()
                self.table.insertRow(row)
                mg_sn  = str(r[1]) if r[1] else ""
                grp    = str(r[2]) if r[2] else ""
                sg_sn  = str(r[3]) if r[3] else ""
                cur_id = str(r[0]) if r[0] else (mg_sn + sg_sn)
                display = [cur_id, mg_sn, grp, sg_sn, sub]
                for c in range(5):
                    it = QTableWidgetItem(display[c])
                    if c in [0, 4]:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        it.setBackground(Qt.GlobalColor.lightGray)
                    self.table.setItem(row, c, it)
            self.table.setSortingEnabled(True)
            self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
            self.table.blockSignals(False)
            self.update_summary()
        except Exception as e:
            logger.error(f"SuperMaster load error: {e}")

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