from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPushButton, QInputDialog, QMenu, QMessageBox, QTableWidget, QStyledItemDelegate, QLineEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


from src.ui.table_nav_mixin import UniversalCellDelegate, UNIVERSAL_TABLE_STYLE
from PyQt6.QtWidgets import QAbstractItemView
class ExcelSheetBase(QTableWidget):
    def __init__(self, color):
        super().__init__(100, 52) # 52 Columns (AZ तक)
        self.setObjectName("ExcelSheetTable") # QSS: #ExcelSheetTable
        self.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setHorizontalHeaderLabels([self.get_column_name(i) for i in range(52)])
        # Apply opaque-editor delegate to prevent ghost-text during cell editing
        self.setItemDelegate(UniversalCellDelegate(self))

    def get_column_name(self, n):
        res = ""
        while n >= 0:
            res = chr(n % 26 + 65) + res
            n = n // 26 - 1
        return res

class VatBaseUI(QWidget):
    def __init__(self, title_prefix, theme_color, object_name):
        super().__init__()
        self.setObjectName(object_name) # QSS: #BalanceMain या #StockMain
        self.title_prefix = title_prefix
        self.theme_color = theme_color
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("VatTabWidget") # QSS: #VatTabWidget
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.tabBar().setExpanding(False)
        
        # इनलाइन स्टाइल को डायनामिक थीम के लिए रखा है, बाकी QSS से होगा
        # self.tabs.setStyleSheet(...) # Moved to QSS (handled by #BalanceMain/#StockMain selectors)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("VatAddBtn") # QSS: #VatAddBtn
        self.add_btn.setFixedSize(45, 32)
        # self.add_btn.setStyleSheet(f"background-color: {self.theme_color}; color: white; font-weight: bold; margin-right: 15px; border-radius: 4px;") # Moved to QSS
        
        self.add_btn.clicked.connect(self.add_new_sheet)
        self.tabs.setCornerWidget(self.add_btn, Qt.Corner.BottomLeftCorner)

        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        self.insert_sheet(f"{self.title_prefix} 1")
        layout.addWidget(self.tabs)

    def insert_sheet(self, name):
        sheet = ExcelSheetBase(self.theme_color)
        if not getattr(self, '_can_edit', True):
            sheet.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        idx = self.tabs.addTab(sheet, name)
        self.tabs.setCurrentIndex(idx)

    def add_new_sheet(self):
        if not getattr(self, '_can_edit', True):
            return
        self.insert_sheet(f"{self.title_prefix} {self.tabs.count() + 1}")

    def rename_tab(self, index):
        if not getattr(self, '_can_edit', True):
            return
        if index == -1: return
        name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=self.tabs.tabText(index))
        if ok and name: self.tabs.setTabText(index, name)

    def show_menu(self, point):
        if not getattr(self, '_can_edit', True):
            return
        idx = self.tabs.tabAt(point)
        if idx == -1: return
        menu = QMenu(self)
        menu.setObjectName("TabContextMenu")
        del_act = menu.addAction("❌ Delete")
        if menu.exec(self.tabs.tabBar().mapToGlobal(point)) == del_act and self.tabs.count() > 1:
            self.tabs.removeTab(idx)

    def apply_edit_mode(self, can_edit: bool):
        """Called by main_window._apply_permissions() to enforce display-only mode."""
        self._can_edit = can_edit

        for i in range(self.tabs.count()):
            sheet = self.tabs.widget(i)
            if sheet:
                sheet.setEditTriggers(
                    QTableWidget.EditTrigger.CurrentChanged | QTableWidget.EditTrigger.EditKeyPressed |
                    QTableWidget.EditTrigger.AnyKeyPressed | QTableWidget.EditTrigger.DoubleClicked
                    if can_edit else QTableWidget.EditTrigger.NoEditTriggers
                )

        self.add_btn.setEnabled(can_edit)
        self.add_btn.setToolTip("" if can_edit else "🔒 Adding sheets disabled — display only")
        self.tabs.setMovable(can_edit)
        if can_edit:
            self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        else:
            self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

# --- Derived Classes ---

class BalanceUI(VatBaseUI):
    def __init__(self): 
        super().__init__("Balance", "#8e44ad", "BalanceMain") # Purple Theme

class StockUI(VatBaseUI):
    def __init__(self): 
        super().__init__("Stock", "#27ae60", "StockMain") # Green Theme