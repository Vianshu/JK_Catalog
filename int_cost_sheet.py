import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableWidget, QHeaderView
)
from PyQt6.QtCore import Qt

class IntCostSheetUI(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CostSheetDialog") # QSS: #CostSheetDialog
        self.setWindowTitle("Internal Cost Sheet")
        self.resize(1150, 650)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("📊 Internal Costing Sheet")
        title.setObjectName("CostSheetTitle") # QSS: #CostSheetTitle
        layout.addWidget(title)

        # Costing Table
        self.table = QTableWidget(20, 9)
        headers = [
            "Batch No", "Item Name", "Raw Material", "Labors", 
            "Overheads", "Other Exp", "Total Cost", "Markup %", "Final Price"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setObjectName("CostingTable") # QSS: #CostingTable
        
        # Table Behavior
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.table)

        # Bottom Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        
        self.calc_btn = QPushButton("🔄 Calculate All")
        self.calc_btn.setObjectName("CalculateButton") # QSS: #CalculateButton
        
        self.save_btn = QPushButton("💾 Save Sheet")
        self.save_btn.setObjectName("SaveSheetButton") # QSS: #SaveSheetButton
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("SecondaryButton") # पहले से QSS में डिफाइन किया हुआ नाम
        self.close_btn.clicked.connect(self.reject)
        
        btn_box.addStretch()
        btn_box.addWidget(self.calc_btn)
        btn_box.addWidget(self.save_btn)
        btn_box.addWidget(self.close_btn)
        layout.addLayout(btn_box)