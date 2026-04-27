import sqlite3
import os
import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QLabel, QHeaderView, QMessageBox, QHBoxLayout)
from PyQt6.QtCore import Qt

from src.utils.path_utils import get_data_file_path

class CalendarMappingUI(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Use centralized utility for data path
        self.db_path = get_data_file_path("calendar_data.db")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        self.setup_ui()
        self.init_db()

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
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS calendar 
                     (ad_date TEXT PRIMARY KEY, bs_date TEXT, year TEXT, month TEXT, day TEXT)""")
        conn.close()
        self.load_data()

    def set_company_path(self, path):
        """MainWindow isko call karta hai, hum sirf data reload kar dete hain"""
        self.load_data()

    def generate_calendar_data(self):
        try:
            import nepali_datetime
        except ImportError:
            QMessageBox.critical(self, "Error", "nepali-datetime package is missing. Please run: pip install nepali-datetime")
            return

        conn = sqlite3.connect(self.db_path)
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
            conn.close()
            return
            
        # 3. Generate and Append 5 years (1826 days)
        for _ in range(1826): 
            ad_str = curr_ad.strftime("%d-%m-%Y")
            
            # Get accurate astrological date from the package
            bs_date = nepali_datetime.date.from_datetime_date(curr_ad)
            y, m, d = bs_date.year, bs_date.month, bs_date.day
            bs_str = f"{y:04d}-{m:02d}-{d:02d}"
            
            # Use INSERT OR IGNORE so we don't crash if there's overlap
            cursor.execute("INSERT OR IGNORE INTO calendar VALUES (?, ?, ?, ?, ?)", 
                           (ad_str, bs_str, str(y), str(m), str(d)))
            
            curr_ad += datetime.timedelta(days=1)
        
        conn.commit()
        conn.close()
        self.load_data()
        QMessageBox.information(self, "Success", "Calendar successfully extended by 5 years!")

    def load_data(self):
        if not os.path.exists(self.db_path): return
        conn = sqlite3.connect(self.db_path)
        data = conn.execute("SELECT * FROM calendar").fetchall()
        conn.close()
        
        self.table.setRowCount(len(data))
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def save_manual_edits(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM calendar")
        for r in range(self.table.rowCount()):
            row_vals = [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(5)]
            if row_vals[0]:
                conn.execute("INSERT INTO calendar VALUES (?,?,?,?,?)", row_vals)
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Saved", "Manual changes save ho gaye!")