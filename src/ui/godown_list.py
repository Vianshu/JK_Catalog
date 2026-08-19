import os
from datetime import date as _date
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from src.logic.db_manager import get_db_manager, build_logical_name
from src.ui.table_nav_mixin import ExcelTableMixin, UniversalCellDelegate
from src.ui.ui_helpers import pick_export_folder

# ── Part No Override Mapping ──────────────────────────────────────────────────
# Item names that should display a fixed Part No in the Godown List,
# overriding whatever Tally / stock_items returns.
PART_NO_OVERRIDE = {
    "super stick 100gm":  "col-1",
    "super stick 250gm":  "col-2",
    "super stick 500gm":  "col-3",
    "super stick 1kg":    "col-4",
    "super stick 2 kg":   "col-5",
    "super stick 5 kg":   "col-6",
    "super stick 10 kg":  "col-7",
    "super stick 20 kg":  "col-8",
    "super stick 50 kg":  "col-9",
}

# ── CN Blank Prefixes ─────────────────────────────────────────────────────────
# Rows whose Part No starts with any of these prefixes (case-insensitive)
# get a blank CN value and are excluded from sequential numbering.
CN_BLANK_PREFIXES = ("COL", "GI P", "JALI", "LDR", "SDC")

# CN numbers that must never be assigned to any row (culturally/business reserved)
_EXCLUDED_CNS = frozenset({6, 9, 66, 69, 86, 89, 98, 99})


def _is_cn_excluded(part_no: str) -> bool:
    """Return True if this row's Part No means it should have a blank CN.
    Matching is case-insensitive so 'col-1', 'GI P ...', etc. all match."""
    if not part_no:
        return False
    p = part_no.strip().upper()
    return any(p.startswith(prefix.upper()) for prefix in CN_BLANK_PREFIXES)


# Pre-compute a space-free dictionary for robust matching
_CLEAN_PART_NO_OVERRIDE = {k.replace(" ", ""): v for k, v in PART_NO_OVERRIDE.items()}

def _apply_part_no_override(item_name: str, current_part_no: str) -> str:
    """Return the overridden Part No if the item name is in PART_NO_OVERRIDE,
    otherwise return the original value. Ignores spaces for robust matching."""
    clean_key = item_name.strip().lower().replace(" ", "")
    return _CLEAN_PART_NO_OVERRIDE.get(clean_key, current_part_no)


class _GodownSortProxyModel(QSortFilterProxyModel):
    """Proxy model for the Godown col-0 completer.

    Sorts the dropdown so that **starts-with** matches appear at the top
    and **contains** matches appear below them — identical to Tally's
    autocomplete behaviour.  Without this, Qt orders results by their
    original position in the source list, which means items starting with
    a completely different letter can float to the top just because they
    contain the typed letter somewhere in the middle.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_prefix(self, text: str):
        self._prefix = text.lower()
        self.invalidate()          # force re-sort

    def filterAcceptsRow(self, source_row, source_parent):
        """Accept rows that contain the current prefix (case-insensitive)."""
        idx = self.sourceModel().index(source_row, 0, source_parent)
        text = self.sourceModel().data(idx, Qt.ItemDataRole.DisplayRole) or ""
        return self._prefix in text.lower()

    def lessThan(self, left, right):
        """Starts-with wins; within each tier sort alphabetically."""
        lv = (self.sourceModel().data(left,  Qt.ItemDataRole.DisplayRole) or "").lower()
        rv = (self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole) or "").lower()
        p  = self._prefix
        l_starts = lv.startswith(p)
        r_starts = rv.startswith(p)
        if l_starts != r_starts:
            return l_starts  # starts-with rows sort first
        return lv < rv       # alphabetical within same tier





class _GodownDelegate(UniversalCellDelegate):
    """UniversalCellDelegate subclass for the Godown List.
    Tab key commits the current value and moves down — identical to Enter.
    Applies ONLY to this table; all other tables retain default Tab behaviour.
    """
    def eventFilter(self, editor, event):
        from PyQt6.QtCore import QEvent, Qt
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            from PyQt6.QtGui import QKeyEvent
            # Convert Tab → Return and let Qt's built-in delegate mechanism
            # handle commitData / closeEditor atomically. This avoids the
            # "does not belong to this view" error that occurs when we emit
            # those signals ourselves on an editor that may already be closing.
            ret_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            )
            super().eventFilter(editor, ret_event)   # commits via Qt internals
            # Schedule downward navigation (editor is closed by now)
            t = getattr(self._owner, '_excel_table', None)
            if t:
                row = t.currentRow()
                if row < t.rowCount() - 1:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda r=row: t.setCurrentCell(r + 1, t.currentColumn()))
            return True   # consume the Tab — don't let Qt move right
        return super().eventFilter(editor, event)


class GodownListUI(ExcelTableMixin, QWidget):
    def __init__(self, data_folder_path, final_data_df=None):
        super().__init__()
        self.settings = QSettings("TallySync", "GodownList")
        self.export_folder = self.settings.value("export_folder", "")
        self.final_data = None  # Will be loaded from final_data DB
        self._alias_lookup = {}  # {alias_lower: {Item_Name, Unit, Part_No}}
        self.company_path = ""
        self.db = get_db_manager()
        self.godown_db_name = ""
        self.final_db_name = ""
        self._active_editor = None  # Track (row, editor) for cleanup
        self._pre_cn       = ""    # CN value before the user starts editing col 6
        # _is_edit_mode is initialised by ExcelTableMixin._init_excel_table()
        
        # Debounced save timer — saves 1 second after last edit instead of on every keystroke
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self.save_data_to_db)
        
        self.init_ui()
        self.change_data_folder(data_folder_path, final_data_df)

    def change_data_folder(self, company_path, final_data_df=None):
        if not company_path: return
        self.company_path = company_path
        company_name = os.path.basename(company_path)
        self.godown_db_name = build_logical_name(company_name, company_path=company_path)
        self.final_db_name = build_logical_name(company_name, company_path=company_path)
        self.db_path = os.path.join(company_path, "godown_stock.db")  # Legacy for export
        
        # Load product data from final_data DB for autocomplete
        self.load_final_data_from_db(company_path)
        
        self.init_db()
        
        # Safety check: Only clear table if it was initialized
        if hasattr(self, 'table'):
            self.table.setRowCount(0) 
            self.load_data_from_db()
            self.update_completer()
            # Ensure at least 50 empty buffer rows, scaling with product count
            named_count = sum(
                1 for r in range(self.table.rowCount())
                if self.table.item(r, 0) and self.table.item(r, 0).text().strip()
            )
            self.ensure_minimum_rows(max(200, named_count + 50))
            # Every row (named or empty) must always have a CN from the start
            self._fill_all_cn_gaps()
            # Flush DB immediately so old empty buffer rows are removed
            self.save_data_to_db()

    # ---------------- LOAD PRODUCT DATA ----------------
    def load_final_data_from_db(self, company_path):
        """Load FirstAlias, Item_Name, Unit, Part_No from stock_items (Row Data) for autocomplete.
        Uses a plain dict instead of Pandas for O(1) lookups."""
        try:
            conn = self.db.get_connection(self.final_db_name)
            if not conn:
                self.final_data = None
                self._alias_lookup = {}
                return
            cursor = conn.cursor()
            cursor.execute("SELECT [FirstAlias], [Item_Name], [Unit], [Part_No] FROM stock_items")
            rows = cursor.fetchall()
            
            self._alias_lookup = {}
            alias_list = []
            for row in rows:
                alias = str(row[0]).strip() if row[0] else ""
                item_name = str(row[1]).strip() if row[1] else ""
                data = {
                    "Item_Name": item_name,
                    "Unit": row[2] or "",
                    "Part_No": row[3] or ""
                }
                
                # Add Alias → data mapping
                if alias and alias.lower() != 'none':
                    self._alias_lookup[alias.lower()] = data
                    alias_list.append(alias)
                
                # Also add Item_Name → data so Item_Name is directly searchable
                if item_name and item_name.lower() != 'none':
                    if item_name.lower() not in self._alias_lookup:
                        self._alias_lookup[item_name.lower()] = data
                    if item_name not in alias_list:
                        alias_list.append(item_name)
            
            self.final_data = alias_list  # Keep list for completer
            # Pre-sort keys once for O(N log N) paid once, not on every autocomplete commit
            self._sorted_alias_keys = sorted(self._alias_lookup.keys())
            print(f"[GODOWN] Loaded {len(rows)} rows from stock_items")
            print(f"[GODOWN] Completer created with {len(alias_list)} entries (alias + item names)")
        except Exception as e:
            print(f"[GODOWN] Failed to load stock_items: {e}")
            self.final_data = None
            self._alias_lookup = {}
            self._sorted_alias_keys = []

    # ---------------- DATABASE ----------------
    def init_db(self):
        company_folder = self.company_path
        self.db.ensure_database_exists(self.godown_db_name, company_folder)
        self.db.ensure_table(self.godown_db_name, "stock", """
            CREATE TABLE stock (
                item_name NVARCHAR(MAX), qty_per_ctn NVARCHAR(MAX), unit NVARCHAR(MAX),
                total_ctn NVARCHAR(MAX), godown NVARCHAR(MAX), part_no NVARCHAR(MAX), cn NVARCHAR(MAX)
            )
        """)

    # ---------------- COMPLETER ----------------
    def update_completer(self):
        self.completer = None
        if self.final_data:
            self.completer = QCompleter(self.final_data)  # final_data is now a list of alias strings
            self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.completer.setFilterMode(Qt.MatchFlag.MatchContains)

    # ---------------- UI ----------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        btn_set_location = QPushButton("📂 Set Location")
        self.btn_excel = QPushButton("📥 Excel डाउनलोड")
        btn_print = QPushButton("🖨️ प्रिंट प्रिव्यू")
        self.btn_save = QPushButton("💾 Save & Sort")

        btn_set_location.clicked.connect(self.set_export_location)
        self.btn_excel.clicked.connect(self.export_to_excel)
        btn_print.clicked.connect(self.handle_print_preview)
        self.btn_save.clicked.connect(self.manual_save_and_sort)

        top.addWidget(btn_set_location)
        top.addWidget(self.btn_excel)
        top.addWidget(btn_print)
        top.addWidget(self.btn_save)
        top.addStretch()
        layout.addLayout(top)

        self.table = QTableWidget(200, 7)
        self.table.setHorizontalHeaderLabels([
            "सामानको नाम", "प्रति कार्टुन", "UNIT",
            "जम्मा कार्टुन", "गोदाम", "Part No", "CN"
        ])
        # Item 7: hide Qt's built-in row-number header (the "SN" the user sees)
        self.table.verticalHeader().hide()

        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 80)
        
        # Table navigation (Mode 1 / Mode 2) — ExcelTableMixin
        # UniversalCellDelegate (from mixin) resets _is_edit_mode on editor close.
        # Col 0 (Alias) uses a QLineEdit overlay (setCellWidget), not the delegate.
        self._init_excel_table(self.table)
        
        # Use _GodownDelegate for all columns so Tab acts like Enter everywhere in this table
        self.table.setItemDelegate(_GodownDelegate(self))
        # Specific override for Alias column (col 0) for autocomplete
        self.table.setItemDelegateForColumn(0, _GodownDelegate(
            self, 
            cell_type="autocomplete", 
            autocomplete_items=lambda: getattr(self, "final_data", []),
            enforce_match=False
        ))
        
        # Inline stylesheet overrides global QSS cascade for font (Devanagari support)
        from src.ui.table_nav_mixin import UNIVERSAL_TABLE_STYLE
        self.table.setStyleSheet(UNIVERSAL_TABLE_STYLE + """
            QTableWidget, QLineEdit { font-family: 'Noto Sans Devanagari'; font-size: 14pt; }
            QHeaderView::section { font-family: 'Noto Sans Devanagari'; font-weight: bold; font-size: 14pt; }
        """)
        
        self.table.itemChanged.connect(self.handle_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        # Track the CN value before each edit so the swap in handle_item_changed
        # has the real old value (item already holds the new value by the time
        # itemChanged fires).
        self.table.currentCellChanged.connect(self._on_cn_cell_focus)
        
        layout.addWidget(self.table)

    def apply_edit_mode(self, can_edit: bool):
        """Called by main_window._apply_permissions() to enforce display-only mode.

        can_edit=True  → Normal editing (default behaviour)
        can_edit=False → Read-only: no typing, no autocomplete overlay on col 0,
                         Save/Sort and Excel export buttons disabled.
        """
        self._can_edit = can_edit

        # Table edit triggers
        if can_edit:
            self.table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked |
                QAbstractItemView.EditTrigger.AnyKeyPressed |
                QAbstractItemView.EditTrigger.EditKeyPressed
            )
        else:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Action buttons
        self.btn_save.setEnabled(can_edit)
        self.btn_save.setToolTip("" if can_edit else "🔒 Editing disabled — display only")
        self.btn_excel.setEnabled(can_edit)
        self.btn_excel.setToolTip("" if can_edit else "🔒 Export disabled — display only")


    # ---------------- SHOW EVENT ----------------
    def showEvent(self, event):
        """Reload stock_items data every time the tab becomes visible."""
        super().showEvent(event)
        if self.company_path:
            self.load_final_data_from_db(self.company_path)
            self.update_completer()


    # ── ExcelTableMixin overrides ────────────────────────────────────────────

    def _excel_on_navigate(self):
        """Commit the col-0 overlay editor (if open) before moving away."""
        self._cleanup_active_editor()

    def _on_cell_changed(self, cur_row=None, cur_col=None, prev_row=None, prev_col=None):
        pass

    def _cleanup_active_editor(self):
        """Remove any lingering cell editor and save its text."""
        if not self._active_editor:
            return
        old_row, old_editor = self._active_editor
        self._active_editor = None
        w = self.table.cellWidget(old_row, 0)
        if w and isinstance(w, QLineEdit):
            val = w.text().strip()
            self.table.removeCellWidget(old_row, 0)
            item = QTableWidgetItem(val)
            self.table.blockSignals(True)
            self.table.setItem(old_row, 0, item)
            self.table.blockSignals(False)

    def create_table_item(self, text, alignment=Qt.AlignmentFlag.AlignLeft, locked=False):
        """Create a new table item with alignment and lock properties"""
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        
        if locked:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            
        return item
    
    def ensure_minimum_rows(self, min_rows=200):
        """Ensure at least min_rows rows exist in the table"""
        current_rows = self.table.rowCount()
        if current_rows < min_rows:
            self.table.setRowCount(min_rows)
            
    def _on_cell_double_clicked(self, row, col):
        if col == 6:
            item = self.table.item(row, 6)
            self._pre_cn = item.text().strip() if item else ""
            
    def handle_item_changed(self, item):
        row = item.row()
        col = item.column()
        text = item.text().strip()

        if col == 0 and not text:
            self.table.blockSignals(True)
            for c in range(1, 6):
                self.set_item_locked(row, c, "", should_lock=False)
            self.table.blockSignals(False)
            self.save_data_to_db()
            return
            
        self.table.blockSignals(True)
        try:
            # Column 0 (Alias) - apply lookup logic
            if col == 0 and text:
                data = self._alias_lookup.get(text.lower())
                if not data and self._alias_lookup:
                    for key in getattr(self, '_sorted_alias_keys', sorted(self._alias_lookup.keys())):
                        if text.lower() in key:
                            data = self._alias_lookup[key]
                            break
                if data:
                    item_name = data["Item_Name"]
                    item.setText(item_name)
                    self.table.setItem(row, 2, self.create_table_item(data.get("Unit", ""), Qt.AlignmentFlag.AlignCenter, True))
                    p_no = str(data.get("Part_No", ""))
                    if p_no.lower() == "none": p_no = ""
                    p_no = _apply_part_no_override(item_name, p_no)
                    self.table.setItem(row, 5, self.create_table_item(p_no, Qt.AlignmentFlag.AlignCenter, True))
                    
                    if not self.table.item(row, 1): self.set_item_locked(row, 1, "", should_lock=False)
                    if not self.table.item(row, 3): self.set_item_locked(row, 3, "", should_lock=False)
                    if not self.table.item(row, 4): self.set_item_locked(row, 4, "", should_lock=False)
                    if not self.table.item(row, 6): self.set_item_locked(row, 6, "", should_lock=False)
                    
                    cn_was_freed = False
                    if _is_cn_excluded(p_no):
                        existing_cn_item = self.table.item(row, 6)
                        if existing_cn_item and existing_cn_item.text().strip():
                            self.set_item_locked(row, 6, "", should_lock=False)
                            cn_was_freed = True
                            
                    self._nav_set_current(row, 1)
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda r=row: self.table.editItem(self.table.item(r, 1)) if self.table.item(r, 1) else None)
                    if cn_was_freed: self._reassign_empty_cns()
                    self.save_data_to_db()
                    return
                else:
                    unit_val = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
                    pno_val  = self.table.item(row, 5).text() if self.table.item(row, 5) else ""
                    self.set_item_locked(row, 2, unit_val, should_lock=False)
                    self.set_item_locked(row, 5, pno_val,  should_lock=False)
                    if not self.table.item(row, 1): self.set_item_locked(row, 1, "", should_lock=False)
                    self._nav_set_current(row, 1)
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda r=row: self.table.editItem(self.table.item(r, 1)) if self.table.item(r, 1) else None)
                    self.save_data_to_db()

            # Column 1 (प्रति कार्टुन) - Right align + numeric validation
            if col == 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if text:
                    val = text.replace(",", "").replace(".", "").replace("-", "")
                    if val and not val.isdigit():
                        QMessageBox.warning(self, "Invalid Input", "कृपया केवल संख्या (numbers) लिखें।")
                        item.setText("")

            # Column 3 (जम्मा कार्टुन) — left-align + arithmetic expression evaluator (+ and - only)
            if col == 3:
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if text and any(op in text for op in '+-'):
                    import re as _re
                    tokens = _re.findall(r'[+-]?\d+', text.replace(' ', ''))
                    if tokens:
                        try:
                            result = sum(int(t) for t in tokens)
                            item.setText(str(result))
                        except ValueError:
                            pass

            # Column 4 (Godown) — auto-uppercase and center-align
            if col == 4 and text:
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                item.setText(text.upper())

            # If item name cleared, clear all other columns except CN (col 6)
            if col == 0 and text == "":
                for c in range(1, 6):
                    self.set_item_locked(row, c, "", should_lock=False)

            # CN column (col 6) — enforce blank for excluded prefixes; handle clear; swap on duplicate
            if col == 6:
                part_item = self.table.item(row, 5)
                part_no = part_item.text().strip() if part_item else ""
                if _is_cn_excluded(part_no):
                    # Excluded rows must never hold a CN — blank it immediately
                    item.setText("")
                elif not text:
                    # CN was cleared. Only reassign if this is a NAMED product row.
                    # Clearing a buffer row's CN is not a user action we need to react to.
                    name_item = self.table.item(row, 0)
                    if name_item and name_item.text().strip():
                        self._reassign_empty_cns()
                elif text:
                    # Reject permanently excluded CN numbers
                    _cn_rejected = False
                    try:
                        if int(text) in _EXCLUDED_CNS:
                            item.setText(self._pre_cn)
                            QMessageBox.warning(
                                self, "Invalid CN",
                                f"CN {text} is reserved and cannot be assigned."
                            )
                            _cn_rejected = True
                    except ValueError:
                        pass

                    if not _cn_rejected:
                        # Look for a duplicate CN on another row
                        for r in range(self.table.rowCount()):
                            if r == row:
                                continue
                            other = self.table.item(r, 6)
                            if other and other.text().strip() == text:
                                other_name = self.table.item(r, 0)
                                if other_name and other_name.text().strip():
                                    # Target CN belongs to a named row — reject, revert to old CN
                                    item.setText(self._pre_cn)
                                    QMessageBox.warning(
                                        self, "Cannot Swap",
                                        f"CN {text} is assigned to a product.\nYou can only swap with an empty row."
                                    )
                                else:
                                    # Target is an empty buffer row — swap allowed.
                                    # Only give _pre_cn if it's a real CN; if it's empty
                                    # (cleared previously), just fill the gap normally.
                                    if self._pre_cn:
                                        self.set_item_locked(r, 6, self._pre_cn, should_lock=False)
                                    else:
                                        # _pre_cn is blank — assign a proper CN via gap filler
                                        self.set_item_locked(r, 6, "", should_lock=False)
                                        self._fill_all_cn_gaps()
                                break
                self._pre_cn = ""  # reset after use
        finally:
            self.table.blockSignals(False)

        # Debounced save covers all cases — no forced sort on CN clear.
        self._save_timer.start()
    
    def load_data_from_db(self):
        conn = self.db.get_connection(self.godown_db_name)
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock")
        rows = cursor.fetchall()

        self.table.blockSignals(True)
        try:
            # Build set of known item names to determine lock state for Unit/Part No
            known_names = {
                v["Item_Name"].strip().lower()
                for v in (self._alias_lookup or {}).values()
            }
            if len(rows) > self.table.rowCount():
                self.table.setRowCount(len(rows))
            for r, data in enumerate(rows):
                row_item_lower = str(data[0]).strip().lower() if data[0] else ""
                item_in_list = bool(row_item_lower) and row_item_lower in known_names
                for c, val in enumerate(data):
                    align = Qt.AlignmentFlag.AlignLeft
                    is_locked = False
                    if c == 1: align = Qt.AlignmentFlag.AlignRight # प्रति कार्टुन
                    if c == 3: align = Qt.AlignmentFlag.AlignLeft  # जम्मा कार्टुन — left-aligned
                    if c in (2, 4, 5, 6): align = Qt.AlignmentFlag.AlignCenter # Unit, Godown, PartNo, CN
                    # Lock Unit/Part No only for items in the master list
                    if c in (2, 5): is_locked = item_in_list
                    self.table.setItem(r, c, self.create_table_item(val, align | Qt.AlignmentFlag.AlignVCenter, is_locked))
        finally:
            self.table.blockSignals(False)
        # Fill in any missing CNs (e.g. first load, or data without CN column).
        # Named rows with empty CN are intentionally skipped by _fill_all_cn_gaps.
        self._fill_all_cn_gaps()
        
    def save_data_to_db(self):
        conn = self.db.get_connection(self.godown_db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            # Build all rows first, then send in one batch (executemany)
            # This is far faster than individual INSERT calls over a network connection.
            rows_to_insert = []
            for r in range(self.table.rowCount()):
                row_data = tuple(
                    self.table.item(r, c).text() if self.table.item(r, c) else ""
                    for c in range(7)
                )
                # Only save named rows (col 0 non-empty).
                # Empty buffer rows are recreated fresh on every load via
                # ensure_minimum_rows + _fill_all_cn_gaps — no need to persist them.
                if row_data[0].strip():
                    rows_to_insert.append(row_data)

            # Skip the DB round-trip entirely if nothing has changed since last save.
            import hashlib, json as _json
            current_hash = hashlib.md5(
                _json.dumps(rows_to_insert, ensure_ascii=False).encode()
            ).hexdigest()
            if current_hash == getattr(self, '_last_saved_hash', None):
                return  # identical data — no-op
            self._last_saved_hash = current_hash

            cur.execute("DELETE FROM stock")
            if rows_to_insert:
                cur.executemany("INSERT INTO stock VALUES (?,?,?,?,?,?,?)", rows_to_insert)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save godown stock: {e}")
    
    def _on_cn_cell_focus(self, curr_row, curr_col, _prev_row, _prev_col):
        """Called whenever the selected cell changes.  When the user navigates
        TO the CN column, capture the existing value as the pre-edit baseline
        so the swap logic in handle_item_changed has the correct old value."""
        if curr_col == 6:
            item = self.table.item(curr_row, 6)
            self._pre_cn = item.text().strip() if item else ""

    def _fill_all_cn_gaps(self):
        """Assign CNs to empty buffer rows that have none; leave named rows alone.

        Rules:
        - Named rows that already have a CN  → untouched.
        - Named excluded rows (CN_BLANK_PREFIXES) → keep blank CN.
        - Named rows with NO CN (user intentionally cleared it) → left blank.
        - Empty buffer rows with no CN → assigned the next available CN.
        """
        # Collect all used CNs
        used_cns: set[int] = set()
        max_cn = 0
        for r in range(self.table.rowCount()):
            cn_item = self.table.item(r, 6)
            try:
                v = int(cn_item.text().strip()) if cn_item else 0
                if v > 0:
                    used_cns.add(v)
                    if v > max_cn:
                        max_cn = v
            except (ValueError, TypeError):
                pass

        # Find available gaps — permanently excluded CNs are never recycled
        available_cns = [
            v for v in range(1, max_cn)
            if v not in used_cns and v not in _EXCLUDED_CNS
        ]
        available_cns.sort()

        was_blocked = self.table.signalsBlocked()
        self.table.blockSignals(True)
        try:
            # Start sequential assignment after max used CN, skipping excluded numbers
            next_new_cn = max_cn + 1
            while next_new_cn in _EXCLUDED_CNS:
                next_new_cn += 1

            for r in range(self.table.rowCount()):
                name_item = self.table.item(r, 0)
                name = name_item.text().strip() if name_item else ""
                part_item = self.table.item(r, 5)
                part_no = part_item.text().strip() if part_item else ""

                if name and _is_cn_excluded(part_no):
                    self.set_item_locked(r, 6, "", should_lock=False)
                    continue  # named excluded row — intentionally blank

                cn_item = self.table.item(r, 6)
                if cn_item and cn_item.text().strip():
                    continue  # already has a CN — skip

                # Named product row with no CN:
                # '--' sentinel is truthy so it's caught by the check above.
                # A truly empty named row shouldn't exist in normal flow, but
                # skip it here to be safe (next Sort will handle it).
                if name:
                    continue

                # Empty buffer row — assign the next available CN
                if available_cns:
                    assigned_cn = available_cns.pop(0)
                else:
                    assigned_cn = next_new_cn
                    next_new_cn += 1
                    while next_new_cn in _EXCLUDED_CNS:
                        next_new_cn += 1

                self.set_item_locked(r, 6, str(assigned_cn), should_lock=False)
        finally:
            if not was_blocked:
                self.table.blockSignals(False)

    def _reassign_empty_cns(self):
        """Immediately recycle any missing gaps to the empty buffer rows.
        
        This blanks all empty buffer rows and re-runs the gap filler, causing
        freed CNs (like when a row is changed to JALI) to instantly appear
        at the bottom of the table.
        """
        was_blocked = self.table.signalsBlocked()
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                name_item = self.table.item(r, 0)
                if not (name_item and name_item.text().strip()):
                    self.set_item_locked(r, 6, "", should_lock=False)
        finally:
            if not was_blocked:
                self.table.blockSignals(False)
        self._fill_all_cn_gaps()

    def manual_save_and_sort(self, silent=False):
        """Save & Sort:
        1. Refresh Part No from stock_items (live DB lookup).
        2. Sort named rows by Part No A→Z, then empty rows by CN ascending.
        3. Run _fill_all_cn_gaps as a safety net (handles JALI→normal etc.).
        4. Save to DB and notify user.
        """
        self._signals_blocked = True
        self.table.blockSignals(True)
        try:
            # 1. Refresh Part No
            self.refresh_part_no_from_item()

            # 2. Custom sort — extract, sort, write back
            named_rows = []
            empty_rows = []
            for r in range(self.table.rowCount()):
                row_data = [
                    self.table.item(r, c).text() if self.table.item(r, c) else ""
                    for c in range(7)
                ]
                if row_data[0].strip():  # has a product name
                    named_rows.append(row_data)
                else:
                    empty_rows.append(row_data)

            # Group by Part No presence
            named_no_partno   = [r for r in named_rows if not r[5].strip()]
            named_with_partno = [r for r in named_rows if     r[5].strip()]

            named_no_partno.sort(key=lambda x: x[0].strip().upper())    # item name A→Z
            named_with_partno.sort(key=lambda x: x[5].strip().upper())  # Part No A→Z

            # Sort empty rows by CN (col 6) numerically
            def _cn_sort_key(row_data):
                try:
                    return int(row_data[6].strip())
                except (ValueError, TypeError):
                    return float('inf')  # blank CN sorts last
            empty_rows.sort(key=_cn_sort_key)

            # Sort order:
            #   1. Named rows with NO Part No  — top  (item name A→Z)
            #   2. Named rows WITH Part No      — middle (Part No A→Z, any CN state)
            #   3. Empty buffer rows            — bottom (CN numerically)
            all_rows = named_no_partno + named_with_partno + empty_rows
            total_needed = max(200, len(named_rows) + 50)  # always 50+ buffer rows
            if self.table.rowCount() < total_needed:
                self.table.setRowCount(total_needed)
            # Build known names to decide lock state for Unit/Part No
            known_names = {
                v["Item_Name"].strip().lower()
                for v in (self._alias_lookup or {}).values()
            }
            for r, row_data in enumerate(all_rows):
                row_item_lower = str(row_data[0]).strip().lower() if row_data[0] else ""
                item_in_list = bool(row_item_lower) and row_item_lower in known_names
                for c, val in enumerate(row_data):
                    align = Qt.AlignmentFlag.AlignLeft
                    is_locked = False
                    if c == 1: align = Qt.AlignmentFlag.AlignRight
                    if c == 3: align = Qt.AlignmentFlag.AlignLeft   # जम्मा कार्टुन — left-aligned
                    if c in (2, 4, 5, 6): align = Qt.AlignmentFlag.AlignCenter
                    # Lock Unit/Part No only for items in the master list
                    if c in (2, 5): is_locked = item_in_list
                    self.table.setItem(r, c, self.create_table_item(val, align | Qt.AlignmentFlag.AlignVCenter, is_locked))

            # Recycle freed CNs into visible empty buffer rows.
            # _reassign_empty_cns blanks all empty buffer rows first, then
            # redistributes ALL available gaps — so a freed CN (e.g. CN 3)
            # gets assigned to one of the buffer rows and becomes visible.
            # Named rows WITHOUT a CN are left alone (if name: continue guard).
            self._reassign_empty_cns()

        except Exception as e:
            print(f"Error during save/sort: {e}")
        finally:
            self._signals_blocked = False
            self.table.blockSignals(False)

        self.save_data_to_db()
        if not silent:
            QMessageBox.information(self, "Saved", "Data Saved & Sorted Successfully")

    
    # ---------------- CELL LOGIC ----------------
    def set_item_locked(self, row, col, value, should_lock=True):
        """Set a cell value with proper alignment and lock state"""
        item = QTableWidgetItem(str(value))
        
        if col == 1:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif col in (2, 4, 5, 6):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        else:
            # cols 0, 3 — left-aligned, vertically centred
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if should_lock:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            
        self.table.setItem(row, col, item)
        return item

    def delete_fully_empty_rows(self):
        """Delete rows where all columns 0-5 are empty.
        (We ignore column 6 / CN, because it is always auto-filled)."""
        for r in range(self.table.rowCount() - 1, -1, -1):
            all_empty = True
            for c in range(0, 6):
                item = self.table.item(r, c)
                if item and item.text().strip() != "":
                    all_empty = False
                    break

            if all_empty:
                self.table.removeRow(r)
    
    def refresh_part_no_from_item(self):
        if not self._alias_lookup:
            return

        # Build item_name → Part_No lookup
        item_lookup = {}
        for alias_data in self._alias_lookup.values():
            item_name = str(alias_data["Item_Name"]).strip().lower()
            if item_name:
                item_lookup[item_name] = alias_data.get("Part_No", "")

        for r in range(self.table.rowCount()):
            item0 = self.table.item(r, 0)
            if not item0:
                continue

            item_name = item0.text().strip()
            if item_name == "":
                continue

            part_no = item_lookup.get(item_name.lower())
            if part_no is not None:
                if str(part_no).strip().lower() == "none":
                    part_no = ""
                # Item 13: apply override mapping after fetching from DB
                part_no = _apply_part_no_override(item_name, part_no)
                self.set_item_locked(r, 5, part_no)

    # ---------------- EXPORT / PRINT ----------------
    def set_export_location(self):
        """Pick an export folder via the shared helper (native dialog)."""
        self.export_folder = pick_export_folder(
            parent=self,
            settings=self.settings,
            settings_key="export_folder",
            current_folder=self.export_folder,
        )

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

        df = __import__('pandas').DataFrame(data, columns=[
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
            import pandas as _pd
            writer = _pd.ExcelWriter(path, engine='xlsxwriter')
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
        printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)

        self._godown_print_pages = []
        self._godown_printer = printer

        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self.paint_table)

        # Override the internal "Print" toolbar action with our page-range-aware handler.
        # QPrintPreviewDialog caches rendered pages and sends them directly — it does NOT
        # re-call paintRequested with fromPage/toPage, so we intercept the action here.
        self._godown_preview_ref = preview
        for toolbar in preview.findChildren(QToolBar):
            for action in toolbar.actions():
                tip = (action.toolTip() or "").lower()
                txt = (action.text() or "").replace("&", "").strip().lower()
                if tip == "print" or txt == "print":
                    action.triggered.disconnect()
                    action.triggered.connect(self._custom_print_godown)
                    break

        preview.resize(900, 680)
        preview.exec()

    def _custom_print_godown(self):
        """Called when user clicks Print inside the godown QPrintPreviewDialog.
        Opens QPrintDialog with proper page range support and renders only selected pages."""
        total = len(self._godown_print_pages) if self._godown_print_pages else 1
        printer = self._godown_printer

        from PyQt6.QtPrintSupport import QPrintDialog
        dlg = QPrintDialog(printer, self._godown_preview_ref)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange)
        dlg.setMinMax(1, total)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        fp = printer.fromPage()   # 1-indexed; 0 = all
        tp = printer.toPage()
        if fp == 0 or tp == 0:
            start_pg, end_pg = 0, total - 1
        else:
            start_pg = max(0, fp - 1)
            end_pg   = min(tp - 1, total - 1)

        self.paint_table(printer, page_range=(start_pg, end_pg))

    def paint_table(self, printer, page_range=None):
        """Draw the table directly using QPainter for pixel-perfect A4 output.

        Items 10, 11, 12:
        - A4 paper size (set in handle_print_preview)
        - Column widths derived from actual screen column widths (proportional)
        - Page number and print date printed in a footer on every page
        page_range: (start, end) 0-indexed inclusive. None = all pages (preview mode).
        """
        painter = QPainter()
        if not painter.begin(printer):
            return


        page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        page_w = page_rect.width()
        page_h = page_rect.height()

        # --- Fonts ---
        header_font = QFont("Noto Sans Devanagari", 13, QFont.Weight.Normal)
        cell_font   = QFont("Noto Sans Devanagari", 11)
        footer_font = QFont("Noto Sans Devanagari", 9)

        painter.setFont(header_font)
        fm_header = painter.fontMetrics()
        header_height = int(fm_header.height() * 1.3)

        painter.setFont(cell_font)
        fm_cell   = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.15)
        h_pad = int(fm_cell.averageCharWidth() * 0.3)

        painter.setFont(footer_font)
        fm_footer   = painter.fontMetrics()
        footer_height = int(fm_footer.height() * 1.6)

        # Item 12: derive column widths from actual screen column widths
        col_count = self.table.columnCount()
        screen_widths = [self.table.columnWidth(c) for c in range(col_count)]
        total_screen  = sum(screen_widths) or 1
        col_widths = [int(page_w * w / total_screen) for w in screen_widths]
        # Correct rounding error on last column
        col_widths[-1] = page_w - sum(col_widths[:-1])

        headers = [self.table.horizontalHeaderItem(c).text() for c in range(col_count)]

        # Reserve bottom of each page for the footer
        usable_h = page_h - footer_height

        # --- Collect data rows (skip fully empty) ---
        data_rows = []
        for r in range(self.table.rowCount()):
            row_data = []
            has_data = False
            for c in range(col_count):
                item = self.table.item(r, c)
                text = item.text() if item else ""
                if text.strip():
                    has_data = True
                row_data.append(text)
            if has_data:
                data_rows.append(row_data)

        # --- Alignment per column (जम्मा कार्टुन col 3 is left-aligned to match screen) ---
        alignments = [
            Qt.AlignmentFlag.AlignLeft,      # Item Name
            Qt.AlignmentFlag.AlignRight,     # Qty/Ctn
            Qt.AlignmentFlag.AlignHCenter,   # Unit
            Qt.AlignmentFlag.AlignLeft,      # Total Ctn (जम्मा कार्टुन) — left-aligned
            Qt.AlignmentFlag.AlignHCenter,   # Godown
            Qt.AlignmentFlag.AlignHCenter,   # Part No
            Qt.AlignmentFlag.AlignHCenter,   # CN
        ]

        pen = QPen(QColor(0, 0, 0), 2)
        today_str = _date.today().strftime("%Y-%m-%d")

        def draw_header(y):
            painter.setFont(header_font)
            painter.setPen(pen)
            x = 0
            for c, hdr in enumerate(headers):
                rect = QRect(x, y, col_widths[c], header_height)
                painter.fillRect(rect, QColor(220, 220, 220))
                painter.drawRect(rect)
                text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, header_height)
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
                text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, row_height)
                align = alignments[c] | Qt.AlignmentFlag.AlignVCenter
                painter.drawText(text_rect, align, text)
                x += col_widths[c]
            return y + row_height

        def draw_footer(page_num):
            """Item 10: footer with page number and print date on every page."""
            painter.setFont(footer_font)
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            footer_y = page_h - footer_height
            # Left: print date
            painter.drawText(
                QRect(0, footer_y, page_w // 2, footer_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Printed: {today_str}"
            )
            # Right: page number
            painter.drawText(
                QRect(page_w // 2, footer_y, page_w // 2, footer_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"Page {page_num}"
            )

        # --- Pre-calculate pages (pass 1) ---
        pages = []
        current_page = []
        avail_h = usable_h - header_height
        used = 0
        for row_data in data_rows:
            if used + row_height > avail_h:
                pages.append(current_page)
                current_page = []
                used = 0
            current_page.append(row_data)
            used += row_height
        if current_page or not pages:
            pages.append(current_page)

        total_pages = len(pages)
        # Store for _custom_print_godown to know total count
        self._godown_print_pages = pages

        # Determine which pages to render
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

            page_num = pg_idx + 1
            y = 0
            y = draw_header(y)
            for row_data in pages[pg_idx]:
                y = draw_row(y, row_data)
            draw_footer(page_num)

        painter.end()
