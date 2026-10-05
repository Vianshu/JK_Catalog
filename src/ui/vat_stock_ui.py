"""
VAT Working — Stock Screen.

Contains:
1. Int. Stock (reusing stock_items table from App -> Catalog -> Raw Stock Data)
2. Vat Stock (dynamic Excel file selector and previewer, ready for confirmed Excel schema)
3. Mapping (clean placeholder table per Section 30)
"""

import os
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTabWidget, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QLineEdit, QStyledItemDelegate, QAbstractItemView
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from src.logic.db_manager import get_db_manager, build_logical_name
from src.logic.vat_manager import load_stock_mappings, save_stock_mapping, ensure_vat_tables
from src.ui.table_nav_mixin import UniversalCellDelegate, UNIVERSAL_TABLE_STYLE, _TallyCompleter
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class StockMappingItemDelegate(UniversalCellDelegate):
    """Delegate for Stock Mapping table: provides seamless in-cell QLineEdit editing with
    searchable _TallyCompleter for both VAT Stock Item (Col 0) and Internal Stock Item (Col 1),
    and editable text for Manual Name (Col 2). Paints unmapped rows fully in red.
    """
    def __init__(self, get_vat_options_callback, get_int_options_callback, parent_table=None, parent=None):
        super().__init__(parent=parent)
        self.get_vat_options_callback = get_vat_options_callback
        self.get_int_options_callback = get_int_options_callback
        self.parent_table = parent_table

    def paint(self, painter, option, index):
        # Full row must be marked red if either VAT or Internal stock cell is empty
        model = index.model()
        vat_idx = model.index(index.row(), 0)
        int_idx = model.index(index.row(), 1)
        vat_text = (model.data(vat_idx, Qt.ItemDataRole.DisplayRole) or "").strip()
        int_text = (model.data(int_idx, Qt.ItemDataRole.DisplayRole) or "").strip()
        is_unmapped = (not vat_text or not int_text)

        if is_unmapped:
            painter.save()
            painter.fillRect(option.rect, QColor("#fecaca"))
            painter.restore()

        super().paint(painter, option, index)

    def _commit_and_close(self, editor):
        table = self.parent_table or self.parent()
        if not table or not hasattr(table, 'state'):
            p = editor.parent() if editor else None
            table = p if hasattr(p, 'state') else (getattr(p, 'parent', lambda: None)() if p else None)

        if table and hasattr(table, 'state') and table.state() != QAbstractItemView.State.EditingState:
            return

        try:
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        except RuntimeError:
            pass

    def createEditor(self, parent, option, index):
        # Check permissions
        table = self.parent_table or (self.parent() if isinstance(self.parent(), QAbstractItemView) else None)
        if table and hasattr(table, '_can_edit') and not table._can_edit:
            return None

        col = index.column()
        if col in (0, 1):  # VAT Stock Item (0) or Internal Stock Item (1)
            ed = QLineEdit(parent)
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)

            callback = self.get_vat_options_callback if col == 0 else self.get_int_options_callback
            options = callback() if callable(callback) else []
            completer = _TallyCompleter(options or [], ed)
            completer.setMaxVisibleItems(12)
            completer.popup().setMinimumWidth(340)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_activated)
            return ed

        elif col == 2:  # Manual Name column
            ed = QLineEdit(parent)
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)
            return ed

        return super().createEditor(parent, option, index)

    def updateEditorGeometry(self, editor, option, index):
        view = option.widget if option else None
        if not view:
            p = self.parent()
            if isinstance(p, QAbstractItemView):
                view = p
        if view is not None and isinstance(editor, QLineEdit):
            editor.setGeometry(view.visualRect(index))
            return
        super().updateEditorGeometry(editor, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            val = index.data() or ""
            editor.setText(val)
            editor._initial_text = val
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            col = index.column()
            val = editor.text().strip()
            init_val = getattr(editor, '_initial_text', index.data() or "")

            if col in (0, 1):
                if not val:
                    if col == 1:
                        # Clearing internal stock item is allowed (unmaps)
                        model.setData(index, "", Qt.ItemDataRole.EditRole)
                        return
                    else:
                        # VAT item cannot be empty -> revert
                        editor.setText(init_val)
                        return

                callback = self.get_vat_options_callback if col == 0 else self.get_int_options_callback
                options = callback() if callable(callback) else []
                resolved = None
                for opt in (options or []):
                    if opt.strip().lower() == val.lower():
                        resolved = opt.strip()
                        break

                if resolved:
                    model.setData(index, resolved, Qt.ItemDataRole.EditRole)
                else:
                    # Item not in allowed list! Revert
                    editor.setText(init_val)
                    return
            else:
                model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)



# ── Background Worker for non-blocking stock data load ────────────────
class _VatStockLoadWorker(QThread):
    """Fetches Internal Stock rows and Stock Mappings off the main thread."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db_name: str, company_name: str, vat_items: list, parent=None):
        super().__init__(parent)
        self._db_name = db_name
        self._company_name = company_name
        self._vat_items = vat_items

    def run(self):
        try:
            db = get_db_manager()
            stock_rows = []
            if db.database_exists(self._db_name):
                conn = db.get_connection(self._db_name)
                if conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'stock_items'
                    """)
                    if cur.fetchone()[0] > 0:
                        cur.execute("""
                            SELECT Item_Name, SubGroup, Category, Part_No, Closing_Qty, Closing_Rate, Closing_Value, Unit
                            FROM dbo.stock_items
                            ORDER BY Item_Name
                        """)
                        stock_rows = cur.fetchall()

            mappings = load_stock_mappings(self._db_name, self._company_name, self._vat_items)
            self.finished.emit({
                "stock_rows": stock_rows,
                "mappings": mappings,
            })
        except Exception as e:
            logger.error(f"[_VatStockLoadWorker] error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            get_db_manager().close_thread_connections()


class StockUI(QWidget):
    """Stock page for VAT Working."""
    def __init__(self):
        super().__init__()
        self.setObjectName("VatStockContainer")
        self.db = get_db_manager()
        self.current_company_path = ""
        self.current_company_name = ""
        self.db_name = ""
        self._can_edit = True
        self.selected_excel_path = ""
        self._load_worker = None
        self._last_loaded_path = None
        self._loading_path = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── Main Tabs (inside screen) ──────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("StockTabs")
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cbd5e1;
                background: #ffffff;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                color: #475569;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #cbd5e1;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
                font-weight: 700;
                border-bottom: 2px solid #059669;
            }
            QTabBar::tab:hover:!selected {
                background: #e2e8f0;
                color: #1e293b;
            }
        """)

        # Tab 0: Int. Stock
        self.int_stock_widget = self._create_int_stock_tab()
        self.tabs.addTab(self.int_stock_widget, "Int. Stock")

        # Tab 1: Vat Stock
        self.vat_stock_widget = self._create_vat_stock_tab()
        self.tabs.addTab(self.vat_stock_widget, "Vat Stock")

        # Tab 2: Mapping
        self.mapping_widget = self._create_mapping_tab()
        self.tabs.addTab(self.mapping_widget, "Mapping")

        layout.addWidget(self.tabs, stretch=1)

    def set_current_view(self, index: int):
        """Switch active tab (0: Int Stock, 1: Vat Stock, 2: Stock Mapping)."""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    # ── TAB CREATION HELPERS ─────────────────────────────────────────

    def _create_int_stock_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        # Top Bar
        top_bar = QHBoxLayout()
        lbl = QLabel("Internal Stock")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.int_search = QLineEdit()
        self.int_search.setPlaceholderText("Filter stock item name...")
        self.int_search.setFixedWidth(260)
        self.int_search.textChanged.connect(self._filter_int_stock_table)

        self.btn_refresh_int = QPushButton("Refresh")
        self.btn_refresh_int.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_refresh_int.clicked.connect(self.refresh_int_stock_table)

        top_bar.addWidget(lbl)
        top_bar.addStretch()
        top_bar.addWidget(self.int_search)
        top_bar.addWidget(self.btn_refresh_int)
        vbox.addLayout(top_bar)

        # Table
        self.int_table = QTableWidget()
        self.int_table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.int_table.setAlternatingRowColors(True)
        self.int_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.int_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.int_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.int_table.verticalHeader().setVisible(False)
        self.int_table.setItemDelegate(UniversalCellDelegate(self.int_table))

        headers = ["Item Name", "SubGroup", "Category", "Part No", "Closing Qty", "Closing Rate", "Closing Value", "Unit"]
        self.int_table.setColumnCount(len(headers))
        self.int_table.setHorizontalHeaderLabels(headers)
        default_widths = [250, 130, 130, 120, 100, 100, 110, 80]
        for col, w in enumerate(default_widths):
            self.int_table.setColumnWidth(col, w)
        vbox.addWidget(self.int_table)

        return widget

    def _create_vat_stock_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        # Top Bar: File selector + Import action
        top_bar = QHBoxLayout()
        
        self.btn_select_file = QPushButton("Select Excel File")
        self.btn_select_file.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600;
                border: none; border-radius: 4px; padding: 6px 16px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_select_file.clicked.connect(self._select_excel_file)

        self.lbl_file_path = QLabel("No Excel file selected")
        self.lbl_file_path.setStyleSheet("color: #64748b; font-size: 12px;")

        top_bar.addWidget(self.btn_select_file)
        top_bar.addWidget(self.lbl_file_path)
        top_bar.addStretch()
        vbox.addLayout(top_bar)

        # Dynamic Preview Table
        self.vat_table = QTableWidget()
        self.vat_table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.vat_table.setAlternatingRowColors(True)
        self.vat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vat_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.vat_table.verticalHeader().setVisible(False)
        self.vat_table.setItemDelegate(UniversalCellDelegate(self.vat_table))
        vbox.addWidget(self.vat_table)

        return widget

    def _create_mapping_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Clean Top Bar: Search filter only, no extra clutter or descriptive paragraphs
        top_bar = QHBoxLayout()
        self.mapping_search = QLineEdit()
        self.mapping_search.setPlaceholderText("Search stock mapping...")
        self.mapping_search.setFixedWidth(260)
        self.mapping_search.textChanged.connect(self._filter_mapping_table)
        top_bar.addWidget(self.mapping_search)
        top_bar.addStretch()
        vbox.addLayout(top_bar)

        # Table: Compact 2-column layout (not stretched across the entire screen)
        self.mapping_table = QTableWidget()
        self.mapping_table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.mapping_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.SelectedClicked |
            QTableWidget.EditTrigger.EditKeyPressed
        )
        self.mapping_table.verticalHeader().setVisible(False)

        headers = ["VAT Stock Item", "Internal Stock Item", "Manual Name"]
        self.mapping_table.setColumnCount(3)
        self.mapping_table.setHorizontalHeaderLabels(headers)

        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.mapping_table.setColumnWidth(0, 320)
        self.mapping_table.setColumnWidth(1, 320)
        self.mapping_table.setColumnWidth(2, 260)

        # Set mapping delegate with seamless QLineEdit + _TallyCompleter for both sides
        self.mapping_table.setItemDelegate(
            StockMappingItemDelegate(
                self.get_vat_stock_names,
                self.get_internal_stock_names,
                parent_table=self.mapping_table,
                parent=self.mapping_table
            )
        )
        self.mapping_table.itemChanged.connect(self._on_stock_mapping_item_changed)
        self.mapping_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mapping_table.customContextMenuRequested.connect(self._show_stock_mapping_context_menu)

        vbox.addWidget(self.mapping_table)
        return widget

    # ── DATA LOADING ─────────────────────────────────────────────────

    def load_data(self, company_path: str, company_name: str = None, force: bool = False):
        """Called when company changes or tab opens. Deduped & non-blocking."""
        company_path = company_path or ""
        if not force and company_path and (
            company_path == self._last_loaded_path
            or (self._load_worker is not None and self._load_worker.isRunning() and getattr(self, '_loading_path', None) == company_path)
        ):
            return

        self.current_company_path = company_path
        self.current_company_name = company_name or (os.path.basename(os.path.normpath(company_path)) if company_path else "")
        self.db_name = build_logical_name(self.current_company_name, company_path=self.current_company_path) if company_path else ""

        if not self.db_name or not self.db.database_exists(self.db_name):
            return

        # Cancel any in-flight worker for previous company or forced reload
        if self._load_worker is not None and self._load_worker.isRunning():
            try:
                self._load_worker.finished.disconnect()
                self._load_worker.error.disconnect()
            except Exception:
                pass
            self._load_worker.quit()
            self._load_worker.wait(300)
            self._load_worker = None

        self._loading_path = company_path

        vat_items = getattr(self, 'imported_vat_items', [])
        self._load_worker = _VatStockLoadWorker(self.db_name, self.current_company_name, vat_items, parent=self)
        self._load_worker.finished.connect(self._on_data_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_data_loaded(self, data: dict):
        self._last_loaded_path = self.current_company_path
        self._loading_path = None
        self._load_worker = None

        self._populate_int_stock_table_from_rows(data.get("stock_rows", []))
        self._populate_stock_mapping_from_data(data.get("mappings", []))

    def _on_load_error(self, msg: str):
        self._loading_path = None
        self._load_worker = None
        logger.error(f"[StockUI._on_load_error] {msg}")

    def refresh_int_stock_table(self):
        """Load internal stock items from dbo.stock_items in company DB (sync path)."""
        if not self.db_name or not self.db.database_exists(self.db_name):
            self.int_table.setRowCount(0)
            return

        conn = self.db.get_connection(self.db_name)
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'stock_items'
            """)
            if cur.fetchone()[0] == 0:
                self.int_table.setRowCount(0)
                cur.close()
                conn.commit()
                return

            cur.execute("""
                SELECT Item_Name, SubGroup, Category, Part_No, Closing_Qty, Closing_Rate, Closing_Value, Unit
                FROM dbo.stock_items
                ORDER BY Item_Name
            """)
            rows = cur.fetchall()
            cur.close()
            conn.commit()
            self._populate_int_stock_table_from_rows(rows)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"[refresh_int_stock_table] error: {e}")

    def _populate_int_stock_table_from_rows(self, rows: list):
        """Populate Internal Stock table from pre-fetched rows."""
        self.int_table.blockSignals(True)
        self.int_table.setUpdatesEnabled(False)
        self.int_table.setRowCount(len(rows))

        for r_idx, r in enumerate(rows):
            for c_idx, val in enumerate(r):
                it = QTableWidgetItem(str(val) if val is not None else "")
                if c_idx in (4, 5, 6):  # Numeric qty/rate/value
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.int_table.setItem(r_idx, c_idx, it)

        self.int_table.setUpdatesEnabled(True)
        self.int_table.blockSignals(False)

    def _select_excel_file(self):
        """Open file dialog for user to select VAT stock Excel file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select VAT Stock Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if not file_path:
            return

        self.selected_excel_path = file_path
        self.lbl_file_path.setText(os.path.basename(file_path))

        try:
            df = pd.read_excel(file_path)
            if df.empty:
                QMessageBox.warning(self, "Empty File", "The selected Excel file contains no data.")
                return

            # Display whatever columns are present in the Excel file
            cols = [str(c).strip() for c in df.columns]
            self.vat_table.blockSignals(True)
            self.vat_table.setColumnCount(len(cols))
            self.vat_table.setHorizontalHeaderLabels(cols)
            self.vat_table.setRowCount(len(df))

            for r_idx, (_, row) in enumerate(df.iterrows()):
                for c_idx, val in enumerate(row):
                    val_str = "" if pd.isna(val) else str(val).strip()
                    it = QTableWidgetItem(val_str)
                    if isinstance(val, (int, float)):
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.vat_table.setItem(r_idx, c_idx, it)

            self.vat_table.blockSignals(False)
            self.vat_table.resizeColumnsToContents()

            # Store imported VAT stock items and refresh Stock Mapping table
            if cols:
                # Intelligently identify the Item Name column instead of blindly taking column 0
                item_col = None
                for c in cols:
                    c_clean = str(c).strip().lower().replace("_", " ")
                    if c_clean in ("item name", "stock item name", "stock item", "item", "particulars", "description", "item_name"):
                        item_col = c
                        break
                if not item_col:
                    for c in cols:
                        c_clean = str(c).strip().lower()
                        if ("item" in c_clean or "particular" in c_clean or "desc" in c_clean) and not any(x in c_clean for x in ("date", "time", "vch", "voucher", "rate", "qty", "amount", "total")):
                            item_col = c
                            break
                if not item_col:
                    item_col = cols[0]

                self.imported_vat_items = sorted(list(set(str(v).strip() for v in df[item_col].dropna() if str(v).strip())))
                self.refresh_stock_mapping_table()

            QMessageBox.information(
                self, "Excel Loaded",
                f"Successfully loaded {len(df)} rows and {len(cols)} columns from '{os.path.basename(file_path)}'."
            )

        except Exception as e:
            logger.error(f"[_select_excel_file] read error: {e}")
            QMessageBox.critical(self, "Read Error", f"Failed to read Excel file:\n{e}")

    def get_vat_stock_names(self) -> list[str]:
        """Return distinct VAT stock item names for autocomplete."""
        names = set(getattr(self, 'imported_vat_items', []))
        for r in range(self.mapping_table.rowCount()):
            it = self.mapping_table.item(r, 0)
            if it and it.text().strip():
                names.add(it.text().strip())
        return sorted(list(names))

    def refresh_stock_mapping_table(self):
        """Populate Stock Mapping table with items from both VAT Excel and Internal Stock (sync path)."""
        if not self.db_name:
            self.mapping_table.setRowCount(0)
            return

        vat_items = getattr(self, 'imported_vat_items', [])
        mappings = load_stock_mappings(self.db_name, self.current_company_name, vat_items)
        self._populate_stock_mapping_from_data(mappings)

    def _populate_stock_mapping_from_data(self, mappings: list):
        """Populate Stock Mapping table from pre-fetched mappings."""
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(mappings))

        for row, m in enumerate(mappings):
            rec_id = m.get("id", 0)
            vat_item_name = m.get("vat_stock_item", "") or ""
            int_item_name = m.get("internal_stock_item", "") or ""
            man_name = m.get("manual_name", "") or ""
            is_unmapped = (not vat_item_name.strip() or not int_item_name.strip())

            c0 = QTableWidgetItem(vat_item_name)
            c1 = QTableWidgetItem(int_item_name)
            c2 = QTableWidgetItem(man_name)

            for it in (c0, c1, c2):
                it.setData(Qt.ItemDataRole.UserRole, rec_id)
                if not self._can_edit:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if is_unmapped:
                red_bg = QColor("#fecaca")
                red_fg = QColor("#991b1b")
                for it in (c0, c1, c2):
                    it.setBackground(red_bg)
                    it.setForeground(red_fg)
            else:
                normal_fg = QColor("#0f172a")
                normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
                for it in (c0, c1, c2):
                    it.setBackground(normal_bg)
                    it.setForeground(normal_fg)

            self.mapping_table.setItem(row, 0, c0)
            self.mapping_table.setItem(row, 1, c1)
            self.mapping_table.setItem(row, 2, c2)

        self.mapping_table.blockSignals(False)

    def get_internal_stock_names(self) -> list[str]:
        """Return distinct internal stock item names for autocomplete."""
        # Query dbo.stock_items directly for authentic Item_Name
        if self.db_name and self.db.database_exists(self.db_name):
            try:
                conn = self.db.get_connection(self.db_name)
                if conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT DISTINCT Item_Name 
                        FROM dbo.stock_items 
                        WHERE Item_Name IS NOT NULL AND LTRIM(RTRIM(Item_Name)) <> ''
                        ORDER BY Item_Name
                    """)
                    rows = cur.fetchall()
                    if rows:
                        return [r[0].strip() for r in rows if r[0]]
            except Exception as e:
                logger.error(f"[get_internal_stock_names] DB query error: {e}")

        # Fallback to int_table if DB query not available
        names = []
        for r in range(self.int_table.rowCount()):
            it = self.int_table.item(r, 0)
            if it and it.text().strip():
                names.append(it.text().strip())
        return sorted(list(set(names)))

    def _filter_mapping_table(self, text: str):
        q = text.strip().lower()
        self.mapping_table.setUpdatesEnabled(False)
        try:
            for r in range(self.mapping_table.rowCount()):
                c0 = self.mapping_table.item(r, 0)
                c1 = self.mapping_table.item(r, 1)
                c2 = self.mapping_table.item(r, 2)
                t0 = c0.text().lower() if c0 else ""
                t1 = c1.text().lower() if c1 else ""
                t2 = c2.text().lower() if c2 else ""
                self.mapping_table.setRowHidden(r, (q not in t0) and (q not in t1) and (q not in t2))
        finally:
            self.mapping_table.setUpdatesEnabled(True)

    def _on_stock_mapping_item_changed(self, item: QTableWidgetItem):
        try:
            row = item.row()
            if row < 0:
                return
            c0 = self.mapping_table.item(row, 0)
            c1 = self.mapping_table.item(row, 1)
            c2 = self.mapping_table.item(row, 2)
            if not c0 or not c1 or not c2:
                return

            v_name = c0.text().strip()
            i_name = c1.text().strip()
            m_name = c2.text().strip()

            # Strictly validate i_name against internal stock names if non-empty
            if i_name:
                valid_items = self.get_internal_stock_names()
                canon = None
                for vi in valid_items:
                    if vi.strip().lower() == i_name.lower():
                        canon = vi.strip()
                        break
                if not canon:
                    # Invalid item name not in list! Revert
                    self.mapping_table.blockSignals(True)
                    c1.setText("")
                    self.mapping_table.blockSignals(False)
                    return
                i_name = canon

            is_unmapped = (not v_name or not i_name)
            self.mapping_table.blockSignals(True)
            try:
                if not is_unmapped:
                    normal_fg = QColor("#0f172a")
                    normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
                    for it in (c0, c1, c2):
                        it.setBackground(normal_bg)
                        it.setForeground(normal_fg)
                else:
                    red_bg = QColor("#fecaca")
                    red_fg = QColor("#991b1b")
                    for it in (c0, c1, c2):
                        it.setBackground(red_bg)
                        it.setForeground(red_fg)
            finally:
                self.mapping_table.blockSignals(False)
            self.mapping_table.viewport().update()

            if not self.db_name:
                return

            rec_id = item.data(Qt.ItemDataRole.UserRole)
            if not rec_id:
                rec_id = c0.data(Qt.ItemDataRole.UserRole) or c1.data(Qt.ItemDataRole.UserRole) or 0

            new_id = save_stock_mapping(self.db_name, self.current_company_name, rec_id or 0, v_name, i_name, m_name)
            if new_id:
                self.mapping_table.blockSignals(True)
                c0.setData(Qt.ItemDataRole.UserRole, new_id)
                c1.setData(Qt.ItemDataRole.UserRole, new_id)
                c2.setData(Qt.ItemDataRole.UserRole, new_id)
                self.mapping_table.blockSignals(False)
                if v_name and i_name:
                    QTimer.singleShot(250, self.refresh_stock_mapping_table)
        except Exception as e:
            logger.error(f"[_on_stock_mapping_item_changed] error: {e}")

    def _show_stock_mapping_context_menu(self, pos):
        """Right-click context menu on Stock Mapping table to unmap a mapped row."""
        if not self._can_edit:
            return
        row = self.mapping_table.rowAt(pos.y())
        if row < 0:
            return
        c0 = self.mapping_table.item(row, 0)
        c1 = self.mapping_table.item(row, 1)
        if not c0 or not c1:
            return
        v_name = c0.text().strip()
        i_name = c1.text().strip()

        if v_name and i_name:
            menu = QMenu(self)
            act_unmap = menu.addAction("Remove Mapping (Unmap)")
            selected_act = menu.exec(self.mapping_table.viewport().mapToGlobal(pos))
            if selected_act == act_unmap:
                rec_id = c0.data(Qt.ItemDataRole.UserRole) or c1.data(Qt.ItemDataRole.UserRole) or 0
                save_stock_mapping(self.db_name, self.current_company_name, rec_id, "", "")
                self.refresh_stock_mapping_table()

    def _filter_int_stock_table(self, text: str):
        q = text.strip().lower()
        for r in range(self.int_table.rowCount()):
            it = self.int_table.item(r, 0)
            self.int_table.setRowHidden(r, q not in it.text().lower() if it else False)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.mapping_table._can_edit = can_edit
        self.btn_select_file.setEnabled(can_edit)
        self.mapping_table.blockSignals(True)
        for r in range(self.mapping_table.rowCount()):
            for c in range(3):
                it = self.mapping_table.item(r, c)
                if it:
                    if can_edit:
                        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.mapping_table.blockSignals(False)

    def get_current_table(self) -> tuple[str, QTableWidget]:
        """Return (title, table_widget) for active tab."""
        idx = self.tabs.currentIndex()
        if idx == 0:
            return "VAT Working - Int. Stock", self.int_table
        elif idx == 1:
            return "VAT Working - Vat Stock", self.vat_table
        else:
            return "VAT Working - Stock Mapping", self.mapping_table

