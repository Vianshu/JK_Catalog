from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableWidget, QHeaderView
)
from PyQt6.QtCore import Qt

class CatalogPriceListUI(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Catalog Price List")
        self.resize(1000, 650)
        
        # मुख्य लेआउट
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # टाइटल लेबल - स्टाइल अब QSS से आएगा (ID: PageTitle)
        title = QLabel("Catalog Price List Management")
        title.setObjectName("PageTitle") 
        layout.addWidget(title)

        # टेबल - स्टाइल QSS के QTableWidget सेलेक्टर से लगेगा
        self.table = QTableWidget(30, 6)
        headers = ["Item Code", "Item Name", "Basic Price", "Standard Price", "Discount %", "Final MRP"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # बटन बॉक्स
        btn_box = QHBoxLayout()
        
        # सेव बटन - स्टाइल QSS से (ID: SaveButton)
        self.save_btn = QPushButton("Save Price List")
        self.save_btn.setObjectName("SaveButton")
        
        # क्लोज बटन - स्टाइल QSS के सामान्य QPushButton से
        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryButton") # वैकल्पिक: अलग पहचान के लिए
        close_btn.clicked.connect(self.reject)
        
        btn_box.addStretch()
        btn_box.addWidget(self.save_btn)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

    def apply_edit_mode(self, can_edit: bool):
        """Called by main_window handler to enforce display-only mode."""
        if can_edit:
            self.table.setEditTriggers(
                self.table.EditTrigger.DoubleClicked |
                self.table.EditTrigger.AnyKeyPressed |
                self.table.EditTrigger.EditKeyPressed
            )
        else:
            self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.save_btn.setEnabled(can_edit)
        self.save_btn.setToolTip("" if can_edit else "Editing disabled — display only")