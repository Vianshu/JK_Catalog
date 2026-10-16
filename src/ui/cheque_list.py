import os
import uuid as _uuid_mod
from src.ui.table_nav_mixin import ExcelTableMixin
import pandas as pd
from PyQt6.QtWidgets import (
    QComboBox,
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QLineEdit, QLabel, QHeaderView,
    QPushButton, QCompleter, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QAbstractItemView, QStyledItemDelegate, QSplitter, QDialog
)

from PyQt6.QtGui import QTextDocument, QPageSize, QPageLayout, QFont, QPainter, QPen, QColor, QFontMetrics, QBrush
from PyQt6.QtCore import Qt, QEvent, QSettings, QSizeF, QMarginsF, QRect, QTimer
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from difflib import SequenceMatcher
from src.logic.db_manager import get_db_manager, build_logical_name
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from src.ui.ui_helpers import pick_export_folder

from src.ui.table_nav_mixin import (
    ExcelTableMixin, UniversalCellDelegate, 
    CELL_TYPE_ROLE, AUTOCOMPLETE_ITEMS_ROLE, 
    DISPLAY_CALLBACK_ROLE, SET_MODEL_DATA_CALLBACK_ROLE
)

# Custom data roles for GUID/bank-ref storage (invisible to user, stored behind display text)
_GUID_ROLE = Qt.ItemDataRole.UserRole + 20   # stores ledger GUID in party cells
_BREF_ROLE = Qt.ItemDataRole.UserRole + 21   # stores bank_ref UUID in bank cells


class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except Exception as e:
            return super().__lt__(other)

class ChequeListUI(ExcelTableMixin, QWidget):
    def _party_display_cb(self, index):
        guid = index.data(_GUID_ROLE)
        if guid:
            name = self.guid_to_name.get(guid, "")
            if not name:
                return f"[Not found: {guid[:8]}…]"
            return name
        return index.data(Qt.ItemDataRole.DisplayRole)

    def _bank_display_cb(self, index):
        bref = index.data(_BREF_ROLE)
        if bref:
            name = self.bref_to_name.get(bref, "")
            if name:
                return name
            # bref exists but not in map (stale ref after bank was deleted) — show raw text
        return index.data(Qt.ItemDataRole.DisplayRole)
        
    def _match_autocomplete_val(self, val, data_list):
        if not val or not data_list:
            return None
        val_str = str(val).strip()
        val_lower = val_str.lower()
        # 1. Exact case-insensitive match
        for item in data_list:
            if val_lower == str(item).lower().strip():
                return item
        # 2. Normalized match (ignoring spaces, punctuation)
        from src.ui.table_nav_mixin import _norm
        val_norm = _norm(val_str)
        if val_norm:
            for item in data_list:
                if val_norm == _norm(str(item)):
                    return item
        # 3. Substring match
        for item in sorted(str(x) for x in data_list):
            if val_lower in str(item).lower():
                return item
        # 4. Normalized substring match
        if val_norm:
            for item in sorted(str(x) for x in data_list):
                if val_norm in _norm(str(item)):
                    return item
        return None

    def _party_set_model_cb(self, val, index):
        model = index.model()
        if not val:
            self.table.blockSignals(True)
            model.setData(index, "", Qt.ItemDataRole.EditRole)
            model.setData(index, "", Qt.ItemDataRole.DisplayRole)
            model.setData(index, None, _GUID_ROLE)
            self.table.blockSignals(False)
            self.table.viewport().update()
            self.save_cheques_to_db()
            return
            
        data_list = list(self.party_mapping.keys())
        matched = self._match_autocomplete_val(val, data_list)
        if not matched:
            return # reject
            
        # Resolve to canonical name first
        val_lower = matched.lower()
        for alias, name in self.party_mapping.items():
            if alias.lower() == val_lower:
                matched = name
                break
        
        guid = self.name_to_guid.get(matched, "") or self.name_to_guid.get(val_lower, "")
        # Block signals so save fires once with both values already set
        self.table.blockSignals(True)
        model.setData(index, matched, Qt.ItemDataRole.DisplayRole)
        model.setData(index, matched, Qt.ItemDataRole.EditRole)
        model.setData(index, guid, _GUID_ROLE)
        self.table.blockSignals(False)
        self.table.viewport().update()   # repaint so initStyleOption picks up the new name
        self.save_cheques_to_db()

    def _bank_set_model_cb(self, val, index):
        model = index.model()
        if not val:
            self.table.blockSignals(True)
            model.setData(index, "", Qt.ItemDataRole.EditRole)
            model.setData(index, "", Qt.ItemDataRole.DisplayRole)
            model.setData(index, None, _BREF_ROLE)
            self.table.blockSignals(False)
            self.table.viewport().update()
            self.save_cheques_to_db()
            return
            
        matched = self._match_autocomplete_val(val, self.bank_list_data)
        if not matched:
            return # reject
            
        bref = self.bank_name_to_ref.get(matched, "") or self.bank_name_to_ref.get(matched.lower(), "")
        if not bref:
            bref = str(_uuid_mod.uuid4())
            self.bref_to_name[bref] = matched
            self.bank_name_to_ref[matched] = bref
            self.bank_name_to_ref[matched.lower()] = bref
            try:
                conn = self.db.get_connection(self.cheque_db_name)
                if conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bank_list SET bank_ref = ? WHERE bank_name = ? AND (bank_ref IS NULL OR bank_ref = '')", (bref, matched))
                    conn.commit()
            except Exception:
                pass

        # Block signals so save fires once with both values already set
        self.table.blockSignals(True)
        model.setData(index, matched, Qt.ItemDataRole.DisplayRole)
        model.setData(index, matched, Qt.ItemDataRole.EditRole)
        model.setData(index, bref, _BREF_ROLE)
        self.table.blockSignals(False)
        self.table.viewport().update()
        self.save_cheques_to_db()

    def _crm_set_model_cb(self, val, index):
        model = index.model()
        if not val:
            self.table.blockSignals(True)
            model.setData(index, "", Qt.ItemDataRole.EditRole)
            model.setData(index, "", Qt.ItemDataRole.DisplayRole)
            self.table.blockSignals(False)
            self.table.viewport().update()
            self.save_cheques_to_db()
            return
        matched = self._match_autocomplete_val(val, self.crm_list_data)
        if matched:
            self.table.blockSignals(True)
            model.setData(index, matched, Qt.ItemDataRole.EditRole)
            model.setData(index, matched, Qt.ItemDataRole.DisplayRole)
            self.table.blockSignals(False)
            self.table.viewport().update()
            self.save_cheques_to_db()

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
        self.party_mapping = {}        # alias/name -> canonical_name
        self.guid_to_name = {}         # ledger GUID -> canonical display name
        self.name_to_guid = {}         # canonical_name (lower) -> GUID
        self.bref_to_name = {}         # bank_ref UUID -> bank display name
        self.bank_name_to_ref = {}     # bank display name (lower) -> bank_ref UUID
        self._can_edit = True
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
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(["All cheques", "Cleared Cheques", "Uncleared Cheques"])
        self.cmb_filter.currentIndexChanged.connect(self.apply_filter)
        self.cmb_filter.setMinimumWidth(150)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setMinimumWidth(200)
        self.search_bar.textChanged.connect(self.apply_filter)
        
        top_bar.addWidget(self.cmb_filter)
        top_bar.addWidget(self.search_bar)

        # 2. Middle: Summary Labels
        top_bar.addStretch()

        # Font size controlled via #ChqSummaryLabel in style.qss
        _sum_font = QFont()
        _sum_font.setBold(True)
        self.lbl_count = QLabel("Chq. Count: 0")
        self.lbl_total = QLabel("₹ 0.00")
        self.lbl_count.setObjectName("ChqSummaryLabel")
        self.lbl_total.setObjectName("ChqSummaryLabel")
        self.lbl_count.setFont(_sum_font)
        self.lbl_total.setFont(_sum_font)


        top_bar.addWidget(self.lbl_count)
        top_bar.addWidget(self.lbl_total)

        top_bar.addStretch()

        # 3. Right Side: Utility Buttons
        self.btn_set_location = QPushButton("Set Location")
        self.btn_set_location.setObjectName("BtnOrange")
        self.btn_set_location.clicked.connect(self.set_export_location)

        self.btn_print = QPushButton("Print")
        self.btn_print.setObjectName("BtnBlue")
        self.btn_print.clicked.connect(self.print_table)

        self.btn_bank_list = QPushButton("Bank List")
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
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        # S.N stays fixed; data columns auto-size to content; Narration fills remainder
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 45)
        for i in range(1, 9):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
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
        # _init_excel_table sets UniversalCellDelegate as default
        self._init_excel_table(self.table)
        
        # Apply specific delegates for Date and Autocomplete columns
        self.table.setItemDelegateForColumn(1, UniversalCellDelegate(self, cell_type="date"))
        self.table.setItemDelegateForColumn(8, UniversalCellDelegate(self, cell_type="date"))
        
        party_del = UniversalCellDelegate(
            self, cell_type="autocomplete",
            autocomplete_items=lambda: list(self.party_mapping.keys()),
            display_cb=self._party_display_cb,
            set_model_cb=self._party_set_model_cb
        )
        self.table.setItemDelegateForColumn(2, party_del)
        
        bank_del = UniversalCellDelegate(
            self, cell_type="autocomplete",
            autocomplete_items=lambda: self.bank_list_data,
            display_cb=self._bank_display_cb,
            set_model_cb=self._bank_set_model_cb,
            enforce_match=False
        )
        self.table.setItemDelegateForColumn(3, bank_del)
        
        crm_del = UniversalCellDelegate(
            self, cell_type="autocomplete",
            autocomplete_items=lambda: self.crm_list_data,
            set_model_cb=self._crm_set_model_cb
        )
        self.table.setItemDelegateForColumn(5, crm_del)
        # _init_excel_table already connected cellDoubleClicked — no duplicate needed.

        # Inline stylesheet overrides global QSS cascade for font (Devanagari support)
        from src.ui.table_nav_mixin import UNIVERSAL_TABLE_STYLE
        self.table.setStyleSheet(UNIVERSAL_TABLE_STYLE + """
            QTableWidget { font-family: 'Noto Sans Devanagari'; font-size: 14pt; }
            QHeaderView::section { font-weight: normal; }
        """)

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
        self.bank_table.setStyleSheet("QHeaderView::section { font-weight: normal; }")
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
        self.btn_bank_list.setText("Hide Bank List" if show else "Bank List")

    def normalize_bank_name(self, name: str) -> str:
        name = name.lower().strip()
        for w in ["bank", "ltd", "ltd.", "limited"]:
            name = name.replace(w, "")
        return "".join(ch for ch in name if ch.isalpha() or ch == " ").strip()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        if hasattr(self, 'table'):
            if can_edit:
                self.table.setEditTriggers(
                    QAbstractItemView.EditTrigger.DoubleClicked |
                    QAbstractItemView.EditTrigger.AnyKeyPressed |
                    QAbstractItemView.EditTrigger.EditKeyPressed
                )
            else:
                self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        if hasattr(self, 'bank_table'):
            if can_edit:
                self.bank_table.setEditTriggers(
                    QAbstractItemView.EditTrigger.DoubleClicked |
                    QAbstractItemView.EditTrigger.EditKeyPressed
                )
            else:
                self.bank_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def is_similar_bank(self, a: str, b: str, threshold=0.85) -> bool:
        return SequenceMatcher(None, a, b).ratio() >= threshold
    def on_item_changed(self, item):
        if not getattr(self, '_can_edit', True): return
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
        text = self.search_bar.text().lower().strip()
        idx  = self.cmb_filter.currentIndex()  # 0=All, 1=Cleared, 2=Uncleared

        # Build inverted alias index: {hindi_name_lower → [alias_lower, ...]}
        # party_mapping is  {alias → canonical_name, name → canonical_name}
        # We need the reverse: canonical_name → all aliases that point to it
        name_to_aliases: dict[str, list[str]] = {}
        for alias, canonical in self.party_mapping.items():
            key = canonical.lower()
            if alias.lower() != key:            # only add true aliases, not self-maps
                name_to_aliases.setdefault(key, []).append(alias.lower())

        for r in range(self.table.rowCount()):
            clear_date_item = self.table.item(r, 8)
            clear_date = clear_date_item.text().strip() if clear_date_item else ""

            # ── Dropdown (status) filter ──────────────────────────────────────
            if idx == 1 and not clear_date:   # Cleared only → hide uncleared
                self.table.setRowHidden(r, True)
                continue
            if idx == 2 and clear_date:        # Uncleared only → hide cleared
                self.table.setRowHidden(r, True)
                continue

            # ── Text search ───────────────────────────────────────────────────
            if not text:
                self.table.setRowHidden(r, False)
                continue

            found = False

            # 1. Direct match in any visible cell (works for Hindi, numbers, dates, etc.)
            for c in range(self.table.columnCount()):
                w = self.table.cellWidget(r, c)
                if w and isinstance(w, QLineEdit):
                    cell_val = w.text().lower()
                else:
                    it = self.table.item(r, c)
                    cell_val = it.text().lower() if it else ""
                if text in cell_val:
                    found = True
                    break

            # 2. Alias fallback for Party Name (col 2):
            #    If the party name in the cell is Hindi, try English aliases
            if not found:
                party_it = self.table.item(r, 2)
                party_name_lower = party_it.text().strip().lower() if party_it else ""
                if party_name_lower:
                    for alias in name_to_aliases.get(party_name_lower, []):
                        if text in alias:
                            found = True
                            break

            self.table.setRowHidden(r, not found)

        self.update_summary()
        self.table.resizeColumnsToContents()  # re-fit columns after rows are shown/hidden
    
    # ================= DB =================
    def save_cheques_to_db(self):
        if not getattr(self, '_can_edit', True): return
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
                def _role(c, role, _r=r):
                    it = self.table.item(_r, c)
                    return it.data(role) if it else None
                party_guid = _role(2, _GUID_ROLE) or ""
                bank_ref   = _role(3, _BREF_ROLE) or ""
                rows_to_insert.append((
                    txt(0), txt(1), txt(2), txt(3),
                    txt(4), txt(5), txt(6), txt(7), txt(8), txt(9),
                    party_guid, bank_ref
                ))
            cur.execute("DELETE FROM cheques")
            if rows_to_insert:
                cur.executemany(
                    "INSERT INTO cheques VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows_to_insert)
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
        if not getattr(self, '_can_edit', True): return
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

        # DB Update Logic — preserve bank_ref UUIDs through renames via UserRole
        conn = self.db.get_connection(self.cheque_db_name)
        if not conn: return
        cur = conn.cursor()
        try:
            rows_to_insert = []
            save_idx = 1
            self.bank_list_data = []
            self.bref_to_name = {}
            self.bank_name_to_ref = {}

            for r in range(total_row_idx):
                it = self.bank_table.item(r, 1)
                if it and it.text().strip():
                    bname = it.text().strip()
                    # Read UUID stored in UserRole (set at load time; survives renames)
                    bref = (it.data(Qt.ItemDataRole.UserRole) or "").strip()
                    if not bref:
                        # New bank row that was never loaded from DB — generate a fresh UUID
                        bref = str(_uuid_mod.uuid4())
                    rows_to_insert.append((str(save_idx), bname, bref))
                    self.bank_list_data.append(bname)
                    self.bref_to_name[bref] = bname
                    self.bank_name_to_ref[bname.lower()] = bref
                    self.bank_name_to_ref[bname] = bref
                    save_idx += 1

            cur.execute("DELETE FROM bank_list")
            if rows_to_insert:
                cur.executemany("INSERT INTO bank_list (sn, bank_name, bank_ref) VALUES (?,?,?)",
                                rows_to_insert)
            conn.commit()

            # Write the (possibly new) bref back into UserRole so next save still finds it
            self.bank_table.blockSignals(True)
            save_r = 0
            for r in range(total_row_idx):
                it = self.bank_table.item(r, 1)
                if it and it.text().strip() and save_r < len(rows_to_insert):
                    it.setData(Qt.ItemDataRole.UserRole, rows_to_insert[save_r][2])  # bref
                    save_r += 1
                elif it:
                    it.setData(Qt.ItemDataRole.UserRole, "")  # clear stale ref on blank rows
            self.bank_table.blockSignals(False)

        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save bank_list: {e}")

        self.ensure_bank_row_capacity()

        # --- Live cheque table update ---
        # Identify the UUID of the bank row that was just renamed, using UserRole on the
        # bank_table item (which was updated in the write-back loop above).
        changed_bref = (item.data(Qt.ItemDataRole.UserRole) or "").strip()
        old_name_str  = (self._pre_bank_name or "").strip()
        new_name_str  = self.bref_to_name.get(changed_bref, "")

        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            bank_cell = self.table.item(r, 3)
            if not bank_cell:
                continue
            bref_on_cell = (bank_cell.data(_BREF_ROLE) or "").strip()
            if bref_on_cell and bref_on_cell in self.bref_to_name:
                # Delegate-driven row: keep DisplayRole in sync (paint() uses bref_to_name,
                # but having DisplayRole match avoids stale tooltip/search text)
                bank_cell.setText(self.bref_to_name[bref_on_cell])
            elif bank_cell.text().strip() == old_name_str and old_name_str and new_name_str:
                # Legacy row (no _BREF_ROLE stored): update display text directly
                bank_cell.setText(new_name_str)
        self.table.blockSignals(False)

        # Force repaint on next event loop tick so the cheque table shows new bank name
        QTimer.singleShot(0, self.table.viewport().repaint)
        self.save_cheques_to_db()
        self.update_bank_counts()


    # ================= SUMMARY =================
    def update_summary(self):
        """Count and sum cheques based on visible rows."""
        total = 0.0
        count = 0
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
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

        self.lbl_count.setText(f"Chq. Count: {count}")
        self.lbl_total.setText(f"₹ {total:,.2f}")
        self.update_bank_counts()


    def generate_sn(self, row_index):
        return f"{row_index + 1:04d}"

    def sort_table_safe(self, col_idx):
        """Sort the cheque table by col_idx, toggling Asc/Desc on repeated clicks.
        Blank rows (no party) stay pinned to the bottom. Numeric columns sort numerically.

        NOTE: We track state in self._sort_col / self._sort_asc rather than reading
        header.sortIndicatorSection/Order because Qt auto-updates the header indicator
        BEFORE sectionClicked fires, so the header values are already wrong by the time
        our handler runs.
        """
        header = self.table.horizontalHeader()

        # --- Our own state (reliable toggle) ---
        prev_col = getattr(self, '_sort_col', -1)
        prev_asc = getattr(self, '_sort_asc', True)

        if prev_col == col_idx:
            asc = not prev_asc          # same column → flip
        else:
            asc = True                  # new column → start Ascending

        self._sort_col = col_idx
        self._sort_asc = asc

        new_order = Qt.SortOrder.AscendingOrder if asc else Qt.SortOrder.DescendingOrder

        # Numeric columns: S.N (0), Amount (6)
        NUMERIC_COLS = {0, 6}

        def cell_key(row):
            """Return (is_blank, sort_value) so blank rows always sink to bottom."""
            party = self.table.item(row, 2)
            is_blank = not (party and party.text().strip())
            it = self.table.item(row, col_idx)
            raw = it.text().strip() if it else ""
            if col_idx in NUMERIC_COLS:
                try:
                    val = float(raw.replace(",", ""))
                except ValueError:
                    val = float("-inf") if asc else float("inf")
            else:
                val = raw.lower()
            return (is_blank, val)

        n = self.table.rowCount()
        rows = list(range(n))
        rows.sort(key=cell_key, reverse=not asc)

        # Snapshot all row data (items + roles) before reordering
        def snapshot_row(r):
            snap = []
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it:
                    snap.append({
                        "text":  it.text(),
                        "guid":  it.data(_GUID_ROLE),
                        "bref":  it.data(_BREF_ROLE),
                        "align": it.textAlignment(),
                        "hidden": self.table.isRowHidden(r),
                    })
                else:
                    snap.append(None)
            return snap

        snapshots = [snapshot_row(r) for r in rows]

        self.table.blockSignals(True)
        for dest, snap in enumerate(snapshots):
            for c, cell in enumerate(snap):
                if cell is None:
                    self.table.setItem(dest, c, QTableWidgetItem(""))
                else:
                    new_it = QTableWidgetItem(cell["text"])
                    if cell["align"]:
                        new_it.setTextAlignment(cell["align"])
                    if cell["guid"] is not None:
                        new_it.setData(_GUID_ROLE, cell["guid"])
                    if cell["bref"] is not None:
                        new_it.setData(_BREF_ROLE, cell["bref"])
                    self.table.setItem(dest, c, new_it)
            self.table.setRowHidden(dest, snap[0]["hidden"] if snap[0] else False)
        self.table.blockSignals(False)

        header.setSortIndicator(col_idx, new_order)


    def ensure_cheque_schema(self):
        cols = self.db.get_table_columns(self.cheque_db_name, "cheques")
        if "clear_date" not in cols:
            self.db.add_column(self.cheque_db_name, "cheques", "clear_date", "NVARCHAR(MAX)")
        if "narration" not in cols:
            self.db.add_column(self.cheque_db_name, "cheques", "narration", "NVARCHAR(MAX)")

    def _ensure_linked_schema(self):
        """Add party_guid and bank_ref columns to cheques and bank_ref to bank_list (one-time migration)."""
        # cheques.party_guid — stores Tally GUID for party
        cols_chq = self.db.get_table_columns(self.cheque_db_name, "cheques")
        if "party_guid" not in cols_chq:
            self.db.add_column(self.cheque_db_name, "cheques", "party_guid", "NVARCHAR(200)")
        # cheques.bank_ref — stores stable UUID for bank
        if "bank_ref" not in cols_chq:
            self.db.add_column(self.cheque_db_name, "cheques", "bank_ref", "NVARCHAR(100)")
        # bank_list.bank_ref — stable UUID per bank row
        cols_bl = self.db.get_table_columns(self.cheque_db_name, "bank_list")
        if "bank_ref" not in cols_bl:
            self.db.add_column(self.cheque_db_name, "bank_list", "bank_ref", "NVARCHAR(100)")
            # Generate UUIDs for all existing bank rows
            conn = self.db.get_connection(self.cheque_db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("SELECT sn, bank_name FROM bank_list")
                    rows = cur.fetchall()
                    for sn, bname in rows:
                        new_ref = str(_uuid_mod.uuid4())
                        cur.execute("UPDATE bank_list SET bank_ref=? WHERE sn=?", (new_ref, sn))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print("[CHEQUE] _ensure_linked_schema bank_ref error:", e)

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
            data = []  # [(existing_sn_int | None, row_values_list, party_guid, bank_ref)]

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
                    # Snapshot custom roles so they survive the setRowCount(0) wipe
                    p_it = self.table.item(r, 2)
                    b_it = self.table.item(r, 3)
                    party_guid = p_it.data(_GUID_ROLE) if p_it else None
                    bank_ref   = b_it.data(_BREF_ROLE) if b_it else None
                    data.append((existing_sn, row, party_guid, bank_ref))

            # Track SN integers already claimed by data rows so buffer rows skip them
            used_sns = {sn for sn, _, _, _ in data if sn is not None}
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
            for existing_sn, row_data, party_guid, bank_ref in data:
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
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    elif c == 6:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif c == 7:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    else:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    # Restore custom roles (critical: _party_display_cb needs _GUID_ROLE)
                    if c == 2 and party_guid:
                        item.setData(_GUID_ROLE, party_guid)
                    elif c == 3 and bank_ref:
                        item.setData(_BREF_ROLE, bank_ref)
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
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                        else:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        self.table.setItem(idx, c, item)
        finally:
            self.table.blockSignals(False)


    def update_bank_counts(self):
        # Count by bank_ref UUID so renames don't break counts
        counts_by_ref  = {}   # bank_ref  -> count
        counts_by_name = {}   # bank_name -> count (fallback for unlinked rows)
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            it = self.table.item(r, 3)  # Bank column
            if it:
                bref = it.data(_BREF_ROLE)
                if bref:
                    counts_by_ref[bref] = counts_by_ref.get(bref, 0) + 1
                else:
                    # Legacy row without bank_ref — fall back to name matching
                    name = it.text().strip()
                    if name:
                        counts_by_name[name] = counts_by_name.get(name, 0) + 1
        
        self.bank_table.blockSignals(True)
        try:
            total_count = 0
            total_row_idx = self.bank_table.rowCount() - 1
            
            for r in range(total_row_idx):
                bank_name_item = self.bank_table.item(r, 1)
                if bank_name_item:
                    bn = bank_name_item.text().strip()
                    if bn:
                        # Look up by bank_ref first, fall back to name
                        bref = self.bank_name_to_ref.get(bn.lower(), "")
                        if bref and bref in counts_by_ref:
                            count_val = counts_by_ref[bref]
                        else:
                            count_val = counts_by_name.get(bn, 0)
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
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "Kya aap saare cleared cheques (jinka Clear Date bhara hua hai) hatana chahte hain?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Cleared cheques are identified by a non-empty clear_date (column 8),
            # NOT by status = 'C' (which is never written — 'c' is auto-corrected to 'Cash').
            self.db.execute_query(
                self.cheque_db_name,
                "DELETE FROM cheques WHERE clear_date IS NOT NULL AND clear_date != ''",
                fetch=False
            )
            self.load_all_data()

    def set_company_path(self, path):
        self.company_path = path
        self.db_path = os.path.join(path, "chq_list.db")  # Legacy
        company_name = os.path.basename(path)
        self.cheque_db_name = build_logical_name(company_name, company_path=path)
        self.ledger_db_name = build_logical_name(company_name, company_path=path)

        # Clear search bar on company load/switch, preserving current filter selection
        if hasattr(self, 'search_bar'):
            self.search_bar.blockSignals(True)
            self.search_bar.clear()
            self.search_bar.blockSignals(False)

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
        self._ensure_linked_schema()   # adds party_guid, bank_ref columns
        self.load_all_data()

    def load_all_data(self):
        if not self.cheque_db_name: return
        self._reload_dropdown_data()
        conn = self.db.get_connection(self.cheque_db_name)
        if not conn: return
        cursor = conn.cursor()
        
        # ── Bank list: build bref_to_name & bank_name_to_ref maps ──
        try:
            cursor.execute("SELECT sn, bank_name, bank_ref FROM bank_list")
            bnks = cursor.fetchall()
        except Exception:
            cursor.execute("SELECT sn, bank_name FROM bank_list")
            bnks = [(r[0], r[1], "") for r in cursor.fetchall()]

        self.bref_to_name = {}
        self.bank_name_to_ref = {}
        for sn, bname, bref in bnks:
            bname = (bname or "").strip()
            bref  = (bref  or "").strip()
            if bname:
                self.bref_to_name[bref] = bname
                self.bank_name_to_ref[bname.lower()] = bref
                self.bank_name_to_ref[bname] = bref

        self.bank_table.blockSignals(True)
        try:
            total_required_rows = max(30, len(bnks)+10)
            self.bank_table.setRowCount(total_required_rows)
            total_idx = total_required_rows - 1
            for i in range(total_idx):
                self.bank_table.setItem(i, 0, QTableWidgetItem(str(i+1)))
                self.bank_table.setItem(i, 1, QTableWidgetItem(""))
                self.bank_table.setItem(i, 2, QTableWidgetItem(""))
            for r, (sn, bname, bref) in enumerate(bnks):
                name_item = QTableWidgetItem(bname or "")
                name_item.setData(Qt.ItemDataRole.UserRole, bref or "")  # preserve UUID through renames
                self.bank_table.setItem(r, 1, name_item)
            self.bank_table.setItem(total_idx, 0, QTableWidgetItem(""))
            total_lbl = QTableWidgetItem("Total")
            total_lbl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.bank_table.setItem(total_idx, 1, total_lbl)
            self.bank_table.setItem(total_idx, 2, QTableWidgetItem(""))
        finally:
            self.bank_table.blockSignals(False)
        self.bank_list_data = [b[1] for b in bnks if b[1]]

        # ── Cheque list: resolve party_guid and bank_ref to display names ──
        try:
            cursor.execute("SELECT sn,date,party,bank,chq_no,crm,amount,status,clear_date,narration,party_guid,bank_ref FROM cheques")
            chqs = cursor.fetchall()
            has_linked_cols = True
        except Exception:
            cursor.execute("SELECT * FROM cheques")
            chqs = cursor.fetchall()
            has_linked_cols = False

        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(chqs))
            for r, row in enumerate(chqs):
                # First 10 cols are the core fields
                party_guid = row[10] if has_linked_cols and len(row) > 10 else ""
                bank_ref   = row[11] if has_linked_cols and len(row) > 11 else ""
                party_guid = (party_guid or "").strip()
                bank_ref   = (bank_ref   or "").strip()

                # Migration: if no GUID stored yet but party text matches a ledger name, resolve it
                if not party_guid:
                    raw_party = (row[2] or "").strip()
                    if raw_party:
                        party_guid = self.name_to_guid.get(raw_party.lower(), "")

                # Migration: if no bank_ref stored yet but bank text matches a bank_name, resolve it
                if not bank_ref:
                    raw_bank = (row[3] or "").strip()
                    if raw_bank:
                        bank_ref = self.bank_name_to_ref.get(raw_bank.lower(), "")

                for c, v in enumerate(row[:10]):
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

                    # Attach hidden ID roles for party and bank
                    if c == 2 and party_guid:
                        item.setData(_GUID_ROLE, party_guid)
                    elif c == 3 and bank_ref:
                        item.setData(_BREF_ROLE, bank_ref)

                    self.table.setItem(r, c, item)
        finally:
            self.table.blockSignals(False)
        
        # --- 3. Final Triggers (सही क्रम) ---
        self.sync_cheque_rows()      # रोज़ को सिंक करें
        self.apply_filter()          # Apply current filter and update summary/bank counts
        self.table.resizeColumnsToContents()
        
        # Column widths already set in setup_ui via balanced _col_widths
    
    def showEvent(self, event):
        super().showEvent(event)
        self._reload_dropdown_data()
        self.apply_filter()
        self.table.resizeColumnsToContents()  # re-fit columns every time the tab is opened
    
    def refresh_ledger_maps(self):
        """Re-load guid_to_name / name_to_guid from row_ledger_data after a Tally ledger sync.
        Repaints the party column so all cells show updated names immediately.
        Safe to call from any thread via QTimer.singleShot(0, ...).
        """
        if not self.ledger_db_name:
            return
        try:
            l_conn = self.db.get_connection(self.ledger_db_name)
            if not l_conn:
                return
            l_cursor = l_conn.cursor()
            l_cursor.execute(
                "SELECT GUID, Alias, Name FROM row_ledger_data "
                "WHERE [Group] LIKE '%Sundry Debtors%'"
            )
            new_guid_to_name = {}
            new_name_to_guid = {}
            new_party_mapping = {}
            for guid, alias, name in l_cursor.fetchall():
                name_str  = str(name).strip()  if name  and str(name).strip().lower()  != "none" else ""
                alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
                guid_str  = str(guid).strip()  if guid  and str(guid).strip().lower()  != "none" else ""
                if alias_str:
                    new_party_mapping[alias_str] = name_str
                if name_str:
                    new_party_mapping[name_str] = name_str
                if guid_str and name_str:
                    new_guid_to_name[guid_str] = name_str
                    new_name_to_guid[name_str.lower()] = guid_str
                    if alias_str:
                        new_name_to_guid[alias_str.lower()] = guid_str
            # Atomic swap so delegate always sees a consistent map
            self.guid_to_name  = new_guid_to_name
            self.name_to_guid  = new_name_to_guid
            self.party_mapping = new_party_mapping
            # Repaint party column so new names appear without a full reload
            self.table.viewport().update()
            print(f"[CHEQUE] Ledger maps refreshed: {len(new_guid_to_name)} entries")
        except Exception as e:
            print("[CHEQUE] refresh_ledger_maps error:", e)

    def _reload_dropdown_data(self):
        """Refresh party names, CRM, and bank list from SQL Server.
        Called every time the tab becomes visible."""
        if not self.ledger_db_name:
            return

        # 1. CRM Data
        from src.ui.settings import load_crm_list
        self.crm_list_data = load_crm_list(self.company_path)

        # 2. Party Mapping (Sundry Debtors: Alias + Name searchable) + GUID maps
        self.party_mapping = {}
        self.guid_to_name = {}
        self.name_to_guid = {}
        try:
            l_conn = self.db.get_connection(self.ledger_db_name)
            if l_conn:
                l_cursor = l_conn.cursor()
                l_cursor.execute("SELECT GUID, Alias, Name FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
                for guid, alias, name in l_cursor.fetchall():
                    name_str  = str(name).strip()  if name  and str(name).strip().lower()  != "none" else ""
                    alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
                    guid_str  = str(guid).strip()  if guid  and str(guid).strip().lower()  != "none" else ""
                    if alias_str:
                        self.party_mapping[alias_str] = name_str
                    if name_str:
                        self.party_mapping[name_str] = name_str
                    if guid_str and name_str:
                        self.guid_to_name[guid_str] = name_str
                        self.name_to_guid[name_str.lower()] = guid_str
                        if alias_str:
                            self.name_to_guid[alias_str.lower()] = guid_str
        except Exception as e:
            print("[CHEQUE] Error loading ledger:", e)

        # 3. Bank list refresh
        try:
            conn = self.db.get_connection(self.cheque_db_name)
            if conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT bank_name, bank_ref FROM bank_list")
                    bnks = cursor.fetchall()
                except Exception:
                    cursor.execute("SELECT bank_name FROM bank_list")
                    bnks = [(r[0], "") for r in cursor.fetchall()]

                self.bank_list_data = []
                for bname, bref in bnks:
                    bname = (bname or "").strip()
                    bref  = (bref  or "").strip()
                    if bname:
                        self.bank_list_data.append(bname)
                        if bref:
                            self.bref_to_name[bref] = bname
                            self.bank_name_to_ref[bname.lower()] = bref
                            self.bank_name_to_ref[bname] = bref
        except Exception:
            pass
    
    def apply_initial_hide(self):
        """App start logic to apply current filter to table rows."""
        self.apply_filter()
                
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
        title_font = QFont("Noto Sans Devanagari", 15, QFont.Weight.Bold)
        header_font = QFont("Noto Sans Devanagari", 13, QFont.Weight.Normal)
        cell_font = QFont("Noto Sans Devanagari", 12)

        # Measure using painter's coordinate system (printer DPI, not screen DPI)
        painter.setFont(title_font)
        title_height = int(painter.fontMetrics().height() * 2.2)

        painter.setFont(header_font)
        header_height = int(painter.fontMetrics().height() * 1.3)

        painter.setFont(cell_font)
        fm_cell = painter.fontMetrics()
        row_height = int(fm_cell.height() * 1.15)
        h_pad = int(fm_cell.averageCharWidth() * 0.3)

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
            max_w = fm_h.horizontalAdvance(self.columns[c]) + 2 * h_pad
            for rd in data_rows:
                w = fm_c.horizontalAdvance(rd[c]) + 2 * h_pad
                if w > max_w:
                    max_w = w
            raw_widths.append(max(max_w, h_pad * 3))  # enforce a minimum

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
                text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, header_height)
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
                text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, row_height)
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

    def _reset_edit_mode(self, cr=None, cc=None, pr=None, pc=None):
        pass
    def _on_selection_changed(self):
        pass

