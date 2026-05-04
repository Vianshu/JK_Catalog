import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QDialog, QComboBox, QListWidget, QFileDialog, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QMarginsF
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PyQt6.QtGui import QPainter, QPageSize, QPageLayout
from src.ui.settings import load_crm_list, load_report_json, save_report_json
from src.logic.catalog_logic import CatalogLogic
from src.ui.a4_renderer import A4PageRenderer
from src.ui.print_export import PrintExportDialog # Import the shared dialog
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# Use screen DPI for consistency with full catalog
SCREEN_DPI = 96

# Use screen DPI for consistency with full catalog
SCREEN_DPI = 96

class CRMSelectDialog(QDialog):
    def __init__(self, parent=None, report_data=None, crm_path="crm_data.json", mode="Print"):
        super().__init__(parent)
        self.report_data = report_data or {}
        self.crm_path = crm_path
        self.setObjectName("ReportActionDialog") # QSS: #ReportActionDialog
        
        # Set context-aware title and button text
        if mode == "Download":
            self.setWindowTitle("Select CRM & Pages \u2014 PDF")
            btn_text = "Process to PDF"
        else:
            self.setWindowTitle("Select CRM & Pages \u2014 Print")
            btn_text = "Process to Print"
        
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

        layout.addWidget(QLabel("<b>Pending Pages (Serial Nos):</b>"))
        self.pages_list = QListWidget()
        self.pages_list.setObjectName("PendingPagesList")
        layout.addWidget(self.pages_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton(btn_text)
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
        # Default to empty list, not 1-12
        pending = self.report_data.get(crm_name, {}).get("pending", [])
        if pending:
            try:
                pending.sort(key=lambda x: int(x) if str(x).isdigit() else float('inf'))
            except:
                pending.sort()
        self.pages_list.addItems(pending)

class ReportsUI(QWidget):
    def __init__(self):
        super().__init__()
        self.current_company_path = "" 
        self.download_path = "" 
        self.logic = None
        self.init_ui()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(20)

        # --- Top Header Section ---
        header_layout = QHBoxLayout()
        title = QLabel("📈 CRM Performance Reports")
        title.setObjectName("SectionTitle")
        
        self.lbl_refresh = QLabel("⏳ Refreshing Catalog... Please Wait")
        self.lbl_refresh.setStyleSheet("color: #ff9900; font-weight: bold; font-size: 14px;")
        self.lbl_refresh.hide()
        
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
        header_layout.addWidget(self.lbl_refresh)
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
        
    def set_refreshing(self, is_refreshing):
        if is_refreshing:
            self.lbl_refresh.show()
            self.table.setEnabled(False)
        else:
            self.lbl_refresh.hide()
            self.table.setEnabled(True)
            
    def ensure_logic_init(self):
        if not self.current_company_path: return False
        
        catalog_db = os.path.join(self.current_company_path, "catalog.db")
        final_db = os.path.join(self.current_company_path, "final_data.db")
        super_db = os.path.join(os.path.dirname(self.current_company_path), "super_master.db")
        
        if not self.logic:
            self.logic = CatalogLogic(catalog_db) # init with catalog db as primary for now
            self.logic.set_paths(catalog_db, final_db, super_db)
        else:
            self.logic.set_paths(catalog_db, final_db, super_db)
        return True

    def get_report_path(self):
        if self.current_company_path:
            return os.path.join(self.current_company_path, "REPORT_DATA.JSON")
        return "REPORT_DATA.JSON"

    def set_location(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if path:
            self.download_path = path
            logger.info(f"Report download location set: '{path}'")
            QMessageBox.information(self, "Success", f"Download location set to:\n{path}")

    def open_dialog(self, mode):
        """
        Open the unified printing flow:
        1. Select CRM (CRMSelectDialog)
        2. Print/Export (PrintExportDialog)
        3. Confirm Completion (MessageBox)
        """
        if not self.ensure_logic_init():
            QMessageBox.warning(self, "Error", "Please load a company first.")
            return

        current_report_data = load_report_json(self.get_report_path())
        crm_path = os.path.join(self.current_company_path, "crm_data.json") if self.current_company_path else "crm_data.json"
        
        # 1. Select CRM
        sel_dlg = CRMSelectDialog(parent=self, report_data=current_report_data, crm_path=crm_path, mode=mode)
        if not sel_dlg.exec():
            return

        crm_name = sel_dlg.crm_combo.currentText()
        
        # Get pending pages
        pending_serials = current_report_data.get(crm_name, {}).get("pending", [])
        logger.info(f"Report opened: crm='{crm_name}', mode='{mode}', pending={len(pending_serials)} pages")
        if not pending_serials:
            QMessageBox.information(self, "Info", "No pending pages to process for this CRM.")
            # We allow them to proceed? Maybe they want to reprint old ones? 
            # Current logic in CRMSelectDialog only shows pending.
            # If nothing pending, list is empty.
            # Let's stop here if empty, as per previous logic.
            return
        
        # Sort pages
        try:
            pending_serials = sorted(pending_serials, key=lambda x: int(x) if str(x).isdigit() else float('inf'))
        except:
            pending_serials = sorted(pending_serials)

        # 2. Open Print/Export Dialog
        # We pass the mode (Print or PDF) to pre-configure the dialog, but let the user switch if they want.
        dialog_mode = "print" if mode == "Print" else "pdf"
        
        # Purge stale product data so renderer reads fresh MOQ/MRP/sizes from DB
        self.logic.invalidate_cache()

        print_dlg = PrintExportDialog(
            catalog_ui=self, # Pass self as context
            parent=self,
            mode=dialog_mode,
            page_list=pending_serials,
            renderer_callback=self.render_report_page,
            initial_crm=crm_name
        )
        
        result = print_dlg.exec()
        
        # 3. Confirmation (Only if dialog was Accepted)
        if result == QDialog.DialogCode.Accepted:
            reply = QMessageBox.question(
                self, 
                "Update Status", 
                f"Did you successfully print/export the {len(pending_serials)} pages for '{crm_name}'?\n\n"
                "Click YES to mark them as completed.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                logger.info(f"Report completed: crm='{crm_name}', pages={len(pending_serials)} marked done")
                self.update_pages_logic(crm_name)
            
    def render_report_page(self, painter, serial_no, renderer, crm_name):
        """Callback to render a specific page for the PrintExportDialog."""
        page_info = self.logic.get_page_info_by_serial(serial_no)
        if not page_info:
            return False
            
        group_name = page_info["group_name"]
        sg_sn = page_info["sg_sn"]
        page_no = page_info["page_no"]
        
        # Set header
        renderer.set_header_data(group_name, serial_no)
        
        # Get products
        products = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        renderer.fill_products(products if products else [])
        
        # Footer Date (using centralized date_utils)
        from src.utils.date_utils import get_footer_date
        footer_date = get_footer_date(products, self.logic)
        
        renderer.set_footer_data(crm_name, footer_date)
        
        renderer.render(painter)
        return True

    def update_pages_logic(self, crm_name):
        path = self.get_report_path()
        all_data = load_report_json(path)
        
        if crm_name not in all_data:
            all_data[crm_name] = {"pending": [], "recent": []}
            
        # Move pending to recent
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
            
            p_list = data["pending"]
            if p_list:
                try: p_list.sort(key=lambda x: int(x) if str(x).isdigit() else float('inf'))
                except: p_list.sort()
            
            p_pages = ", ".join(p_list) if p_list else "Completed"
            self.table.setItem(row, 1, QTableWidgetItem(p_pages))
            r_pages = ", ".join(data["recent"]) if data["recent"] else "None"
            self.table.setItem(row, 2, QTableWidgetItem(r_pages))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_report_data()