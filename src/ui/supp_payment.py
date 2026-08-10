from PyQt6.QtWidgets import (
    QColorDialog, QGridLayout,
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QObject, QEvent
from PyQt6.QtGui import QFont, QColor, QBrush
from src.logic.db_manager import get_db_manager, build_logical_name

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_H_BOLD = QFont("Arial", 10, QFont.Weight.Bold)
_H_NORM = QFont("Arial", 10)


def _item(text, bold=False, bg=None, fg=None, align=None):
    it = QTableWidgetItem("" if text is None else str(text))
    if bold:
        it.setFont(_H_BOLD)
    if bg:
        it.setBackground(QBrush(QColor(bg)))
    if fg:
        it.setForeground(QBrush(QColor(fg)))
    if align:
        it.setTextAlignment(align)
    return it


def _num(val):
    return _item(val,
                 align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class HeaderEditFilter(QObject):
    """Makes a QTableWidget's QHeaderView editable on double-click and colorable on right-click."""
    def __init__(self, table: QTableWidget, settings_key: str):
        super().__init__(table)
        self.table = table
        self.settings_key = settings_key
        self.header = table.horizontalHeader()
        self.header.viewport().installEventFilter(self)
        self.header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._on_context_menu)
        
        self.editor = None
        self.edit_col = -1

        from PyQt6.QtCore import QSettings
        self.settings = QSettings("JKCatalog", "HeaderCustomizations")
        self.customs = self.settings.value(self.settings_key, {})
        if not isinstance(self.customs, dict):
            self.customs = {}
            
    def apply_customs(self):
        for col in range(self.table.columnCount()):
            key = str(col)
            if key in self.customs:
                if "name" in self.customs[key]:
                    it = self.table.horizontalHeaderItem(col)
                    if not it:
                        it = QTableWidgetItem()
                        self.table.setHorizontalHeaderItem(col, it)
                    it.setText(self.customs[key]["name"])
        self._update_stylesheet()

    def eventFilter(self, obj, event):
        try:
            if obj == self.header.viewport() and event.type() == QEvent.Type.MouseButtonDblClick:
                pos = event.position().toPoint()
                col = self.header.logicalIndexAt(pos)
                if col >= 0:
                    self._start_editing(col)
                    return True
        except RuntimeError:
            pass
        return super().eventFilter(obj, event)
        
    def _start_editing(self, col):
        from PyQt6.QtWidgets import QLineEdit
        self.edit_col = col
        rect = self.header.sectionViewportPosition(col)
        width = self.header.sectionSize(col)
        height = self.header.height()
        
        self.editor = QLineEdit(self.header.viewport())
        self.editor.setGeometry(rect, 0, width, height)
        it = self.table.horizontalHeaderItem(col)
        self.editor.setText(it.text() if it else "")
        self.editor.selectAll()
        self.editor.setFocus()
        self.editor.show()
        
        self.editor.editingFinished.connect(self._finish_editing)
        
    def _finish_editing(self):
        if self.editor:
            new_text = self.editor.text()
            it = self.table.horizontalHeaderItem(self.edit_col)
            if not it:
                it = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(self.edit_col, it)
            it.setText(new_text)
            
            key = str(self.edit_col)
            if key not in self.customs: self.customs[key] = {}
            self.customs[key]["name"] = new_text
            self.settings.setValue(self.settings_key, self.customs)
            
            self.editor.deleteLater()
            self.editor = None

    def _on_context_menu(self, pos):
        col = self.header.logicalIndexAt(pos)
        if col < 0: return
        
        from PyQt6.QtWidgets import QMenu, QColorDialog
        menu = QMenu(self.table)
        action_bg_color = menu.addAction("🎨 Change Background Color")
        action_text_color = menu.addAction("🔤 Change Text Color")
        action = menu.exec(self.header.viewport().mapToGlobal(pos))
        
        if action == action_bg_color or action == action_text_color:
            color = QColorDialog.getColor()
            if color.isValid():
                key = str(col)
                if key not in self.customs: self.customs[key] = {}
                
                if action == action_bg_color:
                    self.customs[key]["color"] = color.name()
                else:
                    self.customs[key]["text_color"] = color.name()
                    
                self.settings.setValue(self.settings_key, self.customs)
                self._update_stylesheet()
                
    def _update_stylesheet(self):
        # We append to the table's stylesheet so it overrides existing styles with higher specificity
        base_style = getattr(self, "_base_style", None)
        if base_style is None:
            self._base_style = self.table.styleSheet()
            base_style = self._base_style
            
        dynamic_style = ""
        for col_str, custom in self.customs.items():
            bg = custom.get("color", "")
            fg = custom.get("text_color", "")
            if bg or fg:
                dynamic_style += f"QHeaderView::section:horizontal:logicalIndex({col_str}) {{"
                if bg: dynamic_style += f" background-color: {bg} !important;"
                if fg: dynamic_style += f" color: {fg} !important;"
                dynamic_style += " }\n"
                
        self.table.setStyleSheet(base_style + "\n" + dynamic_style)

# ===========================================================================
# A) INSURANCE TAB  –  three separate scrollable sub-tables
# ===========================================================================
_INS_COLS   = ["Location", "Post", "Name of Employee",
               "Amount", "Starting Date", "Ending Date"]
_INS_COL_W  = [100, 110, 200, 110, 110, 110]

_INS_SECTIONS = [
    ("Human Insurance Details",  "#1A3A5C"),
    ("Vehicle Insurance Details", "#8B4513"),
    ("Stock Insurance",           "#1E4D2B"),
]


class InsuranceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._tables = []
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Bar ---
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #f1f3f5; border-bottom: 1px solid #dee2e6;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(15, 8, 15, 8)
        
        title_lbl = QLabel("Insurance Details")
        title_lbl.setFont(_H_BOLD)
        title_lbl.setStyleSheet("color: #343a40; border: none;")
        top_lay.addWidget(title_lbl)
        top_lay.addStretch()
        
        from PyQt6.QtWidgets import QComboBox, QStackedWidget
        self.view_selector = QComboBox()
        self.view_selector.addItems(["Detailed Column View", "Classic Excel Grid View"])
        self.view_selector.setFont(_H_NORM)
        self.view_selector.setStyleSheet("padding: 4px 10px; border: 1px solid #ced4da; border-radius: 4px; background-color: white;")
        self.view_selector.currentIndexChanged.connect(self._switch_view)
        top_lay.addWidget(self.view_selector)
        
        main_layout.addWidget(top_bar)
        
        self.stack = QStackedWidget()
        
        # --- VIEW 1: Detailed Column View ---
        self.view1 = QWidget()
        v1_layout = QVBoxLayout(self.view1)
        v1_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(12, 8, 12, 8)
        vlay.setSpacing(10)

        # 3 Independent Grids for Detailed View
        self.human_grid = UniversalExcelGrid("ins_human", cols=6, excel_mode=False)
        self.vehicle_grid = UniversalExcelGrid("ins_vehicle", cols=6, excel_mode=False)
        self.stock_grid = UniversalExcelGrid("ins_stock", cols=6, excel_mode=False)
        
        self._tables = [self.human_grid, self.vehicle_grid, self.stock_grid]
        
        for grid, (title, color) in zip(self._tables, _INS_SECTIONS):
            # Create a section header
            lbl = QLabel(title)
            lbl.setFont(_H_BOLD)
            lbl.setStyleSheet(f"background:{color}; color:#fff; padding:6px 12px; border-radius:4px;")
            
            grid.setHorizontalHeaderLabels(_INS_COLS)
            for c, w in enumerate(_INS_COL_W):
                grid.setColumnWidth(c, w)
            grid.setMinimumHeight(150)
                
            vlay.addWidget(lbl)
            vlay.addWidget(grid)
            
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            vlay.addWidget(line)

        vlay.addStretch()
        scroll.setWidget(container)
        v1_layout.addWidget(scroll)
        self.stack.addWidget(self.view1)
        
        # --- VIEW 2: Excel Grid View ---
        self.view2 = QWidget()
        v2_layout = QVBoxLayout(self.view2)
        v2_layout.setContentsMargins(12, 12, 12, 12)
        
        self.grid = UniversalExcelGrid("ins_grid_data", cols=10, excel_mode=True)
        v2_layout.addWidget(self.grid)
        self.stack.addWidget(self.view2)
        
        main_layout.addWidget(self.stack)

    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)

    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        
        # Hook up all grids to DB
        self.grid.set_db_name(self._db_name)
        for t in self._tables:
            t.set_db_name(self._db_name)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        if hasattr(self.grid, 'apply_edit_mode'):
            self.grid.apply_edit_mode(can_edit)
        for t in self._tables:
            if hasattr(t, 'apply_edit_mode'):
                t.apply_edit_mode(can_edit)
    def _show_grid_context_menu(self, pos):
        if getattr(self, "_can_edit", True) == False: return
        
        # Determine which grid we are targeting
        if hasattr(self, "grid"):
            grid = self.grid
        elif hasattr(self, "table"):
            grid = self.table
        else:
            return

        menu = QMenu(self)
        action_insert_row_above = menu.addAction("Insert Row Above")
        action_insert_row_below = menu.addAction("Insert Row Below")
        menu.addSeparator()
        action_insert_col_left = menu.addAction("Insert Column Left")
        action_insert_col_right = menu.addAction("Insert Column Right")
        menu.addSeparator()
        action_delete_row = menu.addAction("Delete Row")
        action_delete_col = menu.addAction("Delete Column")
        
        item = grid.itemAt(pos)
        r = item.row() if item else grid.currentRow()
        c = item.column() if item else grid.currentColumn()
        
        if r < 0: r = 0
        if c < 0: c = 0
        
        action = menu.exec(grid.viewport().mapToGlobal(pos))
        
        if action == action_insert_row_above:
            grid.insertRow(r)
        elif action == action_insert_row_below:
            grid.insertRow(r + 1)
        elif action == action_insert_col_left:
            grid.insertColumn(c)
        elif action == action_insert_col_right:
            grid.insertColumn(c + 1)
        elif action == action_delete_row:
            grid.removeRow(r)
        elif action == action_delete_col:
            grid.removeColumn(c)


# ===========================================================================
# B) BONUS DETAILS TAB
# ===========================================================================
_BONUS_DATA = [
]

_BONUS_BASE_COLS = ["Location", "Post", "Employee Name", "Diwali Bonus", "Remarks"]
_BONUS_BASE_W    = [90, 110, 200, 110, 150]
_BONUS_LOC_BG    = {"HO": "#E8F4FD", "BTM": "#FFF3E0",
                    "JNK": "#F3E5F5", "NGT": "#E8F5E9"}


class BonusTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        self.table = UniversalExcelGrid('bonus_grid_data', cols=15, excel_mode=False)
        
        headers = ['Location', 'Post', 'Name of Employee', 'Diwali Bonus', '', 'Notes']
        headers += [""] * (15 - len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(5, 200)
        
        vlay.addWidget(self.table)
        
    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(self._db_name)
        
    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        if hasattr(self.table, 'apply_edit_mode'):
            self.table.apply_edit_mode(can_edit)


# ===========================================================================
# C) TEAM-LIST TAB  –  fixed left cols + year pairs (oldest -> newest ->)
# ===========================================================================
_YEAR_LABELS = []

# (location, post, name, {yr_label: (yr_month, salary)})
_TEAM_DATA = [
]

_TEAM_LOC_BG = {"HO":"#E3F2FD","BTM":"#FFF9C4","JNK":"#F3E5F5","NGT":"#E8F5E9"}
_FIXED_COLS  = [("Location",70),("Post",110),("Name",200)]
_FIXED_N     = len(_FIXED_COLS)


class TeamListTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        
        # Toolbar
        tbar = QHBoxLayout()
        tbar.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Team List (Excel View)")
        lbl.setFont(_H_BOLD)
        tbar.addWidget(lbl)
        tbar.addStretch()
        self._add_yr_btn = QPushButton("+ Add Year")
        self._add_yr_btn.setFixedHeight(28)
        self._add_yr_btn.clicked.connect(self._add_year)
        tbar.addWidget(self._add_yr_btn)
        vlay.addLayout(tbar)
        
        # Determine total cols
        self._year_labels = ["2082-83","2081-82","2080-81","2079-80","2078-79","2077-78","2076-77","2075-76"]
        total_cols = 4 + len(self._year_labels) * 3
        self.table = UniversalExcelGrid('teamlist_grid_data', cols=total_cols, excel_mode=False)
        
        self._rebuild_headers()
        vlay.addWidget(self.table)
        
    def _rebuild_headers(self):
        labels = ["S.N", "Location", "Post", "Name of Employee"]
        for yr in self._year_labels:
            labels += ["", yr, "Salary"]
        
        if self.table.columnCount() < len(labels):
            self.table.setColumnCount(len(labels))
            
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 180)
        for i in range(len(self._year_labels)):
            base = 4 + i * 3
            self.table.setColumnWidth(base, 30)
            self.table.setColumnWidth(base + 1, 80)
            self.table.setColumnWidth(base + 2, 85)
            
    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(self._db_name)
        
    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._add_yr_btn.setEnabled(can_edit)
        if hasattr(self.table, 'apply_edit_mode'):
            self.table.apply_edit_mode(can_edit)
            
    def _add_year(self):
        if not self._can_edit: return
        
        latest_yr = "2082-83"
        if self._year_labels:
            latest_yr = self._year_labels[0]
            parts = latest_yr.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                latest_yr = f"{int(parts[0])+1}-{int(parts[1])+1}"
                
        self._year_labels.insert(0, latest_yr)
        
        self.table.blockSignals(True)
        # Insert at index 4 (right after S.N, Location, Post, Name)
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        
        self._rebuild_headers()
        
        self.table.blockSignals(False)
        if hasattr(self.table, 'save_to_db'):
            self.table.save_to_db()


# ===========================================================================
# RECORD TAB  -  Supplier Bank Account Records (Vertical Format)
# Layout: each record spans 6 rows.
#   Col 0    : S.N. (spans 6 rows)
#   Col 1    : A/C of (spans 6 rows)
#   Col 2    : Acct 0 Label
#   Col 3    : Acct 0 Value
#   Col 4    : Spacer
#   Col 5    : Acct 1 Label
#   Col 6    : Acct 1 Value
#   ...
#   Row between records: 1 empty row for spacing
# ===========================================================================
_REC_FIELD_KEYS   = ["naam","thegana","baik","khata","rakam","jamma"]
_REC_FIELD_LABELS = ["\u0928\u093e\u092e","\u0920\u0947\u0917\u093e\u0928\u093e","\u092c\u0948\u0915",
                     "\u0916\u093e\u0924\u093e \u0928.","\u0930\u0915\u092e","\u091c\u092e\u094d\u092e\u093e \u0917\u0930\u094d\u0928\u0947"]
_REC_FIXED        = 2          # SN + A/C of
_REC_BLOCK        = 3          # Label + Value + Sep
_REC_LBL_W        = 70
_REC_VAL_W        = 220
_REC_SEP_W        = 20
_REC_ROW_H        = 24
_REC_GAP_H        = 30

# ---------------------------------------------------------------------------
# All 39 supplier records parsed from the Excel workbook.
# Each entry: (SN, "A/C of name", [acct0_dict, acct1_dict, acct2_dict])
# acct dict keys: naam, thegana, baik, khata, rakam, jamma
# ---------------------------------------------------------------------------
_RECORD_DATA = [
]

def _rec_col(acct: int, part: int) -> int:
    # part: 0=Label, 1=Value, 2=Spacer
    return _REC_FIXED + acct * _REC_BLOCK + part

# ===========================================================================
# TODAY PAYMENT TAB
# ===========================================================================

class UniversalExcelGrid(QTableWidget):
    """A generic, fully-featured Excel-like grid widget for all tabs."""
    def __init__(self, table_name: str, rows=50, cols=15, parent=None, excel_mode=False):
        super().__init__(rows, cols, parent)
        self._excel_mode = excel_mode  # True = always A,B,C... no DB-backed header names
        self.table_name = table_name
        self._db = get_db_manager()
        self._db_name = ""
        self._can_edit = True
        
        self.setFont(_H_NORM)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setVisible(True)
        def excel_col(n):
            res = ""
            while n >= 0:
                res = chr(65 + (n % 26)) + res
                n = n // 26 - 1
            return res
        self.setHorizontalHeaderLabels([excel_col(i) for i in range(cols)])
        self.verticalHeader().setDefaultSectionSize(25)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_grid_context_menu)
        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().customContextMenuRequested.connect(self._show_header_context_menu)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        
        self.setStyleSheet('''
            QTableWidget {
                gridline-color: #dee2e6;
                alternate-background-color: #f8f9fa;
                border: 1px solid #ced4da;
            }
            QTableWidget::item:selected {
                background-color: rgba(0, 0, 0, 0);
                border: 2px solid #0055ff;
            }
            QHeaderView::section:horizontal {
                background-color: #1A2035;
                color: #ffffff;
                padding: 4px;
                border: 1px solid #ced4da;
                font-weight: bold;
            }
        ''')
        
        for i in range(cols):
            self.setColumnWidth(i, 110)
                
        self.itemChanged.connect(self._grid_item_changed)
        self.horizontalHeader().sectionResized.connect(self._save_dragged_col_width)
        
    def _save_dragged_col_width(self, logicalIndex, oldSize, newSize):
        if not self._db_name: return
        # Save to DB so column widths are portable to client machines
        conn = self._db.get_connection(self._db_name)
        if not conn: return
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM " + self.table_name + " WHERE row_idx=-2 AND col_idx=?",
                (logicalIndex,))
            cur.execute(
                "INSERT INTO " + self.table_name +
                " (row_idx, col_idx, cell_text, bg_color) VALUES (-2,?,?,'')",
                (logicalIndex, str(newSize)))
            conn.commit()
        except Exception as e:
            conn.rollback()
        
    def set_db_name(self, db_name: str):
        self._db_name = db_name
        self._ensure_table()
        self.load_from_db()
        
    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        
    def _ensure_table(self):
        if not self._db_name: return
        ddl = f"CREATE TABLE {self.table_name} (row_idx INT NOT NULL, col_idx INT NOT NULL, cell_text NVARCHAR(MAX), bg_color NVARCHAR(20), PRIMARY KEY (row_idx, col_idx))"
        self._db.ensure_table(self._db_name, self.table_name, ddl)
        
    def keyPressEvent(self, event):
        if self._can_edit and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for item in self.selectedItems():
                item.setText("")
                self._grid_item_changed(item)
        else:
            super().keyPressEvent(event)
            
    def contextMenuEvent(self, event):
        if not getattr(self, '_can_edit', True): return
        menu = QMenu(self)
        a_bg = menu.addAction("Change Background Color")
        a_fg = menu.addAction("Change Text Color")
        a_clear = menu.addAction("Clear Colors")
        act = menu.exec(event.globalPos())
        if not act: return
        
        ranges = self.selectedRanges()
        if not ranges: return
        
        if act == a_bg:
            c = QColorDialog.getColor(Qt.GlobalColor.white, self, "Background Color")
            if c.isValid():
                for r in ranges:
                    for row in range(r.topRow(), r.bottomRow() + 1):
                        for col in range(r.leftColumn(), r.rightColumn() + 1):
                            it = self.item(row, col)
                            if not it:
                                it = QTableWidgetItem("")
                                self.setItem(row, col, it)
                            it.setBackground(QBrush(c))
                self.save_to_db()
        elif act == a_fg:
            c = QColorDialog.getColor(Qt.GlobalColor.black, self, "Text Color")
            if c.isValid():
                for r in ranges:
                    for row in range(r.topRow(), r.bottomRow() + 1):
                        for col in range(r.leftColumn(), r.rightColumn() + 1):
                            it = self.item(row, col)
                            if not it:
                                it = QTableWidgetItem("")
                                self.setItem(row, col, it)
                            it.setForeground(QBrush(c))
                self.save_to_db()
        elif act == a_clear:
            for r in ranges:
                for row in range(r.topRow(), r.bottomRow() + 1):
                    for col in range(r.leftColumn(), r.rightColumn() + 1):
                        it = self.item(row, col)
                        if it:
                            it.setBackground(QBrush(Qt.GlobalColor.transparent))
                            it.setForeground(QBrush(Qt.GlobalColor.black))
            self.save_to_db()

            
    def _grid_item_changed(self, item):
        if getattr(self, '_loading', False): return
        if not self._can_edit: return
        QTimer.singleShot(300, self.save_to_db)
        
    def save_to_db(self):
        if not self._db_name: return
        conn = self._db.get_connection(self._db_name)
        if not conn: return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM " + self.table_name)

            # row_idx = -1 : column names (skipped in excel_mode)
            if not self._excel_mode:
                for c in range(self.columnCount()):
                    h = self.horizontalHeaderItem(c)
                    name = h.text() if h else ""
                    if name:
                        cur.execute(
                            "INSERT INTO " + self.table_name +
                            " (row_idx, col_idx, cell_text, bg_color) VALUES (-1,?,?,'')",
                            (c, name))

            # row_idx = -2 : column widths
            for c in range(self.columnCount()):
                w = self.columnWidth(c)
                cur.execute(
                    "INSERT INTO " + self.table_name +
                    " (row_idx, col_idx, cell_text, bg_color) VALUES (-2,?,?,'')",
                    (c, str(w)))

            # row_idx >= 0 : cell data
            for r in range(self.rowCount()):
                for c in range(self.columnCount()):
                    it = self.item(r, c)
                    if it is None: continue
                    text = it.text()
                    bg = ""
                    if (it.background().style() != Qt.BrushStyle.NoBrush
                            and it.background().color().alpha() > 0):
                        h2 = it.background().color().name()
                        if h2 != '#000000': bg = h2
                    fg = ""
                    if (it.foreground().style() != Qt.BrushStyle.NoBrush
                            and it.foreground().color().alpha() > 0):
                        h2 = it.foreground().color().name()
                        if h2 != '#000000': fg = h2
                    packed_color = (bg + ";" + fg) if (bg or fg) else ""
                    if text or packed_color:
                        cur.execute(
                            "INSERT INTO " + self.table_name +
                            " (row_idx, col_idx, cell_text, bg_color) VALUES (?,?,?,?)",
                            (r, c, text, packed_color))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[ERROR] save_to_db(" + self.table_name + "):", e)
            
    def load_from_db(self):
        if not self._db_name: return
        self._loading = True
        all_rows = self._db.execute_query(
            self._db_name,
            "SELECT row_idx, col_idx, cell_text, bg_color FROM " + self.table_name
        ) or []
        self.blockSignals(True)
        self.clearContents()

        # Separate metadata rows from data rows
        col_names   = {}  # ci -> name  (row_idx = -1)
        col_widths  = {}  # ci -> width (row_idx = -2)
        data_rows   = []
        for r, c, txt, packed in all_rows:
            ri, ci = int(r), int(c)
            if ri == -1:
                col_names[ci]  = txt or ""
            elif ri == -2:
                try: col_widths[ci] = int(txt)
                except: pass
            elif ri >= 0:
                data_rows.append((ri, ci, txt, packed))

        # Apply column names from DB (skipped in excel_mode — always A,B,C...)
        if col_names and not self._excel_mode:
            for ci, name in col_names.items():
                while self.columnCount() <= ci:
                    self.insertColumn(self.columnCount())
                if name:
                    self.setHorizontalHeaderItem(ci, QTableWidgetItem(name))

        # Apply column widths from DB (fallback to default 110)
        for ci in range(self.columnCount()):
            w = col_widths.get(ci, 110)
            self.setColumnWidth(ci, w)

        # Reset row count so we don't have 50 empty rows artificially inflating the height
        self.setRowCount(0)

        # Load data rows
        for ri, ci, txt, packed in data_rows:
            while self.rowCount() <= ri:
                self.insertRow(self.rowCount())
            while self.columnCount() <= ci:
                self.insertColumn(self.columnCount())
            it = QTableWidgetItem(txt or "")
            if packed:
                parts = packed.split(';')
                bg = parts[0] if len(parts) > 0 else ""
                fg = parts[1] if len(parts) > 1 else ""
                if bg and bg != '#000000':
                    it.setBackground(QBrush(QColor(bg)))
                if fg and fg != '#000000':
                    it.setForeground(QBrush(QColor(fg)))
            self.setItem(ri, ci, it)

        # Always ensure at least 1 empty row at the bottom for new entries
        self.insertRow(self.rowCount())

        self.blockSignals(False)
        self._loading = False
        
    def _show_header_context_menu(self, pos):
        if not self._can_edit or self._excel_mode: return
        c = self.horizontalHeader().logicalIndexAt(pos)
        if c < 0: return
        
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid #ccc; padding: 4px; }")
        
        action_rename_col = menu.addAction("✏️ Rename Column Header")
        menu.addSeparator()
        action_insert_left = menu.addAction("Insert Column Left")
        action_insert_right = menu.addAction("Insert Column Right")
        menu.addSeparator()
        action_delete = menu.addAction("Delete Column")
        
        action = menu.exec(self.horizontalHeader().viewport().mapToGlobal(pos))
        if not action: return
        
        if action == action_rename_col:
            from PyQt6.QtWidgets import QInputDialog
            h = self.horizontalHeaderItem(c)
            curr = h.text() if h else ""
            new_name, ok = QInputDialog.getText(self, "Rename Column", "New header name:", text=curr)
            if ok:
                if not h:
                    h = QTableWidgetItem(new_name)
                    self.setHorizontalHeaderItem(c, h)
                else:
                    h.setText(new_name)
                self.save_to_db()
        elif action == action_insert_left:
            self.insertColumn(c)
            self.save_to_db()
        elif action == action_insert_right:
            self.insertColumn(c + 1)
            self.save_to_db()
        elif action == action_delete:
            self.removeColumn(c)
            self.save_to_db()

    def _show_grid_context_menu(self, pos):
        if not self._can_edit: return
        
        item = self.itemAt(pos)
        r = item.row() if item else self.currentRow()
        c = item.column() if item else self.currentColumn()
        if r < 0 or c < 0: return

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid #ccc; padding: 4px; }")
        
        action_bg = menu.addAction("Change Background Color")
        action_fg = menu.addAction("🔤 Change Text Color")
        menu.addSeparator()
        action_set_width = menu.addAction("↔️ Set Column Width")
        action_rename_col = menu.addAction("✏️ Rename Column Header")
        menu.addSeparator()
        action_insert_row_above = menu.addAction("Insert Row Above")
        action_insert_row_below = menu.addAction("Insert Row Below")
        menu.addSeparator()
        action_insert_col_left = menu.addAction("Insert Column Left")
        action_insert_col_right = menu.addAction("Insert Column Right")
        menu.addSeparator()
        action_delete_row = menu.addAction("Delete Row")
        action_delete_col = menu.addAction("Delete Column")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if not action: return

        if action == action_set_width:
            from PyQt6.QtWidgets import QInputDialog
            current_width = self.columnWidth(c)
            new_width, ok = QInputDialog.getInt(self, "Set Column Width", "Width:", current_width, 10, 2000)
            if ok:
                self.setColumnWidth(c, new_width)
                if self._db_name:
                    from PyQt6.QtCore import QSettings
                    settings = QSettings("JKCatalog", "GridWidths")
                    settings.setValue(f"{self._db_name}_{self.table_name}_col_{c}", new_width)
        elif action == action_rename_col:
            from PyQt6.QtWidgets import QInputDialog
            h = self.horizontalHeaderItem(c)
            curr = h.text() if h else ""
            new_name, ok = QInputDialog.getText(self, "Rename Column", "New header name:", text=curr)
            if ok:
                if not h:
                    h = QTableWidgetItem(new_name)
                    self.setHorizontalHeaderItem(c, h)
                else:
                    h.setText(new_name)
                self.save_to_db()
        elif action == action_bg:
            color = QColorDialog.getColor(Qt.GlobalColor.white, self, "Select Background Color")
            if color.isValid():
                for sel_item in self.selectedItems():
                    if sel_item is None:
                        sel_item = QTableWidgetItem("")
                        self.setItem(sel_item.row(), sel_item.column(), sel_item)
                    sel_item.setBackground(QBrush(color))
                self.save_to_db()
        elif action == action_fg:
            color = QColorDialog.getColor(Qt.GlobalColor.black, self, "Select Text Color")
            if color.isValid():
                for sel_item in self.selectedItems():
                    if sel_item is None:
                        sel_item = QTableWidgetItem("")
                        self.setItem(sel_item.row(), sel_item.column(), sel_item)
                    self.blockSignals(True)
                    sel_item.setForeground(QBrush(color))
                    self.blockSignals(False)
                self.save_to_db()
        elif action == action_insert_row_above:
            self.insertRow(r)
            self.save_to_db()
        elif action == action_insert_row_below:
            self.insertRow(r + 1)
            self.save_to_db()
        elif action == action_insert_col_left:
            self.insertColumn(c)
            self.save_to_db()
        elif action == action_insert_col_right:
            self.insertColumn(c + 1)
            self.save_to_db()
        elif action == action_delete_row:
            self.removeRow(r)
            self.save_to_db()
        elif action == action_delete_col:
            self.removeColumn(c)
            self.save_to_db()




# ===========================================================================
# SECTION WIDGET  -  a single named section in the Today Payment detailed view
# ===========================================================================
class SectionWidget(QWidget):
    """Colored header bar + user-managed QTableWidget (columns and rows)."""

    def __init__(self, section_id, name, color, db_manager, db_name, parent=None):
        super().__init__(parent)
        self.section_id = section_id
        self._db        = db_manager
        self._db_name   = db_name
        self._can_edit  = True
        self._saving    = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar
        self._hdr = QWidget()
        self._hdr.setStyleSheet(
            "background-color:" + color + "; border-radius:4px 4px 0 0;")
        hlay = QHBoxLayout(self._hdr)
        hlay.setContentsMargins(10, 5, 6, 5)
        hlay.setSpacing(4)

        self.title_lbl = QLabel(name)
        self.title_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(
            "color:white; border:none; background:transparent;")
        hlay.addWidget(self.title_lbl)
        hlay.addStretch()

        _bs = (
            "QPushButton{"
            "background:rgba(255,255,255,.18);color:white;"
            "border:1px solid rgba(255,255,255,.35);border-radius:3px;"
            "padding:0 7px;font-size:11px;}"
            "QPushButton:hover{background:rgba(255,255,255,.32);}"
        )
        self._btn_col  = QPushButton("+ Col")
        self._btn_col.setFixedHeight(22)
        self._btn_row  = QPushButton("+ Row")
        self._btn_row.setFixedHeight(22)
        self._btn_gear = QPushButton("\u2699")
        self._btn_gear.setFixedSize(26, 22)
        for b in (self._btn_col, self._btn_row, self._btn_gear):
            b.setStyleSheet(_bs)
            hlay.addWidget(b)
        self._btn_col.clicked.connect(self._add_column)
        self._btn_row.clicked.connect(self._add_row)
        self._btn_gear.clicked.connect(self._show_gear)
        outer.addWidget(self._hdr)

        # Table
        self.table = QTableWidget(0, 0)
        self.table.setFont(QFont("Arial", 10))
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.table.setMinimumHeight(50)
        self.table.setStyleSheet(
            "QTableWidget{border:1px solid #dee2e6;border-top:none;"
            "gridline-color:#e9ecef;background:white;}"
            "QHeaderView::section:horizontal{background:#f8f9fa;color:#343a40;"
            "padding:4px;border:none;border-bottom:2px solid #dee2e6;"
            "border-right:1px solid #e0e0e0;font-weight:bold;}"
        )

        self.table.horizontalHeader().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(
            self._hdr_ctx)
        self.table.horizontalHeader().sectionDoubleClicked.connect(
            self._rename_col)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: QTimer.singleShot(500, self._save_cols))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)
        self.table.itemChanged.connect(self._on_change)
        outer.addWidget(self.table)
        outer.addStretch()

        self._load()

    # ------------------------------------------------------------------ DB --
    def _load(self):
        if not self._db_name:
            return
        self.table.blockSignals(True)
        cols = self._db.execute_query(
            self._db_name,
            "SELECT col_index, col_name, col_width FROM tp_section_cols "
            "WHERE section_id=" + str(self.section_id) +
            " ORDER BY col_index") or []
        if cols:
            self.table.setColumnCount(len(cols))
            for idx, (ci, cname, cw) in enumerate(cols):
                self.table.setHorizontalHeaderItem(
                    idx, QTableWidgetItem(cname or ""))
                self.table.setColumnWidth(idx, cw or 120)

        data = self._db.execute_query(
            self._db_name,
            "SELECT row_idx, col_idx, cell_text, bg_color "
            "FROM tp_section_data WHERE section_id=" +
            str(self.section_id) +
            " ORDER BY row_idx, col_idx") or []
        if data:
            max_r = max(r[0] for r in data)
            self.table.setRowCount(max_r + 1)
            for ri, ci, txt, packed in data:
                it = QTableWidgetItem(txt or "")
                if packed:
                    parts = packed.split(';')
                    bg = parts[0] if len(parts) > 0 else ""
                    fg = parts[1] if len(parts) > 1 else ""
                    if bg and bg != '#000000':
                        it.setBackground(QBrush(QColor(bg)))
                    if fg and fg != '#000000':
                        it.setForeground(QBrush(QColor(fg)))
                self.table.setItem(ri, ci, it)
        self.table.blockSignals(False)
        self._recalc()

    def _save_data(self):
        if not self._db_name or self._saving:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        self._saving = True
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_data WHERE section_id=?",
                        (self.section_id,))
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    if not it:
                        continue
                    txt = it.text()
                    bg = fg = ""
                    if (it.background().style() != Qt.BrushStyle.NoBrush
                            and it.background().color().alpha() > 0):
                        h = it.background().color().name()
                        if h != '#000000':
                            bg = h
                    if (it.foreground().style() != Qt.BrushStyle.NoBrush
                            and it.foreground().color().alpha() > 0):
                        h = it.foreground().color().name()
                        if h != '#000000':
                            fg = h
                    packed = (bg + ";" + fg) if (bg or fg) else ""
                    if txt or packed:
                        cur.execute(
                            "INSERT INTO tp_section_data "
                            "(section_id, row_idx, col_idx, cell_text, bg_color)"
                            " VALUES(?,?,?,?,?)",
                            (self.section_id, r, c, txt, packed))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[ERROR] SectionWidget._save_data:", e)
        finally:
            self._saving = False

    def _save_cols(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_cols WHERE section_id=?",
                        (self.section_id,))
            for c in range(self.table.columnCount()):
                h = self.table.horizontalHeaderItem(c)
                cur.execute(
                    "INSERT INTO tp_section_cols"
                    "(section_id, col_index, col_name, col_width)"
                    " VALUES(?,?,?,?)",
                    (self.section_id, c,
                     h.text() if h else "", self.table.columnWidth(c)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[ERROR] SectionWidget._save_cols:", e)

    def _update_db(self, field, value):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("UPDATE tp_sections SET " + field + "=? WHERE id=?",
                        (value, self.section_id))
            conn.commit()
        except Exception as e:
            conn.rollback()

    def _delete_from_db(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_data WHERE section_id=?",
                        (self.section_id,))
            cur.execute("DELETE FROM tp_section_cols WHERE section_id=?",
                        (self.section_id,))
            cur.execute("DELETE FROM tp_sections WHERE id=?",
                        (self.section_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()

    # --------------------------------------------------------------- Actions --
    def _on_change(self, _item):
        QTimer.singleShot(300, self._save_data)

    def _add_column(self):
        if not self._can_edit:
            return
        c = self.table.columnCount()
        self.table.insertColumn(c)
        self.table.setHorizontalHeaderItem(c, QTableWidgetItem("Column " + str(c + 1)))
        self.table.setColumnWidth(c, 120)
        self._save_cols()
        self._recalc()

    def _add_row(self):
        if not self._can_edit:
            return
        if self.table.columnCount() == 0:
            QMessageBox.information(self, "No Columns",
                "Add at least one column first (+ Col).")
            return
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self._save_data()
        self._recalc()

    def _rename_col(self, col):
        if not self._can_edit:
            return
        h = self.table.horizontalHeaderItem(col)
        old = h.text() if h else ""
        new, ok = QInputDialog.getText(
            self, "Rename Column", "Column name:", text=old)
        if ok and new.strip():
            if not h:
                h = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(col, h)
            h.setText(new.strip())
            self._save_cols()

    def _hdr_ctx(self, pos):
        if not self._can_edit:
            return
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        menu = QMenu(self)
        a_ren = menu.addAction("Rename Column")
        a_del = menu.addAction("Delete Column")
        act = menu.exec(
            self.table.horizontalHeader().viewport().mapToGlobal(pos))
        if act == a_ren:
            self._rename_col(col)
        elif act == a_del:
            self.table.removeColumn(col)
            self._save_cols()
            self._save_data()
            self._recalc()

    def _row_ctx(self, pos):
        if not self._can_edit:
            return
        item = self.table.itemAt(pos)
        r = item.row() if item else self.table.currentRow()
        menu = QMenu(self)
        a_del = menu.addAction("Delete Row")
        menu.addSeparator()
        a_bg = menu.addAction("Change Cell Color")
        a_fg = menu.addAction("Change Text Color")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == a_del and r >= 0:
            self.table.removeRow(r)
            self._save_data()
            self._recalc()
        elif act in (a_bg, a_fg):
            default = Qt.GlobalColor.white if act == a_bg else Qt.GlobalColor.black
            title = "Background Color" if act == a_bg else "Text Color"
            color = QColorDialog.getColor(default, self, title)
            if color.isValid():
                for s in self.table.selectedItems():
                    if act == a_bg:
                        s.setBackground(QBrush(color))
                    else:
                        s.setForeground(QBrush(color))
                self._save_data()

    def _show_gear(self):
        menu = QMenu(self)
        a_ren = menu.addAction("Rename Section")
        a_col = menu.addAction("Change Header Color")
        menu.addSeparator()
        a_up  = menu.addAction("Move Left / Up")
        a_dn  = menu.addAction("Move Right / Down")
        menu.addSeparator()
        a_del = menu.addAction("Delete Section")
        act = menu.exec(
            self._btn_gear.mapToGlobal(self._btn_gear.rect().bottomLeft()))
        if act == a_ren:
            new, ok = QInputDialog.getText(
                self, "Rename Section", "Name:", text=self.title_lbl.text())
            if ok and new.strip():
                self.title_lbl.setText(new.strip())
                self._update_db("name", new.strip())
        elif act == a_col:
            c = QColorDialog.getColor(Qt.GlobalColor.blue, self, "Header Color")
            if c.isValid():
                self._hdr.setStyleSheet(
                    "background-color:" + c.name() +
                    "; border-radius:4px 4px 0 0;")
                self._update_db("header_color", c.name())
        elif act == a_up:
            self._move_section(-1)
        elif act == a_dn:
            self._move_section(+1)
        elif act == a_del:
            if QMessageBox.question(
                    self, "Delete Section",
                    "Delete '" + self.title_lbl.text() + "'?\nAll data will be lost.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self._delete_from_db()
                p = self.parent()
                for _ in range(12):
                    if isinstance(p, DynamicSectionView):
                        break
                    p = p.parent() if p else None
                if isinstance(p, DynamicSectionView):
                    self.deleteLater()
                    p._rebuild()

    def _move_section(self, direction):
        """Swap sort_order with the adjacent section (direction = -1 or +1)."""
        if not self._db_name:
            return
        # Get my current sort_order
        res = self._db.execute_query(
            self._db_name,
            "SELECT sort_order FROM tp_sections WHERE id=" + str(self.section_id))
        if not res:
            return
        my_order = res[0][0]
        target_order = my_order + direction

        # Find the section with target_order
        res2 = self._db.execute_query(
            self._db_name,
            "SELECT id FROM tp_sections WHERE sort_order=" + str(target_order))
        if not res2:
            return  # Already at the edge
        other_id = res2[0][0]

        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            # Swap the two sort_orders
            cur.execute(
                "UPDATE tp_sections SET sort_order=? WHERE id=?",
                (target_order, self.section_id))
            cur.execute(
                "UPDATE tp_sections SET sort_order=? WHERE id=?",
                (my_order, other_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return

        # Rebuild the parent DynamicSectionView
        p = self.parent()
        for _ in range(12):
            if isinstance(p, DynamicSectionView):
                break
            p = p.parent() if p else None
        if isinstance(p, DynamicSectionView):
            p._rebuild()

    def _recalc(self):
        cols = self.table.columnCount()
        hh = self.table.horizontalHeader().sizeHint().height() if cols else 0
        rh = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        
        # Calculate strict height to fit exactly the rows, capped at 500px (so it scrolls if too large)
        h = hh + rh + 6
        h = min(max(h, 50), 500)
        
        self.table.setMinimumHeight(h)
        self.table.setMaximumHeight(h)

    def set_edit_mode(self, can_edit):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        for b in (self._btn_col, self._btn_row, self._btn_gear):
            b.setEnabled(can_edit)


# ===========================================================================
# DYNAMIC SECTION VIEW  -  2-column grid of SectionWidgets
# ===========================================================================
class DynamicSectionView(QWidget):

    _DEFAULTS = [
        ("Payments",             "#1565C0"),
        ("Demand Loans (DL)",    "#2E7D32"),
        ("Purchase (Today)",     "#1565C0"),
        ("Account Table",        "#E65100"),
        ("Purchase (Upcoming)",  "#1565C0"),
        ("Limits & LC",          "#B71C1C"),
    ]

    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self._db       = db_manager
        self._db_name  = ""
        self._can_edit = True
        self._widgets  = []

        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(12, 12, 12, 12)
        vlay.setSpacing(16)

        self._grid_w = QWidget()
        self._grid_l = QGridLayout(self._grid_w)
        self._grid_l.setSpacing(16)
        self._grid_l.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(self._grid_w)

        self.btn_add = QPushButton("+ Add New Section")
        self.btn_add.setFixedHeight(34)
        self.btn_add.setStyleSheet(
            "QPushButton{background:#f1f3f5;color:#495057;"
            "border:2px dashed #adb5bd;border-radius:6px;"
            "font-weight:bold;font-size:12px;}"
            "QPushButton:hover{background:#e9ecef;border-color:#6c757d;}"
        )
        self.btn_add.clicked.connect(self._add_section)
        vlay.addWidget(self.btn_add)
        vlay.addStretch()

    def set_db_name(self, db_name):
        self._db_name = db_name
        self._rebuild()

    def _rebuild(self):
        for w in self._widgets:
            try:
                w.deleteLater()
            except RuntimeError:
                pass
        self._widgets.clear()
        while self._grid_l.count():
            item = self._grid_l.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        if not self._db_name:
            return
        rows = self._db.execute_query(
            self._db_name,
            "SELECT id, name, header_color FROM tp_sections "
            "ORDER BY sort_order, id") or []
        for idx, (sid, name, color) in enumerate(rows):
            sw = SectionWidget(
                sid, name or "Section", color or "#1565C0",
                self._db, self._db_name, parent=self._grid_w)
            sw.set_edit_mode(self._can_edit)
            self._widgets.append(sw)
            self._grid_l.addWidget(sw, idx // 2, idx % 2, Qt.AlignmentFlag.AlignTop)

    def _add_section(self):
        if not self._can_edit or not self._db_name:
            return
        name, ok = QInputDialog.getText(self, "Add Section", "Section name:")
        if not ok or not name.strip():
            return
        res = self._db.execute_query(
            self._db_name,
            "SELECT ISNULL(MAX(sort_order), 0) FROM tp_sections")
        max_ord = (res[0][0] if res else 0) + 1
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tp_sections(sort_order, name, header_color)"
                " VALUES(?,?,?)",
                (max_ord, name.strip(), "#1565C0"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return
        self._rebuild()

    def set_edit_mode(self, can_edit):
        self._can_edit = can_edit
        self.btn_add.setEnabled(can_edit)
        for w in self._widgets:
            w.set_edit_mode(can_edit)


# ===========================================================================
# TODAY PAYMENT TAB
# ===========================================================================
class TodayPaymentTab(QWidget):

    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._db       = get_db_manager()
        self._db_name  = ""

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top bar
        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background-color:#f1f3f5; border-bottom:1px solid #dee2e6;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(15, 8, 15, 8)
        title_lbl = QLabel("Today Payment")
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color:#343a40; border:none;")
        top_lay.addWidget(title_lbl)
        top_lay.addStretch()

        from PyQt6.QtWidgets import QComboBox, QStackedWidget
        self.view_selector = QComboBox()
        self.view_selector.addItems(
            ["Detailed Column View", "Classic Excel Grid View"])
        self.view_selector.setFont(QFont("Arial", 10))
        self.view_selector.setStyleSheet(
            "QComboBox{padding:4px 10px;border:1px solid #ced4da;"
            "border-radius:4px;background:white;}")
        self.view_selector.currentIndexChanged.connect(
            lambda i: self.stack.setCurrentIndex(i))
        top_lay.addWidget(self.view_selector)
        main_layout.addWidget(top_bar)

        # Stacked widget
        self.stack = QStackedWidget()

        # VIEW 0: Dynamic section view (2-col grid of user-managed sections)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:#fdfdfd;}")
        self.section_view = DynamicSectionView(self._db)
        scroll.setWidget(self.section_view)
        self.stack.addWidget(scroll)

        # VIEW 1: Freeform Excel grid (blank, user-defined)
        self.view2 = QWidget()
        v2 = QVBoxLayout(self.view2)
        v2.setContentsMargins(12, 12, 12, 12)
        self.grid = UniversalExcelGrid("tp_grid_data", cols=26, excel_mode=True)
        v2.addWidget(self.grid)
        self.stack.addWidget(self.view2)

        main_layout.addWidget(self.stack)

    def set_company_path(self, path):
        import os
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._db.ensure_database_exists(self._db_name, path)
        self._ensure_tables()
        self._seed_if_empty()
        self.section_view.set_db_name(self._db_name)
        self.grid.set_db_name(self._db_name)

    def _ensure_tables(self):
        for tname, ddl in [
            ("tp_sections",
             "CREATE TABLE tp_sections (id INT IDENTITY PRIMARY KEY, "
             "sort_order INT, name NVARCHAR(200), header_color NVARCHAR(20))"),
            ("tp_section_cols",
             "CREATE TABLE tp_section_cols (id INT IDENTITY PRIMARY KEY, "
             "section_id INT, col_index INT, col_name NVARCHAR(200), "
             "col_width INT)"),
            ("tp_section_data",
             "CREATE TABLE tp_section_data (section_id INT, row_idx INT, "
             "col_idx INT, cell_text NVARCHAR(MAX), bg_color NVARCHAR(40), "
             "PRIMARY KEY (section_id, row_idx, col_idx))"),
            ("tp_grid_data",
             "CREATE TABLE tp_grid_data (row_idx INT NOT NULL, "
             "col_idx INT NOT NULL, cell_text NVARCHAR(MAX), "
             "bg_color NVARCHAR(40), "
             "PRIMARY KEY (row_idx, col_idx))"),
        ]:
            self._db.ensure_table(self._db_name, tname, ddl)

    def _seed_if_empty(self):
        res = self._db.execute_query(
            self._db_name, "SELECT COUNT(*) FROM tp_sections")
        if (res[0][0] if res else 0) > 0:
            return
        defaults = [
            ("Payments",             "#1565C0"),
            ("Demand Loans (DL)",    "#2E7D32"),
            ("Purchase (Today)",     "#1565C0"),
            ("Account Table",        "#E65100"),
            ("Purchase (Upcoming)",  "#1565C0"),
            ("Limits & LC",          "#B71C1C"),
        ]
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            for i, (name, color) in enumerate(defaults):
                cur.execute(
                    "INSERT INTO tp_sections(sort_order, name, header_color)"
                    " VALUES(?,?,?)", (i, name, color))
            conn.commit()
        except Exception as e:
            conn.rollback()

    def apply_edit_mode(self, can_edit):
        self._can_edit = can_edit
        self.section_view.set_edit_mode(can_edit)
        self.grid.apply_edit_mode(can_edit)


class RecordTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._n_company = 1
        self._n_personal = 1
        self._headers = []
        self.header_filter = None
        self._update_headers()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Bar (Toggle Switch & Buttons) ---
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #f1f3f5; border-bottom: 1px solid #dee2e6;")
        tbar = QHBoxLayout(top_bar)
        tbar.setContentsMargins(15, 8, 15, 8)
        
        lbl = QLabel("Supplier Bank Account Records")
        lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #343a40; border: none;")
        tbar.addWidget(lbl)
        tbar.addStretch()
        
        self._add_row_btn = QPushButton("+ Add Supplier")
        self._add_row_btn.setFixedHeight(28)
        self._add_row_btn.clicked.connect(self._add_supplier)
        tbar.addWidget(self._add_row_btn)
        
        self._add_co_btn = QPushButton("+ Add Company Acc")
        self._add_co_btn.setFixedHeight(28)
        self._add_co_btn.clicked.connect(self._add_company_acct)
        tbar.addWidget(self._add_co_btn)

        self._add_pe_btn = QPushButton("+ Add Personal Acc")
        self._add_pe_btn.setFixedHeight(28)
        self._add_pe_btn.clicked.connect(self._add_personal_acct)
        tbar.addWidget(self._add_pe_btn)
        btn_style = """
            QPushButton {
                background-color: #1976D2; color: white;
                border: none; border-radius: 4px; padding: 0px 10px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1565C0; }
        """
        self._add_row_btn.setStyleSheet(btn_style)
        self._add_co_btn.setStyleSheet(btn_style)
        self._add_pe_btn.setStyleSheet(btn_style)
        self._add_row_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_co_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_pe_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        
        from PyQt6.QtWidgets import QComboBox, QStackedWidget
        self.view_selector = QComboBox()
        self.view_selector.addItems(["Classic Excel Grid View", "Detailed Column View"])
        self.view_selector.setFont(QFont("Arial", 10))
        self.view_selector.setStyleSheet("""
            QComboBox {
                padding: 4px 10px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
        """)
        self.view_selector.currentIndexChanged.connect(self._switch_view)
        tbar.addWidget(self.view_selector)
        
        main_layout.addWidget(top_bar)
        
        # --- Stacked Widget ---
        self.stack = QStackedWidget()
        
        # --- VIEW 0: Excel Grid View (Default) ---
        self.view0 = QWidget()
        v0_layout = QVBoxLayout(self.view0)
        v0_layout.setContentsMargins(8, 8, 8, 8)
        v0_layout.setSpacing(6)
        
        self.table = UniversalExcelGrid("record_grid_data", cols=self._total_cols(), excel_mode=True)
        self.table.horizontalHeader().setVisible(True)
        v0_layout.addWidget(self.table)
        self.stack.addWidget(self.view0)
        
        # --- VIEW 1: Detailed Column View ---
        self.view1 = QWidget()
        v1_layout = QVBoxLayout(self.view1)
        v1_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background-color: #fdfdfd; }")
        
        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.c_lay = QVBoxLayout(self.container)
        self.c_lay.setContentsMargins(12, 8, 12, 8)
        self.c_lay.setSpacing(10)
        
        self.scroll.setWidget(self.container)
        v1_layout.addWidget(self.scroll)
        
        # --- Hidden Detailed Data Grid ---
        self.detailed_table = UniversalExcelGrid("record_detailed_data", cols=self._total_cols())
        self.detailed_table.hide()
        v1_layout.addWidget(self.detailed_table)
        
        self.stack.addWidget(self.view1)
        
        main_layout.addWidget(self.stack)
        self.header_filter = HeaderEditFilter(self.detailed_table, "RecordTable")
        self.header_filter.apply_customs()

        self._setup_columns()
        self.table.load_from_db()
        self.detailed_table.load_from_db()
        self._build_detailed_view()

    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(self._db_name)
        self.detailed_table.set_db_name(self._db_name)
        self._build_detailed_view()

    def _update_headers(self):
        self._headers = ["SN", "A/C of"]
        for i in range(self._n_company):
            name = "Company Account" if self._n_company == 1 else f"Company Account {i+1}"
            self._headers.extend(["Field", name, ""])
        for i in range(self._n_personal):
            name = "Personal Account" if self._n_personal == 1 else f"Personal Account {i+1}"
            self._headers.extend(["Field", name, ""])
        # Update horizontalHeaderLabels if table exists and reapply custom names/colors
        if getattr(self, "detailed_table", None):
            self.detailed_table.setHorizontalHeaderLabels(self._headers)
            if self.header_filter:
                self.header_filter.apply_customs()

    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)
        
    def _build_detailed_view(self):
        # Clear existing items
        while self.c_lay.count():
            child = self.c_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        # Styling constants
        CARD_STYLE = """
            QFrame#SupplierCard {
                background-color: #ffffff;
                border: 1px solid #e0e4e8;
                border-radius: 12px;
            }
        """
        
        INPUT_STYLE = """
            QLineEdit {
                background-color: #f4f6f8;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: #2c3e50;
            }
            QLineEdit:focus {
                background-color: #ffffff;
                border: 1px solid #3498db;
            }
            QLineEdit:read-only {
                background-color: transparent;
                color: #7f8c8d;
            }
        """
        
        LABEL_STYLE = """
            QLabel {
                font-size: 12px;
                font-weight: 500;
                color: #7f8c8d;
            }
        """
        
        from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFormLayout, QWidget, QGraphicsDropShadowEffect
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QFont
        
        r = 0
        total_accts = self._n_company + self._n_personal
        
        while r < self.detailed_table.rowCount():
            # Skip gaps
            if self.detailed_table.rowSpan(r, 0) == 1 and not (self.detailed_table.item(r, 0) and self.detailed_table.item(r, 0).text()):
                r += 1
                continue
                
            sn = self.detailed_table.item(r, 0).text() if self.detailed_table.item(r, 0) else ""
            acof = self.detailed_table.item(r, 1).text() if self.detailed_table.item(r, 1) else ""
            
            # --- CARD ---
            card = QFrame()
            card.setObjectName("SupplierCard")
            card.setStyleSheet(CARD_STYLE)
            
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(15)
            shadow.setColor(QColor(0, 0, 0, 15))
            shadow.setOffset(0, 2)
            card.setGraphicsEffect(shadow)
            
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(20, 20, 20, 20)
            card_lay.setSpacing(15)
            
            # --- HEADER ROW (SN + NAME) ---
            header_row = QHBoxLayout()
            header_row.setSpacing(15)
            
            sn_label = QLabel(f"#{sn}" if sn else "#")
            sn_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #bdc3c7;")
            header_row.addWidget(sn_label)
            
            name_edit = QLineEdit(acof)
            name_edit.setPlaceholderText("Enter Supplier Name...")
            name_edit.setStyleSheet(INPUT_STYLE + "QLineEdit { font-size: 18px; font-weight: bold; background-color: transparent; padding: 0px; }")
            name_edit.setReadOnly(not self._can_edit)
            
            def on_name_changed(text, r_idx=r):
                self.detailed_table.blockSignals(True)
                it = self.detailed_table.item(r_idx, 1)
                if not it:
                    it = self.detailed_table.QTableWidgetItem(text)
                    self.detailed_table.setItem(r_idx, 1, it)
                else:
                    it.setText(text)
                self.detailed_table.blockSignals(False)
            
            def on_name_finished():
                if hasattr(self.detailed_table, 'save_to_db'):
                    self.detailed_table.save_to_db()
                    
            name_edit.textEdited.connect(on_name_changed)
            name_edit.editingFinished.connect(on_name_finished)
            
            header_row.addWidget(name_edit, 1)
            card_lay.addLayout(header_row)
            
            # --- ACCOUNTS GRID ---
            accts_row = QHBoxLayout()
            accts_row.setSpacing(30)
            
            # Helper to build a form block
            def build_account_form(a_idx, title_text, badge_color):
                has_data = any(
                    self.detailed_table.item(r + i, _rec_col(a_idx, 1)) and
                    self.detailed_table.item(r + i, _rec_col(a_idx, 1)).text().strip()
                    for i in range(6)
                )
                
                # If overall supplier has no data in ANY account, we show all forms so they can be filled out.
                supplier_has_data = any(
                    self.detailed_table.item(r + i, _rec_col(x, 1)) and self.detailed_table.item(r + i, _rec_col(x, 1)).text().strip()
                    for x in range(total_accts) for i in range(6)
                )
                
                if supplier_has_data and not has_data and not self._can_edit:
                    return None # Hide empty accounts in read mode if at least one account exists
                    
                form_widget = QWidget()
                form_lay = QVBoxLayout(form_widget)
                form_lay.setContentsMargins(0, 0, 0, 0)
                form_lay.setSpacing(10)
                
                # Title Badge
                title_lbl = QLabel(title_text)
                title_lbl.setStyleSheet(f"""
                    font-size: 12px; font-weight: bold; color: {badge_color};
                    background-color: {badge_color}1A; padding: 4px 8px; border-radius: 4px;
                """)
                form_lay.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignLeft)
                
                # Form Fields
                fields_container = QWidget()
                flay = QFormLayout(fields_container)
                flay.setContentsMargins(0, 5, 0, 0)
                flay.setHorizontalSpacing(15)
                flay.setVerticalSpacing(8)
                
                for i, key in enumerate(_REC_FIELD_KEYS):
                    val_item = self.detailed_table.item(r + i, _rec_col(a_idx, 1))
                    val_text = val_item.text() if val_item else ""
                    
                    lbl = QLabel(_REC_FIELD_LABELS[i])
                    lbl.setStyleSheet(LABEL_STYLE)
                    
                    edit = QLineEdit(val_text)
                    edit.setStyleSheet(INPUT_STYLE)
                    edit.setReadOnly(not self._can_edit)
                    
                    if key == "rakam":
                        edit.setStyleSheet(INPUT_STYLE + "QLineEdit { font-weight: bold; }")
                        
                    def on_val_edited(text, r_idx=r+i, c_idx=_rec_col(a_idx, 1)):
                        self.detailed_table.blockSignals(True)
                        it = self.detailed_table.item(r_idx, c_idx)
                        if not it:
                            from PyQt6.QtWidgets import QTableWidgetItem
                            it = QTableWidgetItem(text)
                            self.detailed_table.setItem(r_idx, c_idx, it)
                        else:
                            it.setText(text)
                        self.detailed_table.blockSignals(False)
                        
                    def on_val_finished():
                        if hasattr(self.detailed_table, 'save_to_db'):
                            self.detailed_table.save_to_db()
                            
                    edit.textEdited.connect(on_val_edited)
                    edit.editingFinished.connect(on_val_finished)
                    
                    flay.addRow(lbl, edit)
                    
                form_lay.addWidget(fields_container)
                return form_widget

            # Build Company Accounts
            for a in range(self._n_company):
                title = "Company Account" if self._n_company == 1 else f"Company Account {a+1}"
                form_w = build_account_form(a, title, "#2980b9") # Blue badge
                if form_w:
                    accts_row.addWidget(form_w)
                    
            # Build Personal Accounts
            for a in range(self._n_company, total_accts):
                title = "Personal Account" if self._n_personal == 1 else f"Personal Account {a - self._n_company + 1}"
                form_w = build_account_form(a, title, "#27ae60") # Green badge
                if form_w:
                    accts_row.addWidget(form_w)
                    
            accts_row.addStretch()
            card_lay.addLayout(accts_row)
            
            self.c_lay.addWidget(card)
            r += 6

        self.c_lay.addStretch()

    def _total_cols(self) -> int:
        return _REC_FIXED + (self._n_company + self._n_personal) * _REC_BLOCK

    def _setup_columns(self):
        self.detailed_table.setColumnCount(self._total_cols())
        self.detailed_table.setColumnWidth(0, 40)
        self.detailed_table.setColumnWidth(1, 200)
        total_accts = self._n_company + self._n_personal
        for a in range(total_accts):
            self.detailed_table.setColumnWidth(_rec_col(a, 0), _REC_LBL_W)
            self.detailed_table.setColumnWidth(_rec_col(a, 1), 250)
            if a < total_accts - 1:
                self.detailed_table.setColumnWidth(_rec_col(a, 2), _REC_SEP_W)
            else:
                self.detailed_table.setColumnWidth(_rec_col(a, 2), 0)

    def _load_data(self):
        for sn, acof, accts in _RECORD_DATA:
            self._insert_row(sn, acof, accts)

    def _insert_row(self, sn, acof, accts):
        r = self.detailed_table.rowCount()
        # insert 6 rows for fields
        for i in range(6):
            self.detailed_table.insertRow(r + i)
            self.detailed_table.setRowHeight(r + i, _REC_ROW_H)

        # Merge SN and A/C of across 6 rows
        self.detailed_table.setSpan(r, 0, 6, 1)
        self.detailed_table.setSpan(r, 1, 6, 1)
        
        # Set SN and A/C of text in the top-left cell of the span
        sn_item = QTableWidgetItem(str(sn))
        sn_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.detailed_table.setItem(r, 0, sn_item)
        
        acof_item = QTableWidgetItem(acof)
        acof_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detailed_table.setItem(r, 1, acof_item)

        # Fill in the data for each account
        total_accts = self._n_company + self._n_personal
        if isinstance(accts, dict):
            c_list = accts.get("company", [])
            p_list = accts.get("personal", [])
        else:
            c_list = [accts[0]] if len(accts) > 0 else []
            p_list = [accts[1]] if len(accts) > 1 else []
        
        for a in range(total_accts):
            if a < self._n_company:
                d = c_list[a] if a < len(c_list) else {}
            else:
                p_idx = a - self._n_company
                d = p_list[p_idx] if p_idx < len(p_list) else {}
            
            # Spacer column
            if a < total_accts - 1:
                self.detailed_table.setSpan(r, _rec_col(a, 2), 6, 1)
                spacer = QTableWidgetItem("")
                spacer.setFlags(Qt.ItemFlag.NoItemFlags)
                self.detailed_table.setItem(r, _rec_col(a, 2), spacer)

            for i, key in enumerate(_REC_FIELD_KEYS):
                # Label cell
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled) # Read only labels
                self.detailed_table.setItem(r + i, _rec_col(a, 0), lbl_item)

                # Value cell
                val = d.get(key, "")
                val_item = QTableWidgetItem(val)
                if key == "rakam" and val:
                    f = val_item.font()
                    f.setBold(True)
                    val_item.setFont(f)
                self.detailed_table.setItem(r + i, _rec_col(a, 1), val_item)

        # Insert Gap row
        gap_row = r + 6
        self.detailed_table.insertRow(gap_row)
        self.detailed_table.setRowHeight(gap_row, _REC_GAP_H)
        self.detailed_table.setSpan(gap_row, 0, 1, self._total_cols())
        gap_item = QTableWidgetItem("")
        gap_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.detailed_table.setItem(gap_row, 0, gap_item)

    def _add_supplier(self):
        if not self._can_edit: return
        self._insert_row("", "", {})
        self.detailed_table.scrollToBottom()
        self._build_detailed_view()

    def _add_company_acct(self):
        if not self._can_edit: return
        insert_idx = _REC_FIXED + self._n_company * _REC_BLOCK
        self._n_company += 1
        self._update_headers()

        # Insert 3 new columns (Label, Value, Spacer)
        for i in range(3):
            self.detailed_table.insertColumn(insert_idx + i)

        self._setup_columns()

        # Fill in field labels and empty values for every existing supplier row
        self.detailed_table.blockSignals(True)
        for r in range(0, self.detailed_table.rowCount(), 6):
            # Skip gap rows (rows without SN text and no row span)
            if self.detailed_table.rowSpan(r, 0) == 1 and not (self.detailed_table.item(r, 0) and self.detailed_table.item(r, 0).text()):
                continue
            for i, key in enumerate(_REC_FIELD_KEYS):
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.detailed_table.setItem(r + i, insert_idx, lbl_item)
                self.detailed_table.setItem(r + i, insert_idx + 1, QTableWidgetItem(""))
            # Spacer column spans all 6 rows
            self.detailed_table.setSpan(r, insert_idx + 2, 6, 1)
            spacer = QTableWidgetItem("")
            spacer.setFlags(Qt.ItemFlag.NoItemFlags)
            self.detailed_table.setItem(r, insert_idx + 2, spacer)
        self.detailed_table.blockSignals(False)

        if hasattr(self.detailed_table, 'save_to_db'):
            self.detailed_table.save_to_db()
        self._build_detailed_view()

    def _add_personal_acct(self):
        if not self._can_edit: return
        insert_idx = _REC_FIXED + (self._n_company + self._n_personal) * _REC_BLOCK
        self._n_personal += 1
        self._update_headers()

        # Insert 3 new columns (Label, Value, Spacer)
        for i in range(3):
            self.detailed_table.insertColumn(insert_idx + i)

        self._setup_columns()

        # Fill in field labels and empty values for every existing supplier row
        self.detailed_table.blockSignals(True)
        for r in range(0, self.detailed_table.rowCount(), 6):
            if self.detailed_table.rowSpan(r, 0) == 1 and not (self.detailed_table.item(r, 0) and self.detailed_table.item(r, 0).text()):
                continue
            for i, key in enumerate(_REC_FIELD_KEYS):
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.detailed_table.setItem(r + i, insert_idx, lbl_item)
                self.detailed_table.setItem(r + i, insert_idx + 1, QTableWidgetItem(""))
            # Spacer column spans all 6 rows
            self.detailed_table.setSpan(r, insert_idx + 2, 6, 1)
            spacer = QTableWidgetItem("")
            spacer.setFlags(Qt.ItemFlag.NoItemFlags)
            self.detailed_table.setItem(r, insert_idx + 2, spacer)
        self.detailed_table.blockSignals(False)

        if hasattr(self.detailed_table, 'save_to_db'):
            self.detailed_table.save_to_db()
        self._build_detailed_view()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self._add_row_btn.setEnabled(can_edit)
        self._add_co_btn.setEnabled(can_edit)
        self._add_pe_btn.setEnabled(can_edit)

    def _show_grid_context_menu(self, pos):
        if getattr(self, "_can_edit", True) == False: return
        if hasattr(self, "grid"):
            grid = self.grid
        elif hasattr(self, "table"):
            grid = self.table
        else:
            return
        menu = QMenu(self)
        action_insert_row_above = menu.addAction("Insert Row Above")
        action_insert_row_below = menu.addAction("Insert Row Below")
        menu.addSeparator()
        action_insert_col_left = menu.addAction("Insert Column Left")
        action_insert_col_right = menu.addAction("Insert Column Right")
        menu.addSeparator()
        action_delete_row = menu.addAction("Delete Row")
        action_delete_col = menu.addAction("Delete Column")
        item = grid.itemAt(pos)
        r = item.row() if item else grid.currentRow()
        c = item.column() if item else grid.currentColumn()
        if r < 0: r = 0
        if c < 0: c = 0
        action = menu.exec(grid.viewport().mapToGlobal(pos))
        if action == action_insert_row_above:
            grid.insertRow(r)
        elif action == action_insert_row_below:
            grid.insertRow(r + 1)
        elif action == action_insert_col_left:
            grid.insertColumn(c)
        elif action == action_insert_col_right:
            grid.insertColumn(c + 1)
        elif action == action_delete_row:
            grid.removeRow(r)
        elif action == action_delete_col:
            grid.removeColumn(c)


# ===========================================================================
# ANIL DAI HISAB TAB  -  running-balance ledger
# Balance = prev_balance + DR - Cr.
# ===========================================================================
_ANIL_COL_DR  = 4   # column index of DR
_ANIL_COL_CR  = 5   # column index of Cr.
_ANIL_COL_BAL = 6   # column index of Balance

# Actual data from the Excel sheet (rows 2-48, excluding header)
# (start_date, end_date, days, particular, dr, cr, balance)
_ANIL_DATA = [
]

_C  = Qt.AlignmentFlag.AlignCenter  | Qt.AlignmentFlag.AlignVCenter
_R  = Qt.AlignmentFlag.AlignRight   | Qt.AlignmentFlag.AlignVCenter
_L  = Qt.AlignmentFlag.AlignLeft    | Qt.AlignmentFlag.AlignVCenter

# col: (header, width, alignment)
_ANIL_COLS = [
    ("Start Date",  100, _C),
    ("End Date",    100, _C),
    ("Days",         50, _C),
    ("Particular",  190, _L),
    ("DR",          115, _R),
    ("Cr.",         115, _R),
    ("Balance",     130, _R),
    ("Remarks",     160, _L),
]


def _fmt(val):
    if val is None or val == "" or val == 0 or val == "0":
        return ""
    if isinstance(val, float):
        if val == int(val):
            return f"{int(val):,}"
        return f"{val:,.2f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def _anil_item(text, align):
    it = QTableWidgetItem("" if text is None else str(text))
    it.setTextAlignment(align)
    return it


class AnilHisabTab(QWidget):
    # Ledger: Balance auto-recalculates when DR or Cr. changes.
    # Balance[0] = DR[0]
    # Balance[n] = Balance[n-1] + DR[n] - Cr.[n]

    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._blocking = False   # prevents recursive cellChanged signals

        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(6)

        # Toolbar
        tbar = QHBoxLayout()
        tbar.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Anil Dai Hisab  —  Running Balance Ledger")
        lbl.setFont(_H_BOLD)
        tbar.addWidget(lbl)
        tbar.addStretch()

        self._add_btn = QPushButton("+ Add Row")
        self._add_btn.setObjectName("AnilAddRowBtn")
        self._add_btn.setFixedHeight(28)
        self._add_btn.clicked.connect(self._add_row)
        tbar.addWidget(self._add_btn)
        vlay.addLayout(tbar)

        # Formula hint


        # Table
        self.table = UniversalExcelGrid('anil_grid_data', cols=len(_ANIL_COLS))
        self.table.setObjectName("AnilHisabTable")
        self.table.setFont(_H_NORM)
        self.table.setHorizontalHeaderLabels([c[0] for c in _ANIL_COLS])
        for c, (_, w, _a) in enumerate(_ANIL_COLS):
            self.table.setColumnWidth(c, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        vlay.addWidget(self.table)

        # Status bar showing current outstanding balance (removed per user request)
        self._status = QLabel()
        self._status.hide()

        self._load_data()
        self.table.cellChanged.connect(self._on_cell_changed)

    # ------------------------------------------------------------------ #
    def _load_data(self):
        self._blocking = True
        for row_data in _ANIL_DATA:
            start, end, days, part, dr, cr, bal = row_data
            r = self.table.rowCount()
            self.table.insertRow(r)
            row_bg = None

            vals = [
                (start, _C),
                (end,   _C),
                (_fmt(days) if days is not None else "", _C),
                (part,  _L),
                (_fmt(dr),  _R),
                (_fmt(cr),  _R),
                (_fmt(bal), _R),
                ("",    _L),
            ]
            for c, (v, align) in enumerate(vals):
                it = _anil_item(v, align)
                if row_bg:
                    it.setBackground(QBrush(row_bg))
                self.table.setItem(r, c, it)

        self._blocking = False
        self._refresh_status()
        if hasattr(self.table, 'save_to_db'):
            self.table.save_to_db()

    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(self._db_name)

    def _add_row(self):

        if not self._can_edit:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, (_, _w, align) in enumerate(_ANIL_COLS):
            self.table.setItem(r, c, _anil_item("", align))
        self.table.scrollToBottom()
        self._recalc_from(r)

    # ------------------------------------------------------------------ #
    # Auto-recalculate balance for all rows from `start_row` downward
    # ------------------------------------------------------------------ #
    def _recalc_from(self, start_row: int):
        self._blocking = True
        rc = self.table.rowCount()
        for r in range(start_row, rc):
            # Get previous balance
            if r == 0:
                prev_bal = 0.0
            else:
                prev_item = self.table.item(r - 1, _ANIL_COL_BAL)
                prev_text = prev_item.text().replace(",", "") if prev_item else ""
                try:
                    prev_bal = float(prev_text)
                except ValueError:
                    prev_bal = 0.0

            dr_item = self.table.item(r, _ANIL_COL_DR)
            cr_item = self.table.item(r, _ANIL_COL_CR)
            dr_text = dr_item.text().replace(",", "") if dr_item else ""
            cr_text = cr_item.text().replace(",", "") if cr_item else ""

            try:
                dr_val = float(dr_text) if dr_text else 0.0
            except ValueError:
                dr_val = 0.0
            try:
                cr_val = float(cr_text) if cr_text else 0.0
            except ValueError:
                cr_val = 0.0

            # Special case: first data row, balance = DR (opening entry)
            if r == 0:
                new_bal = dr_val - cr_val
            else:
                new_bal = prev_bal + dr_val - cr_val

            bal_text = _fmt(new_bal) if (dr_text or cr_text) else ""
            bal_it = _anil_item(bal_text, _R)
            # Colour the balance: red if negative, green if positive
            if new_bal < 0:
                bal_it.setForeground(QBrush(QColor("#C0392B")))
            elif new_bal > 0:
                bal_it.setForeground(QBrush(QColor("#1A6B3C")))
            self.table.setItem(r, _ANIL_COL_BAL, bal_it)

        self._blocking = False
        self._refresh_status()
        if hasattr(self.table, 'save_to_db'):
            self.table.save_to_db()

    def _on_cell_changed(self, row: int, col: int):
        if self._blocking:
            return
        if col in (_ANIL_COL_DR, _ANIL_COL_CR):
            self._recalc_from(row)

    def _refresh_status(self):
        rc = self.table.rowCount()
        if rc == 0:
            self._status.setText("  Balance: —")
            return
        last = self.table.item(rc - 1, _ANIL_COL_BAL)
        txt = last.text() if last else ""
        # Walk up to find last non-empty balance
        for r in range(rc - 1, -1, -1):
            it = self.table.item(r, _ANIL_COL_BAL)
            if it and it.text().strip():
                txt = it.text()
                break
        self._status.setText(f"  Outstanding Balance:  Rs. {txt}")

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self._add_btn.setEnabled(can_edit)


# ===========================================================================
# Generic sheet for today payment
# ===========================================================================
_SHEET_CONFIGS = [
]


class PaymentSheet(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Bar (Toggle Switch) ---
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #f1f3f5; border-bottom: 1px solid #dee2e6;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(15, 8, 15, 8)
        
        title_lbl = QLabel(cfg.get("tab", "Sheet"))
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #343a40; border: none;")
        top_lay.addWidget(title_lbl)
        
        top_lay.addStretch()
        
        from PyQt6.QtWidgets import QComboBox, QStackedWidget
        self.view_selector = QComboBox()
        self.view_selector.addItems(["Detailed Column View", "Classic Excel Grid View"])
        self.view_selector.setFont(QFont("Arial", 10))
        self.view_selector.setStyleSheet("""
            QComboBox {
                padding: 4px 10px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
        """)
        self.view_selector.currentIndexChanged.connect(self._switch_view)
        top_lay.addWidget(self.view_selector)
        
        main_layout.addWidget(top_bar)
        
        # --- Stacked Widget ---
        self.stack = QStackedWidget()
        self._tables = []
        
        # --- VIEW 1: Column View ---
        self.view1 = QWidget()
        v1_layout = QVBoxLayout(self.view1)
        v1_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #fdfdfd; }")
        
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(12, 12, 12, 12)
        c_lay.setSpacing(25)
        
        cols = cfg.get("columns", [])
        headers = [c[0] for c in cols]
        widths = [c[1] for c in cols]
        sections = cfg.get("sections", {})
        
        if not sections:
            sections = {0: ("Data", "#1976D2", "#ffffff")}
            
        for row, (label, bg, fg) in sections.items():
            t = _StyledTable(label, headers, widths, header_color=bg)
            t.btn_add.clicked.connect(lambda _, tbl=t: self._add_row(tbl, len(headers)))
            self._tables.append(t)
            c_lay.addWidget(t)
            
        c_lay.addStretch()
        scroll.setWidget(container)
        v1_layout.addWidget(scroll)
        self.stack.addWidget(self.view1)
        
        # --- VIEW 2: Excel Grid View ---
        self.view2 = QWidget()
        v2_layout = QVBoxLayout(self.view2)
        v2_layout.setContentsMargins(12, 12, 12, 12)
        
        import hashlib
        tab_key = hashlib.md5(cfg.get("tab", "sheet").encode()).hexdigest()[:8]
        grid_table_name = f"sheet_{tab_key}_grid"
        self.grid = UniversalExcelGrid(grid_table_name, rows=cfg.get("rows", 50), cols=len(cols))
        self.grid.setObjectName("PaymentSheetTable")
        self._numeric = cfg.get("numeric_cols", set())
        self.grid.setFont(_H_NORM)
        self.grid.setHorizontalHeaderLabels(headers)
        for col, (_, w) in enumerate(cols):
            self.grid.setColumnWidth(col, w)
            
        self.grid.verticalHeader().setDefaultSectionSize(25)
        self.grid.horizontalHeader().setHighlightSections(False)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        
        self.grid.setStyleSheet("""
            QTableWidget {
                gridline-color: #dee2e6;
                alternate-background-color: #f8f9fa;
                border: 1px solid #ced4da;
            }
            QHeaderView::section:horizontal {
                background-color: #1A2035;
                color: #ffffff;
                padding: 4px;
                border: 1px solid #ced4da;
                font-weight: bold;
            }
        """)
        
        self._paint_sections(sections)
        v2_layout.addWidget(self.grid)
        self.stack.addWidget(self.view2)
        
        main_layout.addWidget(self.stack)
        
    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)

    def set_company_path(self, path: str):
        import os
        from src.logic.db_manager import build_logical_name
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        # If grid is a UniversalExcelGrid, hook it up to the DB
        if hasattr(self.grid, 'set_db_name'):
            self.grid.set_db_name(db_name)

    def _paint_sections(self, sections: dict):
        for row, (label, bg, fg) in sections.items():
            if row >= self.grid.rowCount():
                continue
            for col in range(self.grid.columnCount()):
                it = QTableWidgetItem(label if col == 0 else "")
                it.setFont(_H_BOLD)
                it.setBackground(QBrush(QColor(bg)))
                it.setForeground(QBrush(QColor(fg)))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.grid.setItem(row, col, it)
            self.grid.setRowHeight(row, 28)

    def setItem(self, row, col, item):
        if item and col in self._numeric:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.setItem(row, col, item)
        
    def setEditTriggers(self, trigs):
        self.grid.setEditTriggers(trigs)
        for t in self._tables:
            t.table.setEditTriggers(trigs)
            
    def _add_row(self, t_obj, num_cols):
        r = t_obj.table.rowCount()
        t_obj.table.insertRow(r)
        for c in range(num_cols):
            t_obj.table.setItem(r, c, QTableWidgetItem(""))
        t_obj.recalculate_height()


# ===========================================================================
# Main widget
# ===========================================================================
class SuppPaymentUI(QWidget):
    # Tally Internal -> Supp. Payment
    # Tabs mirror all 6 sheets of the supplier bank-account Excel workbook.

    def __init__(self):
        super().__init__()
        self.setObjectName("SuppPaymentMain")
        self._can_edit = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("PaymentTabContainer")
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)

        self.add_button = QPushButton("+")
        self.add_button.setObjectName("AddNewSheetBtn")
        self.add_button.setFixedSize(45, 32)
        self.add_button.clicked.connect(self.add_new_sheet)
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        # Record tab
        self._today_payment_tab = TodayPaymentTab()
        self.tabs.addTab(self._today_payment_tab, "Today Payment")
        
        self._record_tab = RecordTab()
        self.tabs.addTab(self._record_tab, "Record")

        # Generic sheets
        for cfg in _SHEET_CONFIGS:
            self.tabs.addTab(PaymentSheet(cfg), cfg["tab"])

        # Anil Dai Hisab  - running-balance ledger
        self._anil_tab = AnilHisabTab()
        self.tabs.addTab(self._anil_tab, "Anil Dai Hisab")

        # Specialised sheets
        self._team_tab  = TeamListTab()
        self._bonus_tab = BonusTab()
        self._ins_tab   = InsuranceTab()
        self.tabs.addTab(self._team_tab,  "Team-List")
        self.tabs.addTab(self._bonus_tab, "Bonus detail's")
        self.tabs.addTab(self._ins_tab,   "Insurance")

        self.tabs.setCurrentIndex(1)   # open on "today payment"
        layout.addWidget(self.tabs)

    # ------------------------------------------------------------------ #
    def set_company_path(self, path: str):
        """Propagate the active company path to all tabs."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, 'set_company_path'):
                w.set_company_path(path)

    def add_new_sheet(self):
        if not self._can_edit:
            return
        blank = {"rows": 50,
                 "columns": [(chr(65+i), 100) for i in range(10)],
                 "numeric_cols": set(), "sections": {}}
        self.tabs.addTab(PaymentSheet(blank),
                         f"Sheet {self.tabs.count()+1}")
        self.tabs.setCurrentIndex(self.tabs.count()-1)

    def rename_tab(self, index: int):
        if not self._can_edit or index == -1:
            return
        old = self.tabs.tabText(index)
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip():
            self.tabs.setTabText(index, new.strip())

    def show_tab_menu(self, point):
        idx = self.tabs.tabBar().tabAt(point)
        if idx == -1:
            return
        menu = QMenu(self)
        menu.setObjectName("TabContextMenu")
        ra = menu.addAction("Rename Sheet")
        da = menu.addAction("Delete Sheet")
        act = menu.exec(self.tabs.tabBar().mapToGlobal(point))
        if act == ra:
            self.rename_tab(idx)
        elif act == da:
            if self.tabs.count() > 1:
                if (QMessageBox.question(
                        self, "Delete",
                        f"Delete '{self.tabs.tabText(idx)}'?",
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No)
                        == QMessageBox.StandardButton.Yes):
                    self.tabs.removeTab(idx)
            else:
                QMessageBox.warning(
                    self, "Warning", "At least one sheet must remain!")

    # ------------------------------------------------------------------ #
    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        triggers = (
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, PaymentSheet):
                w.setEditTriggers(triggers)
            elif isinstance(w, (RecordTab, AnilHisabTab)):
                w.apply_edit_mode(can_edit)
            elif hasattr(w, "apply_edit_mode"):
                w.apply_edit_mode(can_edit)
        self.add_button.setEnabled(can_edit)
        self.add_button.setToolTip("" if can_edit else "Disabled — display only")
        self.tabs.setMovable(can_edit)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu if can_edit
            else Qt.ContextMenuPolicy.NoContextMenu)
