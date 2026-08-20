"""
ExcelTableMixin — shared Excel-like Mode 1 / Mode 2 navigation for QTableWidget.
"""

from PyQt6.QtWidgets import QAbstractItemView, QStyledItemDelegate, QLineEdit, QDateEdit, QStyleOptionViewItem, QCompleter
from PyQt6.QtCore import Qt, QEvent, QTimer, QDate

# Custom roles for the universal delegate
CELL_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1          # "date", "number", "autocomplete", or None (text)
AUTOCOMPLETE_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 2 # list of strings or callable
DISPLAY_CALLBACK_ROLE = Qt.ItemDataRole.UserRole + 3   # callable(index) -> str
SET_MODEL_DATA_CALLBACK_ROLE = Qt.ItemDataRole.UserRole + 4 # callable(text, index)

# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------

class _TallyCompleter(QCompleter):
    def __init__(self, data_list, parent=None):
        super().__init__(data_list, parent)
        self.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

def _enforce_match(editor, text, data_list):
    if text and data_list:
        text_lower = text.lower()
        if not any(text_lower in item.lower() for item in data_list):
            editor.setText(text[:-1])

def get_visual_text(table, r, c):
    """Get the visual text of a cell, resolving any delegates (e.g. converting GUID to party name)."""
    w = table.cellWidget(r, c)
    if w and hasattr(w, "text"):
        return w.text().strip()
        
    it = table.item(r, c)
    if not it:
        return ""
        
    index = table.model().index(r, c)
    
    # Check data role first
    display_cb = index.data(DISPLAY_CALLBACK_ROLE)
    if callable(display_cb):
        res = display_cb(index)
        if res is not None:
            return str(res).strip()
            
    # Check delegate fallback
    delegate = table.itemDelegateForColumn(c) or table.itemDelegateForIndex(index) or table.itemDelegate()
    if delegate and hasattr(delegate, "_display_cb") and callable(delegate._display_cb):
        res = delegate._display_cb(index)
        if res is not None:
            return str(res).strip()
            
    return it.text().strip()

# ---------------------------------------------------------------------------
# Universal Cell Delegate
# ---------------------------------------------------------------------------

UNIVERSAL_TABLE_STYLE = """
QTableWidget {
    gridline-color: #e2e8f0;
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-family: 'Segoe UI';
    font-size: 10pt;
}
QTableWidget::item {
    /* Zero padding: avoids content-rect vs visualRect mismatch that caused
       the inset-box appearance. Row height (26px) provides sufficient spacing. */
    padding: 0px;
}
QTableWidget::item:selected {
    background-color: #dbeafe;
    color: #1e40af;
}
QTableWidget::item:open {
    background-color: transparent;
    color: #000000;
}
"""

class UniversalCellDelegate(QStyledItemDelegate):
    def __init__(self, owner=None, parent=None, cell_type=None, autocomplete_items=None, display_cb=None, set_model_cb=None, enforce_match=True):
        if parent is None and owner is not None:
            parent = owner
        super().__init__(parent)
        if hasattr(parent, '__dict__'):
            if not hasattr(parent, '_universal_delegate_refs'):
                parent._universal_delegate_refs = []
            parent._universal_delegate_refs.append(self)
            
        self._owner = owner
        self._cell_type = cell_type
        self._autocomplete_items = autocomplete_items
        self._display_cb = display_cb
        self._set_model_cb = set_model_cb
        self._enforce_match = enforce_match

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        display_cb = index.data(DISPLAY_CALLBACK_ROLE) or self._display_cb
        if callable(display_cb):
            display_text = display_cb(index)
            if display_text is not None:
                option.text = str(display_text)

    def paint(self, painter, option, index):
        """Delegate paint. The editor is opaque-white so it covers old text;
        no special editing-state detection is needed here."""
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        cell_type = index.data(CELL_TYPE_ROLE) or self._cell_type

        if cell_type == "date":
            # Plain text editor — user types YYYY-MM-DD directly; no calendar popup.
            ed = QLineEdit(parent)
            ed.setPlaceholderText("YYYY-MM-DD")
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: none; "
                "padding: 0px; margin: 0px; color: #0f172a; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)
            return ed
        
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            # Solid white background: naturally covers old cell text without
            # needing any paint() editing-detection (which doesn't work reliably
            # in PyQt6). setFrame(False) + no border = seamless appearance.
            editor.setFrame(False)
            editor.setAutoFillBackground(True)
            editor.setStyleSheet(
                "QLineEdit { background: #ffffff; border: none; "
                "padding: 0px; margin: 0px; color: #0f172a; }"
            )
            editor.setTextMargins(0, 0, 0, 0)
            editor.setContentsMargins(0, 0, 0, 0)
            if cell_type == "autocomplete":
                data_list = index.data(AUTOCOMPLETE_ITEMS_ROLE) or self._autocomplete_items
                if callable(data_list):
                    data_list = data_list()
                if data_list:
                    completer = _TallyCompleter(data_list, editor)
                    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                    completer.setMaxVisibleItems(12)
                    editor.setCompleter(completer)
                    completer.popup().setMinimumWidth(350)
                    if self._enforce_match:
                        editor.textEdited.connect(
                            lambda text, e=editor, dl=data_list: _enforce_match(e, text, dl)
                        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        """Force the editor to fill the full cell rect with no inset.
        visualRect() gives the raw cell boundary before any stylesheet padding
        is applied. We use it directly so the editor visually becomes the cell,
        regardless of what padding the table stylesheet declares."""
        view = option.widget
        if view is not None and isinstance(editor, QLineEdit):
            editor.setGeometry(view.visualRect(index))
            return
        super().updateEditorGeometry(editor, option, index)

    def setEditorData(self, editor, index):
        cell_type = index.data(CELL_TYPE_ROLE) or self._cell_type
        
        if cell_type == "date" and isinstance(editor, QLineEdit):
            # Pre-fill with whatever text is currently stored in the cell
            val = index.data(Qt.ItemDataRole.DisplayRole) or ""
            editor.setText(str(val))
            return
            
        elif cell_type == "autocomplete":
            display_cb = index.data(DISPLAY_CALLBACK_ROLE) or self._display_cb
            if callable(display_cb):
                display_text = display_cb(index)
                if display_text is not None:
                    editor.setText(str(display_text))
                    return
        
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        cell_type = index.data(CELL_TYPE_ROLE) or self._cell_type
        
        if cell_type == "date" and isinstance(editor, QLineEdit):
            import re as _re
            val = editor.text().strip()
            if val and not _re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    editor.parent(), "गलत फॉर्मेट",
                    f"मिति YYYY-MM-DD फॉर्मेन्ट मा लेख्नुहोस\nExample: 2082-01-15"
                )
                # Keep old value — do not write bad format to model
                return
            model.setData(index, val, Qt.ItemDataRole.EditRole)
            return

        elif cell_type == "autocomplete":
            set_model_cb = index.data(SET_MODEL_DATA_CALLBACK_ROLE) or self._set_model_cb
            if callable(set_model_cb):
                set_model_cb(editor.text(), index)
                return
        
        super().setModelData(editor, model, index)


    def destroyEditor(self, editor, index):
        if self._owner and hasattr(self._owner, '_is_edit_mode'):
            self._owner._is_edit_mode = False
        super().destroyEditor(editor, index)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class ExcelTableMixin:
    """Excel-like Mode 1 / Mode 2 navigation mixin for QTableWidget UIs."""

    def _init_excel_table(self, table):
        self._excel_table = table
        self._is_edit_mode = False

        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | 
                              QAbstractItemView.EditTrigger.AnyKeyPressed | 
                              QAbstractItemView.EditTrigger.EditKeyPressed)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        
        table.setItemDelegate(UniversalCellDelegate(self, table))
        table.installEventFilter(self)

    def _nav_set_current(self, row, col):
        t = self._excel_table
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setCurrentCell(row, col)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | 
                          QAbstractItemView.EditTrigger.AnyKeyPressed | 
                          QAbstractItemView.EditTrigger.EditKeyPressed)

    def eventFilter(self, source, event):
        t = self._excel_table
        if source == t or source == t.viewport():
            if event.type() == QEvent.Type.KeyPress:
                row = t.currentRow()
                col = t.currentColumn()
                key = event.key()

                if self._is_edit_mode:
                    return False

                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
                    new_row, new_col = row, col
                    if key == Qt.Key.Key_Up and row > 0:
                        new_row = row - 1
                    elif key == Qt.Key.Key_Down and row < t.rowCount() - 1:
                        new_row = row + 1
                    elif key == Qt.Key.Key_Left and col > 0:
                        new_col = col - 1
                    elif key == Qt.Key.Key_Right and col < t.columnCount() - 1:
                        new_col = col + 1
                    if new_row != row or new_col != col:
                        self._excel_on_navigate()
                        self._nav_set_current(new_row, new_col)
                    return True

                if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                    return self._excel_on_enter(row, col)

        return super().eventFilter(source, event)

    def _excel_on_navigate(self):
        pass

    def _excel_on_enter(self, row, col):
        t = self._excel_table
        self._excel_on_navigate()
        if row < t.rowCount() - 1:
            self._nav_set_current(row + 1, col)
        return True
