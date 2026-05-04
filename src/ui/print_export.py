# print_export.py - Print and PDF Export functionality for Catalog

import os
import tempfile
import fitz
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QMessageBox,
    QScrollArea, QWidget, QFrame, QComboBox, QGroupBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QSize, QMarginsF, QSettings, QEvent
from PyQt6.QtGui import QPainter, QPageSize, QPageLayout, QImage
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtPdf import QPdfDocument
from src.ui.settings import load_crm_list
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# Fixed A4 dimensions in mm (ISO standard)
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# ── Rendering & Margin Strategy ──────────────────────────────────
# A4PageRenderer handles margins internally (3mm on each side).
# The content area is 204×291mm within the 210×297mm A4 page.
#
# QPrinter margins are set to 0 for all modes — the renderer's own
# margins provide the safety zone for printer non-printable areas.
# This ensures no double-margin and consistent output across
# PDF export, print preview, and direct print.
#
# ONE path (_render_pages) handles all modes.  No manual offsets.
# ─────────────────────────────────────────────────────────────────
RENDER_DPI = 96                 # widget layout DPI (must match screen)
PDF_MARGIN_MM = 0.0             # zero — renderer has 3mm internal margins


class ZoomablePdfView(QPdfView):
    """Custom PDF view that supports smooth scrolling/pinch zoom."""
    def wheelEvent(self, event):
        # Windows Trackpad Pinch usually sends Ctrl + WheelEvent
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                self.setZoomMode(QPdfView.ZoomMode.Custom)
                # 1.05 gives a very smooth, fine-grained zoom for trackpads/wheels
                factor = 1.05 if delta > 0 else (1 / 1.05)
                self.setZoomFactor(self.zoomFactor() * factor)
            event.accept()
        else:
            super().wheelEvent(event)
            
    def viewportEvent(self, event):
        # Native macOS/Windows precision touchpad pinch gesture
        if event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                self.setZoomMode(QPdfView.ZoomMode.Custom)
                # event.value() is the scale delta
                factor = 1.0 + event.value()
                if factor > 0:
                    self.setZoomFactor(self.zoomFactor() * factor)
                return True
        return super().viewportEvent(event)


class PDFPreviewDialog(QDialog):
    def __init__(self, pdf_path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.setWindowTitle("Print Preview")
        self.resize(1000, 800)
        
        # Main Layout is Horizontal
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 1. Left side: PDF Viewer (Multi-page scrollable)
        self.pdf_view = ZoomablePdfView(self)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_document = QPdfDocument(self)
        self.pdf_view.setDocument(self.pdf_document)
        
        self.layout.addWidget(self.pdf_view, stretch=1)
        
        # 2. Right side: Vertical Toolbar
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setStyleSheet("background-color: #2b2b2b; border-left: 1px solid #444;")
        self.sidebar_frame.setFixedWidth(160)
        self.sidebar = QVBoxLayout(self.sidebar_frame)
        self.sidebar.setContentsMargins(10, 15, 10, 15)
        self.sidebar.setSpacing(10)
        
        # Primary Action Buttons
        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setStyleSheet("background-color: #28a745; color: white; padding: 10px; font-weight: bold; border-radius: 4px; font-size: 14px;")
        self.btn_print.clicked.connect(self.print_document)
        self.sidebar.addWidget(self.btn_print)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet("background-color: #dc3545; color: white; padding: 8px; font-weight: bold; border-radius: 4px;")
        self.btn_close.clicked.connect(self.reject)
        self.sidebar.addWidget(self.btn_close)
        
        # Spacer between actions and zoom controls
        self.sidebar.addSpacing(20)
        
        # Zoom Controls Label
        zoom_lbl = QLabel("VIEW CONTROLS")
        zoom_lbl.setStyleSheet("color: #888; font-size: 11px; font-weight: bold; margin-bottom: 5px;")
        self.sidebar.addWidget(zoom_lbl)
        
        # Zoom Buttons
        btn_style = "background-color: #444; color: white; padding: 6px; border-radius: 4px; text-align: left; padding-left: 10px;"
        
        self.btn_zoom_in = QPushButton("🔍 Zoom In")
        self.btn_zoom_in.setStyleSheet(btn_style)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.sidebar.addWidget(self.btn_zoom_in)
        
        self.btn_zoom_out = QPushButton("🔎 Zoom Out")
        self.btn_zoom_out.setStyleSheet(btn_style)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.sidebar.addWidget(self.btn_zoom_out)
        
        self.btn_fit_width = QPushButton("↔️ Fit Width")
        self.btn_fit_width.setStyleSheet(btn_style)
        self.btn_fit_width.clicked.connect(self.fit_width)
        self.sidebar.addWidget(self.btn_fit_width)
        
        # Push everything to the top
        self.sidebar.addStretch()
        
        self.layout.addWidget(self.sidebar_frame)
        
        self._load_document()
        
    def zoom_in(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.1)
        
    def zoom_out(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() / 1.1)
        
    def fit_width(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        
    def _load_document(self):
        self.pdf_document.load(self.pdf_path)
        
    def print_document(self):
        """Print the PDF document on the MAIN thread.

        QPainter + QPrinter are NOT thread-safe in Qt.  Using them from a
        QThread causes the Windows print spooler to deadlock (the "Not
        Responding" freeze).  We run the entire paint loop on the GUI
        thread, calling processEvents() after each page to keep the
        progress dialog responsive.
        """
        from PyQt6.QtWidgets import QApplication

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        # Crucial on Windows: release file lock so PyMuPDF can open it
        self.pdf_document.close()

        doc = None
        try:
            # Enforce full page mapping so hardware margins symmetrically trim the image
            printer.setFullPage(True)

            doc = fitz.open(self.pdf_path)
            total = len(doc)

            progress = QProgressDialog("Starting print job...", "Cancel", 0, total, self)
            progress.setWindowTitle("Printing")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()

            painter = QPainter()
            if not painter.begin(printer):
                progress.close()
                doc.close()
                QMessageBox.critical(self, "Print Error",
                                     "Could not initialize QPainter on QPrinter.")
                self._load_document()
                return

            # 300 DPI for high-quality text rasterization
            zoom_matrix = fitz.Matrix(300 / 72, 300 / 72)
            cancelled = False

            for i in range(total):
                if progress.wasCanceled():
                    cancelled = True
                    break

                page = doc[i]
                pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)

                # Convert raw fitz bytes directly to QImage
                img = QImage(pix.samples, pix.width, pix.height,
                             pix.stride, QImage.Format.Format_RGB888)

                # Draw the image perfectly onto the physical paper bounds
                painter.drawImage(
                    printer.paperRect(QPrinter.Unit.DevicePixel), img)

                if i < total - 1:
                    printer.newPage()

                progress.setValue(i + 1)
                progress.setLabelText(f"Printing page {i + 1} of {total}...")
                QApplication.processEvents()

            painter.end()
            doc.close()
            doc = None
            progress.close()

            if not cancelled:
                logger.info("Print job completed successfully")
                QMessageBox.information(self, "Success",
                                        "Document sent to printer successfully.")
            else:
                logger.info("Print job cancelled by user")

        except Exception as e:
            logger.error(f"Print job failed: {e}", exc_info=True)
            if doc:
                doc.close()
            QMessageBox.critical(self, "Print Error",
                                 f"Failed to print document:\n{e}")

        # Re-lock and load document for viewing
        self._load_document()


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
        self.company_path = getattr(catalog_ui, 'company_path', '') or getattr(catalog_ui, 'current_company_path', '') or ''
        
        self.setup_ui()
        self.load_settings()
        
        # Set initial CRM if provided
        if self.initial_crm:
            idx = self.crm_combo.findText(self.initial_crm)
            if idx >= 0:
                self.crm_combo.setCurrentIndex(idx)
            if hasattr(self, 'crm_group'):
                self.crm_group.setVisible(False)
        
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
        self.crm_group = QGroupBox("CRM Name (Footer)")
        crm_layout = QHBoxLayout(self.crm_group)
        
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
        layout.addWidget(self.crm_group)
        
        # Options Section REMOVED (Empty)
        
        # Info Section
        info_frame = QFrame()
        info_frame.setObjectName("PrintInfoFrame")
        info_layout = QVBoxLayout(info_frame)
        
        self.lbl_info = QLabel("Total Pages: 0")
        self.lbl_info.setObjectName("PrintInfoLabel")
        info_layout.addWidget(self.lbl_info)
        
        self.lbl_size = QLabel("Output Size: A4 (210mm x 297mm) | Margins: 3mm")
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
        renderer.set_target_dpi(RENDER_DPI)
            
        # Calculate and set the company prefix for the top-left header
        co_path = getattr(self.catalog_ui, 'company_path', "") or getattr(self.catalog_ui, 'current_company_path', "")
        if co_path:
            import json, os
            folder_name = os.path.basename(co_path)
            prefix = folder_name[:3].upper() if len(folder_name) >= 3 else folder_name.upper()
            info_file = os.path.join(co_path, "company_info.json")
            if os.path.exists(info_file):
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        info_data = json.load(f)
                        if info_data and "display_name" in info_data and info_data["display_name"].strip():
                            name = info_data["display_name"].strip()
                            prefix = name[:3].upper() if len(name) >= 3 else name.upper()
                except:
                    pass
            renderer._company_prefix = prefix
            
        return renderer
    
    def render_page_to_painter(self, painter, page_item, renderer, skip_render=False):
        """Render a single page to the given painter.
           page_item: Index (int) for Catalog, or Serial (str) for Reports.
           skip_render: If True, populate renderer data but don't paint
                        (caller will handle rendering, e.g. via QPixmap).
        """
        # Set footer - get CRM name from selection
        selected_crm = self.crm_combo.currentText()
        crm_name = "" if selected_crm == "CRM_NAME (Default)" else selected_crm
        
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
        
        # Footer Date (using centralized date_utils)
        from src.utils.date_utils import get_footer_date
        footer_date = get_footer_date(products, self.catalog_ui.logic)
        
        renderer.set_footer_data(crm_name, footer_date)
        
        # Render the widget to painter (unless caller handles it)
        if not skip_render and painter is not None:
            renderer.render(painter)
        return True

    def _prewarm_image_cache(self, page_indices):
        """Pre-load all product images into PixmapCache before rendering.
        This avoids per-page disk I/O during the rendering loop."""
        from src.ui.a4_renderer import PixmapCache
        try:
            for page_idx in page_indices:
                if page_idx >= len(self.catalog_ui.all_pages_data):
                    continue
                mg_sn, group_name, sg_sn, page_no, serial_no = self.catalog_ui.all_pages_data[page_idx]
                products = self.catalog_ui.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
                if not products:
                    continue
                for it in products:
                    prod = it.get("data") or it
                    img_path = prod.get("image_path", "")
                    if img_path and os.path.exists(img_path):
                        # Trigger cache load at a reasonable size
                        PixmapCache.get(img_path, 200, 200)
        except Exception:
            pass  # Non-critical — images will load on demand anyway

    def _render_pages(self, painter, printer, page_indices):
        """Unified rendering loop for PDF, print preview, and direct print.

        Performance optimizations:
          - Image cache is pre-warmed before the loop
          - Vector text rendering (sharp at any zoom)
          - processEvents batched every 5 pages
        """
        renderer = self.create_print_renderer()

        from PyQt6.QtWidgets import QProgressDialog, QApplication

        # Pre-warm image cache (loads all product images before rendering)
        self._prewarm_image_cache(page_indices)

        progress = QProgressDialog("Exporting PDF...", "Cancel", 0, len(page_indices), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        
        # PDF mode: no hardware margins, pageRect is perfect.
        target_w = page_rect.width()
        target_h = page_rect.height()

        scale_x = target_w / renderer.width()
        scale_y = target_h / renderer.height()
        scale = min(scale_x, scale_y)

        actual_w = renderer.width() * scale
        actual_h = renderer.height() * scale
        
        center_x = (target_w - actual_w) / 2.0
        center_y = (target_h - actual_h) / 2.0

        total = len(page_indices)
        for i, page_idx in enumerate(page_indices):
            if progress.wasCanceled():
                painter.end()
                renderer.deleteLater()
                progress.close()
                return False

            if i > 0:
                printer.newPage()

            # Populate the renderer with this page's data
            self.render_page_to_painter(painter, page_idx, renderer, skip_render=True)

            # Direct render (PDF — vector text, sharp at any zoom)
            painter.save()
            painter.translate(center_x, center_y)
            painter.scale(scale, scale)
            renderer.render(painter)
            painter.restore()

            progress.setValue(i + 1)
            # Batch processEvents every 5 pages for speed
            if i % 5 == 0 or i == total - 1:
                QApplication.processEvents()

        renderer.deleteLater()
        progress.close()
        return True

    def _render_to_printer(self, printer: QPrinter, page_indices: list):
        """Shared logic to strictly render standard vector PDF to a given QPrinter."""
        page_size = QPageSize(QPageSize.PageSizeId.A4)
        margins = QMarginsF(PDF_MARGIN_MM, PDF_MARGIN_MM, PDF_MARGIN_MM, PDF_MARGIN_MM)
        page_layout = QPageLayout(page_size, QPageLayout.Orientation.Portrait, margins, QPageLayout.Unit.Millimeter)
        printer.setPageLayout(page_layout)
        
        painter = QPainter()
        if not painter.begin(printer):
            raise Exception("Failed to initialize PDF painter.")
            
        ok = self._render_pages(painter, printer, page_indices)
        painter.end()
        return ok

    def show_print_preview(self):
        """Triggered by the Preview/Print button. Shows internal PDF viewer."""
        page_indices = self.get_page_range()
        if not page_indices:
            QMessageBox.warning(self, "No Pages", "No pages available to print.")
            return

        selected_crm = self.crm_combo.currentText()
        logger.info(f"Print preview started: pages={len(page_indices)}, crm='{selected_crm}'")
            
        temp_dir = tempfile.gettempdir()
        temp_pdf = os.path.join(temp_dir, "jk_catalog_temp_print.pdf")
        
        try:
            printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(temp_pdf)
            
            ok = self._render_to_printer(printer, page_indices)
            if not ok:
                try:
                    if os.path.exists(temp_pdf): os.remove(temp_pdf)
                except: pass
                self.reject()
                return
                
            # Open the custom preview dialog
            dialog = PDFPreviewDialog(temp_pdf, self)
            dialog.exec()
            
            # Clean up when closed
            try:
                if os.path.exists(temp_pdf): os.remove(temp_pdf)
            except: pass
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Print Error", f"Failed to generate print document:\n{str(e)}")
    
    # ─── PDF Export ─────────────────────────────────────────────────
    def export_to_pdf(self):
        """Export catalog to PDF file."""
        page_indices = self.get_page_range()
        if not page_indices:
            QMessageBox.warning(self, "No Pages", "No pages available to export.")
            return

        logger.info(f"PDF export initiated: pages={len(page_indices)}")
        
        # Generate File Name Format
        import datetime
        now = datetime.datetime.now()
        date_str = now.strftime("%d-%m")
        time_str = now.strftime("%H-%M-%S")
        
        crm = self.crm_combo.currentText()
        if crm == "CRM_NAME (Default)": crm = "DefaultCRM"
        
        # Determine Company Prefix
        co_path = getattr(self.catalog_ui, 'company_path', "") or getattr(self.catalog_ui, 'current_company_path', "")
        prefix = "CAT"
        if co_path:
            base = os.path.basename(co_path)
            prefix = base[:3].upper() if len(base) >= 3 else base.upper()
            
        default_name = f"{prefix}_{crm}_{date_str}_{time_str}.pdf"
        file_path = ""
        
        # Check download directory bypass
        download_dir = getattr(self.catalog_ui, 'download_path', "")
        if download_dir and os.path.exists(download_dir):
            file_path = os.path.join(download_dir, default_name)
        else:
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
        
        try:
            printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)

            ok = self._render_to_printer(printer, page_indices)
            
            if not ok:
                # Cancelled
                try:
                    if os.path.exists(file_path): os.remove(file_path)
                except: pass
                self.reject()
                return
            
            QMessageBox.information(
                self, 
                "Export Complete", 
                f"PDF saved successfully!\n\nLocation: {file_path}\nPages: {len(page_indices)}"
            )
            logger.info(f"PDF export completed: path='{file_path}', pages={len(page_indices)}, crm='{crm}'")
            
            # Offer to open the file
            reply = QMessageBox.question(
                self,
                "Open PDF?",
                "Would you like to open the exported PDF?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                os.startfile(file_path)
            
            # Signal success to parent
            self.accept()
            
        except Exception as e:
            logger.error(f"PDF export failed: path='{file_path}', error={e}", exc_info=True)
            QMessageBox.critical(self, "Export Failed", f"Failed to export PDF:\n{e}")
