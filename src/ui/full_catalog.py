"""
Full Catalog UI — PyQt6 widget for catalog page viewing, navigation, building, and export.

Responsibilities:
  - Index sidebar (main groups + expandable subgroups)
  - A4 page rendering and navigation
  - Build workflow (background thread)
  - Page management (add/remove/clean empty)
  - Reshuffle trigger
  - Print & PDF export delegation

All DB access is routed through CatalogLogic — no direct sqlite3 usage here.
"""

import os
import datetime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QPushButton, QLineEdit, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QScrollArea,
    QStyle, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from src.logic.catalog_logic import CatalogLogic
from src.ui.a4_renderer import A4PageRenderer
from src.ui.settings import EmptyPagesDialog, add_pages_to_all_crms
from src.ui.print_export import PrintExportDialog
from src.utils.path_utils import get_data_file_path
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND WORKER
# ═══════════════════════════════════════════════════════════════════════════════

class CatalogBuildWorker(QThread):
    """Background worker for catalog build operations.
    Performs all heavy DB/layout operations off the main thread."""

    progress_update = pyqtSignal(int, str)
    build_finished = pyqtSignal(dict)

    def __init__(self, logic, company_path=None):
        super().__init__()
        self.logic = logic
        self.company_path = company_path

    def run(self):
        try:
            self.progress_update.emit(1, "Step 1/4: Running engine...")
            engine_result = self.logic.engine_run(self.company_path)

            self.progress_update.emit(2, "Step 2/4: Rebuilding serials...")
            self.logic.rebuild_serial_numbers()

            self.progress_update.emit(3, "Step 3/4: Finalizing...")
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            self.logic.save_last_build_date(now)

            self.progress_update.emit(4, "Step 4/4: Complete.")

            self.build_finished.emit({
                "success": True,
                "affected_count": engine_result.get("dirty_count", 0),
                "crm_updated": engine_result.get("dirty_count", 0),
                "changed_pages": engine_result.get("dirty_serials", []),
                "pages_created": engine_result.get("pages_created", 0),
                "error": None
            })
        except Exception as e:
            logger.error(f"CatalogBuildWorker error: {e}", exc_info=True)
            self.build_finished.emit({
                "success": False,
                "affected_count": 0,
                "crm_updated": 0,
                "changed_pages": [],
                "pages_created": 0,
                "error": str(e)
            })


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN UI WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class FullCatalogUI(QWidget):
    catalog_built = pyqtSignal()

    def __init__(self):
        super().__init__()
        db_path = get_data_file_path("super_master.db")
        self.logic = CatalogLogic(db_path)

        self.company_path = None
        self.expanded_groups = {}
        self.current_page_index = 0
        self.all_pages_data = []
        self._build_worker = None

        self._setup_ui()
        self._load_index_data()
        self._connect_signals()

    # ───────────────────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ───────────────────────────────────────────────────────────────────────────

    def set_company_path(self, company_path):
        """Set the active company and initialize its catalog database."""
        self.company_path = company_path

        catalog_db = os.path.join(company_path, "catalog.db")
        final_db = os.path.join(company_path, "final_data.db")
        super_db = os.path.join(os.path.dirname(company_path), "super_master.db")

        self.logic.set_paths(catalog_db, final_db, super_db)
        self.logic.init_catalog_db()

        # Determine company prefix for A4 renderer header
        prefix = self._get_company_prefix(company_path)
        self.renderer._company_prefix = prefix
        if hasattr(self, 'lbl_comp_code'):
            self.lbl_comp_code.setText(prefix)

        self.refresh_catalog_data()

    def _get_company_prefix(self, company_path):
        """Get 3-letter company code from company_info.json or folder name."""
        folder_name = os.path.basename(company_path)
        prefix = folder_name[:3].upper()

        info_file = os.path.join(company_path, "company_info.json")
        if os.path.exists(info_file):
            try:
                import json
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    display_name = info.get("display_name", "").strip()
                    if display_name:
                        prefix = display_name[:3].upper()
            except Exception:
                pass
        return prefix

    # ───────────────────────────────────────────────────────────────────────────
    # UI SETUP
    # ───────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(20)

        # 1. LEFT: Index Table
        self._setup_index_panel(main_layout)

        # 2. CENTER: A4 Renderer
        self._setup_renderer_panel(main_layout)

        # 3. RIGHT: Controls
        self._setup_controls_panel(main_layout)

    def _setup_index_panel(self, parent_layout):
        """Create the left sidebar with group/subgroup index."""
        index_layout = QVBoxLayout()

        self.index_table = QTableWidget()
        self.index_table.setObjectName("CatalogIndexTable")
        self.index_table.setFixedWidth(260)
        self.index_table.setColumnCount(2)
        self.index_table.setHorizontalHeaderLabels(["SN", "NAME"])
        self.index_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        header = self.index_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.index_table.verticalHeader().setVisible(False)
        self.index_table.setShowGrid(False)
        self.index_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        index_layout.addWidget(self.index_table)
        parent_layout.addLayout(index_layout)

    def _setup_renderer_panel(self, parent_layout):
        """Create the center panel with A4 page renderer."""
        center_layout = QVBoxLayout()

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("CatalogScrollArea")
        self.scroll_area.setStyleSheet("background-color: #e0e0e0;")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.renderer = A4PageRenderer()
        self.renderer.set_target_dpi(96)

        self.scroll_area.setWidget(self.renderer)
        center_layout.addWidget(self.scroll_area)
        parent_layout.addLayout(center_layout)

    def _setup_controls_panel(self, parent_layout):
        """Create the right panel with navigation and action buttons."""
        right_widget = QWidget()
        right_widget.setFixedWidth(150)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(15)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Navigation
        self._setup_navigation(right_layout)

        # Action buttons
        self._setup_action_buttons(right_layout)

        right_layout.addStretch()

        # Page management
        self._setup_page_management(right_layout)

        parent_layout.addWidget(right_widget)

    def _setup_navigation(self, parent_layout):
        """Create page navigation controls."""
        nav_box = QFrame()
        nav_box.setObjectName("CatalogNavBox")
        nav_layout = QVBoxLayout(nav_box)
        nav_layout.setContentsMargins(5, 8, 5, 8)
        nav_layout.setSpacing(8)

        # Arrow buttons
        icon_prev = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        icon_next = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(icon_prev)
        self.btn_prev.setObjectName("CatalogPrevBtn")
        self.btn_prev.setToolTip("Previous Page")
        self.btn_prev.setFixedSize(40, 30)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(icon_next)
        self.btn_next.setObjectName("CatalogNextBtn")
        self.btn_next.setToolTip("Next Page")
        self.btn_next.setFixedSize(40, 30)

        arrows = QHBoxLayout()
        arrows.addStretch()
        arrows.addWidget(self.btn_prev)
        arrows.addSpacing(10)
        arrows.addWidget(self.btn_next)
        arrows.addStretch()
        nav_layout.addLayout(arrows)

        # Page input
        self.page_input = QLineEdit("1")
        self.page_input.setObjectName("CatalogPageInput")
        self.page_input.setFixedWidth(50)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setStyleSheet("font-size: 14px; font-weight: bold;")

        self.total_lbl = QLabel("/1")
        self.total_lbl.setObjectName("CatalogTotalLabel")
        self.total_lbl.setStyleSheet("font-size: 14px; font-weight: bold; padding-left: 5px;")

        info_row = QHBoxLayout()
        info_row.setSpacing(2)
        info_row.addStretch()
        info_row.addWidget(self.page_input)
        info_row.addWidget(self.total_lbl)
        info_row.addStretch()
        nav_layout.addLayout(info_row)

        parent_layout.addWidget(nav_box)

    def _setup_action_buttons(self, parent_layout):
        """Create build, export, print, and reshuffle buttons."""
        self.btn_build = QPushButton("🔨 Build")
        self.btn_build.setObjectName("CatalogBuildBtn")
        self.btn_build.setFixedHeight(40)

        self.btn_export = QPushButton("📄 PDF")
        self.btn_export.setObjectName("CatalogExportBtn")
        self.btn_export.setToolTip("Export to PDF")
        self.btn_export.setFixedHeight(40)

        self.btn_print = QPushButton("🖨️ Print")
        self.btn_print.setObjectName("CatalogPrintBtn")
        self.btn_print.setToolTip("Direct Print (Full Page)")
        self.btn_print.setFixedHeight(40)

        self.btn_reshuffle = QPushButton("🔀 Reshuffle")
        self.btn_reshuffle.setObjectName("CatalogReshuffleBtn")
        self.btn_reshuffle.setToolTip("Re-sort all products into proper groups\n(Use after adding new items)")
        self.btn_reshuffle.setFixedHeight(40)
        self.btn_reshuffle.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad; color: white;
                font-weight: bold; border: none; border-radius: 5px;
            }
            QPushButton:hover { background-color: #9b59b6; }
            QPushButton:pressed { background-color: #7d3c98; }
        """)

        parent_layout.addWidget(self.btn_build)
        parent_layout.addWidget(self.btn_export)
        parent_layout.addWidget(self.btn_print)
        parent_layout.addWidget(self.btn_reshuffle)

    def _setup_page_management(self, parent_layout):
        """Create page add/remove/clean buttons."""
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

        parent_layout.addWidget(mgmt_box)

    # ───────────────────────────────────────────────────────────────────────────
    # SIGNAL CONNECTIONS
    # ───────────────────────────────────────────────────────────────────────────

    def _connect_signals(self):
        """Connect all UI signals to handlers (single connection per signal)."""
        # Index clicks
        self.index_table.cellClicked.connect(self._handle_cell_click)

        # Navigation
        self.btn_next.clicked.connect(self.next_page)
        self.btn_prev.clicked.connect(self.prev_page)
        self.page_input.returnPressed.connect(self.go_to_page)

        # Page management
        self.btn_add_page.clicked.connect(self.add_page)
        self.btn_remove_page.clicked.connect(self.remove_page)
        self.btn_check_empty.clicked.connect(self.check_empty_pages)

        # Build & Export
        self.btn_build.clicked.connect(self.build_catalog)
        self.btn_export.clicked.connect(self.export_pdf)
        self.btn_print.clicked.connect(self.handle_direct_print)
        self.btn_reshuffle.clicked.connect(self.reshuffle_catalog)

        # Length change from context menu
        self.renderer.length_changed.connect(self._handle_length_change)

    # ───────────────────────────────────────────────────────────────────────────
    # DATA LOADING
    # ───────────────────────────────────────────────────────────────────────────

    def _load_index_data(self):
        """Load main group list into the index sidebar."""
        data = self.logic.get_index_data()
        if not data:
            return

        self.all_groups = []

        # Filter valid entries
        valid_entries = []
        for sn, group in data:
            sn_val = "".join(filter(str.isdigit, str(sn)))
            if not sn_val:
                continue
            g_name = str(group).upper().strip()
            if not g_name:
                continue
            valid_entries.append((sn_val, g_name))

        self.index_table.setRowCount(len(valid_entries))

        for row_idx, (sn_val, g_name) in enumerate(valid_entries):
            self.all_groups.append(g_name)

            sn_str = sn_val.zfill(2)
            item_sn = QTableWidgetItem(sn_str)
            item_name = QTableWidgetItem(g_name)

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
        """Reload page list and update current view.
        
        Syncs pages with content (ensures page count matches products),
        rebuilds serial numbers, and refreshes the display.
        """
        if not self.logic.catalog_db_path:
            return

        # Sync & rebuild serial numbers
        self.logic.sync_pages_with_content()
        self.logic.rebuild_serial_numbers()

        # Load all pages
        self.all_pages_data = self.logic.get_all_pages()

        if self.all_pages_data:
            self.total_lbl.setText(f"/{len(self.all_pages_data)}")
            if self.current_page_index >= len(self.all_pages_data):
                self.current_page_index = 0

        self._update_catalog_page()

    # ───────────────────────────────────────────────────────────────────────────
    # PAGE DISPLAY
    # ───────────────────────────────────────────────────────────────────────────

    def _update_catalog_page(self):
        """Render the currently selected page."""
        if not self.all_pages_data:
            return

        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]

        # Update navigation display
        self.page_input.setText(str(self.current_page_index + 1))
        self.total_lbl.setText(f"/{len(self.all_pages_data)}")

        # Set header
        self.renderer.set_header_data(group_name, serial_no)

        # Load products
        products = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        self.renderer.fill_products(products if products else [])

        # Footer
        from src.utils.date_utils import get_footer_date
        footer_date = get_footer_date(products, self.logic)
        self.renderer.set_footer_data("CRM_NAME", footer_date)

    # ───────────────────────────────────────────────────────────────────────────
    # NAVIGATION
    # ───────────────────────────────────────────────────────────────────────────

    def next_page(self):
        """Navigate to next page."""
        if self.all_pages_data and self.current_page_index < len(self.all_pages_data) - 1:
            self.current_page_index += 1
            self._update_catalog_page()

    def prev_page(self):
        """Navigate to previous page."""
        if self.all_pages_data and self.current_page_index > 0:
            self.current_page_index -= 1
            self._update_catalog_page()

    def go_to_page(self):
        """Navigate to the page number entered in the input field."""
        if not self.all_pages_data:
            return
        try:
            target = int(self.page_input.text())
            if 1 <= target <= len(self.all_pages_data):
                self.current_page_index = target - 1
                self._update_catalog_page()
            else:
                # Revert to current page
                self.page_input.setText(str(self.current_page_index + 1))
        except ValueError:
            self.page_input.setText(str(self.current_page_index + 1))

    # ───────────────────────────────────────────────────────────────────────────
    # INDEX CLICK HANDLING
    # ───────────────────────────────────────────────────────────────────────────

    def _handle_cell_click(self, row, col):
        """Handle click on index table cell."""
        item = self.index_table.item(row, col)
        if not item:
            return

        sn_item = self.index_table.item(row, 0)
        name_item = self.index_table.item(row, 1)
        if not sn_item or not name_item:
            return

        sn_text = sn_item.text()
        group_text = name_item.text().strip()

        # Subgroup click → navigate to first page of that subgroup
        if "->" in sn_text:
            main_group = ""
            for r in range(row - 1, -1, -1):
                check_sn = self.index_table.item(r, 0)
                if check_sn and "->" not in check_sn.text():
                    main_group = self.index_table.item(r, 1).text().strip()
                    break

            target_idx = self._find_page_index(main_group, sn_text)
            if target_idx != -1:
                self.current_page_index = target_idx
                self._update_catalog_page()
            return

        # Main group click → expand/collapse subgroups
        if group_text in self.expanded_groups:
            self._collapse_group(group_text)
        else:
            self._expand_group(row, group_text)

    def _find_page_index(self, group_name, sg_sn_text):
        """Find the first page index for a given group and subgroup."""
        if not self.all_pages_data:
            return -1

        clean_sn = "".join(filter(str.isdigit, str(sg_sn_text)))
        for idx, (m, g, s, p, seq) in enumerate(self.all_pages_data):
            if (g.upper().strip() == group_name.upper().strip()
                    and str(s).zfill(2) == clean_sn.zfill(2)
                    and p == 1):
                return idx
        return -1

    def _expand_group(self, row, group_name):
        """Expand a main group to show its subgroups in the index."""
        try:
            sub_data = self.logic.get_subgroups(group_name)
            if not sub_data:
                return

            self.index_table.blockSignals(True)

            for sg_sn, sg_name in reversed(sub_data):
                next_row = row + 1
                self.index_table.insertRow(next_row)

                sn_str = f"      -> {str(sg_sn).zfill(2)}"
                item_sn = QTableWidgetItem(sn_str)
                item_name = QTableWidgetItem(str(sg_name).upper())

                # Tag with parent group for collapse
                item_sn.setData(Qt.ItemDataRole.UserRole, group_name)
                item_name.setData(Qt.ItemDataRole.UserRole, group_name)

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
        except Exception as e:
            self.index_table.blockSignals(False)
            logger.error(f"_expand_group error: {e}")

    def _collapse_group(self, group_name):
        """Collapse a main group's subgroups in the index."""
        self.index_table.blockSignals(True)

        # Remove from bottom to top for safe row deletion
        for row in range(self.index_table.rowCount() - 1, -1, -1):
            item = self.index_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == group_name:
                self.index_table.removeRow(row)

        self.expanded_groups.pop(group_name, None)
        self.index_table.blockSignals(False)

    # ───────────────────────────────────────────────────────────────────────────
    # PAGE MANAGEMENT
    # ───────────────────────────────────────────────────────────────────────────

    def add_page(self):
        """Add a new page to the current subgroup."""
        if not self.all_pages_data:
            return

        mg_sn, group_name, sg_sn, page_no, _ = self.all_pages_data[self.current_page_index]
        new_page = self.logic.add_page(mg_sn, group_name, sg_sn)

        if new_page is None:
            return

        self.refresh_catalog_data()

        # Navigate to the new page
        for i, row in enumerate(self.all_pages_data):
            if row[1] == group_name and row[2] == sg_sn and row[3] == new_page:
                self.current_page_index = i
                break
        self._update_catalog_page()

    def remove_page(self):
        """Remove the current page (only if empty and not the last one).
        Handles backward serial shift for all subsequent pages."""
        if not self.all_pages_data:
            return

        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]

        # Check: page must not contain products
        items = self.logic.get_items_for_page_dynamic(group_name, sg_sn, page_no)
        if items:
            QMessageBox.warning(self, "Cannot Remove",
                                "This page contains products. Cannot remove a page with data.")
            return

        # Check: at least 1 page must remain
        page_count = self.logic.get_page_count_for_subgroup(group_name, sg_sn)
        if page_count <= 1:
            QMessageBox.warning(self, "Cannot Remove",
                                "At least one page must remain in each subgroup.")
            return

        # Capture serial info BEFORE deletion for shift handling
        deleted_serial = serial_no
        all_pages = self.logic.get_all_pages()
        old_max_serial = max(p[4] for p in all_pages) if all_pages else 0

        self.logic.remove_page(group_name, sg_sn, page_no)
        self.logic.rebuild_serial_numbers()

        # Handle backward serial shift — remap CRM and add shifted pages
        if self.company_path:
            self.logic.handle_serial_shift_backward(
                self.company_path, deleted_serial, old_max_serial=old_max_serial
            )

        self.refresh_catalog_data()

    def check_empty_pages(self):
        """Scan for and optionally delete empty pages."""
        if not self.logic.catalog_db_path:
            return

        QMessageBox.information(self, "Checking",
                                "Scanning for empty pages... This may take a moment.")

        empty_list = self.logic.find_empty_pages()

        dlg = EmptyPagesDialog(empty_list, self)
        if dlg.exec():
            if empty_list:
                reply = QMessageBox.question(
                    self, "Confirm Delete",
                    f"Are you sure you want to delete {len(empty_list)} pages?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.logic.delete_empty_pages(empty_list)
                    self.refresh_catalog_data()
                    QMessageBox.information(self, "Success", "Empty pages deleted.")

    # ───────────────────────────────────────────────────────────────────────────
    # BUILD CATALOG
    # ───────────────────────────────────────────────────────────────────────────

    def build_catalog(self, silent=False):
        """Build/refresh the catalog with change detection.
        Runs heavy operations in a background thread."""
        if not self.logic.catalog_db_path:
            if not silent:
                QMessageBox.warning(self, "No Data", "Please load a company first.")
            return

        # Prevent concurrent builds
        if self._build_worker and self._build_worker.isRunning():
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

        self._build_worker = CatalogBuildWorker(self.logic, self.company_path)
        self._build_worker.progress_update.connect(self._on_build_progress)
        self._build_worker.build_finished.connect(self._on_build_finished)
        self._build_worker.start()

    def _on_build_progress(self, step, label):
        if self._build_progress:
            self._build_progress.setLabelText(label)
            self._build_progress.setValue(step)

    def _on_build_finished(self, result):
        from PyQt6.QtWidgets import QApplication

        if self._build_progress:
            self._build_progress.close()
        if self._build_silent:
            QApplication.restoreOverrideCursor()

        self.refresh_catalog_data()

        if result["success"]:
            self.catalog_built.emit()
            if not self._build_silent:
                msg = f"Catalog built successfully!\n\n"
                msg += f"• Changed Pages: {result['affected_count']}\n"
                msg += f"• CRMs Updated: {result['crm_updated']}\n"
                msg += f"• Pages Created: {result.get('pages_created', 0)}\n"
                if result['affected_count'] > 0:
                    sample = result['changed_pages'][:5]
                    msg += f"• Sample: {', '.join(map(str, sample))}"
                    if result['affected_count'] > 5:
                        msg += f" (+{result['affected_count'] - 5} more)"
                QMessageBox.information(self, "Build Complete", msg)
        else:
            if not self._build_silent:
                QMessageBox.critical(self, "Build Error",
                                     f"Error during build: {result['error']}")
            else:
                logger.error(f"Auto-Build Error: {result['error']}")

        self._build_worker = None

    # ───────────────────────────────────────────────────────────────────────────
    # RESHUFFLE
    # ───────────────────────────────────────────────────────────────────────────

    def reshuffle_catalog(self):
        """Force re-sort/re-clustering of products in the current subgroup."""
        if not self.logic.catalog_db_path:
            QMessageBox.warning(self, "No Data", "Please load a company first.")
            return

        if not self.all_pages_data:
            QMessageBox.warning(self, "No Pages", "No catalog pages available.")
            return

        mg_sn, group_name, sg_sn, page_no, serial_no = self.all_pages_data[self.current_page_index]

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
            # Clear cache for this subgroup and force reshuffle
            self.logic.invalidate_subgroup_cache(group_name, sg_sn)
            layout_map = self.logic.simulate_page_layout(
                group_name, sg_sn, use_cache=False, reshuffle=True
            )

            # Auto-create pages if layout overflows
            max_required = max(layout_map.keys()) if layout_map else 1
            current_max = self.logic.get_page_count_for_subgroup(group_name, sg_sn)

            if max_required > current_max:
                for p in range(current_max + 1, max_required + 1):
                    self.logic.add_page(mg_sn, group_name, sg_sn)

            # Clear cache again so display uses fresh layout
            self.logic.invalidate_subgroup_cache(group_name, sg_sn)
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
            logger.error(f"reshuffle_catalog error: {e}", exc_info=True)
            self.refresh_catalog_data()

    # ───────────────────────────────────────────────────────────────────────────
    # PRINT & EXPORT
    # ───────────────────────────────────────────────────────────────────────────

    def export_pdf(self):
        """Open print/export dialog in PDF mode."""
        if not self.logic.catalog_db_path:
            QMessageBox.warning(self, "No Data", "Please load a company first.")
            return
        if not self.all_pages_data:
            QMessageBox.warning(self, "No Pages",
                                "No catalog pages available. Please build the catalog first.")
            return

        dialog = PrintExportDialog(self, self, mode="pdf")
        dialog.exec()

    def handle_direct_print(self):
        """Open print/export dialog in print mode."""
        if not self.logic.catalog_db_path:
            return
        dialog = PrintExportDialog(self, self, mode="print")
        dialog.exec()

    # ───────────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS
    # ───────────────────────────────────────────────────────────────────────────

    def _handle_length_change(self, product_name, new_length):
        """Handle product size change from renderer context menu."""
        if not self.logic.final_db_path:
            return

        group_name = None
        sg_sn = None
        if getattr(self, "all_pages_data", None) and getattr(self, "current_page_index", None) is not None:
            if 0 <= self.current_page_index < len(self.all_pages_data):
                try:
                    _, group_name, sg_sn, _, _ = self.all_pages_data[self.current_page_index]
                except Exception as e:
                    logger.error(f"Could not get current group data for length update: {e}")

        affected = self.logic.update_product_length(product_name, new_length, group_name, sg_sn)
        if affected > 0:
            self.logic.invalidate_cache()
            self.refresh_catalog_data()

    def showEvent(self, event):
        """Reload data and run engine when the tab becomes visible."""
        self.expanded_groups = {}
        self._load_index_data()

        # Run engine silently on tab switch (detect changes + sort dirty ranges)
        if self.logic.catalog_db_path:
            try:
                self.logic.engine_run(self.company_path)
            except Exception as e:
                logger.error(f"showEvent engine_run error: {e}")

        self.refresh_catalog_data()
        super().showEvent(event)

    def _handle_print_preview_paint(self, printer):
        """Deprecated — handled by PrintExportDialog."""
        pass