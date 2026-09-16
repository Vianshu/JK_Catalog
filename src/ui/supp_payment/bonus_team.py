import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidgetItem,
)
from src.logic.db_manager import build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

from .shared import (
    _PrintExportMixin, _BTN_PRIMARY, _DbTable,
)

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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = _DbTable("bonus_data", _BONUS_HEADERS, _BONUS_WIDTHS, row_count=30)
        layout.addWidget(self.table, 1)

        right_bar = QWidget()
        right_bar.setStyleSheet("background:#f8fafc; border-left:1px solid #e2e8f0;")
        right_bar.setFixedWidth(52)
        tlay = QVBoxLayout(right_bar)
        tlay.setContentsMargins(6, 16, 6, 16)
        tlay.setSpacing(12)
        def on_toggle_bonus(expanded):
            if expanded:
                self._btn_add.setText(" Add Row")
            else:
                self._btn_add.setText("")

        self._init_print_export(tlay, "Bonus Details",
                                  table_getter=lambda: [{"title": "", "table": self.table}], right_bar=right_bar, on_toggle_cb=on_toggle_bonus)

        from src.ui.supp_payment.shared import get_icon
        self._btn_add = QPushButton()
        self._btn_add.setIcon(get_icon("add.svg"))
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        
        tlay.addStretch()
        
        layout.addWidget(right_bar, 0)

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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        total_cols = 4 + len(self._year_labels) * 3
        headers = ["S.N", "Location", "Post", "Name of Employee"]
        for yr in self._year_labels:
            headers += ["", yr, "Salary"]
        widths = [40, 70, 110, 190]
        for _ in self._year_labels:
            widths += [30, 90, 90]

        self.table = _DbTable("team_list_data", headers, widths, row_count=40)
        self.table.setColumnHidden(0, True)
        self.table.can_manage_col_fn = self._can_manage_col
        layout.addWidget(self.table, 1)

        right_bar = QWidget()
        right_bar.setStyleSheet("background:#f8fafc; border-left:1px solid #e2e8f0;")
        right_bar.setFixedWidth(52)
        tlay = QVBoxLayout(right_bar)
        tlay.setContentsMargins(6, 16, 6, 16)
        tlay.setSpacing(12)
        
        def on_toggle_team(expanded):
            if expanded:
                self._btn_add_yr.setText(" Add Year")
                self._btn_add_emp.setText(" Add Row")
            else:
                self._btn_add_yr.setText("")
                self._btn_add_emp.setText("")

        self._init_print_export(tlay, "Team List",
                                  table_getter=self._get_tables_for_export,
                                  print_table_getter=self._get_tables_for_print, right_bar=right_bar, on_toggle_cb=on_toggle_team)
        
        from src.ui.supp_payment.shared import get_icon
        self._btn_add_yr = QPushButton()
        self._btn_add_yr.setIcon(get_icon("add.svg"))
        self._btn_add_yr.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_yr.setFixedHeight(32)
        self._btn_add_yr.clicked.connect(self._add_year)
        tlay.addWidget(self._btn_add_yr)

        self._btn_add_emp = QPushButton()
        self._btn_add_emp.setIcon(get_icon("user_add.svg"))
        self._btn_add_emp.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_emp.setFixedHeight(32)
        self._btn_add_emp.clicked.connect(self._add_employee)
        tlay.addWidget(self._btn_add_emp)
        
        tlay.addStretch()
        
        layout.addWidget(right_bar, 0)

    
    def _get_year_groups(self):
        import re
        groups = []
        fixed = []
        i = 0
        while i < self.table.columnCount():
            h1 = self.table.horizontalHeaderItem(i+1) if i+1 < self.table.columnCount() else None
            is_year_group = False
            if h1 and h1.text():
                txt = h1.text().strip()
                if re.match(r'^\d{4}-\d{2}$', txt) or "New Year" in txt:
                    is_year_group = True
            
            if is_year_group and i+2 < self.table.columnCount():
                groups.append([i, i+1, i+2])
                i += 3
            else:
                fixed.append(i)
                i += 1
        return fixed, groups

    def _get_tables_for_export(self):
        fixed, groups = self._get_year_groups()
        truncate_groups = [tuple(g) for g in groups]
        return [{"title": "", "table": self.table, "truncate_groups": truncate_groups}]

    def _get_tables_for_print(self):
        fixed, groups = self._get_year_groups()
        YEARS_PER_PAGE = 3
        tables = []
        for page_idx in range(0, max(len(groups), 1), YEARS_PER_PAGE):
            chunk = groups[page_idx : page_idx + YEARS_PER_PAGE]
            col_range = set(fixed)
            for grp in chunk:
                col_range.update(grp)
            
            yr_names = []
            for grp in chunk:
                h = self.table.horizontalHeaderItem(grp[1])
                if h: yr_names.append(h.text().strip())
                
            page_title = "Team List — " + ", ".join(yr_names) if yr_names else "Team List"
            tables.append({
                "title": page_title,
                "table": self.table,
                "col_range": col_range,
                "page_break_before": page_idx > 0,
            })
        return tables

    def _find_year_start_index(self):
        import re
        for c in range(self.table.columnCount()):
            h = self.table.horizontalHeaderItem(c)
            txt = h.text().strip() if h else ""
            if re.match(r'^\d{4}-\d{2}$', txt) or "New Year" in txt:
                if c > 0:
                    h_prev = self.table.horizontalHeaderItem(c - 1)
                    txt_prev = h_prev.text().strip() if h_prev else ""
                    if txt_prev == "":
                        return c - 1
                return c
        return self.table.columnCount()

    def _find_year_insert_index(self):
        return self._find_year_start_index()

    def _can_manage_col(self, col_idx: int, action: str) -> bool:
        """Restricts manual column addition/removal inside or after the year section.
        Only 'Add Year' can manage the year section.
        """
        year_start = self._find_year_start_index()

        # Validation for raw insertion index in _insert_col:
        if action == "insert_raw":
            return col_idx <= year_start

        # For context menu actions on header index col_idx:
        # If clicked in the year section (col_idx >= year_start):
        if col_idx >= year_start:
            return False

        # If clicked before the year section (col_idx < year_start):
        if action in ("insert_left", "rename", "delete"):
            return True
        if action == "insert_right":
            # Right of col_idx inserts at col_idx + 1.
            # Even if col_idx == year_start - 1, col_idx + 1 == year_start,
            # which inserts right before the year section, pushing it right.
            return True

        return False

    def _add_year(self):
        if not self._can_edit:
            return
        
        insert_idx = self._find_year_start_index()
        
        latest = self._year_labels[0] if self._year_labels else "2082-83"
        parts = latest.split('-')
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            new_yr = f"{int(parts[0])+1}-{int(parts[1])+1}"
        else:
            new_yr = "New Year"
        self._year_labels.insert(0, new_yr)
        
        # Shift database
        db_name = self.table._db_name
        if db_name:
            conn = self.table._db.get_connection(db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE team_list_data SET col_idx = col_idx + 3 WHERE col_idx >= ?", (insert_idx,))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"[TeamListTab] DB Shift Error: {e}")
                finally:
                    cur.close()
                    
        self.table.insertColumn(insert_idx)
        self.table.insertColumn(insert_idx)
        self.table.insertColumn(insert_idx)
        self.table.setColumnWidth(insert_idx, 30)
        self.table.setColumnWidth(insert_idx + 1, 90)
        self.table.setColumnWidth(insert_idx + 2, 90)
        self.table.setHorizontalHeaderItem(insert_idx, QTableWidgetItem(""))
        self.table.setHorizontalHeaderItem(insert_idx + 1, QTableWidgetItem(new_yr))
        self.table.setHorizontalHeaderItem(insert_idx + 2, QTableWidgetItem("Salary"))
        
        if hasattr(self.table, '_save_cols'):
            self.table._save_cols()
        self.table.load_from_db()

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


