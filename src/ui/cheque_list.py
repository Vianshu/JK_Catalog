import sqlite3
import os
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QLineEdit, QLabel, QHeaderView,
    QPushButton, QCompleter, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QAbstractItemView
)

from PyQt6.QtGui import QTextDocument, QPageSize, QPageLayout, QFont, QPainter, QPen, QColor, QFontMetrics
from PyQt6.QtCore import Qt, QEvent, QSettings, QSizeF, QMarginsF, QRect
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from difflib import SequenceMatcher

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except:
            return super().__lt__(other)
        
class ChequeListUI(QWidget):
    def __init__(self, company_path=None):
        super().__init__()
        
        # ================= BASIC =================
        self.db_path = ""
        self.company_path = ""
        self.settings = QSettings("TallySync", "ChequeList")
        self.export_folder = self.settings.value("export_folder", "")
        self.bank_list_data = []
        self.crm_list_data = []
        self.party_mapping = {}
        self.columns = [
            "S.N", "Date", "Party Name", "Bank",
            "Chq No.", "CRM", "Amount", "Cash/Bank", "Clear Date", "Narration"
        ]

        # ================= MAIN LAYOUT =================
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # ================= LEFT =================
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # ---------- TOP BAR ----------
        top_bar = QHBoxLayout()
        
        # 1. Left Side: Clear Button
        self.btn_clear = QPushButton("✅ Clear Chq Unhide")
        self.btn_clear.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_clear.clicked.connect(self.toggle_clear_visibility)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self.apply_filter)
        
        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.search_box)
        
        # 2. Middle: Summary Labels
        top_bar.addStretch()
        
        self.lbl_count = QLabel("Total No. of Chq.: 0")
        self.lbl_total = QLabel("Amount: 0.00")
        self.lbl_count.setStyleSheet("font-weight: 600; margin-right: 10px;")
        self.lbl_total.setStyleSheet("font-weight: 600; margin-right: 10px;")
        
        top_bar.addWidget(self.lbl_count)
        top_bar.addWidget(self.lbl_total)
        
        top_bar.addStretch()

        # 3. Right Side: Utility Buttons
        self.btn_set_location = QPushButton("📂 Set Location")
        self.btn_set_location.setStyleSheet("background-color: #f39c12; color: white;")
        self.btn_set_location.clicked.connect(self.set_export_location)

        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setStyleSheet("background-color: #3498db; color: white;")
        self.btn_print.clicked.connect(self.print_table)
        
        self.btn_bank_list = QPushButton("🏦 Bank List")
        self.btn_bank_list.setCheckable(True)
        self.btn_bank_list.setStyleSheet("background-color: #3498db; color: white;")
        self.btn_bank_list.clicked.connect(self.toggle_bank_list)
        
        self.btn_export = QPushButton("Excel")
        self.btn_export.setStyleSheet("background-color: #3498db; color: white;")
        self.btn_export.clicked.connect(self.export_to_excel)
        
        top_bar.addWidget(self.btn_set_location)
        top_bar.addWidget(self.btn_print)
        top_bar.addWidget(self.btn_bank_list)
        top_bar.addWidget(self.btn_export)

        left_layout.addLayout(top_bar)
        
        # ---------- MAIN TABLE ----------
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.verticalHeader().hide()
        
        # Header settings: Sirf utni width jitna data hai
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents) 
        header.setCascadingSectionResizes(True)
        
        # Header click handle karne ke liye
        self.table.horizontalHeader().sectionClicked.connect(self.sort_table_safe)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.installEventFilter(self)
        
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(8, 0, 0, 0)  # 👈 LEFT GAP
        table_layout.addWidget(self.table)
        
        left_layout.addWidget(table_container, 1)

        main_layout.addWidget(left_container, 75)
        
        # Table Events
        self.table.cellDoubleClicked.connect(self.start_cell_search)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)

        # ================= RIGHT (BANK LIST) =================
        self.right_container = QWidget()
        right_layout = QVBoxLayout(self.right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        right_layout.addWidget(QLabel("<b>Bank Name List</b>"))

        self.bank_table = QTableWidget()
        self.bank_table.setColumnCount(3)
        self.bank_table.setHorizontalHeaderLabels(["SN", "Bank Name", "Count"])
        self.bank_table.verticalHeader().hide()
        self.bank_table.setColumnWidth(0, 40)
        self.bank_table.setColumnWidth(2, 50)
        self.bank_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bank_table.itemChanged.connect(self.handle_bank_change)

        right_layout.addWidget(self.bank_table)

        main_layout.addWidget(self.right_container, 25)
        self.right_container.setVisible(False)
    
    def toggle_bank_list(self):
        show = self.btn_bank_list.isChecked()
        self.right_container.setVisible(show)
        self.btn_bank_list.setText("❌ Hide Bank List" if show else "🏦 Bank List")

    def normalize_bank_name(self, name: str) -> str:
        name = name.lower().strip()
        for w in ["bank", "ltd", "ltd.", "limited"]:
            name = name.replace(w, "")
        return "".join(ch for ch in name if ch.isalpha() or ch == " ").strip()

    def is_similar_bank(self, a: str, b: str, threshold=0.85) -> bool:
        return SequenceMatcher(None, a, b).ratio() >= threshold
    
    def toggle_clear_visibility(self):
        is_currently_hidden = "Unhide" in self.btn_clear.text()
        
        for r in range(self.table.rowCount()):
            clear_date_item = self.table.item(r, 8)
            has_date = clear_date_item and clear_date_item.text().strip()
            
            if is_currently_hidden:
                # Ab sab dikhana hai
                self.table.setRowHidden(r, False)
            else:
                # Ab chhupana hai
                if has_date: 
                    self.table.setRowHidden(r, True)
        
        # Button update
        if is_currently_hidden:
            self.btn_clear.setText("🚫 Clear Chq Hide")
            self.btn_clear.setStyleSheet("background-color: #f0f0f0; color: black;")
        else:
            self.btn_clear.setText("✅ Clear Chq Unhide")
            self.btn_clear.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            
        # 🔥 Sabse important: click ke baad summary update trigger karein
        self.update_summary()
        
     # ================= TABLE LOGIC =================
    def on_item_changed(self, item):
        if self.table.signalsBlocked(): return
        
        col = item.column()
        text = item.text().strip()
        
        # --- 1. Date Format Validation (Column 1 and 8) ---
        if col in [1, 8] and text:
            import re
            pattern = r"^\d{4}-\d{2}-\d{2}$"
            if not re.match(pattern, text):
                QMessageBox.warning(self, "गलत फॉर्मेट", "मिति 2082-01-01 फॉर्मेन्ट मा लेख्नुहोस")
                self.table.blockSignals(True)
                item.setText("")
                self.table.blockSignals(False)
                return

        # --- 2. Amount Validation (Column 6) ---
        elif col == 6 and text:
            # Check karein ki kya text sirf number ya float hai
            try:
                # Agar comma hai to use hata kar check karein
                clean_text = text.replace(",", "")
                float(clean_text) 
            except ValueError:
                QMessageBox.warning(self, "गलत इनपुट", "Amount कॉलममा नम्बर मात्र लेख्नुहोस")
                self.table.blockSignals(True)
                item.setText("") # Galat hone par clear kar dega
                self.table.blockSignals(False)
                return

        # --- 3. Cash/Bank Auto-complete (Column 7) ---
        elif col == 7:
            raw_text = text.lower()
            self.table.blockSignals(True)
            if raw_text == "c" or raw_text == "cash":
                item.setText("Cash")
            elif raw_text == "b" or raw_text == "bank":
                item.setText("Bank")
            elif raw_text == "":
                item.setText("")
            else:
                item.setText("")
            self.table.blockSignals(False)

        self.table.resizeColumnToContents(col)
        self.save_cheques_to_db()
    
    def apply_filter(self):
        text = self.search_box.text().lower().strip()
        is_currently_hiding = "Unhide" in self.btn_clear.text()
        
        for r in range(self.table.rowCount()):
            clear_date_item = self.table.item(r, 8)
            clear_date = clear_date_item.text().strip() if clear_date_item else ""
            
            if is_currently_hiding and clear_date:
                self.table.setRowHidden(r, True)
                continue

            found = False
            if not text:
                found = True
            else:
                for c in range(self.table.columnCount()):
                    w = self.table.cellWidget(r, c)
                    if w and isinstance(w, QLineEdit):
                        val = w.text().lower()
                    else:
                        it = self.table.item(r, c)
                        val = it.text().lower() if it else ""

                    if text in val:
                        found = True
                        break

            self.table.setRowHidden(r, not found)

        self.update_summary()
    
    # ================= DB =================
    def save_cheques_to_db(self):
        if not self.db_path: return
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("BEGIN TRANSACTION")
            cur.execute("DELETE FROM cheques")

            for r in range(self.table.rowCount()):
                def txt(c):
                    w = self.table.cellWidget(r, c)
                    if w and isinstance(w, QLineEdit): return w.text().strip()
                    it = self.table.item(r, c)
                    return it.text().strip() if it and it.text().strip() else None

                cur.execute("INSERT INTO cheques VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    txt(0), txt(1), txt(2), txt(3),
                    txt(4), txt(5), txt(6), txt(7), txt(8), txt(9)
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save cheques: {e}")
        finally:
            conn.close()
        self.update_summary()
        
    # ================= BANK LIST =================
    def handle_bank_change(self, item):
        if item.column() != 1: return
        
        total_row_idx = self.bank_table.rowCount() - 1
        if item.row() == total_row_idx: return # Ignoring edits on total row

        new_name = item.text().strip()

        # DB Update Logic (Export explicit list items to bank_list)
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM bank_list")
        save_idx = 1
        self.bank_list_data = []
        for r in range(total_row_idx):
            it = self.bank_table.item(r, 1)
            if it and it.text().strip():
                conn.execute("INSERT INTO bank_list VALUES (?, ?)", (str(save_idx), it.text().strip()))
                self.bank_list_data.append(it.text().strip())
                save_idx += 1
        conn.commit()
        conn.close()

        self.ensure_bank_row_capacity()
    
    def start_cell_search(self, row, col):
        if col not in (2, 3, 5): return

        current = self.table.item(row, col)
        text = current.text() if current else ""

        editor = QLineEdit(text)
        editor.setFrame(False)
        
        data_list = []
        if col == 2:
            data_list = list(self.party_mapping.keys())
        elif col == 3:
            data_list = self.bank_list_data
        elif col == 5:
            data_list = self.crm_list_data

        if data_list:
            completer = QCompleter(data_list)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            editor.setCompleter(completer)

        self.table.setCellWidget(row, col, editor)
        editor.selectAll()
        editor.setFocus()
        
        editor.returnPressed.connect(lambda: self.handle_editor_enter(row, col, editor))
        
    def handle_editor_enter(self, row, col, editor):
        val = editor.text().strip()
        
        if col == 2:
            val_lower = val.lower()
            for alias, name in self.party_mapping.items():
                if alias.lower() == val_lower:
                    val = name
                    break

        self.table.removeCellWidget(row, col)
        
        item = QTableWidgetItem(val)
        if col == 6: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif col == 7: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, col, item) 
        
        self.table.resizeColumnToContents(col)
        
        if col == 2: self.table.setCurrentCell(row, 3)
        elif col == 3: self.table.setCurrentCell(row, 4)
        elif col == 5: self.table.setCurrentCell(row, 6)
        
        self.table.setFocus()
        self.save_cheques_to_db()

    # ================= SUMMARY =================
    def update_summary(self):
        total = 0.0
        count = 0
        for r in range(self.table.rowCount()):
            # Jo row chhupi hai (hidden), usko count nahi karega
            if self.table.isRowHidden(r):
                continue
                
            chq = self.table.item(r, 4) # Chq No
            amt = self.table.item(r, 6) # Amount
            
            if chq and chq.text().strip():
                count += 1
            try:
                total += float(amt.text().replace(",", "")) if amt and amt.text() else 0
            except:
                pass
        
        self.lbl_count.setText(f"Total No. of Chq.: {count}")
        self.lbl_total.setText(f"Amount: {total:,.2f}")
        self.update_bank_counts()

    def generate_sn(self, row_index):
        if row_index < 50:
            return f"{row_index + 1:03d}"

        # after 50, grow by blocks of 10
        extra = row_index - 50
        block = extra // 10
        sn = 50 + (block + 1) * 10
        offset = extra % 10
        return f"{sn - 9 + offset:03d}"

    def sort_table_safe(self, col_idx):
        # सिग्नल्स रोकें ताकि डेटाबेस बार-बार सेव न हो
        self.table.blockSignals(True)
        
        header = self.table.horizontalHeader()
        current_col = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()

        # अगर उसी कॉलम पर दोबारा क्लिक किया है, तो आर्डर बदलें
        if current_col == col_idx:
            new_order = (Qt.SortOrder.DescendingOrder 
                         if current_order == Qt.SortOrder.AscendingOrder 
                         else Qt.SortOrder.AscendingOrder)
        else:
            new_order = Qt.SortOrder.AscendingOrder
            
        self.table.sortItems(col_idx, new_order)
        header.setSortIndicator(col_idx, new_order)

        self.table.blockSignals(False)

    def ensure_cheque_schema(self, conn):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(cheques)")]
        if "clear_date" not in cols:
            conn.execute("ALTER TABLE cheques ADD COLUMN clear_date TEXT")
        if "narration" not in cols:
            conn.execute("ALTER TABLE cheques ADD COLUMN narration TEXT")

    def sync_cheque_rows(self):
        self.table.blockSignals(True)
        data = []
        
        # 1. डेटा निकालना
        for r in range(self.table.rowCount()):
            def val(c):
                w = self.table.cellWidget(r, c)
                if w and isinstance(w, QLineEdit): return w.text().strip()
                it = self.table.item(r, c)
                return it.text().strip() if it and it.text().strip() else ""
            
            row = [val(c) for c in range(10)]
            if any(v.strip() for v in row[1:]): 
                data.append(row)

        # 2. डेटा वापस डालना (S.N को 001 फॉर्मेट में करके)
        self.table.setRowCount(0)
        for row_data in data:
            idx = self.table.rowCount()
            self.table.insertRow(idx)
            for c, v in enumerate(row_data):
                if c == 0:
                    val = f"{idx + 1:03d}"
                else:
                    val = v
                
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif c == 6:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif c == 7:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, c, item)

        # 3. एक्स्ट्रा खाली रोज़ (S.N को 001 फॉर्मेट में करके)
        target = max(50, len(data) + 10)
        while self.table.rowCount() < target:
            idx = self.table.rowCount()
            self.table.insertRow(idx)
            for c in range(10):
                if c == 0:
                    val = f"{idx + 1:03d}"
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, c, item)
                else:
                    item = QTableWidgetItem("")
                    if c == 6: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif c == 7: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, c, item)
                    
        self.table.blockSignals(False)
            
    def update_bank_counts(self):
        counts = {}
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            
            def val(c):
                w = self.table.cellWidget(r, c)
                if w and isinstance(w, QLineEdit): return w.text().strip()
                it = self.table.item(r, c)
                return it.text().strip() if it else ""

            name = val(3) # Bank Column
            if name:
                counts[name] = counts.get(name, 0) + 1
        
        self.bank_table.blockSignals(True)
        total_count = 0
        total_row_idx = self.bank_table.rowCount() - 1
        
        for r in range(total_row_idx):
            bank_name_item = self.bank_table.item(r, 1)
            if bank_name_item:
                bn = bank_name_item.text().strip()
                if bn:
                    count_val = counts.get(bn, 0)
                    total_count += count_val
                    display_val = str(count_val) if count_val > 0 else ""
                    
                    self.bank_table.setItem(r, 2, QTableWidgetItem(display_val))
                    count_item = self.bank_table.item(r, 2)
                    if count_item:
                        count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    self.bank_table.setItem(r, 2, QTableWidgetItem(""))

        # Update Total Row
        total_str = str(total_count) if total_count > 0 else "0"
        total_item = QTableWidgetItem(total_str)
        total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bank_table.setItem(total_row_idx, 2, total_item)
        
        lbl_item = QTableWidgetItem("Total")
        lbl_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bank_table.setItem(total_row_idx, 1, lbl_item)
        self.bank_table.setItem(total_row_idx, 0, QTableWidgetItem(""))
        self.bank_table.blockSignals(False)

    def clear_completed_cheques(self):
        reply = QMessageBox.question(self, "Confirm Clear", "Kya aap saare 'C' (Cleared) cheques hatana chahte hain?", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM cheques WHERE status = 'C'")
            conn.commit(); conn.close()
            self.load_all_data()

    def set_company_path(self, path):
        self.company_path = path
        self.db_path = os.path.join(path, "chq_list.db")
        
        # 1. Load CRM Data
        crm_file = os.path.join(path, "crm_data.json")
        try:
            if os.path.exists(crm_file):
                import json
                with open(crm_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict): self.crm_list_data = data.get("crms", [])
                    elif isinstance(data, list): self.crm_list_data = data
            else:
                self.crm_list_data = []
        except:
            self.crm_list_data = []

        # 2. Load Party Mapping
        ledger_db = os.path.join(path, "ledger_internal_data.db")
        self.party_mapping = {}
        if os.path.exists(ledger_db):
            try:
                l_conn = sqlite3.connect(ledger_db)
                c_rows = l_conn.execute("SELECT Alias, Name FROM row_leger_data WHERE \"Group\" LIKE '%Sundry Debtors%'").fetchall()
                for alias, name in c_rows:
                    if alias and str(alias).strip():
                        self.party_mapping[str(alias).strip()] = str(name).strip() if name else ""
                l_conn.close()
            except Exception as e:
                print("Error loading ledger:", e)

        # 3. Setup Cheque DB
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cheques (
                sn TEXT, date TEXT, party TEXT, bank TEXT,
                chq_no TEXT, crm TEXT, amount TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_list (
                sn TEXT, bank_name TEXT
            )
        """)
        self.ensure_cheque_schema(conn)
        conn.commit()
        conn.close()
        self.load_all_data()

    def load_all_data(self):
        if not self.db_path: return
        conn = sqlite3.connect(self.db_path)
        
        # Bank list loading logic
        bnks = conn.execute("SELECT * FROM bank_list").fetchall()
        self.bank_table.blockSignals(True)
        total_required_rows = max(30, len(bnks)+10)
        self.bank_table.setRowCount(total_required_rows)
        
        total_idx = total_required_rows - 1
        
        for i in range(total_idx): 
            self.bank_table.setItem(i, 0, QTableWidgetItem(str(i+1)))
            self.bank_table.setItem(i, 1, QTableWidgetItem(""))
            self.bank_table.setItem(i, 2, QTableWidgetItem(""))
            
        for r, b in enumerate(bnks): 
            self.bank_table.setItem(r, 1, QTableWidgetItem(b[1]))
            
        self.bank_table.setItem(total_idx, 0, QTableWidgetItem(""))
        total_lbl = QTableWidgetItem("Total")
        total_lbl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.bank_table.setItem(total_idx, 1, total_lbl)
        self.bank_table.setItem(total_idx, 2, QTableWidgetItem(""))
            
        self.bank_table.blockSignals(False)
        self.bank_list_data = [b[1] for b in bnks]
        
        # Cheque list loading logic
        chqs = conn.execute("SELECT * FROM cheques").fetchall()
        conn.close()
        
        self.table.blockSignals(True)
        self.table.setRowCount(len(chqs))
        for r, row in enumerate(chqs):
            for c, v in enumerate(row):
                if c >= 10: break
                val = "" if v in (None, "None") else str(v)
                
                # S.N को लोड करते समय ही 001 फॉर्मेट में बदलें
                if c == 0:
                    try:
                        val = f"{int(val):03d}"
                    except:
                        val = f"{r + 1:03d}"
                
                item = QTableWidgetItem(val)
                if c == 0: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif c == 6: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif c == 7: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        
        self.table.blockSignals(False)
        
        # --- 3. Final Triggers (सही क्रम) ---
        self.sync_cheque_rows()      # रोज़ को सिंक करें
        self.apply_initial_hide()    # पहले डेटा छुपाएं (App Start Hide)
        self.update_summary()        # फिर समरी कैलकुलेट करें (ताकि छुपा हुआ डेटा न गिना जाए)
        self.update_bank_counts()    # बैंक काउंट अपडेट करें
        
        self.table.setColumnWidth(9, 250) # कॉलम विड्थ सेट करें
    
    def showEvent(self, event):
        super().showEvent(event)
        self.update_summary() # Tab switch par trigger
    
    def apply_initial_hide(self):
        """App start logic to hide cleared rows"""
        for r in range(self.table.rowCount()):
            clear_date_item = self.table.item(r, 8)
            if clear_date_item and clear_date_item.text().strip():
                self.table.setRowHidden(r, True)
                
    def ensure_bank_row_capacity(self):
        self.bank_table.blockSignals(True)
        total_row_idx = self.bank_table.rowCount() - 1
        filled = 0
        for r in range(total_row_idx):
            it = self.bank_table.item(r, 1)
            if it and it.text().strip():
                filled += 1

        # Keep at least 4 empty rows above Total
        empty_rows = total_row_idx - filled
        if empty_rows < 4:
            # Need to insert 5 rows above Total
            for _ in range(5):
                self.bank_table.insertRow(total_row_idx)
            
            # Recalculate SNs and update total_row_idx
            total_row_idx = self.bank_table.rowCount() - 1
            for r in range(total_row_idx):
                self.bank_table.setItem(r, 0, QTableWidgetItem(str(r+1)))
                
        self.bank_table.blockSignals(False)

    def set_export_location(self):
        start_dir = self.export_folder if self.export_folder and os.path.exists(self.export_folder) else ""
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder", start_dir)
        if folder:
            self.export_folder = folder
            self.settings.setValue("export_folder", folder)
            QMessageBox.information(self, "Location Set", f"Export folder saved to:\n{folder}")

    def export_to_excel(self):
        if not self.export_folder:
            QMessageBox.warning(self, "Set Location", "Please set an export location first using 'Set Location' button.")
            return
            
        company_name = "Unknown"
        if hasattr(self, "company_path") and self.company_path:
            # Safely extract company name part from the path
            company_name = os.path.basename(self.company_path.strip(r"\/"))
            import re
            company_name = re.sub(r'[\/:*?"<>|]', '_', company_name)
            
        filename = f"chq_List_{company_name}.xlsx"
        path = os.path.join(self.export_folder, filename)

        d = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            def val(c):
                w = self.table.cellWidget(r, c)
                if w and isinstance(w, QLineEdit): return w.text().strip()
                it = self.table.item(r, c)
                return it.text().strip() if it and it.text().strip() else ""
            row = [val(c) for c in range(10)]
            if any(v.strip() for v in row[1:]): d.append(row)
        
        try:
            df = pd.DataFrame(d, columns=self.columns)
            writer = pd.ExcelWriter(path, engine='xlsxwriter')
            df.to_excel(writer, index=False, sheet_name='Cheque List')
            
            worksheet = writer.sheets['Cheque List']
            (max_row, max_col) = df.shape
            
            if max_row > 0:
                worksheet.autofilter(0, 0, max_row, max_col - 1)
                for i, col in enumerate(df.columns):
                    max_len = max(
                        df[col].astype(str).map(len).max() if not df[col].empty else 0,
                        len(str(col))
                    ) + 2
                    worksheet.set_column(i, i, max_len)
            
            writer.close()
            
            if os.name == 'nt':
                os.startfile(path)
                
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export Excel:\n{str(e)}")

    def print_table(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setPageMargins(
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter
        )
        
        from PyQt6.QtPrintSupport import QPrintPreviewDialog
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self._paint_cheque_table)
        preview.exec()

    def _paint_cheque_table(self, printer):
        """Draw the cheque table directly using QPainter for pixel-perfect A4 Landscape output."""
        painter = QPainter()
        if not painter.begin(printer):
            return

        page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        page_w = page_rect.width()
        page_h = page_rect.height()

        # --- Fonts (use painter.fontMetrics for PRINTER DPI measurements) ---
        title_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        cell_font = QFont("Segoe UI", 8)

        # Measure using painter's coordinate system (printer DPI, not screen DPI)
        painter.setFont(title_font)
        title_height = int(painter.fontMetrics().height() * 2.2)

        painter.setFont(header_font)
        header_height = int(painter.fontMetrics().height() * 1.8)

        painter.setFont(cell_font)
        fm_cell = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.6)
        padding = int(fm_cell.averageCharWidth() * 1.2)

        # --- Column widths as fractions of full page width ---
        # S.N(5%), Date(9%), Party(22%), Bank(12%), Chq(8%), CRM(8%), Amount(10%), Cash/Bank(7%), Clear Date(9%), Narration(10%)
        col_ratios = [0.05, 0.09, 0.22, 0.12, 0.08, 0.08, 0.10, 0.07, 0.09, 0.10]
        col_widths = [int(page_w * r) for r in col_ratios]
        col_widths[-1] = page_w - sum(col_widths[:-1])

        # --- Alignment per column ---
        alignments = [
            Qt.AlignmentFlag.AlignHCenter,  # S.N
            Qt.AlignmentFlag.AlignHCenter,  # Date
            Qt.AlignmentFlag.AlignLeft,     # Party Name
            Qt.AlignmentFlag.AlignLeft,     # Bank
            Qt.AlignmentFlag.AlignHCenter,  # Chq No
            Qt.AlignmentFlag.AlignLeft,     # CRM
            Qt.AlignmentFlag.AlignRight,    # Amount
            Qt.AlignmentFlag.AlignHCenter,  # Cash/Bank
            Qt.AlignmentFlag.AlignHCenter,  # Clear Date
            Qt.AlignmentFlag.AlignLeft,     # Narration
        ]

        pen = QPen(QColor(0, 0, 0), 2)

        def draw_title(y):
            painter.setFont(title_font)
            painter.setPen(pen)
            rect = QRect(0, y, page_w, title_height)
            painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "Cheque List")
            return y + title_height

        def draw_header(y):
            painter.setFont(header_font)
            painter.setPen(pen)
            x = 0
            for c, col_name in enumerate(self.columns):
                rect = QRect(x, y, col_widths[c], header_height)
                painter.fillRect(rect, QColor(220, 220, 220))
                painter.drawRect(rect)
                text_rect = QRect(x + padding, y, col_widths[c] - 2 * padding, header_height)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, col_name)
                x += col_widths[c]
            return y + header_height

        def draw_row(y, row_data):
            painter.setFont(cell_font)
            painter.setPen(pen)
            x = 0
            for c, text in enumerate(row_data):
                rect = QRect(x, y, col_widths[c], row_height)
                painter.drawRect(rect)
                text_rect = QRect(x + padding, y, col_widths[c] - 2 * padding, row_height)
                align = alignments[c] | Qt.AlignmentFlag.AlignVCenter
                painter.drawText(text_rect, align, text)
                x += col_widths[c]
            return y + row_height

        # --- Collect visible data rows ---
        data_rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            def val(c):
                w = self.table.cellWidget(r, c)
                if w and isinstance(w, QLineEdit): return w.text().strip()
                it = self.table.item(r, c)
                return it.text().strip() if it and it.text().strip() else ""
            row_data = [val(c) for c in range(10)]
            if any(v.strip() for v in row_data[1:]):
                data_rows.append(row_data)

        # --- Render pages ---
        y = 0
        y = draw_title(y)
        y = draw_header(y)

        for row_data in data_rows:
            if y + row_height > page_h:
                printer.newPage()
                y = 0
                y = draw_header(y)
            y = draw_row(y, row_data)

        painter.end()

    def eventFilter(self, source, event):
        if source == self.table and event.type() == QEvent.Type.KeyPress:
            row = self.table.currentRow()
            col = self.table.currentColumn()
            key = event.key()
            text = event.text()

            if col == 0: return super().eventFilter(source, event)

            # Cell Search logic for columns 2, 3, 5
            if col in (2, 3, 5):
                if key == Qt.Key.Key_F2 or (text and text.isprintable()):
                    self.start_cell_search(row, col)
                    if text and text.isprintable() and key != Qt.Key.Key_F2:
                        editor = self.table.cellWidget(row, col)
                        if isinstance(editor, QLineEdit): editor.setText(text)
                    return True

            # Baki Columns
            elif col != 0:
                item = self.table.item(row, col)
                if not item:
                    item = QTableWidgetItem("")
                    self.table.setItem(row, col, item)
                
                if key == Qt.Key.Key_F2:
                    self.table.editItem(item)
                    return True

                if text and text.isprintable():
                    if item.text().strip() == "":
                        self.table.editItem(item)
                        editor = self.table.findChild(QLineEdit)
                        if editor: editor.setText(text)
                        return True
                    else:
                        return True

        return super().eventFilter(source, event)