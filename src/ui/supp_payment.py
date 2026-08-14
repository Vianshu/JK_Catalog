# =============================================================================
# supp_payment.py  –  Supplier Payment Module (Redesigned)
# =============================================================================
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QTabWidget, QInputDialog,
    QMenu, QMessageBox, QHeaderView, QAbstractItemView,
    QLabel, QScrollArea, QFrame, QSizePolicy, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter,
    QFormLayout, QCompleter, QStyledItemDelegate, QDateEdit,
    QApplication, QToolButton,
)
from PyQt6.QtCore import (
    Qt, QTimer, QDate, QEvent, QSortFilterProxyModel, QMimeData,
    QSize,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPixmap, QPainter, QStandardItemModel,
    QStandardItem, QKeySequence, QShortcut, QCursor,
)
from src.logic.db_manager import get_db_manager, build_logical_name

# ---------------------------------------------------------------------------
# Shared font helpers
# ---------------------------------------------------------------------------
def _bold_font(size=10):
    f = QFont("Segoe UI", size)
    f.setWeight(QFont.Weight.Bold)
    return f

def _norm_font(size=10):
    return QFont("Segoe UI", size)

# ---------------------------------------------------------------------------
# Common stylesheet constants
# ---------------------------------------------------------------------------
_TABLE_STYLE = """
QTableWidget {
    gridline-color: #e2e8f0;
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-family: 'Segoe UI';
    font-size: 10pt;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected {
    background-color: #dbeafe;
    color: #1e40af;
}
QHeaderView::section:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1e3a5f,stop:1 #162d4a);
    color: #ffffff;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #2d5a8e;
    font-weight: bold;
    font-size: 10pt;
}
QHeaderView::section:horizontal:first { border-radius: 6px 0 0 0; }
QHeaderView::section:horizontal:last  { border-radius: 0 6px 0 0; border-right: none; }
"""

_SECTION_HEADER_STYLE = (
    "background: {color}; color: white; padding: 8px 14px; "
    "border-radius: 6px 6px 0 0; font-weight: bold; font-size: 11pt;"
)

_BTN_PRIMARY = """
QPushButton {
    background: #1d4ed8; color: white; border: none;
    border-radius: 5px; padding: 5px 14px; font-weight: bold; font-size: 10pt;
}
QPushButton:hover { background: #1e40af; }
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

# ===========================================================================
# Tally-like completer  (borrowed from cheque_list.py — exact same logic)
# ===========================================================================
class _TallySortProxyModel(QSortFilterProxyModel):
    """Keeps starts-with matches at the top; contains matches below."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix = ""

    def set_prefix(self, prefix: str):
        self._prefix = prefix.lower()

    def lessThan(self, left, right):
        lv = left.data(Qt.ItemDataRole.DisplayRole) or ""
        rv = right.data(Qt.ItemDataRole.DisplayRole) or ""
        p = self._prefix
        l_starts = lv.lower().startswith(p)
        r_starts = rv.lower().startswith(p)
        if l_starts != r_starts:
            return l_starts
        return lv.lower() < rv.lower()


class _TallyCompleter(QCompleter):
    """QCompleter that shows starts-with matches first, then contains."""
    def __init__(self, data_list, parent=None):
        self._data_list = [str(x) for x in data_list]
        self._src_model = QStandardItemModel()
        for item in self._data_list:
            self._src_model.appendRow(QStandardItem(item))
        self._proxy = _TallySortProxyModel()
        self._proxy.setSourceModel(self._src_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)
        super().__init__(self._proxy, parent)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        if parent:
            parent.textEdited.connect(self._on_text_edited)

    def _on_text_edited(self, text: str):
        p = text.lower()
        self._proxy.set_prefix(p)
        self._proxy.setFilterFixedString(text)
        self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self.complete()

    def update_data(self, data_list):
        self._data_list = [str(x) for x in data_list]
        self._src_model.clear()
        for item in self._data_list:
            self._src_model.appendRow(QStandardItem(item))


def _enforce_match(editor: QLineEdit, text: str, data_list: list):
    """Reject last typed char if current text has no match at all."""
    if not text:
        return
    tl = text.lower()
    for item in data_list:
        if tl in str(item).lower():
            return
    editor.blockSignals(True)
    editor.setText(text[:-1])
    editor.blockSignals(False)
    completer = editor.completer()
    if completer and hasattr(completer, '_on_text_edited'):
        completer._on_text_edited(text[:-1])


# ===========================================================================
# Delegate: Date-Only column
# ===========================================================================
class _DateDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = QDateEdit(parent)
        ed.setDisplayFormat("dd/MM/yyyy")
        ed.setCalendarPopup(True)
        ed.setDate(QDate.currentDate())
        ed.setFrame(False)
        return ed

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.DisplayRole) or ""
        d = QDate.fromString(val, "dd/MM/yyyy")
        if d.isValid():
            editor.setDate(d)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.date().toString("dd/MM/yyyy"), Qt.ItemDataRole.EditRole)


# ===========================================================================
# Delegate: Autocomplete column (Sundry Debtors)
# ===========================================================================
class _AutocompleteDelegate(QStyledItemDelegate):
    def __init__(self, data_getter, parent=None):
        """data_getter: callable that returns the current list of strings."""
        super().__init__(parent)
        self._data_getter = data_getter

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        data_list = self._data_getter()
        if data_list:
            completer = _TallyCompleter(data_list, editor)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setMaxVisibleItems(12)
            editor.setCompleter(completer)
            completer.popup().setMinimumWidth(300)
            editor.textEdited.connect(
                lambda text, e=editor, dl=data_list: _enforce_match(e, text, dl)
            )
        return editor

    def setModelData(self, editor, model, index):
        val = editor.text().strip()
        model.setData(index, val, Qt.ItemDataRole.EditRole)


# ===========================================================================
# Simple DB-backed QTableWidget
# ===========================================================================
class _DbTable(QTableWidget):
    """A clean QTableWidget backed by a single SQL table.
    Schema: (row_idx INT, col_idx INT, cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))
    """
    def __init__(self, table_name: str, headers: list, widths: list,
                 parent=None, row_count=40):
        super().__init__(row_count, len(headers), parent)
        self._table_name = table_name
        self._db = get_db_manager()
        self._db_name = ""
        self._headers = headers
        self._widths = widths
        self._loading = False
        self._can_edit = True

        self.setFont(_norm_font())
        self.setAlternatingRowColors(True)
        self.setStyleSheet(_TABLE_STYLE)
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)

        self.itemChanged.connect(self._on_change)

    def set_db_name(self, db_name: str):
        self._db_name = db_name
        self._ensure_table()
        self.load_from_db()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )

    def _ensure_table(self):
        if not self._db_name:
            return
        ddl = (f"CREATE TABLE {self._table_name} "
               f"(row_idx INT NOT NULL, col_idx INT NOT NULL, "
               f"cell_text NVARCHAR(MAX), PRIMARY KEY (row_idx, col_idx))")
        self._db.ensure_table(self._db_name, self._table_name, ddl)

    def _on_change(self, _):
        if self._loading:
            return
        QTimer.singleShot(400, self.save_to_db)

    def save_to_db(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(f"DELETE FROM {self._table_name}")
            for r in range(self.rowCount()):
                for c in range(self.columnCount()):
                    it = self.item(r, c)
                    if it and it.text():
                        cur.execute(
                            f"INSERT INTO {self._table_name} (row_idx, col_idx, cell_text) VALUES (?,?,?)",
                            (r, c, it.text()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] _DbTable.save_to_db({self._table_name}):", e)

    def load_from_db(self):
        if not self._db_name:
            return
        self._loading = True
        rows = self._db.execute_query(
            self._db_name,
            f"SELECT row_idx, col_idx, cell_text FROM {self._table_name} ORDER BY row_idx, col_idx"
        ) or []
        self.blockSignals(True)
        self.clearContents()
        for r, c, txt in rows:
            while self.rowCount() <= int(r):
                self.insertRow(self.rowCount())
            it = QTableWidgetItem(txt or "")
            self.setItem(int(r), int(c), it)
        self.blockSignals(False)
        self._loading = False

    def add_row(self):
        if not self._can_edit:
            return
        r = self.rowCount()
        self.insertRow(r)
        for c in range(self.columnCount()):
            self.setItem(r, c, QTableWidgetItem(""))
        self.scrollToBottom()

    def keyPressEvent(self, event):
        if self._can_edit and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for it in self.selectedItems():
                it.setText("")
        else:
            super().keyPressEvent(event)


# ===========================================================================
# Section card widget  used in Today Payment
# ===========================================================================
class _SectionCard(QWidget):
    """Header bar + QTableWidget for one section in the Today Payment tab."""

    def __init__(self, section_id, name, color, db_manager, db_name,
                 col_specs=None, parent=None):
        """
        col_specs: list of (header_name, width, delegate_or_None)
        If None, the table loads columns dynamically from DB.
        """
        super().__init__(parent)
        self.section_id = section_id
        self._db = db_manager
        self._db_name = db_name
        self._can_edit = True
        self._saving = False
        self._fixed_cols = col_specs is not None
        self._col_specs = col_specs or []
        self._today_tab_ref = None   # set by TodayPaymentTab after construction

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Header bar ----
        self._hdr = QWidget()
        self._hdr.setMinimumHeight(36)
        self._hdr.setStyleSheet(f"background:{color}; border-radius:6px 6px 0 0;")
        hlay = QHBoxLayout(self._hdr)
        hlay.setContentsMargins(12, 4, 8, 4)
        hlay.setSpacing(6)

        self.title_lbl = QLabel(name)
        self.title_lbl.setFont(_bold_font(11))
        self.title_lbl.setStyleSheet("color:white; border:none; background:transparent;")
        hlay.addWidget(self.title_lbl)
        hlay.addStretch()

        _bs = (
            "QPushButton{background:rgba(255,255,255,.20);color:white;"
            "border:1px solid rgba(255,255,255,.35);border-radius:4px;"
            "padding:2px 10px;font-size:10pt;}"
            "QPushButton:hover{background:rgba(255,255,255,.35);}"
        )

        if not self._fixed_cols:
            self._btn_col = QPushButton("+ Col")
            self._btn_col.setFixedHeight(24)
            self._btn_col.setStyleSheet(_bs)
            self._btn_col.clicked.connect(self._add_column)
            hlay.addWidget(self._btn_col)

        self._btn_row = QPushButton("+ Row")
        self._btn_row.setFixedHeight(24)
        self._btn_row.setStyleSheet(_bs)
        self._btn_row.clicked.connect(self._add_row)
        hlay.addWidget(self._btn_row)

        if not self._fixed_cols:
            self._btn_gear = QPushButton("⚙")
            self._btn_gear.setFixedSize(28, 24)
            self._btn_gear.setStyleSheet(_bs)
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

        # ---- Table ----
        n_cols = len(self._col_specs) if self._fixed_cols else 0
        self.table = QTableWidget(0, max(n_cols, 1))
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.table.setMinimumHeight(50)

        if self._fixed_cols and self._col_specs:
            headers = [s[0] for s in self._col_specs]
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            for i, spec in enumerate(self._col_specs):
                self.table.setColumnWidth(i, spec[1])
                if len(spec) > 2 and spec[2] is not None:
                    self.table.setItemDelegateForColumn(i, spec[2])

        self.table.horizontalHeader().sectionDoubleClicked.connect(self._rename_col)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: QTimer.singleShot(500, self._save_cols))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_ctx)
        self.table.itemChanged.connect(self._on_change)
        outer.addWidget(self.table)

        self._load()

    # ---- drag-and-drop header: initiates position swap in multi view ----
    def eventFilter(self, source, event):
        if source is self._hdr:
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
                self.setStyleSheet("border: 2px dashed #1d4ed8;")
            except ValueError:
                event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

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
        self.table.blockSignals(True)
        if not self._fixed_cols:
            cols = self._db.execute_query(
                self._db_name,
                "SELECT col_index, col_name, col_width FROM tp_section_cols "
                "WHERE section_id=? ORDER BY col_index", (self.section_id,)) or []
            if cols:
                self.table.setColumnCount(len(cols))
                for idx, (ci, cname, cw) in enumerate(cols):
                    self.table.setHorizontalHeaderItem(idx, QTableWidgetItem(cname or ""))
                    self.table.setColumnWidth(idx, cw or 120)

        data = self._db.execute_query(
            self._db_name,
            "SELECT row_idx, col_idx, cell_text FROM tp_section_data "
            "WHERE section_id=? ORDER BY row_idx, col_idx", (self.section_id,)) or []
        if data:
            max_r = max(r[0] for r in data)
            self.table.setRowCount(max_r + 1)
            for ri, ci, txt in data:
                if ci < self.table.columnCount():
                    self.table.setItem(int(ri), int(ci), QTableWidgetItem(txt or ""))
        self.table.blockSignals(False)
        self._recalc()

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
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    if it and it.text():
                        cur.execute(
                            "INSERT INTO tp_section_data(section_id,row_idx,col_idx,cell_text)"
                            " VALUES(?,?,?,?)",
                            (self.section_id, r, c, it.text()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[ERROR] _SectionCard._save_data:", e)
        finally:
            self._saving = False

    def _save_cols(self):
        if not self._db_name or self._fixed_cols:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM tp_section_cols WHERE section_id=?", (self.section_id,))
            for c in range(self.table.columnCount()):
                h = self.table.horizontalHeaderItem(c)
                cur.execute(
                    "INSERT INTO tp_section_cols(section_id,col_index,col_name,col_width)"
                    " VALUES(?,?,?,?)",
                    (self.section_id, c, h.text() if h else "", self.table.columnWidth(c)))
            conn.commit()
        except Exception as e:
            conn.rollback()

    def _update_db(self, field, value):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE tp_sections SET {field}=? WHERE id=?", (value, self.section_id))
            conn.commit()
        except Exception as e:
            conn.rollback()

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

    # ------------------------------------------------------------ Actions --
    def _on_change(self, _):
        QTimer.singleShot(300, self._save_data)

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
            QMessageBox.information(self, "No Columns", "Add at least one column first.")
            return
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self._save_data()
        self._recalc()

    def _rename_col(self, col):
        if not self._can_edit or self._fixed_cols:
            return
        h = self.table.horizontalHeaderItem(col)
        old = h.text() if h else ""
        new, ok = QInputDialog.getText(self, "Rename Column", "Column name:", text=old)
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
        a_del = menu.addAction("🗑 Delete Row")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == a_del and r >= 0:
            self.table.removeRow(r)
            self._save_data()
            self._recalc()

    def _show_gear(self):
        if self._fixed_cols:
            return
        menu = QMenu(self)
        a_ren = menu.addAction("✏ Rename Table")
        a_col = menu.addAction("🎨 Change Header Color")
        menu.addSeparator()
        a_del = menu.addAction("🗑 Delete Table")
        act = menu.exec(self._btn_gear.mapToGlobal(self._btn_gear.rect().bottomLeft()))
        if act == a_ren:
            new, ok = QInputDialog.getText(self, "Rename Table", "Name:",
                                           text=self.title_lbl.text())
            if ok and new.strip():
                self.title_lbl.setText(new.strip())
                self._update_db("name", new.strip())
        elif act == a_del:
            if QMessageBox.question(
                    self, "Delete Table",
                    f"Delete '{self.title_lbl.text()}'?\nAll data will be lost.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self._delete_from_db()
                tp = self._today_tab_ref
                if tp:
                    tp._rebuild_section_views()

    def _recalc(self):
        """Set table height based on its content so cards don't stretch."""
        cols = self.table.columnCount()
        hh = self.table.horizontalHeader().sizeHint().height() if cols else 0
        rh = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        h = hh + rh + 6
        h = min(max(h, 60), 500)
        self.table.setMinimumHeight(h)
        self.table.setMaximumHeight(h)

    def set_edit_mode(self, can_edit):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
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
        new_delegate = _AutocompleteDelegate(lambda dl=data_list: dl, self.table)
        self.table.setItemDelegateForColumn(col_idx, new_delegate)


# ===========================================================================
# TODAY PAYMENT TAB
# ===========================================================================
class TodayPaymentTab(QWidget):
    # Fixed core section definitions: (name, color, col_specs or None)
    # col_specs = list of (header, width, delegate_instance_or_None)
    _CORE_SECTIONS = [
        ("Payments",            "#1565C0", None),  # col_specs set after completer is built
        ("Demand Loans (DL)",   "#2E7D32", None),
        ("Purchase (Today)",    "#00695C", None),
        ("Account Table",       "#E65100", None),
        ("Purchase (Upcoming)", "#4527A0", None),
        ("Limits & LC",         "#B71C1C", None),
    ]

    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._db = get_db_manager()
        self._db_name = ""
        self._party_list = []         # Sundry Debtors list for Payments col 3
        self._section_cards = {}      # section_id -> _SectionCard
        self._current_view = 1        # 0=single, 1=multi

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Top bar ----
        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)

        lbl = QLabel("Today Payment")
        lbl.setFont(_bold_font(13))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()

        self._btn_add = QPushButton("+ New Table")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_section)
        tlay.addWidget(self._btn_add)

        # View toggle
        toggle_frame = QFrame()
        toggle_frame.setStyleSheet(
            "QFrame{background:#e2e8f0;border-radius:6px;}")
        tgl = QHBoxLayout(toggle_frame)
        tgl.setContentsMargins(3, 3, 3, 3)
        tgl.setSpacing(2)

        _ts = ("QPushButton{border-radius:4px;padding:3px 14px;font-size:10pt;border:none;}"
               "QPushButton:checked{background:#1d4ed8;color:white;font-weight:bold;}"
               "QPushButton:!checked{background:transparent;color:#64748b;}")
        self._btn_single = QPushButton("Single Table")
        self._btn_single.setCheckable(True)
        self._btn_stack  = QPushButton("Multi View")
        self._btn_stack.setCheckable(True)
        self._btn_stack.setChecked(True)
        for b in (self._btn_single, self._btn_stack):
            b.setStyleSheet(_ts)
            tgl.addWidget(b)
        self._btn_single.clicked.connect(lambda: self._switch_view(0))
        self._btn_stack.clicked.connect(lambda: self._switch_view(1))
        tlay.addWidget(toggle_frame)
        main_layout.addWidget(top_bar)

        # ---- Body: QStackedWidget switching between single and multi view ----
        self._body_stack = QStackedWidget()
        self._body_stack.setContentsMargins(0, 0, 0, 0)

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
                background: #dbeafe; color: #1d4ed8; font-weight: bold;
            }
            QListWidget::item:hover:!selected { background: #e2e8f0; }
        """)
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
        multi_scroll.setStyleSheet("QScrollArea{background:#f1f5f9;}")

        self._multi_container = QWidget()
        self._multi_container.setStyleSheet("background:transparent;")
        self._multi_grid = QGridLayout(self._multi_container)
        self._multi_grid.setContentsMargins(12, 12, 12, 12)
        self._multi_grid.setSpacing(12)
        # Stretch both columns equally
        self._multi_grid.setColumnStretch(0, 1)
        self._multi_grid.setColumnStretch(1, 1)

        multi_scroll.setWidget(self._multi_container)
        self._body_stack.addWidget(multi_scroll)

        self._body_stack.setCurrentIndex(1)   # default: multi view
        main_layout.addWidget(self._body_stack)


    def _switch_view(self, idx):
        self._current_view = idx
        self._btn_single.setChecked(idx == 0)
        self._btn_stack.setChecked(idx == 1)
        self._body_stack.setCurrentIndex(idx)
        if idx == 0:
            self._on_sidebar_select(self._sidebar_list.currentRow())
        else:
            self._rebuild_multi_grid()

    def _build_core_section_specs(self):
        """Build column specs for the Payments core section."""
        date_delegate = _DateDelegate()
        party_delegate = _AutocompleteDelegate(lambda: self._party_list)

        specs = {
            "Payments": [
                ("S.N",        40,  None),
                ("Date",      110,  date_delegate),
                ("Party Name",200,  party_delegate),
                ("Bank",      130,  None),
                ("Cheque No", 110,  None),
                ("Amount",    110,  None),
                ("Narration", 180,  None),
            ],
            "Demand Loans (DL)": [
                ("S.N",        40,  None),
                ("Party Name", 200, None),
                ("Limit",      110, None),
                ("Outstanding",110, None),
                ("Expiry Date",110, date_delegate),
                ("Remarks",    200, None),
            ],
            "Purchase (Today)": [
                ("S.N",        40,  None),
                ("Supplier",  200,  None),
                ("Item",      160,  None),
                ("Qty",        80,  None),
                ("Rate",       90,  None),
                ("Amount",    110,  None),
                ("Date",      110,  date_delegate),
            ],
            "Account Table": [
                ("S.N",        40,  None),
                ("Account",   200,  None),
                ("Debit",     110,  None),
                ("Credit",    110,  None),
                ("Balance",   120,  None),
                ("Remarks",   180,  None),
            ],
            "Purchase (Upcoming)": [
                ("S.N",        40,  None),
                ("Supplier",  200,  None),
                ("Item",      160,  None),
                ("Qty",        80,  None),
                ("Rate",       90,  None),
                ("Amount",    110,  None),
                ("Expected Date", 120, date_delegate),
            ],
            "Limits & LC": [
                ("S.N",        40,  None),
                ("Party",     200,  None),
                ("Limit",     110,  None),
                ("Used",      110,  None),
                ("Available", 110,  None),
                ("Expiry",    110,  date_delegate),
                ("Remarks",   180,  None),
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
        """Load Sundry Debtors list for the Payments party autocomplete."""
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
                    cur.execute("SELECT Alias, Name FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
                    mapping = {}
                    for alias, name in cur.fetchall():
                        alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
                        name_str  = str(name).strip()  if name  and str(name).strip().lower()  != "none" else ""
                        if alias_str:
                            mapping[alias_str] = name_str
                        if name_str:
                            mapping[name_str] = name_str
                    self._party_list = list(mapping.keys())
                    break
                except Exception:
                    pass
        except Exception as e:
            print("[TodayPayment] Could not load party list:", e)

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

        # Add is_core column if it doesn't exist (migration)
        try:
            conn = self._db.get_connection(self._db_name)
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("ALTER TABLE tp_sections ADD is_core BIT DEFAULT 0")
                    conn.commit()
                except Exception:
                    pass  # Column already exists
        except Exception:
            pass

    def _seed_core_sections(self):
        """Insert the fixed core sections if they don't exist yet."""
        _CORE = [
            ("Payments",            "#1565C0", 0),
            ("Demand Loans (DL)",   "#2E7D32", 1),
            ("Purchase (Today)",    "#00695C", 2),
            ("Account Table",       "#E65100", 3),
            ("Purchase (Upcoming)", "#4527A0", 4),
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
            print("[TodayPayment] Seed core sections error:", e)

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
            "SELECT id, name, header_color, is_core FROM tp_sections ORDER BY sort_order, id"
        ) or []

        core_specs = self._build_core_section_specs()

        for sid, name, color, is_core in rows:
            col_specs = core_specs.get(name) if is_core else None
            card = _SectionCard(
                sid, name or "Table", color or "#1565C0",
                self._db, self._db_name,
                col_specs=col_specs,
                parent=self._multi_container
            )
            card._today_tab_ref = self   # direct reference, avoids broken parent-walk
            card.set_edit_mode(self._can_edit)
            self._section_cards[sid] = card

            # Sidebar entry
            item = QListWidgetItem(f"  {name}")
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

    def _on_sidebar_select(self, row):
        """Show the selected card in single-table view. No-op in multi view."""
        if self._current_view != 0:
            return  # Only affects single view — prevents grid gap bug

        # Remove any existing card from single pane
        while self._single_card_holder.count() > 0:
            item = self._single_card_holder.takeAt(0)
            if item.widget():
                item.widget().setParent(self._multi_container)  # re-park under multi

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
        # Re-parent card to single pane
        card.setParent(self._single_pane)
        self._single_card_holder.addWidget(card)

    def _rename_section_from_sidebar(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        res = self._db.execute_query(
            self._db_name, "SELECT is_core, name FROM tp_sections WHERE id=?", (sid,))
        if not res:
            return
        is_core, current_name = res[0]
        new, ok = QInputDialog.getText(self, "Rename Table", "New name:", text=current_name)
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
        # Only refresh the grid layout — don't rebuild (that destroys and recreates cards)
        if self._current_view == 1:
            self._rebuild_multi_grid()
        elif self._current_view == 0:
            # Re-select current item so single-view refreshes
            self._on_sidebar_select(self._sidebar_list.currentRow())

    def _add_section(self):
        if not self._can_edit or not self._db_name:
            return
        name, ok = QInputDialog.getText(self, "Add Table", "Table name:")
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
                (max_ord, name.strip(), "#1565C0"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return
        self._rebuild_section_views()

    def _clear_multi_grid(self):
        """Remove all widgets AND row stretches from the multi grid layout."""
        while self._multi_grid.count() > 0:
            item = self._multi_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        # Clear all row stretches accumulated from previous builds
        for r in range(self._multi_grid.rowCount() + 1):
            self._multi_grid.setRowStretch(r, 0)

    def _rebuild_multi_grid(self):
        """Lay cards out in a 2-column grid inside the multi view."""
        self._clear_multi_grid()
        # Get cards in their current sort order (from sidebar, which reflects DB order)
        ordered_sids = []
        for i in range(self._sidebar_list.count()):
            sid = self._sidebar_list.item(i).data(Qt.ItemDataRole.UserRole)
            ordered_sids.append(sid)

        for i, sid in enumerate(ordered_sids):
            card = self._section_cards.get(sid)
            if card:
                row, col = divmod(i, 2)
                card.setParent(self._multi_container)
                self._multi_grid.addWidget(card, row, col)
        # Stretch the empty row at the bottom so cards don't balloon vertically
        n = len(ordered_sids)
        self._multi_grid.setRowStretch((n + 1) // 2, 1)

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

        # Redraw the grid with new order (no full rebuild needed)
        self._rebuild_multi_grid()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._btn_add.setEnabled(can_edit)
        for card in self._section_cards.values():
            card.set_edit_mode(can_edit)


# ===========================================================================
# RECORD TAB — Supplier Bank Accounts
# ===========================================================================
_REC_FIELDS = [
    ("naam",    "नाम",        "Name"),
    ("thegana", "ठेगाना",    "Address"),
    ("baik",    "बैंक",       "Bank"),
    ("khata",   "खाता न.",   "Account No."),
    ("rakam",   "रकम",        "Amount"),
    ("jamma",   "जम्मा गर्ने","Deposit To"),
]

# ─── color tokens ───────────────────────────────────────────────────────────
_C_CO_BG     = "#f0faf5"   # company card background
_C_CO_BORDER = "#b2dfcc"   # company card border
_C_CO_ACCENT = "#1e7a4b"   # company label/header accent
_C_CO_HEAD   = "#e6f5ee"   # company column header bg

_C_PE_BG     = "#f0f5fc"   # personal card bg
_C_PE_BORDER = "#b3c9e8"   # personal card border
_C_PE_ACCENT = "#1a4a8a"   # personal label/header accent
_C_PE_HEAD   = "#e6edf8"   # personal column header bg

_C_SUP_HEADER  = "#f8f9fa"  # supplier row header bg
_C_PAGE_BG     = "#eef0f3"  # scroll-area bg
_C_CARD_NORM   = "#ffffff"  # unselected card bg
_C_SEP         = "#d1d5db"  # thin separators

# ─── common input stylesheet ─────────────────────────────────────────────────
def _field_ss(accent_color="#1a4a8a", is_amount=False):
    """Uniform field stylesheet. Amount gets bold text only — no green tint."""
    return f"""
        QLineEdit {{
            background:#ffffff; border:1px solid #d1d5db;
            border-radius:2px; padding:2px 6px;
            color:#111827; font-size:9pt;
            {'font-weight:bold;' if is_amount else ''}
        }}
        QLineEdit:hover {{ border-color:{accent_color}; }}
        QLineEdit:focus {{ border:1px solid {accent_color}; background:white; }}
        QLineEdit:read-only {{
            background:#f9fafb; border-color:#e5e7eb;
            color:#374151;
        }}
    """


class _AccCard(QFrame):
    """One compact account card — label | input rows, right-click to delete."""

    def __init__(self, supplier_id, acc_idx, acc_data, db, db_name,
                 is_company=True, can_edit=True, refresh_fn=None, parent=None):
        super().__init__(parent)
        self.supplier_id  = supplier_id
        self.acc_idx      = acc_idx
        self._db          = db
        self._db_name     = db_name
        self._can_edit    = can_edit
        self._is_company  = is_company
        self._saving      = False
        self._selected    = False
        self._refresh_fn  = refresh_fn
        self._field_edits = []  # list of (fkey, QLineEdit)

        accent = _C_CO_ACCENT if is_company else _C_PE_ACCENT
        bg     = _C_CO_BG     if is_company else _C_PE_BG
        border = _C_CO_BORDER if is_company else _C_PE_BORDER

        self.setObjectName("AccCard")
        self._norm_ss = (
            f"QFrame#AccCard{{background:{bg};border:1px solid {border};"
            f"border-radius:3px;}}"
        )
        self._sel_ss = (
            f"QFrame#AccCard{{background:{bg};border:2px solid {accent};"
            f"border-radius:3px;}}"
        )
        self.setStyleSheet(self._norm_ss)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to select  |  Right-click to delete")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        lay = QFormLayout(self)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(3)
        lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for fkey, flabel_np, flabel_en in _REC_FIELDS:
            val = acc_data.get(fkey, "")
            is_amount = fkey == "rakam"

            lbl = QLabel(f"{flabel_np}:")
            lbl.setFont(_norm_font(7))
            lbl.setStyleSheet(
                f"color:{'#065f3a' if is_amount and is_company else accent if is_amount else '#6b7280'};"
                f"font-weight:{'600' if is_amount else '400'};"
                f"background:transparent;"
            )

            edit = QLineEdit(val)
            edit.setFont(_norm_font(8) if not is_amount else _bold_font(9))
            edit.setStyleSheet(_field_ss(accent, is_amount))
            edit.setReadOnly(not can_edit)
            edit.setFixedHeight(20)
            edit.setMinimumWidth(100)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if is_amount:
                edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            edit.editingFinished.connect(self._save)
            edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            edit.customContextMenuRequested.connect(self._show_context_menu)
            lay.addRow(lbl, edit)
            self._field_edits.append((fkey, edit))

    # ------------------------------------------------------------------
    def _show_context_menu(self, _):
        if not self._can_edit:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
            QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
            QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
        """)
        act_del = menu.addAction("Delete Account")
        act_del.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_TrashIcon))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_del:
            self._delete_self()

    def _delete_self(self):
        msg = QMessageBox(self.window())
        msg.setWindowTitle("Delete Account")
        msg.setText(f"Delete this {'Company' if self._is_company else 'Personal'} account card?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM supplier_accounts WHERE supplier_id=? AND acc_index=?",
                (self.supplier_id, self.acc_idx))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[AccCard] delete error:", e)
            return
        if callable(self._refresh_fn):
            self._refresh_fn()

    def set_selected(self, sel: bool):
        self._selected = sel
        self.setStyleSheet(self._sel_ss if sel else self._norm_ss)

    def is_selected(self) -> bool:
        return self._selected

    def set_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        for _, e in self._field_edits:
            e.setReadOnly(not can_edit)

    def _save(self):
        if not self._db_name or self._saving or not self._can_edit:
            return
        self._saving = True
        conn = self._db.get_connection(self._db_name)
        if not conn:
            self._saving = False
            return
        cur = conn.cursor()
        try:
            for fkey, edit in self._field_edits:
                cur.execute(
                    f"UPDATE supplier_accounts SET {fkey}=? "
                    f"WHERE supplier_id=? AND acc_index=?",
                    (edit.text().strip(), self.supplier_id, self.acc_idx))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[AccCard] _save error:", e)
        finally:
            self._saving = False


class _SupplierSection(QFrame):
    """One supplier: compact header + two-column account area (Company | Personal)."""

    def __init__(self, supplier_id, name, accounts, db, db_name,
                 can_edit=True, refresh_fn=None, parent=None):
        super().__init__(parent)
        self.supplier_id  = supplier_id
        self._db          = db
        self._db_name     = db_name
        self._can_edit    = can_edit
        self._saving      = False
        self._refresh_fn  = refresh_fn
        self._acc_cards: list[_AccCard] = []
        self._selected    = False

        self.setObjectName("SupplierSection")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._norm_ss = (
            "QFrame#SupplierSection{"
            "background:#ffffff;border:1px solid #d1d5db;"
            "border-radius:4px;}"
        )
        self._sel_ss = (
            "QFrame#SupplierSection{"
            "background:#f8fffc;border:2px solid #1e7a4b;"
            "border-radius:4px;}"
        )
        self.setStyleSheet(self._norm_ss)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ══ Supplier header ══════════════════════════════════════════════
        hdr = QFrame()
        hdr.setObjectName("SuppHdr")
        hdr.setFixedHeight(34)
        hdr.setStyleSheet(
            f"QFrame#SuppHdr{{background:{_C_SUP_HEADER};"
            f"border-bottom:1px solid {_C_SEP};"
            f"border-radius:4px 4px 0 0;}}")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 0, 6, 0)
        hdr_lay.setSpacing(8)

        # Index badge
        badge = QLabel(f"#{supplier_id}")
        badge.setFont(_bold_font(8))
        badge.setFixedSize(32, 18)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "color:#374151;background:#e5e7eb;"
            "border-radius:2px;font-size:8pt;")
        hdr_lay.addWidget(badge)

        # Supplier name
        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("Supplier / Party Name...")
        self._name_edit.setFont(_bold_font(10))
        self._name_edit.setStyleSheet("""
            QLineEdit {
                background:transparent; border:none;
                color:#111827; font-size:10pt; font-weight:600;
            }
            QLineEdit:focus {
                border-bottom:1px solid #1e7a4b;
                background:transparent;
            }
            QLineEdit:read-only { color:#1f2937; }
        """)
        self._name_edit.setReadOnly(not can_edit)
        self._name_edit.editingFinished.connect(self._save_name)
        self._name_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._name_edit.customContextMenuRequested.connect(self._show_context_menu)
        hdr_lay.addWidget(self._name_edit, 1)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        root.addWidget(hdr)

        # ══ Two-column body ═══════════════════════════════════════════════
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(10, 10, 10, 10)
        body_lay.setSpacing(12)

        # Split accounts into company vs personal
        co_accs = [(a.get("acc_idx", i), a) for i, a in enumerate(accounts)
                   if "company" in a.get("type", "").lower()]
        pe_accs = [(a.get("acc_idx", i), a) for i, a in enumerate(accounts)
                   if "company" not in a.get("type", "").lower()]

        for is_co, accs_for_col, head_txt, head_bg, head_accent in [
            (True,  co_accs, "??  COMPANY ACCOUNTS",  _C_CO_HEAD, _C_CO_ACCENT),
            (False, pe_accs, "??  PERSONAL ACCOUNTS", _C_PE_HEAD, _C_PE_ACCENT),
        ]:
            col = QWidget()
            col.setStyleSheet("background:transparent;")
            # Fixed horizontal size so column hugs its card content width
            col.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            col_lay = QVBoxLayout(col)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(4)

            if accs_for_col:
                # -- cards in a fixed-size container so header can match its width --
                cards_widget = QWidget()
                cards_widget.setStyleSheet("background:transparent;")
                cards_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                cards_row_lay = QHBoxLayout(cards_widget)
                cards_row_lay.setContentsMargins(0, 0, 0, 0)
                cards_row_lay.setSpacing(6)
                for acc_idx, acc_data in accs_for_col:
                    card = _AccCard(
                        supplier_id, acc_idx, acc_data,
                        db, db_name, is_co, can_edit, refresh_fn=self._refresh_fn, parent=body)
                    card.setMinimumWidth(190)
                    card.setMaximumWidth(280)
                    card.mousePressEvent = lambda e, c=card: self._acc_click(e, c)
                    cards_row_lay.addWidget(card)
                    self._acc_cards.append(card)

                # Header label -- width synced to cards_widget after layout
                col_hdr = QLabel(head_txt)
                col_hdr.setFont(_bold_font(8))
                col_hdr.setFixedHeight(22)
                col_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
                col_hdr.setStyleSheet(
                    f"color:{head_accent};background:{head_bg};"
                    f"border:1px solid {'#c2ddd0' if is_co else '#c0cfe8'};"
                    f"border-radius:2px;font-size:8pt;letter-spacing:0.5px;")

                col_lay.addWidget(col_hdr)
                col_lay.addWidget(cards_widget)

                # Deferred sync: set header width == cards_widget sizeHint width
                def _sync(hdr=col_hdr, cw=cards_widget):
                    hdr.setFixedWidth(cw.sizeHint().width())
                QTimer.singleShot(0, _sync)

            else:
                col_hdr = QLabel(head_txt)
                col_hdr.setFont(_bold_font(8))
                col_hdr.setFixedHeight(22)
                col_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
                col_hdr.setStyleSheet(
                    f"color:{head_accent};background:{head_bg};"
                    f"border:1px solid {'#c2ddd0' if is_co else '#c0cfe8'};"
                    f"border-radius:2px;font-size:8pt;letter-spacing:0.5px;")
                col_lay.addWidget(col_hdr)
                empty = QLabel("No accounts")
                empty.setFont(_norm_font(8))
                empty.setStyleSheet(
                    "color:#9ca3af;padding:10px;"
                    "background:#fafafa;border:1px dashed #e5e7eb;"
                    "border-radius:2px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                col_lay.addWidget(empty)

            col_lay.addStretch()
            # No stretch factor -- column is exactly as wide as its content
            body_lay.addWidget(col)

        # Push columns left; blank space on the right
        body_lay.addStretch()

        root.addWidget(body)

    # ------------------------------------------------------------------
    def _acc_click(self, event, card: _AccCard):
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            card.set_selected(not card.is_selected())
        else:
            # Plain click: select only this card within this supplier
            for c in self._acc_cards:
                c.set_selected(c is card)
        # Bubble up so RecordTab can update its status bar
        if hasattr(self.parent(), '_update_status'):
            try:
                self.parent()._update_status()  # type: ignore
            except Exception:
                pass

    def set_selected(self, sel: bool):
        """Select/deselect the entire supplier section."""
        self._selected = sel
        self.setStyleSheet(self._sel_ss if sel else self._norm_ss)
        for c in self._acc_cards:
            c.set_selected(sel)

    def is_selected(self) -> bool:
        return self._selected

    def selected_cards(self) -> list:
        return [c for c in self._acc_cards if c.is_selected()]

    def set_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._name_edit.setReadOnly(not can_edit)
        for c in self._acc_cards:
            c.set_edit_mode(can_edit)

    def _save_name(self):
        if not self._db_name or self._saving or not self._can_edit:
            return
        self._saving = True
        conn = self._db.get_connection(self._db_name)
        if not conn:
            self._saving = False
            return
        cur = conn.cursor()
        try:
            cur.execute("UPDATE supplier_records SET name=? WHERE id=?",
                        (self._name_edit.text().strip(), self.supplier_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[SupplierSection] _save_name error:", e)
        finally:
            self._saving = False

    def _show_context_menu(self, _):
        if not self._can_edit:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#ffffff;border:1px solid #d1d5db;border-radius:3px;padding:2px;}
            QMenu::item{padding:6px 20px;font-size:10pt;color:#111827;}
            QMenu::item:selected{background:#fee2e2;color:#b91c1c;border-radius:2px;}
        """)
        act_del = menu.addAction("Delete Supplier")
        act_del.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_TrashIcon))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_del:
            self._delete_supplier()

    def _delete_supplier(self):
        """Delete this entire supplier record + all its accounts."""
        name = self._name_edit.text().strip() or f"Supplier #{self.supplier_id}"
        msg = QMessageBox(self.window())
        msg.setWindowTitle("Delete Supplier")
        msg.setText(f"Delete supplier '{name}' and ALL its account cards?")
        msg.setInformativeText("This cannot be undone.")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM supplier_accounts WHERE supplier_id=?",
                        (self.supplier_id,))
            cur.execute("DELETE FROM supplier_records WHERE id=?",
                        (self.supplier_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[SupplierSection] _delete_supplier error:", e)
            return
        if callable(self._refresh_fn):
            self._refresh_fn()


class RecordTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._db = get_db_manager()
        self._db_name = ""
        self._sections: list[_SupplierSection] = []
        self._last_clicked_idx = -1

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ══ Compact dark header toolbar ══════════════════════════════════
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet("background:#1c2b3a; border-bottom:1px solid #2d3f50;")
        hlay = QHBoxLayout(hdr)
        hlay.setContentsMargins(14, 0, 14, 0)
        hlay.setSpacing(6)

        title = QLabel("🏦  Supplier Bank Records")
        title.setFont(_bold_font(11))
        title.setStyleSheet("color:#e2e8f0; font-size:11pt;")
        hlay.addWidget(title)

        self._sel_status = QLabel("—")
        self._sel_status.setFont(_norm_font(8))
        self._sel_status.setStyleSheet(
            "color:#64748b;padding:2px 8px;"
            "border-radius:2px;border:1px solid #2d3f50;"
            "background:#1c2b3a;")
        hlay.addWidget(self._sel_status)
        hlay.addStretch()

        # Hint
        hint = QLabel("Click · Ctrl+Click · Shift+Click")
        hint.setFont(_norm_font(8))
        hint.setStyleSheet("color:#475569;")
        hlay.addWidget(hint)

        _BTN_HDR = """
            QPushButton{{background:{bg};color:{fg};border:1px solid {bd};
                border-radius:2px;padding:3px 10px;font-size:8pt;
                font-weight:{fw};}}
            QPushButton:hover{{background:{hv};}}
            QPushButton:disabled{{background:#1c2b3a;color:#475569;border-color:#2d3f50;}}
        """

        def _hbtn(label, bg, fg, bd, hv, fw="400"):
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.setStyleSheet(_BTN_HDR.format(
                bg=bg, fg=fg, bd=bd, hv=hv, fw=fw))
            return b

        btn_clr = _hbtn("✕", "#1c2b3a", "#64748b", "#2d3f50", "#263545")
        btn_clr.setToolTip("Deselect all")
        btn_clr.clicked.connect(self._deselect_all)
        hlay.addWidget(btn_clr)

        self._btn_image = _hbtn("⎙ Copy", "#263545", "#94a3b8", "#334155", "#2d3f50")
        self._btn_image.setToolTip("Copy selected supplier(s) as image  (Ctrl+C)")
        self._btn_image.clicked.connect(self._copy_selected_as_image)
        hlay.addWidget(self._btn_image)

        self._btn_add = _hbtn("+ Supplier", "#1e3a52", "#7dd3fc", "#2d5a7a", "#1a3347", "600")
        self._btn_add.clicked.connect(self._add_supplier)
        hlay.addWidget(self._btn_add)

        self._btn_add_co = _hbtn("+ Company Acc", "#0d3526", "#6ee7b7", "#1e5c40", "#0b2d20", "600")
        self._btn_add_co.clicked.connect(self._add_company_acct)
        hlay.addWidget(self._btn_add_co)

        self._btn_add_pe = _hbtn("+ Personal Acc", "#0d2341", "#93c5fd", "#1a3f6b", "#0b1d34", "600")
        self._btn_add_pe.clicked.connect(self._add_personal_acct)
        hlay.addWidget(self._btn_add_pe)

        main_layout.addWidget(hdr)

        # ══ Scroll area ══════════════════════════════════════════════════
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{_C_PAGE_BG};}}"
            "QScrollBar:vertical{width:7px;background:transparent;}"
            "QScrollBar::handle:vertical{background:#c1c9d2;border-radius:3px;min-height:20px;}"
            "QScrollBar::handle:vertical:hover{background:#a0aab4;}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{_C_PAGE_BG};")
        self._c_lay = QVBoxLayout(self._container)
        self._c_lay.setContentsMargins(16, 14, 16, 14)
        self._c_lay.setSpacing(10)
        self._scroll.setWidget(self._container)
        main_layout.addWidget(self._scroll)

        # Ctrl+C → copy image
        shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        shortcut.activated.connect(self._copy_selected_as_image)

    # ──────────────────────────────────────────────────────────────────────
    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._ensure_tables()
        self._load_cards()

    def _ensure_tables(self):
        for tname, ddl in [
            ("supplier_records",
             "CREATE TABLE supplier_records "
             "(id INT IDENTITY PRIMARY KEY, name NVARCHAR(300), sort_order INT)"),
            ("supplier_accounts",
             "CREATE TABLE supplier_accounts "
             "(id INT IDENTITY PRIMARY KEY, supplier_id INT, acc_index INT, "
             "acc_type NVARCHAR(100), naam NVARCHAR(300), thegana NVARCHAR(300), "
             "baik NVARCHAR(300), khata NVARCHAR(300), rakam NVARCHAR(100), "
             "jamma NVARCHAR(300))"),
        ]:
            self._db.ensure_table(self._db_name, tname, ddl)

    def _load_cards(self):
        # Capture currently selected supplier IDs to persist across reload
        selected_ids = {s.supplier_id for s in self._sections if s.is_selected()}

        for w in self._sections:
            try:
                w.setParent(None)
                w.deleteLater()
            except RuntimeError:
                pass
        self._sections.clear()
        self._last_clicked_idx = -1
        while self._c_lay.count() > 0:
            item = self._c_lay.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        suppliers = self._db.execute_query(
            self._db_name,
            "SELECT id, name FROM supplier_records ORDER BY sort_order, id"
        ) or []

        for sup_id, sup_name in suppliers:
            accs = self._db.execute_query(
                self._db_name,
                "SELECT acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma "
                "FROM supplier_accounts WHERE supplier_id=? ORDER BY acc_index",
                (sup_id,)
            ) or []
            acc_list = []
            for acc_idx, acc_type, naam, thegana, baik, khata, rakam, jamma in accs:
                acc_list.append({
                    "acc_idx": acc_idx,
                    "type": acc_type or "Account",
                    "naam": naam or "", "thegana": thegana or "",
                    "baik": baik or "", "khata": khata or "",
                    "rakam": rakam or "", "jamma": jamma or "",
                })

            section = _SupplierSection(
                sup_id, sup_name or "", acc_list,
                self._db, self._db_name, self._can_edit,
                refresh_fn=self._load_cards,
                parent=self._container)
            
            # Restore selection state
            if sup_id in selected_ids:
                section.set_selected(True)
                
            # Clicking the supplier header row selects entire section
            section._name_edit.mousePressEvent = lambda e, s=section: self._section_click(e, s)
            # Wrap in HBox + stretch so section only takes its content width,
            # not the full scroll-area width (Qt stretches VBox children horizontally).
            row_wrap = QHBoxLayout()
            row_wrap.setContentsMargins(0, 0, 0, 0)
            row_wrap.setSpacing(0)
            row_wrap.addWidget(section)
            row_wrap.addStretch()
            self._c_lay.addLayout(row_wrap)
            self._sections.append(section)

        self._c_lay.addStretch()
        self._update_status()

    # ──────────────────────────────────────────────────────────────────────
    def _section_click(self, event, section: _SupplierSection):
        mods = event.modifiers()
        curr_idx = self._sections.index(section) if section in self._sections else -1

        if mods & Qt.KeyboardModifier.ControlModifier:
            section.set_selected(not section.is_selected())
            if section.is_selected():
                self._last_clicked_idx = curr_idx
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            lo = self._last_clicked_idx
            if lo >= 0 and curr_idx >= 0:
                a, b = sorted([lo, curr_idx])
                for i, s in enumerate(self._sections):
                    s.set_selected(a <= i <= b)
            else:
                self._select_only(section, curr_idx)
        else:
            self._select_only(section, curr_idx)

        self._update_status()
        # Also let the edit widget receive focus naturally
        section._name_edit.setFocus()

    def _select_only(self, section, idx=-1):
        for s in self._sections:
            s.set_selected(s is section)
        self._last_clicked_idx = idx

    def _deselect_all(self):
        for s in self._sections:
            s.set_selected(False)
        self._last_clicked_idx = -1
        self._update_status()

    def _update_status(self):
        n_sup = sum(1 for s in self._sections if s.is_selected())
        n_acc = sum(len(s.selected_cards()) for s in self._sections)
        total = n_sup if n_sup else n_acc
        if total == 0:
            self._sel_status.setText("—")
            self._sel_status.setStyleSheet(
                "color:#64748b;padding:2px 8px;"
                "border-radius:2px;border:1px solid #2d3f50;background:#1c2b3a;")
        else:
            label = (f"{n_sup} supplier{'s' if n_sup>1 else ''}"
                     if n_sup else f"{n_acc} account card{'s' if n_acc>1 else ''}")
            self._sel_status.setText(f"✓  {label} selected")
            self._sel_status.setStyleSheet(
                "color:#d1fae5;padding:2px 8px;"
                "border-radius:2px;font-weight:bold;"
                "border:1px solid #1e7a4b;background:#0d3526;")

    # ──────────────────────────────────────────────────────────────────────
    def _copy_selected_as_image(self):
        selected = [s for s in self._sections if s.is_selected()]
        if not selected:
            QMessageBox.information(self, "No Selection",
                                    "Click a supplier header to select it.\n"
                                    "Ctrl+Click = multi · Shift+Click = range.")
            return

        margin = 8
        bg = QColor(_C_PAGE_BG)
        pixmaps = []
        for sec in selected:
            hint = sec.sizeHint()
            ow, oh = sec.width(), sec.height()
            sec.setFixedSize(max(hint.width(), 640), hint.height())
            sec.adjustSize()
            px = sec.grab()
            sec.setMinimumSize(0, 0)
            sec.setMaximumSize(16777215, 16777215)
            sec.resize(ow, oh)
            pixmaps.append(px)

        max_w = max(p.width() for p in pixmaps)
        total_h = margin + sum(p.height() + margin for p in pixmaps)
        result = QPixmap(max_w + margin * 2, total_h)
        result.fill(bg)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = margin
        for px in pixmaps:
            painter.drawPixmap(margin, y, px)
            y += px.height() + margin
        painter.end()

        QApplication.clipboard().setPixmap(result)
        self._btn_image.setText("✓ Copied")
        QTimer.singleShot(2000, lambda: self._btn_image.setText("⎙ Copy"))

    # ──────────────────────────────────────────────────────────────────────
    def _add_supplier(self):
        if not self._can_edit or not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO supplier_records(name, sort_order) VALUES(?,?)",
                ("New Supplier", 9999))
            cur.execute("SELECT @@IDENTITY")
            new_id = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO supplier_accounts(supplier_id, acc_index, acc_type) VALUES(?,?,?)",
                (new_id, 0, "Company Account"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[RecordTab] _add_supplier error:", e)
            return
        self._load_cards()
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum())

    def _add_company_acct(self):
        self._add_account_to_selected("Company Account")

    def _add_personal_acct(self):
        self._add_account_to_selected("Personal Account")

    def _add_account_to_selected(self, acc_type: str):
        if not self._can_edit or not self._db_name:
            return
        selected = [s for s in self._sections if s.is_selected()]
        if not selected:
            QMessageBox.information(self, "Select Supplier",
                                    "Please select a supplier first.")
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            for sec in selected:
                res = self._db.execute_query(
                    self._db_name,
                    "SELECT ISNULL(MAX(acc_index), -1) FROM supplier_accounts WHERE supplier_id=?",
                    (sec.supplier_id,))
                next_idx = (res[0][0] if res else -1) + 1
                cur.execute(
                    "INSERT INTO supplier_accounts(supplier_id, acc_index, acc_type)"
                    " VALUES(?,?,?)",
                    (sec.supplier_id, next_idx, acc_type))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[RecordTab] _add_account error:", e)
            return
        self._load_cards()

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self._btn_add.setEnabled(can_edit)
        self._btn_add_co.setEnabled(can_edit)
        self._btn_add_pe.setEnabled(can_edit)
        for s in self._sections:
            s.set_edit_mode(can_edit)


# ===========================================================================
# INSURANCE TAB
# ===========================================================================
_INS_SECTIONS = [
    ("Human Insurance Details",   "#1A3A5C", "ins_human",
     [("Location",80),("Post",110),("Name of Employee",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
    ("Vehicle Insurance Details", "#8B4513", "ins_vehicle",
     [("Location",80),("Post",110),("Name of Employee",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
    ("Stock Insurance",           "#1E4D2B", "ins_stock",
     [("Location",80),("Post",110),("Description",200),
      ("Amount",110),("Starting Date",110),("Ending Date",110)]),
]


class InsuranceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._tables = []
        self._date_delegate = _DateDelegate()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top bar
        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(42)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Insurance Details")
        lbl.setFont(_bold_font(13))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        layout.addWidget(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:#f8fafc;}")

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(20)

        for title, color, tname, cols in _INS_SECTIONS:
            # Section header
            hdr = QLabel(title)
            hdr.setFont(_bold_font(11))
            hdr.setStyleSheet(
                f"background:{color}; color:white; padding:8px 14px; border-radius:6px 6px 0 0;")
            c_lay.addWidget(hdr)

            headers = [c[0] for c in cols]
            widths  = [c[1] for c in cols]
            tbl = _DbTable(tname, headers, widths)

            # Apply date delegates to start/end date columns (indices 4 and 5)
            tbl.setItemDelegateForColumn(4, _DateDelegate())
            tbl.setItemDelegateForColumn(5, _DateDelegate())

            # Add row button
            add_btn = QPushButton("+ Add Row")
            add_btn.setStyleSheet(_BTN_SECONDARY)
            add_btn.setFixedHeight(28)
            add_btn.clicked.connect(lambda _, t=tbl: t.add_row())
            btn_row = QHBoxLayout()
            btn_row.addWidget(add_btn)
            btn_row.addStretch()

            c_lay.addWidget(tbl)
            c_lay.addLayout(btn_row)
            self._tables.append((tname, tbl))

        c_lay.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        db = get_db_manager()
        for tname, tbl in self._tables:
            tbl.set_db_name(db_name)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        for _, tbl in self._tables:
            tbl.apply_edit_mode(can_edit)


# ===========================================================================
# BONUS DETAILS TAB
# ===========================================================================
_BONUS_LOC_COLORS = {
    "HO":  "#E8F4FD", "BTM": "#FFF3E0",
    "JNK": "#F3E5F5", "NGT": "#E8F5E9",
}
_BONUS_HEADERS = ["Location", "Post", "Name of Employee", "Diwali Bonus", "Remarks"]
_BONUS_WIDTHS  = [90, 110, 200, 120, 220]


class BonusTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Bonus Details")
        lbl.setFont(_bold_font(13))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()

        self._btn_add = QPushButton("+ Add Row")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        layout.addWidget(top_bar)

        self.table = _DbTable("bonus_data", _BONUS_HEADERS, _BONUS_WIDTHS, row_count=30)
        layout.addWidget(self.table)

    def _add_row(self):
        if not self._can_edit:
            return
        self.table.add_row()

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(db_name)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.apply_edit_mode(can_edit)
        self._btn_add.setEnabled(can_edit)


# ===========================================================================
# TEAM LIST TAB
# ===========================================================================
class TeamListTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._year_labels = [
            "2082-83", "2081-82", "2080-81", "2079-80",
            "2078-79", "2077-78", "2076-77", "2075-76",
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        lbl = QLabel("Team List")
        lbl.setFont(_bold_font(13))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()

        self._btn_add_yr  = QPushButton("+ Add Year")
        self._btn_add_yr.setStyleSheet(_BTN_SECONDARY)
        self._btn_add_yr.setFixedHeight(32)
        self._btn_add_yr.clicked.connect(self._add_year)
        tlay.addWidget(self._btn_add_yr)

        self._btn_add_emp = QPushButton("+ Add Employee")
        self._btn_add_emp.setStyleSheet(_BTN_PRIMARY)
        self._btn_add_emp.setFixedHeight(32)
        self._btn_add_emp.clicked.connect(self._add_employee)
        tlay.addWidget(self._btn_add_emp)
        layout.addWidget(top_bar)

        total_cols = 4 + len(self._year_labels) * 3
        headers = ["S.N", "Location", "Post", "Name of Employee"]
        for yr in self._year_labels:
            headers += ["", yr, "Salary"]
        widths = [40, 70, 110, 190]
        for _ in self._year_labels:
            widths += [30, 90, 90]

        self.table = _DbTable("team_list_data", headers, widths, row_count=40)
        layout.addWidget(self.table)

    def _add_year(self):
        if not self._can_edit:
            return
        latest = self._year_labels[0] if self._year_labels else "2082-83"
        parts = latest.split('-')
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            new_yr = f"{int(parts[0])+1}-{int(parts[1])+1}"
        else:
            new_yr = "New Year"
        self._year_labels.insert(0, new_yr)
        # Insert 3 new columns at position 4
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        self.table.insertColumn(4)
        self.table.setColumnWidth(4, 30)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 90)
        self.table.setHorizontalHeaderItem(4, QTableWidgetItem(""))
        self.table.setHorizontalHeaderItem(5, QTableWidgetItem(new_yr))
        self.table.setHorizontalHeaderItem(6, QTableWidgetItem("Salary"))
        self.table.save_to_db()

    def _add_employee(self):
        if not self._can_edit:
            return
        self.table.add_row()

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        db_name = build_logical_name(company_name, company_path=path)
        self.table.set_db_name(db_name)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.apply_edit_mode(can_edit)
        self._btn_add_yr.setEnabled(can_edit)
        self._btn_add_emp.setEnabled(can_edit)


# ===========================================================================
# ANIL DAI HISAB TAB — Running Balance Ledger
# ===========================================================================
_ANIL_COLS = [
    ("Start Date",  110), ("End Date",  110), ("Days",   55),
    ("Particular",  200), ("DR",        120), ("Cr.",    120),
    ("Balance",     135), ("Remarks",   180),
]
_ANIL_DR  = 4
_ANIL_CR  = 5
_ANIL_BAL = 6
_R = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
_C = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
_L = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


def _fmt(val):
    if val is None or val == "" or val == 0 or val == "0":
        return ""
    try:
        fv = float(val)
        if fv == int(fv):
            return f"{int(fv):,}"
        return f"{fv:,.2f}"
    except Exception:
        return str(val)


class AnilHisabTab(QWidget):
    def __init__(self):
        super().__init__()
        self._can_edit = True
        self._blocking = False
        self._db_name  = ""
        self._db       = get_db_manager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(48)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)

        lbl = QLabel("Anil Dai Hisab — Running Balance Ledger")
        lbl.setFont(_bold_font(12))
        lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(lbl)
        tlay.addStretch()

        self._btn_add = QPushButton("+ Add Row")
        self._btn_add.setStyleSheet(_BTN_PRIMARY)
        self._btn_add.setFixedHeight(32)
        self._btn_add.clicked.connect(self._add_row)
        tlay.addWidget(self._btn_add)
        layout.addWidget(top_bar)

        # Table
        n = len(_ANIL_COLS)
        self.table = QTableWidget(0, n)
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setHorizontalHeaderLabels([c[0] for c in _ANIL_COLS])
        for i, (_, w) in enumerate(_ANIL_COLS):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Date delegates on Start Date (0) and End Date (1)
        self.table.setItemDelegateForColumn(0, _DateDelegate())
        self.table.setItemDelegateForColumn(1, _DateDelegate())

        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

    def _a_item(self, text, align=_L):
        it = QTableWidgetItem("" if text is None else str(text))
        it.setTextAlignment(align)
        return it

    def set_company_path(self, path: str):
        company_name = os.path.basename(os.path.normpath(path))
        self._db_name = build_logical_name(company_name, company_path=path)
        self._ensure_table()
        self._load_from_db()

    def _ensure_table(self):
        ddl = ("CREATE TABLE anil_ledger "
               "(id INT IDENTITY PRIMARY KEY, sort_order INT, "
               "start_date NVARCHAR(20), end_date NVARCHAR(20), days NVARCHAR(20), "
               "particular NVARCHAR(MAX), dr NVARCHAR(50), cr NVARCHAR(50), "
               "remarks NVARCHAR(MAX))")
        self._db.ensure_table(self._db_name, "anil_ledger", ddl)

    def _load_from_db(self):
        rows = self._db.execute_query(
            self._db_name,
            "SELECT start_date, end_date, days, particular, dr, cr, remarks "
            "FROM anil_ledger ORDER BY sort_order, id"
        ) or []
        self._blocking = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row_data in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            start, end, days, part, dr, cr, remarks = row_data
            self.table.setItem(r, 0, self._a_item(start or "", _C))
            self.table.setItem(r, 1, self._a_item(end   or "", _C))
            self.table.setItem(r, 2, self._a_item(days  or "", _C))
            self.table.setItem(r, 3, self._a_item(part  or "", _L))
            self.table.setItem(r, 4, self._a_item(_fmt(dr)  if dr  else "", _R))
            self.table.setItem(r, 5, self._a_item(_fmt(cr)  if cr  else "", _R))
            self.table.setItem(r, 7, self._a_item(remarks or "", _L))
        self.table.blockSignals(False)
        self._blocking = False
        self._recalc_from(0)

    def _save_to_db(self):
        if not self._db_name:
            return
        conn = self._db.get_connection(self._db_name)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM anil_ledger")
            for r in range(self.table.rowCount()):
                def _t(c):
                    it = self.table.item(r, c)
                    return it.text().strip() if it else ""
                cur.execute(
                    "INSERT INTO anil_ledger"
                    "(sort_order,start_date,end_date,days,particular,dr,cr,remarks)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (r, _t(0), _t(1), _t(2), _t(3), _t(4), _t(5), _t(7)))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("[AnilHisab] _save_to_db error:", e)

    def _add_row(self):
        if not self._can_edit:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, self._a_item(""))
        self.table.scrollToBottom()
        self._recalc_from(r)

    def _recalc_from(self, start_row: int):
        self._blocking = True
        for r in range(start_row, self.table.rowCount()):
            prev_bal = 0.0
            if r > 0:
                prev_item = self.table.item(r - 1, _ANIL_BAL)
                try:
                    prev_bal = float(prev_item.text().replace(",", "")) if prev_item and prev_item.text() else 0.0
                except ValueError:
                    prev_bal = 0.0

            def _num(col):
                it = self.table.item(r, col)
                try:
                    return float(it.text().replace(",", "")) if it and it.text() else 0.0
                except ValueError:
                    return 0.0

            dr = _num(_ANIL_DR)
            cr = _num(_ANIL_CR)
            new_bal = (dr - cr) if r == 0 else (prev_bal + dr - cr)
            dr_txt = self.table.item(r, _ANIL_DR)
            cr_txt = self.table.item(r, _ANIL_CR)
            has_val = (dr_txt and dr_txt.text()) or (cr_txt and cr_txt.text())
            bal_str = _fmt(new_bal) if has_val else ""
            bal_it = self._a_item(bal_str, _R)
            if new_bal < 0:
                bal_it.setForeground(QBrush(QColor("#dc2626")))
            elif new_bal > 0:
                bal_it.setForeground(QBrush(QColor("#16a34a")))
            self.table.setItem(r, _ANIL_BAL, bal_it)

        self._blocking = False
        QTimer.singleShot(500, self._save_to_db)

    def _on_cell_changed(self, row, col):
        if self._blocking:
            return
        if col in (_ANIL_DR, _ANIL_CR):
            self._recalc_from(row)
        else:
            QTimer.singleShot(500, self._save_to_db)

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers)
        self._btn_add.setEnabled(can_edit)


# ===========================================================================
# PAYMENT SHEET  (generic user-added sheets — column view only)
# ===========================================================================
class _StyledTable(QWidget):
    """Colored-header table widget for PaymentSheet."""
    def __init__(self, title, headers, widths, header_color="#1565C0", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QLabel(title)
        hdr.setFont(_bold_font(11))
        hdr.setStyleSheet(
            f"background:{header_color}; color:white; padding:8px 14px; "
            f"border-radius:6px 6px 0 0;")
        lay.addWidget(hdr)

        self.table = QTableWidget(0, len(headers))
        self.table.setFont(_norm_font())
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.table.setMinimumHeight(60)
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Row")
        self.btn_add.setStyleSheet(_BTN_SECONDARY)
        self.btn_add.setFixedHeight(26)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch()
        btn_row.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(btn_row)

        self.recalculate_height()
        self.table.model().rowsInserted.connect(lambda *_: self.recalculate_height())
        self.table.model().rowsRemoved.connect(lambda *_: self.recalculate_height())

    def recalculate_height(self):
        hh = self.table.horizontalHeader().height()
        rh = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        h = hh + rh + 6
        h = min(max(h, 60), 600)
        self.table.setMinimumHeight(h)
        self.table.setMaximumHeight(h)


class PaymentSheet(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self._tables = []
        self._db_name = ""
        self._db = get_db_manager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet("background:#f8fafc; border-bottom:1px solid #e2e8f0;")
        top_bar.setFixedHeight(42)
        tlay = QHBoxLayout(top_bar)
        tlay.setContentsMargins(16, 6, 16, 6)
        title_lbl = QLabel(cfg.get("tab", "Sheet"))
        title_lbl.setFont(_bold_font(12))
        title_lbl.setStyleSheet("color:#1e293b;")
        tlay.addWidget(title_lbl)
        layout.addWidget(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(20)

        cols = cfg.get("columns", [])
        headers = [c[0] for c in cols]
        widths  = [c[1] for c in cols]
        sections = cfg.get("sections", {0: ("Data", "#1976D2")})

        for row, (label, bg) in sections.items():
            t = _StyledTable(label, headers, widths, header_color=bg)
            t.btn_add.clicked.connect(lambda _, tbl=t: self._add_row(tbl))
            self._tables.append(t)
            c_lay.addWidget(t)

        c_lay.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _add_row(self, tbl):
        r = tbl.table.rowCount()
        tbl.table.insertRow(r)
        for c in range(tbl.table.columnCount()):
            tbl.table.setItem(r, c, QTableWidgetItem(""))
        tbl.recalculate_height()

    def set_company_path(self, path: str):
        pass  # Generic sheets don't persist to DB

    def setEditTriggers(self, trigs):
        for t in self._tables:
            t.table.setEditTriggers(trigs)


# ===========================================================================
# MAIN WIDGET
# ===========================================================================
class SuppPaymentUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SuppPaymentMain")
        self._can_edit = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("PaymentTabContainer")
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: #e2e8f0; color: #475569;
                padding: 7px 18px; border-radius: 6px 6px 0 0;
                margin-right: 2px; font-size: 10pt;
            }
            QTabBar::tab:selected {
                background: #1d4ed8; color: white; font-weight: bold;
            }
            QTabBar::tab:hover:!selected { background: #cbd5e1; }
        """)

        self.add_button = QPushButton("+")
        self.add_button.setObjectName("AddNewSheetBtn")
        self.add_button.setFixedSize(36, 30)
        self.add_button.setStyleSheet(_BTN_PRIMARY)
        self.add_button.clicked.connect(self.add_new_sheet)
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        # Core tabs
        self._today_payment_tab = TodayPaymentTab()
        self.tabs.addTab(self._today_payment_tab, "Today Payment")

        self._record_tab = RecordTab()
        self.tabs.addTab(self._record_tab, "Record")

        self._anil_tab = AnilHisabTab()
        self.tabs.addTab(self._anil_tab, "Anil Dai Hisab")

        self._team_tab  = TeamListTab()
        self._bonus_tab = BonusTab()
        self._ins_tab   = InsuranceTab()
        self.tabs.addTab(self._team_tab,  "Team-List")
        self.tabs.addTab(self._bonus_tab, "Bonus Details")
        self.tabs.addTab(self._ins_tab,   "Insurance")

        self.tabs.setCurrentIndex(0)
        layout.addWidget(self.tabs)

    def set_company_path(self, path: str):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, 'set_company_path'):
                w.set_company_path(path)

    def add_new_sheet(self):
        if not self._can_edit:
            return
        blank = {
            "tab": f"Sheet {self.tabs.count() + 1}",
            "columns": [(chr(65 + i), 100) for i in range(10)],
            "sections": {0: ("Data", "#1565C0")},
        }
        self.tabs.addTab(PaymentSheet(blank), blank["tab"])
        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def rename_tab(self, index: int):
        if not self._can_edit or index == -1:
            return
        old = self.tabs.tabText(index)
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip():
            self.tabs.setTabText(index, new.strip())

    def show_tab_menu(self, point):
        idx = self.tabs.tabBar().tabAt(point)
        if idx == -1:
            return
        menu = QMenu(self)
        ra = menu.addAction("✏ Rename Sheet")
        da = menu.addAction("🗑 Delete Sheet")
        act = menu.exec(self.tabs.tabBar().mapToGlobal(point))
        if act == ra:
            self.rename_tab(idx)
        elif act == da:
            if self.tabs.count() > 1:
                if (QMessageBox.question(
                        self, "Delete",
                        f"Delete '{self.tabs.tabText(idx)}'?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        == QMessageBox.StandardButton.Yes):
                    self.tabs.removeTab(idx)
            else:
                QMessageBox.warning(self, "Warning", "At least one sheet must remain!")

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        triggers = (
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed
            if can_edit else QTableWidget.EditTrigger.NoEditTriggers
        )
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, PaymentSheet):
                w.setEditTriggers(triggers)
            elif hasattr(w, "apply_edit_mode"):
                w.apply_edit_mode(can_edit)
        self.add_button.setEnabled(can_edit)
        self.tabs.setMovable(can_edit)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu if can_edit
            else Qt.ContextMenuPolicy.NoContextMenu)
