import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog, QMenu, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class PaymentSheet(QTableWidget):
    def __init__(self):
        super().__init__(100, 15)
        self.setObjectName("PaymentSheetTable") # QSS: #PaymentSheetTable
        self.setFont(QFont("Arial", 10))
        self.verticalHeader().setDefaultSectionSize(25)
        self.setHorizontalHeaderLabels([self.get_column_name(i) for i in range(15)])

    def get_column_name(self, n):
        res = ""
        while n >= 0:
            res = chr(n % 26 + 65) + res
            n = n // 26 - 1
        return res

class SuppPaymentUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SuppPaymentMain") # QSS: #SuppPaymentMain
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # --- Tab Widget ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("PaymentTabContainer") # QSS: #PaymentTabContainer
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)
        
        # --- '+' Button ---
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("AddNewSheetBtn") # QSS: #AddNewSheetBtn
        self.add_button.setFixedSize(45, 32)
        
        # सुधार: फ़ंक्शन का नाम सही किया
        self.add_button.clicked.connect(self.add_new_sheet)
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        # राइट क्लिक और डबल क्लिक इवेंट्स
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        # पहली शीट जोड़ना
        self.insert_sheet("Payment 1")
        self.layout.addWidget(self.tabs)

    # --- आपके लॉजिक फंक्शन्स (अपरिवर्तित) ---

    def show_tab_menu(self, point):
        index = self.tabs.tabBar().tabAt(point)
        if index == -1: return

        menu = QMenu(self)
        menu.setObjectName("TabContextMenu") # QSS: #TabContextMenu
        
        rename_action = menu.addAction("✏️ Rename Sheet")
        delete_action = menu.addAction("❌ Delete Sheet")

        action = menu.exec(self.tabs.tabBar().mapToGlobal(point))

        if action == rename_action:
            self.rename_tab(index)
        elif action == delete_action:
            if self.tabs.count() > 1:
                confirm = QMessageBox.question(self, "Confirm Delete", 
                                             f"Are you sure you want to delete '{self.tabs.tabText(index)}'?", 
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if confirm == QMessageBox.StandardButton.Yes:
                    self.tabs.removeTab(index)
            else:
                QMessageBox.warning(self, "Warning", "At least one sheet must remain!")

    def insert_sheet(self, name):
        new_sheet = PaymentSheet()
        index = self.tabs.insertTab(0, new_sheet, name)
        self.tabs.setCurrentIndex(index)

    def add_new_sheet(self):
        count = self.tabs.count() + 1
        self.insert_sheet(f"Sheet {count}")

    def rename_tab(self, index):
        if index == -1: return
        old_name = self.tabs.tabText(index)
        new_name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=old_name)
        if ok and new_name.strip():
            self.tabs.setTabText(index, new_name.strip())