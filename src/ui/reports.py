import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QDialog, QComboBox, QListWidget, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter 
from src.ui.settings import load_crm_list, load_report_json, save_report_json

class PrintDownloadDialog(QDialog):
    def __init__(self, mode="Print", parent=None, report_data=None, crm_path="crm_data.json"):
        super().__init__(parent)
        self.report_data = report_data or {}
        self.crm_path = crm_path
        self.setObjectName("ReportActionDialog") # QSS: #ReportActionDialog
        self.setWindowTitle(f"{mode} CRM")
        self.setFixedSize(400, 500)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # UI Elements
        layout.addWidget(QLabel("<b>Select CRM:</b>"))
        self.crm_combo = QComboBox()
        self.crm_combo.setObjectName("CrmSelector")
        self.crm_combo.addItems(load_crm_list(self.crm_path))
        self.crm_combo.currentTextChanged.connect(self.load_pending_pages)
        layout.addWidget(self.crm_combo)

        layout.addWidget(QLabel("<b>Pending Pages:</b>"))
        self.pages_list = QListWidget()
        self.pages_list.setObjectName("PendingPagesList")
        layout.addWidget(self.pages_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("Confirm")
        self.ok_btn.setObjectName("PrimaryActionButton")
        self.ok_btn.clicked.connect(self.accept)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.load_pending_pages()

    def load_pending_pages(self):
        self.pages_list.clear()
        crm_name = self.crm_combo.currentText()
        pending = self.report_data.get(crm_name, {}).get("pending", [str(i) for i in range(1, 13)])
        self.pages_list.addItems(pending)

class ReportsUI(QWidget):
    def __init__(self):
        super().__init__()
        self.current_company_path = "" 
        self.download_path = "" 
        self.init_ui()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(20)

        # --- Top Header Section ---
        header_layout = QHBoxLayout()
        title = QLabel("📈 CRM Performance Reports")
        title.setObjectName("SectionTitle")
        
        button_box = QHBoxLayout()
        button_box.setSpacing(10)
        
        self.btn_loc = QPushButton("📍 Set Location")
        self.btn_loc.setObjectName("LocationBtn")
        self.btn_loc.clicked.connect(self.set_location)
        
        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setObjectName("PrintBtn")
        self.btn_print.clicked.connect(lambda: self.open_dialog("Print"))
        
        self.btn_download = QPushButton("📄 PDF Download")
        self.btn_download.setObjectName("DownloadBtn")
        self.btn_download.clicked.connect(lambda: self.open_dialog("Download"))
        
        button_box.addWidget(self.btn_loc)
        button_box.addWidget(self.btn_print)
        button_box.addWidget(self.btn_download)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addLayout(button_box)
        main_layout.addLayout(header_layout)

        # --- Report Table ---
        self.table = QTableWidget()
        self.table.setObjectName("ReportsTable")
        headers = ["CRM Name", "Pending Pages", "Last Synced Pages"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table)

    def get_report_path(self):
        if self.current_company_path:
            return os.path.join(self.current_company_path, "REPORT_DATA.JSON")
        return "REPORT_DATA.JSON"

    def set_location(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if path:
            self.download_path = path
            QMessageBox.information(self, "Success", f"Download location set to:\n{path}")

    def open_dialog(self, mode):
        current_report_data = load_report_json(self.get_report_path())
        crm_path = os.path.join(self.current_company_path, "crm_data.json") if self.current_company_path else "crm_data.json"
        
        dlg = PrintDownloadDialog(mode=mode, parent=self, report_data=current_report_data, crm_path=crm_path)
        
        if dlg.exec():
            crm_name = dlg.crm_combo.currentText()
            if mode == "Print":
                self.handle_actual_print()
            elif mode == "Download" and not self.download_path:
                self.set_location()
            
            self.update_pages_logic(crm_name)

    def handle_actual_print(self):
        printer = QPrinter()
        print_dialog = QPrintDialog(printer, self)
        if print_dialog.exec():
            # Actual print logic would go here
            pass

    def update_pages_logic(self, crm_name):
        path = self.get_report_path()
        all_data = load_report_json(path)
        
        if crm_name not in all_data:
            all_data[crm_name] = {"pending": [str(i) for i in range(1, 13)], "recent": []}
            
        all_data[crm_name]["recent"] = all_data[crm_name]["pending"]
        all_data[crm_name]["pending"] = []
        
        save_report_json(all_data, path)
        self.refresh_report_data()

    def refresh_report_data(self):
        if not self.current_company_path:
            self.table.setRowCount(0)
            return

        crm_path = os.path.join(self.current_company_path, "crm_data.json")
        crm_names = load_crm_list(crm_path) 
        
        if not crm_names:
            self.table.setRowCount(0)
            return

        report_db = load_report_json(self.get_report_path())
        self.table.setRowCount(0)

        for name in crm_names:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = report_db.get(name, {"pending": [], "recent": []})
            
            self.table.setItem(row, 0, QTableWidgetItem(name))
            p_pages = ", ".join(data["pending"]) if data["pending"] else "Completed"
            self.table.setItem(row, 1, QTableWidgetItem(p_pages))
            r_pages = ", ".join(data["recent"]) if data["recent"] else "None"
            self.table.setItem(row, 2, QTableWidgetItem(r_pages))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_report_data()