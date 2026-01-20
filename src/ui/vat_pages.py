from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPushButton, QInputDialog, QMenu, QMessageBox, QTableWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class ExcelSheetBase(QTableWidget):
    def __init__(self, color):
        super().__init__(100, 52) # 52 Columns (AZ तक)
        self.setObjectName("ExcelSheetTable") # QSS: #ExcelSheetTable
        self.setFont(QFont("Arial", 10))
        
        # यहाँ इनलाइन स्टाइल को रहने दिया है क्योंकि यह 'color' वेरिएबल पर निर्भर है
        # header_style = f"QHeaderView::section {{ background-color: {color}; color: white; font-weight: bold; height: 30px; border: 1px solid #dee2e6; }}"
        # self.horizontalHeader().setStyleSheet(header_style) # Moved to QSS
        self.setHorizontalHeaderLabels([self.get_column_name(i) for i in range(52)])

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
        idx = self.tabs.addTab(sheet, name)
        self.tabs.setCurrentIndex(idx)

    def add_new_sheet(self):
        self.insert_sheet(f"{self.title_prefix} {self.tabs.count() + 1}")

    def rename_tab(self, index):
        if index == -1: return
        name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=self.tabs.tabText(index))
        if ok and name: self.tabs.setTabText(index, name)

    def show_menu(self, point):
        idx = self.tabs.tabAt(point)
        if idx == -1: return
        menu = QMenu(self)
        menu.setObjectName("TabContextMenu")
        del_act = menu.addAction("❌ Delete")
        if menu.exec(self.tabs.tabBar().mapToGlobal(point)) == del_act and self.tabs.count() > 1:
            self.tabs.removeTab(idx)

# --- Derived Classes ---

class BalanceUI(VatBaseUI):
    def __init__(self): 
        super().__init__("Balance", "#8e44ad", "BalanceMain") # Purple Theme

class StockUI(VatBaseUI):
    def __init__(self): 
        super().__init__("Stock", "#27ae60", "StockMain") # Green Theme