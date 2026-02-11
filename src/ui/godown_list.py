import sqlite3
import os
import pandas as pd
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtPrintSupport import QPrintPreviewDialog, QPrinter

class GodownListUI(QWidget):
    def __init__(self, data_folder_path, final_data_df=None):
        super().__init__()
        self.change_data_folder(data_folder_path, final_data_df, init_ui=True)

    def change_data_folder(self, company_path, final_data_df=None, init_ui=False):
        if not company_path: return
        self.db_path = os.path.join(company_path, "godown_stock.db")
        self.final_data = final_data_df

        if init_ui:
            self.init_ui()
        
        self.init_db()
        
        # Safety check: Only clear table if it was initialized
        if hasattr(self, 'table'):
            self.table.setRowCount(0) 
            self.load_data_from_db()
            self.update_completer()

    # ---------------- DATABASE ----------------
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                item_name TEXT, qty_per_ctn TEXT, unit TEXT,
                total_ctn TEXT, godown TEXT, part_no TEXT, cn TEXT
            )
        """)
        conn.close()

    # ---------------- COMPLETER ----------------
    def update_completer(self):
        self.completer = None
        if self.final_data is not None and not self.final_data.empty:
            if "Alias" in self.final_data.columns:
                Alias = self.final_data["Alias"].astype(str).tolist()
                self.completer = QCompleter(Alias)
                self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                self.completer.setFilterMode(Qt.MatchFlag.MatchContains)

    # ---------------- UI ----------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        btn_excel = QPushButton("📥 Excel डाउनलोड")
        btn_print = QPushButton("🖨️ प्रिंट प्रिव्यू")
        btn_save = QPushButton("💾 Save & Sort")

        btn_excel.clicked.connect(self.export_to_excel)
        btn_print.clicked.connect(self.handle_print_preview)
        btn_save.clicked.connect(self.manual_save_and_sort)

        top.addWidget(btn_excel)
        top.addWidget(btn_print)
        top.addWidget(btn_save)
        top.addStretch()
        layout.addLayout(top)

        self.table = QTableWidget(200, 7)
        self.table.setHorizontalHeaderLabels([
            "सामानको नाम", "प्रति कार्टुन", "UNIT",
            "जम्मा कार्टुन", "गोदाम", "Part No", "CN"
        ])

        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 80)
        
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | 
            QAbstractItemView.EditTrigger.AnyKeyPressed | 
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        
        self.table.installEventFilter(self)
        self.table.cellDoubleClicked.connect(self.start_Alias_search)
        self.table.itemChanged.connect(self.handle_item_changed)
        
        layout.addWidget(self.table)

    # ---------------- EVENT FILTER (🔥 MAIN FIX) ----------------
    def eventFilter(self, source, event):
        if source == self.table and event.type() == QEvent.Type.KeyPress:
            row = self.table.currentRow()
            col = self.table.currentColumn()

            # F2 → Alias Search
            if event.key() == Qt.Key.Key_F2:
                if row != -1 and col == 0:
                    self.start_Alias_search(row, col)
                    return True

            # Enter Navigation: कर्सर को अगले सेल में ले जाना और उसे "लिखने के लिए तैयार" करना
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                next_row = row
                next_col = col + 1

                # अगर आखिरी कॉलम है तो अगली लाइन के पहले कॉलम पर जाओ
                if col == self.table.columnCount() - 1:
                    next_row = row + 1
                    next_col = 0
                
                # टेबल की रेंज चेक करें
                if next_row < self.table.rowCount():
                    self.table.setCurrentCell(next_row, next_col)
                    # 🔥 यह लाइन जादू करेगी: अगले सेल को सीधा EDIT MODE में खोल देगी
                    self.table.editItem(self.table.currentItem())
                
                return True

        return super().eventFilter(source, event)
    
    def create_table_item(self, text, alignment=Qt.AlignmentFlag.AlignLeft, locked=False):
        """नयाँ आइटम बनाउने र त्यसको प्रोपर्टी सेट गर्ने फङ्सन"""
        item = QTableWidgetItem(str(text))
        # Alignment सेट गर्ने
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        
        # Lock गर्ने कि नगर्ने
        if locked:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            
        return item
    
    def start_Alias_search(self, row, col):
        if col != 0: return
        current = self.table.item(row, col)
        text = current.text() if current else ""
        editor = QLineEdit(text)
        if self.completer:
            editor.setCompleter(self.completer)
        self.table.setCellWidget(row, col, editor)
        editor.selectAll()
        editor.setFocus()
        editor.returnPressed.connect(lambda: self.handle_editor_enter(row, editor))
        
    def handle_editor_enter(self, row, editor):
        Alias = editor.text().strip()
        self.table.removeCellWidget(row, 0)
        
        if self.final_data is not None:
            match = self.final_data[self.final_data["Alias"].astype(str).str.lower() == Alias.lower()]
            if not match.empty:
                data = match.iloc[0]
                
                # 1. डेटा भरना (Item Name, Unit, Part No)
                self.table.setItem(row, 0, self.create_table_item(data["Item_Name"]))
                self.table.setItem(row, 2, self.create_table_item(data.get("Unit", ""), Qt.AlignmentFlag.AlignCenter, True))
                
                p_no = str(data.get("Part_No", ""))
                if p_no.lower() == "none": p_no = ""
                self.table.setItem(row, 5, self.create_table_item(p_no, Qt.AlignmentFlag.AlignCenter, True))
                
                # 2. बाकी कॉलम को खाली और Editable बनाना (ताकि editItem काम करे)
                if not self.table.item(row, 1):
                    self.set_item_locked(row, 1, "", should_lock=False)
                if not self.table.item(row, 3):
                    self.set_item_locked(row, 3, "", should_lock=False)
                if not self.table.item(row, 4):
                    self.set_item_locked(row, 4, "", should_lock=False)
                if not self.table.item(row, 6):
                    self.set_item_locked(row, 6, "", should_lock=False)

                # 3. कर्सर को "प्रति कार्टुन" (Index 1) पर ले जाना
                self.table.setCurrentCell(row, 1)
                self.table.setFocus()
                
                # 🔥 जादू वाली लाइन: सेल को सीधे EDIT MODE में खोलना
                self.table.editItem(self.table.item(row, 1))
                
                self.save_data_to_db()
                return

        # अगर मैच नहीं मिला तो Alias को ही Item Name बना देना
        self.table.setItem(row, 0, self.create_table_item(Alias))
        self.table.setCurrentCell(row, 1)
        self.table.setFocus()
        
        # यहाँ भी edit mode चालू करें
        if not self.table.item(row, 1):
            self.set_item_locked(row, 1, "", should_lock=False)
        self.table.editItem(self.table.item(row, 1))
    
    def ensure_minimum_rows(self, min_rows=200):
        """टेबल में कम से कम 200 रोज़ सुनिश्चित करता है"""
        current_rows = self.table.rowCount()
        if current_rows < min_rows:
            self.table.setRowCount(min_rows)
            
    def handle_item_changed(self, item):
        row = item.row()
        col = item.column()
        text = item.text().strip()

        self.table.blockSignals(True)

        # ✅ कॉलम 2 में कुछ भी लिखते ही उसे Right Align रखना
        if col == 1:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # अगर सामान का नाम हटाया जाए तो बाकी सेल साफ़ करना
        if col == 0 and text == "":
            for c in range(1, 7):
                lock = True if c in (2, 5) else False
                self.set_item_locked(row, c, "", should_lock=lock)

        self.table.blockSignals(False)
        self.save_data_to_db()   
    
    def load_data_from_db(self):
        if not os.path.exists(self.db_path): return
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT * FROM stock").fetchall()
        conn.close()

        self.table.blockSignals(True)
        for r, data in enumerate(rows):
            for c, val in enumerate(data):
                align = Qt.AlignmentFlag.AlignLeft
                is_locked = False
                
                if c == 1: align = Qt.AlignmentFlag.AlignRight # प्रति कार्टुन
                if c in (2, 5, 6): align = Qt.AlignmentFlag.AlignCenter # Unit, PartNo, CN
                if c in (2, 5): is_locked = True # Unit र Part No मात्र लक
                
                self.table.setItem(r, c, self.create_table_item(val, align, is_locked))
        self.table.blockSignals(False)
        
    def save_data_to_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("BEGIN TRANSACTION")
            cur.execute("DELETE FROM stock")
            for r in range(self.table.rowCount()):
                row_data = [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(7)]
                if any(row_data):
                    cur.execute("INSERT INTO stock VALUES (?,?,?,?,?,?,?)", row_data)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save godown stock: {e}")
        finally:
            conn.close()
    
    def manual_save_and_sort(self):
        self.table.blockSignals(True)
        try:
            # Part No रिफ्रेश करें
            self.refresh_part_no_from_item()

            # Part No (Column 5) के आधार पर सॉर्ट करें
            self.table.sortItems(5, Qt.SortOrder.AscendingOrder)

            # खाली रोज़ हटाएं
            self.delete_fully_empty_rows()

            # 🔥 अब यह एरर नहीं देगा
            self.ensure_minimum_rows(200)

        except Exception as e:
            print(f"Error during save/sort: {e}")
        
        self.table.blockSignals(False)
        self.save_data_to_db()
        QMessageBox.information(self, "Saved", "Data Saved & Sorted Successfully")
    
    # ---------------- CELL LOGIC ----------------
    def set_item_locked(self, row, col, value, should_lock=True):
        """वैल्यू सेट करता है और अलाइनमेंट ठीक रखता है"""
        item = QTableWidgetItem(str(value))
        
        # ✅ कॉलम 2 (Index 1) को Right Align करना
        if col == 1:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif col in (2, 5, 6):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # ✅ लॉकिंग लॉजिक
        if should_lock:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            
        self.table.setItem(row, col, item)
        return item

    def fill_row_from_Alias(self, row, editor):
        Alias = editor.text().strip()
        self.table.removeCellWidget(row, 0)

        if self.final_data is not None:
            match = self.final_data[self.final_data["Alias"].astype(str).str.lower() == Alias.lower()]
            if not match.empty:
                data = match.iloc[0]

                # 0: Item Name (Editable)
                self.table.setItem(row, 0, QTableWidgetItem(str(data["Item_Name"])))
                # 1: प्रति कार्टुन (Index 1) - Unlock & Right Align
                self.set_item_locked(row, 1, "", should_lock=False)
                # 2: Unit - Locked
                self.set_item_locked(row, 2, data.get("Unit", ""), should_lock=True)
                # 3: जम्मा कार्टुन - Unlock
                self.set_item_locked(row, 3, "", should_lock=False)
                # 4: गोदाम - Unlock
                self.set_item_locked(row, 4, "", should_lock=False)
                # 5: Part No - Locked
                p_no = str(data.get("Part_No", ""))
                if p_no.lower() == "none": p_no = ""
                self.set_item_locked(row, 5, p_no, should_lock=True)
                # 6: CN - Unlock
                self.set_item_locked(row, 6, "", should_lock=False)

                self.save_data_to_db()
                return

        self.table.setItem(row, 0, QTableWidgetItem(Alias))

    def delete_fully_empty_rows(self):
        """
        Sirf wahi row delete hogi:
        - jisme column 0–6 sab empty ho
        - agar CN (column-6) me value hai to row kabhi delete nahi hogi
        """
        for r in range(self.table.rowCount() - 1, -1, -1):
            # ✅ Agar CN me value hai → row safe
            cn_item = self.table.item(r, 6)
            if cn_item and cn_item.text().strip() != "":
                continue

            # 🔍 Check 0–5 columns
            all_empty = True
            for c in range(0, 6):  # 0 to 5 ONLY
                item = self.table.item(r, c)
                if item and item.text().strip() != "":
                    all_empty = False
                    break

            # 🗑️ Delete only if 0–5 empty AND CN empty
            if all_empty:
                self.table.removeRow(r)
    
    def refresh_part_no_from_item(self):
        if self.final_data is None or self.final_data.empty:
            return

        for r in range(self.table.rowCount()):
            item0 = self.table.item(r, 0)
            if not item0:
                continue

            item_name = item0.text().strip()
            if item_name == "":
                continue

            match = self.final_data[
                self.final_data["Item_Name"].astype(str).str.lower()
                == item_name.lower()
            ]

            if not match.empty:
                part_no = match.iloc[0].get("Part_No", "")

                # 🔥 None / "none" ko blank bana do
                if part_no is None or str(part_no).strip().lower() == "none":
                    part_no = ""

                self.set_item_locked(r, 5, part_no)

    # ---------------- EXPORT / PRINT ----------------
    def export_to_excel(self):
        data = []
        for r in range(self.table.rowCount()):
            row = [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(7)]
            if any(row):
                data.append(row)

        if not data:
            return

        df = pd.DataFrame(data, columns=[
            "Item Name", "Qty/Ctn", "Unit",
            "Total Ctn", "Godown", "Part No", "CN"
        ])

        path, _ = QFileDialog.getSaveFileName(self, "Save", "Godown_Stock.xlsx", "Excel (*.xlsx)")
        if path:
            df.to_excel(path, index=False)
        pass 

    def handle_print_preview(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self.print_document)
        preview.exec()
        pass
    
    def print_document(self, printer):
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)

        printer.setPageMargins(
            QMarginsF(20, 25, 20, 25),
            QPageLayout.Unit.Millimeter
        )

        document = QTextDocument()
        document.setDefaultFont(QFont("Segoe UI", 10))
        document.setHtml(self.build_print_html())

        document.print(printer)

    def build_print_html(self):
        headers = [self.table.horizontalHeaderItem(c).text()
                   for c in range(self.table.columnCount())]

        html = """
        <html>
        <head>
        <style>
            body {
                font-family: Segoe UI, Arial;
                font-size: 10pt;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                table-layout: fixed;
            }

            th, td {
                border: 1px solid black;
                padding: 4px 6px;
                vertical-align: middle;
            }

            td {
                white-space: nowrap;
            }

            .wrap {
                white-space: normal;
                word-wrap: break-word;
            }

            th {
                background-color: #f0f0f0;
                text-align: center;
                font-weight: bold;
            }

            col.c0 { width: 35%; }
            col.c1 { width: 10%; }
            col.c2 { width: 8%; }
            col.c3 { width: 12%; }
            col.c4 { width: 10%; }
            col.c5 { width: 15%; }
            col.c6 { width: 10%; }

            .left { text-align: left; }
            .right { text-align: right; }
            .center { text-align: center; }
        </style>
        </head>
        <body>

        <table>
            <colgroup>
                <col class="c0">
                <col class="c1">
                <col class="c2">
                <col class="c3">
                <col class="c4">
                <col class="c5">
                <col class="c6">
            </colgroup>

            <tr>
        """

        for h in headers:
            html += f"<th>{h}</th>"
        html += "</tr>"

        for r in range(self.table.rowCount()):
            has_data = False
            row_html = "<tr>"

            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                text = item.text() if item else ""
                if text.strip():
                    has_data = True

                if c == 0:
                    cls = "left wrap"   # only item name wraps
                elif c == 1:
                    cls = "right"
                elif c == 3:
                    cls = "left"
                else:
                    cls = "center"

                row_html += f'<td class="{cls}">{text}</td>'

            row_html += "</tr>"
            if has_data:
                html += row_html

        html += "</table></body></html>"
        return html
