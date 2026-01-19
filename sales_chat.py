import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class ExcelSheet(QTableWidget):
    def __init__(self):
        super().__init__(100, 20)
        self.setObjectName("SalesExcelTable") # QSS: #SalesExcelTable
        self.setFont(QFont("Arial", 10))
        self.verticalHeader().setDefaultSectionSize(25)
        self.setHorizontalHeaderLabels([self.get_column_name(i) for i in range(20)])

    def get_column_name(self, n):
        res = ""
        while n >= 0:
            res = chr(n % 26 + 65) + res
            n = n // 26 - 1
        return res

class SalesChatUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # --- Tab Widget (Bottom Position like Excel) ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("SalesTabWidget") # QSS: #SalesTabWidget
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)

        # --- '+' Button Style ---
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("SalesAddSheetBtn") # QSS: #SalesAddSheetBtn
        self.add_button.setFixedSize(45, 32)
        self.add_button.clicked.connect(self.add_new_sheet)
        
        # Bottom Left corner for the plus button
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        # Events: Double Click to Rename & Right Click Menu
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab_on_double_click)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)

        # Initial Sheet
        self.add_new_sheet("Sheet 1")
        self.layout.addWidget(self.tabs)

    def add_new_sheet(self, name=None):
        if not name:
            count = self.tabs.count() + 1
            name = f"Sheet {count}"
        
        new_sheet = ExcelSheet()
        index = self.tabs.addTab(new_sheet, name) # Adds to the end
        self.tabs.setCurrentIndex(index)

    def rename_tab_on_double_click(self, index):
        if index != -1:
            self.rename_sheet(index)

    def rename_sheet(self, index):
        old_name = self.tabs.tabText(index)
        new_name, ok = QInputDialog.getText(self, "Rename Sheet", "Enter new name:", text=old_name)
        if ok and new_name.strip():
            self.tabs.setTabText(index, new_name.strip())

    def show_tab_menu(self, point):
        index = self.tabs.tabBar().tabAt(point)
        if index == -1: return

        menu = QMenu(self)
        menu.setObjectName("SalesTabMenu")
        rename_action = menu.addAction("✏️ Rename")
        delete_action = menu.addAction("❌ Delete")
        
        action = menu.exec(self.tabs.tabBar().mapToGlobal(point))

        if action == rename_action:
            self.rename_sheet(index)
        elif action == delete_action:
            if self.tabs.count() > 1:
                confirm = QMessageBox.question(self, "Confirm Delete", f"Delete '{self.tabs.tabText(index)}'?", 
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if confirm == QMessageBox.StandardButton.Yes:
                    self.tabs.removeTab(index)
            else:
                QMessageBox.warning(self, "Alert", "At least one sheet is required.")