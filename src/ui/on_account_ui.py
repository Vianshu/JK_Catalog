"""
Tally Internal -> On Account Screen.

Displays ledgers where:
- Group = 'Sundry Debtors'
- On_Account_Value is non-zero (both positive and negative non-zero values qualify)
- Excludes subgroups: 'Othere Account' / 'Other Account' and 'Recovery party list'
Filtered at the database layer from dbo.row_ledger_data.
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt

from src.logic.db_manager import get_db_manager, build_logical_name
from src.ui.table_nav_mixin import UniversalCellDelegate, UNIVERSAL_TABLE_STYLE
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically for amounts."""
    def __init__(self, text: str = "", num_value: float = None):
        super().__init__(text)
        if num_value is not None:
            self.num_value = float(num_value)
        else:
            try:
                self.num_value = float(text.replace(",", "").strip())
            except Exception:
                self.num_value = 0.0

    def __lt__(self, other):
        if hasattr(other, 'num_value'):
            return self.num_value < other.num_value
        try:
            return self.num_value < float(other.text().replace(",", "").strip())
        except Exception:
            return super().__lt__(other)


class OnAccountUI(QWidget):
    """Tally Internal On Account table view."""
    def __init__(self):
        super().__init__()
        self.setObjectName("OnAccountContainer")
        self.db = get_db_manager()
        self.current_company_path = ""
        self.current_company_name = ""
        self.db_name = ""

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header bar
        top_bar = QHBoxLayout()
        title = QLabel("On Account")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #0f172a;")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter ledger name...")
        self.search_input.setFixedWidth(260)
        self.search_input.textChanged.connect(self._filter_table)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_refresh.clicked.connect(self.load_data)

        top_bar.addWidget(title)
        top_bar.addStretch()
        top_bar.addWidget(self.search_input)
        top_bar.addWidget(self.btn_refresh)
        layout.addLayout(top_bar)

        # Table
        self.table = QTableWidget()
        self.table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegate(UniversalCellDelegate(self.table))

        headers = ["Name", "On Account"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 180)
        header.sectionDoubleClicked.connect(self._on_header_double_clicked)

        layout.addWidget(self.table)

    def load_data(self, company_path: str = None):
        if company_path:
            self.current_company_path = company_path
            self.current_company_name = os.path.basename(company_path)
            self.db_name = build_logical_name(self.current_company_name, company_path=self.current_company_path)

        if not self.db_name or not self.db.database_exists(self.db_name):
            self.table.setRowCount(0)
            return

        conn = self.db.get_connection(self.db_name)
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'row_ledger_data'
            """)
            if cur.fetchone()[0] == 0:
                self.table.setRowCount(0)
                return

            # Query-level filtering: Group = 'Sundry Debtors' AND On_Account_Value != 0
            # Exclude subgroups: 'Othere Account' / 'Other Account' and 'Recovery party list'
            query = """
                SELECT Name, On_Account_Value
                FROM dbo.row_ledger_data
                WHERE [Group] = 'Sundry Debtors' 
                  AND On_Account_Value != 0
                  AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
                  AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
                  AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
                  AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%recovery%'
                ORDER BY Name
            """
            cur.execute(query)
            rows = cur.fetchall()

            self.table.blockSignals(True)
            self.table.setRowCount(len(rows))

            for r_idx, r in enumerate(rows):
                # Name
                self.table.setItem(r_idx, 0, QTableWidgetItem(str(r[0] or "")))

                # On Account Value (numeric, right-aligned)
                val_on_acc = float(r[1] or 0.0)
                it_on_acc = NumericTableWidgetItem(f"{val_on_acc:,.2f}", val_on_acc)
                it_on_acc.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r_idx, 1, it_on_acc)

            self.table.blockSignals(False)

        except Exception as e:
            logger.error(f"[OnAccountUI.load_data] error: {e}")

    def _on_header_double_clicked(self, logical_index: int):
        """Sort columns on double-click (Name alphabetically, On Account numerically)."""
        cur_col = getattr(self.table, '_sort_col', -1)
        cur_order = getattr(self.table, '_sort_order', None)
        if cur_col == logical_index and cur_order == Qt.SortOrder.AscendingOrder:
            order = Qt.SortOrder.DescendingOrder
        else:
            order = Qt.SortOrder.AscendingOrder
        self.table._sort_col = logical_index
        self.table._sort_order = order
        self.table.sortItems(logical_index, order)

    def _filter_table(self, query: str):
        q = query.strip().lower()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            self.table.setRowHidden(r, q not in it.text().lower() if it else False)

    def get_current_table(self) -> tuple[str, QTableWidget]:
        return "Tally Internal - On Account", self.table

