# print_export.py - Print and PDF Export functionality for Catalog

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QMessageBox,
    QScrollArea, QWidget, QFrame, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, QSize, QMarginsF, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QPageSize, QPageLayout
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog

# Fixed A4 dimensions in mm (ISO standard)
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# Print DPI for consistent output
PRINT_DPI = 300


class PrintExportDialog(QDialog):
    """Dialog for print preview and PDF export."""
    
    def __init__(self, catalog_ui, parent=None):
        super().__init__(parent)
        self.catalog_ui = catalog_ui
        self.setWindowTitle("Print / Export Catalog")
        self.setMinimumSize(500, 400)
        
        self.setup_ui()
        self.update_page_info()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Page Range Section
        range_group = QGroupBox("Page Range")
        range_layout = QHBoxLayout(range_group)
        
        self.radio_all = QCheckBox("All Pages")
        self.radio_all.setChecked(True)
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
        
        # Options Section
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        self.chk_skip_empty = QCheckBox("Skip Empty Pages")
        self.chk_skip_empty.setChecked(True)
        options_layout.addWidget(self.chk_skip_empty)
        
        layout.addWidget(options_group)
        
        # Info Section
        info_frame = QFrame()
        info_frame.setStyleSheet("background: #f0f0f0; padding: 10px; border-radius: 5px;")
        info_layout = QVBoxLayout(info_frame)
        
        self.lbl_info = QLabel("Total Pages: 0")
        self.lbl_info.setStyleSheet("font-size: 14pt; font-weight: bold;")
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
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
    
    def toggle_range(self, state):
        """Enable/disable range spinboxes."""
        enabled = not self.radio_all.isChecked()
        self.spin_from.setEnabled(enabled)
        self.spin_to.setEnabled(enabled)
    
    def update_page_info(self):
        """Update page count info."""
        if hasattr(self.catalog_ui, 'all_pages_data') and self.catalog_ui.all_pages_data:
            total = len(self.catalog_ui.all_pages_data)
            self.spin_from.setMaximum(total)
            self.spin_to.setMaximum(total)
            self.spin_to.setValue(total)
            self.lbl_info.setText(f"Total Pages: {total}")
        else:
            self.lbl_info.setText("Total Pages: 0 (No data loaded)")
    
    def get_page_range(self):
        """Get list of page indices to print/export."""
        if not hasattr(self.catalog_ui, 'all_pages_data') or not self.catalog_ui.all_pages_data:
            return []
        
        total = len(self.catalog_ui.all_pages_data)
        
        if self.radio_all.isChecked():
            page_indices = list(range(total))
        else:
            start = self.spin_from.value() - 1  # 0-indexed
            end = self.spin_to.value()  # exclusive
            page_indices = list(range(start, min(end, total)))
        
        # Filter empty pages if option checked
        if self.chk_skip_empty.isChecked():
            filtered = []
            for idx in page_indices:
                if idx < len(self.catalog_ui.all_pages_data):
                    _, group_name, sg_sn, page_no, _ = self.catalog_ui.all_pages_data[idx]
                    items = self.catalog_ui.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
                    if items:  # Only include pages with content
                        filtered.append(idx)
            page_indices = filtered
        
        return page_indices
    
    def create_print_renderer(self):
        """Create a renderer configured for print output at 300 DPI."""
        from src.ui.a4_renderer import A4PageRenderer
        renderer = A4PageRenderer()
        renderer.set_target_dpi(PRINT_DPI)
        return renderer
    
    def render_page_to_painter(self, painter, page_index, renderer):
        """Render a single page to the given painter."""
        if page_index >= len(self.catalog_ui.all_pages_data):
            return False
        
        mg_sn, group_name, sg_sn, page_no, serial_no = self.catalog_ui.all_pages_data[page_index]
        
        # Set header
        renderer.set_header_data(group_name, serial_no)
        
        # Get products for this page
        products = self.catalog_ui.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        renderer.fill_products(products if products else [])
        
        # Set footer
        crm_name = "CRM_NAME"  # TODO: Get from settings
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
        """Show print preview dialog."""
        page_indices = self.get_page_range()
        if not page_indices:
            QMessageBox.warning(self, "No Pages", "No pages available to print.")
            return
        
        # Create printer for preview
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(PRINT_DPI)
        
        # Set A4 page size explicitly
        page_size = QPageSize(QPageSize.PageSizeId.A4)
        printer.setPageSize(page_size)
        
        # Set minimal margins
        margins = QMarginsF(0, 0, 0, 0)
        page_layout = QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins)
        printer.setPageLayout(page_layout)
        
        # Store page indices for the preview handler
        self._preview_pages = page_indices
        
        # Create and show preview dialog
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("Print Preview - Catalog")
        preview.paintRequested.connect(self.handle_paint_request)
        preview.exec()
    
    def handle_paint_request(self, printer):
        """Handle the paint request from print preview."""
        painter = QPainter()
        if not painter.begin(printer):
            return
        
        page_indices = self._preview_pages
        renderer = self.create_print_renderer()
        
        for i, page_idx in enumerate(page_indices):
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
        
        painter.end()
        renderer.deleteLater()
    
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
        
        # Ensure .pdf extension
        if not file_path.lower().endswith('.pdf'):
            file_path += '.pdf'
        
        self.progress.setVisible(True)
        self.progress.setMaximum(len(page_indices))
        self.progress.setValue(0)
        
        try:
            # Create PDF printer
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)
            printer.setResolution(PRINT_DPI)
            
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
                
                self.progress.setValue(i + 1)
                # Allow UI to update
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
            
            painter.end()
            renderer.deleteLater()
            
            self.progress.setVisible(False)
            
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
            self.progress.setVisible(False)
            QMessageBox.critical(self, "Export Failed", f"Failed to export PDF:\n{e}")
