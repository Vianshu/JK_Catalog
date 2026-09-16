# -*- coding: utf-8 -*-
# =============================================================================
# anil_hisab_tab.py — AnilHisabTab (Running Balance Ledger)
# =============================================================================
import os
import re as _re
import json as _json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QApplication, QAbstractScrollArea, QFileDialog,
    QColorDialog, QTextEdit, QStyledItemDelegate, QStyle,
    QAbstractItemDelegate,
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QMimeData, QSettings, QRect,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QKeySequence,
    QShortcut, QCursor, QImage, QPen, QFontMetrics,
)
from src.logic.db_manager import get_db_manager, build_logical_name
from .shared import (
    _PrintExportMixin, ModernTableDelegate,
    _bold_font, _norm_font,
    _SCROLLBAR_STYLE, _TABLE_STYLE, _SECTION_HEADER_STYLE,
    _BTN_PRIMARY, _BTN_SECONDARY, _BTN_DANGER,
    _MENU_STYLE, _POPUP_STYLE, _CARD_MENU_STYLE,
    _setup_smart_header, _setup_sn_header, _DbTable,
    RAW_NUMERIC_ROLE,
)

# ===========================================================================
# ANIL DAI HISAB TAB — Running Balance Ledger
# ===========================================================================
_ANIL_COLS = [
    ("Start Date",  110), ("End Date",  110), ("Days",   55),
    ("Particular",  200), ("DR",        120), ("Cr.",    120),
    ("Balance",     135),
]
_ANIL_DR  = 4
_ANIL_CR  = 5
_ANIL_BAL = 6
_R = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
_C = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
_L = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


class _ReadOnlyDelegate(ModernTableDelegate):
    """Delegate that refuses to open an editor — makes a column truly read-only.
    Inherits ModernTableDelegate so painting stays consistent with other cells."""
    def createEditor(self, parent, option, index):
        return None  # no editor → cell is not editable


class _StartDateDelegate(ModernTableDelegate):
    """Start Date column:
      Respects the parent tab's _start_date_locked flag.
      Row 0  → always editable.
      Rows 1+→ editable only when lock is OFF.
    """
    def __init__(self, parent_table, tab_ref):
        super().__init__(parent_table)
        self._tab = tab_ref  # reference to AnilHisabTab to read lock state

    def createEditor(self, parent, option, index):
        if index.row() == 0:
            return super().createEditor(parent, option, index)
        if getattr(self._tab, '_start_date_locked', True):
            return None  # locked — no editor
        return super().createEditor(parent, option, index)


def _fmt(val):
    """Format numeric value as integer with thousands separator (no decimals shown)."""
    if val is None or val == "":
        return ""
    try:
        fv = float(str(val).replace(",", "").strip())
        return f"{int(round(fv)):,}"
    except Exception:
        return str(val)


def _fmt_dr(val):
    """Format DR debit/interest value rounded off to nearest integer (blank if 0)."""
    if val is None or val == "" or val == 0 or val == "0" or val == 0.0:
        return ""
    try:
        fv = float(str(val).replace(",", "").strip())
        rounded = int(round(fv))
        if rounded == 0:
            return ""
        return f"{rounded:,}"
    except Exception:
        return str(val)


class AnilHisabTab(QWidget, _PrintExportMixin):
    @staticmethod
    def _align_for_col(c):
        if c in (0, 1, 2):
            return _C
        elif c == 3 or c >= len(_ANIL_COLS):
            return _L
        return _R
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._start_date_locked = True  # Start Date col (rows 1+) locked by default
        self._loading = False
        self._load_failed = False
        self._loaded_row_count = 0
        self._interest_rate = 0.18      # Configurable annual interest rate (defaults to 18%)

        self._db_name  = ""
        self._db       = get_db_manager()

        # Debounce timer for header state saving (M-09)
        from PyQt6.QtCore import QTimer
        self._hdr_save_timer = QTimer(self)
        self._hdr_save_timer.setSingleShot(True)
        self._hdr_save_timer.setInterval(500)
        self._hdr_save_timer.timeout.connect(self._save_header_state)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Table
        n = len(_ANIL_COLS)
        self.table = QTableWidget(0, n)
        self.table.setFont(_norm_font())

        # Right Bar
        right_bar = QWidget()
        right_bar.setStyleSheet("background:#f8fafc; border-left:1px solid #e2e8f0;")
        right_bar.setFixedWidth(52)
        tlay = QVBoxLayout(right_bar)
        tlay.setContentsMargins(6, 16, 6, 16)
        tlay.setSpacing(12)

        def on_toggle_anil(expanded):
            if expanded:
                self._btn_add.setText(" Add Row")
                self._btn_add_col.setText(" Add Column")
            else:
                self._btn_add.setText("")
                self._btn_add_col.setText("")
        
        self._init_print_export(tlay, "Anil Dai Hisab",
                                  table_getter=lambda: [{"title": "", "table": self.table}], right_bar=right_bar, on_toggle_cb=on_toggle_anil)

        from src.ui.supp_payment.shared import get_icon
        self._btn_add = QPushButton()
        self._btn_add.setIcon(get_icon("add.svg"))
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.setToolTip("Add Row")
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)

        self._btn_add_col = QPushButton()
        self._btn_add_col.setIcon(get_icon("add.svg"))
        self._btn_add_col.setStyleSheet(_BTN_SECONDARY)
        self._btn_add_col.setFixedHeight(32)
        self._btn_add_col.setToolTip("Add Column")
        self._btn_add_col.clicked.connect(lambda: self._insert_custom_col())
        tlay.addWidget(self._btn_add_col)
        
        tlay.addStretch()
        
        layout.addWidget(self.table, 1)
        layout.addWidget(right_bar, 0)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(_TABLE_STYLE)
        
        self._custom_cols = []
        self._init_columns()
        _setup_smart_header(self.table)
        try:
            self.table.horizontalHeader().customContextMenuRequested.disconnect(self.table._smart_hdr_menu)
        except Exception:
            pass
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        _setup_sn_header(self.table)
        from PyQt6.QtCore import QSettings
        settings = QSettings("TallySync", "SuppPayment")
        self._show_sn = settings.value("show_sn_anil_hisab", False, type=bool)
        self.table.verticalHeader().setVisible(self._show_sn)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setItemDelegate(ModernTableDelegate(self.table))

        # Date delegate on End Date (1), Start Date (0) uses the lock-aware delegate
        self.table.setItemDelegateForColumn(0, _StartDateDelegate(self.table, self))
        self.table.setItemDelegateForColumn(1, ModernTableDelegate(self.table, cell_type="date"))
        # Balance (6) and Days (2) are read-only formula columns
        for _fc in (2, _ANIL_BAL):
            self.table.setItemDelegateForColumn(_fc, _ReadOnlyDelegate(self.table))

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)
        
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._header_ctx)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self._hdr_save_timer.start())
        self.table.horizontalHeader().sectionMoved.connect(lambda *_: self._hdr_save_timer.start())

        self.table.cellChanged.connect(self._on_cell_changed)


    def _init_columns(self):
        total_cols = len(_ANIL_COLS) + len(self._custom_cols)
        self.table.setColumnCount(total_cols)
        labels = [c[0] for c in _ANIL_COLS] + self._custom_cols
        self.table.setHorizontalHeaderLabels(labels)
        for i, (_, w) in enumerate(_ANIL_COLS):
            self.table.setColumnWidth(i, w)
        for i in range(len(_ANIL_COLS), total_cols):
            self.table.setColumnWidth(i, 120)
            self.table.setItemDelegateForColumn(i, ModernTableDelegate(self.table))
        # Ensure formula columns remain read-only
        self.table.setItemDelegateForColumn(2, _ReadOnlyDelegate(self.table))
        self.table.setItemDelegateForColumn(_ANIL_BAL, _ReadOnlyDelegate(self.table))
        self.table.setItemDelegateForColumn(0, _StartDateDelegate(self.table, self))
        self.table.setItemDelegateForColumn(1, ModernTableDelegate(self.table, cell_type="date"))

    def _load_custom_columns(self):
        self._custom_cols = []
        if not self._db_name:
            return
        # 1. Try anil_settings
        try:
            rows = self._db.execute_query(
                self._db_name,
                "SELECT value FROM anil_settings WHERE [key]='custom_cols'"
            ) or []
            if rows and rows[0][0]:
                loaded = _json.loads(rows[0][0])
                if isinstance(loaded, list):
                    self._custom_cols = [str(c).strip() for c in loaded if str(c).strip()]
        except Exception:
            self._custom_cols = []

        # Validate that custom columns actually exist in anil_ledger table
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='anil_ledger'"
                    )
                    existing_cols = {r[0].lower() for r in cur.fetchall()}
                    self._custom_cols = [c for c in self._custom_cols if c.lower() in existing_cols]
                finally:
                    cur.close()
        except Exception:
            pass

        self._init_columns()

    def _save_custom_columns(self):
        if not self._db_name:
            return
        try:
            val = _json.dumps(self._custom_cols)
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "IF EXISTS (SELECT 1 FROM anil_settings WHERE [key]='custom_cols') "
                        "UPDATE anil_settings SET value=? WHERE [key]='custom_cols' "
                        "ELSE INSERT INTO anil_settings ([key],value) VALUES ('custom_cols',?)",
                        (val, val)
                    )
                    conn.commit()
                finally:
                    cur.close()
        except Exception as e:
            from src.utils.app_logger import get_logger
            get_logger(__name__).error(f"[AnilHisab] _save_custom_columns failed: {e}")

    def _insert_custom_col(self, visual_idx=None):
        if not self._can_edit:
            return
        from .shared import _styled_get_text
        name, ok = _styled_get_text(self, "New Column", "Column Name:")
        if not ok or not name or not name.strip():
            return
        
        raw_name = name.strip()
        safe_name = _re.sub(r'[\[\]\'"`;]', '', raw_name).strip()
        if not safe_name:
            return

        # H-08: Strict allowlist validation to prevent SQL/DDL injection
        if not _re.fullmatch(r'^[A-Za-z0-9_ ]+$', safe_name):
            QMessageBox.warning(self, "Invalid Name", "Column name may only contain letters, numbers, underscores, and spaces.")
            return

        base_names = [c[0].lower() for c in _ANIL_COLS] + ["balance", "id", "sort_order"]
        if safe_name.lower() in base_names:
            QMessageBox.warning(self, "Invalid Name", f"'{safe_name}' is a reserved column name.")
            return

        if safe_name.lower() in [c.lower() for c in self._custom_cols]:
            QMessageBox.warning(self, "Column Exists", f"Column '{safe_name}' already exists.")
            return

        # 1. Alter SQL Table if column doesn't exist yet
        if self._db_name:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME='anil_ledger' AND LOWER(COLUMN_NAME)=LOWER(?)",
                        (safe_name,)
                    )
                    already_in_table = cur.fetchone() is not None
                    if not already_in_table:
                        cur.execute(f"ALTER TABLE anil_ledger ADD [{safe_name}] NVARCHAR(MAX)")
                        conn.commit()
                except Exception as e:
                    conn.rollback()
                    from src.utils.app_logger import get_logger
                    get_logger(__name__).error(f"[AnilHisab] ALTER TABLE ADD [{safe_name}] failed: {e}")
                    QMessageBox.critical(self, "Database Error", f"Failed to add column to database:\n{e}")
                    return
                finally:
                    cur.close()

        # 2. Update UI
        self.table.blockSignals(True)
        logical_idx = self.table.columnCount()
        self.table.insertColumn(logical_idx)
        self.table.setHorizontalHeaderItem(logical_idx, QTableWidgetItem(safe_name))
        self.table.setColumnWidth(logical_idx, 120)
        self.table.setItemDelegateForColumn(logical_idx, ModernTableDelegate(self.table))

        for r in range(self.table.rowCount()):
            self.table.setItem(r, logical_idx, self._a_item("", _L))
        self.table.blockSignals(False)

        # 3. Move visually if requested
        if visual_idx is not None and len(_ANIL_COLS) <= visual_idx < logical_idx:
            self.table.horizontalHeader().moveSection(logical_idx, visual_idx)

        self._custom_cols.append(safe_name)
        self._save_custom_columns()
        self._save_header_state()
        self._save_all()

    def _rename_custom_col(self, col):
        if col < len(_ANIL_COLS):
            return
        h = self.table.horizontalHeaderItem(col)
        old_name = h.text() if h else ""
        from .shared import _styled_get_text
        name, ok = _styled_get_text(self, "Rename Column", "New Name:", text=old_name)
        if not ok or not name or not name.strip():
            return
        new_name = _re.sub(r'[\[\]\'"`;]', '', name.strip()).strip()
        if not new_name or new_name.lower() == old_name.lower():
            return

        # H-08: Strict allowlist validation
        if not _re.fullmatch(r'^[A-Za-z0-9_ ]+$', new_name):
            QMessageBox.warning(self, "Invalid Name", "Column name may only contain letters, numbers, underscores, and spaces.")
            return
        
        base_names = [c[0].lower() for c in _ANIL_COLS] + ["balance", "id", "sort_order"]
        if new_name.lower() in base_names:
            QMessageBox.warning(self, "Invalid Name", f"'{new_name}' is a reserved column name.")
            return
        if new_name.lower() in [c.lower() for c in self._custom_cols if c.lower() != old_name.lower()]:
            QMessageBox.warning(self, "Column Exists", f"Column '{new_name}' already exists.")
            return
        
        if self._db_name:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(f"EXEC sp_rename 'anil_ledger.[{old_name}]', '{new_name}', 'COLUMN'")
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    from src.utils.app_logger import get_logger
                    get_logger(__name__).error(f"[AnilHisab] sp_rename failed: {e}")
                    QMessageBox.critical(self, "Rename Failed", f"Failed to rename column in database:\n{e}")
                    return
                finally:
                    cur.close()
        
        if h:
            h.setText(new_name)
        try:
            idx = [c.lower() for c in self._custom_cols].index(old_name.lower())
            self._custom_cols[idx] = new_name
        except ValueError:
            self._custom_cols.append(new_name)
        self._save_custom_columns()
        self._save_header_state()

    def _delete_custom_col(self, col):
        if col < len(_ANIL_COLS):
            return
        h = self.table.horizontalHeaderItem(col)
        col_name = h.text() if h else ""
        custom_idx = col - len(_ANIL_COLS)
        if not col_name and 0 <= custom_idx < len(self._custom_cols):
            col_name = self._custom_cols[custom_idx]
        
        from .shared import _styled_question
        confirm = _styled_question(
            self, "Delete Column",
            f"Are you sure you want to delete column '{col_name}' and all its data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
            
        if self._db_name:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(f"ALTER TABLE anil_ledger DROP COLUMN [{col_name}]")
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    from src.utils.app_logger import get_logger
                    get_logger(__name__).warning(f"[AnilHisab] Drop column from DB skipped or failed: {e}")
                finally:
                    cur.close()
                    
        self._custom_cols = [c for c in self._custom_cols if c.lower() != col_name.lower()]
        self.table.removeColumn(col)
        self._save_custom_columns()
        self._save_header_state()
        self._save_all()

    def _save_header_state(self):
        if getattr(self, '_loading', False) or not self._db_name:
            return
        state = self.table.horizontalHeader().saveState().toBase64().data().decode()
        if self._db_name:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "IF EXISTS (SELECT 1 FROM anil_settings WHERE [key]='header_state') "
                        "UPDATE anil_settings SET value=? WHERE [key]='header_state' "
                        "ELSE INSERT INTO anil_settings ([key],value) VALUES ('header_state',?)",
                        (state, state)
                    )
                    conn.commit()
                except Exception as e:
                    from src.utils.app_logger import get_logger as _gl
                    _gl(__name__).warning(f"[AnilHisab] _save_header_state error: {e}")
                finally:
                    cur.close()

    def _load_header_state(self):
        if self._db_name:
            try:
                rows = self._db.execute_query(self._db_name, "SELECT value FROM anil_settings WHERE [key]='header_state'")
                if rows and rows[0][0]:
                    from PyQt6.QtCore import QByteArray
                    state = QByteArray.fromBase64(rows[0][0].encode())
                    self.table.horizontalHeader().restoreState(state)
            except Exception as e:
                from src.utils.app_logger import get_logger as _gl
                _gl(__name__).warning(f"[AnilHisab] _load_header_state error: {e}")

    def _vhdr_ctx(self, pos):
        if not self._can_edit:
            return
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        act_hide = menu.addAction("👁️  Hide S.N")
        chosen = menu.exec(QCursor.pos())
        if chosen == act_hide:
            self._set_sn_visible(False)

    def _set_sn_visible(self, visible: bool):
        self._show_sn = visible
        self.table.verticalHeader().setVisible(visible)
        from PyQt6.QtCore import QSettings
        settings = QSettings("TallySync", "SuppPayment")
        settings.setValue("show_sn_anil_hisab", visible)

    def _header_ctx(self, pos):
        if not self._can_edit:
            return
        
        hdr = self.table.horizontalHeader()
        col = hdr.logicalIndexAt(pos.x())
        if col < 0:
            visual_col = hdr.count() - 1
        else:
            visual_col = hdr.visualIndex(col)
            
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        
        # 1. Smart-header resize/stretch actions
        a_fit = menu.addAction("↔  Fit Column to Content") if col >= 0 else None
        a_fit_all = menu.addAction("↔  Fit All Columns to Content")
        is_stretch = hdr.stretchLastSection()
        a_stretch = menu.addAction(
            "📌  Stretch Last Column (On)" if is_stretch else "📌  Stretch Last Column (Off)"
        )
        menu.addSeparator()

        # S.N toggle
        act_sn = menu.addAction("👁️  Hide S.N" if self._show_sn else "👁️  Show S.N")
        menu.addSeparator()

        # 2. Opening Dr balance, Interest Rate, and Recalculate
        a_set_dr = menu.addAction("💰  Set Opening Dr (Row 1)") if col in (0, _ANIL_DR) else None
        rate_pct = round(getattr(self, '_interest_rate', 0.18) * 100.0, 2)
        a_set_rate = menu.addAction(f"📈  Set Interest Rate (Current: {rate_pct}%)") if col in (0, _ANIL_DR) else None
        a_recalc_hdr = menu.addAction("🔄  Recalculate All Balances")
        menu.addSeparator()

        # 3. Column insertion
        a_ins_l = None
        a_ins_r = None
        if col == _ANIL_BAL:
            # On Balance column: allow inserting column to the right
            a_ins_r = menu.addAction("➕  Insert Column Right")
        elif col >= len(_ANIL_COLS):
            # On custom column: allow inserting left or right
            a_ins_l = menu.addAction("➕  Insert Column Left")
            a_ins_r = menu.addAction("➕  Insert Column Right")
        else:
            # On other columns or empty space: allow Add Column
            a_ins_r = menu.addAction("➕  Add Column")

        menu.addSeparator()

        # 4. Custom column management
        is_custom = (col >= len(_ANIL_COLS))
        a_rename = menu.addAction("✏️  Rename Column")
        a_rename.setEnabled(is_custom)
        a_del = menu.addAction("🗑️  Delete Column")
        a_del.setEnabled(is_custom)
        
        act = menu.exec(hdr.mapToGlobal(pos))
        
        if a_fit and act == a_fit:
            self.table.resizeColumnToContents(col)
        elif act == a_fit_all:
            self.table.resizeColumnsToContents()
        elif act == a_stretch:
            hdr.setStretchLastSection(not is_stretch)
        elif act == act_sn:
            self._set_sn_visible(not self._show_sn)
        elif a_set_dr and act == a_set_dr:
            from .shared import _styled_get_text
            val, ok = _styled_get_text(self, "Opening Dr", "Enter Opening Dr Balance for Row 1:")
            if ok:
                val = val.strip()
                if val:
                    try:
                        float(val.replace(",", ""))
                    except ValueError:
                        return
                    
                self.table.blockSignals(True)
                if self.table.rowCount() == 0:
                    self.table.insertRow(0)
                    for c in range(self.table.columnCount()):
                        self.table.setItem(0, c, self._a_item("", self._align_for_col(c)))
                
                new_dr = self._a_item(_fmt_dr(val), _R)
                new_dr.setData(Qt.ItemDataRole.UserRole, "manual")
                if val:
                    try:
                        new_dr.setData(RAW_NUMERIC_ROLE, float(val.replace(",", "")))
                    except ValueError:
                        pass
                new_dr.setFlags(new_dr.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(0, _ANIL_DR, new_dr)
                self.table.blockSignals(False)
                self._recalc_all()
                self._save_all()
        elif a_set_rate and act == a_set_rate:
            from PyQt6.QtWidgets import QInputDialog
            curr_pct = round(getattr(self, '_interest_rate', 0.18) * 100.0, 2)
            val, ok = QInputDialog.getDouble(
                self, "Interest Rate",
                "Enter Annual Interest Rate (%):",
                curr_pct, 0.0, 100.0, 2
            )
            if ok:
                self._save_interest_rate(val)
        elif a_recalc_hdr and act == a_recalc_hdr:
            self._recalc_all()
            self._save_all()
        elif a_ins_l and act == a_ins_l:
            self._insert_custom_col(visual_idx=visual_col)
        elif a_ins_r and act == a_ins_r:
            self._insert_custom_col(visual_idx=visual_col + 1 if visual_col >= 0 else None)
        elif act == a_rename and is_custom:
            self._rename_custom_col(col)
        elif act == a_del and is_custom:
            self._delete_custom_col(col)

    def _row_ctx(self, pos):
        if not self._can_edit:
            return
        item = self.table.itemAt(pos)
        r = item.row() if item else self.table.currentRow()
        col = item.column() if item else (self.table.columnAt(pos.x()) if pos.x() >= 0 else self.table.currentColumn())
        menu = QMenu(self)
        from .shared import _styled_get_color
        from PyQt6.QtGui import QBrush, QColor
        menu.setStyleSheet(_MENU_STYLE)

        # Lock/Unlock Start Date — only shown when right-clicking the Start Date column
        a_lock = None
        if col == 0:
            menu.addSeparator()
            if self._start_date_locked:
                a_lock = menu.addAction("\U0001f513  Unlock Start Dates (allow editing)")
            else:
                a_lock = menu.addAction("\U0001f512  Lock Start Dates (auto-only)")
            menu.addSeparator()

        a_restore_formula = None
        dr_item = self.table.item(r, _ANIL_DR) if r > 0 else None
        is_dr_manual = bool(dr_item and dr_item.data(Qt.ItemDataRole.UserRole) == "manual")
        if (col == _ANIL_DR or is_dr_manual) and r > 0:
            menu.addSeparator()
            rate_pct = round(getattr(self, '_interest_rate', 0.18) * 100.0, 1)
            a_restore_formula = menu.addAction(f"🔄  Calculate / Restore Auto Formula ({rate_pct}%/365 × Days)")
            menu.addSeparator()

        a_recalc_row = menu.addAction("🔄  Recalculate All Balances")
        menu.addSeparator()

        a_add_above = menu.addAction("\u2191  Add Row Above")
        a_add_below = menu.addAction("\u2193  Add Row Below")
        menu.addSeparator()

        a_add_col = menu.addAction("➕  Add Column")
        menu.addSeparator()

        a_del = menu.addAction("\u2715  Delete Row")
        menu.addSeparator()
        a_color = menu.addAction("\u25cf  Set Cell Color")
        a_text_color = menu.addAction("\u25d0  Set Text Color")
        a_clear = menu.addAction("\u25cb  Clear Colors")
        
        act = menu.exec(self.table.viewport().mapToGlobal(pos))

        if a_lock and act == a_lock:
            self._start_date_locked = not self._start_date_locked
            self._apply_start_date_lock()
            self._save_start_lock_state()
            return

        if a_restore_formula and act == a_restore_formula:
            self.table.blockSignals(True)
            it = self.table.item(r, _ANIL_DR)
            if it:
                it.setData(Qt.ItemDataRole.UserRole, None)
                it.setData(RAW_NUMERIC_ROLE, None)
                it.setText("")  # Clears manual text so auto formula recomputes fresh
            self.table.blockSignals(False)
            self._recalc_all()
            self._save_all()
            return

        if a_recalc_row and act == a_recalc_row:
            self._recalc_all()
            self._save_all()
            return
        
        if act == a_add_col:
            self._insert_custom_col()
            return
        
        if act == a_add_above and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r)
            for c in range(self.table.columnCount()):
                self.table.setItem(r, c, self._a_item("", self._align_for_col(c)))
            self.table.blockSignals(False)
            self._recalc_all()
            self._save_all()
        elif act == a_add_below and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r + 1)
            for c in range(self.table.columnCount()):
                self.table.setItem(r + 1, c, self._a_item("", self._align_for_col(c)))
            self.table.blockSignals(False)
            self._recalc_all()
            self._save_all()
        elif act == a_del and r >= 0:
            self.table.removeRow(r)
            self._recalc_all()
            self._save_all()
        elif act == a_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = self._a_item("", self._align_for_col(idx.column()))
                        self.table.setItem(idx.row(), idx.column(), it)
                    it.setBackground(QBrush(color))
                self.table.blockSignals(False)
                self.table.resizeColumnsToContents()
                self._save_all()
        elif act == a_text_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = self._a_item("", self._align_for_col(idx.column()))
                        self.table.setItem(idx.row(), idx.column(), it)
                    it.setForeground(QBrush(color))
                self.table.blockSignals(False)
                self.table.resizeColumnsToContents()
                self._save_all()
        elif act == a_clear:
            self.table.blockSignals(True)
            for idx in self.table.selectedIndexes():
                it = self.table.item(idx.row(), idx.column())
                if it:
                    it.setBackground(QBrush())
                    it.setForeground(QBrush())
            self.table.blockSignals(False)
            self.table.resizeColumnsToContents()
            self._save_all()

    def _a_item(self, text, align=_L):
        it = QTableWidgetItem("" if text is None else str(text))
        it.setTextAlignment(align)
        return it

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._ensure_table()
        self._load_custom_columns()
        self._load_interest_rate()
        self._load_start_lock_state()  # restore lock state before loading data
        self._load_from_db()

    def _ensure_table(self):
        ddl = ("CREATE TABLE anil_ledger "
               "(id INT IDENTITY PRIMARY KEY, sort_order INT, "
               "start_date NVARCHAR(MAX), end_date NVARCHAR(MAX), days NVARCHAR(MAX), "
               "particular NVARCHAR(MAX), dr NVARCHAR(MAX), cr NVARCHAR(MAX), "
               "remarks NVARCHAR(MAX))")
        self._db.ensure_table(self._db_name, "anil_ledger", ddl)
        # Settings table for persisting UI state (e.g. start date lock)
        self._db.ensure_table(
            self._db_name, "anil_settings",
            "CREATE TABLE anil_settings ([key] NVARCHAR(100) PRIMARY KEY, value NVARCHAR(MAX))"
        )
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    # C-04: Only alter columns if they are not already NVARCHAR(MAX)
                    # Prevents acquiring Sch-M locks on every application launch
                    cols_to_check = ["start_date", "end_date", "days", "dr", "cr"]
                    for col in cols_to_check:
                        cur.execute(
                            "SELECT CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_NAME='anil_ledger' AND COLUMN_NAME=?",
                            (col,)
                        )
                        row = cur.fetchone()
                        if row and row[0] != -1:  # -1 represents MAX in SQL Server
                            cur.execute(f"ALTER TABLE anil_ledger ALTER COLUMN [{col}] NVARCHAR(MAX)")
                    conn.commit()
                finally:
                    cur.close()
        except Exception as _e:
            # Non-fatal: columns may already be the correct type or the user may
            # lack ALTER TABLE permissions. Log so it surfaces in error.log.
            from src.utils.app_logger import get_logger as _gl
            _gl(__name__).warning(f"[AnilHisab] schema migration ALTER COLUMN skipped: {_e}")

    def _load_interest_rate(self):
        """Load configured interest rate from DB (defaults to 18% = 0.18)."""
        try:
            rows = self._db.execute_query(
                self._db_name,
                "SELECT value FROM anil_settings WHERE [key]='interest_rate'"
            ) or []
            if rows and rows[0][0]:
                val = float(str(rows[0][0]).strip())
                self._interest_rate = val / 100.0 if val > 1.0 else val
            else:
                self._interest_rate = 0.18
        except Exception:
            self._interest_rate = 0.18

    def _save_interest_rate(self, rate_pct: float):
        """Persist user-configured interest rate to DB and recalculate ledger."""
        try:
            self._interest_rate = float(rate_pct) / 100.0
            val = str(rate_pct)
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "IF EXISTS (SELECT 1 FROM anil_settings WHERE [key]='interest_rate') "
                        "UPDATE anil_settings SET value=? WHERE [key]='interest_rate' "
                        "ELSE INSERT INTO anil_settings ([key],value) VALUES ('interest_rate',?)",
                        (val, val)
                    )
                    conn.commit()
                finally:
                    cur.close()
            self._recalc_all()
            self._save_all()
        except Exception as e:
            from src.utils.app_logger import get_logger
            get_logger(__name__).error(f"[AnilHisab] _save_interest_rate error: {e}")

    def _load_start_lock_state(self):
        """Load the start-date lock preference from DB (defaults to True = locked)."""
        try:
            rows = self._db.execute_query(
                self._db_name,
                "SELECT value FROM anil_settings WHERE [key]='start_date_locked'"
            ) or []
            if rows:
                self._start_date_locked = rows[0][0].strip() == '1'
        except Exception:
            self._start_date_locked = True

    def _save_start_lock_state(self):
        """Persist the current start-date lock state to DB."""
        try:
            val = '1' if self._start_date_locked else '0'
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "IF EXISTS (SELECT 1 FROM anil_settings WHERE [key]='start_date_locked') "
                        "UPDATE anil_settings SET value=? WHERE [key]='start_date_locked' "
                        "ELSE INSERT INTO anil_settings ([key],value) VALUES ('start_date_locked',?)",
                        (val, val)
                    )
                    conn.commit()
                finally:
                    cur.close()
        except Exception as e:
            from src.utils.app_logger import get_logger as _gl
            _gl(__name__).warning(f"[AnilHisab] _save_start_lock_state error: {e}")

    def _apply_start_date_lock(self):
        """Enforce or remove the editable flag on Start Date cells for rows 1+.
        Row 0 is always editable regardless of lock state.
        """
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if not it:
                it = self._a_item("", _C)
                self.table.setItem(r, 0, it)
            if r == 0:
                # Row 0 start date is always user-editable
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            else:
                if self._start_date_locked:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        self.table.blockSignals(False)

    def _load_from_db(self):
        if not self._db_name:
            return
        self._loading = True
        self._load_failed = False
        try:
            # Dynamically build SELECT based on custom cols
            cols = ["start_date", "end_date", "days", "particular", "dr", "cr"]
            cols.extend([f"[{c}]" for c in self._custom_cols])
            
            rows = self._db.execute_query(
                self._db_name,
                f"SELECT {','.join(cols)} FROM anil_ledger ORDER BY sort_order, id"
            )
            if rows is None:
                self._load_failed = True
                from src.utils.app_logger import get_logger
                get_logger(__name__).error("[AnilHisab] Failed to load data from anil_ledger (query returned None).")
                return

            self._load_failed = False
            self._loaded_row_count = len(rows)

            self.table.blockSignals(True)
            self.table.setRowCount(0)
            for row_data in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                start, end, days, part, dr, cr = row_data[:6]
                import json
                from PyQt6.QtGui import QBrush, QColor
                def _unpack(val, align):
                    if not val: return self._a_item("", align)
                    if val.startswith('{') and '"text"' in val:
                        try:
                            d = json.loads(val)
                            it = self._a_item(d.get("text", ""), align)
                            if d.get("bg"): it.setBackground(QBrush(QColor(d.get("bg"))))
                            if d.get("fg"): it.setForeground(QBrush(QColor(d.get("fg"))))
                            if d.get("manual"): it.setData(Qt.ItemDataRole.UserRole, "manual")
                            if "val" in d:
                                try:
                                    it.setData(RAW_NUMERIC_ROLE, float(d["val"]))
                                except (ValueError, TypeError):
                                    pass
                            return it
                        except (json.JSONDecodeError, Exception):
                            pass
                    return self._a_item(val, align)
                start_it = _unpack(start, _C)
                if r > 0 and self._start_date_locked:
                    start_it.setFlags(start_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 0, start_it)
                self.table.setItem(r, 1, _unpack(end, _C))
                # col 2 (Days) is a formula column — recalculated by _recalc_all().
                # col 4 (DR): load stored value, ensuring rounded off to integer
                dr_it = _unpack(dr, _R)
                if dr_it and dr_it.text().strip():
                    dr_it.setText(_fmt_dr(dr_it.text().strip()))
                dr_it.setFlags(dr_it.flags() & ~Qt.ItemFlag.ItemIsEditable if r == 0
                               else dr_it.flags() | Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, _ANIL_DR, dr_it)
                self.table.setItem(r, 3, _unpack(part, _L))
                self.table.setItem(r, 5, _unpack(cr, _R))
                
                # Populate custom cols
                for i, val in enumerate(row_data[6:]):
                    col_idx = len(_ANIL_COLS) + i
                    self.table.setItem(r, col_idx, _unpack(val, _L))
                    
            self.table.blockSignals(False)
            self.table.resizeColumnsToContents()
            # Recalc balances silently after load
            self._recalc_all()
            # Apply lock state to start date cells after data is loaded
            self._apply_start_date_lock()
            self._load_header_state()
        except Exception as e:
            self._load_failed = True
            from src.utils.app_logger import get_logger
            get_logger(__name__).error(f"[AnilHisab] Exception during _load_from_db: {e}")
        finally:
            self._loading = False

    _INTEREST_RATE = 0.18  # 18% annual — hardcoded

    def _recalc_days(self, row=None):
        """Recompute Days, formula DR (interest), and Balances for the ledger."""
        self._recalc_all()

    def _recalc_all(self):
        """Recalculate Days, formula DR (interest), and Balances iteratively row by row.
        Calculations use unrounded decimal precision internally (matching Excel),
        while all displayed numbers are strictly formatted as integers with commas.
        """
        self.table.blockSignals(True)
        from PyQt6.QtGui import QBrush, QColor
        prev_bal = 0.0

        for r in range(self.table.rowCount()):
            # 1. Update Days: Days = End Date - Start Date
            start_it = self.table.item(r, 0)
            end_it   = self.table.item(r, 1)
            start_txt = start_it.text().strip() if start_it else ""
            end_txt   = end_it.text().strip()   if end_it   else ""
            days_val  = None
            days_str  = ""
            if start_txt and end_txt:
                try:
                    d0 = QDate.fromString(start_txt, "yyyy-MM-dd")
                    d1 = QDate.fromString(end_txt,   "yyyy-MM-dd")
                    if d0.isValid() and d1.isValid():
                        days_val = d0.daysTo(d1)
                        if days_val >= 0:
                            days_str = str(days_val)
                except Exception:
                    pass
            days_it = self.table.item(r, 2)
            if not days_it:
                days_it = self._a_item(days_str, _C)
                self.table.setItem(r, 2, days_it)
            else:
                days_it.setText(days_str)
            days_it.setFlags(days_it.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # 2. Update DR
            dr_it = self.table.item(r, _ANIL_DR)
            is_manual = False
            if dr_it:
                is_manual = (dr_it.data(Qt.ItemDataRole.UserRole) == "manual")
            if r == 0:
                is_manual = True  # Row 0 opening balance is always manual
                if dr_it and dr_it.data(Qt.ItemDataRole.UserRole) != "manual":
                    dr_it.setData(Qt.ItemDataRole.UserRole, "manual")

            interest_val = None
            if not is_manual:
                # Formula row: DR = prev_balance * interest_rate / 365 * days
                if days_val is not None and days_val > 0 and prev_bal != 0.0:
                    interest_val = prev_bal * getattr(self, '_interest_rate', 0.18) / 365.0 * float(days_val)
                    dr_str = _fmt_dr(interest_val)
                else:
                    interest_val = 0.0
                    dr_str = ""
                
                if not dr_it:
                    dr_it = self._a_item(dr_str, _R)
                    self.table.setItem(r, _ANIL_DR, dr_it)
                else:
                    dr_it.setText(dr_str)
                dr_it.setData(RAW_NUMERIC_ROLE, interest_val)
                dr_it.setFlags(dr_it.flags() | Qt.ItemFlag.ItemIsEditable)
            else:
                # Manual row: preserve existing text and ensure editable (except row 0)
                if dr_it and dr_it.text().strip():
                    raw_dr = dr_it.data(RAW_NUMERIC_ROLE)
                    if raw_dr is None:
                        try:
                            raw_dr = float(dr_it.text().replace(",", "").strip())
                            dr_it.setData(RAW_NUMERIC_ROLE, raw_dr)
                        except ValueError:
                            pass
                    dr_it.setText(_fmt_dr(dr_it.text().strip()))
                if dr_it:
                    dr_it.setFlags(dr_it.flags() & ~Qt.ItemFlag.ItemIsEditable if r == 0
                                   else dr_it.flags() | Qt.ItemFlag.ItemIsEditable)

            # 3. Read DR and CR numeric values (decimals used for calculation)
            def _get_num(col):
                if col == _ANIL_DR and not is_manual and interest_val is not None:
                    return interest_val
                it = self.table.item(r, col)
                if not it: return 0.0
                raw = it.data(RAW_NUMERIC_ROLE)
                if raw is not None and isinstance(raw, (int, float)):
                    return float(raw)
                txt = it.text().replace(",", "").strip() if it.text() else ""
                if not txt: return 0.0
                try: return float(txt)
                except ValueError: return 0.0

            dr_num = _get_num(_ANIL_DR)
            cr_num = _get_num(_ANIL_CR)

            # 4. Compute Balance (unrounded decimal)
            if r == 0:
                new_bal = dr_num - cr_num
            else:
                new_bal = prev_bal + dr_num - cr_num
            prev_bal = new_bal

            # 5. Update Balance cell (display integer only, store exact decimal)
            has_val = (dr_it and bool(dr_it.text().strip())) or bool(self.table.item(r, _ANIL_CR) and self.table.item(r, _ANIL_CR).text().strip())
            bal_str = _fmt(new_bal) if has_val else ""
            bal_it = self.table.item(r, _ANIL_BAL)
            if not bal_it:
                bal_it = self._a_item(bal_str, _R)
                self.table.setItem(r, _ANIL_BAL, bal_it)
            else:
                bal_it.setText(bal_str)
            bal_it.setData(RAW_NUMERIC_ROLE, new_bal)
            bal_it.setFlags(bal_it.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if new_bal < 0:
                bal_it.setForeground(QBrush(QColor("#dc2626")))
            elif new_bal > 0:
                bal_it.setForeground(QBrush(QColor("#16a34a")))
            else:
                bal_it.setForeground(QBrush())

        self.table.blockSignals(False)

    def _save_all(self):
        """Save all rows inside a single atomic transaction to prevent partial writes."""
        if not self._db_name or getattr(self, '_loading', False):
            return
        if getattr(self, '_load_failed', False):
            from src.utils.app_logger import get_logger
            get_logger(__name__).warning("[AnilHisab] Blocked _save_all to prevent data loss after load failure.")
            return

        # Safeguard against accidental data wipe (C-02):
        # If UI table has 0 rows but DB previously had records loaded, refuse to delete.
        if getattr(self, '_loaded_row_count', 0) > 0 and self.table.rowCount() == 0:
            from src.utils.app_logger import get_logger
            get_logger(__name__).warning(
                f"[AnilHisab] Blocked _save_all — table has 0 rows in UI but DB had {self._loaded_row_count} rows loaded. Refusing to wipe anil_ledger."
            )
            return

        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM anil_ledger")
            
            base_cols = ["sort_order", "start_date", "end_date", "days", "particular", "dr", "cr"]
            custom_cols = [f"[{c}]" for c in self._custom_cols]
            all_cols = base_cols + custom_cols
            
            placeholders = ",".join(["?"] * len(all_cols))
            
            rows_to_insert = []
            for r in range(self.table.rowCount()):
                row_vals = [
                    r,
                    self._cell(r, 0), self._cell(r, 1), self._cell(r, 2),
                    self._cell(r, 3), self._cell(r, 4), self._cell(r, 5)
                ]
                for i in range(len(self._custom_cols)):
                    row_vals.append(self._cell(r, len(_ANIL_COLS) + i))
                rows_to_insert.append(tuple(row_vals))
                
            if rows_to_insert:
                cur.executemany(
                    f"INSERT INTO anil_ledger ({','.join(all_cols)}) VALUES ({placeholders})",
                    rows_to_insert
                )
            conn.commit()
            self._loaded_row_count = len(rows_to_insert)
        except Exception as e:
            conn.rollback()
            from src.utils.app_logger import get_logger
            get_logger(__name__).error(f"[AnilHisab] _save_all failed, rolled back: {e}")
        finally:
            cur.close()

    def _cell(self, r, c):
        it = self.table.item(r, c)
        if not it: return ""
        import json
        from PyQt6.QtGui import QBrush
        txt = it.text().strip()
        bg = it.background().color().name() if isinstance(it.background(), QBrush) and it.background().style() != Qt.BrushStyle.NoBrush and it.background().color().isValid() else ""
        fg = it.foreground().color().name() if isinstance(it.foreground(), QBrush) and it.foreground().style() != Qt.BrushStyle.NoBrush and it.foreground().color().isValid() else ""
        is_manual = (c == _ANIL_DR and (it.data(Qt.ItemDataRole.UserRole) == "manual" or r == 0))
        raw_val = it.data(RAW_NUMERIC_ROLE)
        has_val = raw_val is not None and isinstance(raw_val, (int, float))

        fmt_txt = _fmt_dr(txt) if c == _ANIL_DR and txt else (_fmt(txt) if c in (4,5) and txt else txt)

        if bg or fg or is_manual or has_val:
            payload = {"text": fmt_txt}
            if bg: payload["bg"] = bg
            if fg: payload["fg"] = fg
            if is_manual: payload["manual"] = True
            if has_val: payload["val"] = float(raw_val)
            return json.dumps(payload)
        return fmt_txt

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, self._a_item("", self._align_for_col(c)))
        # Prefill start_date from previous row's end_date + 1 day so the chain is unbroken
        if r > 0:
            prev_end_it = self.table.item(r - 1, 1)
            prev_end_txt = prev_end_it.text().strip() if prev_end_it else ""
            if prev_end_txt:
                d1 = QDate.fromString(prev_end_txt, "yyyy-MM-dd")
                if d1.isValid():
                    new_start = self._a_item(d1.addDays(1).toString("yyyy-MM-dd"), _C)
                    if self._start_date_locked:
                        new_start.setFlags(new_start.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    else:
                        new_start.setFlags(new_start.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, 0, new_start)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.scrollToBottom()
        self._recalc_all()
        self._save_all()

    def _on_cell_changed(self, row, col):
        """Save on any column edit; recalc balance on DR/CR change;
        recalc Days and auto-fill next start date on date change.

        DR manual override: if the user types a value in DR (rows 1+), it is
        preserved as-is and marked manual.
        If the user clears the DR cell, the formula resumes automatically.
        """
        # Formula 1: Date change (Start Date or End Date)
        if col in (0, 1):
            if col == 1:  # End Date edited
                end_it = self.table.item(row, 1)
                end_txt = end_it.text().strip() if end_it else ""
                if end_txt and getattr(self, '_start_date_locked', True):
                    d_end = QDate.fromString(end_txt, "yyyy-MM-dd")
                    if d_end.isValid():
                        self.table.blockSignals(True)
                        current = row + 1
                        while current < self.table.rowCount():
                            new_start_str = d_end.addDays(1).toString("yyyy-MM-dd")
                            start_it = self.table.item(current, 0)
                            if not start_it:
                                start_it = self._a_item(new_start_str, _C)
                                self.table.setItem(current, 0, start_it)
                            else:
                                start_it.setText(new_start_str)
                            if self._start_date_locked:
                                start_it.setFlags(start_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            else:
                                start_it.setFlags(start_it.flags() | Qt.ItemFlag.ItemIsEditable)

                            next_end_it = self.table.item(current, 1)
                            next_end_txt = next_end_it.text().strip() if next_end_it else ""
                            if next_end_txt:
                                d_end = QDate.fromString(next_end_txt, "yyyy-MM-dd")
                                if not d_end.isValid():
                                    break
                            else:
                                break
                            current += 1
                        self.table.blockSignals(False)
            self._recalc_all()

        elif col == _ANIL_DR:
            dr_it = self.table.item(row, _ANIL_DR)
            dr_txt = dr_it.text().strip().replace(",", "") if dr_it else ""
            self.table.blockSignals(True)
            try:
                # If user typed an expression like =calc or =auto, clear manual override
                if dr_txt.lower() in ('=calc', '=auto', '=formula', '=', '=interest'):
                    if dr_it and row > 0:
                        dr_it.setData(Qt.ItemDataRole.UserRole, None)
                        dr_it.setData(RAW_NUMERIC_ROLE, None)
                        dr_it.setText("")
                elif dr_txt:
                    if row > 0:
                        dr_it.setData(Qt.ItemDataRole.UserRole, "manual")
                    try:
                        fv = float(dr_txt)
                        dr_it.setData(RAW_NUMERIC_ROLE, fv)
                        rounded_str = _fmt_dr(fv)
                        if dr_it.text().strip() != rounded_str:
                            dr_it.setText(rounded_str)
                    except ValueError:
                        pass
                elif not dr_txt:
                    if dr_it:
                        if row > 0:
                            dr_it.setData(Qt.ItemDataRole.UserRole, None)
                        dr_it.setData(RAW_NUMERIC_ROLE, None)
            finally:
                self.table.blockSignals(False)
            self._recalc_all()

        elif col == _ANIL_CR:
            cr_it = self.table.item(row, _ANIL_CR)
            cr_txt = cr_it.text().strip().replace(",", "") if cr_it else ""
            if cr_txt:
                try:
                    fv = float(cr_txt)
                    cr_it.setData(RAW_NUMERIC_ROLE, fv)
                    rounded_str = _fmt(fv)
                    if cr_it.text().strip() != rounded_str:
                        self.table.blockSignals(True)
                        cr_it.setText(rounded_str)
                        self.table.blockSignals(False)
                except ValueError:
                    pass
            else:
                if cr_it:
                    cr_it.setData(RAW_NUMERIC_ROLE, None)
            self._recalc_all()

        self._save_all()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        self._btn_add.setEnabled(can_edit)
        if hasattr(self, '_btn_add_col'):
            self._btn_add_col.setEnabled(can_edit)


# ===========================================================================
# PAYMENT SHEET  (generic user-added sheets — column view only)
