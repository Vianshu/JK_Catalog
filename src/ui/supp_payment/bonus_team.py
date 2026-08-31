# =============================================================================
# bonus_team_tab.py — BonusTab + TeamListTab
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
# BONUS DETAILS TAB
# ===========================================================================
_BONUS_LOC_COLORS = {
    "HO":  "#E8F4FD", "BTM": "#FFF3E0",
    "JNK": "#F3E5F5", "NGT": "#E8F5E9",
}
_BONUS_HEADERS = ["Location", "Post", "Name of Employee", "Diwali Bonus", "Remarks"]
_BONUS_WIDTHS  = [90, 110, 200, 120, 220]


class BonusTab(QWidget, _PrintExportMixin):
    def __init__(self):
        super().__init__()
        self._can_edit = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Bonus Details")
        lbl.setFont(_bold_font(11))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()
        self._init_print_export(tlay, "Bonus Details",
                                  table_getter=lambda: [{"title": "", "table": self.table}])

        self._btn_add = QPushButton("+ Add Row")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        layout.addWidget(top_bar)

        self.table = _DbTable("bonus_data", _BONUS_HEADERS, _BONUS_WIDTHS, row_count=30)
        layout.addWidget(self.table)

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.add_row()

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(db_name, path)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.apply_edit_mode(can_edit)
        self._btn_add.setEnabled(can_edit)


# ===========================================================================
# TEAM LIST TAB
# ===========================================================================
class TeamListTab(QWidget, _PrintExportMixin):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._year_labels = [
            "2082-83", "2081-82", "2080-81", "2079-80",
            "2078-79", "2077-78", "2076-77", "2075-76",
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Team List")
        lbl.setFont(_bold_font(11))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()
        self._init_print_export(tlay, "Team List",
                                   table_getter=self._get_tables_for_export,
                                   print_table_getter=self._get_tables_for_print)

        self._btn_add_yr  = QPushButton("+ Add Year")
        self._btn_add_yr.setStyleSheet(_BTN_SECONDARY)
        self._btn_add_yr.setFixedHeight(32)
        self._btn_add_yr.clicked.connect(self._add_year)
        tlay.addWidget(self._btn_add_yr)

        
        self._btn_add_emp = QPushButton("+ Add Employee")
        self._btn_add_emp.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_emp.setFixedHeight(32)
        self._btn_add_emp.clicked.connect(self._add_employee)
        tlay.addWidget(self._btn_add_emp)
        layout.addWidget(top_bar)

        total_cols = 4 + len(self._year_labels) * 3
        headers = ["S.N", "Location", "Post", "Name of Employee"]
        for yr in self._year_labels:
            headers += ["", yr, "Salary"]
        widths = [40, 70, 110, 190]
        for _ in self._year_labels:
            widths += [30, 90, 90]

        self.table = _DbTable("team_list_data", headers, widths, row_count=40)
        layout.addWidget(self.table)

    
    def _get_tables_for_export(self):
        """For Excel export — unchanged, all columns in one sheet."""
        truncate_groups = []
        base_col = 4  # S.N, Location, Post, Name
        for i in range(len(self._year_labels)):
            truncate_groups.append((base_col + i*3, base_col + i*3 + 1, base_col + i*3 + 2))
        return [{"title": "", "table": self.table, "truncate_groups": truncate_groups}]

    def _get_tables_for_print(self):
        """For print — split wide table into column-pages.
        Fixed cols (0-3: SN/Location/Post/Name) repeat on every page.
        Year groups (3 cols each) are distributed: up to YEARS_PER_PAGE per page.
        """
        YEARS_PER_PAGE = 3          # adjust if needed
        fixed_cols = list(range(4)) # S.N, Location, Post, Name
        year_groups = []
        base = 4
        for i in range(len(self._year_labels)):
            year_groups.append([base + i*3, base + i*3 + 1, base + i*3 + 2])

        tables = []
        for page_idx in range(0, max(len(year_groups), 1), YEARS_PER_PAGE):
            chunk = year_groups[page_idx : page_idx + YEARS_PER_PAGE]
            col_range = set(fixed_cols)
            for grp in chunk:
                col_range.update(grp)
            yr_names = [self._year_labels[page_idx + i]
                        for i in range(len(chunk))]
            page_title = "Team List — " + ", ".join(yr_names) if yr_names else "Team List"
            tables.append({
                "title": page_title,
                "table": self.table,
                "col_range": col_range,
                "page_break_before": page_idx > 0,
            })
        return tables

    def _add_year(self):
        if not self._can_edit:
            return
        latest = self._year_labels[0] if self._year_labels else "2082-83"
        parts = latest.split('-')
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            new_yr = f"{int(parts[0])+1}-{int(parts[1])+1}"
        else:
            new_yr = "New Year"
        self._year_labels.insert(0, new_yr)
        # Insert 3 new columns at position 4
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        self.table.setColumnWidth(4, 30)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 90)
        self.table.setHorizontalHeaderItem(4, QTableWidgetItem(""))
        self.table.setHorizontalHeaderItem(5, QTableWidgetItem(new_yr))
        self.table.setHorizontalHeaderItem(6, QTableWidgetItem("Salary"))
        self.table.save_to_db()

    def _add_employee(self):
        if not self._can_edit:
            return
        self.table.add_row()

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(db_name, path)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.apply_edit_mode(can_edit)
        self._btn_add_yr.setEnabled(can_edit)
        self._btn_add_emp.setEnabled(can_edit)


