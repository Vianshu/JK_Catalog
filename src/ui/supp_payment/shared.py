# =============================================================================
# supp_payment_shared.py — Shared constants, helpers, delegate, and _DbTable
# Imported by all supp_payment_* sub-modules.
# =============================================================================
# =============================================================================
# supp_payment.py  ΓÇô  Supplier Payment Module (Redesigned)
# =============================================================================
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QApplication, QAbstractScrollArea, QFileDialog, QColorDialog, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QMimeData, QSettings,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QKeySequence, QShortcut, QCursor, QImage,
)
from src.logic.db_manager import get_db_manager, build_logical_name

from src.ui.table_exporter import export_tables_to_excel
from src.ui.table_printer import print_tables_via_preview

class _PrintExportMixin:
    def _init_print_export(self, layout, title, supports_print=True, table_getter=None, print_table_getter=None):
        self._export_title = title
        self._table_getter = table_getter if table_getter else lambda: [{"title": title, "table": self.table}]
        self._print_table_getter = print_table_getter if print_table_getter else self._table_getter
        self._export_grid_cols = 1
        self._export_title_on_left = False

        self.btn_export = QPushButton("📊 Excel")
        self.btn_export.setStyleSheet(_BTN_PRIMARY)
        self.btn_export.clicked.connect(self._do_export)
        layout.addWidget(self.btn_export)

        if supports_print:
            self.btn_print = QPushButton("🖨 Print")
            self.btn_print.setStyleSheet(_BTN_PRIMARY)
            self.btn_print.clicked.connect(self._do_print)
            layout.addWidget(self.btn_print)

    def _do_export(self):
        tables = self._table_getter()
        if not tables:
            QMessageBox.information(self, "Nothing to Export", "No data found to export.")
            return

        default_name = f"{self._export_title.replace(' ', '_')}.xlsx"
        # Retrieve last-used directory from QSettings for convenience
        settings = QSettings("TallySync", "SuppPayment")
        last_dir = settings.value("export_last_dir", "")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel File",
            os.path.join(last_dir, default_name) if last_dir else default_name,
            "Excel Files (*.xlsx)"
        )
        if not path:
            return  # user cancelled

        # Remember directory for next time
        settings.setValue("export_last_dir", os.path.dirname(path))

        success = export_tables_to_excel(
            os.path.dirname(path), os.path.basename(path), tables, self,
            grid_cols=self._export_grid_cols, title_on_left=self._export_title_on_left
        )
        if success:
            QMessageBox.information(
                self, "Export Complete",
                f"File saved to:\n{path}"
            )

    def _do_print(self):
        tables = self._print_table_getter()
        nbc = getattr(self, "no_border_cols", [])
        print_tables_via_preview(tables, self, self._export_title, no_border_cols=nbc)

from src.ui.table_nav_mixin import (
    UniversalCellDelegate, 
    CELL_TYPE_ROLE, 
    AUTOCOMPLETE_ITEMS_ROLE,
    UNIVERSAL_TABLE_STYLE
)

from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFontMetrics, QFont
from PyQt6.QtCore import Qt, QRect

class ModernTableDelegate(UniversalCellDelegate):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.status_colors = {
            "completed": ("#dcfce7", "#166534"),
            "paid": ("#dcfce7", "#166534"),
            "pending": ("#fef9c3", "#854d0e"),
            "processing": ("#dbeafe", "#1e40af"),
            "active": ("#dcfce7", "#166534"),
            "overdue": ("#fee2e2", "#991b1b"),
            "approved": ("#e0e7ff", "#3730a3"),
            "sent": ("#f3e8ff", "#6b21a8"),
            "draft": ("#f1f5f9", "#475569"),
            "clear": ("#f1f5f9", "#475569"),
        }
        
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        model = index.model()
        header = ""
        if hasattr(model, "headerData"):
            val = model.headerData(index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            if val is not None: header = str(val).lower()
            
        if "amount" in header or "balance" in header or "rs" in header or "dr" in header or "cr" in header or "value" in header or "cash" in header or "bank" in header:
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                from PyQt6.QtGui import QFont, QFontMetrics
                font = QFont("Consolas", 10)
                fm = QFontMetrics(font)
                # + 24 for padding to match paint margins
                w = fm.horizontalAdvance(str(text)) + 24
                if w > size.width():
                    size.setWidth(w)
        return size

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        self.initStyleOption(option, index)
        text = option.text
        if text is None: text = ""
        text = str(text).strip()
        
        # Background highlighting
        bg_brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#f1f5f9"))
        elif bg_brush:
            # Safely extract color from brush to avoid PyQt overload resolution issues
            if isinstance(bg_brush, QBrush):
                painter.fillRect(option.rect, bg_brush.color())
            elif isinstance(bg_brush, QColor):
                painter.fillRect(option.rect, bg_brush)
            else:
                painter.fillRect(option.rect, QBrush(bg_brush).color())
            
        model = index.model()
        header = ""
        if hasattr(model, "headerData"):
            val = model.headerData(index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            if val is not None: header = str(val).lower()
        
        # Draw single bottom border for row (extend x by 1 to make it continuous)
        painter.setPen(QPen(QColor("#e2e8f0"), 1)) # slightly darker line to match Check.txt
        bottom_left = option.rect.bottomLeft()
        bottom_right = option.rect.bottomRight()
        painter.drawLine(bottom_left.x(), bottom_left.y(), bottom_right.x() + 1, bottom_right.y())
        
        rect = option.rect
        rect.adjust(8, 4, -8, -4)
        
        fg_brush = index.data(Qt.ItemDataRole.ForegroundRole)
        custom_fg = None
        if fg_brush:
            if isinstance(fg_brush, QBrush): custom_fg = fg_brush.color()
            elif isinstance(fg_brush, QColor): custom_fg = fg_brush
        
        if "status" in header and text:
            status_key = text.lower()
            bg_c, text_c = self.status_colors.get(status_key, ("#f1f5f9", "#475569"))
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            pill_rect = QRect(0, 0, text_width + 16, fm.height() + 8)
            pill_rect.moveCenter(option.rect.center())
            
            painter.setBrush(QBrush(QColor(bg_c)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill_rect, 6, 6)
            
            painter.setPen(custom_fg if custom_fg else QColor(text_c))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
            
        elif "amount" in header or "balance" in header or "rs" in header or "dr" in header or "cr" in header or "value" in header or "cash" in header or "bank" in header:
            painter.setPen(custom_fg if custom_fg else QColor("#1e293b"))
            font = painter.font()
            font.setFamily("Consolas")
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            
        elif "party" in header or "name" in header or "particular" in header or "remarks" in header or "account" in header or "type" in header:
            painter.setPen(custom_fg if custom_fg else QColor("#1e293b")) # Standard dark text
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            
        else:
            painter.setPen(custom_fg if custom_fg else QColor("#334155"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            
        painter.restore()

# ---------------------------------------------------------------------------
# Shared font helpers
# ---------------------------------------------------------------------------
def _bold_font(size=10):
    f = QFont()
    f.setFamilies(["Segoe UI", "Noto Sans Devanagari", "Mangal", "Arial Unicode MS"])
    f.setPointSize(size)
    f.setWeight(QFont.Weight.Bold)
    return f

def _norm_font(size=10):
    f = QFont()
    f.setFamilies(["Segoe UI", "Noto Sans Devanagari", "Mangal", "Arial Unicode MS"])
    f.setPointSize(size)
    return f

# ---------------------------------------------------------------------------
# Common stylesheet constants
# ---------------------------------------------------------------------------
_SCROLLBAR_STYLE = """
QScrollBar:vertical {
    border: none; background: transparent; width: 6px; margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.2); min-height: 20px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: rgba(0, 0, 0, 0.4); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    border: none; background: transparent; height: 6px; margin: 0px 0px 0px 0px;
}
QScrollBar::handle:horizontal {
    background: rgba(0, 0, 0, 0.2); min-width: 20px; border-radius: 3px;
}
QScrollBar::handle:horizontal:hover { background: rgba(0, 0, 0, 0.4); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
"""

_TABLE_STYLE = UNIVERSAL_TABLE_STYLE + """
QTableWidget {
    background: #ffffff;
    border: none;
    gridline-color: #f1f5f9;
    color: #1e293b;
    font-size: 10pt;
    selection-background-color: #d1fae5;
    selection-color: #064e3b;
    outline: none;
}
QTableWidget::item {
    padding: 6px;
    border-bottom: 1px solid #f1f5f9;
    border-right: 1px solid #e2e8f0;
}
QHeaderView::section:horizontal {
    background: #f8fafc;
    color: #475569;
    padding: 1px 4px;
    min-height: 20px;
    max-height: 24px;
    border: none;
    border-bottom: 2px solid #e2e8f0;
    font-weight: 700;
    font-size: 9pt;
    text-transform: uppercase;
}
QHeaderView::section:horizontal:first { border-radius: 8px 0 0 0; }
QHeaderView::section:horizontal:last  { border-radius: 0 8px 0 0; }
"""

_SECTION_HEADER_STYLE = (
    "background: #ffffff; color: {color}; padding: 14px 16px; "
    "border-radius: 12px 12px 0 0; font-weight: 800; font-size: 11pt; "
    "border-bottom: 1px solid #e2e8f0;"
)

_BTN_PRIMARY = """
QPushButton {
    background: #059669; color: white; border: none;
    border-radius: 5px; padding: 5px 14px; font-weight: bold; font-size: 10pt;
}
QPushButton:hover { background: #047857; }
QPushButton:disabled { background: #94a3b8; }
"""

_BTN_SECONDARY = """
QPushButton {
    background: #f1f5f9; color: #374151; border: 1px solid #cbd5e1;
    border-radius: 5px; padding: 5px 14px; font-size: 10pt;
}
QPushButton:hover { background: #e2e8f0; }
"""

_BTN_DANGER = """
QPushButton {
    background: #ef4444; color: white; border: none;
    border-radius: 5px; padding: 5px 14px; font-weight: bold; font-size: 10pt;
}
QPushButton:hover { background: #dc2626; }
"""

_MENU_STYLE = """
    QMenu {
        background: #ffffff; color: #1e293b;
        border: 1px solid #e2e8f0;
        padding: 4px 0;
    }
    QMenu::item { padding: 7px 20px; font-size: 10pt; }
    QMenu::item:selected { background: #f1f5f9; color: #1e293b; }
    QMenu::item:disabled { color: #94a3b8; }
    QMenu::separator { height: 1px; background: #e2e8f0; margin: 3px 8px; }
"""

_POPUP_STYLE = """
    QMessageBox { background: #ffffff; color: #0f172a; }
    QMessageBox QLabel { color: #0f172a; font-size: 10pt; }
    QPushButton {
        background: #f1f5f9; color: #374151; border: 1px solid #cbd5e1;
        border-radius: 4px; padding: 5px 15px; font-weight: bold;
    }
    QPushButton:hover { background: #e2e8f0; }
"""

# Context menu style for card-level right-click menus (red-toned selection).
_CARD_MENU_STYLE = """
    QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
    QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
    QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
"""

# ===========================================================================
# Simple DB-backed QTableWidget
# ===========================================================================


def _setup_smart_header(table):
    hdr = table.horizontalHeader()
    hdr.setHighlightSections(False)
    hdr.setMinimumSectionSize(20)
    
    # Force the header height to be strictly 24px to eliminate top/bottom whitespace
    hdr.setFixedHeight(24)
    
    # Stretch the last section so the table fills the full width, aligning the right borders
    hdr.setStretchLastSection(True)
    
    # Must use string-based signals to avoid garbage collection of local closures
    hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Attach a state object to the table to store our lambda/slot
    if not hasattr(table, '_smart_hdr_menu'):
        def _show_menu(pos):
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(table)
            menu.setStyleSheet("""
                QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
                QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
                QMenu::item:selected{background:#e2e8f0;color:#0f172a;border-radius:2px;}
            """)
            act_fit = menu.addAction("Fit Column to Content")
            act_fit_all = menu.addAction("Fit All Columns to Content")
            
            # Show current stretch state
            is_stretch = hdr.stretchLastSection()
            act_stretch = menu.addAction("Stretch Last Column (On)" if is_stretch else "Stretch Last Column (Off)")
            
            chosen = menu.exec(hdr.mapToGlobal(pos))
            if chosen == act_fit:
                idx = hdr.logicalIndexAt(pos)
                table.resizeColumnToContents(idx)
            elif chosen == act_fit_all:
                table.resizeColumnsToContents()
            elif chosen == act_stretch:
                hdr.setStretchLastSection(not is_stretch)
                
        table._smart_hdr_menu = _show_menu
        hdr.customContextMenuRequested.connect(table._smart_hdr_menu)


class _DbTable(QTableWidget):
    """A clean QTableWidget backed by a single SQL table.
    Schema: (row_idx INT, col_idx INT, cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))
    """
    def __init__(self, table_name: str, headers: list, widths: list,
                 parent=None, row_count=0):
        super().__init__(0, len(headers), parent)
        self._table_name = table_name
        self._db = get_db_manager()
        self._db_name = ""
        self._headers = headers
        self._widths = widths
        self._loading = False
        self._can_edit = True
        self._min_rows = max(0, row_count)  # Bug 1b: minimum visible rows after load
        self._is_edit_mode = False           # tracks F2 edit mode (cursor at end, no selection)

        self.setFont(_norm_font())
        self.setAlternatingRowColors(True)
        self.setStyleSheet(_TABLE_STYLE)
        self.setHorizontalHeaderLabels(headers)
        _setup_smart_header(self)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self.itemChanged.connect(self._on_change)
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)

        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)

        self.setItemDelegate(ModernTableDelegate(self))

    def set_db_name(self, db_name: str, path: str = None):
        self._db_name = db_name
        if path:
            self._db.ensure_database_exists(db_name, path)
        self._ensure_table()
        self.load_from_db()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            | QTableWidget.EditTrigger.EditKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )

    def _ensure_table(self):
        if not self._db_name:
            return
        ddl = (f"CREATE TABLE {self._table_name} "
               f"(row_idx INT NOT NULL, col_idx INT NOT NULL, "
               f"cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))")
        self._db.ensure_table(self._db_name, self._table_name, ddl)

    def _on_change(self, item):
        if self._loading:
            return
        # Dynamically resize the column to fit new content but respect minimum width and header text
        self._enforce_min_widths(item.column())
        
        # Debounced 300ms save ΓÇô consistent with _SectionCardV2 strategy
        self._save_timer.start(300)

    def _on_section_resized(self, logicalIndex, oldSize, newSize):
        if self._loading: return
        
        if not hasattr(self, '_resize_timers'):
            self._resize_timers = {}
            
        if logicalIndex not in self._resize_timers:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda idx=logicalIndex: self._enforce_col_min(idx))
            self._resize_timers[logicalIndex] = t
            
        self._resize_timers[logicalIndex].start(300)

    def _enforce_col_min(self, logicalIndex):
        if self._loading: return
        min_w = self._widths[logicalIndex] if logicalIndex < len(self._widths) else 0
        hdr_item = self.horizontalHeaderItem(logicalIndex)
        hdr_text = hdr_item.text() if hdr_item else ""
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(hdr_text) + 20
        required_w = max(min_w, text_w)
        if self.columnWidth(logicalIndex) < required_w:
            self.horizontalHeader().blockSignals(True)
            self.setColumnWidth(logicalIndex, required_w)
            self.horizontalHeader().blockSignals(False)

    def _do_save(self):
        """Save table contents using a single atomic transaction to prevent data loss."""
        if not self._db_name or self._loading:
            return
        if getattr(self, '_load_failed', False):
            print(f"[_DbTable] Blocked save for {self._table_name} to prevent data loss after load failure.")
            return
            
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(f"DELETE FROM {self._table_name}")
            # Collect all non-empty cells first, then send in one batched round-trip.
            rows_to_insert = [
                (r, c, self.item(r, c).text())
                for r in range(self.rowCount())
                for c in range(self.columnCount())
                if self.item(r, c) and self.item(r, c).text()
            ]
            if rows_to_insert:
                cur.executemany(
                    f"INSERT INTO {self._table_name} (row_idx, col_idx, cell_text) VALUES (?,?,?)",
                    rows_to_insert
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[_DbTable] _do_save error ({self._table_name}):", e)

    # keep save_to_db as alias for external callers
    def save_to_db(self):
        self._do_save()

    def _enforce_min_widths(self, col=None):
        fm = self.fontMetrics()
        
        if col is not None:
            cols = [col]
        else:
            cols = range(self.columnCount())
            
        for i in cols:
            # Use sizeHintForColumn instead of resizeColumnToContents so we don't snap back
            # if the user manually dragged the column to be wider.
            min_w = self.sizeHintForColumn(i)
            saved_w = self._widths[i] if i < len(self._widths) else 0
            min_w = max(min_w, saved_w)
            
            h_item = self.horizontalHeaderItem(i)
            if h_item and h_item.text():
                # Add 24px padding for sort indicator and margins
                min_w = max(min_w, fm.horizontalAdvance(h_item.text()) + 24)
            if self.columnWidth(i) < min_w:
                self.setColumnWidth(i, min_w)

    def load_from_db(self):
        if not self._db_name:
            return
        self._loading = True
        rows = self._db.execute_query(
            self._db_name,
            f"SELECT row_idx, col_idx, cell_text FROM {self._table_name} ORDER BY row_idx, col_idx"
        )
        if rows is None:
            self._load_failed = True
            self._loading = False
            print(f"[_DbTable] Failed to load data from {self._table_name}.")
            return
        self._load_failed = False
        
        self.blockSignals(True)
        self.clearContents()
        self.setRowCount(0)
        for r, c, txt in rows:
            while self.rowCount() <= int(r):
                self.insertRow(self.rowCount())
                for ci in range(self.columnCount()):
                    self.setItem(self.rowCount() - 1, ci, QTableWidgetItem(""))
            it = QTableWidgetItem(txt or "")
            self.setItem(int(r), int(c), it)
        # Bug 1b: Pad up to the minimum row count so the table is never visually empty
        while self.rowCount() < self._min_rows:
            r = self.rowCount()
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
        self.blockSignals(False)
        self._enforce_min_widths()
        self._loading = False

    def add_row(self):
        if not self._can_edit:
            return
        self.blockSignals(True)
        r = self.rowCount()
        self.insertRow(r)
        for c in range(self.columnCount()):
            self.setItem(r, c, QTableWidgetItem(""))
        self.blockSignals(False)
        self._enforce_min_widths()
        self.scrollToBottom()
        # Save the new empty row directly (no timer, no thread)
        self._do_save()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2 and self._can_edit:
            # Set flag BEFORE super() so setEditorData sees it.
            # Qt opens the editor via EditKeyPressed trigger inside super().
            self._is_edit_mode = True
            super().keyPressEvent(event)
        elif self._can_edit and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for it in self.selectedItems():
                it.setText("")
        else:
            super().keyPressEvent(event)

    def closeEditor(self, editor, hint):
        """Reset F2 edit-mode flag when any editor closes so normal typing
        never inherits the 'cursor at end, no selection' F2 behaviour."""
        self._is_edit_mode = False
        super().closeEditor(editor, hint)

    # ΓöÇΓöÇ Right-click context menu with Delete Row ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QBrush, QColor

        sel_rows = sorted({i.row() for i in self.selectedItems()})
        lbl = f"\u2715  Delete {len(sel_rows)} Row(s)" if sel_rows else "\u2715  Delete Row"
        act_del = menu.addAction(lbl)
        act_del.setEnabled(bool(sel_rows) and self._can_edit)

        menu.addSeparator()
        act_add_above = menu.addAction("\u2191  Add Row Above")
        act_add_above.setEnabled(self._can_edit and bool(sel_rows))

        act_add_below = menu.addAction("\u2193  Add Row Below")
        act_add_below.setEnabled(self._can_edit and bool(sel_rows))
        
        menu.addSeparator()
        act_add = menu.addAction("\u2295  Add Row (Bottom)")
        act_add.setEnabled(self._can_edit)

        menu.addSeparator()
        a_color = menu.addAction("\u25cf  Set Cell Color")
        a_text_color = menu.addAction("\u25d0  Set Text Color")
        a_clear = menu.addAction("\u25cb  Clear Colors")

        chosen = menu.exec(event.globalPos())

        if chosen == act_del and sel_rows:
            msg = QMessageBox(self)
            msg.setWindowTitle("Delete Rows")
            msg.setText(f"Delete {len(sel_rows)} row(s)? This cannot be undone.")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setStyleSheet(_POPUP_STYLE)
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self.blockSignals(True)
                for r in reversed(sel_rows):
                    self.removeRow(r)
                # Pad back to minimum rows if needed
                while self.rowCount() < self._min_rows:
                    r = self.rowCount()
                    self.insertRow(r)
                    for c in range(self.columnCount()):
                        self.setItem(r, c, QTableWidgetItem(""))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == act_add_above and sel_rows:
            self.blockSignals(True)
            r = min(sel_rows)
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
            self.blockSignals(False)
            self._save_timer.start(300)

        elif chosen == act_add_below and sel_rows:
            self.blockSignals(True)
            r = max(sel_rows) + 1
            self.insertRow(r)
            for c in range(self.columnCount()):
                self.setItem(r, c, QTableWidgetItem(""))
            self.blockSignals(False)
            self._save_timer.start(300)

        elif chosen == act_add:
            self.add_row()
            
        elif chosen == a_color:
            color = QColorDialog.getColor(parent=self)
            if color.isValid():
                self.blockSignals(True)
                for idx in self.selectedIndexes():
                    it = self.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.setItem(idx.row(), idx.column(), it)
                    it.setBackground(QBrush(color))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == a_text_color:
            color = QColorDialog.getColor(parent=self)
            if color.isValid():
                self.blockSignals(True)
                for idx in self.selectedIndexes():
                    it = self.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.setItem(idx.row(), idx.column(), it)
                    it.setForeground(QBrush(color))
                self.blockSignals(False)
                self.resizeColumnsToContents()
                self._do_save()

        elif chosen == a_clear:
            self.blockSignals(True)
            for idx in self.selectedIndexes():
                it = self.item(idx.row(), idx.column())
                if it:
                    it.setBackground(QBrush())
                    it.setForeground(QBrush())
            self.blockSignals(False)
            self.resizeColumnsToContents()
            self._do_save()


# ===========================================================================
# Section card widget used in Today Payment
