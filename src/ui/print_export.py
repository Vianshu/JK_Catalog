# print_export.py - Print and PDF Export functionality for Catalog

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QMessageBox,
    QScrollArea, QWidget, QFrame, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, QSize, QMarginsF, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QPainter, QPageSize, QPageLayout
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from src.ui.settings import load_crm_list

# Fixed A4 dimensions in mm (ISO standard)
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# Use screen DPI for rendering - printer will scale appropriately
# This ensures fonts look the same as on screen
SCREEN_DPI = 96


class PrintExportDialog(QDialog):
    """Dialog for print preview and PDF export."""
    
    def __init__(self, catalog_ui, parent=None, mode="both", page_list=None, renderer_callback=None, initial_crm=None):
        super().__init__(parent)
        self.catalog_ui = catalog_ui
        self.mode = mode
        self.page_list = page_list
        self.renderer_callback = renderer_callback
        self.initial_crm = initial_crm
        self.settings = QSettings("CatalogApp", "PrinterSettings")
        
        self.setWindowTitle("Print / Export Catalog")
        self.setMinimumSize(500, 400)
        
        # PROPER STYLING to fix visibility issues (Dark Mode)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #ffffff; font-size: 13px; }
            QGroupBox { font-weight: bold; color: #ffffff; border: 1px solid #555; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; }
            QCheckBox { color: #ffffff; spacing: 5px; }
            QSpinBox { background-color: #333333; color: #ffffff; padding: 4px; border: 1px solid #555; border-radius: 4px; }
            QComboBox { background-color: #333333; color: #ffffff; padding: 4px; border: 1px solid #555; border-radius: 4px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #333333; color: #ffffff; selection-background-color: #007bff; }
            QPushButton { background-color: #007bff; color: white; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton#BtnCancel { background-color: #555555; }
            QPushButton#BtnCancel:hover { background-color: #444444; }
        """)
        
        # Get company path for CRM list
        self.company_path = getattr(catalog_ui, 'company_path', '') or ''
        
        self.setup_ui()
        self.load_settings()
        
        # Set initial CRM if provided
        if self.initial_crm:
            idx = self.crm_combo.findText(self.initial_crm)
            if idx >= 0:
                self.crm_combo.setCurrentIndex(idx)
        
        # Apply Mode
        if self.mode == "pdf":
            self.btn_preview.setVisible(False)
            self.setWindowTitle("Export PDF")
        elif self.mode == "print":
            self.btn_pdf.setVisible(False)
            self.setWindowTitle("Print Catalog")
            
        self.update_page_info()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Page Range Section
        range_group = QGroupBox("Page Range")
        range_layout = QHBoxLayout(range_group)
        
        self.radio_all = QCheckBox("All Pages" if not self.page_list else f"All {len(self.page_list)} Pending Pages")
        self.radio_all.setChecked(True)
        # Disable radio if we are in page_list mode (force all pending)
        if self.page_list:
             self.radio_all.setEnabled(False)
             self.radio_all.setChecked(True)
        else:
             self.radio_all.stateChanged.connect(self.toggle_range)
        
        range_layout.addWidget(self.radio_all)
        
        range_layout.addWidget(QLabel("From:"))
        self.spin_from = QSpinBox()
        self.spin_from.setMinimum(1)
        self.spin_from.setEnabled(False)
        range_layout.addWidget(self.spin_from)
        
        range_layout.addWidget(QLabel("To:"))
        self.spin_to = QSpinBox()
        self.spin_to.setMinimum(1)
        self.spin_to.setEnabled(False)
        range_layout.addWidget(self.spin_to)
        
        range_layout.addStretch()
        layout.addWidget(range_group)
        
        # CRM Selection Section
        crm_group = QGroupBox("CRM Name (Footer)")
        crm_layout = QHBoxLayout(crm_group)
        
        crm_layout.addWidget(QLabel("Select CRM:"))
        self.crm_combo = QComboBox()
        self.crm_combo.setMinimumWidth(200)
        
        # Add default option
        self.crm_combo.addItem("CRM_NAME (Default)")
        
        # Load CRM list from company path
        crm_path = os.path.join(self.company_path, "crm_data.json") if self.company_path else "crm_data.json"
        crm_list = load_crm_list(crm_path)
        for crm in crm_list:
            self.crm_combo.addItem(crm)
        
        crm_layout.addWidget(self.crm_combo)
        crm_layout.addStretch()
        layout.addWidget(crm_group)
        
        # Options Section REMOVED (Empty)
        
        # Info Section
        info_frame = QFrame()
        info_frame.setObjectName("PrintInfoFrame")
        info_layout = QVBoxLayout(info_frame)
        
        self.lbl_info = QLabel("Total Pages: 0")
        self.lbl_info.setObjectName("PrintInfoLabel")
        info_layout.addWidget(self.lbl_info)
        
        self.lbl_size = QLabel("Output Size: A4 (210mm × 297mm)")
        info_layout.addWidget(self.lbl_size)
        
        layout.addWidget(info_frame)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_preview = QPushButton("🖨️ Print Preview")
        self.btn_preview.setFixedHeight(40)
        self.btn_preview.clicked.connect(self.show_print_preview)
        btn_layout.addWidget(self.btn_preview)
        
        self.btn_pdf = QPushButton("📄 Export PDF")
        self.btn_pdf.setFixedHeight(40)
        self.btn_pdf.clicked.connect(self.export_to_pdf)
        btn_layout.addWidget(self.btn_pdf)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("BtnCancel")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
    
    def toggle_range(self, state):
        """Enable/disable range spinboxes."""
        if self.page_list:
            # Always disabled in page list mode
            self.spin_from.setEnabled(False)
            self.spin_to.setEnabled(False)
        else:
            enabled = not self.radio_all.isChecked()
            self.spin_from.setEnabled(enabled)
            self.spin_to.setEnabled(enabled)
    
    def save_settings(self):
        """Persist current settings (CRM, Path, etc)."""
        self.settings.setValue("last_crm", self.crm_combo.currentText())
        
    def load_settings(self):
        """Load persisted settings."""
        last_crm = self.settings.value("last_crm", "")
        if last_crm:
            idx = self.crm_combo.findText(last_crm)
            if idx >= 0:
                self.crm_combo.setCurrentIndex(idx)
    
    def update_page_info(self):
        """Update page count info."""
        if self.page_list:
            total = len(self.page_list)
            self.lbl_info.setText(f"Total Pages: {total} (Pending)")
        elif hasattr(self.catalog_ui, 'all_pages_data') and self.catalog_ui.all_pages_data:
            total = len(self.catalog_ui.all_pages_data)
            self.spin_from.setMaximum(total)
            self.spin_to.setMaximum(total)
            self.spin_to.setValue(total)
            self.lbl_info.setText(f"Total Pages: {total}")
        else:
            self.lbl_info.setText("Total Pages: 0 (No data loaded)")
    
    def get_page_range(self):
        """Get list of page indices/identifiers to print/export."""
        self.save_settings() # Save settings when action starts
        
        if self.page_list:
            # In page list mode, return the list itself (or indices if they map to it)
            # The renderer_callback needs to know what to do with these items
            return self.page_list
            
        if not hasattr(self.catalog_ui, 'all_pages_data') or not self.catalog_ui.all_pages_data:
            return []
        
        total = len(self.catalog_ui.all_pages_data)
        
        if self.radio_all.isChecked():
            page_indices = list(range(total))
        else:
            start = self.spin_from.value() - 1  # 0-indexed
            end = self.spin_to.value()  # exclusive
            page_indices = list(range(start, min(end, total)))
        
        return page_indices
    
    def create_print_renderer(self):
        """Create a renderer configured for print output using screen DPI for consistency."""
        from src.ui.a4_renderer import A4PageRenderer
        renderer = A4PageRenderer()
        renderer.set_target_dpi(SCREEN_DPI)  # Use screen DPI so fonts match display
        return renderer
    
    def render_page_to_painter(self, painter, page_item, renderer):
        """Render a single page to the given painter.
           page_item: Index (int) for Catalog, or Serial (str) for Reports.
        """
        # Set footer - get CRM name from selection
        selected_crm = self.crm_combo.currentText()
        crm_name = "CRM_NAME" if selected_crm == "CRM_NAME (Default)" else selected_crm
        
        # --- Custom Callback Mode (Reports) ---
        if self.renderer_callback:
            return self.renderer_callback(painter, page_item, renderer, crm_name)
            
        # --- Default Catalog Logic ---
        page_index = page_item
        if page_index >= len(self.catalog_ui.all_pages_data):
            return False
        
        mg_sn, group_name, sg_sn, page_no, serial_no = self.catalog_ui.all_pages_data[page_index]
        
        # Set header
        renderer.set_header_data(group_name, serial_no)
        
        # Get products for this page
        products = self.catalog_ui.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        renderer.fill_products(products if products else [])
        
        footer_date = ""
        if products:
            from datetime import datetime
            max_dt_obj = None
            max_date_str = ""
            for p in products:
                p_data = p.get("data", {})
                p_date = p_data.get("max_update_date", "")
                if p_date:
                    try:
                        date_part = p_date.split(" ")[0]
                        dt = datetime.strptime(date_part, "%d-%m-%Y")
                        if max_dt_obj is None or dt > max_dt_obj:
                            max_dt_obj = dt
                            max_date_str = p_date
                    except:
                        pass
            if max_date_str:
                footer_date = self.catalog_ui.logic.get_nepali_date(max_date_str)
        
        renderer.set_footer_data(crm_name, footer_date)
        
        # Render the widget to painter
        renderer.render(painter)
        return True
    
    def show_print_preview(self):
        """Show print preview dialog with loading indicator."""
        page_indices = self.get_page_range()
        if not page_indices:
            QMessageBox.warning(self, "No Pages", "No pages available to print.")
            return
        
        # Show loading dialog
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        from PyQt6.QtCore import QTimer
        
        progress = QProgressDialog("Preparing catalog preview...", None, 0, len(page_indices), self)
        progress.setWindowTitle("Loading Preview")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()
        
        # Pre-calculate page data to check for issues
        valid_pages = []
        for i, idx in enumerate(page_indices):
            progress.setValue(i)
            progress.setLabelText(f"Preparing page {i+1} of {len(page_indices)}...")
            QApplication.processEvents()
            
            if progress.wasCanceled():
                return
            
            valid_pages.append(idx)
            # if idx < len(self.catalog_ui.all_pages_data):
            #    valid_pages.append(idx)
        
        progress.setValue(len(page_indices))
        progress.close()
        
        if not valid_pages:
            QMessageBox.warning(self, "No Valid Pages", "No valid pages to preview.")
            return
        
        # Create printer for preview
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        
        # Set A4 page size explicitly
        page_size = QPageSize(QPageSize.PageSizeId.A4)
        printer.setPageSize(page_size)
        
        # Set minimal margins
        margins = QMarginsF(0, 0, 0, 0)
        page_layout = QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins)
        printer.setPageLayout(page_layout)
        
        # Store page indices for the preview handler
        self._preview_pages = valid_pages
        
        # Create and show preview dialog
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle(f"Print Preview - Catalog ({len(valid_pages)} pages)")
        preview.resize(900, 700)
        preview.paintRequested.connect(self.handle_paint_request)
        preview.exec()
    
    def handle_paint_request(self, printer):
        """Handle the paint request from print preview."""
        painter = QPainter()
        if not painter.begin(printer):
            return
        
        page_indices = self._preview_pages
        renderer = self.create_print_renderer()
        
        # Use QProgressDialog for cancellation support
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        
        progress = QProgressDialog("Rendering Preview...", "Cancel", 0, len(page_indices), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
            
        for i, page_idx in enumerate(page_indices):
            if progress.wasCanceled():
                painter.end()
                renderer.deleteLater()
                return

            if i > 0:
                printer.newPage()
            
            # Scale to fit printer page
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            
            # Calculate scaling to fit A4 exactly
            scale_x = page_rect.width() / renderer.width()
            scale_y = page_rect.height() / renderer.height()
            scale = min(scale_x, scale_y)
            
            painter.save()
            painter.scale(scale, scale)
            
            self.render_page_to_painter(painter, page_idx, renderer)
            
            painter.restore()
            
            progress.setValue(i + 1)
            QApplication.processEvents()
        
        painter.end()
        renderer.deleteLater()
        progress.close()
    
    def export_to_pdf(self):
        """Export catalog to PDF file."""
        page_indices = self.get_page_range()
        if not page_indices:
            QMessageBox.warning(self, "No Pages", "No pages available to export.")
            return
        
        # Get save location
        default_name = "Catalog_Export.pdf"
        if hasattr(self.catalog_ui, 'company_path') and self.catalog_ui.company_path:
            folder_name = os.path.basename(self.catalog_ui.company_path)
            default_name = f"{folder_name}_Catalog.pdf"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save PDF",
            default_name,
            "PDF Files (*.pdf)"
        )
        
        if not file_path:
            return
            
        # Save Last Path
        try:
            folder = os.path.dirname(file_path)
            self.settings.setValue("last_export_dir", folder)
        except: pass
        
        # Ensure .pdf extension
        if not file_path.lower().endswith('.pdf'):
            file_path += '.pdf'
        
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        progress = QProgressDialog("Exporting PDF...", "Cancel", 0, len(page_indices), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        try:
            # Create PDF printer
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)
            
            # Set A4 page size explicitly
            page_size = QPageSize(QPageSize.PageSizeId.A4)
            printer.setPageSize(page_size)
            
            # Set minimal margins for full page usage
            margins = QMarginsF(0, 0, 0, 0)
            page_layout = QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins)
            printer.setPageLayout(page_layout)
            
            # Create painter
            painter = QPainter()
            if not painter.begin(printer):
                raise Exception("Failed to initialize PDF writer")
            
            renderer = self.create_print_renderer()
            
            for i, page_idx in enumerate(page_indices):
                if progress.wasCanceled():
                    painter.end()
                    renderer.deleteLater()
                    try:
                         if os.path.exists(file_path): os.remove(file_path)
                    except: pass
                    return

                if i > 0:
                    printer.newPage()
                
                # Scale to fit printer page
                page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                
                # Calculate scaling to fit A4 exactly
                scale_x = page_rect.width() / renderer.width()
                scale_y = page_rect.height() / renderer.height()
                scale = min(scale_x, scale_y)
                
                painter.save()
                painter.scale(scale, scale)
                
                self.render_page_to_painter(painter, page_idx, renderer)
                
                painter.restore()
                
                progress.setValue(i + 1)
                QApplication.processEvents()
            
            painter.end()
            renderer.deleteLater()
            progress.close()
            
            QMessageBox.information(
                self, 
                "Export Complete", 
                f"PDF saved successfully!\n\nLocation: {file_path}\nPages: {len(page_indices)}"
            )
            
            # Offer to open the file
            reply = QMessageBox.question(
                self,
                "Open PDF?",
                "Would you like to open the exported PDF?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(file_path)
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Export Failed", f"Failed to export PDF:\n{e}")
