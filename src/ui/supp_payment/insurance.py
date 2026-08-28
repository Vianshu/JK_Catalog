# =============================================================================
# insurance_tab.py — InsuranceTab
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
# INSURANCE TAB
# ===========================================================================
_INS_SECTIONS = [
    ("Human Insurance",   "#1A3A5C", "ins_human",
     [("Location",80),("Post",110),("Name of Employee",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
    ("Vehicle Insurance", "#8B4513", "ins_vehicle",
     [("Location",80),("Post",110),("Name of Employee",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
    ("Stock Insurance",           "#1E4D2B", "ins_stock",
     [("Location",80),("Post",110),("Description",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
]


class InsuranceTab(QWidget, _PrintExportMixin):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._tables = []
        self._date_delegate = ModernTableDelegate(self, cell_type="date")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top bar
        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(42)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Insurance Details")
        lbl.setFont(_bold_font(11))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()
        self._init_print_export(tlay, "Insurance", table_getter=self._get_tables_for_export)
        layout.addWidget(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:#f8fafc;}")

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(0)

        for title, color, tname, cols in _INS_SECTIONS:
            # Section header row: title on the left, Add Row button on the right
            hdr_row = QWidget()
            hdr_row.setStyleSheet(f"background: {color}; color: #ffffff; padding: 4px 8px; font-weight: 800; font-size: 11pt; border: none;")
            hdr_lay = QHBoxLayout(hdr_row)
            hdr_lay.setContentsMargins(10, 4, 8, 4)
            hdr_lay.setSpacing(8)

            hdr_lbl = QLabel(title)
            hdr_lbl.setFont(_bold_font(11))
            hdr_lbl.setStyleSheet("background: transparent; border: none;")
            hdr_lay.addWidget(hdr_lbl)
            hdr_lay.addStretch()

            add_btn = QPushButton("+ Add Row")
            add_btn.setFixedHeight(24)
            add_btn.setStyleSheet(
                "QPushButton { background: #f1f5f9; color: #475569; "
                "border: 1px solid #cbd5e1; border-radius: 4px; "
                "padding: 0 10px; font-size: 10pt; }"
                "QPushButton:hover { background: #e2e8f0; }"
                "QPushButton:pressed { background: #cbd5e1; }"
            )
            hdr_lay.addWidget(add_btn)

            c_lay.addWidget(hdr_row)

            headers = [c[0] for c in cols]
            widths  = [c[1] for c in cols]
            tbl = _DbTable(tname, headers, widths)

            # Apply date delegates to start/end date columns (indices 4 and 5)
            tbl.setItemDelegateForColumn(4, ModernTableDelegate(tbl, cell_type="date"))
            tbl.setItemDelegateForColumn(5, ModernTableDelegate(tbl, cell_type="date"))

            # Wire height recalcs
            tbl.model().rowsInserted.connect(lambda *_, t=tbl: self._recalc_table_height(t))
            tbl.model().rowsRemoved.connect(lambda *_, t=tbl: self._recalc_table_height(t))

            # Wire button to its table now that tbl is defined
            add_btn.clicked.connect(lambda _, t=tbl: t.add_row())

            c_lay.addWidget(tbl)
            self._tables.append((title, tname, tbl))


        c_lay.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _recalc_table_height(self, tbl):
        if not tbl.isVisible():
            return
        hh = tbl.horizontalHeader().height()
        rh = sum(tbl.rowHeight(r) for r in range(tbl.rowCount()))
        h = hh + rh + 4
        h = min(max(h, 60), 800)
        tbl.setMinimumHeight(h)
        tbl.setMaximumHeight(h)

    def _get_tables_for_export(self):
        """Collect all insurance sub-tables for export/print."""
        return [{"title": title, "table": tbl, "page_break_before": True} for title, tname, tbl in self._tables]

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        db = get_db_manager()
        db.ensure_database_exists(db_name, path)
        for title, tname, tbl in self._tables:
            tbl.set_db_name(db_name, path)
            self._recalc_table_height(tbl)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        for _, tname, tbl in self._tables:
            tbl.apply_edit_mode(can_edit)


