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
    _setup_smart_header, _DbTable,
)
from src.ui.table_nav_mixin import UniversalCellDelegate

# ===========================================================================
# ANIL DAI HISAB TAB — Running Balance Ledger
# ===========================================================================
_ANIL_COLS = [
    ("Start Date",  110), ("End Date",  110), ("Days",   55),
    ("Particular",  200), ("DR",        120), ("Cr.",    120),
    ("Balance",     135), ("Remarks",   180),
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
      Row 0  → plain text input (user types date manually, e.g. 2081-04-01).
      Rows 1+ → locked (auto-filled from previous end date, cannot be overridden).
    """
    def createEditor(self, parent, option, index):
        return super().createEditor(parent, option, index) if index.row() == 0 else None


def _fmt(val):
    if val is None or val == "" or val == 0 or val == "0":
        return ""
    try:
        fv = float(val)
        if fv == int(fv):
            return f"{int(fv):,}"
        return f"{fv:,.2f}"
    except Exception:
        return str(val)


class AnilHisabTab(QWidget, _PrintExportMixin):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._start_date_locked = True  # Start Date col (rows 1+) locked by default

        self._db_name  = ""
        self._db       = get_db_manager()

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
            else:
                self._btn_add.setText("")
        
        self._init_print_export(tlay, "Anil Dai Hisab",
                                  table_getter=lambda: [{"title": "", "table": self.table}], right_bar=right_bar, on_toggle_cb=on_toggle_anil)

        from src.ui.supp_payment.shared import get_icon
        self._btn_add = QPushButton()
        self._btn_add.setIcon(get_icon("add.svg"))
        self._btn_add.setToolTip("Add Row")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        
        tlay.addStretch()
        
        layout.addWidget(self.table, 1)
        layout.addWidget(right_bar, 0)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setHorizontalHeaderLabels([c[0] for c in _ANIL_COLS])
        for i, (_, w) in enumerate(_ANIL_COLS):
            self.table.setColumnWidth(i, w)
        # Days (col 2) and DR (col 4) are auto-calculated — make them read-only
        self.table.setItemDelegateForColumn(2, _ReadOnlyDelegate(self.table))
        self.table.setItemDelegateForColumn(_ANIL_DR, _ReadOnlyDelegate(self.table))
        _setup_smart_header(self.table)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setItemDelegate(ModernTableDelegate(self.table))
        
        # Date delegate on End Date (1), Start Date (0) uses the row-aware plain-text delegate
        self.table.setItemDelegateForColumn(0, _StartDateDelegate(self.table))
        self.table.setItemDelegateForColumn(1, ModernTableDelegate(self.table, cell_type="date"))
        # Formula columns — read-only: Days (2), DR (4), Balance (6)
        for _fc in (2, _ANIL_DR, _ANIL_BAL):
            self.table.setItemDelegateForColumn(_fc, _ReadOnlyDelegate(self.table))

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)

        self.table.cellChanged.connect(self._on_cell_changed)

    def _row_ctx(self, pos):
        if not self._can_edit:
            return
        item = self.table.itemAt(pos)
        r = item.row() if item else self.table.currentRow()
        col = self.table.columnAt(pos.x())  # detect which column was right-clicked
        menu = QMenu(self)
        from PyQt6.QtWidgets import QColorDialog
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

        a_add_above = menu.addAction("\u2191  Add Row Above")
        a_add_below = menu.addAction("\u2193  Add Row Below")
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
        
        if act == a_add_above and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r)
            for c in range(self.table.columnCount()):
                self.table.setItem(r, c, self._a_item("", _C if c in (0,1,2) else _L if c in (3,7) else _R))
            self.table.blockSignals(False)
            self._recalc_all()
            self._save_all()
        elif act == a_add_below and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r + 1)
            for c in range(self.table.columnCount()):
                self.table.setItem(r+1, c, self._a_item("", _C if c in (0,1,2) else _L if c in (3,7) else _R))
            self.table.blockSignals(False)
            self._recalc_all()
            self._save_all()
        elif act == a_del and r >= 0:
            self.table.removeRow(r)
            self._recalc_all()
            self._save_all()
        elif act == a_color:
            color = QColorDialog.getColor(parent=self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = self._a_item("", _C if idx.column() in (0,1,2) else _L if idx.column() in (3,7) else _R)
                        self.table.setItem(idx.row(), idx.column(), it)
                    it.setBackground(QBrush(color))
                self.table.blockSignals(False)
                self.table.resizeColumnsToContents()
                self._save_all()
        elif act == a_text_color:
            color = QColorDialog.getColor(parent=self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = self._a_item("", _C if idx.column() in (0,1,2) else _L if idx.column() in (3,7) else _R)
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
            "CREATE TABLE anil_settings (key NVARCHAR(100) PRIMARY KEY, value NVARCHAR(MAX))"
        )
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                for col in ["start_date", "end_date", "days", "dr", "cr"]:
                    cur.execute(f"ALTER TABLE anil_ledger ALTER COLUMN {col} NVARCHAR(MAX)")
                conn.commit()
        except Exception as _e:
            # Non-fatal: columns may already be the correct type or the user may
            # lack ALTER TABLE permissions. Log so it surfaces in error.log.
            from src.utils.app_logger import get_logger as _gl
            _gl(__name__).warning(f"[AnilHisab] schema migration ALTER COLUMN skipped: {_e}")

    def _load_start_lock_state(self):
        """Load the start-date lock preference from DB (defaults to True = locked)."""
        try:
            rows = self._db.execute_query(
                self._db_name,
                "SELECT value FROM anil_settings WHERE key='start_date_locked'"
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
                cur.execute(
                    "IF EXISTS (SELECT 1 FROM anil_settings WHERE key='start_date_locked') "
                    "UPDATE anil_settings SET value=? WHERE key='start_date_locked' "
                    "ELSE INSERT INTO anil_settings (key,value) VALUES ('start_date_locked',?)",
                    (val, val)
                )
                conn.commit()
        except Exception:
            pass

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
        rows = self._db.execute_query(
            self._db_name,
            "SELECT start_date, end_date, days, particular, dr, cr, remarks "
            "FROM anil_ledger ORDER BY sort_order, id"
        ) or []
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row_data in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            start, end, days, part, dr, cr, remarks = row_data
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
                        return it
                    except:
                        pass
                return self._a_item(val, align)
            start_it = _unpack(start, _C)
            if r > 0:
                start_it.setFlags(start_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, start_it)
            self.table.setItem(r, 1, _unpack(end, _C))
            # col 2 (Days) and col 4 (DR) are formula columns — skipped here,
            # recalculated by _recalc_all() → _recalc_days() below.
            self.table.setItem(r, 3, _unpack(part, _L))
            self.table.setItem(r, 5, _unpack(cr, _R))
            self.table.setItem(r, 7, _unpack(remarks, _L))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        # Recalc balances silently after load
        self._recalc_all()
        # Apply lock state to start date cells after data is loaded
        self._apply_start_date_lock()

    _INTEREST_RATE = 0.18  # 18% annual — hardcoded

    def _recalc_days(self, row=None):
        """(Re-)compute Days and DR (interest) for one row or all rows.
        Days = End Date - Start Date.
        DR   = Balance[prev_row] x 18% / 365 x Days  (always overwritten — read-only formula).
        """
        rows = range(self.table.rowCount()) if row is None else [row]
        self.table.blockSignals(True)
        from PyQt6.QtGui import QBrush, QColor
        for r in rows:
            start_it = self.table.item(r, 0)
            if start_it and r > 0:
                start_it.setFlags(start_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
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
                        days_str = str(days_val)
                except Exception:
                    pass
            days_it = self._a_item(days_str, _C)
            days_it.setFlags(days_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, days_it)

            # Interest formula: DR = prev_balance × 18% / 365 × days (always computed)
            if days_val and days_val > 0 and r > 0:
                prev_bal_it = self.table.item(r - 1, _ANIL_BAL)
                prev_bal_txt = prev_bal_it.text().strip().replace(",", "") if prev_bal_it else ""
                try:
                    prev_bal = float(prev_bal_txt) if prev_bal_txt else 0.0
                    interest = prev_bal * self._INTEREST_RATE / 365 * days_val
                    interest_str = _fmt(round(interest, 2))
                except Exception:
                    interest_str = ""
            else:
                interest_str = ""
            new_dr = self._a_item(interest_str, _R)
            new_dr.setFlags(new_dr.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, _ANIL_DR, new_dr)
        self.table.blockSignals(False)

    def _recalc_all(self):
        """Recalculate all Balance cells with signals fully blocked."""
        self.table.blockSignals(True)
        prev_bal = 0.0
        for r in range(self.table.rowCount()):
            def _n(col, row=r):
                it = self.table.item(row, col)
                if not it or not it.text(): return 0.0
                val = it.text()
                try: return float(val.replace(",", ""))
                except ValueError:
                    return 0.0
            dr = _n(_ANIL_DR)
            cr = _n(_ANIL_CR)
            new_bal = (dr - cr) if r == 0 else (prev_bal + dr - cr)
            prev_bal = new_bal
            dr_it = self.table.item(r, _ANIL_DR)
            cr_it = self.table.item(r, _ANIL_CR)
            has_val = (dr_it and dr_it.text()) or (cr_it and cr_it.text())
            bal_str = _fmt(new_bal) if has_val else ""
            bal_it = self._a_item(bal_str, _R)
            bal_it.setFlags(bal_it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if new_bal < 0:
                bal_it.setForeground(QBrush(QColor("#dc2626")))
            elif new_bal > 0:
                bal_it.setForeground(QBrush(QColor("#16a34a")))
            self.table.setItem(r, _ANIL_BAL, bal_it)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self._recalc_days()  # auto-compute Days for every row after balance recalc

    def _save_all(self):
        """Save all rows inside a single atomic transaction to prevent partial writes."""
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM anil_ledger")
            rows_to_insert = [
                (r,
                 self._cell(r, 0), self._cell(r, 1), self._cell(r, 2),
                 self._cell(r, 3), self._cell(r, 4), self._cell(r, 5),
                 self._cell(r, 7))
                for r in range(self.table.rowCount())
            ]
            if rows_to_insert:
                cur.executemany(
                    "INSERT INTO anil_ledger"
                    "(sort_order,start_date,end_date,days,particular,dr,cr,remarks)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    [(i, *row[1:]) for i, row in enumerate(rows_to_insert)]
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            from src.utils.app_logger import get_logger
            get_logger(__name__).error(f"[AnilHisab] _save_all failed, rolled back: {e}")

    def _cell(self, r, c):
        it = self.table.item(r, c)
        if not it: return ""
        import json
        from PyQt6.QtGui import QBrush
        txt = it.text().strip()
        bg = it.background().color().name() if isinstance(it.background(), QBrush) and it.background().color().isValid() and it.background().color().name() != '#000000' else ""
        fg = it.foreground().color().name() if isinstance(it.foreground(), QBrush) and it.foreground().color().isValid() and it.foreground().color().name() != '#000000' else ""
        if bg or fg:
            return json.dumps({"text": txt, "bg": bg, "fg": fg})
        # If it's a number column, we should return formatted, wait, actually format happens on display, but let's preserve existing logic.
        return _fmt(txt) if c in (4,5) and txt else txt

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, self._a_item("", _C if c in (0,1,2) else _L if c in (3,7) else _R))
        # Prefill start_date from previous row's end_date + 1 day so the chain is unbroken
        if r > 0:
            prev_end_it = self.table.item(r - 1, 1)
            prev_end_txt = prev_end_it.text().strip() if prev_end_it else ""
            if prev_end_txt:
                d1 = QDate.fromString(prev_end_txt, "yyyy-MM-dd")
                if d1.isValid():
                    new_start = self._a_item(d1.addDays(1).toString("yyyy-MM-dd"), _C)
                    new_start.setFlags(new_start.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, 0, new_start)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.scrollToBottom()
        self._recalc_all()
        self._save_all()

    def _on_cell_changed(self, row, col):
        """Save on any column edit; recalc balance on DR/CR change;
        recalc Days and auto-fill next start date on date change."""
        # Formula 1: Days = End Date - Start Date (current row only)
        if col in (0, 1):
            self._recalc_days(row)

        # Formula 2: Cascade start dates from next_row all the way to the end
        # of the ledger so the full chain stays correct after any single edit.
        if col == 1:  # end_date edited
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
                        start_it.setFlags(start_it.flags() & ~Qt.ItemFlag.ItemIsEditable)

                        # Advance d_end to this row's end date to keep chaining
                        next_end_it = self.table.item(current, 1)
                        next_end_txt = next_end_it.text().strip() if next_end_it else ""
                        if next_end_txt:
                            d_end = QDate.fromString(next_end_txt, "yyyy-MM-dd")
                            if not d_end.isValid():
                                break  # broken end date — stop cascading
                        else:
                            break  # empty end date — nothing to chain to
                        current += 1
                    self.table.blockSignals(False)
                    # Recompute Days, DR (interest), and Balances for all rows
                    # since changing dates changes Days → DR → Balance for every row.
                    self._recalc_all()

        if col in (_ANIL_DR, _ANIL_CR):
            self._recalc_all()
        self._save_all()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        self._btn_add.setEnabled(can_edit)


# ===========================================================================
# PAYMENT SHEET  (generic user-added sheets — column view only)
