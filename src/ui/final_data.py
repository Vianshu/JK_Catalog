import os
import json
import datetime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QGroupBox, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressDialog, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
# Aapka original processor
from src.logic.data_processor import DataProcessor
from src.logic.db_manager import get_db_manager, build_logical_name, DB_SUPER, build_shared_db_name
from src.utils.app_logger import get_logger
from src.ui.table_nav_mixin import ExcelTableMixin

logger = get_logger(__name__)


class _SyncCancelled(Exception):
    """Raised when user cancels the Final Data sync pipeline."""
    pass


class FinalDataSyncWorker(QThread):
    """Background worker for Final Data sync operations.
    Runs DB sync, processor, and image sync off the main thread."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, object)  # (sync_label, dup_map)
    error = pyqtSignal(str)

    def __init__(self, ui_ref, folder_path, company_name):
        super().__init__()
        self.ui = ui_ref
        self.folder_path = folder_path
        self.company_name = company_name
        self._cancelled = False

    def cancel(self):
        """Signal the worker to stop at the next checkpoint."""
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        try:
            sync_label, dup_map = self.ui._run_sync_pipeline(
                self.folder_path, self.company_name, self.progress,
                cancel_check=self.is_cancelled
            )
            self.finished.emit(sync_label, dup_map)
        except (_SyncCancelled, InterruptedError):
            logger.info("Final Data sync pipeline cancelled — rolling back all changes")
            self._rollback_connection()
            self.finished.emit("cancelled", {})
        except Exception as e:
            logger.error(f"Sync Worker Error: {e}", exc_info=True)
            self._rollback_connection()
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            # Clean up all DB connections owned by this worker thread
            try:
                get_db_manager().close_thread_connections()
            except Exception:
                pass

    def _rollback_connection(self):
        """Rollback all uncommitted changes on the shared connection."""
        try:
            db = get_db_manager()
            company_name = os.path.basename(self.folder_path)
            final_db = build_logical_name(company_name, company_path=self.folder_path)
            conn = db.get_connection(final_db)
            if conn:
                conn.rollback()
                logger.info(f"Transaction rolled back for {final_db}")
        except Exception as e:
            logger.error(f"Rollback failed: {e}", exc_info=True)


class RefreshWorker(QThread):
    """Background worker for refresh_table data preparation.
    Moves DB fetch, sorting, clustering, and image checks off the main thread.
    Only the final table population happens on the main thread."""
    finished = pyqtSignal(list, list, list)  # final_display_data, right_align_indices, column_indices
    error = pyqtSignal(str)

    def __init__(self, ui_ref):
        super().__init__()
        self.ui = ui_ref

    def run(self):
        try:
            db = get_db_manager()
            conn = db.get_connection(self.ui.final_db_name)
            if not conn:
                self.error.emit("Cannot connect to DB")
                return
            cursor = conn.cursor()

            # Guard: catalog table may not exist if Tally sync has never been run
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'catalog'"
            )
            if cursor.fetchone()[0] == 0:
                # No data yet — emit empty result, not an error
                self.finished.emit([], [], [])
                return

            # Use the pre-computed ID column for ordering instead of
            # re-running O(n²) cluster_and_sort on every refresh.
            # generate_complex_ids() bakes the full hierarchy into the ID:
            #   {MG}{SG}_{cluster}{item}_{variant}
            # So ORDER BY ID gives us: MG → SG → cluster → item → variant
            # — exactly the same grouping that clustering would produce.
            # Rows with NULL ID (pre-first-sync) fall to the end via ISNULL.
            cursor.execute("""
                SELECT * FROM catalog
                ORDER BY ISNULL(ID, 'ZZZZ_ZZZZ_ZZ') ASC
            """)
            data = cursor.fetchall()

            grp_idx = self.ui.col_index("Group")
            path_idx = self.ui.col_index("Image_Path")

            # Split into missing/found images (fast O(n) pass)
            missing_rows = []
            found_rows = []
            for r in data:
                grp = str(r[grp_idx]).lower().strip() if r[grp_idx] else ""
                path = str(r[path_idx]) if r[path_idx] else ""
                if grp != "price list" and (not path or not os.path.exists(path)):
                    missing_rows.append(r)
                else:
                    found_rows.append(r)

            final_display_data = missing_rows + found_rows

            # Pre-compute column indices
            right_align_cols = ["Unit", "MOQ", "M_Packing", "MRP", "Stock", "MG_SN", "SG_SN"]
            right_align_indices = [self.ui.col_index(c) for c in right_align_cols if c in self.ui.headers]
            col_indices = [grp_idx, path_idx]

            self.finished.emit(final_display_data, right_align_indices, col_indices)

        except Exception as e:
            logger.error(f"RefreshWorker Error: {e}", exc_info=True)
            self.error.emit(str(e))

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)


class AutoImageSyncWorker(QThread):
    """Lightweight background worker: image-only sync triggered on tab switch.

    Only runs when the image folder fingerprint (file count + max mtime) has
    changed since the last scan.  No Tally fetch, no product-name processing —
    just image-path matching + True/False update + commit.

    Guardrails:
    - Never started while FinalDataSyncWorker (_sync_worker) is running.
    - Commits its own transaction so changes are immediately visible.
    - Cleans up its own DB thread-connections in finally block.
    """
    finished = pyqtSignal(object)   # dup_map dict (may be empty)
    error    = pyqtSignal(str)

    def __init__(self, ui_ref):
        super().__init__()
        self.ui = ui_ref

    def run(self):
        import time
        t0 = time.perf_counter()
        try:
            # sync_images_after_processing() calls get_image_mapping() internally.
            # Because the fingerprint already differs from the cache, it will do a
            # full folder scan, update the cache, then update Image_Path / Image_Date
            # / True/False columns — without committing (relies on caller to commit).
            dup_map = self.ui.sync_images_after_processing()

            # Commit — the full sync pipeline does this at its own end; here we must
            # commit explicitly so changes are visible to the subsequent table refresh.
            conn = self.ui.db.get_connection(self.ui.final_db_name)
            if conn:
                conn.commit()

            elapsed = time.perf_counter() - t0
            logger.info(f"AutoImageSync: completed in {elapsed:.2f}s")
            self.finished.emit(dup_map or {})
        except Exception as e:
            logger.error(f"AutoImageSyncWorker error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            try:
                get_db_manager().close_thread_connections()
            except Exception:
                pass


class FinalDataUI(ExcelTableMixin, QWidget):
    sync_complete  = pyqtSignal()  # Emitted when background Tally sync finishes
    sync_cancelled = pyqtSignal()  # Emitted when background Tally sync is cancelled
    image_sync_done = pyqtSignal() # Emitted when auto-image sync commits to DB

    def __init__(self):
        super().__init__()
        self.db_path = ""  # Company folder path (kept for image sync etc.)
        self.db = get_db_manager()
        self.final_db_name = ""  # Logical DB name for final_data
        self.row_data_db_name = ""  # Logical DB name for row_data
        self.image_folder = ""
        self._sync_worker = None
        self._refresh_worker = None
        self._last_data_hash = None  # Cache: skip refresh if data unchanged
        self._columns_sized = False  # One-time column width setup
        self.super_master_path = ""
        self.headers = [
            "GUID", "ID", "Item_Name", "Alias", "Part_No", "Product Name", 
            "Product_Size", "Category", "Unit", "MOQ", "M_Packing", "MRP", 
            "Stock", "MG_SN", "Group", "SG_SN", "Sub_Group", "Image_Name", 
            "Image_Path", "Lenth", "Image_Date", "True/False", "Update_date"
        ]
        self.setup_ui()

    def set_company_path(self, path):
        self.db_path = os.path.join(path, "final_data.db")  # Legacy path for image sync
        self._company_path = path  # Store for path-aware DB naming
        company_name = os.path.basename(path)
        self.final_db_name = build_logical_name(company_name, company_path=path)
        self.row_data_db_name = build_logical_name(company_name, company_path=path)
        # Clear image-map cache so a fresh fingerprint is built for the new company.
        # Without this, stale fingerprints from the previous session/company would
        # prevent the auto-sync from detecting folder changes on first tab-switch.
        self._img_map_cache = None
        # Load image_folder immediately so auto-sync can detect changes without a
        # manual Tally sync being run first (previously only set in load_and_sync_data).
        self.image_folder = ""
        info_file = os.path.join(path, "company_info.json")
        if os.path.exists(info_file):
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    if "image_path" in info:
                        self.image_folder = info["image_path"]
            except Exception:
                pass

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        self.table = QTableWidget(0, len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        
        # 1. GUID ko hide karna (Pehle se shayad tha)
        self.table.setColumnHidden(0, True)
        
        # 3. Side wale row numbers (1,2,3...) ko hatane ke liye:
        self.table.verticalHeader().setVisible(False)
        
        # --- NAYA: Database mein save karne ke liye signal ---
        self.table.itemChanged.connect(self.save_cell_to_db)

        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        
        self.table.cellClicked.connect(self.show_preview)
        self.table.cellDoubleClicked.connect(self.show_path_popup)

        # Excel-like navigation (Mode 1 / Mode 2)
        self._init_excel_table(self.table)
        
        # Side Panel Logic (Aapke backup se same)
        main_layout.addWidget(self.table, 4) # Table gets 4 parts weight

        # --- RIGHT SIDE PANEL ---
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(5, 4, 5, 4)
        side_layout.setSpacing(4)  # Was 8 — tighter so widgets don't balloon at 125% DPI

        # 1. Sync Time — compact single-line info bar
        self.sync_lbl = QLabel("Last Sync: N/A")
        self.sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_lbl.setObjectName("SyncLabel")
        self.sync_lbl.setFixedHeight(22)  # Prevents it from growing with DPI
        self.sync_lbl.setStyleSheet("font-size: 11px; color: #6B7280;")
        side_layout.addWidget(self.sync_lbl)

        # 2. Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Item Name...")
        self.search_input.setFixedHeight(28)
        self.search_input.textChanged.connect(self.filter_table)
        side_layout.addWidget(self.search_input)

        # 2b. GUID filter banner (hidden by default, shown when navigated from Reports)
        self._guid_filter: set = set()   # empty = no GUID filter active
        self._filter_banner = QWidget()
        _fb_layout = QHBoxLayout(self._filter_banner)
        _fb_layout.setContentsMargins(6, 2, 6, 2)
        self._filter_banner_lbl = QLabel("")
        self._filter_banner_lbl.setStyleSheet(
            "color:#fff;background:#c0392b;border-radius:4px;padding:2px 6px;font-size:11px;")
        _btn_clear_filter = QPushButton("✕ Clear")
        _btn_clear_filter.setFixedHeight(22)
        _btn_clear_filter.setStyleSheet(
            "background:#e74c3c;color:white;border-radius:3px;padding:0 6px;font-size:11px;")
        _btn_clear_filter.clicked.connect(self.clear_guid_filter)
        _fb_layout.addWidget(self._filter_banner_lbl)
        _fb_layout.addWidget(_btn_clear_filter)
        self._filter_banner.hide()
        side_layout.addWidget(self._filter_banner)

        # 3. Image Preview — fixed logical height, never expands
        from PyQt6.QtWidgets import QFrame, QGridLayout, QSizePolicy
        img_container = QFrame()
        img_container.setObjectName("ImgContainer")
        img_container_layout = QVBoxLayout(img_container)
        img_container_layout.setContentsMargins(4, 4, 4, 4)
        img_container_layout.setSpacing(3)

        img_title = QLabel("🖼️ Image Preview")
        img_title.setObjectName("ImgTitle")
        img_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_title.setFixedHeight(18)
        img_title.setStyleSheet("font-size: 11px; font-weight: 600; color: #4A5568;")
        img_container_layout.addWidget(img_title)

        self.img_preview = QLabel("NO IMAGE")
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setObjectName("ImgPreview")
        from PyQt6.QtWidgets import QApplication
        _dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.primaryScreen() else 1.0
        _preview_physical_h = 350  # physical px — constant across all DPI settings
        self._img_preview_logical_h = max(80, int(_preview_physical_h / _dpr))
        self.img_preview.setFixedHeight(self._img_preview_logical_h)
        self.img_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        img_container_layout.addWidget(self.img_preview)

        # Duplicate image warning (hidden by default, compact when shown)
        self._dup_warning_lbl = QLabel()
        self._dup_warning_lbl.setWordWrap(True)
        self._dup_warning_lbl.setObjectName("DupWarningLabel")
        self._dup_warning_lbl.setStyleSheet("font-size: 10px;")
        self._dup_warning_lbl.setVisible(False)
        img_container_layout.addWidget(self._dup_warning_lbl)
        self._duplicate_images = {}  # populated by sync_images_after_processing

        side_layout.addWidget(img_container)

        # 4. Summary Statistics Panel
        summary_frame = QFrame()
        summary_frame.setObjectName("SummaryFrame")
        summary_grid = QGridLayout(summary_frame)
        summary_grid.setSpacing(3)
        summary_grid.setContentsMargins(6, 6, 6, 6)

        # Summary Title
        summary_title = QLabel("📊 Summary")
        summary_title.setObjectName("SummaryTitle")
        summary_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_title.setFixedHeight(20)
        summary_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #1A2035;")
        summary_grid.addWidget(summary_title, 0, 0, 1, 2)

        # Catalog Total Items
        self.lbl_catalog_total = QLabel("Catalog Total:")
        self.lbl_catalog_total.setObjectName("SummaryLabel")
        self.lbl_catalog_total_val = QLabel("0")
        self.lbl_catalog_total_val.setObjectName("SummaryValueGreen")
        self.lbl_catalog_total_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_catalog_total, 1, 0)
        summary_grid.addWidget(self.lbl_catalog_total_val, 1, 1)

        # Excluded by Stock
        self.lbl_out_stock = QLabel("Excluded (Stock):")
        self.lbl_out_stock.setObjectName("SummaryLabel")
        self.lbl_out_stock_val = QLabel("0")
        self.lbl_out_stock_val.setObjectName("SummaryValueOrange")
        self.lbl_out_stock_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_out_stock, 2, 0)
        summary_grid.addWidget(self.lbl_out_stock_val, 2, 1)

        # Manual False Items
        self.lbl_false = QLabel("Manual False:")
        self.lbl_false.setObjectName("SummaryLabel")
        self.lbl_false_val = QLabel("0")
        self.lbl_false_val.setObjectName("SummaryValueRed")
        self.lbl_false_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_false, 3, 0)
        summary_grid.addWidget(self.lbl_false_val, 3, 1)

        # Separator
        sep_line = QLabel("─" * 20)
        sep_line.setObjectName("SummarySeparator")
        sep_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep_line.setFixedHeight(14)
        summary_grid.addWidget(sep_line, 4, 0, 1, 2)

        # Final Data Total
        self.lbl_final_total = QLabel("Final Data Total:")
        self.lbl_final_total.setObjectName("SummaryLabel")
        self.lbl_final_total_val = QLabel("0")
        self.lbl_final_total_val.setObjectName("SummaryValueTeal")
        self.lbl_final_total_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_final_total, 5, 0)
        summary_grid.addWidget(self.lbl_final_total_val, 5, 1)

        # Item Mismatch
        self.lbl_mismatch = QLabel("Item Mismatch:")
        self.lbl_mismatch.setObjectName("SummaryLabel")
        self.lbl_mismatch_val = QLabel("0")
        self.lbl_mismatch_val.setObjectName("SummaryValuePurple")
        self.lbl_mismatch_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_grid.addWidget(self.lbl_mismatch, 6, 0)
        summary_grid.addWidget(self.lbl_mismatch_val, 6, 1)

        side_layout.addWidget(summary_frame)

        # Push all widgets to the top — prevents them from distributing vertically
        side_layout.addStretch(1)

        main_layout.addWidget(side_panel, 1)  # Side panel gets 1 part weight
        
        # Connect Selection Change for Arrow Keys
        self.table.selectionModel().currentRowChanged.connect(self.on_row_changed)


    def col_index(self, name):
        return self.headers.index(name)

    def select_rows_by_guid(self, guids: list):
        """Deprecated alias — use filter_to_guids instead."""
        self.filter_to_guids(guids)

    def filter_to_guids(self, guids: list):
        """Hide every row whose GUID is NOT in *guids*, show a clear-filter
        banner, and scroll to the first visible row."""
        self._guid_filter = set(guids)
        if not self._guid_filter:
            self.clear_guid_filter()
            return
        self.filter_table()   # applies both GUID filter and search text
        # Update banner
        self._filter_banner_lbl.setText(
            f"Showing {len(guids)} product(s) with missing images from pending pages")
        self._filter_banner.show()
        # Scroll to first visible row
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.scrollToItem(
                    self.table.item(row, 0),
                    self.table.ScrollHint.PositionAtTop
                )
                break

    def clear_guid_filter(self):
        """Remove the GUID filter and show all rows again."""
        self._guid_filter = set()
        self._filter_banner.hide()
        self.filter_table()   # re-applies search text only

    def current_datetime(self):
        return datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')

    def get_file_modify_date(self, file_path):
        try:
            if file_path and os.path.exists(file_path):
                # File ki modification date nikalna
                mtime = os.path.getmtime(file_path)
                return datetime.datetime.fromtimestamp(mtime).strftime('%d-%m-%Y %H:%M:%S')
        except Exception:
            pass
        return ""

    # --- HELPER: Calc Lenth ---
    def calc_length_from_size(self, size_str):
        # Always default to "1|0" (Auto Height)
        # 1 = One extra column (total 2 cols)
        # 0 = Auto Vertical Height (calculated based on num sizes in Logic)
        return "1|0"

    # --- NAYA: Manual Edit Save karne ka logic ---
    def on_row_changed(self, current, previous):
        if current.isValid():
            self.show_preview(current.row(), current.column())

    def save_cell_to_db(self, item):
        if self.table.signalsBlocked(): return
        
        # RBAC: Block edits if user lacks permission
        session = getattr(self, '_user_session', None)
        if session and not session.can("final_data.edit"):
            # Revert the change silently
            old = item.data(Qt.ItemDataRole.UserRole)
            if old is not None:
                self.table.blockSignals(True)
                item.setText(str(old))
                self.table.blockSignals(False)
            return
        
        # ── Display-label guard ──────────────────────────────────────────
        # The Image_Path column shows visual labels ("✅ FOUND", "❌ NOT FOUND",
        # "NO NEED", "⚠️ DUPLICATE") instead of the real file path.  These are
        # set during refresh_table and must NEVER be persisted to the DB.
        # If Qt fires itemChanged for one of these labels (e.g. user clicks,
        # drags, or pastes over the cell), silently discard the event.
        DISPLAY_ONLY_LABELS = {"✅ FOUND", "❌ NOT FOUND", "NO NEED", "⚠️ DUPLICATE"}
        raw_text = item.text().strip()
        if raw_text in DISPLAY_ONLY_LABELS:
            return

        new_val = raw_text
        old_val = item.data(Qt.ItemDataRole.UserRole)
        row, col = item.row(), item.column()
        col_name = self.headers[col]
        
        logger.debug(f"[SAVE_CELL] col={col} ({col_name}), new_val='{new_val}', old_val='{old_val}'")

        # --- VALIDATION: True/False Column (Index 21) ---
        if col == 21: # True/False Column
            lower_val = new_val.lower()
            
            # Check for Image Path "no_need" condition
            img_path_item = self.table.item(row, self.col_index("Image_Path"))
            img_path_val = img_path_item.data(Qt.ItemDataRole.UserRole) if img_path_item else ""
            
            if "no_need" in str(img_path_val).lower() or "no need" in str(img_path_val).lower():
                final_bool_val = "false"
            elif lower_val == "":
                final_bool_val = ""
            elif lower_val in ["0"] or lower_val.startswith("f") or lower_val.startswith("n"):
                # Any input starting with 'f' (false, flase, fals, fa, etc.)
                # or 'n' (no, noo, nah, etc.) or '0' → autocorrect to false
                final_bool_val = "false"
            elif lower_val in ["1", "true", "t", "yes"] or lower_val.startswith("t") or lower_val.startswith("y"):
                final_bool_val = "1"
            else:
                 # Unknown input → Default to "1"
                 final_bool_val = "1"
            
            if final_bool_val != new_val:
                self.table.blockSignals(True)
                item.setText(final_bool_val)
                self.table.blockSignals(False)
                new_val = final_bool_val # Update variable for DB save

            # known_layout_products table was removed in catalog v2 rewrite.
            # No need to clean it up anymore.

            self.update_summary_stats() # Update counts on change

        # --- NAYA: Auto-Update Lenth if Product_Size changes ---
        if col_name == "Product_Size":
             # Recalculate Lenth
             new_len = self.calc_length_from_size(new_val)
             
             # Setup Update for Lenth too
             # We need to update DB for Lenth AND Product_Size
             # Doing separate update for Lenth to keep simple logic or combine?
             # Simple: Update Product_Size first (below), then Update Lenth.
             pass 

        # Check if actual change happened (after normalization)
        if str(new_val) == str(old_val):
            return

        # --- UPDATE DATE TRIGGER ---
        # List of columns that trigger update_date
        trigger_cols = [
            "Product Name", "Product_Size", "Category", "Unit", "MOQ", 
            "M_Packing", "MRP", "MG_SN", "Group", "SG_SN", "Sub_Group", 
            "Image_Path", "Lenth", "Image_Date", "True/False"
        ]
        
        should_update_date = col_name in trigger_cols
        
        try:
            guid_item = self.table.item(row, 0)
            if not guid_item: return
            guid = guid_item.text()

            now = self.current_datetime()

            conn = self.db.get_connection(self.final_db_name)
            if not conn:
                return
            cur = conn.cursor()
            
            if should_update_date:
                cur.execute(f"UPDATE catalog SET [{col_name}]=?, Update_date=? WHERE GUID=?", (new_val, now, guid))
            else:
                cur.execute(f"UPDATE catalog SET [{col_name}]=? WHERE GUID=?", (new_val, guid))
            
            # --- If Image_Path was just set to 'no need', force True/False to 'false' ---
            if col_name == "Image_Path":
                if "no_need" in new_val.lower() or "no need" in new_val.lower() or "noneed" in new_val.lower():
                    cur.execute("UPDATE catalog SET [True/False]='false' WHERE GUID=?", (guid,))
                    # Also update the UI
                    tf_col = self.col_index("True/False")
                    self.table.blockSignals(True)
                    tf_item = self.table.item(row, tf_col)
                    if tf_item:
                        tf_item.setText("false")
                    self.table.blockSignals(False)
                
            # --- Post-Update Logic: Update Lenth if Size Changed ---
            if col_name == "Product_Size":
                 new_len = self.calc_length_from_size(new_val)
                 cur.execute("UPDATE catalog SET Lenth=? WHERE GUID=?", (new_len, guid))
                 
                 # UI Update
                 len_col = self.col_index("Lenth")
                 self.table.blockSignals(True)
                 self.table.setItem(row, len_col, QTableWidgetItem(new_len))
                 self.table.blockSignals(False)
                 if hasattr(self, 'status_lbl') and self.status_lbl:
                     self.status_lbl.setText(f"Updated: Size & Lenth ({new_len})")

            # Single atomic commit for main column + any post-update changes
            conn.commit()

            item.setData(Qt.ItemDataRole.UserRole, new_val) # Update memory

            if should_update_date:
                self.table.blockSignals(True)
                self.table.setItem(row, self.col_index("Update_date"), QTableWidgetItem(now))
                self.table.blockSignals(False)
            
            if hasattr(self, 'status_lbl') and self.status_lbl:
                if col_name != "Product_Size":  # Size already set a specific label above
                    self.status_lbl.setText(f"Updated: {col_name}" + (f" & Date at {now}" if should_update_date else ""))
            
            # Refresh stats if needed
            # print("DEBUG: Cell Save - Updating Summary Stats")
            self.update_summary_stats()

        except Exception as e:
            logger.error(f"Update Error: {e}", exc_info=True)

    def load_and_sync_data(self, company_name, company_path=None):
        """Entry point: resolves paths, then starts background sync worker."""
        logger.info(f"Data sync started: company='{company_name}'")
        try:
            # 1. Path Setup (fast — stays on main thread)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            folder_path = company_path
            self.image_folder = ""
            
            if not folder_path or not os.path.exists(folder_path):
                 logger.error(f"Invalid Company Path: {folder_path}")
                 return

            # Read company_info.json for Image Path
            info_file = os.path.join(folder_path, "company_info.json")
            if os.path.exists(info_file):
                 try:
                     with open(info_file, 'r', encoding='utf-8') as f:
                         info = json.load(f)
                         if "image_path" in info: self.image_folder = info["image_path"]
                 except Exception: pass

            self.db_path = os.path.join(folder_path, "final_data.db")
            self.super_master_path = os.path.join(os.path.dirname(folder_path), "super_master.db")

            # 2. Show progress dialog and start background worker
            self._sync_progress = QProgressDialog("Syncing Final Data...", "Cancel", 0, 0, self)
            self._sync_progress.setWindowTitle("Processing")
            self._sync_progress.setWindowModality(Qt.WindowModality.WindowModal)
            self._sync_progress.setMinimumDuration(0)
            self._sync_progress.setMinimumWidth(320)
            self._sync_progress.show()
            QApplication.processEvents()

            # Prevent concurrent syncs
            if self._sync_worker and self._sync_worker.isRunning():
                self._sync_progress.close()
                return

            self._sync_worker = FinalDataSyncWorker(self, folder_path, company_name)
            self._sync_worker.progress.connect(self._on_sync_progress)
            self._sync_worker.finished.connect(self._on_sync_finished)
            self._sync_worker.error.connect(self._on_sync_error)
            self._sync_progress.canceled.connect(self._on_final_sync_cancel)
            self._sync_worker.start()

        except Exception as e:
            logger.error(f"Sync Setup Error: {e}", exc_info=True)
            import traceback
            traceback.print_exc()

    def remap_from_super_master(self, folder_path=None):
        """Quick re-map: update MG_SN/Group/SG_SN in catalog from current Super Master data.
        
        Called after Super Master edits — much faster than a full Tally sync
        because it only updates the group columns, not all product data.
        """
        if not folder_path:
            folder_path = getattr(self, 'company_path', '') or getattr(self, 'folder_path', '')
        if not folder_path:
            return 0
        
        db = get_db_manager()
        company_name = os.path.basename(folder_path)
        final_db = build_logical_name(company_name, company_path=folder_path)
        _data_path = os.path.dirname(folder_path)
        _super_db = build_shared_db_name(DB_SUPER, _data_path) if _data_path else DB_SUPER
        
        try:
            # Read Super Master mapping
            s_conn = db.get_connection(_super_db)
            if not s_conn:
                return 0
            s_cursor = s_conn.cursor()
            s_cursor.execute("SELECT Sub_Group, MG_SN, Group_Name, SG_SN FROM super_master")
            super_mapping = {}
            for r in s_cursor.fetchall():
                super_mapping[r[0]] = (r[1], r[2], r[3])
            
            if not super_mapping:
                return 0
            
            # Batch update catalog: set MG_SN/Group/SG_SN based on Sub_Group
            final_conn = db.get_connection(final_db)
            if not final_conn:
                return 0
            cur = final_conn.cursor()
            
            updated = 0
            for sub_group, (mg_sn, group_name, sg_sn) in super_mapping.items():
                cur.execute("""
                    UPDATE catalog SET MG_SN=?, [Group]=?, SG_SN=?, Update_date=?
                    WHERE Sub_Group=? AND (
                        ISNULL(MG_SN,'') != ? OR ISNULL([Group],'') != ? OR ISNULL(SG_SN,'') != ?
                    )
                """, (mg_sn, group_name, sg_sn, self.current_datetime(),
                      sub_group, str(mg_sn), str(group_name), str(sg_sn)))
                updated += cur.rowcount
            
            final_conn.commit()
            logger.info(f"Re-mapped {updated} items from Super Master")
            
            if updated > 0:
                self._last_data_hash = None  # Invalidate cache
            
            return updated
        except Exception as e:
            logger.error(f"remap_from_super_master error: {e}", exc_info=True)
            return 0

    def _on_final_sync_cancel(self):
        """Handle cancel button click on Final Data sync progress."""
        logger.info("Final Data sync cancelled by user")
        if self._sync_worker:
            self._sync_worker.cancel()

    def _run_sync_pipeline(self, folder_path, company_name, progress_signal, cancel_check=None):
        """Heavy sync work — runs in background thread. No widget access allowed.
        Returns the sync label text string."""
        import time
        _pipeline_start = time.perf_counter()

        def emit(msg):
            if progress_signal:
                progress_signal.emit(msg)

        def check_cancelled():
            if cancel_check and cancel_check():
                raise _SyncCancelled()

        def elapsed(label, _ref=[_pipeline_start]):
            """Log seconds since pipeline start AND since last checkpoint."""
            now = time.perf_counter()
            total = now - _pipeline_start
            since_last = now - _ref[0]
            _ref[0] = now
            logger.info(f"[TIMING] {label}: +{since_last:.2f}s (total {total:.2f}s)")



        check_cancelled()
        emit("Creating database tables...")
        # Ensure final_data DB exists
        company_name_from_path = os.path.basename(folder_path)
        final_db = build_logical_name(company_name_from_path, company_path=folder_path)
        row_db = build_logical_name(company_name_from_path, company_path=folder_path)
        db = get_db_manager()
        db.ensure_database_exists(final_db, folder_path, company_name=company_name_from_path)
        
        # Ensure catalog table
        col_defs = ', '.join([f'[{h}] NVARCHAR(MAX)' for h in self.headers])
        db.ensure_table(final_db, "catalog", f"CREATE TABLE catalog ({col_defs})")
        # Ensure unique index on GUID
        try:
            conn_check = db.get_connection(final_db)
            if conn_check:
                cursor_check = conn_check.cursor()
                try:
                    # SQL Server will abort the transaction if this fails, so we must rollback
                    cursor_check.execute("""
                        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'idx_guid' AND object_id = OBJECT_ID('catalog'))
                        BEGIN
                            CREATE UNIQUE INDEX idx_guid ON catalog (GUID)
                        END
                    """)
                    conn_check.commit()
                except Exception:
                    conn_check.rollback()
        except Exception:
            pass
        elapsed("DB setup")
        
        final_conn = db.get_connection(final_db)
        if not final_conn:
            return "Last Sync: Error - Cannot connect to DB"
        cur = final_conn.cursor()

        # Super Master Mapping
        check_cancelled()
        emit("Reading Super Master data...")
        super_mapping = {}
        try:
            _data_path = os.path.dirname(folder_path)
            _super_db = build_shared_db_name(DB_SUPER, _data_path) if _data_path else DB_SUPER
            s_conn = db.get_connection(_super_db)
            if s_conn:
                s_cursor = s_conn.cursor()
                s_cursor.execute("SELECT Sub_Group, MG_SN, Group_Name, SG_SN FROM super_master")
                for r in s_cursor.fetchall():
                    super_mapping[r[0]] = (r[1], r[2], r[3])
        except Exception as e:
            logger.error(f"Super Master Read Error: {e}", exc_info=True)
        elapsed("Super Master read")

        # Tally Data Fetch
        check_cancelled()
        emit("Reading Tally data...")
        row_conn = db.get_connection(row_db)
        if not row_conn:
            return "Last Sync: Error - Cannot connect to RowData DB"
        row_cursor = row_conn.cursor()

        # Guard: stock_items table may not exist if Tally sync has never been run
        row_cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'stock_items'"
        )
        if row_cursor.fetchone()[0] == 0:
            return "Last Sync: No Tally data yet — run \"Sync Tally\" first"

        # Detect actual column names using INFORMATION_SCHEMA
        row_cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'stock_items'
        """)
        col_names = {r[0] for r in row_cursor.fetchall()}
        
        # Build column mapping for query: use actual column name, alias to expected
        def col_or_fallback(expected, fallback):
            if expected in col_names:
                return expected
            if fallback in col_names:
                return f'[{fallback}] AS [{expected}]'
            return f"NULL AS [{expected}]"
        
        select_cols = ", ".join([
            col_or_fallback("GUID", "$GUID"),
            col_or_fallback("Item_Name", "$Name"),
            col_or_fallback("FirstAlias", "$_FirstAlias"),
            col_or_fallback("Part_No", "$MailingName"),
            col_or_fallback("Category", "$Category"),
            col_or_fallback("Unit", "$BaseUnits"),
            col_or_fallback("SubGroup", "$Parent"),
            col_or_fallback("MRP", "$StandardPrice"),
            col_or_fallback("Closing_Qty", "$_ClosingBalance"),
        ])
        rows = row_cursor.execute(f"SELECT {select_cols} FROM stock_items").fetchall()
        elapsed(f"stock_items fetch ({len(rows)} rows)")

        # Identify items removed from Tally (delete AFTER inserts/updates for safety)
        check_cancelled()
        emit("Checking for removed items...")
        tally_guids_set = {r[0] for r in rows}
        cur.execute("SELECT GUID FROM catalog")
        catalog_guids = [row[0] for row in cur.fetchall()]
        guids_to_delete = [g for g in catalog_guids if g not in tally_guids_set]

        now = self.current_datetime()

        # Calculate sync label (using current time since DB is on SQL Server now)
        sync_label = f"Last Sync: {now}"

        # Pre-fetch ALL existing catalog rows into a dict keyed by GUID
        # This eliminates ~2000 individual SELECT queries
        cur.execute("""
            SELECT GUID, Item_Name, Alias, Part_No, Category, Unit,
                   MRP, Stock, MG_SN, [Group], SG_SN, Sub_Group
            FROM catalog
        """)
        existing_rows = {}
        for erow in cur.fetchall():
            existing_rows[erow[0]] = erow[1:]  # GUID → (Item_Name, Alias, ...)
        elapsed("catalog pre-fetch")

        # Pre-build INSERT query once (reused for all new items)
        insert_placeholders = ', '.join(['?'] * len(self.headers))
        insert_cols = ', '.join([f"[{h}]" for h in self.headers])
        insert_query = f"INSERT INTO catalog ({insert_cols}) VALUES ({insert_placeholders})"

        # Main sync loop — batch UPDATE and INSERT for speed
        check_cancelled()
        emit(f"Syncing {len(rows)} items...")
        update_rows = []  # (Item_Name, Alias, Part_No, Category, Unit, MRP, Stock, MG_SN, Group, SG_SN, Sub_Group, Update_date, GUID)
        insert_rows = []  # full row tuples
        price_list_resets = []  # GUIDs to reset True/False
        
        for r in rows:
            guid = r[0]
            sub_group_name = r[6]
            s_data = super_mapping.get(sub_group_name, ("", "", ""))

            old_row_db = existing_rows.get(guid)

            new_row = tuple("" if v is None else str(v) for v in (
                r[1], r[2], r[3], r[4], r[5],
                r[7], r[8],
                s_data[0], s_data[1], s_data[2],
                r[6],
            ))

            if old_row_db:
                old_row_norm = tuple("" if v is None else str(v) for v in old_row_db)
                # Compare excluding Part_No (index 2) — it is not visible on the
                # catalog PDF so a Part_No-only change must NOT mark pages dirty
                # or trigger CRM updates. Part_No is still persisted in the DB.
                _CMP = (0, 1, 3, 4, 5, 6, 7, 8, 9, 10)
                if tuple(old_row_norm[i] for i in _CMP) != tuple(new_row[i] for i in _CMP):
                    update_rows.append((*new_row, now, guid))
                    
                    # Check if reverting from Price List / MG_SN >= 90
                    old_group = str(old_row_db[8]).lower().strip() if old_row_db[8] else ""
                    new_group = str(s_data[1]).lower().strip() if s_data[1] else ""
                    try: old_mg = int(str(old_row_db[7]).strip())
                    except (ValueError, TypeError): old_mg = 0
                    try: new_mg = int(str(s_data[0]).strip())
                    except (ValueError, TypeError): new_mg = 0
                    
                    if (old_group == "price list" or old_mg >= 90) and (new_group != "price list" and new_mg < 90):
                        price_list_resets.append((guid,))
            else:
                # New item — build INSERT row
                f_row = [None] * len(self.headers)
                f_row[self.col_index("GUID")] = guid
                f_row[self.col_index("Item_Name")] = r[1]
                f_row[self.col_index("Alias")] = r[2]
                f_row[self.col_index("Part_No")] = r[3]
                f_row[self.col_index("Category")] = r[4]
                f_row[self.col_index("Unit")] = r[5]
                f_row[self.col_index("MRP")] = r[7]
                f_row[self.col_index("Stock")] = r[8]
                f_row[self.col_index("MG_SN")] = s_data[0]
                f_row[self.col_index("Group")] = s_data[1]
                f_row[self.col_index("SG_SN")] = s_data[2]
                f_row[self.col_index("Sub_Group")] = r[6]
                f_row[self.col_index("Lenth")] = "1"
                f_row[self.col_index("Update_date")] = now
                insert_rows.append(f_row)
        elapsed(f"diff loop ({len(update_rows)} updates, {len(insert_rows)} inserts)")

        # Batch execute — ~2 round trips instead of ~2000
        if hasattr(cur, 'fast_executemany'):
            cur.fast_executemany = True
        
        if update_rows:
            emit(f"Updating {len(update_rows)} changed items...")
            update_query = """UPDATE catalog SET
                Item_Name=?, Alias=?, Part_No=?, Category=?, Unit=?,
                MRP=?, Stock=?, MG_SN=?, [Group]=?, SG_SN=?, Sub_Group=?,
                Update_date=?
                WHERE GUID=?"""
            cur.executemany(update_query, update_rows)
        
        if insert_rows:
            emit(f"Inserting {len(insert_rows)} new items...")
            cur.executemany(insert_query, insert_rows)
        
        if price_list_resets:
            cur.executemany("UPDATE catalog SET [True/False]='' WHERE GUID=?", price_list_resets)

        # Delete removed items AFTER successful inserts/updates
        # This order ensures a crash mid-sync never loses items permanently
        if guids_to_delete:
            emit(f"Removing {len(guids_to_delete)} deleted items...")
            for i in range(0, len(guids_to_delete), 500):
                chunk = guids_to_delete[i:i+500]
                placeholders = ','.join(['?'] * len(chunk))
                cur.execute(f"DELETE FROM catalog WHERE GUID IN ({placeholders})", chunk)
        elapsed(f"catalog UPSERT/DELETE to SQL Server")

        # Processor — run WITHOUT auto-commit (shares same connection)
        check_cancelled()
        emit("Processing product names...")
        processor = DataProcessor(final_db)
        # Pass cancel_check so processor can bail out between internal phases
        _cancel_fn = cancel_check if cancel_check else None
        processor.process_and_save_final_data(auto_commit=False, cancel_check=_cancel_fn)
        elapsed("DataProcessor.process_and_save_final_data")

        check_cancelled()
        emit("Generating complex IDs...")
        processor.generate_complex_ids(auto_commit=False, cancel_check=_cancel_fn)
        elapsed("DataProcessor.generate_complex_ids")

        # Image Sync
        check_cancelled()
        emit("Syncing images...")
        dup_map = self.sync_images_after_processing()
        elapsed("sync_images_after_processing (incl. True/False sync)")

        # === SINGLE ATOMIC COMMIT ===
        # Everything above runs in one uncommitted transaction.
        # This single commit makes ALL changes visible at once.
        # If cancelled at any checkpoint above, _SyncCancelled is raised
        # and the except block in the worker does rollback().
        check_cancelled()
        final_conn.commit()
        elapsed("final commit")
        emit("Sync complete!")
        logger.info(f"[TIMING] === Full pipeline done in {time.perf_counter() - _pipeline_start:.2f}s ===")

        return sync_label, (dup_map or {})

    def _on_sync_progress(self, msg):
        """Update progress dialog label from worker signal."""
        if hasattr(self, '_sync_progress') and self._sync_progress:
            self._sync_progress.setLabelText(msg)

    def _on_sync_finished(self, sync_label, dup_map):
        """Called on main thread when background sync completes."""
        if hasattr(self, '_sync_progress') and self._sync_progress:
            # Disconnect canceled BEFORE close() — QProgressDialog in indeterminate
            # mode (max=0) emits canceled() on close(), which would incorrectly
            # trigger _on_final_sync_cancel and emit sync_cancelled on a successful sync.
            try:
                self._sync_progress.canceled.disconnect(self._on_final_sync_cancel)
            except (TypeError, RuntimeError):
                pass
            self._sync_progress.close()

        # Handle cancellation
        if sync_label == "cancelled":
            logger.info("Final Data sync was cancelled — existing data preserved")
            self._sync_worker = None
            self.sync_cancelled.emit()  # NOT sync_complete — so "Sync Done" popup is skipped
            return

        # Set duplicate image map on main thread (safe for show_preview to read)
        self._duplicate_images = dup_map

        self.sync_lbl.setText(sync_label)

        logger.debug("Attempting to refresh table...")
        try:
            self._last_data_hash = None  # Invalidate cache — force full refresh after sync
            self.refresh_table(force=True)
            logger.debug("Table refresh completed successfully")
        except Exception as e:
            logger.error(f"Refresh table failed: {e}", exc_info=True)

        self._sync_worker = None
        self.sync_complete.emit()

    def _on_sync_error(self, error_msg):
        """Called on main thread when background sync fails."""
        if hasattr(self, '_sync_progress') and self._sync_progress:
            try:
                self._sync_progress.canceled.disconnect(self._on_final_sync_cancel)
            except (TypeError, RuntimeError):
                pass
            self._sync_progress.close()
        logger.error(f"Sync Error: {error_msg}")
        self._sync_worker = None
        self.sync_complete.emit()
            
    def sync_images_after_processing(self):
        """Syncs image paths to catalog after processing.
        Returns dup_map so the caller can set self._duplicate_images
        on the main thread (avoids cross-thread write to a UI attribute).

        Optimized:
        - Batched executemany() instead of per-row round-trips.
        - File-date cached per unique path (avoids redundant os.stat calls).
        - Skip-if-unchanged: rows whose Image_Path already matches the
          resolved path are excluded from both UPDATE batches, cutting
          DB writes to zero on a sync where nothing changed.
        """
        try:
            conn = self.db.get_connection(self.final_db_name)
            if not conn:
                return {}
            img_map, dup_map = self.get_image_mapping()
            # NOTE: Do NOT write self._duplicate_images here — this method
            # is called from the background thread. The caller (_on_sync_finished)
            # sets self._duplicate_images on the main thread using the returned value.
            cursor = conn.cursor()
            # Fetch current path too so we can skip unchanged rows
            cursor.execute("SELECT GUID, Image_Name, Image_Path, Image_Date FROM catalog")
            rows = cursor.fetchall()

            # Cache file-modify dates per unique path (avoids redundant os.stat calls
            # when many catalog rows share the same image file)
            _date_cache = {}

            found_updates   = []  # (path, date, guid) — path changed or newly matched
            missing_updates = []  # (guid,)            — no image and path not already empty
            skipped         = 0

            for rid, img_name, current_path, current_date in rows:
                clean = img_name.lower().strip() if img_name else ""
                current_path = current_path or ""

                if clean in img_map:
                    path = img_map[clean]
                    if path not in _date_cache:
                        _date_cache[path] = self.get_file_modify_date(path)
                    new_date = _date_cache[path]
                    if path == current_path and new_date == (current_date or ""):
                        skipped += 1   # path AND date unchanged — truly nothing to write
                        continue
                    # Path changed OR same path but image was replaced (mtime differs)
                    found_updates.append((path, new_date, rid))
                else:
                    if current_path == "":
                        skipped += 1   # already empty — nothing to write
                        continue
                    missing_updates.append((rid,))

            # Two batched round-trips instead of N individual ones
            if hasattr(cursor, 'fast_executemany'):
                cursor.fast_executemany = True
            if found_updates:
                cursor.executemany(
                    "UPDATE catalog SET Image_Path=?, Image_Date=? WHERE GUID=?",
                    found_updates
                )
            if missing_updates:
                cursor.executemany(
                    "UPDATE catalog SET Image_Path='', Image_Date='' WHERE GUID=?",
                    missing_updates
                )
            # NOTE: No commit here — the pipeline's final commit handles everything.
            # This keeps all sync steps in one atomic transaction.
            logger.info(
                f"Image sync: {len(found_updates)} updated, "
                f"{len(missing_updates)} cleared, {skipped} skipped (unchanged)"
            )

            # After image sync, update True/False values
            self.sync_true_false_values()
            return dup_map
        except Exception as e:
            logger.error(f"Image Sync Error: {e}", exc_info=True)
            return {}
    
    def sync_true_false_values(self):
        """
        Update True/False column based on image availability ONLY.
        Stock-based inclusion is handled dynamically by the SQL query (Empty + Stock > 0).

        Logic:
        - If Image_Path contains 'no_need' / 'noneed' / 'no need'  -> 'false'
        - If [Group] = 'price list'                                 -> 'false'
        - Otherwise                                                 -> keep existing value

        Optimized: pure SET-BASED SQL — no Python row loop, no per-row round-trips.
        3 SQL statements replace N individual UPDATE calls.
        """
        try:
            if not self.final_db_name:
                return

            conn = self.db.get_connection(self.final_db_name)
            if not conn:
                return
            cursor = conn.cursor()

            # Rule 1: Image_Path contains a 'no need' variant → force 'false'
            cursor.execute("""
                UPDATE catalog
                SET [True/False] = 'false'
                WHERE (
                    LOWER(ISNULL(Image_Path, '')) LIKE '%no_need%'
                    OR LOWER(ISNULL(Image_Path, '')) LIKE '%noneed%'
                    OR LOWER(ISNULL(Image_Path, '')) LIKE '%no need%'
                )
                AND LOWER(LTRIM(RTRIM(ISNULL([True/False], '')))) != 'false'
            """)

            # Rule 2: Price List group → force 'false'
            cursor.execute("""
                UPDATE catalog
                SET [True/False] = 'false'
                WHERE LOWER(LTRIM(RTRIM(ISNULL([Group], '')))) = 'price list'
                AND LOWER(LTRIM(RTRIM(ISNULL([True/False], '')))) != 'false'
            """)

            # Fix Lenth column defaults in the same transaction
            # (was a separate commit before — merged here to save one round-trip)
            cursor.execute("""
                UPDATE catalog
                SET Lenth = '1|0'
                WHERE LTRIM(RTRIM(ISNULL(Lenth, ''))) IN ('', '1')
            """)

            # NOTE: No commit here — the pipeline's final commit handles everything.
            logger.debug("True/False sync completed (set-based SQL)")

        except Exception as e:
            logger.error(f"True/False Sync Error: {e}", exc_info=True)

    def refresh_table(self, force=False):
        """Launch background worker to fetch/sort data, then populate table on main thread.
        Skips entirely if data hasn't changed since last refresh (instant tab switch)."""
        logger.debug("CALLED: refresh_table")
        if not self.final_db_name: 
            logger.warning("ABORT: No final_db_name in refresh_table")
            return
        
        # Prevent concurrent refreshes.
        # If force=True (e.g. called from auto-image-sync callback), remember it so
        # we run again immediately after the current refresh finishes.
        if self._refresh_worker and self._refresh_worker.isRunning():
            if force:
                self._pending_refresh = True   # will be honoured in _on_refresh_data_ready
                logger.debug("refresh_table: worker busy — queued pending refresh")
            return
        self._pending_refresh = False
        
        # --- Restore last sync label from DB on startup (so it's never "N/A" if data exists) ---
        if self.sync_lbl.text() == "Last Sync: N/A":
            try:
                conn = self.db.get_connection(self.final_db_name)
                if conn:
                    row = conn.cursor().execute(
                        "SELECT MAX(Update_date) FROM catalog"
                    ).fetchone()
                    if row and row[0]:
                        self.sync_lbl.setText(f"Last Sync: {row[0]}")
            except Exception:
                pass
        
        # --- CACHE CHECK: skip if data unchanged ---
        if not force and self._last_data_hash is not None and self.table.rowCount() > 0:
            try:
                conn = self.db.get_connection(self.final_db_name)
                if conn:
                    cursor = conn.cursor()
                    # Fast count + checksum: if row count same, data likely unchanged
                    row_count = cursor.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] or 0
                    if row_count == self._last_data_hash:
                        logger.debug("Cache HIT: data unchanged, skipping refresh")
                        return
            except Exception:
                pass  # On error, proceed with full refresh
        
        # Show loading state
        self.table.setRowCount(0)
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        
        self._refresh_worker = RefreshWorker(self)
        self._refresh_worker.finished.connect(self._on_refresh_data_ready)
        self._refresh_worker.error.connect(self._on_refresh_error)
        self._refresh_worker.start()

    def _on_refresh_error(self, error_msg):
        """Handle refresh worker failure."""
        logger.error(f"Refresh worker failed: {error_msg}")
        self.table.blockSignals(False)
        self._refresh_worker = None

    def _on_refresh_data_ready(self, final_display_data, right_align_indices, col_indices):
        """Populate table from pre-sorted data (runs on main thread, fast)."""
        try:
            # No Tally data yet — table doesn't exist, show empty grid cleanly
            if not col_indices:
                self.table.setRowCount(0)
                self.table.blockSignals(False)
                self.table.setSortingEnabled(True)
                self._refresh_worker = None
                self.sync_lbl.setText("Last Sync: No data — run Sync Tally first")
                return

            grp_idx, path_idx = col_indices

            # Pre-allocate all rows at once (single layout recalc instead of N)
            self.table.setRowCount(len(final_display_data))


            for r_idx, r_val in enumerate(final_display_data):
                
                # Image missing color logic
                is_row_missing = False
                grp_name = str(r_val[grp_idx]).lower().strip()
                path_val = str(r_val[path_idx]) if r_val[path_idx] else ""
                if grp_name != "price list" and (not path_val or not os.path.exists(path_val)):
                    is_row_missing = True
                    
                for c_idx, val in enumerate(r_val):
                    clean_val = str(val if val is not None else "")
                    
                    # Numeric sorting logic (MRP aur Stock ke liye)
                    if c_idx in [11, 12]:
                        item = NumericTableWidgetItem(clean_val)
                    else:
                        item = QTableWidgetItem(clean_val)
                    
                    # --- SMART LOGIC: Purani value ko UserRole mein save karna ---
                    # Yeh line save_cell_to_db ko comparison karne mein madad karegi
                    item.setData(Qt.ItemDataRole.UserRole, clean_val)
                    
                    # --- EDITABLE FLAGS ---
                    editable_indices = [19, 21] # Lenth aur True/False column
                    if c_idx in editable_indices:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    
                    # Image Status Display (Column 18)
                    if c_idx == path_idx:
                        item.setData(Qt.ItemDataRole.UserRole, path_val)
                        # Get Image_Name for duplicate check
                        img_name_idx = self.col_index("Image_Name")
                        img_name_key = str(r_val[img_name_idx]).lower().strip() if r_val[img_name_idx] else ""
                        dup_map = getattr(self, '_duplicate_images', {})
                        has_duplicate = img_name_key and img_name_key in dup_map

                        if grp_name == "price list":
                             # User Requirement: Price List items display "NO NEED" (Green).
                             # This is strictly visual. Underlying UserRole keeps original path.
                            item.setText("NO NEED"); item.setForeground(QColor("green"))
                        elif is_row_missing:
                            item.setText("❌ NOT FOUND"); item.setForeground(QColor("red"))
                        elif has_duplicate:
                            item.setText("⚠️ DUPLICATE"); item.setForeground(QColor("#e67e00"))
                            item.setBackground(QColor("#fff3cd"))
                        else:
                            item.setText("✅ FOUND"); item.setForeground(QColor("green"))

                    if is_row_missing:
                        item.setBackground(QColor(255, 0, 0))
                        item.setForeground(QColor(255, 255, 255))
                    
                    if c_idx in right_align_indices:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    
                    self.table.setItem(r_idx, c_idx, item)
            
            # Cache the row count for change detection
            self._last_data_hash = len(final_display_data)

            # If a forced refresh was requested while we were running, do it now
            if getattr(self, '_pending_refresh', False):
                self._pending_refresh = False
                self._last_data_hash = None     # ensure full re-read
                logger.debug("_on_refresh_data_ready: executing pending forced refresh")
                self.refresh_table(force=True)
            
            # Set column widths once (not on every refresh)
            if not self._columns_sized:
                self._columns_sized = True
                self.table.resizeColumnsToContents()
            
            # Re-enable signals so itemChanged fires on user edits
            self.table.blockSignals(False)
            # NOTE: Do NOT call setSortingEnabled(True) here.
            # It causes Qt to re-sort by the last column header click,
            # which destroys our custom missing-images-first ordering.
            
            self.update_summary_stats()
        except Exception as e: 
            self.table.blockSignals(False)  # Always unblock on error too
            logger.error(f"Refresh Error: {e}", exc_info=True)
        finally:
            self._refresh_worker = None

    def update_summary_stats(self):
        """Calculate and update the summary statistics in the side panel.
           RE-WRITTEN as per user request to ensure correctness and add debug.
        """
        # print("CALLED: update_summary_stats") # DEBUG TRACE
        try:
            if not self.final_db_name:
                logger.debug("ABORT: final_db_name invalid")
                return
            
            logger.debug(f"Updating Summary Stats [DB: {self.final_db_name}]")
            conn = self.db.get_connection(self.final_db_name)
            if not conn:
                return
            cursor = conn.cursor()
            
            # 1. Final Data Total (Simple Count)
            final_data_total = cursor.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] or 0
            logger.debug(f"Final Total = {final_data_total}")

            # 2. Catalog Total (Passed Inclusion Logic)
            # TF is '1' OR (TF is Empty AND Stock > 0)
            catalog_total = cursor.execute("""
                SELECT COUNT(*) FROM catalog 
                WHERE (LOWER(LTRIM(RTRIM(CAST([True/False] AS NVARCHAR(MAX))))) IN ('1', 'true', 'yes'))
                OR (
                    (ISNULL(LTRIM(RTRIM([True/False])), '') = '') 
                    AND (ISNULL(CAST(REPLACE(REPLACE(Stock, ',', ''), ' ', '') AS FLOAT), 0) > 0)
                )
            """).fetchone()[0] or 0
            logger.debug(f"Catalog Total = {catalog_total}")
            
            # 3. Excluded by Stock (Stock <= 0 AND TF is Empty)
            out_of_stock = cursor.execute("""
                SELECT COUNT(*) FROM catalog 
                WHERE (ISNULL(CAST(REPLACE(REPLACE(Stock, ',', ''), ' ', '') AS FLOAT), 0) <= 0)
                AND (ISNULL(LTRIM(RTRIM([True/False])), '') = '')
            """).fetchone()[0] or 0
            logger.debug(f"Excluded (Stock) = {out_of_stock}")
            
            # 4. Manual False (Explicitly marked 'false', '0', 'no')
            false_items = cursor.execute("""
                SELECT COUNT(*) FROM catalog 
                WHERE LOWER(LTRIM(RTRIM(CAST([True/False] AS NVARCHAR(MAX))))) IN ('false', '0', 'no')
            """).fetchone()[0] or 0
            logger.debug(f"Manual False = {false_items}")
            
            # 5. Item Mismatch
            sum_parts = catalog_total + out_of_stock + false_items
            item_mismatch = final_data_total - sum_parts
            logger.debug(f"Mismatch = {item_mismatch} (Total {final_data_total} - Sum {sum_parts})")
            # Update labels
            self.lbl_catalog_total_val.setText(str(catalog_total))
            self.lbl_out_stock_val.setText(str(out_of_stock))
            self.lbl_false_val.setText(str(false_items))
            self.lbl_final_total_val.setText(str(final_data_total))
            
            # Special Visual for Mismatch
            self.lbl_mismatch_val.setText(str(item_mismatch))
            if item_mismatch != 0:
                self.lbl_mismatch_val.setProperty("alert", "true")
            else:
                self.lbl_mismatch_val.setProperty("alert", "false")
            self.lbl_mismatch_val.style().unpolish(self.lbl_mismatch_val)
            self.lbl_mismatch_val.style().polish(self.lbl_mismatch_val)

        except Exception as e:
            logger.error(f"Summary Stats Error: {e}", exc_info=True)

    # Aapke baaki functions (get_image_mapping, show_preview, show_path_popup, filter_table) 
    # backup code ke jaise hi kaam karenge...
    def get_image_mapping(self):
        """Scan image folder and return (image_map, duplicate_map).

        image_map: {name_lower: path} — last-seen path wins (legacy behaviour).
        duplicate_map: {name_lower: [path1, path2, ...]} — only names that appear ≥ 2 times.

        Optimized: result is cached by a folder fingerprint
        (total file count + latest mtime across the folder).  If neither
        changes between two syncs the expensive os.walk is skipped entirely.
        """
        if not self.image_folder or not os.path.exists(self.image_folder):
            return {}, {}

        # ── build folder fingerprint (filename + mtime + size) ───────────────
        # Including file size alongside mtime catches the common case where an
        # image is deleted and replaced with a new one of the same name but the
        # copy operation preserved the original timestamp (e.g. WhatsApp downloads,
        # robocopy /COPYALL, or network-share writes that round mtime).
        sigs = set()
        for root, _, files in os.walk(self.image_folder):
            for f in files:
                full = os.path.join(root, f)
                try:
                    st = os.stat(full)
                    mt = st.st_mtime
                    sz = st.st_size
                except OSError:
                    mt = 0.0
                    sz = 0
                sigs.add((f.lower(), mt, sz))
        fingerprint = (self.image_folder, hash(frozenset(sigs)))

        # ── return cached result if folder is unchanged ─────────────────────
        cached = getattr(self, '_img_map_cache', None)
        # cached[1] may be None if we stored only a fingerprint baseline (no full scan yet).
        if cached and cached[0] == fingerprint and cached[1] is not None:
            logger.debug("get_image_mapping: folder unchanged — returning cached result")
            return cached[1], cached[2]

        # ── full scan ───────────────────────────────────────────────────────
        image_map = {}
        all_hits  = {}   # name_lower → list of full paths
        for root, _, files in os.walk(self.image_folder):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    key       = os.path.splitext(file)[0].lower().strip()
                    full_path = os.path.join(root, file)
                    image_map[key] = full_path
                    all_hits.setdefault(key, []).append(full_path)

        dup_map = {k: v for k, v in all_hits.items() if len(v) >= 2}
        if dup_map:
            logger.warning(
                f"Duplicate image names detected: {len(dup_map)} names have multiple files"
            )

        # store cache
        self._img_map_cache = (fingerprint, image_map, dup_map)
        return image_map, dup_map

    # ── Auto-image sync (tab-switch trigger) ─────────────────────────────────

    def check_and_sync_images(self):
        """Check if the image folder changed since the last scan.

        Performs a fast fingerprint pre-check (file count + max mtime via
        os.walk).  If unchanged, returns False immediately — no worker started.
        If changed, starts AutoImageSyncWorker in the background.

        Returns:
            True  — sync worker was started (folder changed).
            False — nothing to do (folder unchanged, no DB, or another sync
                    is already in progress).
        """
        logger.info(
            f"AutoImageSync.check: image_folder='{self.image_folder}' "
            f"sync_running={bool(self._sync_worker and self._sync_worker.isRunning())} "
            f"auto_running={bool(getattr(self, '_auto_img_worker', None) and self._auto_img_worker.isRunning())}"
        )
        if not self.image_folder:
            logger.warning("AutoImageSync: image_folder is empty — set up image path in company settings")
            return False
        if not os.path.exists(self.image_folder):
            logger.warning(f"AutoImageSync: image_folder does not exist: '{self.image_folder}'")
            return False
        # Guard: never interfere with a running full Tally sync
        if self._sync_worker and self._sync_worker.isRunning():
            logger.info("AutoImageSync: skipping — full Tally sync in progress")
            return False
        # Guard: don't start a second auto-sync while one is running
        if getattr(self, '_auto_img_worker', None) and self._auto_img_worker.isRunning():
            logger.info("AutoImageSync: skipping — worker already running")
            return False

        # Fingerprint: hash(frozenset((filename_lower, mtime, size)))
        # Size is included alongside mtime so that replacing an image with a new
        # one of the same name (and preserved timestamp) is still detected.
        sigs = set()
        for root, _, files in os.walk(self.image_folder):
            for f in files:
                full = os.path.join(root, f)
                try:
                    st = os.stat(full)
                    mt = st.st_mtime
                    sz = st.st_size
                except OSError:
                    mt = 0.0
                    sz = 0
                sigs.add((f.lower(), mt, sz))
        new_fp = (self.image_folder, hash(frozenset(sigs)))

        cached = getattr(self, '_img_map_cache', None)
        old_fp = cached[0] if cached else None

        if old_fp is not None and old_fp == new_fp:
            logger.debug("AutoImageSync: folder unchanged — skipping")
            return False  # Folder unchanged — instant return, no worker

        # Either no baseline yet (old_fp is None) OR folder changed.
        # Both cases need a sync:
        #   - No baseline: ensures images already in folder on first run are picked up.
        #     The "skip unchanged rows" optimization makes this a no-op if DB is correct.
        #   - Folder changed: new/removed/renamed image detected.
        if old_fp is None:
            logger.info(
                f"AutoImageSync: no baseline — running initial sync "
                f"(files={len(sigs)}) to ensure DB is consistent with folder"
            )
        else:
            logger.info(
                f"AutoImageSync: folder changed "
                f"(hash {old_fp[1]} → {new_fp[1]}, files={len(sigs)}) — starting worker"
            )
        self._auto_img_worker = AutoImageSyncWorker(self)
        self._auto_img_worker.finished.connect(self._on_auto_img_sync_done)
        self._auto_img_worker.error.connect(
            lambda e: logger.error(f"AutoImageSync error: {e}")
        )
        self._auto_img_worker.start()
        return True

    def _on_auto_img_sync_done(self, dup_map):
        """Called on the main thread when AutoImageSyncWorker finishes.

        1. Refreshes the Final Data table (✅/❌ status column).
        2. Emits image_sync_done so main_window can rebuild the catalog if
           Catalog or Reports tab is currently visible.
        """
        self._auto_img_worker = None
        self._duplicate_images = dup_map
        self._last_data_hash = None   # Invalidate cache — force full DB re-read
        self.refresh_table(force=True)
        self.image_sync_done.emit()   # Notify main_window
        logger.info("AutoImageSync: done — table refresh + image_sync_done emitted")

    # ─────────────────────────────────────────────────────────────────────────

    def filter_table(self):

        txt = self.search_input.text().lower()
        guid_filter = getattr(self, '_guid_filter', set())

        # Charo columns ke sahi index nikaalein
        idx_alias = self.col_index("Alias")
        idx_cat = self.col_index("Category")
        idx_group = self.col_index("Group")
        idx_subgroup = self.col_index("Sub_Group")

        for i in range(self.table.rowCount()):
            # GUID filter: if active, hide rows not in set
            if guid_filter:
                guid_item = self.table.item(i, 0)
                if not guid_item or guid_item.text().strip() not in guid_filter:
                    self.table.setRowHidden(i, True)
                    continue

            it_alias = self.table.item(i, idx_alias)
            it_cat = self.table.item(i, idx_cat)
            it_group = self.table.item(i, idx_group)
            it_subgroup = self.table.item(i, idx_subgroup)
            
            # Text values (None check ke saath)
            val_alias = it_alias.text().lower() if it_alias else ""
            val_cat = it_cat.text().lower() if it_cat else ""
            val_group = it_group.text().lower() if it_group else ""
            val_subgroup = it_subgroup.text().lower() if it_subgroup else ""
            
            # Logic: Agar kisi bhi ek column mein search text mil jaye
            match = (txt in val_alias) or \
                    (txt in val_cat) or \
                    (txt in val_group) or \
                    (txt in val_subgroup)
            
            # Agar match hai toh row dikhayein (setRowHidden = False)
            self.table.setRowHidden(i, not match)
            
    def show_preview(self, row, col):
        # --- Duplicate image warning ---
        dup_map = getattr(self, '_duplicate_images', {})
        img_name_item = self.table.item(row, self.col_index("Image_Name"))
        img_name_key = img_name_item.text().lower().strip() if img_name_item else ""

        it = self.table.item(row, self.col_index("Image_Path"))
        if it:
            p = it.data(Qt.ItemDataRole.UserRole)
            if p and os.path.exists(p):
                pix = QPixmap(p)
                # Scale image to the DPI-independent logical height of the preview widget.
                preview_w = max(self.img_preview.width() - 10, 150)
                preview_h = getattr(self, '_img_preview_logical_h', 200) - 10
                scaled = pix.scaled(preview_w, preview_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.img_preview.setPixmap(scaled)

                # Show duplicate warning if applicable
                if img_name_key and img_name_key in dup_map:
                    paths = dup_map[img_name_key]
                    short_paths = [os.path.relpath(pp, self.image_folder) if self.image_folder else pp for pp in paths]
                    warn_text = f"⚠️ DUPLICATE ({len(paths)} files):\n" + "\n".join(short_paths)
                    self._dup_warning_lbl.setText(warn_text)
                    self._dup_warning_lbl.setVisible(True)
                else:
                    self._dup_warning_lbl.setVisible(False)
                return
        self.img_preview.setText("NO IMAGE")
        self.img_preview.setPixmap(QPixmap())
        self._dup_warning_lbl.setVisible(False)

    def show_path_popup(self, row, col):
        if col == self.col_index("Image_Path"):
            it = self.table.item(row, col)
            path = it.data(Qt.ItemDataRole.UserRole) if it else None
            
            if path and os.path.exists(path):
                # Open with system default viewer
                try:
                    os.startfile(path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not open image: {e}")
            else:
                 QMessageBox.information(self, "Info", f"No valid image path found.")


