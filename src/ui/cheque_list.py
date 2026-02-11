import sqlite3
import os
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QLineEdit, QLabel, QHeaderView,
    QPushButton, QCompleter, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QAbstractItemView
)
from PyQt6.QtCore import Qt, QEvent
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
        self.bank_list_data = []
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
        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setStyleSheet("background-color: #3498db; color: white;")
        
        self.btn_bank_list = QPushButton("🏦 Bank List")
        self.btn_bank_list.setCheckable(True)
        self.btn_bank_list.setStyleSheet("background-color: #3498db; color: white;")
        self.btn_bank_list.clicked.connect(self.toggle_bank_list)
        
        self.btn_export = QPushButton("Excel")
        self.btn_export.setStyleSheet("background-color: #3498db; color: white;")
        self.btn_export.clicked.connect(self.export_to_excel)
        
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
        self.table.cellDoubleClicked.connect(self.start_bank_search)
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
        
        # यह चेक करें कि अभी 'Hide' मोड एक्टिव है या नहीं (बटन के टेक्स्ट से)
        is_currently_hiding = "Unhide" in self.btn_clear.text()
        
        for r in range(self.table.rowCount()):
            # 1. पहले 'Cleared Check' वाला लॉजिक चेक करें
            clear_date_item = self.table.item(r, 8)
            clear_date = clear_date_item.text().strip() if clear_date_item else ""
            
            if is_currently_hiding and clear_date:
                self.table.setRowHidden(r, True)
                continue

            # 2. अब सर्च टेक्स्ट के लिए सभी कॉलम्स को चेक करें
            found = False
            if not text:
                found = True # अगर सर्च खाली है तो सब दिखाओ
            else:
                # 0 से 9 तक के सभी कॉलम्स चेक करें
                for c in range(self.table.columnCount()):
                    # Bank Column (3) में अक्सर Widget (QLineEdit) होता है, उसे अलग से हैंडल करें
                    if c == 3:
                        w = self.table.cellWidget(r, 3)
                        if w and isinstance(w, QLineEdit):
                            val = w.text().lower()
                        else:
                            it = self.table.item(r, 3)
                            val = it.text().lower() if it else ""
                    else:
                        # बाकी सभी कॉलम्स (Party Name, Chq No, Amount, etc.)
                        it = self.table.item(r, c)
                        val = it.text().lower() if it else ""

                    if text in val:
                        found = True
                        break

            self.table.setRowHidden(r, not found)

        # सर्च के बाद टोटल काउंट अपडेट करें
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
                bw = self.table.cellWidget(r, 3)
                bank_val = bw.text().strip() if bw else (self.table.item(r, 3).text().strip() if self.table.item(r, 3) else "")

                def txt(c):
                    it = self.table.item(r, c)
                    return it.text().strip() if it and it.text().strip() else None

                # 🔥 Yahan self.get_status_value(r) hata kar txt(7) kar diya
                cur.execute("INSERT INTO cheques VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    txt(0), txt(1), txt(2), bank_val,
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
        new_name = item.text().strip()
        if not new_name: return

        # DB Update Logic
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM bank_list")
        for r in range(self.bank_table.rowCount()):
            it = self.bank_table.item(r, 1)
            if it and it.text().strip():
                conn.execute("INSERT INTO bank_list VALUES (?, ?)", (str(r + 1), it.text().strip()))
        conn.commit()
        conn.close()

        # सर्च लिस्ट (Completer) को अपडेट करना
        self.bank_list_data = [
            self.bank_table.item(r, 1).text().strip()
            for r in range(self.bank_table.rowCount())
            if self.bank_table.item(r, 1) and self.bank_table.item(r, 1).text().strip()
        ]
        self.ensure_bank_row_capacity()
    
    def start_bank_search(self, row, col):
        if col != 3: return

        current = self.table.item(row, col)
        text = current.text() if current else ""

        editor = QLineEdit(text)
        editor.setFrame(False)
        
        # Dropdown list (Bank names)
        if self.bank_list_data:
            completer = QCompleter(self.bank_list_data)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            editor.setCompleter(completer)

        self.table.setCellWidget(row, col, editor)
        editor.selectAll()
        editor.setFocus()
        
        # Enter dabane par kya ho
        editor.returnPressed.connect(lambda: self.handle_bank_editor_enter(row, col, editor))
        
    def handle_bank_editor_enter(self, row, col, editor):
        val = editor.text().strip()
        self.table.removeCellWidget(row, col)
        self.table.setItem(row, col, QTableWidgetItem(val)) 
        
        # Bank column ki width turant adjust karein
        self.table.resizeColumnToContents(col)
        
        self.table.setCurrentCell(row, 4) # Chq No par jayein
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
            bw = self.table.cellWidget(r, 3)
            b_val = bw.text().strip() if bw else (self.table.item(r, 3).text() if self.table.item(r, 3) else "")
            st_item = self.table.item(r, 7)
            st_val = st_item.text().strip() if st_item else ""
            
            row = [b_val if c==3 else (st_val if c==7 else (self.table.item(r,c).text() if self.table.item(r,c) else "")) for c in range(10)]
            
            if any(v.strip() for v in row[1:]): 
                data.append(row)

        # 2. डेटा वापस डालना (S.N को 001 फॉर्मेट में करके)
        self.table.setRowCount(0)
        for row_data in data:
            idx = self.table.rowCount()
            self.table.insertRow(idx)
            for c, v in enumerate(row_data):
                if c == 0:
                    val = f"{idx + 1:03d}" # 3-digit format
                else:
                    val = v
                
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, c, item)

        # 3. एक्स्ट्रा खाली रोज़ (S.N को 001 फॉर्मेट में करके)
        target = max(50, len(data) + 10)
        while self.table.rowCount() < target:
            idx = self.table.rowCount()
            self.table.insertRow(idx)
            for c in range(10):
                if c == 0:
                    val = f"{idx + 1:03d}" # 3-digit format
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, c, item)
                else:
                    self.table.setItem(idx, c, QTableWidgetItem(""))
                    
        self.table.blockSignals(False)
            
    def update_bank_counts(self):
        counts = {}
        # 1. Main table se counts ikatha karein (Sirf wahi jo dikh rahe hain)
        for r in range(self.table.rowCount()):
            # Check karein ki kya row chhupi hui hai?
            if self.table.isRowHidden(r):
                continue  # Agar chhupi hai to ise mat gino
            
            item = self.table.item(r, 3) # Bank Column
            name = item.text().strip() if item else ""
            if name:
                counts[name] = counts.get(name, 0) + 1
        
        # 2. Bank Table mein counts likhein
        self.bank_table.blockSignals(True)
        for r in range(self.bank_table.rowCount()):
            bank_name_item = self.bank_table.item(r, 1)
            if bank_name_item:
                bn = bank_name_item.text().strip()
                count_val = counts.get(bn, 0)
                
                # Agar count 0 hai to khali rakhein, nahi to number
                display_val = str(count_val) if count_val > 0 else ""
                
                self.bank_table.setItem(r, 2, QTableWidgetItem(display_val))
                
                # Text ko center mein karein
                count_item = self.bank_table.item(r, 2)
                if count_item:
                    count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    
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
        self.db_path = os.path.join(path, "chq_list.db")
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

        # 🔥 MIGRATION
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
        self.bank_table.setRowCount(max(30, len(bnks)+10))
        for i in range(self.bank_table.rowCount()): 
            self.bank_table.setItem(i, 0, QTableWidgetItem(str(i+1)))
        for r, b in enumerate(bnks): 
            self.bank_table.setItem(r, 1, QTableWidgetItem(b[1]))
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
        filled = 0
        for r in range(self.bank_table.rowCount()):
            it = self.bank_table.item(r, 1)
            if it and it.text().strip():
                filled += 1

        # Initial growth: 26 → +5
        if self.bank_table.rowCount() == 30 and filled >= 26:
            self.bank_table.setRowCount(35)
            return

        # After that: 1 by 1
        if filled >= self.bank_table.rowCount() - 1:
            self.bank_table.setRowCount(self.bank_table.rowCount() + 1)

    def export_to_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel", "", "Excel Files (*.xlsx)")
        if path:
            d = []
            for r in range(self.table.rowCount()):
                bw = self.table.cellWidget(r, 3); b_val = bw.text() if bw else (self.table.item(r, 3).text() if self.table.item(r, 3) else "")
                
                # 🔥 Direct text from item
                st_item = self.table.item(r, 7)
                st_val = st_item.text() if st_item else ""
                
                row = [b_val if c==3 else (st_val if c==7 else (self.table.item(r,c).text() if self.table.item(r,c) else "")) for c in range(10)]
                if any(v.strip() for v in row[1:]): d.append(row)
            pd.DataFrame(d, columns=self.columns).to_excel(path, index=False)

    def eventFilter(self, source, event):
        if source == self.table and event.type() == QEvent.Type.KeyPress:
            row = self.table.currentRow()
            col = self.table.currentColumn()
            key = event.key()
            text = event.text()

            if col == 0: return super().eventFilter(source, event)

            # Bank Search logic
            if col == 3:
                if key == Qt.Key.Key_F2 or (text and text.isprintable()):
                    self.start_bank_search(row, col)
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
                        return True # Block overwrite

        return super().eventFilter(source, event)