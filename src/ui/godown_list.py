import os
from datetime import date as _date
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from src.logic.db_manager import get_db_manager, build_logical_name
from src.ui.table_nav_mixin import ExcelTableMixin
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


def _godown_enforce_match(editor, text: str, data_list: list, proxy, completer):
    """Reject the last typed character if no entry in data_list contains it.
    After rejecting, update the proxy and re-open the popup for the reverted text."""
    if not text:
        return
    tl = text.lower()
    for item in data_list:
        if tl in str(item).lower():
            return  # at least one match — allow
    # No match: strip the last character
    editor.blockSignals(True)
    editor.setText(text[:-1])
    editor.blockSignals(False)
    # Re-open popup with correct matches for the reverted text
    reverted = text[:-1].lower()
    proxy.set_prefix(reverted)
    completer.complete()


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
            print(f"[GODOWN] Loaded {len(rows)} rows from stock_items")
            print(f"[GODOWN] Completer created with {len(alias_list)} entries (alias + item names)")
        except Exception as e:
            print(f"[GODOWN] Failed to load stock_items: {e}")
            self.final_data = None
            self._alias_lookup = {}

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
        # _NavResetDelegate (from mixin) resets _is_edit_mode on editor close.
        # Col 0 (Alias) uses a QLineEdit overlay (setCellWidget), not the delegate.
        self._init_excel_table(self.table)
        self.table.itemChanged.connect(self.handle_item_changed)
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

    def _excel_on_double_click(self, row, col):
        """Col 0: open autocomplete overlay. Col > 0: mixin default (track + cursor)."""
        if not getattr(self, '_can_edit', True):
            return  # Display-only mode: block overlay editor
        if col == 0:
            self.start_Alias_search(row, col)
            return
        if col == 6:
            # Capture pre-edit CN so the swap in handle_item_changed is correct
            item = self.table.item(row, 6)
            self._pre_cn = item.text().strip() if item else ""
        super()._excel_on_double_click(row, col)

    def _excel_on_printable_key(self, row, col, text):
        """Col 0: open overlay + type. Col 1: numeric only. Others: mixin default."""
        if not getattr(self, '_can_edit', True):
            return True  # Display-only mode: swallow key, block overlay
        if col == 0:
            self.start_Alias_search(row, col)
            editor = self._active_editor[1] if self._active_editor else None
            if editor:
                editor.clear()
                editor.setText(text)
            return True
        if col == 6:
            # Capture pre-edit CN before super() clears/replaces the cell value
            item = self.table.item(row, 6)
            self._pre_cn = item.text().strip() if item else ""
        if col == 1 and text not in "0123456789.,-":
            return True   # block non-numeric
        return super()._excel_on_printable_key(row, col, text)

    # kept for backward-compat with any stale signal connections
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
    
    def start_Alias_search(self, row, col):
        if col != 0: return

        # Clean up any previous editor
        self._cleanup_active_editor()

        current = self.table.item(row, col)
        # Item 8: capture pre-edit text so we can restore it if user clears the field
        self._pre_edit_text = current.text() if current else ""
        text = self._pre_edit_text
        editor = QLineEdit(text)
        if self.final_data:
            # Build source model from the alias/item-name list
            src_model = QStringListModel(self.final_data)

            # Proxy: starts-with matches at the top, contains matches below
            proxy = _GodownSortProxyModel()
            proxy.setSourceModel(src_model)
            proxy.setSortRole(Qt.ItemDataRole.DisplayRole)
            proxy.setDynamicSortFilter(True)

            local_completer = QCompleter(proxy, editor)
            local_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            local_completer.setFilterMode(Qt.MatchFlag.MatchContains)
            local_completer.setMaxVisibleItems(12)
            local_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            editor.setCompleter(local_completer)

            # Keep proxy sorted whenever the user types
            editor.textEdited.connect(lambda t: proxy.set_prefix(t.strip()))
            # Typing guard: reject characters that have no match in the list
            editor.textEdited.connect(
                lambda t, e=editor, dl=self.final_data, p=proxy, c=local_completer:
                    _godown_enforce_match(e, t, dl, p, c)
            )
            local_completer.activated.connect(lambda val: self._commit_alias_search(row, editor))

        self.table.setCellWidget(row, col, editor)
        # Use QTimer so deselect/cursor-end runs AFTER focusInEvent fires
        # (focusInEvent calls selectAll which overwrites any deselect done here)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, editor.deselect)
        QTimer.singleShot(0, lambda: editor.end(False))
        editor.setFocus()

        # Track this editor
        self._active_editor = (row, editor)

        editor.returnPressed.connect(lambda: self._commit_alias_search(row, editor))
        
    def _commit_alias_search(self, row, editor):
        if not editor or not editor.parent():
            return  # Already committed

        Alias = editor.text().strip()
        self.table.removeCellWidget(row, 0)

        # Empty input — user wants to clear the row completely
        if not Alias:
            self.table.blockSignals(True)
            # Clear name and columns 1-5 only; CN stays as-is
            self.table.setItem(row, 0, self.create_table_item(""))
            for c in range(1, 6):
                lock = True if c in (2, 5) else False
                self.set_item_locked(row, c, "", should_lock=lock)
            self.table.blockSignals(False)

            self.save_data_to_db()
            return

        # Exact match first
        data = self._alias_lookup.get(Alias.lower())

        # Contains match fallback (first alphabetical result)
        if not data and self._alias_lookup:
            alias_lower = Alias.lower()
            for key in sorted(self._alias_lookup.keys()):
                if alias_lower in key:
                    data = self._alias_lookup[key]
                    break

        if data:
            item_name = data["Item_Name"]
            # 1. Set Item Name (from Name column, not Alias)
            self.table.setItem(row, 0, self.create_table_item(item_name))

            # 2. Unit - auto-fill and lock
            self.table.setItem(row, 2, self.create_table_item(
                data.get("Unit", ""), Qt.AlignmentFlag.AlignCenter, True))

            # 3. Part No - auto-fill, apply override, then lock
            p_no = str(data.get("Part_No", ""))
            if p_no.lower() == "none":
                p_no = ""
            # Item 13: override Part No for mapped products
            p_no = _apply_part_no_override(item_name, p_no)
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

            # 5. If Part No is excluded, handle CN removal (with dialog for named rows)
            cn_was_freed = False
            if _is_cn_excluded(p_no):
                existing_cn_item = self.table.item(row, 6)
                existing_cn = existing_cn_item.text().strip() if existing_cn_item else ""
                if existing_cn:
                    pre_name = getattr(self, '_pre_edit_text', '').strip()
                    if pre_name:
                        # Case 2: Row previously had a name — ask user
                        reply = QMessageBox.question(
                            self, 'Remove CN?',
                            f"This product does not need a CN.\nRemove CN {existing_cn} and swap it?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes
                        )
                        if reply == QMessageBox.StandardButton.No:
                            # User cancelled — revert the row back to the original product
                            self.table.removeCellWidget(row, 0)
                            self.table.setItem(row, 0, self.create_table_item(pre_name))
                            self._nav_set_current(row, 0)
                            return
                        # Yes — blank the CN and swap it to next available empty row
                        self.table.blockSignals(True)
                        self.set_item_locked(row, 6, "", should_lock=False)
                        self.table.blockSignals(False)
                        cn_was_freed = True
                    else:
                        # Case 1: Row was empty before — blank silently
                        self.table.blockSignals(True)
                        self.set_item_locked(row, 6, "", should_lock=False)
                        self.table.blockSignals(False)
                        cn_was_freed = True

            # 6. Move cursor to quantity col (col 1) and open editor
            self._nav_set_current(row, 1)
            self.table.setFocus()
            self._is_edit_mode = True
            self.table.editItem(self.table.item(row, 1))

            # Only recycle if a CN was actually freed (JALI case).
            # Normal product commits (empty row → named row) keep the row's
            # existing CN — no gap-filling so manual CN jumps stay as gaps until Sort.
            if cn_was_freed:
                self._reassign_empty_cns()

            self.save_data_to_db()
            return

        # No match — reject the input, restore previous value and stay on the cell
        prev_text = getattr(self, '_pre_edit_text', '')
        self.table.setItem(row, 0, self.create_table_item(prev_text))
        self._nav_set_current(row, 0)  # stay on col 0, Mode 1
    
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
        try:
            # Column 1 (प्रति कार्टुन) - Right align + numeric validation
            if col == 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if text:
                    val = text.replace(",", "").replace(".", "").replace("-", "")
                    if val and not val.isdigit():
                        QMessageBox.warning(self, "Invalid Input", "कृपया केवल संख्या (numbers) लिखें।")
                        item.setText("")

            # If item name cleared, clear all other columns except CN (col 6)
            if col == 0 and text == "":
                for c in range(1, 6):
                    lock = True if c in (2, 5) else False
                    self.set_item_locked(row, c, "", should_lock=lock)

            # CN column (col 6) — enforce blank for excluded prefixes; swap on duplicate
            if col == 6:
                part_item = self.table.item(row, 5)
                part_no = part_item.text().strip() if part_item else ""
                if _is_cn_excluded(part_no):
                    # Excluded rows must never hold a CN — blank it immediately
                    item.setText("")
                elif text:
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
                                # Target is an empty buffer row — swap allowed
                                self.set_item_locked(r, 6, self._pre_cn, should_lock=False)
                            break
                self._pre_cn = ""  # reset after use
        finally:
            self.table.blockSignals(False)
        self._save_timer.start()  # Debounced save — fires 1s after last edit
    
    def load_data_from_db(self):
        conn = self.db.get_connection(self.godown_db_name)
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock")
        rows = cursor.fetchall()

        self.table.blockSignals(True)
        try:
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
        finally:
            self.table.blockSignals(False)
        # Fill in any missing CNs (e.g. first load, or data without CN column)
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
        """Ensure every row in the table has a CN, reusing any gaps.

        - Rows that already have a CN are left untouched.
        - Named excluded rows (CN_BLANK_PREFIXES) keep their blank CN.
        - Missing CNs (gaps below the current max) are recycled and given 
          to empty rows first. Once gaps are filled, it continues sequentially.
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

        # Find available gaps
        available_cns = [v for v in range(1, max_cn) if v not in used_cns]
        available_cns.sort()

        self.table.blockSignals(True)
        try:
            next_new_cn = max_cn + 1
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

                # Assign a CN to this row
                if available_cns:
                    assigned_cn = available_cns.pop(0)
                else:
                    assigned_cn = next_new_cn
                    next_new_cn += 1

                self.set_item_locked(r, 6, str(assigned_cn), should_lock=False)
        finally:
            self.table.blockSignals(False)

    def _reassign_empty_cns(self):
        """Immediately recycle any missing gaps to the empty buffer rows.
        
        This blanks all empty buffer rows and re-runs the gap filler, causing
        freed CNs (like when a row is changed to JALI) to instantly appear
        at the bottom of the table.
        """
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                name_item = self.table.item(r, 0)
                if not (name_item and name_item.text().strip()):
                    self.set_item_locked(r, 6, "", should_lock=False)
        finally:
            self.table.blockSignals(False)
        self._fill_all_cn_gaps()

    def manual_save_and_sort(self):
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

            # Sort named rows by Part No (col 5) A→Z
            named_rows.sort(key=lambda x: x[5].strip().upper())

            # Sort empty rows by CN (col 6) numerically
            def _cn_sort_key(row_data):
                try:
                    return int(row_data[6].strip())
                except (ValueError, TypeError):
                    return float('inf')  # blank CN sorts last
            empty_rows.sort(key=_cn_sort_key)

            # Write sorted rows back to table
            all_rows = named_rows + empty_rows
            total_needed = max(200, len(named_rows) + 50)  # always 50+ buffer rows
            if self.table.rowCount() < total_needed:
                self.table.setRowCount(total_needed)
            for r, row_data in enumerate(all_rows):
                for c, val in enumerate(row_data):
                    align = Qt.AlignmentFlag.AlignLeft
                    is_locked = False
                    if c == 1: align = Qt.AlignmentFlag.AlignRight
                    if c in (2, 5, 6): align = Qt.AlignmentFlag.AlignCenter
                    if c in (2, 5): is_locked = True
                    self.table.setItem(r, c, self.create_table_item(val, align, is_locked))

            # 3. Safety net: fill any named rows missing a CN, and give CNs to
            #    any newly added empty buffer rows.
            self.table.blockSignals(False)
            self._fill_all_cn_gaps()
            self.table.blockSignals(True)

        except Exception as e:
            print(f"Error during save/sort: {e}")
        finally:
            self._signals_blocked = False
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
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(self.paint_table)
        preview.resize(900, 680)
        preview.exec()

    def paint_table(self, printer):
        """Draw the table directly using QPainter for pixel-perfect A4 output.

        Items 10, 11, 12:
        - A4 paper size (set in handle_print_preview)
        - Column widths derived from actual screen column widths (proportional)
        - Page number and print date printed in a footer on every page
        """
        painter = QPainter()
        if not painter.begin(printer):
            return

        page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
        page_w = page_rect.width()
        page_h = page_rect.height()

        # --- Fonts ---
        header_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        cell_font   = QFont("Segoe UI", 9)
        footer_font = QFont("Segoe UI", 8)

        painter.setFont(header_font)
        fm_header = painter.fontMetrics()
        header_height = int(fm_header.height() * 1.8)

        painter.setFont(cell_font)
        fm_cell   = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.6)
        padding    = int(fm_cell.averageCharWidth() * 1.5)

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
        usable_h = page_h - footer_height - padding

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
        today_str = _date.today().strftime("%Y-%m-%d")

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

        # --- Render pages ---
        page_num = 1
        y = 0
        y = draw_header(y)

        for row_data in data_rows:
            if y + row_height > usable_h:
                draw_footer(page_num)
                printer.newPage()
                page_num += 1
                y = 0
                y = draw_header(y)
            y = draw_row(y, row_data)

        draw_footer(page_num)  # Footer on last page
        painter.end()

