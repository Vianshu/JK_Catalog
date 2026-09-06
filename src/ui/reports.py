import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QDialog, QComboBox, QListWidget, QFileDialog, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QMarginsF, pyqtSignal
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PyQt6.QtGui import QPainter, QPageSize, QPageLayout
from src.logic.report_store import (
    load_crm_list, load_report_json, save_report_json,
    stamp_print_date, get_last_print_date
)
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
            except Exception as e:
                pending.sort()
        self.pages_list.addItems(pending)

class ReportsUI(QWidget):
    # Emitted when the user clicks "Go to Final Data" from the missing-image warning.
    # Carries the list of GUIDs for the missing-image products so Final Data can
    # auto-select those rows.
    navigate_to_final_data = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.current_company_path = ""
        self.download_path = ""
        self.logic = None
        self._user_session = None    # Set by main_window after login
        self._security_mgr = None   # Set by main_window after login
        self.init_ui()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(20)

        # --- Top Header Section ---
        header_layout = QHBoxLayout()
        title = QLabel("📈 CRM Performance Reports")
        title.setObjectName("SectionTitle")
        
        self.lbl_last_sync = QLabel("Last Sync: N/A")
        self.lbl_last_sync.setStyleSheet("color: #64748b; font-weight: bold; font-size: 11pt; margin-left: 20px;")
        
        self.lbl_refresh = QLabel("\u23f3 Refreshing Catalog... Please Wait")
        self.lbl_refresh.setObjectName("RefreshLabel")
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
        header_layout.addWidget(self.lbl_last_sync)
        header_layout.addWidget(self.lbl_refresh)
        header_layout.addStretch()
        header_layout.addLayout(button_box)
        main_layout.addLayout(header_layout)

        # --- Report Table ---
        self.table = QTableWidget()
        self.table.setObjectName("ReportsTable")
        headers = ["CRM Name", "Pending Pages", "Last Synced Pages", "Print Date"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        header = self.table.horizontalHeader()
        # CRM Name — fixed narrow (5-char display)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 65)
        # Pending Pages — stretch to absorb extra space
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Last Synced Pages — stretch
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # Print Date — fixed narrow (DD/MM HH:MM = 11 chars + padding)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 115)
        
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
        """Return company_path for SQL-backed report functions."""
        return self.current_company_path or ""

    def set_location(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if path:
            self.download_path = path
            # Sync download path to catalog page so PDF export uses same location
            main_win = self.window()
            if hasattr(main_win, 'full_catalog_page'):
                main_win.full_catalog_page.download_path = path
            logger.info(f"Report download location set: '{path}'")
            QMessageBox.information(self, "Success", f"Download location set to:\n{path}")

    def _get_pages_missing_images(self, pending_serials: list) -> dict:
        """Return {serial_no: {'products': [...], 'guids': [...]}} for each
        pending page that has at least one product without an image."""
        result = {}
        if not pending_serials or not self.logic:
            return result
        try:
            conn = self.logic._get_conn("_DB_CATALOG")
            if conn is None:
                conn = self.logic._get_conn("catalog")
        except Exception:
            conn = None
        try:
            conn_fd = self.logic._get_conn("_DB_FINAL")
            if conn_fd is None:
                conn_fd = self.logic._get_conn("final")
        except Exception:
            conn_fd = None

        if not conn or not conn_fd:
            return result

        try:
            placeholders = ",".join(["?" for _ in pending_serials])
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT serial_no, group_name, sg_sn FROM catalog_pages "
                f"WHERE serial_no IN ({placeholders})",
                [str(s) for s in pending_serials]
            )
            page_map = {str(r[0]): (r[1], r[2]) for r in cursor.fetchall()}
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"_get_pages_missing_images step1: {e}")
            return result

        try:
            cursor_fd = conn_fd.cursor()
            for serial, (grp, sg) in page_map.items():
                cursor_fd.execute("""
                    SELECT [Product Name], [Item_Name], [GUID]
                    FROM catalog
                    WHERE REPLACE(TRIM([Group]), '.', '') =
                          REPLACE(TRIM(?), '.', '') COLLATE Latin1_General_CI_AI
                      AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)
                      AND (LOWER(TRIM(CAST([True/False] AS NVARCHAR(MAX)))) NOT IN ('false', '0', 'no')
                           OR [True/False] IS NULL OR TRIM([True/False]) = '')
                      AND (CAST(REPLACE(ISNULL([Stock], '0'), ',', '') AS FLOAT) > 0
                           OR LOWER(TRIM(CAST([True/False] AS NVARCHAR(MAX)))) IN ('1', 'true', 'yes'))
                      AND ([Image_Path] IS NULL OR TRIM(CAST([Image_Path] AS NVARCHAR(MAX))) = '')
                """, (grp, sg))
                products, guids = [], []
                for row in cursor_fd.fetchall():
                    name = row[0] if row[0] and str(row[0]).strip() else row[1]
                    if name:
                        products.append(str(name).strip())
                    if row[2]:
                        guids.append(str(row[2]).strip())
                if products:
                    result[str(serial)] = {"products": products, "guids": guids}
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"_get_pages_missing_images step2: {e}")
        return result

    def _show_missing_image_warning(self, pages_missing: dict) -> bool:
        """Show a dialog listing pending pages with missing images.
        Returns True if the user wants to Continue Anyway, False to cancel."""
        from PyQt6.QtWidgets import QScrollArea
        dlg = QDialog(self)
        dlg.setWindowTitle("⚠️ Missing Images Detected")
        dlg.setMinimumWidth(520)
        dlg.setMinimumHeight(360)
        layout = QVBoxLayout(dlg)

        header = QLabel(
            f"<b>{len(pages_missing)} pending page(s) have products with no image.</b><br>"
            "You can continue printing or go to Final Data to fix them first."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # Scrollable list of pages + products
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(4)
        for serial in sorted(pages_missing.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            entry = pages_missing[serial]
            products = entry["products"] if isinstance(entry, dict) else entry
            lbl = QLabel(f"<b>Page {serial}:</b> " + ", ".join(products[:5])
                         + (f" (+{len(products)-5} more)" if len(products) > 5 else ""))
            lbl.setWordWrap(True)
            inner_layout.addWidget(lbl)
        inner_layout.addStretch()
        inner.setLayout(inner_layout)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_go = QPushButton("🔍 Go to Final Data")
        btn_go.setObjectName("BtnBlue")
        btn_continue = QPushButton("🖨️ Continue Anyway")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("BtnCancel")
        btn_row.addWidget(btn_go)
        btn_row.addWidget(btn_continue)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        user_choice = ["cancel"]
        btn_go.clicked.connect(lambda: [user_choice.__setitem__(0, "go"), dlg.accept()])
        btn_continue.clicked.connect(lambda: [user_choice.__setitem__(0, "continue"), dlg.accept()])
        btn_cancel.clicked.connect(dlg.reject)

        dlg.exec()
        if user_choice[0] == "go":
            # Collect all GUIDs from affected pages
            all_guids = []
            for entry in pages_missing.values():
                guids = entry.get("guids", []) if isinstance(entry, dict) else []
                all_guids.extend(guids)
            self.navigate_to_final_data.emit(all_guids)
            return False   # cancel the print flow
        return user_choice[0] == "continue"

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
        
        # 1. Select CRM
        sel_dlg = CRMSelectDialog(parent=self, report_data=current_report_data, crm_path=self.current_company_path or "", mode=mode)
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
        except Exception as e:
            pending_serials = sorted(pending_serials)

        # 1b. Pre-flight: warn about pending pages with missing images
        missing_pages = self._get_pages_missing_images(pending_serials)
        if missing_pages:
            should_continue = self._show_missing_image_warning(missing_pages)
            if not should_continue:
                return

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

        pages_marked = list(all_data[crm_name].get("pending", []))
        page_count = len(pages_marked)

        # Move pending to recent
        all_data[crm_name]["recent"] = all_data[crm_name]["pending"]
        all_data[crm_name]["pending"] = []

        save_report_json(all_data, path)

        # Audit log: who marked which CRM as done
        try:
            if self._security_mgr and self._user_session:
                sample = ", ".join(str(p) for p in pages_marked[:10])
                if len(pages_marked) > 10:
                    sample += f" (+{len(pages_marked) - 10} more)"
                self._security_mgr.log_action(
                    self._user_session,
                    "crm_update",
                    module="reports",
                    detail=f"CRM '{crm_name}' — {page_count} page(s) marked done. Pages: [{sample}]"
                )
                logger.info(
                    f"Audit: crm_update by '{self._user_session.username}' — "
                    f"CRM='{crm_name}', {page_count} pages"
                )
        except Exception as audit_err:
            logger.warning(f"update_pages_logic: audit log failed: {audit_err}")

        # Stamp the last-print date so the Print Date column shows the actual
        # time this user confirmed the job was done (not the report-open time).
        # This MUST happen before refresh_report_data() so the table reads the new date.
        try:
            stamp_print_date(self.get_report_path(), crm_name)
        except Exception as stamp_err:
            logger.warning(f"update_pages_logic: stamp_print_date failed: {stamp_err}")

        self.refresh_report_data()

    def refresh_report_data(self):
        # Read last sync timestamp directly from THIS company's own database
        # (not from final_data_page.sync_lbl which can show another company's sync)
        try:
            if self.current_company_path:
                from src.logic.db_manager import get_db_manager, build_logical_name
                db = get_db_manager()
                company_name = os.path.basename(self.current_company_path)
                db_name = build_logical_name(company_name, company_path=self.current_company_path)
                conn = db.get_connection(db_name)
                if conn:
                    row = conn.cursor().execute(
                        "SELECT TOP 1 Update_date FROM catalog "
                        "WHERE Update_date IS NOT NULL AND Update_date != '' "
                        "ORDER BY ("
                        "   SUBSTRING(Update_date, 7, 4) + "
                        "   SUBSTRING(Update_date, 4, 2) + "
                        "   SUBSTRING(Update_date, 1, 2) + "
                        "   SUBSTRING(Update_date, 11, 9)"
                        ") DESC"
                    ).fetchone()
                    if row and row[0]:
                        self.lbl_last_sync.setText(f"Last Sync: {row[0]}")
                    else:
                        self.lbl_last_sync.setText("Last Sync: No data")
                else:
                    self.lbl_last_sync.setText("Last Sync: N/A")
            else:
                self.lbl_last_sync.setText("Last Sync: N/A")
        except Exception as e:
            logger.warning(f"refresh_report_data: failed to read sync timestamp: {e}")
            self.lbl_last_sync.setText("Last Sync: N/A")

        if not self.current_company_path:
            self.table.setRowCount(0)
            return

        crm_names = load_crm_list(self.current_company_path) 
        
        if not crm_names:
            self.table.setRowCount(0)
            return

        report_db = load_report_json(self.get_report_path())
        self.table.setRowCount(0)

        for name in crm_names:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = report_db.get(name, {"pending": [], "recent": []})
            
            # Col 0: CRM Name (truncated display — column is narrow for 5-char names)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            
            p_list = data["pending"]
            if p_list:
                try: p_list.sort(key=lambda x: int(x) if str(x).isdigit() else float('inf'))
                except Exception as e: p_list.sort()
            
            # Col 1: Pending Pages
            p_pages = ", ".join(p_list) if p_list else "Completed"
            self.table.setItem(row, 1, QTableWidgetItem(p_pages))
            # Col 2: Last Synced Pages
            r_pages = ", ".join(data["recent"]) if data["recent"] else "None"
            self.table.setItem(row, 2, QTableWidgetItem(r_pages))
            # Col 3: Print Date — actual last-print timestamp (blank if never printed)
            print_date = get_last_print_date(self.get_report_path(), name)
            self.table.setItem(row, 3, QTableWidgetItem(print_date))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_report_data()