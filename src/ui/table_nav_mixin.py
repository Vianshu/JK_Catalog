"""
ExcelTableMixin — shared Excel-like Mode 1 / Mode 2 navigation for QTableWidget.
"""

import re as _re
from PyQt6.QtWidgets import (QAbstractItemView, QStyledItemDelegate, QLineEdit,
                             QDateEdit, QStyleOptionViewItem, QCompleter, QStyle)
from PyQt6.QtCore import Qt, QEvent, QTimer, QDate, QStringListModel, QSortFilterProxyModel
from PyQt6.QtGui import QKeyEvent

# Custom roles for the universal delegate
CELL_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1          # "date", "number", "autocomplete", or None (text)
AUTOCOMPLETE_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 2 # list of strings or callable
DISPLAY_CALLBACK_ROLE = Qt.ItemDataRole.UserRole + 3   # callable(index) -> str
SET_MODEL_DATA_CALLBACK_ROLE = Qt.ItemDataRole.UserRole + 4 # callable(text, index)

# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Strip spaces and common punctuation for fuzzy completer matching.
    'pvc.bocket-ganga', 'pvc bocket ganga', 'pvcbocketganga' all normalize the same."""
    return _re.sub(r'[\s\.\,\-\_\/\\]', '', text.lower())


class _NormProxyModel(QSortFilterProxyModel):
    """Proxy that normalizes both the typed prefix and list items before comparing,
    so spaces, dots, commas and hyphens are ignored during completion filtering."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix = ""
        # Must call sort() to activate lessThan; without it Qt ignores the method
        # entirely and keeps items in source-model order regardless of type.
        self.sort(0, Qt.SortOrder.AscendingOrder)

    def set_prefix(self, text: str):
        self._prefix = _norm(text)
        self.invalidate()   # invalidate() = re-filter + re-sort; invalidateFilter() alone skips sort

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._prefix:
            return True
        idx = self.sourceModel().index(source_row, 0, source_parent)
        text = self.sourceModel().data(idx) or ""
        return self._prefix in _norm(text)

    def lessThan(self, left, right):
        """Starts-with matches sort above contains-matches."""
        lv = _norm(self.sourceModel().data(left) or "")
        rv = _norm(self.sourceModel().data(right) or "")
        p = self._prefix
        if lv.startswith(p) != rv.startswith(p):
            return lv.startswith(p)
        return lv < rv


class _FirstRowHighlightDelegate(QStyledItemDelegate):
    """Paints popup row 0 with the selection colour — without setCurrentIndex.

    The naive approach (popup.setCurrentIndex(row0)) triggers Qt's internal
    _q_completionSelected slot which calls editor.setText(item), corrupting the
    editor text on every keystroke and making fast-typing / backspace unusable.

    By never touching popup.currentIndex() and painting row 0 as selected here,
    we get a clean visual highlight with zero side-effects on the editor.
    When the user navigates with arrow-keys Qt sets a real currentIndex, so only
    the arrow-selected row gets the native highlight (cur_row >= 0 guard below).
    """

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.row() == 0:
            view = option.widget          # the popup QListView
            cur_row = view.currentIndex().row() if view else -1
            if cur_row < 0:              # no native selection → highlight row 0
                option.state |= (QStyle.StateFlag.State_Selected |
                                 QStyle.StateFlag.State_Active)


class _TallyCompleter(QCompleter):
    """Completer backed by _NormProxyModel for punctuation-insensitive fuzzy matching.

    Behaviour:
    - Typing filters the dropdown via the normalised proxy.
    - Row 0 is always highlighted after every keystroke (via popup.setCurrentIndex).
    - Enter commits the highlighted item; Ctrl+Enter commits the raw typed text.
    """

    def __init__(self, data_list, parent=None):
        super().__init__(parent)
        src = QStringListModel(data_list, self)
        self._proxy = _NormProxyModel(self)
        self._proxy.setSourceModel(src)
        self.setModel(self._proxy)
        self.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._typed_text = ""
        # Install the visual-highlight delegate on the popup once, at construction.
        # This paints row 0 as selected on every repaint — without ever calling
        # popup.setCurrentIndex() which would corrupt the editor text.
        popup = self.popup()
        popup.setItemDelegate(_FirstRowHighlightDelegate(popup))

    def update_prefix(self, text: str):
        """Called from editor.textEdited — only fires on real keystrokes."""
        self._typed_text = text
        self._proxy.set_prefix(text)
        self._highlight_first()   # synchronous — viewport().update() is safe here


    def _highlight_first(self):
        """Trigger a popup repaint so _FirstRowHighlightDelegate re-draws row 0.

        We do NOT call popup.setCurrentIndex() here — that would fire Qt's
        internal _q_completionSelected which calls editor.setText(item) and
        corrupts the editor text.  The delegate handles the visual highlight.
        """
        popup = self.popup()
        if popup and popup.isVisible():
            popup.viewport().update()

    def eventFilter(self, obj, event):
        """Intercept Enter before Qt's QCompleter.eventFilter.

        Qt's base handler CONSUMES Enter when the popup is visible but only emits
        activated if an item is already current in the engine (which fails for
        'contains' matches as explained above).  We handle it explicitly.
        """
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                popup = self.popup()
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                if popup and popup.isVisible():
                    # Read current visual selection BEFORE hiding (index is cleared on hide)
                    cur_idx = popup.currentIndex()
                    popup.hide()
                    if not ctrl and self._proxy.rowCount() > 0:
                        # Read text from popup's view-level current index (always correct)
                        # NOT from currentCompletion() which uses the broken engine.
                        top_text = None
                        if cur_idx.isValid():
                            top_text = popup.model().data(cur_idx, Qt.ItemDataRole.DisplayRole)
                        if not top_text:   # safety: nothing was highlighted, use proxy row 0
                            top_text = self._proxy.data(
                                self._proxy.index(0, 0), Qt.ItemDataRole.DisplayRole)
                        if top_text:
                            self.activated.emit(top_text)
                            return True   # consumed
                    return False          # no match or Ctrl: pass to delegate
        return super().eventFilter(obj, event)

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
                    completer.setMaxVisibleItems(12)
                    editor.setCompleter(completer)
                    completer.popup().setMinimumWidth(350)
                    # Drive the normalized proxy filter as the user types.
                    # textEdited (not textChanged) so completer's setText() doesn't re-trigger.
                    editor.textEdited.connect(completer.update_prefix)
                    if self._enforce_match:
                        editor.textEdited.connect(
                            lambda text, e=editor, dl=data_list: _enforce_match(e, text, dl)
                        )
                    # activated fires for both explicit selection AND the auto-highlighted
                    # first item when user presses Enter without navigating.
                    # As requested, we now ALWAYS use the selected item if the dropdown is visible.
                    # Free typing is achieved by Ctrl+Enter (handled via eventFilter) or if no matches.
                    def _on_activated(selected, e=editor, c=completer):
                        # Update _typed_text immediately so any pending _do_restore
                        # singleShot reads this value and becomes a no-op (text already
                        # matches → widget.text() == c._typed_text → no revert).
                        c._typed_text = selected
                        e.setText(selected)
                        QTimer.singleShot(0, lambda: self._commit_and_move(e))
                    completer.activated.connect(_on_activated)
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

        # F2 / Edit Mode: schedule cursor-at-end BEFORE any early returns so it applies
        # to date, autocomplete, and plain text cells alike.
        # singleShot(0) runs after Qt's own selectAll() so it always wins.
        _f2_active = isinstance(editor, QLineEdit) and getattr(self._owner, '_is_edit_mode', False)
        if _f2_active:
            # Double-deferred: Qt's QLineEdit.focusInEvent schedules selectAll() via singleShot(0)
            # AFTER setEditorData returns (editor hasn't gained focus yet).  A nested singleShot
            # means our deselect runs one tick later, so it always wins.
            def _deferred_cursor(e=editor):
                def _apply():
                    try:
                        e.deselect()
                        e.setCursorPosition(len(e.text()))
                    except RuntimeError:
                        pass  # editor already destroyed — safe to ignore
                QTimer.singleShot(0, _apply)
            QTimer.singleShot(0, _deferred_cursor)

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

    def eventFilter(self, obj, event):
        """Handle key events for the editor.

        Ctrl+Enter: set bypass flag and commit typed text as-is (no fuzzy match).
        Plain Enter + popup visible: return False WITHOUT calling super().
            The delegate is installed LAST (runs FIRST in LIFO order).
            QStyledItemDelegate.eventFilter commits the editor and returns False.
            By the time _TallyCompleter.eventFilter runs, the editor is already
            closed → activated fires into a dead editor → nothing is saved.
            By returning False here we skip the delegate commit entirely, letting
            _TallyCompleter.eventFilter commit the correct highlighted item.
        Plain Enter + no popup: fall through to super() (QStyledItemDelegate commits).
        """
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                if ctrl:
                    # Ctrl+Enter: bypass flag → commit typed text via QStyledItemDelegate
                    if self._owner and hasattr(self._owner, '_bypass_fuzzy_match'):
                        self._owner._bypass_fuzzy_match = True
                    plain = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                      Qt.KeyboardModifier.NoModifier)
                    # Capture row/col BEFORE committing, so any synchronous navigation
                    # triggered by itemChanged (e.g. handle_item_changed) doesn't change
                    # what _excel_on_enter sees as the origin cell.
                    t = getattr(self._owner, '_excel_table', None)
                    r = t.currentRow() if t else -1
                    c = t.currentColumn() if t else 0

                    result = super().eventFilter(obj, plain)
                    if self._owner and hasattr(self._owner, '_bypass_fuzzy_match'):
                        self._owner._bypass_fuzzy_match = False
                    
                    # For ExcelTableMixin tables (Godown, ChequeList, …) trigger
                    # column-aware navigation — same as _commit_and_move does for
                    # normal Enter.  _SectionCard (supp_payment) has no
                    # _excel_on_enter so it is unaffected.
                    owner = self._owner
                    if t and owner and hasattr(owner, '_excel_on_enter'):
                        QTimer.singleShot(
                            15,
                            lambda r=r, c=c: owner._excel_on_enter(r, c))
                    return result
                else:
                    # Plain Enter
                    if isinstance(obj, QLineEdit):
                        c_obj = obj.completer()
                        # If popup is visible, hand off to _TallyCompleter.eventFilter
                        if c_obj and c_obj.popup() and c_obj.popup().isVisible():
                            return False  # skip delegate; completer runs next (LIFO)
                    
                    # Popup is closed (or no completer) → commit and navigate
                    t = getattr(self._owner, '_excel_table', None)
                    r = t.currentRow() if t else -1
                    c = t.currentColumn() if t else 0
                    
                    result = super().eventFilter(obj, event)
                    
                    owner = self._owner
                    if t and owner and hasattr(owner, '_excel_on_enter'):
                        QTimer.singleShot(15, lambda r=r, c=c: owner._excel_on_enter(r, c))
                    return result

        return super().eventFilter(obj, event)

    def setModelData(self, editor, model, index):
        cell_type = index.data(CELL_TYPE_ROLE) or self._cell_type

        if cell_type == "date" and isinstance(editor, QLineEdit):
            import re as _re
            val = editor.text().strip()
            if val and not _re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    editor.parent(), "गलत फोर्मेट",
                    f"मिति YYYY-MM-DD फोर्मेन्ट मा लेख्नुहोस\nExample: 2082-01-15"
                )
                return
            model.setData(index, val, Qt.ItemDataRole.EditRole)
            return

        elif cell_type == "autocomplete":
            # Ctrl+Enter bypass: save exactly what was typed — skip GUID lookup and normalization
            if getattr(self._owner, '_bypass_fuzzy_match', False):
                raw = editor.text().strip() if isinstance(editor, QLineEdit) else ""
                model.setData(index, raw, Qt.ItemDataRole.EditRole)
                return
            set_model_cb = index.data(SET_MODEL_DATA_CALLBACK_ROLE) or self._set_model_cb
            if callable(set_model_cb):
                set_model_cb(editor.text(), index)
                return
        
        super().setModelData(editor, model, index)


    def destroyEditor(self, editor, index):
        if self._owner and hasattr(self._owner, '_is_edit_mode'):
            self._owner._is_edit_mode = False
        super().destroyEditor(editor, index)

    def _commit_and_move(self, editor):
        """Commit the editor and trigger Enter navigation after a dropdown selection.
        This eliminates the 'double Enter' issue — one action commits and moves cursor."""
        from PyQt6.QtWidgets import QStyledItemDelegate
        
        # Capture row/col BEFORE committing, so any synchronous navigation
        # triggered by itemChanged (e.g. handle_item_changed) doesn't change
        # what _excel_on_enter sees as the origin cell.
        t = getattr(self._owner, '_excel_table', None)
        r = t.currentRow() if t else -1
        c = t.currentColumn() if t else 0
        
        # Guard: editor may already be closed by the time singleShot fires
        try:
            self.commitData.emit(editor)
            # Use SubmitModelCache so _SectionCard._on_editor_close_for_nav fires for navigation.
            # For Godown/cheque, this hint is irrelevant — navigation is handled by _excel_on_enter.
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.SubmitModelCache)
        except RuntimeError:
            return
            
        # Trigger Godown / cheque list Enter-column routing (ExcelTableMixin tables)
        owner = self._owner
        if t and owner and hasattr(owner, '_excel_on_enter'):
            QTimer.singleShot(15, lambda r=r, c=c: owner._excel_on_enter(r, c))


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

                # F2 = Edit Mode: open editor without clearing text, cursor at end
                if key == Qt.Key.Key_F2:
                    self._is_edit_mode = True
                    # Fall through to Qt's default which opens the editor via EditKeyPressed

                if self._is_edit_mode and key != Qt.Key.Key_F2:
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
