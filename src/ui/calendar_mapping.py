import sqlite3
import os
import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QLabel, QHeaderView, QMessageBox, QHBoxLayout)
from PyQt6.QtCore import Qt

class CalendarMappingUI(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Hamesha "Data" folder ke andar calendar_data.db dhundega
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(base_dir, "Data")
        
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            
        self.db_path = os.path.join(data_dir, "calendar_data.db")
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
        reply = QMessageBox.question(self, "Generate", "01-07-2025 se 5 saal ka data generate karein?")
        if reply == QMessageBox.StandardButton.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM calendar")
            
            curr_ad = datetime.date(2025, 7, 1)
            y, m, d = 2082, 3, 17 
            
            for _ in range(1826): 
                ad_str = curr_ad.strftime("%d-%m-%Y")
                bs_str = f"{y:04d}-{m:02d}-{d:02d}"
                cursor.execute("INSERT INTO calendar VALUES (?, ?, ?, ?, ?)", 
                               (ad_str, bs_str, str(y), str(m), str(d)))
                
                curr_ad += datetime.timedelta(days=1)
                d += 1
                if d > 31: d = 1; m += 1
                if m > 12: m = 1; y += 1
            
            conn.commit()
            conn.close()
            self.load_data()
            QMessageBox.information(self, "Success", "Data saved in Data folder!")

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