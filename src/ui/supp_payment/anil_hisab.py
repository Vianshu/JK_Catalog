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
# ANIL DAI HISAB TAB ΓÇö Running Balance Ledger
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

        self._db_name  = ""
        self._db       = get_db_manager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)

        lbl = QLabel("Anil Dai Hisab ΓÇö Running Balance Ledger")
        lbl.setFont(_bold_font(12))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()
        self._init_print_export(tlay, "Anil Dai Hisab",
                                  table_getter=lambda: [{"title": "", "table": self.table}])

        self._btn_add = QPushButton("+ Add Row")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        layout.addWidget(top_bar)

        # Table
        n = len(_ANIL_COLS)
        self.table = QTableWidget(0, n)
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setHorizontalHeaderLabels([c[0] for c in _ANIL_COLS])
        for i, (_, w) in enumerate(_ANIL_COLS):
            self.table.setColumnWidth(i, w)
        _setup_smart_header(self.table)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setItemDelegate(ModernTableDelegate(self.table))
        # Apply UniversalCellDelegate globally for seamless text editing
        self.table.setItemDelegate(ModernTableDelegate(self.table))
        
        # Date delegates on Start Date (0) and End Date (1)
        self.table.setItemDelegateForColumn(0, ModernTableDelegate(self.table, cell_type="date"))
        self.table.setItemDelegateForColumn(1, ModernTableDelegate(self.table, cell_type="date"))

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)

        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

    def _row_ctx(self, pos):
        if not self._can_edit:
            return
        item = self.table.itemAt(pos)
        r = item.row() if item else self.table.currentRow()
        menu = QMenu(self)
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QBrush, QColor
        menu.setStyleSheet(_MENU_STYLE)

        a_add_above = menu.addAction("Γ₧ò  Add Row Above")
        a_add_below = menu.addAction("Γ₧ò  Add Row Below")
        menu.addSeparator()

        a_del = menu.addAction("🗑  Delete Row")
        menu.addSeparator()
        a_color = menu.addAction("🎨  Set Cell Color")
        a_text_color = menu.addAction("🖋  Set Text Color")
        a_clear = menu.addAction("🧹  Clear Colors")
        
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if act == a_add_above and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r)
            for c in range(self.table.columnCount()):
                self.table.setItem(r, c, self._a_item("", _C if c in (0,1,2) else _L if c in (3,7) else _R))
            self.table.blockSignals(False)
            self._save_all()
        elif act == a_add_below and r >= 0:
            self.table.blockSignals(True)
            self.table.insertRow(r + 1)
            for c in range(self.table.columnCount()):
                self.table.setItem(r+1, c, self._a_item("", _C if c in (0,1,2) else _L if c in (3,7) else _R))
            self.table.blockSignals(False)
            self._save_all()
        elif act == a_del and r >= 0:
            self.table.removeRow(r)
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
        self._load_from_db()

    def _ensure_table(self):
        ddl = ("CREATE TABLE anil_ledger "
               "(id INT IDENTITY PRIMARY KEY, sort_order INT, "
               "start_date NVARCHAR(MAX), end_date NVARCHAR(MAX), days NVARCHAR(MAX), "
               "particular NVARCHAR(MAX), dr NVARCHAR(MAX), cr NVARCHAR(MAX), "
               "remarks NVARCHAR(MAX))")
        self._db.ensure_table(self._db_name, "anil_ledger", ddl)
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                for col in ["start_date", "end_date", "days", "dr", "cr"]:
                    cur.execute(f"ALTER TABLE anil_ledger ALTER COLUMN {col} NVARCHAR(MAX)")
                conn.commit()
        except:
            pass

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
            self.table.setItem(r, 0, _unpack(start, _C))
            self.table.setItem(r, 1, _unpack(end, _C))
            self.table.setItem(r, 2, _unpack(days, _C))
            self.table.setItem(r, 3, _unpack(part, _L))
            self.table.setItem(r, 4, _unpack(dr, _R))
            self.table.setItem(r, 5, _unpack(cr, _R))
            self.table.setItem(r, 7, _unpack(remarks, _L))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        # Recalc balances silently after load
        self._recalc_all()

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
            if new_bal < 0:
                bal_it.setForeground(QBrush(QColor("#dc2626")))
            elif new_bal > 0:
                bal_it.setForeground(QBrush(QColor("#16a34a")))
            self.table.setItem(r, _ANIL_BAL, bal_it)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()

    def _save_all(self):
        """Save all rows using execute_query with fetch=False for writes."""
        if not self._db_name:
            return
        try:
            self._db.execute_query(self._db_name,
                "DELETE FROM anil_ledger", fetch=False)
            for r in range(self.table.rowCount()):
                self._db.execute_query(
                    self._db_name,
                    "INSERT INTO anil_ledger"
                    "(sort_order,start_date,end_date,days,particular,dr,cr,remarks)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (r, self._cell(r,0), self._cell(r,1), self._cell(r,2),
                        self._cell(r,3), self._cell(r,4), self._cell(r,5),
                        self._cell(r,7)),
                    fetch=False)
        except Exception as e:
            print("[AnilHisab] _save_all error:", e)

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
            self.table.setItem(r, c, self._a_item(""))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.scrollToBottom()
        self._save_all()

    def _on_cell_changed(self, row, col):
        """Save on any column edit; also recalc running balance when DR/CR changes."""
        if col in (_ANIL_DR, _ANIL_CR):
            self._recalc_all()
        self._save_all()  # Bug 1a: persist dates, particular, remarks, etc.

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        self._btn_add.setEnabled(can_edit)


# ===========================================================================
# PAYMENT SHEET  (generic user-added sheets ΓÇö column view only)
