import os
from src.ui.table_nav_mixin import ExcelTableMixin
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QLineEdit, QLabel, QHeaderView,
    QPushButton, QCompleter, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QAbstractItemView, QStyledItemDelegate, QSplitter, QDialog
)

from PyQt6.QtGui import QTextDocument, QPageSize, QPageLayout, QFont, QPainter, QPen, QColor, QFontMetrics
from PyQt6.QtCore import Qt, QEvent, QSettings, QSizeF, QMarginsF, QRect
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from difflib import SequenceMatcher
from src.logic.db_manager import get_db_manager, build_logical_name
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from src.ui.ui_helpers import pick_export_folder


class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except Exception as e:
            return super().__lt__(other)


# ── Tally-like completer: starts-with entries sorted to top ──────────────────
class _TallySortProxyModel(QSortFilterProxyModel):
    """Keeps starts-with matches at the top; contains matches below."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix = ""

    def set_prefix(self, prefix: str):
        self._prefix = prefix.lower()

    def lessThan(self, left, right):
        lv = left.data(Qt.ItemDataRole.DisplayRole) or ""
        rv = right.data(Qt.ItemDataRole.DisplayRole) or ""
        p = self._prefix
        l_starts = lv.lower().startswith(p)
        r_starts = rv.lower().startswith(p)
        if l_starts != r_starts:
            return l_starts  # starts-with items sort lower (come first)
        return lv.lower() < rv.lower()


class _TallyCompleter(QCompleter):
    """QCompleter that shows starts-with matches first, then contains."""
    def __init__(self, data_list, parent=None):
        self._data_list = [str(x) for x in data_list]
        # Build a standard model so we can re-sort on each keystroke
        self._src_model = QStandardItemModel()
        for item in self._data_list:
            self._src_model.appendRow(QStandardItem(item))

        self._proxy = _TallySortProxyModel()
        self._proxy.setSourceModel(self._src_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)

        super().__init__(self._proxy, parent)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        if parent:
            parent.textEdited.connect(self._on_text_edited)

    def _on_text_edited(self, text: str):
        p = text.lower()
        self._proxy.set_prefix(p)
        # Show starts-with + contains
        self._proxy.setFilterFixedString(text)
        self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self.complete()


def _enforce_match(editor: QLineEdit, text: str, data_list: list):
    """Reject the last typed character if the current text has no match at all.
    Mimics Tally behaviour: typing stops when nothing matches."""
    if not text:
        return
    tl = text.lower()
    for item in data_list:
        if tl in str(item).lower():   # contains check
            return                     # at least one match — allow
    # No match at all: strip the last character
    editor.blockSignals(True)
    editor.setText(text[:-1])
    editor.blockSignals(False)
    # Re-open the popup for the restored text.
    # We call _on_text_edited (not bare complete()) so the proxy filter
    # is updated to text[:-1] first — otherwise the popup would show empty
    # results (still filtered to the rejected text) and Qt's popup event
    # filter would intercept subsequent keypresses, bypassing this guard.
    completer = editor.completer()
    if completer and hasattr(completer, '_on_text_edited'):
        completer._on_text_edited(text[:-1])

class AutocompleteDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_ui = parent

    def createEditor(self, parent, option, index):
        col = index.column()
        if col == 0:  # S.N — never editable
            return None
        if col in (2, 3, 5):
            editor = QLineEdit(parent)
            editor.setFrame(False)

            data_list = []
            if col == 2:
                data_list = list(self.main_ui.party_mapping.keys())
            elif col == 3:
                data_list = self.main_ui.bank_list_data
            elif col == 5:
                data_list = self.main_ui.crm_list_data

            if data_list:
                # ── Tally-like completer: starts-with entries appear first ──
                completer = _TallyCompleter(data_list, editor)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setMaxVisibleItems(12)
                editor.setCompleter(completer)
                completer.popup().setMinimumWidth(350)

                # ── Tally-like typing guard: reject chars that have no match ──
                editor.textEdited.connect(
                    lambda text, e=editor, dl=data_list: _enforce_match(e, text, dl)
                )

            editor.installEventFilter(self)
            return editor
        return super().createEditor(parent, option, index)

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and isinstance(editor, QLineEdit):
            key = event.key()
            
            # Smart Excel Option A: Up/Down moves to next cell, UNLESS dropdown is visible
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                completer = getattr(editor, 'completer', lambda: None)()
                if completer and completer.popup() and completer.popup().isVisible():
                    return False # Let the dropdown handle the arrow key
                
                # Dropdown is hidden: Commit and move like Excel
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                
                table = self.main_ui.table
                r = table.currentRow()
                c = table.currentColumn()
                if key == Qt.Key.Key_Up and r > 0:
                    self.main_ui._nav_set_current(r - 1, c)
                elif key == Qt.Key.Key_Down and r < table.rowCount() - 1:
                    self.main_ui._nav_set_current(r + 1, c)
                return True
                
            # Left/Right: per spec, in Edit mode the cursor moves within text.
            # The delegate eventFilter only fires when a QLineEdit editor IS active,
            # which IS Edit mode — so Left/Right ALWAYS moves cursor, never navigates.
            # (Previously gated by _is_double_click which was unreliable due to
            # _reset_edit_mode firing from currentCellChanged during double-click.)
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                return False  # QLineEdit handles cursor movement natively
                
            # Excel: Enter commits and moves down
            elif key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                completer = getattr(editor, 'completer', lambda: None)()
                if completer and completer.popup() and completer.popup().isVisible():
                    return False # Let completer handle selection
                    
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                
                table = self.main_ui.table
                r = table.currentRow()
                c = table.currentColumn()
                if r < table.rowCount() - 1:
                    self.main_ui._nav_set_current(r + 1, c)
                return True
                
        return super().eventFilter(editor, event)

    def setModelData(self, editor, model, index):
        col = index.column()
        if col in (2, 3, 5):
            val = editor.text().strip()
            if not val:
                model.setData(index, "", Qt.ItemDataRole.EditRole)
                return

            data_list = []
            if col == 2:
                data_list = list(self.main_ui.party_mapping.keys())
            elif col == 3:
                data_list = self.main_ui.bank_list_data
            elif col == 5:
                data_list = self.main_ui.crm_list_data

            if data_list:
                val_lower = val.lower()
                exact_match = False
                for item in data_list:
                    if val_lower == str(item).lower():
                        val = item
                        exact_match = True
                        break

                if not exact_match:
                    contains_match = False
                    for item in sorted(str(x) for x in data_list):
                        if val_lower in item.lower():
                            val = item
                            contains_match = True
                            break
                    if not contains_match:
                        # Reject the edit — value not in the allowed list
                        return

            if col == 2:
                val_lower = val.lower()
                for alias, name in self.main_ui.party_mapping.items():
                    if alias.lower() == val_lower:
                        val = name
                        break

            model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)

    def setEditorData(self, editor, index):
        """Prevent auto-select-all on edit open. Qt calls selectAll() inside
        the editor's focusInEvent, which fires AFTER setEditorData — so
        deselect() here is immediately overwritten. Use QTimer.singleShot(0)
        to defer deselection until after the focusIn event completes."""
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, editor.deselect)        # Runs after focusInEvent
            QTimer.singleShot(0, lambda: editor.end(False))  # Cursor at end, no selection

    def destroyEditor(self, editor, index):
        self.main_ui._is_edit_mode = False   # Exit Mode 2 when editor closes
        super().destroyEditor(editor, index)

class ChequeListUI(ExcelTableMixin, QWidget):
    def __init__(self, company_path=None):
        super().__init__()
        
        # ================= BASIC =================
        self.db_path = ""
        self.company_path = ""
        self.db = get_db_manager()
        self.cheque_db_name = ""
        self.ledger_db_name = ""
        self.settings = QSettings("TallySync", "ChequeList")
        self.export_folder = self.settings.value("export_folder", "")
        self.bank_list_data = []
        self.crm_list_data = []
        self.party_mapping = {}
        # _is_edit_mode is initialised by ExcelTableMixin._init_excel_table()
        self.columns = [
            "S.N", "Date", "Party Name", "Bank",
            "Chq No.", "CRM", "Amount", "Cash/Bank", "Clear Date", "Narration"
        ]

        # ================= MAIN LAYOUT =================
        # Top bar is OUTSIDE the splitter so it always spans the full width.
        # Only the table area and bank list panel live inside the splitter.
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------- TOP BAR (full-width, fixed) ----------
        top_bar_widget = QWidget()
        top_bar_widget.setContentsMargins(0, 0, 0, 0)
        top_bar = QHBoxLayout(top_bar_widget)
        top_bar.setContentsMargins(4, 4, 4, 4)
        top_bar.setSpacing(6)

        # 1. Left Side: Clear Button + Search
        self.btn_clear = QPushButton("✅ Clear Chq Unhide")
        self.btn_clear.setObjectName("BtnClearChq")
        self.btn_clear.clicked.connect(self.toggle_clear_visibility)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self.apply_filter)

        # "Unclear Chq. Hide" — hides rows where Clear Date is empty
        self.btn_unclear_hide = QPushButton("⏳ Unclear Chq. Hide")
        self.btn_unclear_hide.setObjectName("BtnClearChq")
        self.btn_unclear_hide.setCheckable(True)
        self.btn_unclear_hide.clicked.connect(self.toggle_unclear_visibility)

        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.search_box)
        top_bar.addWidget(self.btn_unclear_hide)

        # 2. Middle: Summary Labels
        top_bar.addStretch()

        # Font size controlled via #ChqSummaryLabel in style.qss
        _sum_font = QFont()
        _sum_font.setBold(True)
        self.lbl_count = QLabel("Total No. of Chq.: 0")
        self.lbl_total = QLabel("Amount: 0.00")
        self.lbl_count.setObjectName("ChqSummaryLabel")
        self.lbl_total.setObjectName("ChqSummaryLabel")
        self.lbl_count.setFont(_sum_font)
        self.lbl_total.setFont(_sum_font)


        top_bar.addWidget(self.lbl_count)
        top_bar.addWidget(self.lbl_total)

        top_bar.addStretch()

        # 3. Right Side: Utility Buttons
        self.btn_set_location = QPushButton("📂 Set Location")
        self.btn_set_location.setObjectName("BtnOrange")
        self.btn_set_location.clicked.connect(self.set_export_location)

        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setObjectName("BtnBlue")
        self.btn_print.clicked.connect(self.print_table)

        self.btn_bank_list = QPushButton("🏦 Bank List")
        self.btn_bank_list.setCheckable(True)
        self.btn_bank_list.setObjectName("BtnBlue")
        self.btn_bank_list.clicked.connect(self.toggle_bank_list)

        self.btn_export = QPushButton("Excel")
        self.btn_export.setObjectName("BtnBlue")
        self.btn_export.clicked.connect(self.export_to_excel)

        top_bar.addWidget(self.btn_set_location)
        top_bar.addWidget(self.btn_print)
        top_bar.addWidget(self.btn_bank_list)
        top_bar.addWidget(self.btn_export)

        main_layout.addWidget(top_bar_widget)

        # ---------- SPLITTER (table | bank list) ----------
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)   # stretch=1 fills remaining height

        # ---------- LEFT: MAIN TABLE ONLY ----------
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.verticalHeader().hide()

        # Header settings — balanced column widths
        # S.N, Date, Party Name, Bank, Chq No., CRM, Amount, Cash/Bank, Clear Date, Narration
        _col_widths = [45, 95, 210, 140, 85, 110, 90, 75, 95, 160]
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        for i, w in enumerate(_col_widths):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(i, w)
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)  # Narration fills remaining space

        self.table.horizontalHeader().sectionClicked.connect(self.sort_table_safe)
        self.table.itemChanged.connect(self.on_item_changed)
        # Event filter is installed by _init_excel_table() below — do NOT add another.

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(8, 0, 0, 0)
        table_layout.addWidget(self.table)
        table_container.setMinimumWidth(300)

        self.splitter.addWidget(table_container)

        # Table navigation (Mode 1 / Mode 2) — ExcelTableMixin
        # _init_excel_table sets: DoubleClicked trigger, SingleSelection, blue
        # selection style, _NavResetDelegate, installEventFilter, cellDoubleClicked.
        # We then override the delegate with AutocompleteDelegate for autocomplete cols.
        self._init_excel_table(self.table)
        self.table.setItemDelegate(AutocompleteDelegate(self))
        # _init_excel_table already connected cellDoubleClicked — no duplicate needed.

        # ================= RIGHT (BANK LIST) =================
        self.right_container = QWidget()
        right_layout = QVBoxLayout(self.right_container)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        right_layout.addWidget(QLabel("<b>Bank Name List</b>"))

        self.bank_table = QTableWidget()
        self.bank_table.setColumnCount(3)
        self.bank_table.setHorizontalHeaderLabels(["SN", "Bank Name", "Count"])
        self.bank_table.verticalHeader().hide()
        self.bank_table.setColumnWidth(0, 40)
        self.bank_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bank_table.setColumnWidth(2, 60)
        self.bank_table.itemChanged.connect(self.handle_bank_change)
        # Capture old name before user starts editing a bank cell
        self.bank_table.currentItemChanged.connect(self._capture_pre_bank_name)
        self._pre_bank_name = ""

        right_layout.addWidget(self.bank_table)

        self.splitter.addWidget(self.right_container)
        self.right_container.setMinimumWidth(200)

        self.splitter.setSizes([800, 320])
        self.splitter.setStretchFactor(0, 1)    # Table grows with window
        self.splitter.setStretchFactor(1, 0)    # Bank list holds its size
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)

        # Initial loading and connections
        self.load_all_data()
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
    
    def toggle_unclear_visibility(self):
        """Hide/show rows where Clear Date is empty (unclear/pending cheques)."""
        hiding = self.btn_unclear_hide.isChecked()
        for r in range(self.table.rowCount()):
            clear_item = self.table.item(r, 8)
            has_date = clear_item and clear_item.text().strip()
            if hiding and not has_date:
                self.table.setRowHidden(r, True)
            elif not hiding:
                # Restore — respect the existing clear-chq-hide state
                is_clear_hiding = "Unhide" in self.btn_clear.text()
                if is_clear_hiding and has_date:
                    self.table.setRowHidden(r, True)
                else:
                    self.table.setRowHidden(r, False)
        self.btn_unclear_hide.setText(
            "✅ Unclear Shown" if not hiding else "⏳ Unclear Chq. Hide"
        )
        self.update_summary()

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
            self.btn_clear.setProperty("state", "inactive")
        else:
            self.btn_clear.setText("✅ Clear Chq Unhide")
            self.btn_clear.setProperty("state", "active")
        self.btn_clear.style().unpolish(self.btn_clear)
        self.btn_clear.style().polish(self.btn_clear)
            
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
        if not self.cheque_db_name: return
        conn = self.db.get_connection(self.cheque_db_name)
        if not conn: return
        cur = conn.cursor()
        try:
            # Build all rows first, then insert in one batch
            rows_to_insert = []
            for r in range(self.table.rowCount()):
                def txt(c, _r=r):
                    w = self.table.cellWidget(_r, c)
                    if w and isinstance(w, QLineEdit): return w.text().strip()
                    it = self.table.item(_r, c)
                    return it.text().strip() if it and it.text().strip() else None
                rows_to_insert.append((
                    txt(0), txt(1), txt(2), txt(3),
                    txt(4), txt(5), txt(6), txt(7), txt(8), txt(9)
                ))
            cur.execute("DELETE FROM cheques")
            if rows_to_insert:
                cur.executemany("INSERT INTO cheques VALUES (?,?,?,?,?,?,?,?,?,?)", rows_to_insert)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save cheques: {e}")
        self.update_summary()
        
    def _capture_pre_bank_name(self, current, previous):
        """Store the bank name before the user starts editing, so we can revert if needed."""
        if current and current.column() == 1:
            self._pre_bank_name = current.text().strip()

    # ================= BANK LIST =================
    def handle_bank_change(self, item):
        if item.column() != 1: return

        total_row_idx = self.bank_table.rowCount() - 1
        if item.row() == total_row_idx: return  # Ignore edits on total row

        new_name = item.text().strip()
        old_name = self._pre_bank_name

        # If the bank name was cleared (user deleted it), check if it's still in use
        if not new_name and old_name:
            # Count how many cheque rows reference this bank
            used_count = 0
            for r in range(self.table.rowCount()):
                bank_item = self.table.item(r, 3)
                if bank_item and bank_item.text().strip() == old_name:
                    used_count += 1
            if used_count > 0:
                # Revert — cannot remove a bank that is in use
                self.bank_table.blockSignals(True)
                item.setText(old_name)
                self.bank_table.blockSignals(False)
                QMessageBox.warning(
                    self, "Cannot Remove Bank",
                    f"'{old_name}' is used in {used_count} cheque(s).\nClear those cheques first before removing this bank."
                )
                return

        # DB Update Logic (Export explicit list items to bank_list)
        conn = self.db.get_connection(self.cheque_db_name)
        if not conn: return
        cur = conn.cursor()
        try:
            rows_to_insert = []
            save_idx = 1
            self.bank_list_data = []
            for r in range(total_row_idx):
                it = self.bank_table.item(r, 1)
                if it and it.text().strip():
                    rows_to_insert.append((str(save_idx), it.text().strip()))
                    self.bank_list_data.append(it.text().strip())
                    save_idx += 1
            cur.execute("DELETE FROM bank_list")
            if rows_to_insert:
                cur.executemany("INSERT INTO bank_list VALUES (?, ?)", rows_to_insert)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save bank_list: {e}")

        self.ensure_bank_row_capacity()

    # ================= SUMMARY =================
    def update_summary(self):
        """Count and sum ALL uncleared pending cheques — irrespective of row visibility.

        The summary always reflects the true total of pending cheques in the
        database, regardless of which hide/show buttons are currently active.

        A row counts when:
          - Party Name (col 2) is filled  → it's a real entry, not a buffer row
          - Clear Date (col 8) is blank   → cheque is still pending / uncleared
        """
        total = 0.0
        count = 0
        for r in range(self.table.rowCount()):
            # NOTE: isRowHidden is intentionally NOT checked here.
            # The summary always shows the full picture regardless of filters.

            # Skip rows that are already cleared
            clear_item = self.table.item(r, 8)
            if clear_item and clear_item.text().strip():
                continue

            # A row "exists" when Party Name is filled
            party = self.table.item(r, 2)
            if not (party and party.text().strip()):
                continue

            count += 1
            amt = self.table.item(r, 6)
            try:
                total += float(amt.text().replace(",", "")) if amt and amt.text() else 0
            except Exception:
                pass

        self.lbl_count.setText(f"Total No. of Chq.: {count}")
        self.lbl_total.setText(f"Amount: {total:,.2f}")
        self.update_bank_counts()


    def generate_sn(self, row_index):
        return f"{row_index + 1:04d}"

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

    def ensure_cheque_schema(self):
        cols = self.db.get_table_columns(self.cheque_db_name, "cheques")
        if "clear_date" not in cols:
            self.db.add_column(self.cheque_db_name, "cheques", "clear_date", "NVARCHAR(MAX)")
        if "narration" not in cols:
            self.db.add_column(self.cheque_db_name, "cheques", "narration", "NVARCHAR(MAX)")

    def sync_cheque_rows(self):
        """Compact the cheque table: remove blank rows, preserve order and SNs.

        Normal case (sequential SNs 1..N from a previous save):
            Behaviour is identical to before — rows keep their sequential SNs.

        Year-End case (pending cheques with non-sequential SNs, e.g. 0023, 0047):
            Their original SNs are preserved so the user can see which cheques
            were carried forward from the previous year.  Empty buffer rows below
            get new SNs starting from 1, skipping any numbers already in use.
        """
        self.table.blockSignals(True)
        try:
            data = []  # [(existing_sn_int | None, row_values_list)]

            # 1. Collect data rows with their existing SN values
            for r in range(self.table.rowCount()):
                def val(c, _r=r):
                    w = self.table.cellWidget(_r, c)
                    if w and isinstance(w, QLineEdit): return w.text().strip()
                    it = self.table.item(_r, c)
                    return it.text().strip() if it and it.text().strip() else ""

                row = [val(c) for c in range(10)]
                if any(v.strip() for v in row[1:]):
                    try:
                        existing_sn = int(row[0])
                    except (ValueError, TypeError):
                        existing_sn = None
                    data.append((existing_sn, row))

            # Track SN integers already claimed by data rows so buffer rows skip them
            used_sns = {sn for sn, _ in data if sn is not None}
            _next_ctr = [1]  # mutable counter for closure

            def _next_free():
                while _next_ctr[0] in used_sns:
                    _next_ctr[0] += 1
                v = _next_ctr[0]
                used_sns.add(v)
                _next_ctr[0] += 1
                return v

            # 2. Re-insert data rows, keeping original SNs where present
            self.table.setRowCount(0)
            for existing_sn, row_data in data:
                idx = self.table.rowCount()
                self.table.insertRow(idx)
                for c, v in enumerate(row_data):
                    if c == 0:
                        sn_val = existing_sn if existing_sn is not None else _next_free()
                        cell_text = f"{sn_val:04d}"
                    else:
                        cell_text = v

                    item = QTableWidgetItem(cell_text)
                    if c == 0:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    elif c == 6:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif c == 7:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(idx, c, item)

            # 3. Add empty buffer rows with new sequential SNs (start from 1, skip used)
            target = max(50, len(data) + 10)
            while self.table.rowCount() < target:
                idx = self.table.rowCount()
                self.table.insertRow(idx)
                sn_val = _next_free()
                for c in range(10):
                    if c == 0:
                        item = QTableWidgetItem(f"{sn_val:04d}")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        self.table.setItem(idx, c, item)
                    else:
                        item = QTableWidgetItem("")
                        if c == 6:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        elif c == 7:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table.setItem(idx, c, item)
        finally:
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
        try:
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
        finally:
            self.bank_table.blockSignals(False)

    def clear_completed_cheques(self):
        reply = QMessageBox.question(self, "Confirm Clear", "Kya aap saare 'C' (Cleared) cheques hatana chahte hain?", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.execute_query(self.cheque_db_name, "DELETE FROM cheques WHERE status = 'C'", fetch=False)
            self.load_all_data()

    def set_company_path(self, path):
        self.company_path = path
        self.db_path = os.path.join(path, "chq_list.db")  # Legacy
        company_name = os.path.basename(path)
        self.cheque_db_name = build_logical_name(company_name, company_path=path)
        self.ledger_db_name = build_logical_name(company_name, company_path=path)

        # 3. Setup Cheque DB
        self.db.ensure_database_exists(self.cheque_db_name, path)
        self.db.ensure_table(self.cheque_db_name, "cheques", """
            CREATE TABLE cheques (
                sn NVARCHAR(MAX), date NVARCHAR(MAX), party NVARCHAR(MAX), bank NVARCHAR(MAX),
                chq_no NVARCHAR(MAX), crm NVARCHAR(MAX), amount NVARCHAR(MAX),
                status NVARCHAR(MAX), clear_date NVARCHAR(MAX), narration NVARCHAR(MAX)
            )
        """)
        self.db.ensure_table(self.cheque_db_name, "bank_list", """
            CREATE TABLE bank_list (
                sn NVARCHAR(MAX), bank_name NVARCHAR(MAX)
            )
        """)
        self.ensure_cheque_schema()
        self.load_all_data()

    def load_all_data(self):
        if not self.cheque_db_name: return
        conn = self.db.get_connection(self.cheque_db_name)
        if not conn: return
        cursor = conn.cursor()
        
        # Bank list loading logic
        cursor.execute("SELECT * FROM bank_list")
        bnks = cursor.fetchall()
        self.bank_table.blockSignals(True)
        try:
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
        finally:
            self.bank_table.blockSignals(False)
        self.bank_list_data = [b[1] for b in bnks]
        
        # Cheque list loading logic
        cursor.execute("SELECT * FROM cheques")
        chqs = cursor.fetchall()
        
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(chqs))
            for r, row in enumerate(chqs):
                for c, v in enumerate(row):
                    if c >= 10: break
                    val = "" if v in (None, "None") else str(v)
                    
                    if c == 0:
                        try:
                            val = f"{int(val):04d}"
                        except Exception:
                            val = f"{r + 1:04d}"
                    
                    item = QTableWidgetItem(val)
                    if c == 0:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    elif c == 6:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif c == 7:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(r, c, item)
        finally:
            self.table.blockSignals(False)
        
        # --- 3. Final Triggers (सही क्रम) ---
        self.sync_cheque_rows()      # रोज़ को सिंक करें
        self.apply_initial_hide()    # पहले डेटा छुपाएं (App Start Hide)
        self.update_summary()        # फिर समरी कैलकुलेट करें (ताकि छुपा हुआ डेटा न गिना जाए)
        self.update_bank_counts()    # बैंक काउंट अपडेट करें
        
        # Column widths already set in setup_ui via balanced _col_widths
    
    def showEvent(self, event):
        super().showEvent(event)
        self._reload_dropdown_data()
        self.update_summary()
    
    def _reload_dropdown_data(self):
        """Refresh party names, CRM, and bank list from SQL Server.
        Called every time the tab becomes visible."""
        if not self.ledger_db_name:
            return
        
        # 1. CRM Data
        from src.ui.settings import load_crm_list
        self.crm_list_data = load_crm_list(self.company_path)
        
        # 2. Party Mapping (Sundry Debtors: Alias + Name searchable)
        self.party_mapping = {}
        try:
            l_conn = self.db.get_connection(self.ledger_db_name)
            if l_conn:
                l_cursor = l_conn.cursor()
                l_cursor.execute("SELECT Alias, Name FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
                for alias, name in l_cursor.fetchall():
                    name_str = str(name).strip() if name and str(name).strip().lower() != "none" else ""
                    alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
                    if alias_str:
                        self.party_mapping[alias_str] = name_str
                    if name_str:
                        self.party_mapping[name_str] = name_str
        except Exception as e:
            print("[CHEQUE] Error loading ledger:", e)
        
        # 3. Bank list refresh
        try:
            conn = self.db.get_connection(self.cheque_db_name)
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT bank_name FROM bank_list")
                self.bank_list_data = [r[0] for r in cursor.fetchall() if r[0]]
        except Exception:
            pass
    
    def apply_initial_hide(self):
        """App start logic to hide cleared rows"""
        for r in range(self.table.rowCount()):
            clear_date_item = self.table.item(r, 8)
            if clear_date_item and clear_date_item.text().strip():
                self.table.setRowHidden(r, True)
                
    def ensure_bank_row_capacity(self):
        self.bank_table.blockSignals(True)
        try:
            total_row_idx = self.bank_table.rowCount() - 1
            filled = 0
            for r in range(total_row_idx):
                it = self.bank_table.item(r, 1)
                if it and it.text().strip():
                    filled += 1

            # Keep at least 4 empty rows above Total
            empty_rows = total_row_idx - filled
            if empty_rows < 4:
                for _ in range(5):
                    self.bank_table.insertRow(total_row_idx)
                
                # Recalculate SNs and update total_row_idx
                total_row_idx = self.bank_table.rowCount() - 1
                for r in range(total_row_idx):
                    self.bank_table.setItem(r, 0, QTableWidgetItem(str(r+1)))
        finally:
            self.bank_table.blockSignals(False)

    def set_export_location(self):
        """Pick an export folder via the shared helper (native dialog)."""
        self.export_folder = pick_export_folder(
            parent=self,
            settings=self.settings,
            settings_key="export_folder",
            current_folder=self.export_folder,
        )

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
            QMarginsF(5, 3, 5, 3),
            QPageLayout.Unit.Millimeter
        )

        from PyQt6.QtPrintSupport import QPrintPreviewDialog
        from PyQt6.QtWidgets import QToolBar

        self._cheque_print_pages = []  # populated during first paintRequested
        self._cheque_printer = printer

        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self._paint_cheque_table)

        # Override the internal "Print" toolbar action with our page-range-aware handler.
        # QPrintPreviewDialog caches rendered pages and sends them directly — it does NOT
        # re-call paintRequested with fromPage/toPage, so we intercept the action here.
        self._preview_ref = preview
        for toolbar in preview.findChildren(QToolBar):
            for action in toolbar.actions():
                tip = (action.toolTip() or "").lower()
                txt = (action.text() or "").replace("&", "").strip().lower()
                if tip == "print" or txt == "print":
                    action.triggered.disconnect()
                    action.triggered.connect(self._custom_print_from_preview)
                    break

        preview.resize(900, 680)
        preview.exec()

    def _custom_print_from_preview(self):
        """Opened when user clicks Print inside QPrintPreviewDialog.
        Bypasses the cached-page mechanism and renders the selected page
        range directly to the physical printer."""
        total = len(self._cheque_print_pages) if self._cheque_print_pages else 1
        printer = self._cheque_printer

        dlg = QPrintDialog(printer, self._preview_ref)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange)
        dlg.setMinMax(1, total)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Render only the selected page range directly to the physical printer
        fp = printer.fromPage()   # 1-indexed; 0 = all
        tp = printer.toPage()
        if fp == 0 or tp == 0:
            start_pg, end_pg = 0, total - 1
        else:
            start_pg = max(0, fp - 1)
            end_pg   = min(tp - 1, total - 1)

        self._paint_cheque_table(printer, page_range=(start_pg, end_pg))

    def _paint_cheque_table(self, printer, page_range=None):
        """Draw the cheque table directly using QPainter for pixel-perfect A4 Landscape output.
        page_range: (start, end) 0-indexed inclusive. None = all pages (preview mode)."""
        painter = QPainter()
        if not painter.begin(printer):
            return

        page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        page_w = page_rect.width()
        page_h = page_rect.height()

        # --- Fonts (use painter.fontMetrics for PRINTER DPI measurements) ---
        title_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        header_font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        cell_font = QFont("Segoe UI", 10)

        # Measure using painter's coordinate system (printer DPI, not screen DPI)
        painter.setFont(title_font)
        title_height = int(painter.fontMetrics().height() * 2.2)

        painter.setFont(header_font)
        header_height = int(painter.fontMetrics().height() * 1.8)

        painter.setFont(cell_font)
        fm_cell = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.6)
        padding = int(fm_cell.averageCharWidth() * 1.2)

        # --- Collect visible data rows first (needed for auto-fit widths) ---
        data_rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            def val(c, _r=r):
                w = self.table.cellWidget(_r, c)
                if w and isinstance(w, QLineEdit): return w.text().strip()
                it = self.table.item(_r, c)
                return it.text().strip() if it and it.text().strip() else ""
            row_data = [val(c) for c in range(10)]
            if any(v.strip() for v in row_data[1:]):
                data_rows.append(row_data)

        # --- Auto-fit column widths based on content ---
        # Each column is sized to fit its widest text (header or data cell),
        # then all widths are scaled proportionally to fill the full page width.
        painter.setFont(header_font)
        fm_h = painter.fontMetrics()
        painter.setFont(cell_font)
        fm_c = painter.fontMetrics()

        raw_widths = []
        for c in range(len(self.columns)):
            max_w = fm_h.horizontalAdvance(self.columns[c]) + 2 * padding
            for rd in data_rows:
                w = fm_c.horizontalAdvance(rd[c]) + 2 * padding
                if w > max_w:
                    max_w = w
            raw_widths.append(max(max_w, padding * 3))  # enforce a minimum

        total_raw = sum(raw_widths) or 1
        col_widths = [int(page_w * w / total_raw) for w in raw_widths]
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

        # --- Pre-calculate pages (pass 1) ---
        # Simulate the layout to know which rows land on which page,
        # so we can honour printer.fromPage() / printer.toPage() from the
        # page-range selector in QPrintPreviewDialog's print dialog.
        pages = []          # pages[i] = list of row_data for logical page i
        current_page = []

        # Page 0 has title + header; subsequent pages have header only
        avail_h_p0 = page_h - title_height - header_height
        avail_h    = page_h - header_height

        used = 0
        avail = avail_h_p0
        for row_data in data_rows:
            if used + row_height > avail:
                pages.append(current_page)
                current_page = []
                used = 0
                avail = avail_h
            current_page.append(row_data)
            used += row_height
        if current_page or not pages:
            pages.append(current_page)

        total_pages = len(pages)

        # Store pages so _custom_print_from_preview knows the total count
        self._cheque_print_pages = pages

        # Determine which pages to render
        # page_range=(start, end) is passed by _custom_print_from_preview (0-indexed).
        # When called from QPrintPreviewDialog (preview mode), page_range=None → all pages.
        if page_range is None:
            start_pg, end_pg = 0, total_pages - 1
        else:
            start_pg, end_pg = page_range[0], min(page_range[1], total_pages - 1)

        # --- Render selected pages (pass 2) ---
        first = True
        for pg_idx in range(start_pg, end_pg + 1):
            if not first:
                printer.newPage()
            first = False

            y = 0
            if pg_idx == 0:          # Title only on the first logical page
                y = draw_title(y)
            y = draw_header(y)

            for row_data in pages[pg_idx]:
                y = draw_row(y, row_data)

        painter.end()



    # ── ExcelTableMixin overrides ────────────────────────────────────────────

    def _excel_on_double_click(self, row, col):
        """Col 0 (S.N.) is never editable — skip it; delegate to mixin for all other cols."""
        if col == 0:
            return
        super()._excel_on_double_click(row, col)

    def _excel_on_printable_key(self, row, col, text):
        """Col 0 (S.N.) is never editable — skip it; delegate to mixin for all other cols."""
        if col == 0:
            return False
        return super()._excel_on_printable_key(row, col, text)

    # kept for backward-compat with any stale signal connections
    def _reset_edit_mode(self, cr=None, cc=None, pr=None, pc=None):
        pass
    def _on_selection_changed(self):
        pass

