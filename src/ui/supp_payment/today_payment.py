# -*- coding: utf-8 -*-
# =============================================================================
# today_payment_tab.py — _SectionCardV2 + TodayPaymentTabV2
# =============================================================================
import os
import re as _re
import json as _json
from src.utils.app_logger import get_logger

_logger = get_logger(__name__)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QApplication, QAbstractScrollArea, QFileDialog,
    QColorDialog, QTextEdit, QStyledItemDelegate, QStyle,
    QAbstractItemDelegate,
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QMimeData, QSettings, QRect,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QKeySequence,
    QShortcut, QCursor, QImage, QPen, QFontMetrics,
)
from src.logic.db_manager import get_db_manager, build_logical_name
from .shared import (
    _PrintExportMixin, ModernTableDelegate,
    _bold_font, _norm_font,
    _SCROLLBAR_STYLE, _TABLE_STYLE, _SECTION_HEADER_STYLE,
    _BTN_PRIMARY, _BTN_SECONDARY, _BTN_DANGER,
    _MENU_STYLE, _POPUP_STYLE, _CARD_MENU_STYLE,
    _setup_smart_header, _setup_sn_header, _DbTable,
    _styled_get_text, _styled_question, _styled_info, _styled_get_color,
    RAW_NUMERIC_ROLE,
)
from src.ui.table_nav_mixin import UniversalCellDelegate

# ===========================================================================
class _SectionCardV2(QFrame):
    """A single card containing a title and a dynamically-sized table."""
    def __init__(self, section_id, name, color,
                 db, db_name,
                 col_specs=None,
                 parent=None, card_width=450):
        super().__init__(parent)
        self.setObjectName("CardFrame")
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        self.setStyleSheet("QFrame#CardFrame { background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; }")
        self.section_id = section_id
        self.section_name = name
        self._db = db
        self._db_name = db_name
        self._fixed_cols = (col_specs is not None)
        self._col_specs = col_specs or []
        self._can_edit = False
        self._today_tab_ref = None
        self._saving = False
        self._is_edit_mode = False        # F2 support: cursor at end, no selection
        self._bypass_fuzzy_match = False  # Ctrl+Enter: save typed text as-is
        self._header_color = color

        # Debounce timer — restarted on every cell change, fires once 300 ms after the last keystroke.
        # Using start() (not singleShot) prevents stacking multiple pending saves during rapid typing.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_data)
        
        # Resizing state
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        # Wrap outer layout in a QWidget to prevent shadow bleeding
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        
        content_widget = QWidget()
        main_lay.addWidget(content_widget)
        
        outer = QVBoxLayout(content_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Header bar ----
        self._hdr = QWidget()
        self._hdr.setMinimumHeight(36)
        self._hdr.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self._update_hdr_style()
        hlay = QHBoxLayout(self._hdr)
        hlay.setContentsMargins(12, 4, 8, 4)
        hlay.setSpacing(6)

        self.title_lbl = QLabel(name)
        self.title_lbl.setFont(_bold_font(11))
        hlay.addWidget(self.title_lbl)
        hlay.addStretch()

        if not self._fixed_cols:
            self._btn_col = QPushButton("+ Col")
            self._btn_col.setFixedHeight(24)
            self._btn_col.clicked.connect(self._add_column)
            hlay.addWidget(self._btn_col)

        self._btn_row = QPushButton("+ Row")
        self._btn_row.setFixedHeight(24)
        self._btn_row.clicked.connect(self._add_row)
        hlay.addWidget(self._btn_row)

        if not self._fixed_cols:
            self._btn_gear = QPushButton("⚙")
            self._btn_gear.setFixedSize(28, 24)
            self._btn_gear.clicked.connect(self._show_gear)
            hlay.addWidget(self._btn_gear)

        outer.addWidget(self._hdr)

        # ---- Drag handle: the colored header initiates a drag ----
        self._hdr.setAcceptDrops(False)   # header is source, not target
        self.setAcceptDrops(True)          # whole card is the drop target
        self._hdr.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_start_pos = None

        # Install event filter on hdr to catch mouse events
        self._hdr.installEventFilter(self)
        self._hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._hdr.customContextMenuRequested.connect(self._header_ctx)

        # ---- Table — visually unified with all other tables in the app ----
        # NOTE: _TABLE_STYLE is intentionally NOT applied here because its
        # item padding (4px 8px) creates a visible inset-box inside every cell
        # in the Today Payment cards. Alternating rows, font, and row height
        # are applied to match other tabs without the padding artifact.
        self.table = QTableWidget()
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setMinimumSectionSize(26)
        _setup_sn_header(self.table)
        _setup_smart_header(self.table)
        self.table._card_ref = self   # used by header ctx menu for lock toggle
        from PyQt6.QtCore import QSettings
        settings = QSettings("TallySync", "SuppPayment")
        self._show_sn = settings.value(f"show_sn_tp_{self.section_id}", False, type=bool)
        self.table.verticalHeader().setVisible(self._show_sn)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setShowGrid(True)   # Native Qt gridlines (styled via gridline-color in QSS)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.table.setMinimumHeight(60)

        # Apply ModernTableDelegate which now inherits UniversalCellDelegate for editing
        self.table.setItemDelegate(ModernTableDelegate(self))
        self.table.installEventFilter(self)  # intercept F2 on the table

        if self._fixed_cols and self._col_specs:
            headers = [s[0] for s in self._col_specs]
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            for i, spec in enumerate(self._col_specs):
                self.table.setColumnWidth(i, spec[1])
                if len(spec) > 2 and spec[2] is not None:
                    self.table.setItemDelegateForColumn(i, spec[2])
            if self._col_specs and self._col_specs[0][0] == "S.N":
                self.table.setColumnHidden(0, True)
            # Load any saved custom column widths (user may have resized them)
            if db_name:
                try:
                    saved_widths = db.execute_query(
                        db_name,
                        "SELECT col_index, col_width FROM tp_section_cols WHERE section_id=? ORDER BY col_index",
                        (section_id,)
                    ) or []
                    for col_idx, col_w in saved_widths:
                        if col_w and int(col_idx) < self.table.columnCount():
                            self.table.setColumnWidth(int(col_idx), int(col_w))
                except Exception:
                    pass

        self.table.horizontalHeader().sectionDoubleClicked.connect(self._rename_col)
        self.table.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)
        self.table.itemChanged.connect(self._on_change)
        outer.addWidget(self.table)
        
        self._footer_lbl = QLabel("")
        self._footer_lbl.setFont(_bold_font(10))
        self._footer_lbl.setStyleSheet("color: #475569; padding: 4px 8px; background: #f8fafc; border-top: 1px solid #e2e8f0; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        self._footer_lbl.hide()
        outer.addWidget(self._footer_lbl)
        
        
        # Allow card to naturally shrink/grow unless setFixedWidth is called.
        self.setMinimumWidth(200)
        self._card_fixed_width = None  # Track original fixed width for single/multi toggle
        self._in_single_view = False   # Track whether we're currently in single-view mode
        self._cols_locked = False      # Track whether column widths are locked

        # Ignore 450 (the old DB default) to allow natural sizing.
        if card_width is not None and card_width >= 200 and card_width != 450:
            self.setFixedWidth(card_width)
            self._card_fixed_width = card_width

        self._load()
        self._setup_enter_navigation()  # connect Enter-moves-down for all delegates

        # Extend the column header's right-click menu with add/remove column options.
        # _setup_smart_header already connected its own handler; we replace it so we
        # can include both the existing resize/lock actions AND column management.
        _hdr = self.table.horizontalHeader()
        _hdr.customContextMenuRequested.disconnect(self.table._smart_hdr_menu)
        _hdr.customContextMenuRequested.connect(self._col_hdr_ctx)

    # ------------------------------------------------------------------
    # Column-aligned summary footer
    # ------------------------------------------------------------------
    def set_col_footer(self, col_values: dict, row_label: str = "Total"):
        """Show a column-aligned summary row beneath the table.

        col_values: {column_header_name: display_string_or_number}
                    Only columns listed here get a value; others are blank.
        row_label:  Text shown in the column IMMEDIATELY LEFT of the first value
                    column, right-aligned (so it reads as a label for the value
                    next to it). If the value column is the first column there
                    is no left neighbour and the label is not shown.

        The bar uses one QLabel per column, each fixed-width == column width,
        so values sit exactly below their respective columns. Column-resize
        events propagate automatically via sectionResized.
        """
        # Create the bar on first call
        if not hasattr(self, '_col_footer_bar'):
            bar = QWidget()
            bar.setObjectName("ColFooterBar")
            bar.setStyleSheet(
                "#ColFooterBar {"
                "  background: #f1f5f9;"
                "  border-top: 1.5px solid #64748b;"
                "  border-bottom-left-radius: 8px;"
                "  border-bottom-right-radius: 8px;"
                "}"
            )
            hlay = QHBoxLayout(bar)
            hlay.setContentsMargins(0, 3, 0, 3)
            hlay.setSpacing(0)
            self._col_footer_bar  = bar
            self._col_footer_hlay = hlay
            self._col_footer_lbls: dict = {}
            # Insert above _footer_lbl so stacking is: table | col_footer | footer_lbl
            outer = self.layout()
            idx   = outer.indexOf(self._footer_lbl)
            outer.insertWidget(idx, bar)
            # Keep aligned when the user drags a column boundary
            self.table.horizontalHeader().sectionResized.connect(
                self._update_col_footer_widths
            )
            bar.hide()

        hlay = self._col_footer_hlay
        # Rebuild labels to reflect current column count / order
        while hlay.count():
            item = hlay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._col_footer_lbls.clear()

        # Find the index of the first column that has a value —
        # the row_label will go in the column directly to its left.
        first_value_col = -1
        for c in range(self.table.columnCount()):
            hdr = self.table.horizontalHeaderItem(c)
            col_name = hdr.text().strip() if hdr else ""
            if col_name in col_values:
                first_value_col = c
                break
        label_col = first_value_col - 1  # -1 means no left neighbour

        for c in range(self.table.columnCount()):
            hdr = self.table.horizontalHeaderItem(c)
            col_name = hdr.text().strip() if hdr else ""
            val = col_values.get(col_name)

            lbl = QLabel()
            lbl.setFixedWidth(self.table.columnWidth(c))
            lbl.setFixedHeight(22)
            lbl.setFont(_bold_font(10))

            if c == label_col and row_label:
                # Column immediately left of the value: right-aligned label
                lbl.setText(row_label)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl.setStyleSheet("color: #475569; padding-right: 6px; font-style: italic;")
            elif val is not None:
                # Value column: right-aligned bold number (integer only with commas)
                try:
                    fv = float(str(val).replace(",", "").strip())
                    text = f"{int(round(fv)):,}"
                except Exception:
                    text = str(val)
                lbl.setText(text)
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl.setStyleSheet("color: #1e293b; padding-right: 8px; font-weight: 700;")
            else:
                lbl.setText("")

            hlay.addWidget(lbl)
            self._col_footer_lbls[c] = lbl

        self._col_footer_bar.show()
        # Hide the plain text footer when col-footer is active (avoid double line)
        self._footer_lbl.hide()

    def _update_col_footer_widths(self, logical_index: int, _old: int, new_size: int):
        """Keep footer labels in sync when the user resizes a column."""
        lbl = getattr(self, '_col_footer_lbls', {}).get(logical_index)
        if lbl:
            lbl.setFixedWidth(new_size)

    # ------------------------------------------------------------------
    # Column management (add / remove via right-click on column header)
    # ------------------------------------------------------------------

    def _vhdr_ctx(self, pos):
        if not self._can_edit:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        act_hide = menu.addAction("👁️  Hide S.N")
        act_hide_all = menu.addAction("👁️  Hide S.N (All Tables)")
        chosen = menu.exec(QCursor.pos())
        if chosen == act_hide:
            self._set_sn_visible(False, all_tables=False)
        elif chosen == act_hide_all:
            self._set_sn_visible(False, all_tables=True)

    def _set_sn_visible(self, visible: bool, all_tables: bool = False):
        if all_tables:
            tp = getattr(self, '_today_tab_ref', None)
            if tp and hasattr(tp, '_section_cards'):
                for card in tp._section_cards.values():
                    card._set_sn_visible(visible, all_tables=False)
            return

        self._show_sn = visible
        self.table.verticalHeader().setVisible(visible)
        from PyQt6.QtCore import QSettings
        settings = QSettings("TallySync", "SuppPayment")
        settings.setValue(f"show_sn_tp_{self.section_id}", visible)
        self._recalc_width()

    def _col_hdr_ctx(self, pos):
        """Extended column-header context menu: resize helpers + add/remove columns."""
        hdr  = self.table.horizontalHeader()
        logical = hdr.logicalIndexAt(pos)

        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        # ---- existing smart-header actions ----
        a_fit     = menu.addAction("↔  Fit Column to Content")
        a_fit_all = menu.addAction("↔  Fit All Columns to Content")
        is_stretch = hdr.stretchLastSection()
        a_stretch = menu.addAction(
            "📌  Stretch Last Column (On)" if is_stretch else "📌  Stretch Last Column (Off)"
        )
        if self._cols_locked is not None:
            menu.addSeparator()
            a_lock = menu.addAction(
                "🔓  Unlock Column Widths" if self._cols_locked else "🔒  Lock Column Widths"
            )
        else:
            a_lock = None

        menu.addSeparator()
        act_sn = menu.addAction("👁️  Hide S.N" if self._show_sn else "👁️  Show S.N")
        act_sn_all = menu.addAction("👁️  Hide S.N (All Tables)" if self._show_sn else "👁️  Show S.N (All Tables)")

        # ---- column management ----
        menu.addSeparator()
        a_ins_l = menu.addAction("➕  Insert Column Left")
        a_ins_r = menu.addAction("➕  Insert Column Right")
        menu.addSeparator()
        a_rename = menu.addAction("✏️  Rename Column")

        # Only allow removing columns that are NOT part of the fixed spec
        n_fixed = len(self._col_specs) if (self._fixed_cols and self._col_specs) else 0
        a_remove = menu.addAction("🗑️  Remove Column")
        a_remove.setEnabled(
            logical >= n_fixed and self.table.columnCount() > 1
        )

        chosen = menu.exec(hdr.mapToGlobal(pos))

        if chosen == a_fit:
            self.table.resizeColumnToContents(logical)
        elif chosen == a_fit_all:
            self.table.resizeColumnsToContents()
        elif chosen == a_stretch:
            hdr.setStretchLastSection(not is_stretch)
        elif a_lock and chosen == a_lock:
            self._set_cols_locked(not self._cols_locked)
        elif chosen == act_sn:
            self._set_sn_visible(not self._show_sn, all_tables=False)
        elif chosen == act_sn_all:
            self._set_sn_visible(not self._show_sn, all_tables=True)
        elif chosen == a_ins_l:
            self._insert_col_at(logical)
        elif chosen == a_ins_r:
            self._insert_col_at(logical + 1)
        elif chosen == a_rename:
            self._do_rename_col(logical)
        elif chosen == a_remove:
            self._remove_col_at(logical)

    def _insert_col_at(self, at_idx: int):
        """Insert a blank column at position at_idx and persist the layout."""
        if not self._can_edit:
            return
        name, ok = _styled_get_text(self, "Add Column", "Column name:")
        if not ok or not name.strip():
            return
        self.table.insertColumn(at_idx)
        self.table.setHorizontalHeaderItem(at_idx, QTableWidgetItem(name.strip()))
        self.table.setColumnWidth(at_idx, 120)
        self._save_cols()
        self._recalc()

    def _remove_col_at(self, col: int):
        """Remove a user-added column (extra columns only) and persist the layout."""
        if not self._can_edit:
            return
        hdr_item = self.table.horizontalHeaderItem(col)
        col_name = hdr_item.text() if hdr_item else f"Column {col + 1}"
        reply = _styled_question(
            self, "Remove Column",
            f"Remove column '{col_name}'? All data in this column will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.table.removeColumn(col)
        # Re-save all data so col_idx references stay correct
        self._save_cols()
        self._save_data()
        self._recalc()

    def _do_rename_col(self, col: int):
        """Rename any column (fixed or extra) and persist."""
        if not self._can_edit:
            return
        h   = self.table.horizontalHeaderItem(col)
        old = h.text() if h else ""
        new, ok = _styled_get_text(self, "Rename Column", "Column name:", text=old)
        if ok and new.strip():
            if not h:
                h = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(col, h)
            h.setText(new.strip())
            self._save_cols()

    # ------------------------------------------------------------------
    # Formula recalculation
    # ------------------------------------------------------------------

    def _get_table_provider(self):
        if hasattr(self, '_today_tab_ref') and self._today_tab_ref:
            if hasattr(self._today_tab_ref, 'get_table_by_name'):
                return self._today_tab_ref.get_table_by_name
        p = self.parent()
        while p is not None:
            if hasattr(p, 'get_table_by_name'):
                return p.get_table_by_name
            p = p.parent()
        return None

    def _recalc_formulas(self):
        """Re-evaluate all formula cells (=IF, cross-table, arithmetic) in this card's table.

        MUST be called BEFORE any column-sum or 'Left money' calculation so
        that the evaluated payment values are picked up by downstream totals.
        """
        from src.ui.supp_payment.shared import FORMULA_ROLE, _eval_if_formula, _safe_eval_expr, _format_eval_result
        table_provider = self._get_table_provider()
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    if not it:
                        continue
                    formula = it.data(FORMULA_ROLE)
                    if not formula:
                        continue
                    formula_str = str(formula).strip()
                    if formula_str.upper().startswith('=IF('):
                        result = _eval_if_formula(formula_str, r, self.table, table_provider)
                    else:
                        expr = formula_str[1:] if formula_str.startswith('=') else formula_str
                        result = _safe_eval_expr(expr, table_provider)
                    if result is not None:
                        display = _format_eval_result(result)
                        it.setText(display)
                        if isinstance(result, (int, float)):
                            it.setData(RAW_NUMERIC_ROLE, result)
        finally:
            self.table.blockSignals(False)

    def eventFilter(self, source, event):
        if getattr(self, 'table', None) and source is self.table and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_F2 and self._can_edit:
                self._is_edit_mode = True
                # Pass through - Qt's QAbstractItemView keyPressEvent handles F2
                # via EditKeyPressed trigger (added in set_edit_mode)
                return False
        elif source is self._hdr:
            t = event.type()
            if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                # Only start drag if the click wasn't on a button child
                child = self._hdr.childAt(event.pos())
                if child and isinstance(child, QPushButton):
                    return super().eventFilter(source, event)  # let button handle it
                self._drag_start_pos = event.pos()
                self._hdr.setCursor(Qt.CursorShape.ClosedHandCursor)
            elif t == QEvent.Type.MouseButtonRelease:
                self._drag_start_pos = None
                self._hdr.setCursor(Qt.CursorShape.OpenHandCursor)
            elif t == QEvent.Type.MouseMove and self._drag_start_pos is not None:
                if (event.pos() - self._drag_start_pos).manhattanLength() > 8:
                    from PyQt6.QtGui import QDrag
                    drag = QDrag(self)
                    mime = QMimeData()
                    mime.setText(str(self.section_id))
                    drag.setMimeData(mime)
                    # Grab the header and use it as the drag pixmap
                    pix = self._hdr.grab()
                    drag.setPixmap(pix)
                    drag.setHotSpot(event.pos())
                    self._drag_start_pos = None
                    self._hdr.setCursor(Qt.CursorShape.OpenHandCursor)
                    drag.exec(Qt.DropAction.MoveAction)
        return super().eventFilter(source, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            try:
                int(event.mimeData().text())  # must be a section_id int
                event.acceptProposedAction()
                self.setStyleSheet("border: 2px dashed #059669;")
            except ValueError:
                event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # Restore the card's original stylesheet — do NOT clear to "" which
        # wipes all styling (background, border, border-radius) until repaint.
        self.setStyleSheet("QFrame#CardFrame { background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; }")
    def dropEvent(self, event):
        self.setStyleSheet("")
        try:
            src_sid = int(event.mimeData().text())
        except ValueError:
            return
        if src_sid == self.section_id:
            return  # dropped on self — no-op
        # Use the direct reference stored at construction time
        if self._today_tab_ref:
            self._today_tab_ref._swap_table_positions(src_sid, self.section_id)
        event.acceptProposedAction()

    def _find_today_tab(self):
        """Kept for backward-compat; prefer _today_tab_ref."""
        return self._today_tab_ref

    def _load(self):
        if not self._db_name:
            return
        self._loading = True
        self.table.blockSignals(True)
        self.table.horizontalHeader().blockSignals(True)
        
        is_sn_col = False
        try:
            has_saved_cols = False
            if not self._fixed_cols:
                cols = self._db.execute_query(
                    self._db_name,
                    "SELECT col_index, col_name, col_width FROM tp_section_cols "
                    "WHERE section_id=? ORDER BY col_index", (self.section_id,)) or []
                if cols:
                    self.table.setColumnCount(len(cols))
                    for idx, (ci, cname, cw) in enumerate(cols):
                        self.table.setHorizontalHeaderItem(idx, QTableWidgetItem(cname or ""))
                        if cw:
                            has_saved_cols = True
                            self.table.setColumnWidth(idx, cw)
                        else:
                            self.table.setColumnWidth(idx, 120)
            else:
                # Fixed-cols table: restore saved column widths and check for extra columns
                if self._db_name:
                    try:
                        saved_widths = self._db.execute_query(
                            self._db_name,
                            "SELECT col_index, col_name, col_width FROM tp_section_cols "
                            "WHERE section_id=? ORDER BY col_index", (self.section_id,)) or []
                        n_fixed = len(self._col_specs) if self._col_specs else self.table.columnCount()
                        for ci, cname, cw in saved_widths:
                            col_i = int(ci)
                            if col_i >= n_fixed:
                                extra_c = self.table.columnCount()
                                self.table.insertColumn(extra_c)
                                self.table.setHorizontalHeaderItem(
                                    extra_c, QTableWidgetItem(cname or ""))
                                self.table.setColumnWidth(extra_c, int(cw) if cw else 120)
                            elif cw and col_i < self.table.columnCount():
                                self.table.setColumnWidth(col_i, int(cw))
                    except Exception:
                        pass

            # Safely try to fetch bg_color; if it fails (old db), fallback to without it
            try:
                data = self._db.execute_query(
                    self._db_name,
                    "SELECT row_idx, col_idx, cell_text, bg_color, fg_color FROM tp_section_data "
                    "WHERE section_id=? ORDER BY row_idx, col_idx", (self.section_id,)) or []
                has_colors = 2
            except Exception:
                try:
                    data = self._db.execute_query(
                        self._db_name,
                        "SELECT row_idx, col_idx, cell_text, bg_color FROM tp_section_data "
                        "WHERE section_id=? ORDER BY row_idx, col_idx", (self.section_id,)) or []
                    has_colors = 1
                except Exception:
                    data = self._db.execute_query(
                        self._db_name,
                        "SELECT row_idx, col_idx, cell_text FROM tp_section_data "
                        "WHERE section_id=? ORDER BY row_idx, col_idx", (self.section_id,)) or []
                    has_colors = 0
                
            # Reconstruct rows in memory first to filter out ghost rows (e.g. only S.N populated)
            row_map = {}
            for row in data:
                if has_colors == 2 and len(row) == 5:
                    ri, ci, txt, bg, fg = row
                elif has_colors == 1 and len(row) == 4:
                    ri, ci, txt, bg = row
                    fg = ""
                else:
                    ri, ci, txt = row
                    bg = ""
                    fg = ""
                    
                txt_str = str(txt).strip() if txt else ""
                if not txt_str and not bg and not fg: continue
                if ri not in row_map: row_map[ri] = {}
                row_map[ri][ci] = (txt_str, bg, fg)
                
            # Determine if col 0 is an S.N column
            is_sn_col = False
            if self.table.columnCount() > 0:
                h = self.table.horizontalHeaderItem(0)
                if h and h.text().replace(".", "").strip().upper() in ("SN", "SNO"):
                    is_sn_col = True

            # Filter rows: A row is considered "valid" if it has data in any real column
            valid_rows = []
            for ri in sorted(row_map.keys()):
                has_real_data = any((ci > 0 if is_sn_col else True) and (val[0] or val[1] or val[2]) for ci, val in row_map[ri].items())
                
                if has_real_data or (is_sn_col and 0 in row_map[ri] and len(row_map[ri]) == 1):
                    valid_rows.append(row_map[ri])
                    
            # Trim trailing rows
            while valid_rows:
                last_row = valid_rows[-1]
                if not any((ci > 0 if is_sn_col else True) and (val[0] or val[1] or val[2]) for ci, val in last_row.items()):
                    valid_rows.pop()
                else:
                    break
                    
            self.table.setRowCount(len(valid_rows) + 1) # +1 for a clean empty row at the bottom
            from PyQt6.QtGui import QBrush, QColor
            for new_ri, r_data in enumerate(valid_rows):
                for ci, val_tuple in r_data.items():
                    if ci < self.table.columnCount():
                        txt, bg, fg = val_tuple
                        it = QTableWidgetItem()
                        if bg:
                            it.setBackground(QBrush(QColor(bg)))
                        if fg:
                            it.setForeground(QBrush(QColor(fg)))
                        # Restore formula cells: store raw formula in FORMULA_ROLE,
                        # evaluate and display the result as the cell text.
                        if txt.startswith('='):
                            from src.ui.supp_payment.shared import FORMULA_ROLE
                            it.setData(FORMULA_ROLE, txt)
                            it.setText("")   # placeholder; _recalc_formulas() will populate evaluated result
                        else:
                            it.setText(txt)
                        self.table.setItem(new_ri, int(ci), it)
                        
        finally:
            self.table.blockSignals(False)
            self.table.horizontalHeader().blockSignals(False)
            self._loading = False
            if is_sn_col or (self._col_specs and self._col_specs[0][0] == "S.N"):
                self.table.setColumnHidden(0, True)

            # Re-evaluate formula cells FIRST so downstream calculations and size hints
            # use evaluated numbers rather than raw formula text.
            self._recalc_formulas()

            # Ensure columns are wide enough for evaluated content (capped safely)
            self._expand_all_columns_to_contents()

            self._update_sum()
            self._recalc()

    def _update_sum(self):
        if "DL" not in self.section_name:
            self._footer_lbl.hide()
            return

        sum_cols = []
        for c in range(self.table.columnCount()):
            h = self.table.horizontalHeaderItem(c)
            if h and h.text().strip().upper() in ("AMOUNT", "PAYMENT"):
                sum_cols.append(c)
        if not sum_cols:
            self._footer_lbl.hide()
            return
        totals = {c: 0.0 for c in sum_cols}
        for r in range(self.table.rowCount()):
            for c in sum_cols:
                it = self.table.item(r, c)
                if it and it.text():
                    raw = it.data(RAW_NUMERIC_ROLE)
                    if raw is not None and isinstance(raw, (int, float)):
                        totals[c] += float(raw)
                    else:
                        try:
                            val = it.text().strip().replace(",", "")
                            totals[c] += float(val)
                        except ValueError: pass
        if any(t > 0 for t in totals.values()):
            parts = [f"{self.table.horizontalHeaderItem(c).text()} {int(round(totals[c])):,}" for c in sum_cols]
            self._footer_lbl.setText("Total  " + " | ".join(parts))
            self._footer_lbl.show()
        else:
            self._footer_lbl.hide()


    def _save_data(self):
        if not self._db_name or self._saving:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        self._saving = True
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_data WHERE section_id=?", (self.section_id,))
            
            # Find last content row to avoid saving trailing empty rows
            last_content = -1
            is_sn_col = False
            if self.table.columnCount() > 0:
                h = self.table.horizontalHeaderItem(0)
                if h and h.text().replace(".", "").strip().upper() in ("SN", "SNO"):
                    is_sn_col = True
                    
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    if is_sn_col and c == 0:
                        continue # Skip col 0 (S.N) when checking for emptiness
                    it = self.table.item(r, c)
                    if it:
                        val = str(it.text()).strip()
                        bg = it.data(Qt.ItemDataRole.BackgroundRole)
                        fg = it.data(Qt.ItemDataRole.ForegroundRole)
                        if val or bg or fg:
                            last_content = r
                            break

            rows_to_insert = []
            for r in range(last_content + 1):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    # If this cell holds a formula, save the raw formula text so it
                    # can be restored and re-evaluated correctly on next load.
                    from src.ui.supp_payment.shared import FORMULA_ROLE
                    formula = it.data(FORMULA_ROLE) if it else None
                    val = formula if formula else (str(it.text()).strip() if it else "")

                    bg_color = ""
                    bg_data = it.data(Qt.ItemDataRole.BackgroundRole) if it else None
                    if bg_data:
                        from PyQt6.QtGui import QBrush, QColor
                        if isinstance(bg_data, QBrush): bg_color = bg_data.color().name()
                        elif isinstance(bg_data, QColor): bg_color = bg_data.name()
                        else: bg_color = QBrush(bg_data).color().name()
                        if bg_color == "#000000" and not QColor(bg_color).isValid(): bg_color = ""
                    
                    fg_color = ""
                    fg_data = it.data(Qt.ItemDataRole.ForegroundRole) if it else None
                    if fg_data:
                        from PyQt6.QtGui import QBrush, QColor
                        if isinstance(fg_data, QBrush): fg_color = fg_data.color().name()
                        elif isinstance(fg_data, QColor): fg_color = fg_data.name()
                        else: fg_color = QBrush(fg_data).color().name()
                    
                    if val or bg_color or fg_color:
                        rows_to_insert.append((self.section_id, r, c, val, bg_color or None, fg_color or None))

            # Atomic delete + bulk insert in a single transaction
            cur.execute("DELETE FROM tp_section_data WHERE section_id=?", (self.section_id,))
            if rows_to_insert:
                insert_sql = (
                    "INSERT INTO tp_section_data(section_id, row_idx, col_idx, cell_text, bg_color, fg_color) "
                    "VALUES(?, ?, ?, ?, ?, ?)"
                )
                try:
                    cur.fast_executemany = True
                    cur.executemany(insert_sql, rows_to_insert)
                except Exception:
                    cur.fast_executemany = False
                    cur.executemany(insert_sql, rows_to_insert)

            conn.commit()
            self._update_sum()
            if self._today_tab_ref:
                _ref = self._today_tab_ref
                QTimer.singleShot(0, _ref._update_all_calculations)
        except Exception as e:
            conn.rollback()
            _logger.error(f"[TodayPayment] _save_data section={self.section_id}: {e}")
        finally:
            cur.close()
            self._saving = False

    def _save_cols(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cols_to_insert = []
            for c in range(self.table.columnCount()):
                h = self.table.horizontalHeaderItem(c)
                col_name = h.text() if h else ""
                cols_to_insert.append((self.section_id, c, col_name, self.table.columnWidth(c)))

            cur.execute("DELETE FROM tp_section_cols WHERE section_id=?", (self.section_id,))
            if cols_to_insert:
                col_sql = "INSERT INTO tp_section_cols(section_id, col_index, col_name, col_width) VALUES(?, ?, ?, ?)"
                try:
                    cur.fast_executemany = True
                    cur.executemany(col_sql, cols_to_insert)
                except Exception:
                    cur.fast_executemany = False
                    cur.executemany(col_sql, cols_to_insert)

            conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.error(f"[TodayPayment] _save_cols section={self.section_id}: {e}")
        finally:
            cur.close()

    def _update_db(self, field, value):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            # Bracket the identifier to avoid SQL reserved-word conflicts (e.g. 'key', 'name', 'order')
            cur.execute(f"UPDATE tp_sections SET [{field}]=? WHERE id=?", (value, self.section_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.error(f"[TodayPayment] _update_db field='{field}' section={self.section_id}: {e}")
        finally:
            cur.close()

    def _delete_from_db(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_data WHERE section_id=?", (self.section_id,))
            cur.execute("DELETE FROM tp_section_cols WHERE section_id=?", (self.section_id,))
            cur.execute("DELETE FROM tp_sections WHERE id=?", (self.section_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            cur.close()

    # ------------------------------------------------------------ Actions --
    def _on_change(self, item):
        if not getattr(self, '_saving', False) and not getattr(self, '_loading', False):
            # Auto-format numeric values to int with commas for money columns,
            # while storing full decimal precision in UserRole + 1 for calculations.
            c = item.column()
            h_item = self.table.horizontalHeaderItem(c)
            if h_item:
                h_text = h_item.text().strip().lower()
                if any(k in h_text for k in ("amount", "remain", "bank", "cash", "payment", "salary", "bonus", "rakam")):
                    val = item.text().strip()
                    if val and not val.startswith("="):
                        try:
                            f = float(val.replace(",", "").strip())
                            item.setData(RAW_NUMERIC_ROLE, f)
                            formatted = f"{int(round(f)):,}"
                            if item.text().strip() != formatted:
                                self.table.blockSignals(True)
                                item.setText(formatted)
                                self.table.blockSignals(False)
                        except Exception:
                            pass

            self._expand_column_to_contents(item.column())
            self._recalc_width()
        # Debounce: restart the 300 ms timer so rapid edits produce only one DB write.
        if hasattr(self, '_today_tab_ref') and self._today_tab_ref:
            self._today_tab_ref._notify_table_changed(self.section_name)
        self._save_timer.start(300)

    def _add_column(self):
        if not self._can_edit or self._fixed_cols:
            return
        c = self.table.columnCount()
        self.table.insertColumn(c)
        self.table.setHorizontalHeaderItem(c, QTableWidgetItem(f"Column {c + 1}"))
        self.table.setColumnWidth(c, 120)
        self._save_cols()
        self._recalc()

    def _add_row(self):
        if not self._can_edit:
            return
        if not self._fixed_cols and self.table.columnCount() == 0:
            _styled_info(self, "Cannot Delete", "Cannot delete the last row.")
            return
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self._expand_all_columns_to_contents()
        self._save_data()
        self._recalc()

    def _rename_col(self, col):
        if not self._can_edit or self._fixed_cols:
            return
        h = self.table.horizontalHeaderItem(col)
        old = h.text() if h else ""
        new, ok = _styled_get_text(self, "Rename Column", "Column name:", text=old)
        if ok and new.strip():
            if not h:
                h = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(col, h)
            h.setText(new.strip())
            self._save_cols()

    def _row_ctx(self, pos):
        if not self._can_edit:
            return
        item = self.table.itemAt(pos)
        r = item.row() if item else self.table.currentRow()
        menu = QMenu(self)
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QBrush, QColor
        menu.setStyleSheet(_MENU_STYLE)

        a_add_above = menu.addAction("\u2191  Add Row Above")
        a_add_below = menu.addAction("\u2193  Add Row Below")
        menu.addSeparator()

        a_del = menu.addAction("\u2715  Delete Row")
        menu.addSeparator()
        a_color = menu.addAction("\u25cf  Set Cell Color")
        a_text_color = menu.addAction("\u25d0  Set Text Color")
        a_clear = menu.addAction("\u25cb  Clear Colors")
        
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if act == a_add_above and r >= 0:
            self.table.insertRow(r)
            self._save_data()
            self._recalc()
        elif act == a_add_below and r >= 0:
            self.table.insertRow(r + 1)
            self._save_data()
            self._recalc()
        elif act == a_del and r >= 0:
            # Never delete the trailing empty row — delete the row above it instead
            last_row = self.table.rowCount() - 1
            if r == last_row:
                r = max(0, last_row - 1)
            if r < last_row:  # only delete real data rows
                self.table.removeRow(r)
                self._save_data()
                self._recalc()
        elif act == a_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.table.setItem(idx.row(), idx.column(), it)
                    it.setBackground(QBrush(color))
                self.table.blockSignals(False)
                self._expand_all_columns_to_contents()
                self._save_data()
        elif act == a_text_color:
            color = _styled_get_color(self)
            if color.isValid():
                self.table.blockSignals(True)
                for idx in self.table.selectedIndexes():
                    it = self.table.item(idx.row(), idx.column())
                    if not it:
                        it = QTableWidgetItem("")
                        self.table.setItem(idx.row(), idx.column(), it)
                    it.setForeground(QBrush(color))
                self.table.blockSignals(False)
                self._expand_all_columns_to_contents()
                self._save_data()
        elif act == a_clear:
            self.table.blockSignals(True)
            for item in self.table.selectedItems():
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
            self.table.blockSignals(False)
            self._expand_all_columns_to_contents()
            self._save_data()

    def _header_ctx(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        a_color = menu.addAction("\u25cf  Change Header Color")
        a_clear = menu.addAction("\u25cb  Default Color")
        act = menu.exec(self._hdr.mapToGlobal(pos))
        if act == a_color:
            color = _styled_get_color(self)
            if color.isValid():
                self._header_color = color.name()
                self._update_hdr_style()
                self._update_section_color_in_db()
        elif act == a_clear:
            self._header_color = ""
            self._update_hdr_style()
            self._update_section_color_in_db()
            
    def _update_hdr_style(self):
        bg = self._header_color
        if not bg:
            # Fallback pastel bg based on title if no DB color exists
            title_lower = getattr(self, "section_name", "").lower()
            if "payment" in title_lower: bg = "#d1fae5"
            elif "loan" in title_lower: bg = "#e0e7ff"
            elif "invoice" in title_lower: bg = "#fef3c7"
            elif "card" in title_lower: bg = "#fce7f3"
            else: bg = "#f1f5f9"
            
        self._hdr.setStyleSheet(f"""
            QWidget {{ background: {bg}; border-bottom: 1px solid #e2e8f0; border-top-left-radius: 12px; border-top-right-radius: 12px; }}
            QLabel {{ color: #191c1e; font-weight: 600; font-size: 11pt; }}
            QPushButton {{
                background: rgba(255, 255, 255, 0.6); color: #475569; border: 1px solid rgba(0,0,0,0.1); border-radius: 6px; padding: 4px 12px; font-size: 9pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: #ffffff; color: #0f172a; }}
        """)
            
    def _update_section_color_in_db(self):
        if not self._db_name: return
        conn = self._db.get_connection(self._db_name)
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("UPDATE tp_sections SET header_color=? WHERE id=?", (self._header_color, self.section_id))
                conn.commit()
            except Exception as e:
                _logger.error(f"[TodayPayment] save header_color section={self.section_id}: {e}")
            finally:
                cur.close()

    def _show_gear(self):
        if self._fixed_cols:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        a_ren = menu.addAction("\u270e  Rename Table")
        a_col = menu.addAction("\u25cf  Change Header Color")
        menu.addSeparator()
        a_del = menu.addAction("\u2715  Delete Table")
        act = menu.exec(self._btn_gear.mapToGlobal(self._btn_gear.rect().bottomLeft()))
        if act == a_ren:
            new, ok = _styled_get_text(self, "Rename Table", "Name:", text=self.title_lbl.text())
            if ok and new.strip():
                self.title_lbl.setText(new.strip())
                self._update_db("name", new.strip())
        elif act == a_del:
            msg = QMessageBox(self)
            msg.setWindowTitle("Delete Table")
            msg.setText(f"Delete '{self.title_lbl.text()}'?\nAll data will be lost.")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setStyleSheet(_POPUP_STYLE)
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self._delete_from_db()
                tp = self._today_tab_ref
                if tp:
                    tp._rebuild_section_views()


    def _recalc_width(self):
        tw = 0
        for c in range(self.table.columnCount()):
            if not self.table.isColumnHidden(c):
                tw += self.table.columnWidth(c)
        if not self.table.verticalHeader().isHidden():
            tw += max(self.table.verticalHeader().width(), 36)

        # In single-view the card fills the full pane — do NOT lock the card width.
        # Only tightly wrap in multi-view so the grid doesn’t bloat after toggling.
        if getattr(self, '_in_single_view', False):
            return

        # Both scroll bars are permanently off (AlwaysOff), so no scrollbar width
        # needs to be reserved. Tight-wrap exactly to the column sum.
        # Minimum 200px so empty (no-column) tables are still usable.
        new_w = max(tw + 2, 200)
        self.setFixedWidth(new_w)
        # Keep _card_fixed_width in sync so single/multi toggle restores correctly.
        self._card_fixed_width = new_w

    def _on_section_resized(self, logicalIndex, oldSize, newSize):
        if getattr(self, '_loading', False) or getattr(self, '_enforcing', False) or getattr(self, '_expanding', False): return
        
        if not hasattr(self, '_resize_timers'):
            self._resize_timers = {}
            
        if logicalIndex not in self._resize_timers:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda idx=logicalIndex: self._enforce_col_min(idx))
            self._resize_timers[logicalIndex] = t
            
        self._resize_timers[logicalIndex].start(300)
        
        if not getattr(self, '_saving', False):
            if not hasattr(self, '_recalc_timer'):
                self._recalc_timer = QTimer(self)
                self._recalc_timer.setSingleShot(True)
                self._recalc_timer.timeout.connect(self._do_recalc_and_save)
            self._recalc_timer.start(300)

    def _do_recalc_and_save(self):
        self._recalc_width()
        self._save_cols()
        
    def _enforce_col_min(self, logicalIndex):
        self._enforcing = True
        fm = self.table.fontMetrics()
        h_item = self.table.horizontalHeaderItem(logicalIndex)
        min_w = 40
        if h_item and h_item.text():
            min_w = max(min_w, fm.horizontalAdvance(h_item.text()) + 20)
            
        if self.table.columnWidth(logicalIndex) < min_w:
            self.table.setColumnWidth(logicalIndex, min_w)
        self._enforcing = False

    # ------------------------------------------------------------------
    # Safe resize helpers — ONLY expand, never shrink user-set widths
    # ------------------------------------------------------------------
    def _expand_column_to_contents(self, col: int):
        """Grow column col to fit its content if content is wider than current width.
        Uses _expanding guard so the programmatic setColumnWidth does not re-trigger
        _on_section_resized (prevents spurious _save_cols calls).
        """
        if col < 0 or col >= self.table.columnCount():
            return
        current = self.table.columnWidth(col)
        hint    = self.table.sizeHintForColumn(col)
        hint    = min(hint, 350)
        if hint > current:
            self._expanding = True
            self.table.setColumnWidth(col, hint)
            self._expanding = False

    def _expand_all_columns_to_contents(self):
        """Grow every column to fit content, but never shrink a column the user widened."""
        for c in range(self.table.columnCount()):
            self._expand_column_to_contents(c)

    def _recalc(self, single_view=False):
        """Set table height based on its content so cards don't stretch.

        Args:
            single_view: True when the card is displayed full-width in single-view
                         mode (larger cap). False for compact multi-view grid cards.
        """
        cols = self.table.columnCount()
        hh = max(self.table.horizontalHeader().sizeHint().height(), 24) if cols else 0
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) != 26:
                self.table.setRowHeight(r, 26)
        rh = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        # 10px buffer: covers grid-line, layout margins and any sub-pixel rounding
        # that can cause the last row to be partially clipped.
        h = hh + rh + 10
        # Single-view gets a larger cap (full-width pane, user can scroll the pane).
        # Multi-view gets a compact cap so cards don't dominate the grid.
        max_h = 800 if single_view else 600
        h = min(max(h, 60), max_h)
        self.table.setMinimumHeight(h)
        self._recalc_width()
        self.table.setMaximumHeight(h)
        # Constrain the card's own height to match the table + header bar.
        hdr_h = self._hdr.sizeHint().height() if self._hdr else 36
        footer_h = self._footer_lbl.sizeHint().height() if self._footer_lbl.isVisible() else 0
        col_footer_h = self._col_footer_bar.sizeHint().height() if hasattr(self, '_col_footer_bar') and self._col_footer_bar.isVisible() else 0
        card_h = max(hdr_h + h + footer_h + col_footer_h + 2, 80)
        self.setFixedHeight(card_h)

    def _set_cols_locked(self, locked: bool, save_to_db: bool = True):
        """Lock or unlock all column widths on this card's table."""
        self._cols_locked = locked
        hh = self.table.horizontalHeader()
        if locked:
            hh.setSectionResizeMode(hh.ResizeMode.Fixed)
        else:
            hh.setSectionResizeMode(hh.ResizeMode.Interactive)

        # Persist to DB so state survives restarts
        if save_to_db and self._db and self._db_name and self.section_id:
            try:
                conn = self._db.get_connection(self._db_name)
                if conn:
                    cur = conn.cursor()
                    try:
                        cur.execute(
                            "UPDATE tp_sections SET cols_locked=? WHERE id=?",
                            (1 if locked else 0, self.section_id)
                        )
                        conn.commit()
                    finally:
                        cur.close()
            except Exception:
                pass


    def set_edit_mode(self, can_edit):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
            | QTableWidget.EditTrigger.EditKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        self._btn_row.setEnabled(can_edit)
        if not self._fixed_cols:
            self._btn_col.setEnabled(can_edit)
            self._btn_gear.setEnabled(can_edit)

    def reload_completer(self, col_idx, data_list):
        """Update autocomplete data for a specific column at runtime."""
        delegate = self.table.itemDelegateForColumn(col_idx)
        if hasattr(delegate, '_data_getter'):
            pass  # data_getter is a lambda; just reassign delegate
        new_delegate = ModernTableDelegate(self, cell_type="autocomplete", autocomplete_items=lambda dl=data_list: dl)
        self.table.setItemDelegateForColumn(col_idx, new_delegate)
        self._connect_nav(new_delegate)  # enable Enter-moves-down on the new delegate

    # ── Enter-key navigation: commit and move to next row ─────────────────

    def _setup_enter_navigation(self):
        """Connect closeEditor signals from all current delegates to the move-down handler."""
        self._connect_nav(self.table.itemDelegate())
        for col in range(self.table.columnCount()):
            d = self.table.itemDelegateForColumn(col)
            if d is not None and d is not self.table.itemDelegate():
                self._connect_nav(d)

    def _connect_nav(self, delegate):
        """Connect delegate.closeEditor → _on_editor_close_for_nav (once per delegate)."""
        if delegate and not getattr(delegate, '_nav_connected', False):
            delegate.closeEditor.connect(self._on_editor_close_for_nav)
            delegate._nav_connected = True

    def _on_editor_close_for_nav(self, editor, hint):
        """Move selection to the next row when Enter commits the editor.
        SubmitModelCache = Enter pressed (not Tab, not Escape, not dropdown selection).
        Guard: only act if the editor belongs to THIS card's table to avoid the
        'editor does not belong to this view' warning when cards are re-parented."""
        from PyQt6.QtWidgets import QAbstractItemDelegate
        # Verify editor is a descendant of our table's viewport
        vp = self.table.viewport()
        w = editor
        while w is not None:
            if w is vp:
                break
            w = w.parent()
        else:
            return  # editor belongs to a different view — ignore

        if hint == QAbstractItemDelegate.EndEditHint.SubmitModelCache:
            cur = self.table.currentIndex()
            if cur.isValid():
                next_row = cur.row() + 1
                if next_row < self.table.rowCount():
                    QTimer.singleShot(0, lambda r=next_row, c=cur.column():
                        self.table.setCurrentCell(r, c))



# ===========================================================================
# TODAY PAYMENT TAB
# ===========================================================================
class TodayPaymentTabV2(QWidget, _PrintExportMixin):

    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._db = get_db_manager()
        self._db_name = ""
        self._party_list = []         # Sundry Creditors list for Payments col 3
        self._section_cards = {}      # section_id -> _SectionCardV2
        self._current_view = 1        # 0=single, 1=multi
        self._updating_calcs = False

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Body: QStackedWidget switching between single and multi view ----
        self._body_stack = QStackedWidget()
        self._body_stack.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._body_stack, 1)

        # ---- Right bar ----
        right_bar = QWidget()
        right_bar.setStyleSheet("background:#f8fafc; border-left:1px solid #e2e8f0;")
        right_bar.setFixedWidth(52)  # Slightly wider for icons
        tlay = QVBoxLayout(right_bar)
        tlay.setContentsMargins(6, 16, 6, 16)
        tlay.setSpacing(12)

        from src.ui.supp_payment.shared import get_icon
        self._btn_add = QPushButton()
        self._btn_add.setIcon(get_icon("add.svg"))
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_section)
        tlay.addWidget(self._btn_add)

        # View toggle
        toggle_frame = QFrame()
        toggle_frame.setStyleSheet(
            "QFrame{background:#e2e8f0;border-radius:6px;}")
        tgl = QVBoxLayout(toggle_frame)  # Stack vertically in right bar
        tgl.setContentsMargins(3, 3, 3, 3)
        tgl.setSpacing(2)

        _ts = ("QPushButton{border-radius:4px;padding:8px 4px;font-size:11pt;border:none;font-weight:bold;}"
               "QPushButton:checked{background:#ffffff;color:#0f172a;border:1px solid #cbd5e1;}"
               "QPushButton:!checked{background:transparent;color:#64748b;}"
               "QPushButton:!checked:hover{color:#334155;}"
               "QToolTip{background-color:#1e293b;color:#ffffff;border:none;padding:5px 9px;border-radius:4px;font-size:11px;}")
        def on_toggle_tp(expanded):
            if expanded:
                self._btn_add.setText(" Add Table")
                self._btn_single.setText(" Single")
                self._btn_stack.setText(" Multi")
            else:
                self._btn_add.setText("")
                self._btn_single.setText("")
                self._btn_stack.setText("")

        self._init_print_export(tlay, "Today Payment", supports_print=True, table_getter=self._get_tables_for_export, right_bar=right_bar, on_toggle_cb=on_toggle_tp)
        self._export_grid_cols = 3  # TodayPayment uses 3-column grid layout in UI

        self._btn_single = QPushButton()
        self._btn_single.setIcon(get_icon("single.svg"))
        self._btn_single.setCheckable(True)
        self._btn_stack  = QPushButton()
        self._btn_stack.setIcon(get_icon("multi.svg"))
        self._btn_stack.setCheckable(True)
        self._btn_stack.setChecked(True)
        for b in (self._btn_single, self._btn_stack):
            b.setStyleSheet(_ts)
            tgl.addWidget(b)
        self._btn_single.clicked.connect(lambda: self._switch_view(0))
        self._btn_stack.clicked.connect(lambda: self._switch_view(1))
        tlay.addWidget(toggle_frame)
        
        tlay.addStretch()
        main_layout.addWidget(right_bar, 0)

        # =====================================================================
        # VIEW 0 — Single Table (sidebar + full-width table)
        # =====================================================================
        single_body = QWidget()
        single_body.setStyleSheet("background:#f8fafc;")
        single_hlay = QHBoxLayout(single_body)
        single_hlay.setContentsMargins(0, 0, 0, 0)
        single_hlay.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(176)
        sidebar.setStyleSheet("background:#f1f5f9; border-right:1px solid #e2e8f0;")
        s_lay = QVBoxLayout(sidebar)
        s_lay.setContentsMargins(6, 8, 6, 8)
        s_lay.setSpacing(4)

        s_label = QLabel("TABLES")
        s_label.setFont(_bold_font(8))
        s_label.setStyleSheet("color:#94a3b8; letter-spacing:1px; padding-left:4px;")
        s_lay.addWidget(s_label)

        self._sidebar_list = QListWidget()
        self._sidebar_list.setFont(_norm_font())
        self._sidebar_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self._sidebar_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._sidebar_list.setStyleSheet("""
            QListWidget {
                background: transparent; border: none; font-size: 10pt;
            }
            QListWidget::item {
                padding: 6px 8px; border-radius: 5px; color: #374151;
            }
            QListWidget::item:selected {
                background: #d1fae5; color: #059669; font-weight: bold;
            }
            QListWidget::item:hover:!selected { background: #e2e8f0; }
        """)
        self._sidebar_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sidebar_list.customContextMenuRequested.connect(self._show_sidebar_menu)
        self._sidebar_list.currentRowChanged.connect(self._on_sidebar_select)
        self._sidebar_list.itemDoubleClicked.connect(self._rename_section_from_sidebar)
        self._sidebar_list.model().rowsMoved.connect(self._on_sidebar_reordered)
        s_lay.addWidget(self._sidebar_list)
        single_hlay.addWidget(sidebar)

        # Single table content pane
        self._single_pane = QWidget()
        self._single_pane.setStyleSheet("background:#f8fafc;")
        sp_lay = QVBoxLayout(self._single_pane)
        sp_lay.setContentsMargins(0, 0, 0, 0)
        sp_lay.setSpacing(0)

        self._single_placeholder = QLabel("Select a table from the left panel")
        self._single_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._single_placeholder.setStyleSheet("color:#94a3b8; font-size:13pt;")
        sp_lay.addWidget(self._single_placeholder)

        self._single_card_holder = QVBoxLayout()
        self._single_card_holder.setContentsMargins(0, 0, 0, 0)
        self._single_card_holder.setSpacing(0)
        sp_lay.addLayout(self._single_card_holder)
        sp_lay.addStretch()
        single_hlay.addWidget(self._single_pane, 1)

        self._body_stack.addWidget(single_body)

        # =====================================================================
        # VIEW 1 — Multi View (2-column grid, no sidebar)
        # =====================================================================
        multi_scroll = QScrollArea()
        multi_scroll.setWidgetResizable(True)
        multi_scroll.setFrameShape(QFrame.Shape.NoFrame)
        multi_scroll.setStyleSheet("QScrollArea{background:#f1f5f9;}" + _SCROLLBAR_STYLE)

        self._multi_container = QWidget()
        self._multi_container.setStyleSheet("background:transparent;")
        # Use a VBox of HBox rows so each row is only as wide as its cards
        self._multi_layout = QVBoxLayout(self._multi_container)
        self._multi_layout.setContentsMargins(6, 6, 400, 6)
        self._multi_layout.setSpacing(8)
        self._multi_layout.addStretch(1)  # bottom stretch placeholder
        # Keep _multi_grid as None so any stale references error loudly
        self._multi_grid = None
        self._multi_row_layouts = []  # track child QHBoxLayouts for cleanup

        multi_scroll.setWidget(self._multi_container)
        self._body_stack.addWidget(multi_scroll)

        self._body_stack.setCurrentIndex(1)   # default: multi view

    def get_table_by_name(self, name: str):
        target = name.strip().lower()
        for card in self._section_cards.values():
            if card.section_name.strip().lower() == target:
                return card.table
        # Check Anil Dai Hisab if accessible
        parent_ui = self.parent()
        while parent_ui is not None and parent_ui.__class__.__name__ != "SuppPaymentV2UI":
            parent_ui = parent_ui.parent()
        if parent_ui:
            if target == "anil dai hisab" and hasattr(parent_ui, "_anil_tab"):
                return parent_ui._anil_tab.table
            if target == "bank a/c" and hasattr(parent_ui, "_record_tab"):
                return parent_ui._record_tab.table
        return None

    def _notify_table_changed(self, table_name: str):
        if getattr(self, '_updating_calcs', False):
            return
        self._updating_calcs = True
        try:
            graph = {}
            import re
            from PyQt6.QtCore import Qt
            FORMULA_ROLE = Qt.ItemDataRole.UserRole + 50
            pattern = r'\[([^\]]+)\]\[([^\]]+)\]\[(\d+)(?::\d+)?\]'
            for card in self._section_cards.values():
                for r in range(card.table.rowCount()):
                    for c in range(card.table.columnCount()):
                        it = card.table.item(r, c)
                        if it:
                            f = it.data(FORMULA_ROLE)
                            if f:
                                for m in re.findall(pattern, str(f)):
                                    target = m[0].strip().lower()
                                    if target not in graph:
                                        graph[target] = set()
                                    graph[target].add(card.section_name.strip().lower())
            
            t_name = table_name.strip().lower()
            if t_name in graph:
                for dep in graph[t_name]:
                    for card in self._section_cards.values():
                        if card.section_name.strip().lower() == dep:
                            card._recalc_formulas()
                            card._update_sum()
                            card._recalc()
                            # recursively notify? No, just one level is fine for now
        finally:
            self._updating_calcs = False

    def _get_tables_for_export(self):
        """Collect all section card tables for the Excel export.
        Respects is_column_break so the grid layout matches the on-screen view.
        """
        from src.ui.table_nav_mixin import get_visual_text
        tables = []
        current_grid_col = 0

        for sid, card in self._section_cards.items():
            # A column-break card starts a new grid column
            if card.is_column_break:
                current_grid_col += 1

            tbl = card.table
            has_data = False
            for r in range(tbl.rowCount()):
                for c in range(tbl.columnCount()):
                    if get_visual_text(tbl, r, c).strip():
                        has_data = True
                        break
                if has_data:
                    break
            if has_data:
                # Identify columns to round to int based on headers
                round_int_cols = set()
                for c in range(tbl.columnCount()):
                    h_item = tbl.horizontalHeaderItem(c)
                    h_text = h_item.text().strip().lower() if h_item else ""
                    if any(k in h_text for k in ("amount", "remain", "bank", "cash", "payment", "salary", "bonus", "rakam")):
                        round_int_cols.add(c)

                tables.append({
                    "title": card.title_lbl.text(),
                    "table": tbl,
                    "grid_col": current_grid_col,
                    "header_color": card._header_color or "#f1f5f9",
                    "round_int_cols": round_int_cols,
                })
        return tables

    def _switch_view(self, idx):
        self._current_view = idx
        self._btn_single.setChecked(idx == 0)
        self._btn_stack.setChecked(idx == 1)
        self._body_stack.setCurrentIndex(idx)
        if idx == 0:
            self._on_sidebar_select(self._sidebar_list.currentRow())
        else:
            # Before rebuilding the multi-view grid, restore width constraints for every
            # card that was left in single-view mode (setMinimumWidth(0) + setMaximumWidth
            # QWIDGETSIZE_MAX were applied on entry to single-view). Without restoring them
            # first, _rebuild_multi_grid places the card into a QVBoxLayout with no fixed
            # width and the layout squashes it to an arbitrary narrow width.
            for card in self._section_cards.values():
                if getattr(card, '_in_single_view', False):
                    card.setFrameShape(QFrame.Shape.StyledPanel)
                    card.setFrameShadow(QFrame.Shadow.Raised)
                    card.setLineWidth(1)
                    card.setMaximumHeight(16777215)
                    card._in_single_view = False
                    card._recalc(single_view=False)  # re-applies setFixedWidth via _recalc_width
            self._rebuild_multi_grid()

    def _display_party_cb(self, index):
        """Translate stored GUIDs back to display names.
        Three possible states for the cell value:
          1. A valid GUID with a matching entry → show the ledger name
          2. A plain text name (free-typed, or legacy data with no GUID) → show as-is
          3. An orphaned GUID (Tally entry was deleted) → show as-is silently
        """
        val = index.data(Qt.ItemDataRole.DisplayRole)
        val_str = str(val or "").strip()
        if not val_str:
            return val
        # Case 1: stored GUID maps to a known name
        if val_str in self._guid_to_name:
            return self._guid_to_name[val_str]
        # Case 2 & 3: plain name or orphaned GUID — just show the raw value, no log noise
        return val

    def _set_party_cb(self, text, index):
        """Lookup alias or name and store GUID in the model.
        Matching order:
          1. Exact alias match (case-insensitive)
          2. Exact name match (case-insensitive)
          3. Normalized match — strip spaces & punctuation — so 'balajiMetal'
             and 'balaji.metal' both resolve to 'Balaji Metal Industries, Hetauda'
          4. No match → store typed text as-is (free typing allowed)
        """
        import re as _re
        def _norm(s): return _re.sub(r'[\s\.\,\-\_\/\\]', '', s.lower())

        txt_stripped = text.strip()
        txt_lower = txt_stripped.lower()
        txt_norm = _norm(txt_stripped)

        # 1 & 2: exact match
        guid = self._alias_to_guid.get(txt_lower) or self._name_to_guid.get(txt_lower)

        # 3: normalized match
        if not guid and txt_norm:
            for name_key, g in self._name_to_guid.items():
                if _norm(name_key) == txt_norm:
                    guid = g
                    break
            if not guid:
                for alias_key, g in self._alias_to_guid.items():
                    if _norm(alias_key) == txt_norm:
                        guid = g
                        break

        # We must use Qt.ItemDataRole.EditRole to actually store it in the underlying cell text
        if guid:
            index.model().setData(index, guid, Qt.ItemDataRole.EditRole)
        else:
            index.model().setData(index, txt_stripped, Qt.ItemDataRole.EditRole)


    def _build_core_section_specs(self):
        """Build column specs for the Payments core section."""
        date_delegate = ModernTableDelegate(self, cell_type="date")
        party_delegate = ModernTableDelegate(self, cell_type="autocomplete",
                                               autocomplete_items=lambda: self._party_list,
                                               enforce_match=False)  # allow free typing
        party_delegate._display_cb = self._display_party_cb
        party_delegate._set_model_cb = self._set_party_cb

        specs = {
            "Payments": [
                ("Date",      110,  date_delegate),
                ("Party Name",200,  party_delegate),
                ("To",        130,  None),
                ("From",      110,  None),
                ("Payment",   110,  None),
            ],
            "Demand Loans (DL)": [
                ("S.N",        40,  None),
                ("DL No.",    120,  None),
                ("Amount",    120,  None),
                ("Expiry Date",120, date_delegate),
                ("Day's left",  80, None),   # just a number, 80 is plenty
                ("Gap",         65, None),   # signed number e.g. "-12"
                ("Notes",      140, None),   # allow short note text
            ],
            "Today": [
                ("Date",      110,  date_delegate),
                ("Party Name",200,  party_delegate),
                ("To",        130,  None),
                ("From",      110,  None),
                ("Payment",   110,  None),
            ],
            "Account Table": [
                ("Account",      200,  None),
                ("Remain Cash",  130,  None),
                ("Bank / Cash",  150,  None),
            ],
            "Upcoming": [
                ("Date",      110,  date_delegate),
                ("Party Name",200,  party_delegate),
                ("To",        130,  None),
                ("From",      110,  None),
                ("Payment",   110,  None),
            ],
            "Limits & LC": [
                ("Type",   290,  None),   # wide enough for "Remain demand loan limit"
                ("Value",  140,  None),
            ],
        }
        return specs

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._db.ensure_database_exists(self._db_name, path)
        self._ensure_tables()
        self._seed_core_sections()
        self._reload_party_list()
        self._rebuild_section_views()

    def _reload_party_list(self):
        """Load Sundry Creditors list and mapping dicts for the Payments party autocomplete.
        Falls back to supplier_records names if no Tally ledger data is found."""
        self._guid_to_name = {}
        self._name_to_guid = {}
        self._alias_to_guid = {}
        self._party_list = []
        try:
            # Try to find the ledger DB (same pattern as cheque_list.py)
            import re
            # Build ledger db name by finding the company's tally ledger db
            from src.logic.db_manager import get_db_manager as _gdm
            db = _gdm()
            # Try to derive ledger db from the company path same way cheque_list does
            company_name = os.path.basename(os.path.normpath(self._db_name.split('_')[0] if '_' in self._db_name else self._db_name))
            # Search for any db containing row_ledger_data
            conns_to_try = [self._db_name]
            for db_name in conns_to_try:
                conn = db.get_connection(db_name)
                if not conn:
                    continue
                try:
                    cur = conn.cursor()
                    try:
                        cur.execute("SELECT GUID, Alias, Name FROM row_ledger_data")
                        for guid, alias, name in cur.fetchall():
                            guid_str = str(guid).strip() if guid else ""
                            if not guid_str: continue
                            
                            alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
                            name_str  = str(name).strip()  if name  and str(name).strip().lower()  != "none" else ""
                            
                            if name_str:
                                self._guid_to_name[guid_str] = name_str
                                self._name_to_guid[name_str.lower()] = guid_str
                            
                            if alias_str:
                                self._alias_to_guid[alias_str.lower()] = guid_str
                                
                        # Autocomplete list shows names and aliases
                        keys = set(self._guid_to_name.values()) | set(self._alias_to_guid.keys())
                        self._party_list = sorted(list(keys))
                        break
                    finally:
                        cur.close()
                except Exception as ex:
                    pass
        except Exception as e:
            _logger.error(f"[TodayPayment] Could not load party list: {e}")

        # --- Fallback / merge: also include supplier_records names ---
        # This ensures the dropdown always contains the Record tab parties
        # even when no Tally sync has been done yet.
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("SELECT name FROM supplier_records WHERE name IS NOT NULL AND LTRIM(RTRIM(name)) != '' ORDER BY sort_order, id")
                    supp_names = [row[0].strip() for row in cur.fetchall() if row[0] and row[0].strip()]
                    # Merge: add any names not already in the list
                    existing_lower = {n.lower() for n in self._party_list}
                    for sn in supp_names:
                        if sn.lower() not in existing_lower:
                            self._party_list.append(sn)
                            existing_lower.add(sn.lower())
                    self._party_list.sort()
                finally:
                    cur.close()
        except Exception as e:
            _logger.error(f"[TodayPayment] Could not merge supplier_records into party list: {e}")


    def refresh_ledger_maps(self):
        """Re-load party maps from DB after a Tally sync, then repaint all party columns.
        Safe to call at any time — triggers no DB writes.
        """
        try:
            self._reload_party_list()
            # Repaint the party column in every section card so updated names appear immediately
            for card in self._section_cards.values():
                try:
                    tbl = card.table
                    tbl.viewport().update()
                except Exception:
                    pass
            entry_count = len(self._guid_to_name)
            _logger.info(f"[TodayPayment] Ledger maps refreshed: {entry_count} entries")
        except Exception as e:
            _logger.error(f"[TodayPayment] refresh_ledger_maps error: {e}")

    def _ensure_tables(self):
        for tname, ddl in [
            ("tp_sections",
             "CREATE TABLE tp_sections (id INT IDENTITY PRIMARY KEY, "
             "sort_order INT, name NVARCHAR(200), header_color NVARCHAR(20), is_core BIT DEFAULT 0)"),
            ("tp_section_cols",
             "CREATE TABLE tp_section_cols (id INT IDENTITY PRIMARY KEY, "
             "section_id INT, col_index INT, col_name NVARCHAR(200), col_width INT)"),
            ("tp_section_data",
             "CREATE TABLE tp_section_data (section_id INT, row_idx INT, "
             "col_idx INT, cell_text NVARCHAR(MAX), "
             "PRIMARY KEY (section_id, row_idx, col_idx))"),
        ]:
            self._db.ensure_table(self._db_name, tname, ddl)

        # Migrations — check INFORMATION_SCHEMA.COLUMNS to avoid DDL exceptions & locks on startup
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cols_to_add = [
                        ("supplier_accounts", "is_red", "INT DEFAULT 0"),
                        ("tp_sections", "is_core", "BIT DEFAULT 0"),
                        ("tp_sections", "card_width", "INT NULL"),
                        ("tp_section_data", "bg_color", "NVARCHAR(20) NULL"),
                        ("tp_section_data", "fg_color", "NVARCHAR(20) NULL"),
                        ("tp_sections", "is_column_break", "BIT DEFAULT 0"),
                        ("tp_sections", "cols_locked", "BIT DEFAULT 0"),
                    ]
                    for tbl, col, col_def in cols_to_add:
                        cur.execute(
                            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? AND COLUMN_NAME=?",
                            (tbl, col)
                        )
                        if not cur.fetchone():
                            cur.execute(f"ALTER TABLE [{tbl}] ADD [{col}] {col_def}")
                    conn.commit()
                finally:
                    cur.close()
        except Exception as e:
            _logger.warning(f"[TodayPayment] schema migration check warning: {e}")

    def _seed_core_sections(self):
        """Insert the fixed core sections if they don't exist yet."""
        _CORE = [
            ("Payments",            "#059669", 0),
            ("Demand Loans (DL)",   "#2E7D32", 1),
            ("Today",               "#00695C", 2),
            ("Account Table",       "#E65100", 3),
            ("Upcoming",            "#4527A0", 4),
            ("Limits & LC",         "#B71C1C", 5),
        ]
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            for name, color, order in _CORE:
                res = cur.execute(
                    "SELECT COUNT(*) FROM tp_sections WHERE name=? AND is_core=1",
                    (name,)).fetchone()
                if res and res[0] == 0:
                    cur.execute(
                        "INSERT INTO tp_sections(sort_order,name,header_color,is_core)"
                        " VALUES(?,?,?,1)",
                        (order, name, color))
            conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.error(f"[TodayPayment] Seed core sections error: {e}")
        finally:
            cur.close()

    def _rebuild_section_views(self):
        """Re-fetch tables from DB and rebuild both views."""
        # Clear old cards
        for card in self._section_cards.values():
            try:
                card.setParent(None)
                card.deleteLater()
            except RuntimeError:
                pass
        self._section_cards.clear()

        # Clear sidebar
        self._sidebar_list.blockSignals(True)
        self._sidebar_list.clear()
        self._sidebar_list.blockSignals(False)

        # Clear multi grid
        self._clear_multi_grid()

        if not self._db_name:
            return

        rows = self._db.execute_query(
            self._db_name,
            "SELECT id, name, header_color, is_core, card_width, ISNULL(is_column_break, 0), ISNULL(cols_locked, 0) FROM tp_sections ORDER BY sort_order, id"
        ) or []

        core_specs = self._build_core_section_specs()

        for sid, name, color, is_core, c_width, is_column_break, cols_locked in rows:
            col_specs = core_specs.get(name) if is_core else None
            card = _SectionCardV2(
                sid, name or "Table", color or "",
                self._db, self._db_name,
                col_specs=col_specs,
                parent=self._multi_container,
                card_width=c_width or 450
            )
            card._today_tab_ref = self
            card.is_column_break = bool(is_column_break)   # direct reference, avoids broken parent-walk
            card.set_edit_mode(self._can_edit)
            if cols_locked:
                card._set_cols_locked(True, save_to_db=False)
            self._section_cards[sid] = card
            self._migrate_party_names_to_guid(card)

            # Sidebar entry
            item = QListWidgetItem(f"  {name} →" if is_column_break else f"  {name}")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            if is_core:
                item.setToolTip("Core table — cannot be deleted")
            self._sidebar_list.addItem(item)

        # Populate the active view
        if self._current_view == 1:
            self._rebuild_multi_grid()

        # Select first in sidebar (must come AFTER grid is built to avoid gap bug)
        if self._sidebar_list.count() > 0:
            self._sidebar_list.setCurrentRow(0)
            
        QTimer.singleShot(0, self._update_all_calculations)

    def _update_all_calculations(self):
        if self._updating_calcs: return
        self._updating_calcs = True
        
        # 0. Prevent QAbstractItemView::commitData crashes:
        # If ANY table has an active editor open, skip this run entirely.
        # The QTimer.singleShot(0,...) call-path ensures calculations re-run
        # after the editor commits naturally in the next event loop cycle.
        for card in self._section_cards.values():
            if card.table.state() == QAbstractItemView.State.EditingState:
                self._updating_calcs = False
                return  # editor open — will retry via QTimer after commit

        try:
            # --- Step 0: Re-evaluate ALL formula cells first ---
            # This MUST happen before any column-sum or 'Left money' calculation
            # so that formula cell values (e.g. Payment =IF(...)) are current.
            for _ in range(2):
                for card in self._section_cards.values():
                    card._recalc_formulas()

            dl_card = None
            account_card = None
            today_card = None
            limits_card = None
            
            for card in self._section_cards.values():
                if card.section_name == "Demand Loans (DL)": dl_card = card
                elif card.section_name == "Account Table": account_card = card
                elif card.section_name == "Today": today_card = card
                elif card.section_name == "Limits & LC": limits_card = card
            
            sum_dl = 0.0
            sum_remain_cash = 0.0
            sum_today_payment = 0.0
            
            # 1. Demand Loans
            if dl_card:
                dl_card.table.blockSignals(True)
                col_amt = -1
                col_exp = -1
                col_days = -1
                col_gap = -1
                for c in range(dl_card.table.columnCount()):
                    h = dl_card.table.horizontalHeaderItem(c)
                    if not h: continue
                    ht = h.text().strip().lower()
                    if ht == "amount": col_amt = c
                    elif ht == "expiry date": col_exp = c
                    elif ht == "day's left": col_days = c
                    elif ht == "gap": col_gap = c
                
                prev_days_left = None
                for r in range(dl_card.table.rowCount()):
                    # Sum Amount
                    if col_amt >= 0:
                        it = dl_card.table.item(r, col_amt)
                        if it and it.text():
                            raw = it.data(RAW_NUMERIC_ROLE)
                            if raw is not None and isinstance(raw, (int, float)):
                                sum_dl += float(raw)
                            else:
                                try: sum_dl += float(it.text().replace(",", ""))
                                except (ValueError, TypeError): pass
                    
                    # Calc Days Left & Gap
                    days_left = None
                    if col_exp >= 0 and col_days >= 0:
                        exp_it = dl_card.table.item(r, col_exp)
                        if exp_it and exp_it.text().strip():
                            from PyQt6.QtCore import QDate
                            d = QDate.fromString(exp_it.text().strip(), "yyyy-MM-dd")
                            if d.isValid():
                                days_left = max(0, QDate.currentDate().daysTo(d))
                                days_it = dl_card.table.item(r, col_days)
                                if not days_it:
                                    from PyQt6.QtWidgets import QTableWidgetItem
                                    days_it = QTableWidgetItem()
                                    dl_card.table.setItem(r, col_days, days_it)
                                days_it.setText(str(days_left))
                        else:
                            days_it = dl_card.table.item(r, col_days)
                            if days_it: days_it.setText("")
                            
                    if col_gap >= 0:
                        gap_it = dl_card.table.item(r, col_gap)
                        if not gap_it:
                            from PyQt6.QtWidgets import QTableWidgetItem
                            gap_it = QTableWidgetItem()
                            dl_card.table.setItem(r, col_gap, gap_it)
                        if days_left is not None and prev_days_left is not None:
                            gap_it.setText(str(days_left - prev_days_left))
                        else:
                            gap_it.setText("")
                    
                    if days_left is not None:
                        prev_days_left = days_left
                dl_card.table.blockSignals(False)

            # DL Amount total footer — shown aligned under the "Amount" column
            if dl_card:
                dl_card.set_col_footer(
                    {"Amount": sum_dl},
                    row_label="Total Amount"
                )
                
            # 2. Account Table
            if account_card:
                col_remain = -1
                for c in range(account_card.table.columnCount()):
                    h = account_card.table.horizontalHeaderItem(c)
                    if h and h.text().strip().lower() == "remain cash":
                        col_remain = c
                        break
                if col_remain >= 0:
                    for r in range(account_card.table.rowCount()):
                        it = account_card.table.item(r, col_remain)
                        if it and it.text():
                            raw = it.data(RAW_NUMERIC_ROLE)
                            if raw is not None and isinstance(raw, (int, float)):
                                sum_remain_cash += float(raw)
                            else:
                                try: sum_remain_cash += float(it.text().replace(",", ""))
                                except (ValueError, TypeError): pass
                
                account_card.set_col_footer(
                    {"Remain Cash": sum_remain_cash},
                    row_label="Remain Cash Sum"
                )
                
            # 3. Today Table
            if today_card:
                col_pay = -1
                for c in range(today_card.table.columnCount()):
                    h = today_card.table.horizontalHeaderItem(c)
                    if h and h.text().strip().lower() == "payment":
                        col_pay = c
                        break
                if col_pay >= 0:
                    for r in range(today_card.table.rowCount()):
                        it = today_card.table.item(r, col_pay)
                        if it and it.text():
                            raw = it.data(RAW_NUMERIC_ROLE)
                            if raw is not None and isinstance(raw, (int, float)):
                                sum_today_payment += float(raw)
                            else:
                                try: sum_today_payment += float(it.text().replace(",", ""))
                                except (ValueError, TypeError): pass
                
                left_money = sum_remain_cash - sum_today_payment
                today_card.set_col_footer(
                    {"Payment": left_money},
                    row_label="Left Money"
                )
                
            # 4. Limits & LC
            if limits_card:
                limits_card.table.blockSignals(True)
                used_lc    = 0.0
                remain_dl_row = -1
                remain_lc_row = -1

                # Fallback limits (used when the user has not yet added
                # "DL Limit" / "LC Limit" rows to the Limits & LC card).
                _DEFAULT_DL_LIMIT = 11_200_000.0
                _DEFAULT_LC_LIMIT =  2_500_000.0

                # Read user-defined limits from the card itself.
                # The user can add rows like:
                #   Type column  →  "DL Limit"    Value column → e.g. 15000000
                #   Type column  →  "LC Limit"    Value column → e.g. 3000000
                # If absent, the defaults above are used.
                dl_limit_cap = _DEFAULT_DL_LIMIT
                lc_limit_base = _DEFAULT_LC_LIMIT

                for r in range(limits_card.table.rowCount()):
                    it_type = limits_card.table.item(r, 0)
                    if it_type and it_type.text():
                        t = it_type.text().strip().lower()
                        it_val = limits_card.table.item(r, 1)
                        raw_data = it_val.data(RAW_NUMERIC_ROLE) if it_val else None
                        if raw_data is not None and isinstance(raw_data, (int, float)):
                            fv = float(raw_data)
                        else:
                            try: fv = float(it_val.text().replace(",", "").strip()) if it_val else 0.0
                            except (ValueError, TypeError): fv = 0.0
                        if "used lc" in t:
                            used_lc = fv
                        elif t in ("dl limit", "demand loan limit"):
                            dl_limit_cap = fv
                        elif t in ("lc limit", "lc base limit"):
                            lc_limit_base = fv
                        elif "remain demand loan limit" in t:
                            remain_dl_row = r
                        elif "remain lc limit" in t:
                            remain_lc_row = r

                remain_dl_limit = dl_limit_cap - sum_dl
                remain_lc_limit = lc_limit_base + remain_dl_limit - used_lc
                
                from PyQt6.QtWidgets import QTableWidgetItem
                if remain_dl_row == -1:
                    r = limits_card.table.rowCount()
                    limits_card.table.insertRow(r)
                    limits_card.table.setItem(r, 0, QTableWidgetItem("Remain demand loan limit"))
                    limits_card.table.setItem(r, 1, QTableWidgetItem(""))
                    remain_dl_row = r
                it = limits_card.table.item(remain_dl_row, 1)
                if not it:
                    it = QTableWidgetItem()
                    limits_card.table.setItem(remain_dl_row, 1, it)
                it.setText(f"{int(round(remain_dl_limit)):,}")
                it.setData(RAW_NUMERIC_ROLE, remain_dl_limit)
                
                if remain_lc_row == -1:
                    r = limits_card.table.rowCount()
                    limits_card.table.insertRow(r)
                    limits_card.table.setItem(r, 0, QTableWidgetItem("Remain lc limit"))
                    limits_card.table.setItem(r, 1, QTableWidgetItem(""))
                    remain_lc_row = r
                it = limits_card.table.item(remain_lc_row, 1)
                if not it:
                    it = QTableWidgetItem()
                    limits_card.table.setItem(remain_lc_row, 1, it)
                it.setText(f"{int(round(remain_lc_limit)):,}")
                it.setData(RAW_NUMERIC_ROLE, remain_lc_limit)
                
                # Auto-seed Used LC row if missing
                used_lc_row = -1
                for r in range(limits_card.table.rowCount()):
                    it_type = limits_card.table.item(r, 0)
                    if it_type and "used lc" in it_type.text().strip().lower():
                        used_lc_row = r
                        break
                if used_lc_row == -1:
                    r = limits_card.table.rowCount()
                    limits_card.table.insertRow(r)
                    from PyQt6.QtWidgets import QTableWidgetItem
                    limits_card.table.setItem(r, 0, QTableWidgetItem("Used LC"))
                    limits_card.table.setItem(r, 1, QTableWidgetItem(""))

                # Make formula rows non-editable (Type cell locked, Value cell locked)
                _ro_flag = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                for _formula_row in (remain_dl_row, remain_lc_row):
                    for _c in (0, 1):
                        _it = limits_card.table.item(_formula_row, _c)
                        if _it:
                            _it.setFlags(_ro_flag)

                # Expand formula columns to fit new text — never shrink user-set widths
                for _c in (0, 1):
                    limits_card._expand_column_to_contents(_c)
                limits_card.table.blockSignals(False)
                
        finally:
            self._updating_calcs = False

    def _migrate_party_names_to_guid(self, card):
        """Converts raw name strings in Party Name columns to GUIDs and resaves."""
        if not card._fixed_cols or not card._col_specs:
            return
        
        needs_save = False
        card.table.blockSignals(True)
        for c, spec in enumerate(card._col_specs):
            # Check if this column uses the party delegate
            if len(spec) > 2 and isinstance(spec[2], UniversalCellDelegate) and spec[2]._cell_type == "autocomplete":
                # Assuming this is the party autocomplete since it's the only one we define
                for r in range(card.table.rowCount()):
                    it = card.table.item(r, c)
                    if it and it.text():
                        txt = it.text().strip()
                        # If it's not a known GUID, it must be legacy text
                        if txt not in self._guid_to_name:
                            txt_lower = txt.lower()
                            guid = self._name_to_guid.get(txt_lower) or self._alias_to_guid.get(txt_lower)
                            if guid:
                                it.setText(guid)
                                needs_save = True
        card.table.blockSignals(False)
        if needs_save:
            card._save_data()

    def _on_sidebar_select(self, row):
        """Show the selected card in single-table view. No-op in multi view."""
        if self._current_view != 0:
            return  # Only affects single view — prevents grid gap bug

        # Remove any existing card from single pane; restore multi-view sizing
        while self._single_card_holder.count() > 0:
            item = self._single_card_holder.takeAt(0)
            w = item.widget()
            if w:
                # Restore frame shape and original fixed width before re-parking
                w.setFrameShape(QFrame.Shape.StyledPanel)
                w.setFrameShadow(QFrame.Shadow.Raised)
                w.setLineWidth(1)
                w.setMinimumWidth(300)
                # Undo the fixed height from _recalc() so multi-view can lay it out naturally
                w.setMaximumHeight(16777215)
                # Clear single-view flag BEFORE _recalc so _recalc_width runs normally
                w._in_single_view = False
                w._recalc(single_view=False)  # reapply compact height for multi-view grid
                w.setParent(self._multi_container)  # re-park under multi
                # Do NOT call hide() here — Qt's explicit-hide flag persists through
                # addWidget() and would cause cards to stay invisible in multi-view.

        if row < 0 or row >= self._sidebar_list.count():
            self._single_placeholder.show()
            return

        list_item = self._sidebar_list.item(row)
        if not list_item:
            return
        sid = list_item.data(Qt.ItemDataRole.UserRole)
        card = self._section_cards.get(sid)
        if not card:
            return

        self._single_placeholder.hide()
        # Re-parent card to single pane and make it fill the full width.
        # We must clear the fixed width that was set for the multi-view card layout,
        # and suppress the QFrame's default StyledPanel border which adds visual gaps.
        card.setParent(self._single_pane)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setFrameShadow(QFrame.Shadow.Plain)
        card.setLineWidth(0)
        card.setMinimumWidth(0)  # Qt's QWIDGETSIZE_MAX — removes fixed width
        card.setMaximumWidth(16777215)
        # Ensure height is tight: remove any leftover fixed height from multi-view,
        # then let _recalc() compute the correct compact height.
        card.setMaximumHeight(16777215)
        card._in_single_view = True
        card._recalc(single_view=True)  # use larger height cap in full-width single pane
        self._single_card_holder.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)

    def _show_sidebar_menu(self, pos):
        item = self._sidebar_list.itemAt(pos)
        if not item: return
        sid = item.data(Qt.ItemDataRole.UserRole)
        card = self._section_cards.get(sid)
        if not card: return
        
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        is_break = getattr(card, 'is_column_break', False)
        action = menu.addAction("Remove Column Break" if is_break else "Start New Column Here")
        
        res = menu.exec(self._sidebar_list.viewport().mapToGlobal(pos))
        if res == action:
            new_val = not is_break
            card.is_column_break = new_val
            try:
                self._db.execute_query(self._db_name, "UPDATE tp_sections SET is_column_break=? WHERE id=?", (1 if new_val else 0, sid), fetch=False)
            except Exception as e:
                _logger.error(f"[TodayPayment] Error saving column break: {e}")
                
            txt = item.text()
            if new_val and not txt.endswith(" →"):
                item.setText(txt + " →")
            elif not new_val and txt.endswith(" →"):
                item.setText(txt[:-2])
                
            if self._current_view == 1:
                self._rebuild_multi_grid()

    def _rename_section_from_sidebar(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        res = self._db.execute_query(
            self._db_name, "SELECT is_core, name FROM tp_sections WHERE id=?", (sid,))
        if not res:
            return
        is_core, current_name = res[0]
        new, ok = _styled_get_text(self, "Rename Table", "New name:", text=current_name)
        if ok and new.strip():
            item.setText(f"  {new.strip()}")
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE tp_sections SET name=? WHERE id=?", (new.strip(), sid))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                finally:
                    cur.close()
            card = self._section_cards.get(sid)
            if card:
                card.title_lbl.setText(new.strip())

    def _on_sidebar_reordered(self, *args):
        """Save the new sort_order after sidebar drag-and-drop reorder."""
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            for i in range(self._sidebar_list.count()):
                item = self._sidebar_list.item(i)
                sid = item.data(Qt.ItemDataRole.UserRole)
                cur.execute("UPDATE tp_sections SET sort_order=? WHERE id=?", (i, sid))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            cur.close()
        # Only refresh the grid layout — don't rebuild (that destroys and recreates cards)
        if self._current_view == 1:
            self._rebuild_multi_grid()
        elif self._current_view == 0:
            # Re-select current item so single-view refreshes
            self._on_sidebar_select(self._sidebar_list.currentRow())

    def _add_section(self):
        if not self._can_edit or not self._db_name:
            return
        name, ok = _styled_get_text(self, "Add Table", "Table name:")
        if not ok or not name.strip():
            return
        res = self._db.execute_query(
            self._db_name, "SELECT ISNULL(MAX(sort_order), 0) FROM tp_sections")
        max_ord = (res[0][0] if res else 0) + 1
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tp_sections(sort_order,name,header_color,is_core) VALUES(?,?,?,0)",
                (max_ord, name.strip(), "#059669"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return
        finally:
            cur.close()
        self._rebuild_section_views()
        # Auto-add a first column so the new card is immediately usable
        for card in self._section_cards.values():
            if card.section_name == name.strip() and card.table.columnCount() == 0:
                card._add_column()
                break

    def _clear_multi_grid(self):
        """Remove all card widgets from the multi view layout."""
        # Remove every row HBoxLayout and its cards
        for row_hbox in self._multi_row_layouts:
            while row_hbox.count() > 0:
                item = row_hbox.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
        self._multi_row_layouts.clear()

        # Strip all items from the VBox except re-add the bottom stretch at the end
        while self._multi_layout.count() > 0:
            item = self._multi_layout.takeAt(0)
            if item.layout():
                # delete lingering child layouts
                pass  # already cleared above

    def _rebuild_multi_grid(self):
        """Lay cards out in columns.
        By default, deals cards into 3 columns (left-to-right, top-to-bottom).
        If any section has is_column_break, it switches to manual layout.
        """
        self._clear_multi_grid()

        ordered_cards = []
        for i in range(self._sidebar_list.count()):
            sid = self._sidebar_list.item(i).data(Qt.ItemDataRole.UserRole)
            card = self._section_cards.get(sid)
            if card:
                ordered_cards.append(card)

        # Do we have manual breaks anywhere except maybe the very first card?
        # A break on the first card just means "start col 1", so we consider it manual if there are ANY breaks.
        use_manual = any(getattr(c, 'is_column_break', False) for c in ordered_cards)

        row_widget = QWidget()
        row_widget.setStyleSheet("background: transparent;")
        main_hbox = QHBoxLayout(row_widget)
        main_hbox.setContentsMargins(0, 0, 0, 0)
        main_hbox.setSpacing(8)

        if use_manual:
            cols = []
            for card in ordered_cards:
                if getattr(card, 'is_column_break', False) or not cols:
                    cols.append(QVBoxLayout())
                card.setParent(row_widget)
                cols[-1].addWidget(card)
                card.show()
        else:
            cols = [QVBoxLayout(), QVBoxLayout(), QVBoxLayout()]
            for i, card in enumerate(ordered_cards):
                card.setParent(row_widget)
                cols[i % 3].addWidget(card)
                card.show()

        for c in cols:
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(8)
            c.setAlignment(Qt.AlignmentFlag.AlignTop)
            main_hbox.addLayout(c)

        main_hbox.addStretch(1)

        self._multi_row_layouts.append(main_hbox)
        self._multi_layout.addWidget(row_widget, 0, Qt.AlignmentFlag.AlignTop)
        self._multi_layout.addStretch(1)

    def _swap_table_positions(self, sid_a: int, sid_b: int):
        """Swap two tables' positions in the sidebar order, persist, and redraw grid."""
        if not self._db_name:
            return

        # Find positions in sidebar
        pos_a = pos_b = -1
        for i in range(self._sidebar_list.count()):
            sid = self._sidebar_list.item(i).data(Qt.ItemDataRole.UserRole)
            if sid == sid_a:
                pos_a = i
            elif sid == sid_b:
                pos_b = i

        if pos_a < 0 or pos_b < 0 or pos_a == pos_b:
            return

        # Correct swap of two QListWidgetItems
        # Strategy: read all SIDs, swap the two, repopulate
        self._sidebar_list.blockSignals(True)
        sids_in_order = []
        texts_in_order = []
        tooltips_in_order = []
        for i in range(self._sidebar_list.count()):
            it = self._sidebar_list.item(i)
            sids_in_order.append(it.data(Qt.ItemDataRole.UserRole))
            texts_in_order.append(it.text())
            tooltips_in_order.append(it.toolTip())

        # Swap at the two positions
        sids_in_order[pos_a], sids_in_order[pos_b] = sids_in_order[pos_b], sids_in_order[pos_a]
        texts_in_order[pos_a], texts_in_order[pos_b] = texts_in_order[pos_b], texts_in_order[pos_a]
        tooltips_in_order[pos_a], tooltips_in_order[pos_b] = tooltips_in_order[pos_b], tooltips_in_order[pos_a]

        # Repopulate sidebar
        self._sidebar_list.clear()
        for sid, txt, tip in zip(sids_in_order, texts_in_order, tooltips_in_order):
            new_item = QListWidgetItem(txt)
            new_item.setData(Qt.ItemDataRole.UserRole, sid)
            new_item.setToolTip(tip)
            self._sidebar_list.addItem(new_item)
        self._sidebar_list.blockSignals(False)

        # Persist new sort_order to DB
        conn = self._db.get_connection(self._db_name)
        if conn:
            cur = conn.cursor()
            try:
                for i, sid in enumerate(sids_in_order):
                    cur.execute("UPDATE tp_sections SET sort_order=? WHERE id=?", (i, sid))
                conn.commit()
            except Exception as e:
                conn.rollback()
            finally:
                cur.close()

        # Redraw the grid with new order (no full rebuild needed)
        self._rebuild_multi_grid()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._btn_add.setEnabled(can_edit)
        for card in self._section_cards.values():
            card.set_edit_mode(can_edit)


