from PyQt6.QtWidgets import (
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
        if obj == self.header.viewport() and event.type() == QEvent.Type.MouseButtonDblClick:
            pos = event.position().toPoint()
            col = self.header.logicalIndexAt(pos)
            if col >= 0:
                self._start_editing(col)
                return True
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


class _InsTable(QWidget):
    # One insurance section: coloured header + editable table + Add-Row btn.

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self._can_edit = True
        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(0, 6, 0, 4)
        vlay.setSpacing(4)

        # Header + button row
        hlay = QHBoxLayout()
        hlay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setFont(_H_BOLD)
        lbl.setStyleSheet(
            f"background:{color}; color:#fff;"
            "padding:6px 12px; border-radius:4px;"
        )
        hlay.addWidget(lbl)
        hlay.addStretch()
        self._add_btn = QPushButton("+ Add Row")
        self._add_btn.setObjectName("InsAddRowBtn")
        self._add_btn.setFixedHeight(28)
        self._add_btn.clicked.connect(self._add_row)
        hlay.addWidget(self._add_btn)
        vlay.addLayout(hlay)

        # Table
        self.table = QTableWidget(0, len(_INS_COLS))
        self.table.setObjectName("InsuranceTable")
        self.table.setFont(_H_NORM)
        self.table.setHorizontalHeaderLabels(_INS_COLS)
        for c, w in enumerate(_INS_COL_W):
            self.table.setColumnWidth(c, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.table.setMinimumHeight(80)
        vlay.addWidget(self.table)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        vlay.addWidget(line)

    def load_rows(self, rows):
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, _num(val) if c == 3 else _item(val))
        self._fit_height()

    def _fit_height(self):
        h = self.table.horizontalHeader().height()
        for r in range(self.table.rowCount()):
            h += self.table.rowHeight(r)
        self.table.setFixedHeight(max(80, h + 4))

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.insertRow(self.table.rowCount())
        self.table.scrollToBottom()
        self._fit_height()

    def set_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self._add_btn.setEnabled(can_edit)


class InsuranceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._tables: list[_InsTable] = []
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Bar (Toggle Switch) ---
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #f1f3f5; border-bottom: 1px solid #dee2e6;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(15, 8, 15, 8)
        
        title_lbl = QLabel("Insurance Details")
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

        for title, color in _INS_SECTIONS:
            t = _InsTable(title, color)
            self._tables.append(t)
            vlay.addWidget(t)

        vlay.addStretch()
        scroll.setWidget(container)
        v1_layout.addWidget(scroll)
        self.stack.addWidget(self.view1)
        
        # --- VIEW 2: Excel Grid View ---
        self.view2 = QWidget()
        v2_layout = QVBoxLayout(self.view2)
        v2_layout.setContentsMargins(12, 12, 12, 12)
        
        self.grid = QTableWidget(50, len(_INS_COLS))
        self.grid.setObjectName("InsuranceGridTable")
        self.grid.setFont(_H_NORM)
        self.grid.setHorizontalHeaderLabels(_INS_COLS)
        for c, w in enumerate(_INS_COL_W):
            self.grid.setColumnWidth(c, w)
            
        self.grid.verticalHeader().setDefaultSectionSize(25)
        self.grid.horizontalHeader().setHighlightSections(False)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._show_grid_context_menu)
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
        
        # Paint colored sections
        for row, (label, bg) in enumerate(_INS_SECTIONS):
            r = row * 10 # Spread sections out by 10 rows
            for col in range(len(_INS_COLS)):
                it = QTableWidgetItem(label if col == 0 else "")
                it.setFont(_H_BOLD)
                it.setBackground(QBrush(QColor(bg)))
                it.setForeground(QBrush(QColor("#ffffff")))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.grid.setItem(r, col, it)
            self.grid.setRowHeight(r, 28)
            
        v2_layout.addWidget(self.grid)
        self.stack.addWidget(self.view2)
        
        main_layout.addWidget(self.stack)

    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        flags = (QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed) if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        for t in self._tables:
            t.set_edit_mode(can_edit)
        self.grid.setEditTriggers(flags)
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
    ("HO",  "MANAGER",       "Team--Neeraj Ji",              15000, "for holi"),
    ("HO",  "CRM",           "Team-Madhav Ghimire",          10000, "chocolate and colors"),
    ("HO",  "CRM",           "Team-Naresh Kushwaha",         10000, ""),
    ("HO",  "CRM",           "Team-Anjay Mishra",            10000, ""),
    ("HO",  "ADMIN",         "Team-Harsana",                 10000, ""),
    ("HO",  "Office Member", "Team-Roman Rajbanshi",          3000, ""),
    ("HO",  "Office Member", "Team-Surendra Paswan",          3000, ""),
    ("HO",  "Office Member", "Team-Manish Sharma",            3000, ""),
    ("HO",  "Office Member", "Team--Ashok Sahani",            3000, ""),
    ("HO",  "Office Member", "Team--Dinesh Chaurasiya",       1100, ""),
    ("HO",  "Office Member", "Team--Ram Chandra Guard",       3000, ""),
    ("HO",  "Office Member", "Team--Rabindra Yadav",          "",   ""),
    ("HO",  "Office Member", "Team--Raushan Kumar Yadav",     "",   ""),
    ("BTM", "BM",            "Team--Nikhil Singh",           10000, ""),
    ("BTM", "CRM",           "Team-Rajeev Kr.Chaurasiya",   10000, ""),
    ("BTM", "CRM",           "Team- Santosh Singh",          10000, ""),
    ("BTM", "Office Member", "Team- Ram Pujan Shah",           "",   ""),
    ("JNK", "CRM",           "Team--Shailendra Shrivastav", 10000, ""),
    ("JNK", "Office Member", "Team--Bijay Kumar Das",          "",   ""),
    ("NGT", "BM",            "Team--Vivek Singh",              "",   ""),
    ("NGT", "CRM",           "Team--Ashwini Gupta",            "",   ""),
    ("NGT", "CRM",           "Team--Pramendra Karn",           "",   ""),
    ("NGT", "Office Member", "Team--Basistha  Chaurasiya",     "",   ""),
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
        vlay.setSpacing(6)

        # Toolbar
        tbar = QHBoxLayout()
        tbar.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Bonus Details")
        lbl.setFont(_H_BOLD)
        tbar.addWidget(lbl)
        tbar.addStretch()
        self._add_row_btn = QPushButton("+ Add Row")
        self._add_row_btn.setObjectName("BonusAddRowBtn")
        self._add_row_btn.setFixedHeight(28)
        self._add_row_btn.clicked.connect(self._add_row)
        tbar.addWidget(self._add_row_btn)
        self._add_col_btn = QPushButton("+ Add Column")
        self._add_col_btn.setObjectName("BonusAddColBtn")
        self._add_col_btn.setFixedHeight(28)
        self._add_col_btn.clicked.connect(self._add_column)
        tbar.addWidget(self._add_col_btn)
        vlay.addLayout(tbar)

        # Table
        self.table = QTableWidget(0, len(_BONUS_BASE_COLS))
        self.table.setObjectName("BonusTable")
        self.table.setFont(_H_NORM)
        self.table.setHorizontalHeaderLabels(_BONUS_BASE_COLS)
        for c, w in enumerate(_BONUS_BASE_W):
            self.table.setColumnWidth(c, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        vlay.addWidget(self.table)

        self._load_data()

    def _load_data(self):
        for loc, post, name, bonus, note in _BONUS_DATA:
            r = self.table.rowCount()
            self.table.insertRow(r)
            bg = _BONUS_LOC_BG.get(loc)
            self.table.setItem(r, 0, _item(loc, bg=bg))
            self.table.setItem(r, 1, _item(post))
            self.table.setItem(r, 2, _item(name))
            self.table.setItem(r, 3, _num(bonus))
            # fill any extra cols
            for ec in range(len(_BONUS_BASE_COLS), self.table.columnCount()):
                self.table.setItem(r, ec, _item(""))

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.insertRow(self.table.rowCount())
        self.table.scrollToBottom()

    def _add_column(self):
        if not self._can_edit:
            return
        name, ok = QInputDialog.getText(self, "Add Column", "Column name:")
        if not ok or not name.strip():
            return
        col = self.table.columnCount()
        self.table.insertColumn(col)
        self.table.setHorizontalHeaderItem(col, QTableWidgetItem(name.strip()))
        self.table.setColumnWidth(col, 120)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self._add_row_btn.setEnabled(can_edit)
        self._add_col_btn.setEnabled(can_edit)


# ===========================================================================
# C) TEAM-LIST TAB  –  fixed left cols + year pairs (oldest -> newest ->)
# ===========================================================================
_YEAR_LABELS = []

# (location, post, name, {yr_label: (yr_month, salary)})
_TEAM_DATA = [
    ("HO",  "MANAGER",       "Team--Neeraj Ji",
     {"82-83":("2082-04",100000),"78-79":("2078-04",75000),"77-78":("2077-04",50000)}),
    ("HO",  "CRM",           "Team-Madhav Ghimire",
     {"79-80":("2079-11",40000)}),
    ("HO",  "CRM",           "Team-Naresh Kushwaha",
     {"80-81":("2080-04",40000),"78-79":("2078-04",30000),"77-78":("2077-08",25000)}),
    ("HO",  "ADMIN",         "Team-Harsana",
     {"82-83":("2082-04",40000),"78-79":("2078-01",30000),
      "76-77":("2076-05",10000),"75-76":("2075-11",7000)}),
    ("HO",  "Office Member", "Team--Srijana Giri",
     {"82-83":("2082-12",20000)}),
    ("HO",  "Office Member", "Team--Puja Sharma", {}),
    ("HO",  "Office Member", "Team-Roman Rajbanshi",
     {"82-83":("2082-04",24000),"81-82":("2081-02",20000),"78-79":("2078-12",15000)}),
    ("HO",  "Office Member", "Team-Surendra Paswan",
     {"82-83":("2082-04",19000),"80-81":("2081-01",17000),"79-80":("2079-04",15000)}),
    ("HO",  "Office Member", "Team-Manish Sharma",
     {"82-83":("2082-04",19000),"80-81":("2080-04",17000),"78-79":("2078-05",15000)}),
    ("HO",  "Office Member", "Team--Ashok Sahani",
     {"81-82":("2082-01",17000),"77-78":("2077-11",15000)}),
    ("HO",  "Office Member", "Team--Dinesh Chaurasiya",
     {"82-83":("2082-04",20000)}),
    ("HO",  "Office Member", "Team--Ram Chandra Guard",
     {"78-79":("2078-04",16000),"77-78":("2075-11",14000),"76-77":("2074-00",12000)}),
    ("HO",  "CRM",           "Team--Rabindra Yadav",
     {"82-83":("2082-08","25-30k")}),
    ("HO",  "Office Member", "Team--Raushan Kumar Yadav",
     {"82-83":("2082-07",30000)}),
    ("BTM", "BM",            "Team--Nikhil Singh",
     {"79-80":("2079-05",32000)}),
    ("BTM", "CRM",           "Team-Rajeev Kr.Chaurasiya",
     {"79-80":("2078-09",50000),"78-79":("2078-01",40000),"77-78":("2077-10",25000)}),
    ("BTM", "CRM",           "Team- Santosh Singh",
     {"81-82":("2081-12",30000),"80-81":("2080-09",24000),
      "78-79":("2078-04",20000),"77-78":("2077-10",15000)}),
    ("BTM", "Office Member", "Team- Ram Pujan Shah", {}),
    ("JNK", "CRM",           "Team--Shailendra Shrivastav",
     {"78-79":("2079-03",30000),"77-78":("2078-01",25000)}),
    ("JNK", "Office Member", "Team--Bijay Kumar Das",
     {"82-83":("2082-08",20000)}),
    ("NGT", "BM",            "Team--Vivek Singh",
     {"78-79":("2078-07",24000)}),
    ("NGT", "CRM",           "Team--Ashwini Gupta",
     {"81-82":("2081-04",30000),"80-81":("2081-02",25000)}),
    ("NGT", "CRM",           "Team--Pramendra Karn", {}),
    ("NGT", "Office Member", "Team--Basistha  Chaurasiya",
     {"82-83":("2082-07",20000)}),
    ("NGT", "Office Member", "Team--Manish Barnwal",
     {"82-83":("2082-06",20000)}),
]

_TEAM_LOC_BG = {"HO":"#E3F2FD","BTM":"#FFF9C4","JNK":"#F3E5F5","NGT":"#E8F5E9"}
_FIXED_COLS  = [("Location",70),("Post",110),("Name",200)]
_FIXED_N     = len(_FIXED_COLS)


class TeamListTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit   = True
        # Reversed order for newest on left
        self._year_labels = ["82-83","81-82","80-81","79-80","78-79","77-78","76-77","75-76"]

        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(6)

        # Toolbar
        tbar = QHBoxLayout()
        tbar.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Team Salary History  (◀ newest → oldest)")
        lbl.setFont(_H_BOLD)
        tbar.addWidget(lbl)
        tbar.addStretch()
        self._add_row_btn = QPushButton("+ Add Employee")
        self._add_row_btn.setObjectName("TeamAddRowBtn")
        self._add_row_btn.setFixedHeight(28)
        self._add_row_btn.clicked.connect(self._add_employee_row)
        tbar.addWidget(self._add_row_btn)
        self._add_yr_btn = QPushButton("+ Add Year")
        self._add_yr_btn.setObjectName("TeamAddYearBtn")
        self._add_yr_btn.setFixedHeight(28)
        self._add_yr_btn.clicked.connect(self._add_year)
        tbar.addWidget(self._add_yr_btn)
        vlay.addLayout(tbar)

        # Hint label
        hint = QLabel(
            "  Each year block: Joining Month  |  Salary  "
            "— newest years on the left"
        )
        hint.setStyleSheet("color:#666; font-size:11px;")
        vlay.addWidget(hint)

        # Table
        self.table = QTableWidget(0, _FIXED_N + len(self._year_labels) * 3)
        self.table.setObjectName("TeamListTable")
        self.table.setFont(_H_NORM)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.horizontalHeader().setHighlightSections(False)
        vlay.addWidget(self.table)

        self._rebuild_headers()
        self._load_data()

    def _col_for_year(self, yr: str) -> int:
        return _FIXED_N + self._year_labels.index(yr) * 3 + 1

    def _rebuild_headers(self):
        total = _FIXED_N + len(self._year_labels) * 3
        self.table.setColumnCount(total)
        labels = [n for n, _ in _FIXED_COLS]
        for yr in self._year_labels:
            labels += ["", yr, "Salary"]
        self.table.setHorizontalHeaderLabels(labels)
        for c, (_, w) in enumerate(_FIXED_COLS):
            self.table.setColumnWidth(c, w)
        for i in range(len(self._year_labels)):
            base = _FIXED_N + i * 3
            self.table.setColumnWidth(base,     30)
            self.table.setColumnWidth(base + 1, 80)
            self.table.setColumnWidth(base + 2, 85)

    def _load_data(self):
        self.table.setRowCount(0)
        for loc, post, name, yr_data in _TEAM_DATA:
            r = self.table.rowCount()
            self.table.insertRow(r)
            bg = _TEAM_LOC_BG.get(loc)
            self.table.setItem(r, 0, _item(loc, bg=bg))
            self.table.setItem(r, 1, _item(post))
            self.table.setItem(r, 2, _item(name, bold=True))
            
            for i in range(len(self._year_labels)):
                base = _FIXED_N + i * 3
                spacer = QTableWidgetItem("")
                spacer.setFlags(Qt.ItemFlag.NoItemFlags)
                spacer.setBackground(QBrush(QColor("#f8f9fa")))
                self.table.setItem(r, base, spacer)
                
            for yr, (yr_month, salary) in yr_data.items():
                if yr in self._year_labels:
                    bc = self._col_for_year(yr)
                    self.table.setItem(r, bc,     _item(yr_month))
                    self.table.setItem(r, bc + 1, _num(salary))

    def _add_employee_row(self):
        if not self._can_edit:
            return
        self.table.insertRow(self.table.rowCount())
        self.table.scrollToBottom()

    def _add_year(self):
        if not self._can_edit:
            return
        yr, ok = QInputDialog.getText(
            self, "Add Year",
            "Nepali fiscal year (e.g. 83-84):"
        )
        if not ok or not yr.strip():
            return
        yr = yr.strip()
        if yr in self._year_labels:
            QMessageBox.information(self, "Exists", f"Year {yr} already exists.")
            return
        
        self._year_labels.insert(0, yr)
        self._rebuild_headers()
        self._load_data()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        self._add_row_btn.setEnabled(can_edit)
        self._add_yr_btn.setEnabled(can_edit)


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
    (1,"Vishal nat bolt",[
        {"naam":"\u0935\u093f\u0936\u093e\u0932 \u0928\u091f \u092c\u094b\u0932\u094d\u091f\u0941 \u0909\u0927\u094b\u0917","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"006001-05200842","rakam":"chq rs-65250.72","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Vishal Hardware","baik":"Everest Bank","khata":"00600-1052-00223","rakam":"chq rs- 57194.68","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {}]),
    (2,"Salasar HW, ktm",[
        {"naam":"Shri Salasar Hardware Traders","thegana":"\u0924\u094d\u0930\u093f\u092a\u0941\u0930\u0947\u0936\u094d\u0935\u0930","baik":"Siddath bank","khata":"0061-509-5161","rakam":"chq rs-100000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Khadak singh bista","thegana":"new baneshwor","baik":"nepal sbi","khata":"2031 5241 4093 60NPR","rakam":"cash rs- 194200","jamma":"personal name"},
        {}]),
    (3,"Rani sati, brj",[
        {"naam":"\u0930\u094b\u092f\u0932 \u091f\u094d\u0930\u0947\u0921 \u0932\u093f\u0915","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-1052-00537 CA","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"\u0930\u0941\u092c\u093f \u0930\u0941\u0917\u091f\u093e","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"Nepal investment bank ltd","khata":"003-0508-0263191","jamma":"jitendra"},
        {"naam":"Global Metal Industries","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"Global Bank","khata":"0110-10100-06000","rakam":"chq rs- 366938.84","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (4,"kk impex, brj",[
        {"naam":"K.K. \u0908\u092e\u094d\u092a\u0947\u0915\u094d\u0938 \u092a\u094d\u0930\u093e. \u0932\u0940.","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-10520-1088","rakam":"chq rs-7082.62","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"\u0928\u094d\u092f\u0941 \u092a\u0936\u0941\u092a\u0924\u093f \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930","thegana":"\u092c\u093f\u0930\u0902\u0917\u0928\u094d\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-1050-00379","rakam":"chq rs- 11249.88","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {}]),
    (5,"Universal trading, ktm",[
        {"naam":"\u092f\u0941\u0928\u093f\u0935\u0930\u094d\u0938\u0932 \u091f\u094d\u0930\u0947\u0921\u093f\u0917\u093c \u0938\u0947\u0928\u094d\u091f\u0930 \u092a\u094d\u0930\u093e. \u0932\u0940.","thegana":"\u0915\u093e\u0920\u092e\u093e\u0928\u094d\u0921\u0941","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"01000-1052-00942","rakam":"chq rs- 92500","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"\u092f\u0941\u0928\u093f\u0935\u0930\u094d\u0938\u0932 \u091f\u094d\u0930\u0947\u0921\u093f\u0917\u093c \u0938\u0947\u0928\u094d\u091f\u0930 \u092a\u094d\u0930\u093e. \u0932\u0940.","thegana":"Tripureshwor","baik":"NMB BANK","khata":"0820-0698-2880-0016","rakam":"chq rs- 170000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {}]),
    (10,"Manokamna ,brj",[
        {"naam":"Manokamna overseas","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u0917\u094d\u0932\u094b\u092c\u0932 \u092c\u0948\u0915","khata":"110-1010-005203","rakam":"cash rs-300000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Pawan kumar Agrawal","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u0917\u094d\u0932\u094b\u092c\u0932 \u092c\u0948\u0915","khata":"110-70100-14846","jamma":"JITENDRA"},
        {"naam":"Manokamna overseas","thegana":"\u092c\u093f\u0930\u0917\u091c","baik":"\u0917\u094d\u0932\u094b\u092c\u0932 \u092c\u0948\u0915","khata":"0110-10100-65362","rakam":"chq rs-78715.9","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (11,"Kailashpati International, Brj",[
        {"naam":"Kailashpati international","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Macchapucchure bank Ltd","khata":"1870-990-5036-00015","rakam":"cash rs-96850","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (12,"Balaji metal, Hetoda",[
        {"naam":"Balaji Metal Industries","thegana":"Hetoda","baik":"mega bank","khata":"01000-1013-9993","rakam":"chq rs-120000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Om prakash Bajaj","thegana":"teku","baik":"Everest","khata":"0100-0501-0011-41","rakam":"cash rs- 215118","jamma":"jitendra"},
        {}]),
    (17,"\u0917\u0928\u0947\u0936 \u091f\u094d\u0930\u0947\u0921\u093f\u0917 \u0938\u0947\u0928\u094d\u091f\u0930",[
        {"naam":"\u0917\u0928\u0947\u0936 \u091f\u094d\u0930\u0947\u0921\u093f\u0917 \u0938\u0947\u0928\u094d\u091f\u0930","thegana":"\u0935\u093f\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-105200-347","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Atlantic Overseas","thegana":"\u0935\u093f\u0930\u0917\u091c","baik":"GLOBAL","khata":"110-101-000-6050","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {}]),
    (18,"Bikash ji ,brj",[
        {"naam":"Tulip Polymer Industries","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Nabil Bank Ltd.","khata":"050-101-7500-991","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Kushagra International","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"0060-0105-2014-95","rakam":"chq rs-192106.78","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Win Win Hardware Products","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Siddharth bank Ltd.","khata":"002-165-79101","rakam":"chq Rs. 12000.60","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (19,"ASIA TOOLS",[
        {"naam":"Asia Tools House","thegana":"ktm","baik":"Prabhu Bank","khata":"1140-106-1196-00011","rakam":"chq rs-50000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Mahadev Tiwari","thegana":"ktm","baik":"Prabhu Bank","khata":"1140-13880-8100-012","rakam":"cash rs- 63000","jamma":"jitendra"},
        {}]),
    (20,"Priya Impex",[
        {"naam":"Priya Impex","thegana":"Druber Marg Branch","baik":"Nepal Investment Bank","khata":"00159-020-250-610","rakam":"chq rs-105000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Mukesh kumar singhal","thegana":"Tripureshwor branch","baik":"Global ime bank","khata":"34070-1000-2550","jamma":"jitendra agrawal"},
        {"naam":"Aarna international pvt ltd","thegana":"Ktm","baik":"NIMB Bank","khata":"0010-10103-10505","rakam":"chq rs-150000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (22,"Binayak Enterprises",[
        {"naam":"Binayak Overseas Trade Pvt.Ltd","thegana":"ktm","baik":"Kumari Bank","khata":"0050-3018-7610-0001","rakam":"chq rs-184171.92","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"GANESH DATTA JOSHI","thegana":"TRIPURESHWOR","baik":"LUMBINI BIKAS BANK LTD.","khata":"0311-1020-3647-6400-0001","rakam":"RS-80000","jamma":"jitendra agrawal"},
        {}]),
    (23,"Start International",[
        {"naam":"Star International","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-105201511","rakam":"chq rs-141216/-","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (24,"shruti enterprises",[
        {"naam":"shruti enterprises","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"0060-0105-200689","rakam":"chq rs- 220000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, BRT"},
        {"naam":"Vinay bansal","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"600-501-211-258","rakam":"cash rs- 100000","jamma":"jitendra agrawal"},
        {}]),
    (25,"shree om ji trade international",[
        {"naam":"\u0936\u094d\u0930\u0940 \u0913\u092e \u091c\u0940 \u091f\u094d\u0930\u0947\u0921 \u0908\u0928\u094d\u091f\u0930\u0928\u0947\u0936\u0928\u0932","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Nepal investment bank","khata":"003590-2025-0283","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"sangita kumari agrawal","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"laxmi bank","khata":"0011-9000-146","jamma":"jitnedra"},
        {}]),
    (26,"Lotus Plastic Udhyog",[
        {"naam":"Lotus Plastic udhyog","thegana":"Kalimati","baik":"Nepal Investment bank","khata":"01759-01025-0221","rakam":"CHQ RS- 183791.86","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"tamanna traders","thegana":"Kalimati","baik":"Nepal Investment bank","khata":"01759-01025-0306","rakam":"chq rs- 665000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Lotus Plastic udhyog","thegana":"Kalimati","baik":"Everest Bank","khata":"0370-0105-2000-63","rakam":"CHQ RS- 183791.86","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (27,"Kelash hw, brj",[
        {"naam":"Nirika Traders","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Nepal Investment bank","khata":"0030-10500-03615","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"nitesh kumar Agrawal","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Nepal Investment bank","khata":"0030-509000-2652","jamma":"jitendra"},
        {}]),
    (28,"New Famous Tar Jali, Brj",[
        {"naam":"New Famous Tar Jali Udhyog","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Nepal invesment bank.","khata":"0030-1050-0029-98","rakam":"chq rs-135000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Ram Asis Prasad Kurmi","baik":"Kumari Bank","khata":"00300-7575-4200-001","rakam":"cash rs-90700.64","jamma":"jitendra"},
        {}]),
    (29,"icon, ktm",[
        {"naam":"ICON Traders","thegana":"Teku Branch","baik":"Prabhu Bank Limited","khata":"1140-1137-9940-0011","rakam":"chq rs-102908.73","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Prashant Mahesheka","thegana":"Bhat Bateni Branch, Kathmandu","baik":"Laxmi Sunrise Bank Ltd","khata":"0142-4005-337","rakam":"cash rs-100000","jamma":"personal name"},
        {}]),
    (30,"omex, brj",[
        {"naam":"New Omax international","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"NMB BANK","khata":"019-01168-3570-0016","rakam":"chq rs-140000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"OMAX MANUFACTURING","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"NMB BANK","khata":"019-0146-4318-0000-27","rakam":"chq rs- 50000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {}]),
    (32,"Arvind bandhu",[
        {"naam":"Arvind Bandhu","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"Everest Bank","khata":"0060-0105-2002-84","rakam":"chq rs- 96182.77","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Nirmal Kumar agrawal","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"NMB bank","khata":"01900-5268-1300-011","rakam":"cash rs- 131150","jamma":"jitendra"},
        {}]),
    (33,"Satyam Techno",[
        {"naam":"Satyam Techno Packs Pvt. Ltd.","thegana":"Halchowk Branch","baik":"Nabil Bank LTD.","khata":"320 101 7500 654","rakam":"chq rs- 92449.82","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Rajesh Paudel","thegana":"Halchowk Branch","baik":"Nabil bank ltd.","khata":"032 0101 7500 806","rakam":"cash rs- 15500","jamma":"jitendra"},
        {}]),
    (34,"Jagdamba Metal, Brj",[
        {"naam":"Jagdamba Metal Udhyog","thegana":"\u092c\u0940\u0930\u0917\u091c","baik":"\u090f\u092d\u0930\u0947\u0937\u094d\u091f \u092c\u0948\u0915 \u0932\u093f\u092e\u093f\u091f\u0947\u0921\u093c","khata":"00600-1052-01353","rakam":"chq rs- 233765.92","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (35,"Shiv Enterprises, Brj",[
        {"naam":"Shiv Enterprises","thegana":"Birgunj","baik":"Machhapuchhre bank ltd","khata":"0040 0235 5550  0017","rakam":"chq rs- 275000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Jay Ma Vaishno Enterprises","thegana":"Birgunj","baik":"Machhapuchhre bank ltd","khata":"0040 0533 8430 0011","rakam":"chq rs-115938","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Rajendra Sharma","thegana":"Birgunj","baik":"Machhapuchhre bank ltd","khata":"0040-0004-2980-0011","rakam":"Rs-","jamma":"Jitendra"}]),
    (36,"Rani sati, Brj",[
        {"naam":"Royal Hardware pvt ltd","thegana":"Birgunj","baik":"global bank","khata":"1101 0100 63407","rakam":"chq rs- 67636.63","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Krishna Gopal Keyal","baik":"Siddhartha Bank","khata":"0021-5129-121","rakam":"cash rs-49615","jamma":"Jitendra"},
        {}]),
    (37,"Pashupati plastic Ind, Ktm",[
        {"naam":"Pashupati Plastic Industries","baik":"Prabhu Bank","khata":"1880 1524 8870 0013","rakam":"chq rs- 57600","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (38,"Sri Maruti Mangal, hattiguda",[
        {"naam":"Shree Maruti Mangal","thegana":"Hattigauda","baik":"Prabhu Bank","khata":"1000 1346 7050 0016","rakam":"chq rs- 180000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Touchstone Multipurpose Co-operative ltd","thegana":"New road","baik":"Global Ime Bank","khata":"3020 1010 0021 50","rakam":"cash rs-71180","jamma":"personal name"},
        {}]),
    (40,"Bimal Spark House Pvt. Ltd.,Lalitpur",[
        {"naam":"Bimal Spark House Pvt. Ltd.","thegana":"Lalitpur","baik":"Nabil Bank","khata":"2380 1017 5002 49","rakam":"chq rs- 800000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Future Exim Pvt.Ltd","thegana":"Dhobighat","baik":"Global Bank","khata":"1050-1010-0027-69","rakam":"chq rs- 500000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Future Exim Pvt.Ltd","thegana":"Dhobighat","baik":"Sanima Bank","khata":"9030-1001-0000-134","rakam":"chq rs- 400000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"}]),
    (41,"R R Hardware Center, Brj",[
        {"naam":"R R Hardware Center, Brj","baik":"Machhapuchchhre bank limited","khata":"0040 0002 0350 0042","rakam":"chq rs- 45007.9","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (42,"Crystal Trade Link",[
        {"naam":"Crystal Trade Link","baik":"Prabhu Bank Limited","khata":"0320-1529-2630-0016","rakam":"chq rs-40755","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Crystal Trade Link","baik":"Everest Bank Limited","khata":"0100-0105-2013-84","rakam":"chq rs-","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Pradip Agrawal","baik":"Everest Bank Limited","khata":"0020-0501-0062-40","rakam":"cash rs-54000","jamma":"personal name"}]),
    (43,"Gahawamai Enterprises,Brj",[
        {"naam":"Gahawamai Enterprises,Brj","baik":"Machhapuchhre","khata":"0040-0533-6560-0017","rakam":"chq rs-255390","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (44,"R R Hardware Center, Brj (2)",[
        {"naam":"R.R Hardware Center","thegana":"Birgunj","baik":"Machhapuchhre","khata":"0040-0002-0350-0042","rakam":"chq rs-76496.48","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (45,"Tara Paint & Chemical Industries",[
        {"naam":"TARA PAINTS & CHEMICAL INDUSTRIES PVT LTD","thegana":"Birgunj","baik":"Kumari","khata":"0030-2488-9300-0021","rakam":"chq rs-100000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (46,"Himal Wire Netting Industrirs",[
        {"naam":"Himal Wire Netting Industrirs","thegana":"Birgunj","baik":"Machhapuchhre","khata":"0040-9905-5340-0025","rakam":"chq rs-114319.25","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (47,"Global Marketing, Brj",[
        {"naam":"Global Marketing","thegana":"Birgunj","baik":"Everest Bank Ltd","khata":"0060-0105-2010-70","rakam":"chq rs-43758.6","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {"naam":"Bharat Bhushan Sarraf","thegana":"Birgunj","baik":"Everest Bank Ltd","khata":"0060-0501-2013-95","rakam":"cash rs- 49741.4","jamma":"personal name"},
        {}]),
    (48,"Rituraaj Impex",[
        {"naam":"Rituraaj Impex","thegana":"Birgunj","baik":"prabhu bank","khata":"1880-1534-6760-0010","rakam":"chq no-33840","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (49,"LAXMI BANK",[
        {"naam":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt","thegana":"Brt","baik":"Laxmi Bank","khata":"0061-1036-434","rakam":"chq no-10,85,000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
    (50,"Salasar Tools and Hardware",[
        {"naam":"SALASAR TOOLS AND HARDWARE","thegana":"Teku","baik":"Laxmi Bank","khata":"1661-6948-0201-1079","rakam":"chq no-145000","jamma":"\u091c\u0947.\u0915\u0947. \u0939\u093e\u0930\u094d\u0921\u0935\u0947\u092f\u0930 \u0026 \u0915\u092e\u094d\u092a\u0928\u0940, Brt"},
        {},{}]),
]

def _rec_col(acct: int, part: int) -> int:
    # part: 0=Label, 1=Value, 2=Spacer
    return _REC_FIXED + acct * _REC_BLOCK + part

# ===========================================================================
# TODAY PAYMENT TAB
# ===========================================================================
class TodayPaymentTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._tables = []
        # Registry: (row, col) → {"key": str, "cols": (c_start, c_end), "row": int}
        # Used to detect header cells and apply customizations
        self._header_registry: dict[tuple, dict] = {}
        # Persisted header customizations: {key → {"color": str, "name": str}}
        from PyQt6.QtCore import QSettings
        self._hdr_settings = QSettings("JKCatalog", "TodayPaymentHeaders")
        self._header_customizations: dict[str, dict] = {}
        # Load saved customizations
        raw = self._hdr_settings.value("customizations", {})
        if isinstance(raw, dict):
            self._header_customizations = raw
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Top Bar (Toggle Switch) ---
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #f1f3f5; border-bottom: 1px solid #dee2e6;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(15, 8, 15, 8)
        
        title_lbl = QLabel("Today Payment")
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
        
        from PyQt6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #dee2e6;
                width: 2px;
                margin: 0px 8px;
            }
        """)
        
        # Column 1
        col1_w = QWidget()
        col1 = QVBoxLayout(col1_w)
        col1.setContentsMargins(0, 0, 0, 0)
        col1.setSpacing(25)
        
        self.t_pay = _StyledTable(
            "Payments", 
            ["DATE", "Particulars", "Payment", "", ""],
            col_widths=[100, 200, 100, 80, 80],
            header_color="#1976D2",
            settings_key="TodayPay_Pay"
        )
        self.t_pay.btn_add.clicked.connect(lambda: self._add_row(self.t_pay, 5))
        self._tables.append(self.t_pay)
        col1.addWidget(self.t_pay)

        self.t_pur_tod = _StyledTable(
            "Purchase (Today)", 
            ["DATE", "Particulars", "Payment", "", ""],
            col_widths=[100, 200, 100, 80, 80],
            header_color="#1976D2",
            settings_key="TodayPay_PurTod"
        )
        self.t_pur_tod.btn_add.clicked.connect(lambda: self._add_row(self.t_pur_tod, 5))
        self._tables.append(self.t_pur_tod)
        col1.addWidget(self.t_pur_tod)

        self.t_pur_upc = _StyledTable(
            "Purchase (Upcoming)", 
            ["DATE", "Particulars", "Payment", "", ""],
            col_widths=[100, 200, 100, 80, 80],
            header_color="#1976D2",
            settings_key="TodayPay_PurUpc"
        )
        self.t_pur_upc.btn_add.clicked.connect(lambda: self._add_row(self.t_pur_upc, 5))
        self._tables.append(self.t_pur_upc)
        col1.addWidget(self.t_pur_upc)
        col1.addStretch()
        
        # Column 2
        col2_w = QWidget()
        col2 = QVBoxLayout(col2_w)
        col2.setContentsMargins(0, 0, 0, 0)
        col2.setSpacing(25)
        
        self.t_dl = _StyledTable(
            "Demand Loans (DL)", 
            ["SN", "DL No.", "Amount", "Expiry Date", "Day's left", "Gap"],
            col_widths=[40, 100, 100, 110, 75, 55],
            header_color="#388E3C",
            settings_key="TodayPay_DL"
        )
        self.t_dl.btn_add.clicked.connect(self._add_dl_row)
        self.t_dl.table.itemChanged.connect(self._calc_days_left)
        self._tables.append(self.t_dl)
        col2.addWidget(self.t_dl)
        
        self.t_acc = _StyledTable(
            "Account Table", 
            ["Account Name", "Remain Cash", "Bank / Cash"],
            col_widths=[200, 120, 120],
            header_color="#F57C00",
            settings_key="TodayPay_Acc"
        )
        self.t_acc.btn_add.clicked.connect(lambda: self._add_row(self.t_acc, 3))
        self._tables.append(self.t_acc)
        col2.addWidget(self.t_acc)
        
        self.t_lim = _StyledTable(
            "Limits & LC", 
            ["Limit Type", "Amount"],
            col_widths=[200, 150],
            header_color="#D84315",
            settings_key="TodayPay_Lim"
        )
        self.t_lim.btn_add.clicked.connect(lambda: self._add_row(self.t_lim, 2))
        self._tables.append(self.t_lim)
        col2.addWidget(self.t_lim)
        col2.addStretch()
        
        splitter.addWidget(col1_w)
        splitter.addWidget(col2_w)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)
        
        c_lay.addWidget(splitter)
        scroll.setWidget(container)
        v1_layout.addWidget(scroll)
        self.stack.addWidget(self.view1)
        
        # --- VIEW 2: Excel Grid View ---
        self.view2 = QWidget()
        v2_layout = QVBoxLayout(self.view2)
        v2_layout.setContentsMargins(12, 12, 12, 12)
        
        # Removed spacer columns to make it one massive, tight table
        grid_headers = [""] * 13
        self.grid = QTableWidget(50, len(grid_headers))
        self.grid.setHorizontalHeaderLabels(grid_headers)
        self.grid.horizontalHeader().setVisible(False)
        self.grid.setFont(_H_NORM)
        self.grid.setAlternatingRowColors(True)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._show_grid_context_menu)
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
        
        widths = [90, 220, 110, 80, 80, 180, 110, 110, 40, 90, 110, 100, 70]
        for i, w in enumerate(widths):
            self.grid.setColumnWidth(i, w)
        
        self.grid.itemChanged.connect(self._grid_item_changed)
        v2_layout.addWidget(self.grid)
        self.stack.addWidget(self.view2)
        
        main_layout.addWidget(self.stack)
        self._db = get_db_manager()
        self._db_name = ""  # Set via set_company_path when company is loaded
        self._load_data()

    def set_company_path(self, path: str):
        """Called by SuppPaymentUI when the company session is activated."""
        import os
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._db.ensure_database_exists(self._db_name, path)
        self._ensure_tables()
        self._load_from_db()

    def _ensure_tables(self):
        """Create today_payment tables if they don't exist yet."""
        for table, ddl in [
            ("tp_payments",  "CREATE TABLE tp_payments  (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))"),
            ("tp_pur_today", "CREATE TABLE tp_pur_today (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))"),
            ("tp_pur_upcoming", "CREATE TABLE tp_pur_upcoming (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))"),
            ("tp_accounts", "CREATE TABLE tp_accounts (sn INT IDENTITY, account_name NVARCHAR(200), remain_cash NVARCHAR(100), bank_cash NVARCHAR(100))"),
            ("tp_limits",   "CREATE TABLE tp_limits   (sn INT IDENTITY, limit_type NVARCHAR(200), amount NVARCHAR(100), col3 NVARCHAR(100))"),
            ("tp_dl",       "CREATE TABLE tp_dl       (sn INT IDENTITY, dl_no NVARCHAR(100), amount NVARCHAR(100), expiry_date NVARCHAR(50), days_left NVARCHAR(20), gap NVARCHAR(20))"),
            # Independent grid storage — decoupled from column view tables
            ("tp_grid_data", "CREATE TABLE tp_grid_data (row_idx INT NOT NULL, col_idx INT NOT NULL, cell_text NVARCHAR(MAX), bg_color NVARCHAR(20), PRIMARY KEY (row_idx, col_idx))"),
        ]:
            self._db.ensure_table(self._db_name, table, ddl)

    def _load_from_db(self):
        """Load data from DB and populate both Column View and Grid View."""
        if not self._db_name:
            return

        def fetch(sql):
            rows = self._db.execute_query(self._db_name, sql)
            return [tuple(str(c) if c is not None else "" for c in row) for row in rows] if rows else []

        pay_data     = fetch("SELECT date, particulars, payment, col4, col5 FROM tp_payments  ORDER BY sn")
        pur_tod_data = fetch("SELECT date, particulars, payment, col4, col5 FROM tp_pur_today  ORDER BY sn")
        pur_upc_data = fetch("SELECT date, particulars, payment, col4, col5 FROM tp_pur_upcoming ORDER BY sn")
        acc_data     = fetch("SELECT account_name, remain_cash, bank_cash     FROM tp_accounts  ORDER BY sn")
        lim_data     = fetch("SELECT limit_type, amount, col3                 FROM tp_limits    ORDER BY sn")
        dl_raw       = fetch("SELECT dl_no, amount, expiry_date, days_left, gap FROM tp_dl      ORDER BY sn")
        # Prepend display SN — grid expects 6-tuple: (sn, dl_no, amount, expiry_date, days_left, gap)
        dl_data      = [(str(i + 1),) + row for i, row in enumerate(dl_raw)]

        # 1. Fill Column View only — Grid View is independent
        def fill(t_obj, data, ncols):
            t_obj.table.setRowCount(len(data))
            for r, row in enumerate(data):
                for c in range(ncols):
                    t_obj.table.setItem(r, c, QTableWidgetItem(row[c] if c < len(row) else ""))
            t_obj.recalculate_height()

        fill(self.t_pay,     pay_data,     5)
        fill(self.t_pur_tod, pur_tod_data, 5)
        fill(self.t_pur_upc, pur_upc_data, 5)
        fill(self.t_acc,     acc_data,     3)
        fill(self.t_lim,     lim_data,     3)
        # DL Column View: 6 cols with SN prepended
        self.t_dl.table.setRowCount(len(dl_data))
        for r, row in enumerate(dl_data):
            for c, val in enumerate(row):
                item = QTableWidgetItem(val)
                if c == 4:  # days_left — read-only + bold
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    f = item.font(); f.setBold(True); item.setFont(f)
                self.t_dl.table.setItem(r, c, item)
        self.t_dl.recalculate_height()

        # 2. Load Grid View from its own DB table.
        #    If tp_grid_data is empty this is the first run — seed from column view data.
        grid_rows = self._db.execute_query(self._db_name, "SELECT COUNT(*) FROM tp_grid_data")
        grid_count = grid_rows[0][0] if grid_rows else 0
        if grid_count == 0:
            # First-time seed
            self._populate_grid(pay_data, pur_tod_data, pur_upc_data, acc_data, lim_data, dl_data)
            self._save_grid_to_db()           # persist the seeded state
        else:
            self._load_grid_from_db()         # restore previously saved grid state

    def save_section(self, table_name: str, t_obj, col_names: list[str]):
        """Save a single _StyledTable section back to the database."""
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(f"DELETE FROM {table_name}")
            for r in range(t_obj.table.rowCount()):
                vals = []
                for c in range(len(col_names)):
                    it = t_obj.table.item(r, c)
                    vals.append(it.text().strip() if it else "")
                placeholders = ", ".join(["?"] * len(col_names))
                cur.execute(f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({placeholders})", vals)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] save_section({table_name}): {e}")

    # ── Grid persistence helpers ───────────────────────────────────────────────

    def _save_grid_to_db(self):
        """Persist all non-empty grid cells to tp_grid_data."""
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_grid_data")
            for r in range(self.grid.rowCount()):
                for c in range(self.grid.columnCount()):
                    it = self.grid.item(r, c)
                    if it is None:
                        continue
                    text = it.text()
                    bg   = it.background().color().name() if it.background().style() != 0 else ""
                    if text or bg:
                        cur.execute(
                            "INSERT INTO tp_grid_data (row_idx, col_idx, cell_text, bg_color) VALUES (?,?,?,?)",
                            (r, c, text, bg)
                        )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] _save_grid_to_db: {e}")

    def _load_grid_from_db(self):
        """Restore the grid from tp_grid_data, then repaint section headers on top."""
        if not self._db_name:
            return
        rows = self._db.execute_query(
            self._db_name,
            "SELECT row_idx, col_idx, cell_text, bg_color FROM tp_grid_data"
        )
        self.grid.blockSignals(True)
        self.grid.clearContents()
        self._header_registry.clear()
        for row_idx, col_idx, text, bg_color in (rows or []):
            it = QTableWidgetItem(text or "")
            if bg_color and bg_color != "#000000":
                it.setBackground(QBrush(QColor(bg_color)))
            self.grid.setItem(int(row_idx), int(col_idx), it)
        self.grid.blockSignals(False)
        # Repaint header rows on top so they stay styled + editable
        # We call _paint_grid_headers which only sets the very first row (row 0)
        self._paint_grid_headers()
        # Re-register header cells by running paint_sub_header logic with no data
        self._restore_header_registry()

    def _restore_header_registry(self):
        """Scan the loaded grid and rebuild _header_registry from QSettings customizations.
        Called after _load_grid_from_db so right-click rename/color still works."""
        self._header_registry.clear()
        # Re-invoke paint_sub_header for the known fixed header positions.
        # We don't touch cell text/color — they were already restored from DB.
        # We just register the cells so context menu recognises them.
        sections = [
            # (row, c_start, c_end, default_name, default_color)
            (1,  0,  4, "Payments",           "#1976D2"),
            (1,  5,  7, "Account Table",       "#F57C00"),
            (1,  8, 12, "Demand Loans (DL)",   "#388E3C"),
        ]
        for r, c_start, c_end, name, color in sections:
            key = f"{r}_{c_start}"
            for c in range(c_start, c_end + 1):
                self._header_registry[(r, c)] = {
                    "key": key, "cols": (c_start, c_end), "row": r,
                    "default_name": name, "default_color": color
                }
            # Also register dynamic rows (Purchase Today, Upcoming, Limits) if present
        # Scan all rows for colored cells that look like section headers
        for r in range(self.grid.rowCount()):
            for c in range(self.grid.columnCount()):
                it = self.grid.item(r, c)
                if it is None:
                    continue
                bg = it.background().color()
                # If it has a dark non-white background and bold font → likely a header
                if bg.isValid() and bg.name() not in ("#000000", "#ffffff", "", "#1a2035") \
                        and (r, c) not in self._header_registry:
                    # Use the cell's text as both key and default name
                    key = f"{r}_{c}"
                    self._header_registry[(r, c)] = {
                        "key": key, "cols": (c, c), "row": r,
                        "default_name": it.text(), "default_color": bg.name()
                    }
                    # Make anchor editable
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)

    def _populate_grid(self, pay_data, pur_tod_data, pur_upc_data, acc_data, lim_data, dl_data):
        """Paint section headers and fill data into the Excel Grid View."""
        self.grid.clearContents()
        self._header_registry.clear()  # Reset registry before repainting

        def paint_sub_header(r, c_start, c_end, text, col_headers=None, bg="#1976D2"):
            # Apply any saved customizations for this header block
            key = f"{r}_{c_start}"
            custom = self._header_customizations.get(key, {})
            actual_text = custom.get("name", text)
            actual_bg   = custom.get("color", bg)
            actual_fg   = custom.get("text_color", "#ffffff")
            for c in range(c_start, c_end + 1):
                item = QTableWidgetItem(actual_text if c == c_start else "")
                # Anchor cell is editable so the user can type directly
                if c == c_start:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
                else:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setBackground(QBrush(QColor(actual_bg)))
                item.setForeground(QBrush(QColor(actual_fg)))
                item.setFont(_H_BOLD)
                self.grid.setItem(r, c, item)
                # Register this cell as a header
                self._header_registry[(r, c)] = {
                    "key": key, "cols": (c_start, c_end), "row": r,
                    "default_name": text, "default_color": bg
                }
            if c_start != c_end:
                self.grid.setSpan(r, c_start, 1, c_end - c_start + 1)
            if col_headers:
                for idx, h in enumerate(col_headers):
                    if c_start + idx <= c_end:
                        h_item = QTableWidgetItem(h)
                        h_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                        h_item.setBackground(QBrush(QColor("#1A2035")))
                        h_item.setForeground(QBrush(QColor("#ffffff")))
                        h_item.setFont(_H_BOLD)
                        self.grid.setItem(r + 1, c_start + idx, h_item)

        def fill_block(start_r, start_c, data):
            for i, row_data in enumerate(data):
                for j, val in enumerate(row_data):
                    item = QTableWidgetItem(val)
                    if start_c == 8 and j == 3:  # DL days_left (no SN in grid) — read-only + bold
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        f = item.font(); f.setBold(True); item.setFont(f)
                    self.grid.setItem(start_r + i, start_c + j, item)

        # Left Column: Payments, Purchase Today, Purchase Upcoming
        r_pur = 1
        paint_sub_header(r_pur, 0, 4, "Payments",
                         ["DATE", "Particulars", "Payment", "", ""], "#1976D2")
        fill_block(r_pur + 2, 0, pay_data)

        r_pur += len(pay_data) + 3
        paint_sub_header(r_pur, 0, 4, "Purchase (Today)",
                         ["DATE", "Particulars", "Payment", "", ""], "#1976D2")
        fill_block(r_pur + 2, 0, pur_tod_data)

        r_pur += len(pur_tod_data) + 3
        paint_sub_header(r_pur, 0, 4, "Purchase (Upcoming)",
                         ["DATE", "Particulars", "Payment", "", ""], "#1976D2")
        fill_block(r_pur + 2, 0, pur_upc_data)

        # Middle Column: Accounts & Limits
        r_acc = 1
        paint_sub_header(r_acc, 5, 7, "Account Table",
                         ["Account Name", "Remain Cash", "Bank / Cash"], "#F57C00")
        fill_block(r_acc + 2, 5, acc_data)

        r_acc += len(acc_data) + 3
        paint_sub_header(r_acc, 5, 7, "Limits & LC",
                         ["Limit Type", "Amount", ""], "#D84315")
        fill_block(r_acc + 2, 5, lim_data)

        # Right Column: Demand Loans — grid only has 5 cols (8-12), so drop SN (implicit)
        r_dl = 1
        paint_sub_header(r_dl, 8, 12, "Demand Loans (DL)",
                         ["DL No.", "Amount", "Expiry Date", "Day's left", "Gap"], "#388E3C")
        # Strip the leading SN from each DL row before placing in grid
        dl_for_grid = [row[1:] for row in dl_data] if dl_data and len(dl_data[0]) == 6 else dl_data
        fill_block(r_dl + 2, 8, dl_for_grid)

        QTimer.singleShot(100, self._adjust_heights)

    def _grid_item_changed_save(self):
        """Debounced: save the entire grid to DB after any cell change."""
        if not self._db_name:
            return
        self._save_grid_to_db()

    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)

    def _paint_grid_headers(self):
        self.grid.setRowHeight(0, 30)
        headers = [
            (0, 2, "PURCHASES", "#1976D2", "#ffffff"),
            (3, 5, "ACCOUNTS & LIMITS", "#F57C00", "#ffffff"),
            (6, 10, "DEMAND LOANS", "#388E3C", "#ffffff")
        ]
        for start_c, end_c, title, bg, fg in headers:
            for c in range(start_c, end_c + 1):
                item = QTableWidgetItem(title if c == start_c else "")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setFont(_H_BOLD)
                item.setBackground(QBrush(QColor(bg)))
                item.setForeground(QBrush(QColor(fg)))
                self.grid.setItem(0, c, item)
            if start_c != end_c:
                self.grid.setSpan(0, start_c, 1, (end_c - start_c + 1))

    def _load_data(self):
        """Initialize both views with empty data on startup.
        Real data is loaded via _load_from_db() after set_company_path() is called."""
        self._populate_grid([], [], [], [], [], [])

    def _adjust_heights(self):
        for t in self._tables:
            t.recalculate_height()

    def _add_row(self, t_obj, num_cols):
        r = t_obj.table.rowCount()
        t_obj.table.insertRow(r)
        for c in range(num_cols):
            t_obj.table.setItem(r, c, QTableWidgetItem(""))
        t_obj.recalculate_height()

    def _add_dl_row(self):
        r = self.t_dl.table.rowCount()
        self.t_dl.table.insertRow(r)
        for c in range(6):
            item = QTableWidgetItem("")
            if c == 4:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.t_dl.table.setItem(r, c, item)
        self.t_dl.recalculate_height()
            
    def _calc_days_left(self, item):
        if item.column() != 3: return
        r = item.row()
        date_str = item.text().strip()
        self.t_dl.table.blockSignals(True)
        try:
            item4 = self.t_dl.table.item(r, 4)
            if item4 is None:
                item4 = QTableWidgetItem("")
                font = item4.font()
                font.setBold(True)
                item4.setFont(font)
                item4.setFlags(item4.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.t_dl.table.setItem(r, 4, item4)

            if not date_str:
                item4.setText("")
                return
            import datetime
            try:
                parts = date_str.replace('-','/').replace('.','/').split('/')
                if len(parts) >= 3:
                    if len(parts[0]) == 4:
                        dt = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:
                        if len(parts[2]) == 2: parts[2] = "20" + parts[2]
                        dt = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
                    today = datetime.date.today()
                    diff = (dt - today).days
                    item4.setText(str(diff))
                else:
                    item4.setText("?")
            except Exception:
                item4.setText("?")
        finally:
            self.t_dl.table.blockSignals(False)

    def _grid_item_changed(self, item):
        r, c = item.row(), item.column()

        # Auto-save header renames (user typed directly into the anchor cell)
        hdr_info = self._header_registry.get((r, c))
        if hdr_info and c == hdr_info["cols"][0]:
            key = hdr_info["key"]
            self._header_customizations.setdefault(key, {})["name"] = item.text().strip()
            self._hdr_settings.setValue("customizations", self._header_customizations)
            # Also persist grid so renamed header survives reload
            QTimer.singleShot(300, self._grid_item_changed_save)
            return

        # Persist grid data change
        QTimer.singleShot(300, self._grid_item_changed_save)

        # Grid day's left calc (Column 11 is Expiry Date, Column 12 is Day's left)
        if c != 11:
            return
        date_str = item.text().strip()
        self.grid.blockSignals(True)
        try:
            item12 = self.grid.item(r, 12)
            if item12 is None:
                item12 = QTableWidgetItem("")
                font = item12.font()
                font.setBold(True)
                item12.setFont(font)
                item12.setFlags(item12.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.grid.setItem(r, 12, item12)

            if not date_str:
                item12.setText("")
                return
            import datetime
            try:
                parts = date_str.replace('-','/').replace('.','/').split('/')
                if len(parts) >= 3:
                    if len(parts[0]) == 4:
                        dt = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:
                        if len(parts[2]) == 2: parts[2] = "20" + parts[2]
                        dt = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
                    today = datetime.date.today()
                    diff = (dt - today).days
                    item12.setText(str(diff))
                else:
                    item12.setText("?")
            except Exception:
                item12.setText("?")
        finally:
            self.grid.blockSignals(False)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        col_flags = (QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed) if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        for t in self._tables:
            t.table.setEditTriggers(col_flags)
            t.btn_add.setEnabled(can_edit)
        # Grid: always keep DoubleClicked so header anchor cells can be renamed.
        # Data cells are non-editable in view mode via their item flags.
        grid_flags = (QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed) if can_edit else QTableWidget.EditTrigger.DoubleClicked
        self.grid.setEditTriggers(grid_flags)
        # In view mode, strip ItemIsEditable from data cells (non-header cells)
        if not can_edit:
            for row in range(self.grid.rowCount()):
                for col in range(self.grid.columnCount()):
                    if (row, col) not in self._header_registry:
                        it = self.grid.item(row, col)
                        if it:
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        else:
            # Restore ItemIsEditable on all data cells in edit mode
            for row in range(self.grid.rowCount()):
                for col in range(self.grid.columnCount()):
                    if (row, col) not in self._header_registry:
                        it = self.grid.item(row, col)
                        if it and not (it.flags() & Qt.ItemFlag.ItemIsEditable):
                            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
    def _show_grid_context_menu(self, pos):
        if not getattr(self, "_can_edit", True):
            return

        grid = self.grid if hasattr(self, "grid") else getattr(self, "table", None)
        if not grid:
            return

        item = grid.itemAt(pos)
        r = item.row() if item else grid.currentRow()
        c = item.column() if item else grid.currentColumn()
        if r < 0: r = 0
        if c < 0: c = 0

        menu = QMenu(self)

        # — Color picker available for every cell —
        action_bg_color = menu.addAction("🎨  Change Cell Color")
        action_text_color = menu.addAction("🔤  Change Text Color")
        menu.addSeparator()
        action_insert_row_above = menu.addAction("Insert Row Above")
        action_insert_row_below = menu.addAction("Insert Row Below")
        menu.addSeparator()
        action_insert_col_left  = menu.addAction("Insert Column Left")
        action_insert_col_right = menu.addAction("Insert Column Right")
        menu.addSeparator()
        action_delete_row = menu.addAction("Delete Row")
        action_delete_col = menu.addAction("Delete Column")

        action = menu.exec(grid.viewport().mapToGlobal(pos))

        if action == action_bg_color or action == action_text_color:
            from PyQt6.QtWidgets import QColorDialog
            it = grid.item(r, c)
            if action == action_bg_color:
                cur_color = it.background().color() if it else QColor("#ffffff")
                dlg_title = "Pick Background Color"
            else:
                cur_color = it.foreground().color() if it else QColor("#000000")
                dlg_title = "Pick Text Color"
                
            color = QColorDialog.getColor(cur_color, self, dlg_title)
            if color.isValid():
                if it is None:
                    it = QTableWidgetItem("")
                    grid.setItem(r, c, it)
                    
                if action == action_bg_color:
                    it.setBackground(QBrush(color))
                else:
                    it.setForeground(QBrush(color))
                    
                # If it's a header anchor cell, also save the color
                hdr_info = self._header_registry.get((r, c))
                if hdr_info:
                    key = hdr_info["key"]
                    new_hex = color.name()
                    if action == action_bg_color:
                        self._header_customizations.setdefault(key, {})["color"] = new_hex
                    else:
                        self._header_customizations.setdefault(key, {})["text_color"] = new_hex
                    self._hdr_settings.setValue("customizations", self._header_customizations)
                    # Apply to all cells in the span
                    c_start, c_end = hdr_info["cols"]
                    for col in range(c_start, c_end + 1):
                        span_it = grid.item(r, col)
                        if span_it:
                            if action == action_bg_color:
                                span_it.setBackground(QBrush(color))
                            else:
                                span_it.setForeground(QBrush(color))
                self._grid_item_changed(it)

        elif action == action_insert_row_above:
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
        
        # Table
        self.table = QTableWidget(0, self._total_cols())
        self.table.setObjectName("RecordTable")
        self.table.setFont(_H_NORM)
        
        self.table.horizontalHeader().setVisible(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        
        self.table.setHorizontalHeaderLabels(self._headers)
        
        self.table.setStyleSheet("""
            QTableWidget { gridline-color: #A0A0A0; alternate-background-color: #f8f9fa; }
            QHeaderView::section:horizontal {
                background-color: #1A2035;
                color: #ffffff;
                padding: 4px;
                border: 1px solid #ced4da;
                font-weight: bold;
            }
        """)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_grid_context_menu)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
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
        self.stack.addWidget(self.view1)
        
        main_layout.addWidget(self.stack)
        self.header_filter = HeaderEditFilter(self.table, "RecordTable")
        self.header_filter.apply_customs()

        self._setup_columns()
        self._load_data()
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
        if getattr(self, "table", None):
            self.table.setHorizontalHeaderLabels(self._headers)
            if self.header_filter:
                self.header_filter.apply_customs()

    def _switch_view(self, idx):
        self.stack.setCurrentIndex(idx)
        
    def _build_detailed_table(self, r, a):
        header_idx = 3 + (a * 3)
        acc_name = self._headers[header_idx] if header_idx < len(self._headers) else f"Account {a+1}"
        
        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractScrollArea
        NUM_ROWS = 6
        t = QTableWidget(NUM_ROWS, 2)
        t.setHorizontalHeaderLabels(["Field", acc_name])
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Disable both scroll bars — the table will auto-expand to show all rows
        t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        t.setStyleSheet(
            "QTableWidget { border: none; }"
            "QHeaderView::section:horizontal { background-color: #1A2035; color: #ffffff; "
            "padding: 4px; border: 1px solid #ced4da; font-weight: bold; }"
        )
        # Compact row heights
        for i in range(NUM_ROWS):
            t.setRowHeight(i, 24)
        
        for i in range(NUM_ROWS):
            lbl = self.table.item(r + i, _rec_col(a, 0))
            val = self.table.item(r + i, _rec_col(a, 1))
            
            t.setItem(i, 0, QTableWidgetItem(lbl.text() if lbl else ""))
            v_item = QTableWidgetItem(val.text() if val else "")
            if val and val.font().bold():
                f = v_item.font()
                f.setBold(True)
                v_item.setFont(f)
            t.setItem(i, 1, v_item)
        
        # Calculate exact height: header + (NUM_ROWS * row_height) + 2px border
        header_h = t.horizontalHeader().sizeHint().height()
        rows_h   = sum(t.rowHeight(i) for i in range(NUM_ROWS))
        t.setFixedHeight(header_h + rows_h + 2)
        return t

    def _build_detailed_view(self):
        # Clear existing layout
        while self.c_lay.count():
            child = self.c_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        # Build individual tables based on Grid View data
        r = 0
        while r < self.table.rowCount():
            # Skip gaps
            if self.table.rowSpan(r, 0) == 1 and not (self.table.item(r, 0) and self.table.item(r, 0).text()):
                r += 1
                continue
                
            sn = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            acof = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            
            from PyQt6.QtWidgets import QGroupBox
            group = QGroupBox(f"{sn}. {acof}")
            group.setFont(_H_BOLD)
            group.setStyleSheet(
                "QGroupBox { border: 1px solid #ced4da; border-radius: 6px; "
                "margin-top: 8px; padding-top: 8px; padding-bottom: 4px; } "
                "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; "
                "padding: 0 5px; color: #1976D2; }"
            )
            g_lay = QVBoxLayout(group)
            g_lay.setContentsMargins(6, 4, 6, 4)
            g_lay.setSpacing(4)
            
            total_accts = self._n_company + self._n_personal

            # Single horizontal row: company tables | separator | personal tables
            # Skip any account slot whose value cells are all empty (supplier has fewer accounts)
            all_row = QWidget()
            all_lay = QHBoxLayout(all_row)
            all_lay.setContentsMargins(0, 0, 0, 0)
            all_lay.setSpacing(6)

            company_tables_added = 0
            for a in range(self._n_company):
                # Check if this account slot has any data
                has_data = any(
                    self.table.item(r + i, _rec_col(a, 1)) and
                    self.table.item(r + i, _rec_col(a, 1)).text().strip()
                    for i in range(6)
                )
                if has_data:
                    all_lay.addWidget(self._build_detailed_table(r, a))
                    company_tables_added += 1

            personal_tables = []
            for a in range(self._n_company, total_accts):
                has_data = any(
                    self.table.item(r + i, _rec_col(a, 1)) and
                    self.table.item(r + i, _rec_col(a, 1)).text().strip()
                    for i in range(6)
                )
                if has_data:
                    personal_tables.append(self._build_detailed_table(r, a))

            # Only add separator if both sides have content
            if company_tables_added > 0 and personal_tables:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                sep.setStyleSheet("color: #ced4da;")
                all_lay.addWidget(sep)

            for tbl in personal_tables:
                all_lay.addWidget(tbl)

            all_lay.addStretch()
            g_lay.addWidget(all_row)

            self.c_lay.addWidget(group)
            r += 6

        self.c_lay.addStretch()

    def _total_cols(self) -> int:
        return _REC_FIXED + (self._n_company + self._n_personal) * _REC_BLOCK

    def _setup_columns(self):
        self.table.setColumnCount(self._total_cols())
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 200)
        total_accts = self._n_company + self._n_personal
        for a in range(total_accts):
            self.table.setColumnWidth(_rec_col(a, 0), _REC_LBL_W)
            self.table.setColumnWidth(_rec_col(a, 1), 250)
            if a < total_accts - 1:
                self.table.setColumnWidth(_rec_col(a, 2), _REC_SEP_W)
            else:
                self.table.setColumnWidth(_rec_col(a, 2), 0)

    def _load_data(self):
        for sn, acof, accts in _RECORD_DATA:
            self._insert_row(sn, acof, accts)

    def _insert_row(self, sn, acof, accts):
        r = self.table.rowCount()
        # insert 6 rows for fields
        for i in range(6):
            self.table.insertRow(r + i)
            self.table.setRowHeight(r + i, _REC_ROW_H)

        # Merge SN and A/C of across 6 rows
        self.table.setSpan(r, 0, 6, 1)
        self.table.setSpan(r, 1, 6, 1)
        
        # Set SN and A/C of text in the top-left cell of the span
        sn_item = QTableWidgetItem(str(sn))
        sn_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.table.setItem(r, 0, sn_item)
        
        acof_item = QTableWidgetItem(acof)
        acof_item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.table.setItem(r, 1, acof_item)

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
                self.table.setSpan(r, _rec_col(a, 2), 6, 1)
                spacer = QTableWidgetItem("")
                spacer.setFlags(Qt.ItemFlag.NoItemFlags)
                self.table.setItem(r, _rec_col(a, 2), spacer)

            for i, key in enumerate(_REC_FIELD_KEYS):
                # Label cell
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled) # Read only labels
                self.table.setItem(r + i, _rec_col(a, 0), lbl_item)

                # Value cell
                val = d.get(key, "")
                val_item = QTableWidgetItem(val)
                if key == "rakam" and val:
                    f = val_item.font()
                    f.setBold(True)
                    val_item.setFont(f)
                self.table.setItem(r + i, _rec_col(a, 1), val_item)

        # Insert Gap row
        gap_row = r + 6
        self.table.insertRow(gap_row)
        self.table.setRowHeight(gap_row, _REC_GAP_H)
        self.table.setSpan(gap_row, 0, 1, self._total_cols())
        gap_item = QTableWidgetItem("")
        gap_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(gap_row, 0, gap_item)

    def _add_supplier(self):
        if not self._can_edit: return
        self._insert_row("", "", {})
        self.table.scrollToBottom()
        self._build_detailed_view()

    def _add_company_acct(self):
        if not self._can_edit: return
        insert_idx = _REC_FIXED + self._n_company * _REC_BLOCK
        self._n_company += 1
        self._update_headers()
        self._setup_columns() 
        
        for i in range(3):
            self.table.insertColumn(insert_idx + i)
            
        self._setup_columns()
        self.table.setHorizontalHeaderLabels(self._headers)
        if getattr(self, "header_filter", None):
            self.header_filter.apply_customs()
        
        new_a = self._n_company - 1
        for r in range(0, self.table.rowCount(), 7):
            if self.table.rowSpan(r, 0) == 1 and not (self.table.item(r, 0) and self.table.item(r, 0).text()):
                continue
            
            for i, key in enumerate(_REC_FIELD_KEYS):
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r + i, insert_idx, lbl_item)
                self.table.setItem(r + i, insert_idx + 1, QTableWidgetItem(""))
            
            self.table.setSpan(r, insert_idx + 2, 6, 1)
            spacer = QTableWidgetItem("")
            spacer.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(r, insert_idx + 2, spacer)
            
        self._build_detailed_view()

    def _add_personal_acct(self):
        if not self._can_edit: return
        insert_idx = _REC_FIXED + (self._n_company + self._n_personal) * _REC_BLOCK
        self._n_personal += 1
        self._update_headers()
        self._setup_columns() 
        
        for i in range(3):
            self.table.insertColumn(insert_idx + i)
            
        self._setup_columns()
        self.table.setHorizontalHeaderLabels(self._headers)
        if getattr(self, "header_filter", None):
            self.header_filter.apply_customs()
        
        new_a = self._n_company + self._n_personal - 1
        for r in range(0, self.table.rowCount(), 7):
            if self.table.rowSpan(r, 0) == 1 and not (self.table.item(r, 0) and self.table.item(r, 0).text()):
                continue
            
            for i, key in enumerate(_REC_FIELD_KEYS):
                lbl_item = QTableWidgetItem(_REC_FIELD_LABELS[i])
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r + i, insert_idx, lbl_item)
                self.table.setItem(r + i, insert_idx + 1, QTableWidgetItem(""))
            
            self.table.setSpan(r, insert_idx + 2, 6, 1)
            spacer = QTableWidgetItem("")
            spacer.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(r, insert_idx + 2, spacer)
            
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
    ("2021-02-01","2021-02-24", 23,  "Cash Payment",      4000000,    None,    4000000   ),
    (None,        "2021-02-24", None,"Cash Recived",       None,       800000,  3200000   ),
    (None,        "2021-03-02", None,"Cash Recived",       None,       700000,  2500000   ),
    ("2021-01-31","2021-04-30", 89,  "Interest",          109726,     None,    2609726   ),
    ("2021-05-01","2021-07-31", 91,  "Interest",          117116,     None,    2726842   ),
    ("2021-08-01","2021-10-30", 90,  "Interest",          134474,     None,    2861316   ),
    ("2021-11-01","2022-01-31", 91,  "Interest",          128406,     None,    2989722   ),
    ("2022-02-01","2022-04-30", 88,  "Interest",          129746,     None,    3119468   ),
    ("2022-05-01","2022-07-31", 91,  "Interest",          116916,     None,    3236384   ),
    ("2022-07-27", None,        None, None,                None,       150000,  3086384   ),
    ("2022-08-21", None,        None, None,                None,       50000,   3036384   ),
    ("2022-08-31", None,        None, None,                None,       500000,  2536384   ),
    ("2022-08-01","2022-11-15", 106, "Interest",          158724,     None,    2695108   ),
    ("2022-11-16","2023-02-14", 90,  "Interest",          119619,     None,    2814727   ),
    (None,        None,         None,"Cash Recived",       None,       314727,  2500000   ),
    ("2023-02-15","2023-03-22", 35,  "Cash Recived",      43150.68,   50000,   2493150.68),
    ("2023-03-23","2023-04-23", 31,  "Cash Recived",      38114.47,   50000,   2481265.15),
    ("2023-04-24","2023-05-21", 27,  "Cash Recived",      33038.22,   50000,   2464303.37),
    ("2023-05-22","2023-06-22", 31,  "Cash Recived",      37673.46,   75000,   2426976.83),
    ("2023-06-23","2023-10-20", 119, "Cash Recived",      142426.97,  100000,  2469403.80),
    ("2023-10-21","2023-11-26", 36,  "Cash Recived",      43840.37,   75000,   2438244.17),
    ("2023-11-27","2024-01-16", 50,  "Cash Recived",      60121.09,   75000,   2423365.26),
    ("2024-01-17","2024-02-27", 41,  "Cash Recived",      48998.45,   75000,   2397363.71),
    ("2024-02-28","2024-04-15", 47,  "Cash Recived",      55566.29,   39592,   2413338.01),
    ("2024-04-16","2024-06-04", 49,  "Cash Recived",      58316.83,   45000,   2426654.83),
    ("2024-06-05","2024-06-05", 0,   "Cash Recived",      0,          76655,   2349999.83),
    ("2024-06-06","2024-06-12", 6,   "Cash Recived",      6953.42,    76954,   2279999.26),
    ("2024-06-13","2024-07-15", 32,  "Cash Recived",      35980.26,   15980,   2299999.52),
    ("2024-07-16","2024-08-13", 28,  "Cash Recived",      31758.90,   13000,   2318758.42),
    ("2024-08-14","2024-09-16", 33,  "Cash Recived",      37735.41,   75000,   2281493.83),
    ("2024-09-17","2024-10-17", 30,  "Cash Recived",      33753.61,   75247,   2240000.43),
    ("2024-10-18","2024-12-09", 52,  "Cash Recived",      57442.20,   97443,   2199999.64),
    ("2024-12-10","2024-12-20", 10,  "Cash Recived",      10849.31,  -1000000, 3210848.95),
    ("2024-12-21","2025-02-12", 53,  "account",           83921.92,   119435,  3175335.87),
    ("2025-02-13","2025-03-19", 34,  "account",           53241.25,   103577,  3125000.11),
    ("2025-03-20","2025-04-28", 39,  "account",           60102.74,   75103,   3109999.86),
    ("2025-04-29","2025-06-06", 38,  "account",           58280.55,   78281,   3089999.40),
    ("2025-06-07","2025-07-07", 30,  "account",           45715.06,   75716,   3059998.46),
    ("2025-07-08","2025-08-27", 50,  "account",           75452.02,   85450,   3050000.48),
    ("2025-08-28","2025-11-09", 73,  "account",           109800.02,  139800,  3020000.49),
    ("2025-11-10","2025-11-10", None,"Cash Recived",       None,       800000,  2220000.49),
    ("2025-11-11","2025-12-10", 29,  "account",           43190.14,   75680,   2187510.64),
    ("2025-12-11","2026-01-12", 32,  "account",           34520.72,   86169,   2135862.35),
    ("2026-01-13","2026-03-20", 66,  "account",           69517.93,   99016,   2106364.29),
    ("2026-03-21","2026-04-22", 32,  "account",           33240.16,   76506,   2063098.45),
    ("2026-04-23","2026-06-08", 46,  "account",           46801.25,   75900,   2033999.69),
    ("2026-06-09","2026-07-14", 35,  "account",           35107.39,   75107,   1994000.08),
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
        hint = QLabel("  Balance = Previous Balance + DR  \u2212  Cr.   (auto-calculated)")
        hint.setStyleSheet("color:#666; font-size:11px;")
        vlay.addWidget(hint)

        # Table
        self.table = QTableWidget(0, len(_ANIL_COLS))
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

        # Status bar showing current outstanding balance
        self._status = QLabel()
        self._status.setStyleSheet(
            "font-weight:bold; font-size:12px; padding:4px 8px;"
            "background:#1A2035; color:#fff; border-radius:4px;"
        )
        vlay.addWidget(self._status)

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


class _StyledTable(QWidget):
    def __init__(self, title, headers, col_widths=None, header_color="#2b579a", settings_key="StyledTable"):
        super().__init__()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        hlay = QHBoxLayout()
        hlay.setContentsMargins(4, 4, 4, 0)
        
        lbl = QLabel(title)
        lbl.setFont(_H_BOLD)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {header_color}; 
                color: white; 
                padding: 6px 14px; 
                border-radius: 4px;
            }}
        """)
        hlay.addWidget(lbl)
        hlay.addStretch()
        
        self.btn_add = QPushButton("+ Add Row")
        self.btn_add.setFixedHeight(28)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: #f1f3f5;
                color: #333;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 0px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e9ecef;
                border: 1px solid #adb5bd;
            }
            QPushButton:pressed {
                background-color: #dee2e6;
            }
        """)
        hlay.addWidget(self.btn_add)
        layout.addLayout(hlay)
        
        table_frame = QFrame()
        table_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #dee2e6;
                border-radius: 6px;
                background-color: white;
            }
        """)
        frame_layout = QVBoxLayout(table_frame)
        frame_layout.setContentsMargins(1, 1, 1, 1)
        
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setFont(_H_NORM)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        self.table.setStyleSheet("""
            QTableWidget {
                border: none;
                gridline-color: #f1f3f5;
                background-color: transparent;
                alternate-background-color: #f8f9fa;
            }
            QHeaderView::section:horizontal {
                background-color: #1A2035;
                border: none;
                border-bottom: 2px solid #dee2e6;
                border-right: 1px solid #e9ecef;
                padding: 4px;
                font-weight: bold;
                color: #ffffff;
            }
        """)
        
        if col_widths:
            for i, w in enumerate(col_widths):
                self.table.setColumnWidth(i, w)
        else:
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            
        frame_layout.addWidget(self.table)
        layout.addWidget(table_frame)
        
        self.header_filter = HeaderEditFilter(self.table, settings_key)
        self.header_filter.apply_customs()

    def recalculate_height(self):
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    
    def recalculate_height(self):
        h = self.table.horizontalHeader().height()
        rows = self.table.rowCount()
        for i in range(rows):
            h += self.table.rowHeight(i)
        
        if h < 50 and rows > 0:
            h = 30 + (rows * 24)
            
        h += 6
        self.table.setMinimumHeight(h)
        self.table.setMaximumHeight(h)


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
        
        self.grid = QTableWidget(cfg.get("rows", 50), len(cols))
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
        """Propagate the active company path to Today Payment tab."""
        self._today_payment_tab.set_company_path(path)

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
