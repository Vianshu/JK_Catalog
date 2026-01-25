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

# Use screen DPI for consistency with full catalog
SCREEN_DPI = 96

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

        layout.addWidget(QLabel("<b>Pending Pages (Serial Nos):</b>"))
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
        # Default to empty list, not 1-12
        pending = self.report_data.get(crm_name, {}).get("pending", [])
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
        
    def ensure_logic_init(self):
        if not self.current_company_path: return False
        
        catalog_db = os.path.join(self.current_company_path, "catalog.db")
        final_db = os.path.join(self.current_company_path, "final_data.db")
        
        if not self.logic:
            self.logic = CatalogLogic(catalog_db) # init with catalog db as primary for now
            self.logic.set_paths(catalog_db, final_db)
        else:
            self.logic.set_paths(catalog_db, final_db)
        return True

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
        if not self.ensure_logic_init():
            QMessageBox.warning(self, "Error", "Please load a company first.")
            return

        current_report_data = load_report_json(self.get_report_path())
        crm_path = os.path.join(self.current_company_path, "crm_data.json") if self.current_company_path else "crm_data.json"
        
        dlg = PrintDownloadDialog(mode=mode, parent=self, report_data=current_report_data, crm_path=crm_path)
        
        if dlg.exec():
            crm_name = dlg.crm_combo.currentText()
            
            # Get pending pages and sort them by serial number
            pending_serials = current_report_data.get(crm_name, {}).get("pending", [])
            if not pending_serials:
                QMessageBox.information(self, "Info", "No pending pages to process.")
                return
            
            # Sort pages by serial number (numeric order)
            try:
                pending_serials = sorted(pending_serials, key=lambda x: int(x) if str(x).isdigit() else float('inf'))
            except:
                pending_serials = sorted(pending_serials)  # Fallback to string sort

            success = False
            if mode == "Print":
                self._current_crm_name = crm_name  # Store for print preview
                success = self.handle_actual_print(pending_serials)
            elif mode == "Download":
                if not self.download_path:
                    self.set_location()
                if self.download_path:
                    success = self.handle_actual_download(pending_serials, crm_name)
            
            if success:
                self.update_pages_logic(crm_name)
    
    def render_page_to_painter(self, painter, serial_no, renderer):
        """Render a single page by serial number."""
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
        
        # Set footer (simplified)
        renderer.set_footer_data("CRM_NAME", "") # Todo pass real CRM Name?
        
        renderer.render(painter)
        return True

    def handle_actual_print(self, serial_numbers):
        """Show print preview dialog with the pending pages, similar to catalog tab."""
        
        # Store serial numbers for the paint callback
        self._print_serial_numbers = serial_numbers
        self._print_crm_name = getattr(self, '_current_crm_name', 'CRM_NAME')
        
        # Create printer with A4 settings
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        page_size = QPageSize(QPageSize.PageSizeId.A4)
        printer.setPageSize(page_size)
        margins = QMarginsF(0, 0, 0, 0)
        printer.setPageLayout(QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins))
        
        # Create print preview dialog
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("Print Preview - Pending Pages")
        preview.resize(900, 700)
        
        # Connect paint request
        preview.paintRequested.connect(self._handle_preview_paint)
        
        # Show preview - user can print from there
        if preview.exec():
            return True
        return False
    
    def _handle_preview_paint(self, printer):
        """Paint callback for print preview - renders all pending pages."""
        serial_numbers = getattr(self, '_print_serial_numbers', [])
        crm_name = getattr(self, '_print_crm_name', 'CRM_NAME')
        
        if not serial_numbers:
            return
        
        painter = QPainter()
        if not painter.begin(printer):
            return
        
        renderer = A4PageRenderer()
        renderer.set_target_dpi(SCREEN_DPI)
        
        # Add Progress Dialog
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        progress = QProgressDialog("Rendering Preview...", None, 0, len(serial_numbers), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        for i, serial in enumerate(serial_numbers):
            progress.setValue(i)
            QApplication.processEvents()
            
            if i > 0:
                printer.newPage()
            
            # Calculate scaling
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            scale_x = page_rect.width() / renderer.width()
            scale_y = page_rect.height() / renderer.height()
            scale = min(scale_x, scale_y)
            
            painter.save()
            painter.scale(scale, scale)
            
            # Render the page
            page_info = self.logic.get_page_info_by_serial(serial)
            if page_info:
                group_name = page_info["group_name"]
                sg_sn = page_info["sg_sn"]
                page_no = page_info["page_no"]
                
                renderer.set_header_data(group_name, serial)
                products = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
                renderer.fill_products(products if products else [])
                renderer.set_footer_data(crm_name, "")
                renderer.render(painter)
            
            painter.restore()
        
        painter.end()

    def handle_actual_download(self, serial_numbers, crm_name):
        filename = f"{crm_name}_Update.pdf"
        file_path = os.path.join(self.download_path, filename)
        
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)
            
            # Set A4 properties
            page_size = QPageSize(QPageSize.PageSizeId.A4)
            printer.setPageSize(page_size)
            margins = QMarginsF(0, 0, 0, 0)
            printer.setPageLayout(QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins))
            
            painter = QPainter()
            if not painter.begin(printer):
                 return False

            renderer = A4PageRenderer()
            renderer.set_target_dpi(96)

            progress = QProgressDialog("Exporting Pages...", "Cancel", 0, len(serial_numbers), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            
            for i, serial in enumerate(serial_numbers):
                if progress.wasCanceled():
                    painter.end()
                    return False
                    
                if i > 0: printer.newPage()
                
                # Scaling logic
                page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                scale_x = page_rect.width() / renderer.width()
                scale_y = page_rect.height() / renderer.height()
                scale = min(scale_x, scale_y)
                
                painter.save()
                painter.scale(scale, scale)
                self.render_page_to_painter(painter, serial, renderer)
                painter.restore()
                
                progress.setValue(i + 1)
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
            
            painter.end()
            QMessageBox.information(self, "Export Complete", f"Saved to {file_path}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
            return False

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
            p_pages = ", ".join(data["pending"]) if data["pending"] else "Completed"
            self.table.setItem(row, 1, QTableWidgetItem(p_pages))
            r_pages = ", ".join(data["recent"]) if data["recent"] else "None"
            self.table.setItem(row, 2, QTableWidgetItem(r_pages))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_report_data()