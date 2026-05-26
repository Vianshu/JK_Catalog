import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel
from PyQt6.QtCore import Qt
from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

class LedgerRowDataUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("LedgerRowDataContainer") # QSS: #LedgerRowDataContainer
        self.db = get_db_manager()
        
        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(10)

        # Info label
        self.info_lbl = QLabel("Please select a company to view ledger records.")
        self.info_lbl.setObjectName("TableInfoLabel")
        self.info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.info_lbl)

        # Table setup
        self.table = QTableWidget()
        self.table.setObjectName("MainDataTable") # QSS: #MainDataTable
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        # Interactive Headers
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setVisible(False) # Hide row numbers
        
        self.main_layout.addWidget(self.table)
        self.table.hide() 

    def load_data(self, company_path):
        """MainWindow triggered data loading function (Path Based)"""
        try:
            if not company_path or not os.path.exists(company_path):
                self.show_error("Invalid Company Path.")
                return

            company_name = os.path.basename(company_path)
            db_name = build_logical_name(company_name, company_path=company_path)

            if not self.db.database_exists(db_name):
                self.show_error(f"No database found: {db_name}\nPlease Sync Ledger from Tally.")
                self.table.hide()
                return

            # SQL Server data fetching
            self.fetch_from_sql_server(db_name)

        except Exception as e:
            self.show_error(f"System Error: {str(e)}")

    def fetch_from_sql_server(self, db_name):
        conn = self.db.get_connection(db_name)
        if not conn:
            self.show_error("Could not connect to database.")
            return
        
        try:
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME = 'row_ledger_data'
            """)
            if cursor.fetchone()[0] == 0:
                self.show_error("Table 'row_ledger_data' is missing in the database.")
                return

            cursor.execute("SELECT * FROM row_ledger_data")
            db_headers = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Update UI
            self.info_lbl.hide()
            self.table.show()
            
            self.table.setColumnCount(len(db_headers))
            self.table.setHorizontalHeaderLabels([h.replace("_", " ").title() for h in db_headers])
            self.table.setRowCount(len(rows))

            for row_idx, row_data in enumerate(rows):
                for col_idx, value in enumerate(row_data):
                    item = QTableWidgetItem(str(value) if value is not None else "")
                    # If numerical, right align
                    if isinstance(value, (int, float)):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row_idx, col_idx, item)

            self.table.resizeColumnsToContents()
            
        except Exception as e:
            self.show_error(f"Database Error: {str(e)}")

    def show_error(self, message):
        self.info_lbl.setText(message)
        self.info_lbl.show()
        self.table.hide()
