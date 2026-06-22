"""
ExcelTableMixin — shared Excel-like Mode 1 / Mode 2 navigation for QTableWidget.

Usage
-----
1.  Inherit BEFORE QWidget:

        class MyUI(ExcelTableMixin, QWidget):
            ...

2.  Call _init_excel_table(table) inside init_ui(), AFTER creating the
    QTableWidget.  This sets DoubleClicked trigger, SingleSelection, the
    light-blue selection style, a _NavResetDelegate, and installs the
    event filter.

        def init_ui(self):
            self.table = QTableWidget(...)
            ...
            self._init_excel_table(self.table)
            # Optionally override the delegate afterwards:
            # self.table.setItemDelegate(MyDelegate(self))

3.  Override the navigation hooks as needed:

        _excel_on_double_click(row, col)    — default: track state + cursor
        _excel_on_printable_key(row, col, text) — default: clear + open editor
        _excel_on_enter(row, col)           — default: move selection down
        _excel_on_navigate()                — called before every navigation;
                                              override for cleanup (e.g. col-0
                                              overlay editors in GodownListUI)

Mode 1 (Selected)
    Single click → cell highlighted (no editor)
    Arrow keys   → navigate cells
    Enter        → move down (override for custom behaviour)
    Printable    → open editor, clear, type first char (override to restrict)

Mode 2 (Edit)
    Double-click → editor opens; cursor placed at end
    Any key      → editor handles it natively
    Escape       → Qt reverts model data; editor closes; Mode 1 restored
    Editor close → _NavResetDelegate.destroyEditor() resets _is_edit_mode

IMPORTANT — setCurrentCell and CurrentChanged
    Qt fires the CurrentChanged edit trigger whenever setCurrentCell() is
    called, regardless of the configured EditTrigger.  _nav_set_current()
    wraps every programmatic navigation call with a NoEditTriggers guard
    so that no editor opens accidentally.
"""

from PyQt6.QtWidgets import QAbstractItemView, QStyledItemDelegate, QLineEdit
from PyQt6.QtCore import Qt, QEvent, QTimer


# ---------------------------------------------------------------------------
# Delegate — resets _is_edit_mode when Qt closes any editor
# ---------------------------------------------------------------------------

class _NavResetDelegate(QStyledItemDelegate):
    """Minimal delegate whose only purpose is to reset _is_edit_mode on
    editor close.  Used as the default delegate by ExcelTableMixin.
    Replace with a richer delegate if needed (that delegate should also
    reset owner._is_edit_mode in its own destroyEditor)."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner

    def destroyEditor(self, editor, index):
        self._owner._is_edit_mode = False   # Exit Mode 2
        super().destroyEditor(editor, index)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class ExcelTableMixin:
    """Excel-like Mode 1 / Mode 2 navigation mixin for QTableWidget UIs."""

    # ── initialisation ──────────────────────────────────────────────────────

    def _init_excel_table(self, table):
        """Call in init_ui() after creating the QTableWidget."""
        self._excel_table = table
        self._is_edit_mode = False          # True = Mode 2, False = Mode 1

        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: #CCE8FF;
                color: #1a1a1a;
            }
        """)
        # Default delegate — can be replaced by calling setItemDelegate() after
        # this call (the replacement must also reset _is_edit_mode in destroyEditor).
        table.setItemDelegate(_NavResetDelegate(self, table))
        table.installEventFilter(self)
        table.cellDoubleClicked.connect(self._excel_on_double_click)

    # ── safe navigation helper ──────────────────────────────────────────────

    def _nav_set_current(self, row, col):
        """setCurrentCell guarded against the CurrentChanged edit trigger.

        Qt fires CurrentChanged (and therefore opens an editor) whenever
        setCurrentCell() is called, even when DoubleClicked is the only
        configured trigger.  Disabling all triggers for the duration of the
        call prevents this."""
        t = self._excel_table
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setCurrentCell(row, col)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)

    # ── event filter ────────────────────────────────────────────────────────

    def eventFilter(self, source, event):
        t = self._excel_table
        if source == t and event.type() == QEvent.Type.KeyPress:
            row = t.currentRow()
            col = t.currentColumn()
            key = event.key()

            # ── Mode 2: editor open — pass everything through ──
            if self._is_edit_mode:
                return False

            # ── Mode 1 ──────────────────────────────────────────

            # Arrow keys → navigate
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                       Qt.Key.Key_Left, Qt.Key.Key_Right):
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

            # Enter / Return → subclass hook
            if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                return self._excel_on_enter(row, col)

            # Printable key → subclass hook
            text = event.text()
            if text and text.isprintable():
                return self._excel_on_printable_key(row, col, text)

        return super().eventFilter(source, event)

    # ── overridable hooks ───────────────────────────────────────────────────

    def _excel_on_navigate(self):
        """Called before every programmatic navigation (arrows + Enter).
        Override to commit / clean up any special overlay editors."""
        pass

    def _excel_on_enter(self, row, col):
        """Enter key in Mode 1.  Default: move selection one row down."""
        t = self._excel_table
        self._excel_on_navigate()
        if row < t.rowCount() - 1:
            self._nav_set_current(row + 1, col)
        return True

    def _excel_on_double_click(self, row, col):
        """Double-click -> Mode 2.
        Qt's DoubleClicked trigger already opened the editor before this
        signal fires.  We just track state and position the cursor at end."""
        t = self._excel_table
        item = t.item(row, col)
        if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
            self._is_edit_mode = True
            QTimer.singleShot(0, lambda: (
                t.focusWidget().end(False)
                if isinstance(t.focusWidget(), QLineEdit) else None
            ))

    def _excel_on_printable_key(self, row, col, text):
        """Printable key in Mode 1.
        Default: open editor (keeping item value for Escape restore),
        then clear the editor widget and type the first character."""
        t = self._excel_table
        item = t.item(row, col)
        if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
            self._is_edit_mode = True
            t.editItem(item)
            _t = text
            QTimer.singleShot(0, lambda: self._excel_set_editor_text(_t))
            return True
        return False

    def _excel_set_editor_text(self, text):
        """After the editor is focused, clear it and type the first char."""
        editor = self._excel_table.focusWidget()
        if isinstance(editor, QLineEdit):
            editor.clear()
            editor.setText(text)
            editor.end(False)
