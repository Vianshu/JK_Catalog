import sys
import sqlite3
import os  # Added global import
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, 
    QPushButton, QLineEdit, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QGridLayout, QMessageBox, QScrollArea, QSizePolicy,
    QStyle, QGroupBox
)
from PyQt6.QtCore import Qt, QMarginsF, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPixmap, QPageSize, QPageLayout, QPainter
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
from src.logic.catalog_logic import CatalogLogic
from src.ui.a4_renderer import A4PageRenderer
from src.ui.settings import EmptyPagesDialog, add_pages_to_all_crms
from src.ui.print_export import PrintExportDialog
from src.utils.path_utils import get_data_file_path
import sqlite3
import datetime


class CatalogBuildWorker(QThread):
    """Background worker for catalog building.
    Performs all heavy DB operations off the main thread."""
    progress_update = pyqtSignal(int, str)  # (step_number, step_label)
    build_finished = pyqtSignal(dict)       # {success, affected_count, crm_updated, changed_pages, error}
    
    def __init__(self, logic, company_path=None):
        super().__init__()
        self.logic = logic
        self.company_path = company_path
    
    def run(self):
        try:
            # Step 1: Sync pages
            self.progress_update.emit(1, "Step 1/5: Syncing pages...")
            self.logic.sync_pages_with_content()
            
            # Step 2: Detect changes
            self.progress_update.emit(2, "Step 2/5: Detecting changes...")
            changed_pages = self.logic.detect_changed_pages()
            
            affected_count = len(changed_pages) if changed_pages else 0
            crm_updated = 0
            
            # Step 3: Update CRMs
            self.progress_update.emit(3, "Step 3/5: Updating CRMs...")
            if changed_pages and self.company_path:
                crm_updated = add_pages_to_all_crms(list(changed_pages), self.company_path)
            
            # Step 4: Save snapshots
            self.progress_update.emit(4, "Step 4/5: Saving snapshots...")
            self.logic.save_all_page_snapshots()
            
            # Step 5: Finalize
            self.progress_update.emit(5, "Step 5/5: Finalizing...")
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            self.logic.save_last_build_date(now)
            self.logic.invalidate_cache()
            
            self.build_finished.emit({
                "success": True,
                "affected_count": affected_count,
                "crm_updated": crm_updated,
                "changed_pages": list(changed_pages) if changed_pages else [],
                "error": None
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.build_finished.emit({
                "success": False,
                "affected_count": 0,
                "crm_updated": 0,
                "changed_pages": [],
                "error": str(e)
            })


class FullCatalogUI(QWidget):
    def __init__(self):
        super().__init__()
        # Use path utility for EXE compatibility
        db_path = get_data_file_path("super_master.db")
        # Ensure Logic gets correct DB path
        self.logic = CatalogLogic(db_path)
        
        self.catalog_db_path = None
        self.final_db_path = None
        
        self.expanded_groups = {}
        self.current_page_index = 0
        self.all_pages_data = []
        
        self.setup_ui()
        self.load_index_data()
        self.connect_signals()
        
        try:
            with open("ui_interaction.log", "w") as f: f.write("FullCatalog UI Init - Connections Complete\n")
        except: pass

        
    def set_company_path(self, company_path):
        self.company_path = company_path
        self.catalog_db_path = os.path.join(self.company_path, "catalog.db")
        self.final_db_path = os.path.join(self.company_path, "final_data.db")
        
        
        # Pass to Logic
        self.logic.set_paths(self.catalog_db_path, self.final_db_path)
        
        # Init DB
        self.init_catalog_db()
        self.refresh_catalog_data()
        
        folder_name = os.path.basename(self.company_path)
        prefix = folder_name[:3].upper()
        if hasattr(self, 'lbl_comp_code'): self.lbl_comp_code.setText(prefix)

    def init_catalog_db(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS catalog_pages (id INTEGER PRIMARY KEY AUTOINCREMENT, mg_sn INTEGER, group_name TEXT, sg_sn INTEGER, page_no INTEGER, serial_no INTEGER, is_printable INTEGER DEFAULT 1)")
        try: cursor.execute("ALTER TABLE catalog_pages ADD COLUMN mg_sn INTEGER"); 
        except: pass
        try: cursor.execute("ALTER TABLE catalog_pages ADD COLUMN is_printable INTEGER DEFAULT 1"); 
        except: pass
        conn.commit(); conn.close()
        
    def rebuild_serial_numbers(self):
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM catalog_pages ORDER BY CAST(mg_sn AS INTEGER), CAST(sg_sn AS INTEGER), CAST(page_no AS INTEGER)")
        rows = cursor.fetchall()
        for idx, (rid,) in enumerate(rows, 1):
            cursor.execute("UPDATE catalog_pages SET serial_no=? WHERE id=?", (idx, rid))
        conn.commit(); conn.close()
    
    def connect_signals(self):
        # Index Table - Use only cellClicked (not itemClicked to avoid double-fire)
        self.index_table.cellClicked.connect(self.handle_cell_click)
        
        # Navigation
        self.btn_next.clicked.connect(self.next_page)
        self.btn_prev.clicked.connect(self.prev_page)
        self.page_input.returnPressed.connect(self.go_to_page)
        
        # Page Management
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.btn_check_empty.clicked.connect(self.check_empty_pages)
        
        # Build & Export
        self.btn_build.clicked.connect(self.build_catalog)
        self.btn_export.clicked.connect(self.export_pdf)
        self.btn_print.clicked.connect(self.handle_direct_print)
        self.btn_reshuffle.clicked.connect(self.reshuffle_catalog)
        
        # Length change from right-click context menu
        self.renderer.length_changed.connect(self.handle_length_change)
    
    def handle_length_change(self, product_name, new_length):
        """Handle product size change from context menu."""
        if not self.final_db_path:
            return
        
        try:
            import datetime
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            
            conn = sqlite3.connect(self.final_db_path)
            cursor = conn.cursor()
            
            # Update length AND Update_date in catalog table
            cursor.execute("""
                UPDATE catalog SET [Lenth] = ?, [Update_date] = ?
                WHERE [Product Name] = ? OR [Item_Name] = ?
            """, (str(new_length), now, product_name, product_name))
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            # Invalidate cache after data change
            self.logic.invalidate_cache()
            
            # Refresh current page to show updated layout
            self.refresh_catalog_data()
            
        except Exception as e:
            pass  # Silently handle errors
    
    def go_to_page(self):
        """Navigate to global page number entered in the input field."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
        
        try:
            target_page = int(self.page_input.text())
        except ValueError:
            return
        
        total_pages = len(self.all_pages_data)
        
        # Navigate to global page (1-indexed)
        if 1 <= target_page <= total_pages:
            self.current_page_index = target_page - 1
            self.update_catalog_page()
    
    def build_catalog(self, silent=False):
        """Build/refresh the catalog with smart page change detection.
        Runs heavy operations in a background thread to keep UI responsive."""
        if not self.catalog_db_path: 
            if not silent:
                QMessageBox.warning(self, "No Data", "Please load a company first.")
            return
        
        # Prevent double-builds
        if hasattr(self, '_build_worker') and self._build_worker and self._build_worker.isRunning():
            return
        
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        
        self._build_silent = silent
        
        if not silent:
            self._build_progress = QProgressDialog("Building catalog...", None, 0, 5, self)
            self._build_progress.setWindowTitle("Building Catalog")
            self._build_progress.setWindowModality(Qt.WindowModality.WindowModal)
            self._build_progress.setMinimumDuration(0)
            self._build_progress.setMinimumWidth(300)
            self._build_progress.show()
        else:
            self._build_progress = None
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        # Create and start worker thread
        company_path = getattr(self, 'company_path', None)
        self._build_worker = CatalogBuildWorker(self.logic, company_path)
        self._build_worker.progress_update.connect(self._on_build_progress)
        self._build_worker.build_finished.connect(self._on_build_finished)
        self._build_worker.start()
    
    def _on_build_progress(self, step, label):
        """Handle progress updates from the build worker."""
        if self._build_progress:
            self._build_progress.setLabelText(label)
            self._build_progress.setValue(step)
    
    def _on_build_finished(self, result):
        """Handle build completion from the worker thread."""
        from PyQt6.QtWidgets import QApplication
        
        if self._build_progress:
            self._build_progress.close()
        if self._build_silent:
            QApplication.restoreOverrideCursor()
        
        self.refresh_catalog_data()
        
        if result["success"]:
            if not self._build_silent:
                msg = f"Catalog built successfully!\n\n"
                msg += f"• Changed Pages: {result['affected_count']}\n"
                msg += f"• CRMs Updated: {result['crm_updated']}\n"
                if result['affected_count'] > 0:
                    sample = result['changed_pages'][:5]
                    msg += f"• Sample: {', '.join(map(str, sample))}"
                    if result['affected_count'] > 5:
                        msg += f" (+{result['affected_count'] - 5} more)"
                QMessageBox.information(self, "Build Complete", msg)
        else:
            if not self._build_silent:
                QMessageBox.critical(self, "Build Error", f"Error during build: {result['error']}")
            else:
                print(f"Auto-Build Error: {result['error']}")
        
        # Clean up worker reference
        self._build_worker = None
    
    def reshuffle_catalog(self):
        """Force a re-sort/re-clustering of products in the CURRENT subgroup.
        
        This is useful when new items are added to the catalog — they initially
        appear at the end, but reshuffling groups them with similar products
        and re-sorts by price within each cluster.
        """
        if not self.catalog_db_path:
            QMessageBox.warning(self, "No Data", "Please load a company first.")
            return
        
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            QMessageBox.warning(self, "No Pages", "No catalog pages available.")
            return
        
        # Get current subgroup from the page being viewed
        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]
        
        # Confirmation dialog
        reply = QMessageBox.question(
            self, "Reshuffle Subgroup",
            f"This will re-sort all products in:\n\n"
            f"   📂 {group_name} > {sg_sn}\n\n"
            f"Products will be grouped by name similarity\n"
            f"and sorted by price within each group.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        from PyQt6.QtWidgets import QApplication
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        
        try:
            # Clear only this subgroup's cache entry
            cache_key = f"{group_name}|{sg_sn}"
            if cache_key in self.logic._layout_cache:
                del self.logic._layout_cache[cache_key]
            
            # Sync pages for this subgroup (auto-create if overflow)
            layout_map = self.logic.simulate_page_layout(group_name, sg_sn, use_cache=False, reshuffle=True)
            max_required_page = max(layout_map.keys()) if layout_map else 1
            
            conn = sqlite3.connect(self.catalog_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?", 
                          (group_name, sg_sn))
            res = cursor.fetchone()
            current_max = res[0] if res and res[0] else 0
            
            if max_required_page > current_max:
                for p in range(current_max + 1, max_required_page + 1):
                    cursor.execute("""
                        INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no)
                        VALUES (?, ?, ?, ?)
                    """, (mg_sn, group_name, sg_sn, p))
                conn.commit()
            conn.close()
            
            # Rebuild serial numbers and refresh display
            self.rebuild_serial_numbers()
            
            # Clear cache so display uses fresh layout
            if cache_key in self.logic._layout_cache:
                del self.logic._layout_cache[cache_key]
            
            self.refresh_catalog_data()
            
            QApplication.restoreOverrideCursor()
            
            QMessageBox.information(
                self, "Reshuffle Complete",
                f"Subgroup '{group_name} > {sg_sn}' reshuffled!\n\n"
                "• Similar products are now grouped together\n"
                "• Groups are sorted by minimum price\n"
                "• Items within groups are sorted by price"
            )
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Reshuffle Error", f"Error during reshuffle: {e}")
            import traceback
            traceback.print_exc()
            self.refresh_catalog_data()
    
    def export_pdf(self):
        """Open print/export dialog with preview and PDF options."""
        if not self.catalog_db_path:
            QMessageBox.warning(self, "No Data", "Please load a company first.")
            return
        
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            QMessageBox.warning(self, "No Pages", "No catalog pages available. Please build the catalog first.")
            return
        
        dialog = PrintExportDialog(self, self, mode="pdf")
        dialog.exec()

    def handle_direct_print(self):
        """Open Print Dialog (Print Mode)."""
        if not self.catalog_db_path: return
        
        # Open Dialog in Print Mode
        dialog = PrintExportDialog(self, self, mode="print")
        dialog.exec()

    def _handle_print_preview_paint(self, printer):
        # Deprecated logic - reused logic handles painting
        pass
    
    def setup_ui(self):
        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(10, 10, 10, 10)
        main_h_layout.setSpacing(20)

        # --- 1. LEFT SIDE: Index List ---
        index_container = QVBoxLayout()
        self.index_table = QTableWidget()
        self.index_table.setObjectName("CatalogIndexTable")  # For CSS
        self.index_table.setFixedWidth(260)  # Reduced from 320
        self.index_table.setColumnCount(2)
        self.index_table.setHorizontalHeaderLabels(["SN", "NAME"])
        
        # Disable editing
        self.index_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        header = self.index_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        self.index_table.verticalHeader().setVisible(False)
        self.index_table.setShowGrid(False)
        self.index_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        index_container.addWidget(self.index_table)
        main_h_layout.addLayout(index_container)

        # --- 2. CENTER: Catalog Page (A4 Renderer) ---
        page_v_center_layout = QVBoxLayout()
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("CatalogScrollArea")
        self.scroll_area.setStyleSheet("background-color: #e0e0e0;")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.renderer = A4PageRenderer()
        # Default DPI for Screen Preview (approx)
        self.renderer.set_target_dpi(96) 
        
        self.scroll_area.setWidget(self.renderer)
        # self.scroll_area.setWidgetResizable(True) # Fixed size widget better not resize
        
        page_v_center_layout.addWidget(self.scroll_area)
        main_h_layout.addLayout(page_v_center_layout)

        # --- 3. RIGHT PANEL (Navigation & Buttons) ---
        right_panel_widget = QWidget()
        right_panel_widget.setFixedWidth(150)  # Increased for better visibility
        right_vbox = QVBoxLayout(right_panel_widget)
        right_vbox.setSpacing(15)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        
        # Navigation Box
        nav_box = QFrame()
        nav_box.setObjectName("CatalogNavBox")
        
        # Use Vertical Layout for Navigator
        nav_layout = QVBoxLayout(nav_box)
        nav_layout.setContentsMargins(5, 8, 5, 8)
        nav_layout.setSpacing(8)
        
        # Icons for Prev/Next
        icon_prev = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        icon_next = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        
        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(icon_prev)
        self.btn_prev.setObjectName("CatalogPrevBtn")
        self.btn_prev.setToolTip("Previous Page")
        self.btn_prev.setFixedSize(40, 30) # Wider click area
        
        self.btn_next = QPushButton()
        self.btn_next.setIcon(icon_next)
        self.btn_next.setObjectName("CatalogNextBtn")
        self.btn_next.setToolTip("Next Page")
        self.btn_next.setFixedSize(40, 30)
        
        # Row 1: Arrow Buttons
        arrows_row = QHBoxLayout()
        arrows_row.addStretch()
        arrows_row.addWidget(self.btn_prev)
        arrows_row.addSpacing(10)
        arrows_row.addWidget(self.btn_next)
        arrows_row.addStretch()
        nav_layout.addLayout(arrows_row)
        
        self.page_input = QLineEdit("1")
        self.page_input.setObjectName("CatalogPageInput")
        self.page_input.setFixedWidth(50)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setStyleSheet("font-size: 14px; font-weight: bold;") 
        self.page_input.returnPressed.connect(self.go_to_page)
        
        self.total_lbl = QLabel("/1")
        self.total_lbl.setObjectName("CatalogTotalLabel")
        self.total_lbl.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 5px;")
        
        # Row 2: Page Input & Label
        info_row = QHBoxLayout()
        info_row.setSpacing(2)
        info_row.addStretch()
        info_row.addWidget(self.page_input)
        info_row.addWidget(self.total_lbl)
        info_row.addStretch()
        nav_layout.addLayout(info_row)
        
        right_vbox.addWidget(nav_box)
        
        # Buttons
        self.btn_build = QPushButton("🔨 Build")
        self.btn_build.setObjectName("CatalogBuildBtn")
        self.btn_build.setFixedHeight(40)
        
        self.btn_export = QPushButton("📄 PDF")
        self.btn_export.setObjectName("CatalogExportBtn")
        self.btn_export.setToolTip("Export to PDF")
        self.btn_export.setFixedHeight(40)
        
        right_vbox.addWidget(self.btn_build)
        right_vbox.addWidget(self.btn_export)
        
        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setObjectName("CatalogPrintBtn")
        self.btn_print.setToolTip("Direct Print (Full Page)")
        self.btn_print.setFixedHeight(40)
        right_vbox.addWidget(self.btn_print)
        
        self.btn_reshuffle = QPushButton("🔀 Reshuffle")
        self.btn_reshuffle.setObjectName("CatalogReshuffleBtn")
        self.btn_reshuffle.setToolTip("Re-sort all products into proper groups\n(Use after adding new items)")
        self.btn_reshuffle.setFixedHeight(40)
        self.btn_reshuffle.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #9b59b6;
            }
            QPushButton:pressed {
                background-color: #7d3c98;
            }
        """)
        right_vbox.addWidget(self.btn_reshuffle)
        
        right_vbox.addStretch() # Push Page Mgmt to bottom
        
        # Page Management
        mgmt_box = QGroupBox("Page Mgmt")
        mgmt_box.setObjectName("PageMgmtBox")
        mgmt_layout = QVBoxLayout(mgmt_box)
        mgmt_layout.setSpacing(10)
        mgmt_layout.setContentsMargins(5, 10, 5, 5)
        
        self.btn_add_page = QPushButton("➕ Page")
        self.btn_add_page.setObjectName("BtnAddPage")
        self.btn_remove_page = QPushButton("➖ Page")
        self.btn_remove_page.setObjectName("BtnRemovePage")
        self.btn_check_empty = QPushButton("🧹 Clean")
        self.btn_check_empty.setObjectName("BtnCleanPage")
        
        mgmt_layout.addWidget(self.btn_add_page)
        mgmt_layout.addWidget(self.btn_remove_page)
        mgmt_layout.addWidget(self.btn_check_empty)
        
        right_vbox.addWidget(mgmt_box) 
        
        main_h_layout.addWidget(right_panel_widget)
    
    def load_index_data(self):
        # लॉजिक फाइल से डेटा मंगवाएं (बिना SQL के)
        data = self.logic.get_index_data()
        
        if not data: return

        self.index_table.setRowCount(len(data))
        self.all_groups = [] # बहुत जरूरी: इसे यहाँ खाली करें

        for row_idx, (sn, group) in enumerate(data):
            g_name = str(group).upper().strip()
            self.all_groups.append(g_name) # क्लिक पहचानने के लिए लिस्ट भरें
            
            # SN को 01, 02 फॉर्मेट में बदलें
            sn_val = "".join(filter(str.isdigit, str(sn)))
            sn_str = sn_val.zfill(2) if sn_val else "00"
            
            item_sn = QTableWidgetItem(sn_str)
            item_name = QTableWidgetItem(g_name)
            
            # स्टाइलिंग (फोंट और कलर)
            font = QFont("Arial", 11)
            item_sn.setFont(font)
            item_name.setFont(font)
            
            if row_idx % 2 == 0:
                bg = QColor("#F8F9FA")
                item_sn.setBackground(bg)
                item_name.setBackground(bg)
                
            self.index_table.setItem(row_idx, 0, item_sn)
            self.index_table.setItem(row_idx, 1, item_name)
    
    def refresh_catalog_data(self):
        if not self.catalog_db_path: return
        
        # 1. Sync Pages (Auto Add)
        self.logic.sync_pages_with_content()
        
        # 2. Rebuild Serials
        self.rebuild_serial_numbers()
        
        # 3. Load Data
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT mg_sn, group_name, sg_sn, page_no, serial_no FROM catalog_pages ORDER BY serial_no")
        self.all_pages_data = cursor.fetchall()
        conn.close()
        
        if self.all_pages_data:
            self.total_lbl.setText(f"/{len(self.all_pages_data)}")
            if self.current_page_index >= len(self.all_pages_data):
                self.current_page_index = 0
        
        self.update_catalog_page()
    
    def update_catalog_page(self):
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
            
        # Current page data
        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]
        
        # Global page numbering (1-indexed)
        current_global_page = self.current_page_index + 1
        total_pages = len(self.all_pages_data)
        
        # Update navigation display with global numbers
        self.page_input.setText(str(current_global_page))
        self.total_lbl.setText(f"/{total_pages}")
        
        self.renderer.set_header_data(group_name, serial_no)

        # Grid Load
        self.load_products_to_grid(group_name, sg_sn, page_no)
   
    def load_products_to_grid(self, group_name, sg_sn, page_no):
        # 1. Fetch
        products = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        
        # 2. Render (empty list will show empty cells)
        self.renderer.fill_products(products if products else [])
        
        # 3. Footer Logic (CRM & Date)
        crm_name = "CRM_NAME" # Placeholder for now, later customizable
        
        # Footer Date (using centralized date_utils)
        from src.utils.date_utils import get_footer_date
        footer_date = get_footer_date(products, self.logic)
            
        self.renderer.set_footer_data(crm_name, footer_date)
    
    def find_page_index_by_subgroup(self, group_name, sn_text):
        """Find the first page index for a given group and subgroup."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return -1
        
        # Extract sg_sn from sn_text (format: "      -> 01")
        sg_sn = sn_text.replace("->", "").strip()
        
        # Remove leading zeros for comparison if needed
        try:
            sg_sn_int = int(sg_sn)
        except:
            sg_sn_int = sg_sn
        
        for i, page in enumerate(self.all_pages_data):
            page_group = page[1]
            page_sg = page[2]
            
            # Compare group names (case insensitive)
            if page_group.upper().strip() == group_name.upper().strip():
                # Compare sg_sn
                try:
                    page_sg_int = int(page_sg)
                    if page_sg_int == sg_sn_int:
                        return i
                except:
                    if str(page_sg).strip() == str(sg_sn).strip():
                        return i
        
        return -1
    def handle_cell_click(self, row, col):
        item = self.index_table.item(row, col)
        if item: self.handle_item_click(item)

    def handle_item_click(self, item):
        row = item.row()
        sn_item = self.index_table.item(row, 0)
        name_item = self.index_table.item(row, 1)

        if not sn_item or not name_item:
            return

        sn_text = sn_item.text()
        group_text = name_item.text().strip()

        # CASE 1: Sub Group click (->)
        if "->" in sn_text:
            main_group = ""
            for r in range(row - 1, -1, -1):
                if "->" not in self.index_table.item(r, 0).text():
                    main_group = self.index_table.item(r, 1).text().strip()
                    break

            target_idx = self.find_page_index_by_subgroup(main_group, sn_text)

            if target_idx != -1:
                self.current_page_index = target_idx
                self.update_catalog_page()
            return

        # CASE 2: Main Group click → ONLY expand/collapse
        if group_text in self.expanded_groups:
            self.collapse_group(group_text)
        else:
            self.expand_group(row, group_text)

    def add_page(self):
        if not self.catalog_db_path or not self.all_pages_data: return

        # Get current context
        mg_sn, group_name, sg_sn, page_no, _ = self.all_pages_data[self.current_page_index]
        
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        
        # Find next page number for this subgroup
        cursor.execute("SELECT MAX(page_no) FROM catalog_pages WHERE group_name=? AND sg_sn=?", (group_name, sg_sn))
        res = cursor.fetchone()
        next_page = (res[0] or 0) + 1
        
        # Insert new page
        cursor.execute("INSERT INTO catalog_pages (mg_sn, group_name, sg_sn, page_no) VALUES (?, ?, ?, ?)", 
                       (mg_sn, group_name, sg_sn, next_page))
        conn.commit()
        conn.close()
        
        self.refresh_catalog_data()
        
        # Navigate to the newly created page
        for i, row in enumerate(self.all_pages_data):
            if row[1] == group_name and row[2] == sg_sn and row[3] == next_page:
                self.current_page_index = i
                break
        
        self.update_catalog_page()

    def showEvent(self, event):
        self.refresh_catalog_data()
        super().showEvent(event)

    def next_page(self):
        if hasattr(self, 'all_pages_data') and self.all_pages_data:
            if self.current_page_index < len(self.all_pages_data) - 1:
                self.current_page_index += 1
                self.update_catalog_page()

    def prev_page(self):
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.update_catalog_page()
            
    def go_to_page(self):
        try:
            val = int(self.page_input.text())
            if hasattr(self, 'all_pages_data') and self.all_pages_data:
                if 1 <= val <= len(self.all_pages_data):
                    self.current_page_index = val - 1
                    self.update_catalog_page()
                else:
                    # Revert
                    self.page_input.setText(str(self.current_page_index + 1))
        except:
            pass

    def handle_build(self):
        if not self.catalog_db_path: return
        try:
            import datetime
            
            # 1. Get last build date
            last_build = self.logic.get_last_build_date()
            
            # 2. Sync pages with content (existing logic)
            self.logic.sync_pages_with_content()
            
            # 3. Detect changed products since last build
            changed_products = self.logic.get_changed_products_since(last_build)
            
            # 4. Find which pages are affected
            if changed_products:
                affected_pages = self.logic.find_pages_for_products(changed_products)
                
                # 5. Add affected pages to all CRMs (silent)
                if affected_pages and hasattr(self, 'company_path') and self.company_path:
                    add_pages_to_all_crms(list(affected_pages), self.company_path)
            
            # 6. Update last build timestamp
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            self.logic.save_last_build_date(now)
            
            # 7. Invalidate cache and refresh
            self.logic.invalidate_cache()
            self.refresh_catalog_data()
            
        except Exception as e:
            pass  # Silent error handling

    def remove_page(self):
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return

        m_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]
        
        # Check #1: Page must not contain products
        items = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        if items:
            QMessageBox.warning(self, "Cannot Remove", "This page contains products. Cannot remove a page with data.")
            return
        
        # Check #2: At least 1 page must remain per subgroup
        conn = sqlite3.connect(self.catalog_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM catalog_pages WHERE group_name=? AND sg_sn=?", (group_name, sg_sn))
        page_count = cursor.fetchone()[0]
        
        if page_count <= 1:
            conn.close()
            QMessageBox.warning(self, "Cannot Remove", "At least one page must remain in each subgroup.")
            return
        
        # Safe to delete
        cursor.execute("DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?", (group_name, sg_sn, page_no))
        conn.commit()
        conn.close()
        
        self.refresh_catalog_data()
        
    def find_page_index_by_subgroup(self, group, sg_sn_text):
        clean = "".join(filter(str.isdigit, str(sg_sn_text)))
        if not hasattr(self, 'all_pages_data'): return -1
        for idx, (m, g, s, p, seq) in enumerate(self.all_pages_data):
            if g.upper().strip() == group.upper().strip() and str(s).zfill(2) == clean.zfill(2) and p == 1:
                return idx
        return -1

    def expand_group(self, row, group_name):
        try:
            sub_data = self.logic.get_subgroups(group_name)
            
            if not sub_data:
                return

            self.index_table.blockSignals(True)
            
            # Insert subgroups below the group row (in reverse order)
            for sg_sn, sg_name in reversed(sub_data):
                next_row = row + 1
                self.index_table.insertRow(next_row)
                
                # SN format: "      -> 01"
                sn_str = f"      -> {str(sg_sn).zfill(2)}"
                item_sn = QTableWidgetItem(sn_str)
                item_name = QTableWidgetItem(str(sg_name).upper())
                
                # Tag items with parent group
                item_sn.setData(Qt.ItemDataRole.UserRole, group_name)
                item_name.setData(Qt.ItemDataRole.UserRole, group_name)
                
                # Styling
                sub_font = QFont("Arial", 9)
                item_sn.setFont(sub_font)
                item_name.setFont(sub_font)
                item_sn.setForeground(QColor("#666666"))
                item_name.setForeground(QColor("#666666"))
                
                self.index_table.setItem(next_row, 0, item_sn)
                self.index_table.setItem(next_row, 1, item_name)
                self.index_table.setRowHeight(next_row, 28)
            
            self.expanded_groups[group_name] = True
            
            self.index_table.blockSignals(False)
            self.index_table.resizeColumnToContents(0)
            self.index_table.viewport().update()
            self.index_table.update()
        
        except Exception as e:
            self.index_table.blockSignals(False)
            
    def collapse_group(self, group_name):
        self.index_table.blockSignals(True)

        # Bottom to top scan (safe removal)
        for row in range(self.index_table.rowCount() - 1, -1, -1):
            item = self.index_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == group_name:
                self.index_table.removeRow(row)

        if group_name in self.expanded_groups:
            del self.expanded_groups[group_name]

        self.index_table.blockSignals(False)
    
    def next_page(self):
        """Navigate to next page globally."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
        
        if self.current_page_index < len(self.all_pages_data) - 1:
            self.current_page_index += 1
            self.update_catalog_page()

    def prev_page(self):
        """Navigate to previous page globally."""
        if not hasattr(self, 'all_pages_data') or not self.all_pages_data:
            return
        
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.update_catalog_page()

    def check_empty_pages(self):
        if not self.catalog_db_path: return
        
        QMessageBox.information(self, "Checking", "Scanning for empty pages... This may take a moment.")
        
        empty_list = self.logic.find_empty_pages()
        
        dlg = EmptyPagesDialog(empty_list, self)
        if dlg.exec():
            # Delete if accepted
            if empty_list:
                reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(empty_list)} pages?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    conn = sqlite3.connect(self.catalog_db_path)
                    cursor = conn.cursor()
                    for g, s, p in empty_list:
                        cursor.execute("DELETE FROM catalog_pages WHERE group_name=? AND sg_sn=? AND page_no=?", (g, s, p))
                    conn.commit()
                    conn.close()
                    
                    self.refresh_catalog_data()
                    QMessageBox.information(self, "Success", "Empty pages deleted.")
    