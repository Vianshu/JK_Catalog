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
        self.settings = QSettings("TallySync", "GodownList")
        self.export_folder = self.settings.value("export_folder", "")
        self.final_data = None  # Will be loaded from final_data.db
        self.company_path = ""
        self.init_ui()
        self.change_data_folder(data_folder_path, final_data_df)

    def change_data_folder(self, company_path, final_data_df=None):
        if not company_path: return
        self.company_path = company_path
        self.db_path = os.path.join(company_path, "godown_stock.db")
        
        # Load product data from final_data.db for autocomplete
        self.load_final_data_from_db(company_path)
        
        self.init_db()
        
        # Safety check: Only clear table if it was initialized
        if hasattr(self, 'table'):
            self.table.setRowCount(0) 
            self.load_data_from_db()
            self.update_completer()
            self.ensure_minimum_rows(200)

    # ---------------- LOAD PRODUCT DATA ----------------
    def load_final_data_from_db(self, company_path):
        """Load Alias, Item_Name, Unit, Part_No from final_data.db for autocomplete"""
        final_db = os.path.join(company_path, "final_data.db")
        print(f"[GODOWN] Looking for final_data.db at: {final_db}")
        if not os.path.exists(final_db):
            print(f"[GODOWN] final_data.db NOT FOUND")
            self.final_data = None
            return
        
        try:
            conn = sqlite3.connect(final_db)
            # Use bracket-quoted column names to match catalog table creation
            query = "SELECT [Alias], [Item_Name], [Unit], [Part_No] FROM catalog"
            self.final_data = pd.read_sql_query(query, conn)
            conn.close()
            print(f"[GODOWN] Loaded {len(self.final_data)} rows from final_data.db")
            print(f"[GODOWN] Columns: {list(self.final_data.columns)}")
            if not self.final_data.empty:
                print(f"[GODOWN] Sample Alias: {self.final_data['Alias'].head(3).tolist()}")
        except Exception as e:
            print(f"[GODOWN] Failed to load final_data.db: {e}")
            self.final_data = None

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
                alias_list = self.final_data["Alias"].dropna().astype(str).tolist()
                # Filter out empty strings
                alias_list = [a for a in alias_list if a.strip() and a.strip().lower() != 'none']
                print(f"[GODOWN] Completer created with {len(alias_list)} aliases")
                self.completer = QCompleter(alias_list)
                self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
            else:
                print(f"[GODOWN] 'Alias' column NOT found in final_data. Columns: {list(self.final_data.columns)}")
        else:
            print(f"[GODOWN] final_data is None or empty, no completer created")

    # ---------------- UI ----------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        btn_set_location = QPushButton("📂 Set Location")
        btn_excel = QPushButton("📥 Excel डाउनलोड")
        btn_print = QPushButton("🖨️ प्रिंट प्रिव्यू")
        btn_save = QPushButton("💾 Save & Sort")

        btn_set_location.clicked.connect(self.set_export_location)
        btn_excel.clicked.connect(self.export_to_excel)
        btn_print.clicked.connect(self.handle_print_preview)
        btn_save.clicked.connect(self.manual_save_and_sort)

        top.addWidget(btn_set_location)
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

    # ---------------- EVENT FILTER ----------------
    def eventFilter(self, source, event):
        if source == self.table and event.type() == QEvent.Type.KeyPress:
            row = self.table.currentRow()
            col = self.table.currentColumn()

            # F2 or typing in Alias col (0)
            if col == 0:
                text = event.text()
                if event.key() == Qt.Key.Key_F2 or (text and text.isprintable()):
                    self.start_Alias_search(row, col)
                    if text and text.isprintable() and event.key() != Qt.Key.Key_F2:
                        editor = self.table.cellWidget(row, col)
                        if isinstance(editor, QLineEdit): editor.setText(text)
                    return True

            # Block non-numeric input for column 1 (प्रति कार्टुन)
            if col == 1:
                text = event.text()
                if text and text.isprintable():
                    # Allow digits, dot, comma, minus only
                    if not text in "0123456789.,-":
                        return True  # Block the key

            # Enter Navigation
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                next_row = row
                next_col = col + 1

                if col == self.table.columnCount() - 1:
                    next_row = row + 1
                    next_col = 0
                
                if next_row < self.table.rowCount():
                    self.table.setCurrentCell(next_row, next_col)
                    self.table.editItem(self.table.currentItem())
                
                return True

        return super().eventFilter(source, event)
    
    def create_table_item(self, text, alignment=Qt.AlignmentFlag.AlignLeft, locked=False):
        """Create a new table item with alignment and lock properties"""
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        
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
                
                # 1. Set Item Name (from Name column, not Alias)
                self.table.setItem(row, 0, self.create_table_item(data["Item_Name"]))
                
                # 2. Unit - auto-fill and lock
                self.table.setItem(row, 2, self.create_table_item(
                    data.get("Unit", ""), Qt.AlignmentFlag.AlignCenter, True))
                
                # 3. Part No - auto-fill and lock
                p_no = str(data.get("Part_No", ""))
                if p_no.lower() == "none": p_no = ""
                self.table.setItem(row, 5, self.create_table_item(
                    p_no, Qt.AlignmentFlag.AlignCenter, True))
                
                # 4. Set remaining columns as editable (if empty)
                if not self.table.item(row, 1):
                    self.set_item_locked(row, 1, "", should_lock=False)
                if not self.table.item(row, 3):
                    self.set_item_locked(row, 3, "", should_lock=False)
                if not self.table.item(row, 4):
                    self.set_item_locked(row, 4, "", should_lock=False)
                if not self.table.item(row, 6):
                    self.set_item_locked(row, 6, "", should_lock=False)

                # 5. Move cursor to "प्रति कार्टुन" (col 1)
                self.table.setCurrentCell(row, 1)
                self.table.setFocus()
                self.table.editItem(self.table.item(row, 1))
                
                self.save_data_to_db()
                return

        # If no match found, keep Alias text as Item Name
        self.table.setItem(row, 0, self.create_table_item(Alias))
        self.table.setCurrentCell(row, 1)
        self.table.setFocus()
        
        if not self.table.item(row, 1):
            self.set_item_locked(row, 1, "", should_lock=False)
        self.table.editItem(self.table.item(row, 1))
    
    def ensure_minimum_rows(self, min_rows=200):
        """Ensure at least min_rows rows exist in the table"""
        current_rows = self.table.rowCount()
        if current_rows < min_rows:
            self.table.setRowCount(min_rows)
            
    def handle_item_changed(self, item):
        row = item.row()
        col = item.column()
        text = item.text().strip()

        self.table.blockSignals(True)

        # Column 1 (प्रति कार्टुन) - Right align + numeric validation
        if col == 1:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if text:
                val = text.replace(",", "").replace(".", "").replace("-", "")
                if val and not val.isdigit():
                    QMessageBox.warning(self, "Invalid Input", "कृपया केवल संख्या (numbers) लिखें।")
                    item.setText("")

        # If item name cleared, clear all other columns
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
        if len(rows) > self.table.rowCount():
            self.table.setRowCount(len(rows))
        for r, data in enumerate(rows):
            for c, val in enumerate(data):
                align = Qt.AlignmentFlag.AlignLeft
                is_locked = False
                
                if c == 1: align = Qt.AlignmentFlag.AlignRight # प्रति कार्टुन
                if c in (2, 5, 6): align = Qt.AlignmentFlag.AlignCenter # Unit, PartNo, CN
                if c in (2, 5): is_locked = True # Unit and Part No locked
                
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
            # Refresh Part No from final_data
            self.refresh_part_no_from_item()

            # Sort by Part No (Column 5)
            self.table.sortItems(5, Qt.SortOrder.AscendingOrder)

            # Delete empty rows
            self.delete_fully_empty_rows()

            # Ensure at least 200 rows
            self.ensure_minimum_rows(200)

        except Exception as e:
            print(f"Error during save/sort: {e}")
        
        self.table.blockSignals(False)
        self.save_data_to_db()
        QMessageBox.information(self, "Saved", "Data Saved & Sorted Successfully")
    
    # ---------------- CELL LOGIC ----------------
    def set_item_locked(self, row, col, value, should_lock=True):
        """Set a cell value with proper alignment and lock state"""
        item = QTableWidgetItem(str(value))
        
        if col == 1:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif col in (2, 5, 6):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

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
                # 1: प्रति कार्टुन - Unlock & Right Align
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
        """Delete rows where all columns 0-6 are empty"""
        for r in range(self.table.rowCount() - 1, -1, -1):
            # If CN has value, keep row
            cn_item = self.table.item(r, 6)
            if cn_item and cn_item.text().strip() != "":
                continue

            # Check columns 0-5
            all_empty = True
            for c in range(0, 6):
                item = self.table.item(r, c)
                if item and item.text().strip() != "":
                    all_empty = False
                    break

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

                if part_no is None or str(part_no).strip().lower() == "none":
                    part_no = ""

                self.set_item_locked(r, 5, part_no)

    # ---------------- EXPORT / PRINT ----------------
    def set_export_location(self):
        start_dir = self.export_folder if self.export_folder and os.path.exists(self.export_folder) else ""
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder", start_dir)
        if folder:
            self.export_folder = folder
            self.settings.setValue("export_folder", folder)
            QMessageBox.information(self, "Location Set", f"Export folder saved to:\n{folder}")

    def export_to_excel(self):
        if not hasattr(self, 'export_folder') or not self.export_folder:
            QMessageBox.warning(self, "Set Location", "Please set an export location first using 'Set Location' button.")
            return

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

        company_name = "Unknown"
        if hasattr(self, "db_path") and self.db_path:
            company_path = os.path.dirname(self.db_path)
            company_name = os.path.basename(company_path.strip(r"\/"))
            import re
            company_name = re.sub(r'[\\/:*?"<>|]', '_', company_name)
            
        filename = f"Godown_Stock_{company_name}.xlsx"
        path = os.path.join(self.export_folder, filename)

        try:
            writer = pd.ExcelWriter(path, engine='xlsxwriter')
            df.to_excel(writer, index=False, sheet_name='Godown Stock')
            
            worksheet = writer.sheets['Godown Stock']
            (max_row, max_col) = df.shape
            
            if max_row > 0:
                worksheet.autofilter(0, 0, max_row, max_col - 1)
                for i, cname in enumerate(df.columns):
                    max_len = max(
                        df[cname].astype(str).map(len).max() if not df[cname].empty else 0,
                        len(str(cname))
                    ) + 2
                    worksheet.set_column(i, i, max_len)
            
            writer.close()
            if os.name == 'nt':
                os.startfile(path)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export Excel:\n{str(e)}")

    def handle_print_preview(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        printer.setPageMargins(
            QMarginsF(12, 12, 12, 12),
            QPageLayout.Unit.Millimeter
        )
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self.paint_table)
        preview.exec()

    def paint_table(self, printer):
        """Draw the table directly using QPainter for pixel-perfect A4 output."""
        painter = QPainter()
        if not painter.begin(printer):
            return

        page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        page_w = page_rect.width()
        page_h = page_rect.height()

        # --- Fonts (use painter.fontMetrics for PRINTER DPI measurements) ---
        header_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        cell_font = QFont("Segoe UI", 9)

        # Measure using painter's coordinate system (printer DPI, not screen DPI)
        painter.setFont(header_font)
        fm_header = painter.fontMetrics()
        header_height = int(fm_header.height() * 1.8)

        painter.setFont(cell_font)
        fm_cell = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.6)
        padding = int(fm_cell.averageCharWidth() * 1.5)

        # --- Column widths as fractions of full page width ---
        col_ratios = [0.32, 0.10, 0.08, 0.15, 0.10, 0.15, 0.10]
        col_widths = [int(page_w * r) for r in col_ratios]
        col_widths[-1] = page_w - sum(col_widths[:-1])

        headers = [self.table.horizontalHeaderItem(c).text()
                   for c in range(self.table.columnCount())]

        # --- Collect data rows (skip fully empty) ---
        data_rows = []
        for r in range(self.table.rowCount()):
            row_data = []
            has_data = False
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                text = item.text() if item else ""
                if text.strip():
                    has_data = True
                row_data.append(text)
            if has_data:
                data_rows.append(row_data)

        # --- Alignment per column ---
        alignments = [
            Qt.AlignmentFlag.AlignLeft,      # Item Name
            Qt.AlignmentFlag.AlignRight,      # Qty/Ctn
            Qt.AlignmentFlag.AlignHCenter,    # Unit
            Qt.AlignmentFlag.AlignLeft,       # Total Ctn
            Qt.AlignmentFlag.AlignHCenter,    # Godown
            Qt.AlignmentFlag.AlignHCenter,    # Part No
            Qt.AlignmentFlag.AlignHCenter,    # CN
        ]

        pen = QPen(QColor(0, 0, 0), 2)

        def draw_header(y):
            painter.setFont(header_font)
            painter.setPen(pen)
            x = 0
            for c, hdr in enumerate(headers):
                rect = QRect(x, y, col_widths[c], header_height)
                painter.fillRect(rect, QColor(220, 220, 220))
                painter.drawRect(rect)
                text_rect = QRect(x + padding, y, col_widths[c] - 2 * padding, header_height)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, hdr)
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

        # --- Render pages ---
        y = 0
        y = draw_header(y)

        for row_data in data_rows:
            if y + row_height > page_h:
                printer.newPage()
                y = 0
                y = draw_header(y)
            y = draw_row(y, row_data)

        painter.end()

