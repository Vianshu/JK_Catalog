import os
import datetime
import pyodbc
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QLabel, QHeaderView, QMessageBox, QHBoxLayout)
from PyQt6.QtCore import Qt

from src.logic.db_manager import get_db_manager, DB_CALENDAR, build_shared_db_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

class CalendarMappingUI(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_db_manager()
        self.data_path = ""  # Set when company loads
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.label = QLabel("<h2>English to Nepali Calendar Mapping</h2>")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        # 5 Columns: AD, BS, Year, Month, Day
        self.columns = ["English Date (AD)", "Nepali Date (BS)", "Year", "Month", "Day"]
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_generate = QPushButton("Auto-Generate 5 Years Data")
        self.btn_save = QPushButton("Save Changes")
        
        self.btn_generate.clicked.connect(self.generate_calendar_data)
        self.btn_save.clicked.connect(self.save_manual_edits)
        
        btn_layout.addWidget(self.btn_generate)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def init_db(self):
        """Create calendar table in SQL Server."""
        self._cal_db = build_shared_db_name(DB_CALENDAR, self.data_path) if self.data_path else DB_CALENDAR
        self.db.ensure_database_exists(self._cal_db, self.data_path)
        self.db.ensure_table(self._cal_db, "calendar", """
            CREATE TABLE calendar (
                ad_date NVARCHAR(20) PRIMARY KEY,
                bs_date NVARCHAR(20),
                year NVARCHAR(10),
                month NVARCHAR(10),
                day NVARCHAR(10)
            )
        """)
        self.load_data()

    def set_company_path(self, path):
        """Update data_path when company changes and reload data"""
        self.data_path = os.path.dirname(path) if path else ""
        self.init_db()

    def generate_calendar_data(self):
        try:
            import nepali_datetime
        except ImportError:
            QMessageBox.critical(self, "Error", "nepali-datetime package is missing. Please run: pip install nepali-datetime")
            return

        conn = self.db.get_connection(self._cal_db)
        if not conn:
            QMessageBox.critical(self, "Error", "Could not connect to Calendar database.")
            return
        cursor = conn.cursor()
        
        # 1. Find the last existing date in the DB
        cursor.execute("SELECT ad_date FROM calendar")
        rows = cursor.fetchall()
        
        max_date = None
        for row in rows:
            try:
                dt = datetime.datetime.strptime(row[0], "%d-%m-%Y").date()
                if max_date is None or dt > max_date:
                    max_date = dt
            except Exception:
                pass
                
        # 2. Determine Start Date (Next day after max, or original default if empty)
        if max_date:
            curr_ad = max_date + datetime.timedelta(days=1)
            msg = f"Database has data up to {max_date.strftime('%d-%m-%Y')}.\nAppend 5 more years starting from {curr_ad.strftime('%d-%m-%Y')}?"
        else:
            curr_ad = datetime.date(2025, 7, 1)
            msg = f"Database is empty.\nGenerate 5 years of data starting from {curr_ad.strftime('%d-%m-%Y')}?"

        reply = QMessageBox.question(self, "Extend Calendar", msg)
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        # 3. Generate and Append 5 years (1826 days)
        try:
            for _ in range(1826): 
                ad_str = curr_ad.strftime("%d-%m-%Y")
                
                bs_date = nepali_datetime.date.from_datetime_date(curr_ad)
                y, m, d = bs_date.year, bs_date.month, bs_date.day
                bs_str = f"{y:04d}-{m:02d}-{d:02d}"
                
                cursor.execute("""
                    MERGE calendar AS target
                    USING (SELECT ? AS ad_date) AS source
                    ON target.ad_date = source.ad_date
                    WHEN NOT MATCHED THEN
                        INSERT (ad_date, bs_date, year, month, day)
                        VALUES (?, ?, ?, ?, ?);
                """, (ad_str, ad_str, bs_str, str(y), str(m), str(d)))
                
                curr_ad += datetime.timedelta(days=1)
            conn.commit()
        except Exception as e:
            conn.rollback()
            QMessageBox.critical(self, "Error", f"Failed to extend calendar: {e}")
            return
        self.load_data()
        QMessageBox.information(self, "Success", "Calendar successfully extended by 5 years!")

    def _generate_calendar_data_silent(self):
        """Silently generate 5 years of calendar data if DB is empty."""
        try:
            import nepali_datetime
        except ImportError:
            logger.warning("nepali-datetime package missing, cannot auto-generate calendar")
            return

        conn = self.db.get_connection(self._cal_db)
        if not conn:
            return
            
        cursor = conn.cursor()
        curr_ad = datetime.date(2025, 7, 1)
        
        # Generate 5 years (1826 days)
        try:
            for _ in range(1826): 
                ad_str = curr_ad.strftime("%d-%m-%Y")
                bs_date = nepali_datetime.date.from_datetime_date(curr_ad)
                y, m, d = bs_date.year, bs_date.month, bs_date.day
                bs_str = f"{y:04d}-{m:02d}-{d:02d}"
                
                cursor.execute("""
                    MERGE calendar AS target
                    USING (SELECT ? AS ad_date) AS source
                    ON target.ad_date = source.ad_date
                    WHEN NOT MATCHED THEN
                        INSERT (ad_date, bs_date, year, month, day)
                        VALUES (?, ?, ?, ?, ?);
                """, (ad_str, ad_str, bs_str, str(y), str(m), str(d)))
                
                curr_ad += datetime.timedelta(days=1)
            conn.commit()
            logger.info("Auto-generated 5 years of calendar data.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to auto-generate calendar data: {e}")

    def load_data(self):
        rows = self.db.execute_query(self._cal_db, "SELECT * FROM calendar")
        if not rows:
            # If empty, generate data silently and reload
            self._generate_calendar_data_silent()
            rows = self.db.execute_query(self._cal_db, "SELECT * FROM calendar")
            
        if not rows:
            self.table.setRowCount(0)
            return
            
        self._populate_table(rows)
        
    def _populate_table(self, rows):
        # Sort rows chronologically by ad_date (index 0) which is in "DD-MM-YYYY" format
        def parse_date(row):
            try:
                return datetime.datetime.strptime(row[0], "%d-%m-%Y")
            except Exception:
                return datetime.datetime.min
                
        sorted_rows = sorted(rows, key=parse_date)
        
        self.table.setRowCount(len(sorted_rows))
        for r, row in enumerate(sorted_rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(val) if val else ""))

    def save_manual_edits(self):
        conn = self.db.get_connection(self._cal_db)
        if not conn:
            QMessageBox.critical(self, "Error", "Could not connect to Calendar database.")
            return
        cursor = conn.cursor()
        try:
            rows_to_insert = [
                [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(5)]
                for r in range(self.table.rowCount())
                if self.table.item(r, 0) and self.table.item(r, 0).text()
            ]
            cursor.execute("DELETE FROM calendar")
            if rows_to_insert:
                cursor.executemany(
                    "INSERT INTO calendar (ad_date, bs_date, year, month, day) VALUES (?,?,?,?,?)",
                    rows_to_insert
                )
            conn.commit()
            QMessageBox.information(self, "Saved", "Manual changes save ho gaye!")
        except Exception as e:
            conn.rollback()
            QMessageBox.critical(self, "Error", f"Failed to save calendar: {e}")