import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QScrollArea, QFrame,
    QSizePolicy, QLabel, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer
from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

from .shared import (
    _bold_font, _norm_font, _TABLE_STYLE, _SECTION_HEADER_STYLE,
    _BTN_SECONDARY, _setup_smart_header,
)

# ===========================================================================
class _StyledTable(QWidget):
    """Colored-header table widget for PaymentSheet."""
    def __init__(self, title, headers, widths, header_color="#059669", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QLabel(title)
        hdr.setFont(_bold_font(11))
        hdr.setStyleSheet(_SECTION_HEADER_STYLE.format(color=header_color))
        lay.addWidget(hdr)

        self.table = QTableWidget(0, len(headers))
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        _setup_smart_header(self.table)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.table.setMinimumHeight(60)
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Row")
        self.btn_add.setStyleSheet(_BTN_SECONDARY)
        self.btn_add.setFixedHeight(26)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch()
        btn_row.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(btn_row)

        self.recalculate_height()
        self.table.model().rowsInserted.connect(lambda *_: self.recalculate_height())
        self.table.model().rowsRemoved.connect(lambda *_: self.recalculate_height())

    def recalculate_height(self):
        hh = self.table.horizontalHeader().height()
        rh = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        h = hh + rh + 6
        h = min(max(h, 60), 600)
        self.table.setMinimumHeight(h)
        self._recalc_width()
        self.table.setMaximumHeight(h)

    def _recalc_width(self):
        """Resize the widget to fit content width (sum of column widths + vertical scrollbar)."""
        total = sum(
            self.table.columnWidth(c) for c in range(self.table.columnCount())
        )
        total += self.table.verticalHeader().width() if self.table.verticalHeader().isVisible() else 0
        total += 20  # scrollbar + border padding
        self.table.setMinimumWidth(min(total, 1200))


class PaymentSheet(QWidget):
    """A user-created sheet containing one or more _StyledTable sub-tables.
    Data persists via a dedicated `payment_sheet_data` DB table.
    """

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg
        self._tables: list[_StyledTable] = []
        self._db_name = ""
        self._db = get_db_manager()
        self._sheet_key = cfg.get("tab", "Sheet")  # used as DB identity key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(20)

        cols = cfg.get("columns", [])
        headers = [c[0] for c in cols]
        widths  = [c[1] for c in cols]
        sections = cfg.get("sections", {0: ("Data", "#059669")})

        for row_key, (label, bg) in sections.items():
            t = _StyledTable(label, headers, widths, header_color=bg)
            t._section_key = str(row_key)  # DB identity within this sheet
            t._loading = False
            t._loaded = False
            t._save_timer = QTimer(t)
            t._save_timer.setSingleShot(True)
            t._save_timer.setInterval(400)
            t._save_timer.timeout.connect(lambda tbl=t: self._save_table(tbl))
            t.btn_add.clicked.connect(lambda _, tbl=t: self._add_row(tbl))
            self._tables.append(t)
            c_lay.addWidget(t)
            # Wire persistence
            def _on_payment_sheet_change(item, tbl=t):
                if getattr(tbl, '_loading', False):
                    return
                tbl.table.resizeColumnToContents(item.column())
                tbl._recalc_width()
                tbl._save_timer.start()
            t.table.itemChanged.connect(_on_payment_sheet_change)

        c_lay.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    # ---------------------------------------------------------------- DB --
    def _ensure_db_table(self):
        """Create the payment_sheet_data table if it doesn't exist."""
        if not self._db_name:
            return
        ddl = (
            "CREATE TABLE payment_sheet_data "
            "(sheet_key NVARCHAR(200), section_key NVARCHAR(100), "
            " row_idx INT, col_idx INT, cell_text NVARCHAR(MAX), "
            " PRIMARY KEY (sheet_key, section_key, row_idx, col_idx))"
        )
        self._db.ensure_table(self._db_name, "payment_sheet_data", ddl)

    def _load_table(self, tbl: "_StyledTable"):
        if not self._db_name:
            return
        tbl._loading = True
        try:
            rows = self._db.execute_query(
                self._db_name,
                "SELECT row_idx, col_idx, cell_text FROM payment_sheet_data "
                "WHERE sheet_key=? AND section_key=? ORDER BY row_idx, col_idx",
                (self._sheet_key, tbl._section_key)
            ) or []
            tbl.table.blockSignals(True)
            tbl.table.setRowCount(0)
            for r, c, txt in rows:
                while tbl.table.rowCount() <= int(r):
                    tbl.table.insertRow(tbl.table.rowCount())
                    for ci in range(tbl.table.columnCount()):
                        tbl.table.setItem(tbl.table.rowCount() - 1, ci, QTableWidgetItem(""))
                tbl.table.setItem(int(r), int(c), QTableWidgetItem(txt or ""))
            tbl.table.blockSignals(False)
            tbl.recalculate_height()
            tbl._loaded = True
        finally:
            tbl._loading = False

    def _save_table(self, tbl: "_StyledTable"):
        if not self._db_name or getattr(tbl, '_loading', False):
            return
        # Guard against wiping if the table has not been populated from DB
        if not getattr(tbl, '_loaded', False):
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM payment_sheet_data WHERE sheet_key=? AND section_key=?",
                (self._sheet_key, tbl._section_key)
            )
            rows_to_insert = []
            for r in range(tbl.table.rowCount()):
                for c in range(tbl.table.columnCount()):
                    it = tbl.table.item(r, c)
                    val = it.text().strip() if it else ""
                    if val:
                        rows_to_insert.append((self._sheet_key, tbl._section_key, r, c, val))
            if rows_to_insert:
                cur.executemany(
                    "INSERT INTO payment_sheet_data"
                    " (sheet_key, section_key, row_idx, col_idx, cell_text)"
                    " VALUES (?, ?, ?, ?, ?)",
                    rows_to_insert
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[PaymentSheet] _save_table error, rolled back: {e}")
        finally:
            cur.close()

    def _add_row(self, tbl: "_StyledTable"):
        r = tbl.table.rowCount()
        tbl.table.insertRow(r)
        for c in range(tbl.table.columnCount()):
            tbl.table.setItem(r, c, QTableWidgetItem(""))
        tbl.recalculate_height()
        # Empty row is not saved until the user types in it (debounced on itemChanged)

    def set_company_path(self, path: str):
        """Bug 1c: Wire DB so all table data persists across restarts."""
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        from src.logic.db_manager import get_db_manager
        get_db_manager().ensure_database_exists(self._db_name, path)
        self._ensure_db_table()
        for tbl in self._tables:
            self._load_table(tbl)

    def setEditTriggers(self, trigs):
        for t in self._tables:
            t.table.setEditTriggers(trigs)

    def apply_edit_mode(self, can_edit: bool):
        trigs = (
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self.setEditTriggers(trigs)

    def delete_from_db(self):
        """Remove all saved data for this sheet from the database."""
        if not self._db_name:
            return
        try:
            self._db.execute_query(
                self._db_name,
                "DELETE FROM payment_sheet_data WHERE sheet_key=?",
                (self._sheet_key,), fetch=False)
        except Exception as e:
            logger.error(f"[PaymentSheet] delete_from_db error: {e}")


# ===========================================================================
# MAIN WIDGET
