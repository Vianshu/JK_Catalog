import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog, QMenu, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class PriceSheet(QTableWidget):
    def __init__(self):
        # 100 Rows और 50 Columns
        super().__init__(100, 50) 
        self.setObjectName("PriceSheetTable") # QSS: #PriceSheetTable
        
        # Table Settings
        self.verticalHeader().setDefaultSectionSize(25)
        self.setHorizontalHeaderLabels([self.get_column_name(i) for i in range(50)])
        
    def get_column_name(self, n):
        res = ""
        while n >= 0:
            res = chr(n % 26 + 65) + res
            n = n // 26 - 1
        return res

class PriceListUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # --- Tab Widget (Excel Style - Bottom Tabs) ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("PriceListTabs") # QSS: #PriceListTabs
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)

        # --- '+' Button (New Sheet) ---
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("AddSheetButton") # QSS: #AddSheetButton
        self.add_button.setFixedSize(45, 32)
        self.add_button.clicked.connect(self.add_new_sheet)
        
        # Corner widget for the plus button
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        # Context Menu & Rename Logic
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        # First Default Sheet
        self.insert_sheet("Price List 1")
        
        self.main_layout.addWidget(self.tabs)

    def show_tab_menu(self, point):
        index = self.tabs.tabBar().tabAt(point)
        if index == -1: return

        menu = QMenu(self)
        menu.setObjectName("TabContextMenu")
        rename_action = menu.addAction("✏️ Rename Sheet")
        delete_action = menu.addAction("❌ Delete Sheet")

        action = menu.exec(self.tabs.tabBar().mapToGlobal(point))

        if action == rename_action:
            self.rename_tab(index)
        elif action == delete_action:
            if self.tabs.count() > 1:
                confirm = QMessageBox.question(self, "Delete", f"Delete '{self.tabs.tabText(index)}'?", 
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if confirm == QMessageBox.StandardButton.Yes:
                    self.tabs.removeTab(index)
            else:
                QMessageBox.warning(self, "Warning", "At least one sheet is required!")

    def insert_sheet(self, name):
        new_sheet = PriceSheet()
        index = self.tabs.addTab(new_sheet, name)
        self.tabs.setCurrentIndex(index)

    def add_new_sheet(self):
        count = self.tabs.count() + 1
        self.insert_sheet(f"Price List {count}")

    def rename_tab(self, index):
        if index == -1: return
        old_name = self.tabs.tabText(index)
        new_name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=old_name)
        if ok and new_name.strip():
            self.tabs.setTabText(index, new_name.strip())