from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableWidget, QFileDialog, QHeaderView, QFrame
)
from PyQt6.QtCore import Qt

class PurImportUI(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PurImportDialog") # QSS: #PurImportDialog
        self.setWindowTitle("Purchase Import - Tally Internal")
        self.resize(1000, 600)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title Section
        title = QLabel("📥 Purchase Data Import (Tally)")
        title.setObjectName("PurImportTitle") # QSS: #PurImportTitle
        layout.addWidget(title)

        # Top Control Bar (File Selection)
        top_bar = QHBoxLayout()
        
        self.btn_select = QPushButton("📂 Select Excel/XML File")
        self.btn_select.setObjectName("SelectFileBtn") # QSS: #SelectFileBtn
        self.btn_select.setFixedWidth(250)
        self.btn_select.clicked.connect(self.open_file_dialog)
        
        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("FilePathLabel")
        
        top_bar.addWidget(self.btn_select)
        top_bar.addWidget(self.file_label)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Preview Table
        self.table = QTableWidget(15, 6)
        self.table.setObjectName("ImportPreviewTable") # QSS: #ImportPreviewTable
        headers = ["Date", "Voucher No", "Party Name", "Item Details", "Amount", "Status"]
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table Styling
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Bottom Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        
        self.btn_import = QPushButton("🚀 Import to Tally")
        self.btn_import.setObjectName("ExecuteImportBtn") # QSS: #ExecuteImportBtn
        
        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryButton") # Standard name across your app
        close_btn.clicked.connect(self.reject)
        
        btn_box.addStretch()
        btn_box.addWidget(self.btn_import)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

    def open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Purchase File", "", "Excel Files (*.xlsx);;XML Files (*.xml)"
        )
        if file_path:
            self.file_label.setText(file_path.split("/")[-1]) # सिर्फ फाइल का नाम दिखाएँ
            print(f"File selected: {file_path}")
            # यहाँ फाइल डेटा को टेबल में लोड करने का लॉजिक आएगा

    def apply_edit_mode(self, can_edit: bool):
        """Called by main_window handler to enforce display-only mode."""
        # Lock the preview table
        if can_edit:
            self.table.setEditTriggers(
                self.table.EditTrigger.DoubleClicked |
                self.table.EditTrigger.AnyKeyPressed |
                self.table.EditTrigger.EditKeyPressed
            )
        else:
            self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)

        # Disable action buttons
        self.btn_select.setEnabled(can_edit)
        self.btn_select.setToolTip("" if can_edit else "🔒 Import disabled — display only")
        self.btn_import.setEnabled(can_edit)
        self.btn_import.setToolTip("" if can_edit else "🔒 Import disabled — display only")