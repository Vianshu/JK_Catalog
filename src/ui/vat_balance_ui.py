"""
VAT Working — Balance Screen.

Contains 4 views switchable via sidebar Left Panel:
1. Int. Ledger (Sundry Debtors from Internal Company row_ledger_data)
2. Vat Ledger (Sundry Debtors from configured VAT company) + VAT Company config bar
3. Mapping (VAT Ledger <-> Internal Ledger match with autocomplete, unmatched shown at top in red)
4. Vat Conf. (Debtor & Creditor tabs with 10 compact columns, editable cartoon numbers, flexible Yes/No input)
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTabWidget, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QProgressDialog,
    QMessageBox, QLineEdit, QStyledItemDelegate, QAbstractItemView, QTabBar,
    QDialog, QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings, QEvent
from PyQt6.QtGui import QColor, QFont, QIcon

from src.logic.db_manager import get_db_manager, build_logical_name
from src.logic.vat_manager import (
    get_active_vat_company, load_internal_debtors, load_vat_debtors,
    load_vat_mappings, save_manual_mapping, get_internal_debtor_names,
    get_vat_debtor_names, load_vat_conf_table_data, save_vat_conf_field,
    check_amount_match, ensure_vat_tables, normalize_yes_no, validate_cartoon_number
)
from src.services.tally_sync import fetch_tally_vat_internal_data, fetch_tally_vat_ledger_data, TallyService
from src.ui.vat_company_dialog import VatCompanyDialog
from src.ui.table_nav_mixin import UniversalCellDelegate, UNIVERSAL_TABLE_STYLE, _TallyCompleter
from src.ui.settings import load_crm_list
from src.utils.app_logger import get_logger
from src.utils.path_utils import get_icon

logger = get_logger(__name__)


# ── Background Worker for non-blocking data load ─────────────────────
class _VatBalanceLoadWorker(QThread):
    """Fetches all VAT Balance data off the main thread.

    Emits `finished` with a dict of results when done, or `error` with the
    exception message on failure.  The UI thread picks up the signal and
    populates tables — keeping the window responsive throughout.
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db_name: str, vat_company: str, parent=None):
        super().__init__(parent)
        self._db_name = db_name
        self._vat_company = vat_company

    def run(self):
        try:
            int_debtors = load_internal_debtors(self._db_name)
            vat_debtors = load_vat_debtors(self._db_name, self._vat_company) if self._vat_company else []
            mappings = load_vat_mappings(self._db_name, self._vat_company) if self._vat_company else []
            debtor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Debtor") if self._vat_company else []
            creditor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Creditor") if self._vat_company else []

            self.finished.emit({
                "int_debtors": int_debtors,
                "vat_debtors": vat_debtors,
                "mappings": mappings,
                "debtor_conf": debtor_conf,
                "creditor_conf": creditor_conf,
            })
        except Exception as e:
            logger.error(f"[_VatBalanceLoadWorker] error: {e}", exc_info=True)
            self.error.emit(str(e))


# Authentic columns directly from Tally Ledger + Commercial Sales, Purchase, Receipts, Payments
TALLY_LEDGER_COLUMNS = [
    ("Name", "Ledger Name", 250, False),
    ("Group", "Group", 130, False),
    ("Opening_Balance", "Opening Balance", 120, True),
    ("Sales_Amount", "Sales", 120, True),
    ("Purchase_Amount", "Purchase", 120, True),
    ("Receipt_Amount", "Receipts", 120, True),
    ("Payment_Amount", "Payments", 120, True),
    ("Closing_Balance", "Closing Balance", 120, True),
    ("CashOutFlow", "Cash Outflow", 130, True),
    ("CashInFlow", "Cash Inflow", 120, True),
    ("Pan_No.", "Pan No.", 120, False),
    ("Phone", "Phone", 110, False),
    ("Mobile", "Mobile", 110, False),
    ("Address", "Address", 220, False),
    ("Alias", "Alias", 130, False),
    ("Contact_Person", "Contact Person", 140, False),
    ("Sub_Group", "Sub Group", 150, False),
    ("Credit_Limit", "Credit Limit", 110, True),
    ("Overdue_Bills", "Overdue Bills", 110, True),
    ("On_Account_Value", "On Account Value", 120, True),
    ("Performance", "Performance", 100, True),
    ("This_Qtr_Balance", "This Qtr Balance", 120, True),
    ("Prev_Qtr_Balance", "Prev Qtr Balance", 120, True),
    ("BillwiseOn", "Billwise On", 90, True),
]


class LedgerColumnSettingsDialog(QDialog):
    """Allows user to select which columns to display in Int. and VAT Ledger tables."""

    DEFAULT_COLUMNS = {
        "Name", "Group", "Opening_Balance",
        "Sales_Amount", "Purchase_Amount", "Receipt_Amount", "Payment_Amount",
        "Closing_Balance"
    }

    def __init__(self, current_visible: set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Visible Columns")
        self.setMinimumWidth(380)
        self.setStyleSheet("""
            QDialog { background: #ffffff; }
            QLabel { font-size: 13px; color: #0f172a; }
            QCheckBox { font-size: 12px; color: #334155; padding: 4px 0; }
            QCheckBox:hover { color: #059669; }
            QPushButton {
                font-size: 12px; font-weight: 600; border-radius: 4px; padding: 6px 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Select Columns to Display:")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")
        layout.addWidget(title)

        # Quick preset buttons
        preset_bar = QHBoxLayout()
        btn_preset_def = QPushButton("Default View")
        btn_preset_def.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        btn_preset_all = QPushButton("Show All")
        btn_preset_all.setStyleSheet("background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;")
        preset_bar.addWidget(btn_preset_def)
        preset_bar.addWidget(btn_preset_all)
        preset_bar.addStretch()
        layout.addLayout(preset_bar)

        # Scroll area with checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; border-radius: 4px; }")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)

        self.checkboxes = {}
        for col_key, col_title, _, _ in TALLY_LEDGER_COLUMNS:
            cb = QCheckBox(col_title)
            cb.setChecked(col_key in current_visible)
            if col_key == "Name":
                cb.setChecked(True)
                cb.setEnabled(False)
            self.checkboxes[col_key] = cb
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        btn_preset_def.clicked.connect(self._select_default)
        btn_preset_all.clicked.connect(self._select_all)

        # Bottom buttons: Save / Cancel
        btn_box = QHBoxLayout()
        btn_save = QPushButton("Save & Apply")
        btn_save.setStyleSheet("background: #059669; color: #ffffff; border: none;")
        btn_save.clicked.connect(self.accept)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1;")
        btn_cancel.clicked.connect(self.reject)

        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def _select_default(self):
        for k, cb in self.checkboxes.items():
            if k == "Name":
                continue
            cb.setChecked(k in self.DEFAULT_COLUMNS)

    def _select_all(self):
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def get_selected_columns(self) -> set:
        selected = {"Name"}
        for k, cb in self.checkboxes.items():
            if cb.isChecked():
                selected.add(k)
        return selected


# ─── WORKER THREADS ──────────────────────────────────────────────────────────

class _InternalLedgerWorker(QThread):
    finished = pyqtSignal(int, str)

    def __init__(self, company_name, path, service):
        super().__init__()
        self.company_name = company_name
        self.path = path
        self.service = service

    def run(self):
        try:
            rc, err = fetch_tally_vat_internal_data(
                company_name=self.company_name,
                company_path=self.path,
                service=self.service
            )
            self.finished.emit(rc or 0, err or "")
        except Exception as e:
            self.finished.emit(0, str(e))


class _VatLedgerWorker(QThread):
    finished = pyqtSignal(int, str)

    def __init__(self, vat_company, company_name, path, service):
        super().__init__()
        self.vat_company = vat_company
        self.company_name = company_name
        self.path = path
        self.service = service

    def run(self):
        try:
            rc, err = fetch_tally_vat_ledger_data(
                vat_company_name=self.vat_company,
                company_name=self.company_name,
                company_path=self.path,
                service=self.service
            )
            self.finished.emit(rc or 0, err or "")
        except Exception as e:
            self.finished.emit(0, str(e))


# ─── CUSTOM DELEGATES & CONTROLS ─────────────────────────────────────────────

class MappingItemDelegate(UniversalCellDelegate):
    """Delegate for Mapping table: provides seamless in-cell QLineEdit editing with
    searchable _TallyCompleter for both VAT Ledger (Col 0) and Internal Ledger (Col 1),
    and editable text for Manual Name (Col 2). Paints unmapped rows fully in red.
    """
    def __init__(self, get_vat_options_callback, get_int_options_callback, parent_table=None, parent=None):
        super().__init__(parent=parent)
        self.get_vat_options_callback = get_vat_options_callback
        self.get_int_options_callback = get_int_options_callback
        self.parent_table = parent_table

    def paint(self, painter, option, index):
        # Full row must be marked red if either VAT or Internal ledger cell is empty
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
        table = self.parent_table or (self.parent() if isinstance(self.parent(), QAbstractItemView) else None)
        if table and hasattr(table, '_can_edit') and not table._can_edit:
            return None

        col = index.column()
        if col in (0, 1):  # VAT Ledger (0) or Internal Ledger (1)
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
            editor.setText(index.data() or "")
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            model.setData(index, editor.text().strip(), Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class VatConfDelegate(UniversalCellDelegate):
    """Delegate for Vat Conf table:

    - SN.: seamless centered QLineEdit
    - Did You Print / Get Back: seamless centered QLineEdit normalizing 1/0, Y/N, T/F
    - CRM: seamless QLineEdit with _TallyCompleter
    - Opening ? / Closing ?: right-aligned numeric QLineEdit
    """
    def __init__(self, get_crm_callback, parent=None):
        super().__init__(parent=parent)
        self.get_crm_callback = get_crm_callback

    def paint(self, painter, option, index):
        # Paint full row in solid red if expected opening or closing does not match actual amount
        # Empty expected fields are NOT considered mismatches (check_amount_match returns True for empty)
        model = index.model()
        row = index.row()
        act_op_str = (model.data(model.index(row, 2), Qt.ItemDataRole.DisplayRole) or "").replace(",", "").strip()
        act_cl_str = (model.data(model.index(row, 3), Qt.ItemDataRole.DisplayRole) or "").replace(",", "").strip()
        exp_op = (model.data(model.index(row, 8), Qt.ItemDataRole.DisplayRole) or "").strip()
        exp_cl = (model.data(model.index(row, 9), Qt.ItemDataRole.DisplayRole) or "").strip()

        try:
            act_op = float(act_op_str) if act_op_str else 0.0
        except ValueError:
            act_op = 0.0

        try:
            act_cl = float(act_cl_str) if act_cl_str else 0.0
        except ValueError:
            act_cl = 0.0

        op_matches = check_amount_match(act_op, exp_op)
        cl_matches = check_amount_match(act_cl, exp_cl)

        is_mismatch = not (op_matches and cl_matches)

        if is_mismatch:
            painter.save()
            painter.fillRect(option.rect, QColor("#fecaca"))
            painter.restore()

        super().paint(painter, option, index)

    def _commit_and_close(self, editor):
        table = self.parent()
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
        table = self.parent()
        if table and hasattr(table, '_can_edit') and not table._can_edit:
            return None

        col = index.column()
        ed = QLineEdit(parent)
        ed.setFrame(False)
        ed.setAutoFillBackground(True)
        ed.setStyleSheet(
            "QLineEdit { background: #ffffff; border: 1px solid #059669; "
            "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
        )
        ed.setTextMargins(0, 0, 0, 0)
        ed.setContentsMargins(0, 0, 0, 0)

        if col in (0, 4, 5, 7):
            ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif col in (2, 3, 8, 9):
            ed.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            ed.setAlignment(Qt.AlignmentFlag.AlignLeft)

        if col in (5, 7):
            ed.setPlaceholderText("Y/N or 1/0")
        elif col == 6:  # CRM autocomplete
            crms = self.get_crm_callback() or []
            completer = _TallyCompleter(crms, ed)
            completer.setMaxVisibleItems(10)
            completer.popup().setMinimumWidth(240)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_crm_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_crm_activated)

        return ed

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
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            col = index.column()
            val = editor.text().strip()
            if col in (5, 7):
                val = normalize_yes_no(val)
            model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class VatConfTableWidget(QTableWidget):
    """QTableWidget with spacebar toggle for Did You Print (Col 5) and Get Back (Col 7)."""
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.state() != QTableWidget.State.EditingState:
            col = self.currentColumn()
            row = self.currentRow()
            if col in (5, 7) and row >= 0:
                item = self.item(row, col)
                if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    cur_val = (item.text() or "").strip()
                    new_val = "No" if cur_val.lower() in ("yes", "y", "1", "t", "true") else "Yes"
                    item.setText(new_val)
                    return
        super().keyPressEvent(event)


TABLE_WITH_FOOTER_STYLE = UNIVERSAL_TABLE_STYLE + """
QTableWidget {
    border-bottom: none;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
"""

FOOTER_TABLE_STYLE = """
QTableWidget {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-top: 2px solid #059669;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 0px;
    gridline-color: #64748b;
    font-family: 'Segoe UI';
    font-size: 10pt;
}
QTableWidget::item {
    padding: 2px 4px;
    font-weight: bold;
    color: #0f172a;
}
"""


class TableFooterWidget(QTableWidget):
    """Pinned single-row footer table displaying column-aligned grand totals."""

    def __init__(self, main_table: QTableWidget, parent=None):
        super().__init__(1, main_table.columnCount(), parent)
        self.main_table = main_table
        self.setStyleSheet(FOOTER_TABLE_STYLE)
        self.setFixedHeight(30)
        self.setRowHeight(0, 28)
        self.horizontalHeader().setVisible(False)
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        # Synchronize horizontal scrolling
        self.main_table.horizontalScrollBar().valueChanged.connect(
            self.horizontalScrollBar().setValue
        )
        self.main_table.horizontalScrollBar().rangeChanged.connect(
            lambda min_v, max_v: self.horizontalScrollBar().setRange(min_v, max_v)
        )

        # Synchronize column resize
        self.main_table.horizontalHeader().sectionResized.connect(
            self._on_section_resized
        )

        # Synchronize column movement if applicable
        self.main_table.horizontalHeader().sectionMoved.connect(
            self._on_section_moved
        )

        self.sync_columns()

    def _on_section_resized(self, logical_index: int, old_size: int, new_size: int):
        self.setColumnWidth(logical_index, new_size)

    def _on_section_moved(self, logical_index: int, old_visual: int, new_visual: int):
        self.horizontalHeader().moveSection(old_visual, new_visual)

    def sync_columns(self):
        self.blockSignals(True)
        col_count = self.main_table.columnCount()
        self.setColumnCount(col_count)
        for c in range(col_count):
            self.setColumnWidth(c, self.main_table.columnWidth(c))
            self.setColumnHidden(c, self.main_table.isColumnHidden(c))
        self.horizontalScrollBar().setValue(self.main_table.horizontalScrollBar().value())
        self.blockSignals(False)

    def wheelEvent(self, event):
        self.main_table.wheelEvent(event)

    def update_totals(self, col_values: dict[int, str], label_col: int = 0, label_text: str = "Grand Total"):
        """Populate column totals.

        col_values: {col_index: formatted_string}
        """
        self.blockSignals(True)
        col_count = self.columnCount()
        for c in range(col_count):
            item = self.item(0, c)
            if not item:
                item = QTableWidgetItem()
                self.setItem(0, c, item)

            item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))

            if c == label_col:
                item.setText(label_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor("#0f172a"))
            elif c in col_values:
                item.setText(col_values[c])
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor("#047857"))
            else:
                item.setText("")
        self.blockSignals(False)


class TableFooterContainer(QWidget):
    """Container holding TableFooterWidget with a right-hand spacer that dynamically
    matches the width of the main table's vertical scrollbar to guarantee exact
    column alignment.
    """

    def __init__(self, main_table: QTableWidget, footer: TableFooterWidget, parent=None):
        super().__init__(parent)
        self.main_table = main_table
        self.footer = footer

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(footer, stretch=1)

        self.spacer = QWidget()
        self.spacer.setFixedWidth(0)
        self.spacer.setFixedHeight(30)
        self.spacer.setStyleSheet("""
            background-color: #f8fafc;
            border-top: 2px solid #059669;
            border-bottom: 1px solid #cbd5e1;
            border-right: 1px solid #cbd5e1;
            border-bottom-right-radius: 6px;
        """)
        self.spacer.hide()
        layout.addWidget(self.spacer)

        # Connect vertical scrollbar changes
        main_table.verticalScrollBar().rangeChanged.connect(self._sync_spacer)
        main_table.installEventFilter(self)

    def _sync_spacer(self, *args):
        sb = self.main_table.verticalScrollBar()
        if sb.isVisible() and sb.maximum() > 0:
            w = sb.width()
            if w <= 0:
                w = sb.sizeHint().width()
            self.spacer.setFixedWidth(max(w, 0))
            self.spacer.show()
        else:
            self.spacer.setFixedWidth(0)
            self.spacer.hide()

    def eventFilter(self, obj, event):
        if obj == self.main_table:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
                QTimer.singleShot(0, self._sync_spacer)
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_spacer()
        if hasattr(self, 'footer'):
            self.footer.sync_columns()


# ─── MAIN BALANCE SCREEN ─────────────────────────────────────────────────────

class BalanceUI(QWidget):
    """Main Balance page for VAT Working.

    The 4 views (Int. Ledger, Vat Ledger, Mapping, Vat Conf.) are switched
    directly via the left panel sidebar menu.
    """
    def __init__(self):
        super().__init__()
        self.setObjectName("BalanceContainer")
        self.db = get_db_manager()
        self.current_company_path = ""
        self.current_company_name = ""
        self.db_name = ""
        self.active_vat_company = ""
        self._can_edit = True
        self._load_worker = None          # background data fetch thread
        self._last_loaded_path = None     # dedup guard: skip reload if path unchanged
        self._loading_path = None         # tracks path currently being fetched

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── Main Tabs (inside screen) ──────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("BalanceTabs")
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

        # Tab 0: Int. Ledger
        self.int_ledger_widget = self._create_int_ledger_tab()
        self.tabs.addTab(self.int_ledger_widget, "Int. Ledger")

        # Sync button logo to the right of Int. Ledger tab
        self.btn_tab_sync_int = QPushButton()
        self.btn_tab_sync_int.setObjectName("TabSyncIntBtn")
        self.btn_tab_sync_int.setIcon(get_icon("sync.svg"))
        self.btn_tab_sync_int.setIconSize(QSize(15, 15))
        self.btn_tab_sync_int.setFixedSize(22, 22)
        self.btn_tab_sync_int.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_sync_int.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                padding: 0px;
                margin-left: 2px;
                margin-right: 4px;
            }
            QPushButton:hover {
                background: #e2e8f0;
                border-radius: 11px;
            }
        """)
        self.btn_tab_sync_int.clicked.connect(self.sync_int_ledger)
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, self.btn_tab_sync_int)

        # Tab 1: Vat Ledger (includes active VAT company config)
        self.vat_ledger_widget = self._create_vat_ledger_tab()
        self.tabs.addTab(self.vat_ledger_widget, "Vat Ledger")

        # Sync button logo to the right of Vat Ledger tab
        self.btn_tab_sync_vat = QPushButton()
        self.btn_tab_sync_vat.setObjectName("TabSyncVatBtn")
        self.btn_tab_sync_vat.setIcon(get_icon("sync.svg"))
        self.btn_tab_sync_vat.setIconSize(QSize(15, 15))
        self.btn_tab_sync_vat.setFixedSize(22, 22)
        self.btn_tab_sync_vat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_sync_vat.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                padding: 0px;
                margin-left: 2px;
                margin-right: 4px;
            }
            QPushButton:hover {
                background: #e2e8f0;
                border-radius: 11px;
            }
        """)
        self.btn_tab_sync_vat.clicked.connect(self.sync_vat_ledger)
        self.tabs.tabBar().setTabButton(1, QTabBar.ButtonPosition.RightSide, self.btn_tab_sync_vat)

        # Tab 2: Mapping (clean, uncluttered, unmatched in red at top)
        self.mapping_widget = self._create_mapping_tab()
        self.tabs.addTab(self.mapping_widget, "Mapping")

        # Tab 3: Vat Conf. (with Debtor and Creditor sub-tabs)
        self.vat_conf_widget = self._create_vat_conf_tab()
        self.tabs.addTab(self.vat_conf_widget, "Vat Conf.")

        layout.addWidget(self.tabs, stretch=1)

    def _create_vat_conf_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(6)

        self.conf_tabs = QTabWidget()
        self.conf_tabs.setObjectName("VatConfTabs")
        self.conf_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e2e8f0;
                background: #ffffff;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f8fafc;
                color: #64748b;
                font-weight: 600;
                font-size: 12px;
                padding: 6px 16px;
                margin-right: 3px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #e2e8f0;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
                font-weight: 700;
                border-bottom: 2px solid #059669;
            }
            QTabBar::tab:hover:!selected {
                background: #f1f5f9;
                color: #334155;
            }
        """)

        self.debtor_widget = self._create_debtor_tab()
        self.conf_tabs.addTab(self.debtor_widget, "Debtor")

        self.creditor_widget = self._create_creditor_tab()
        self.conf_tabs.addTab(self.creditor_widget, "Creditor")

        vbox.addWidget(self.conf_tabs, stretch=1)
        return widget

    def set_current_view(self, index: int):
        """Switch active tab (0: Int, 1: Vat, 2: Mapping, 3: Debtor, 4: Creditor)."""
        if index in (0, 1, 2):
            self.tabs.setCurrentIndex(index)
        elif index == 3:
            self.tabs.setCurrentIndex(3)
            if hasattr(self, 'conf_tabs'):
                self.conf_tabs.setCurrentIndex(0)
        elif index == 4:
            self.tabs.setCurrentIndex(3)
            if hasattr(self, 'conf_tabs'):
                self.conf_tabs.setCurrentIndex(1)

    # ── TAB / VIEW CREATION HELPERS ──────────────────────────────────

    def _create_int_ledger_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Search + Sync
        # Top Bar: Search + Sync + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("Internal Ledger")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_int_count = QLabel("")
        self.lbl_int_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.int_search = QLineEdit()
        self.int_search.setPlaceholderText("Filter ledger name...")
        self.int_search.setFixedWidth(220)
        self.int_search.textChanged.connect(self._filter_int_table)

        self.btn_sync_int = QPushButton("Sync Int. Ledger")
        self.btn_sync_int.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600;
                border: none; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_sync_int.clicked.connect(self.sync_int_ledger)

        self.btn_cols_int = QPushButton("Columns ⚙")
        self.btn_cols_int.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_cols_int.clicked.connect(self.open_column_settings_dialog)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_int_count)
        top_bar.addStretch()
        top_bar.addWidget(self.int_search)
        top_bar.addWidget(self.btn_cols_int)
        top_bar.addWidget(self.btn_sync_int)
        vbox.addLayout(top_bar)

        # Table with all authentic columns from Tally Ledger Rows
        self.int_table = QTableWidget()
        self.int_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.int_table.setAlternatingRowColors(True)
        self.int_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.int_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.int_table.verticalHeader().setVisible(False)
        self.int_table.setItemDelegate(UniversalCellDelegate(self.int_table))

        headers = [c[1] for c in TALLY_LEDGER_COLUMNS]
        self.int_table.setColumnCount(len(headers))
        self.int_table.setHorizontalHeaderLabels(headers)

        header = self.int_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for idx, col in enumerate(TALLY_LEDGER_COLUMNS):
            self.int_table.setColumnWidth(idx, col[2])

        self.int_footer = TableFooterWidget(self.int_table)
        self.int_footer_container = TableFooterContainer(self.int_table, self.int_footer)

        self.apply_column_visibility()

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.int_table, stretch=1)
        table_layout.addWidget(self.int_footer_container)

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _create_vat_ledger_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Search + Sync + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("VAT Ledger")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_vat_count = QLabel("")
        self.lbl_vat_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.vat_search = QLineEdit()
        self.vat_search.setPlaceholderText("Filter VAT ledger name...")
        self.vat_search.setFixedWidth(220)
        self.vat_search.textChanged.connect(self._filter_vat_table)

        self.btn_sync_vat = QPushButton("Sync Vat Ledger")
        self.btn_sync_vat.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600;
                border: none; border-radius: 4px; padding: 6px 14px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_sync_vat.clicked.connect(self.sync_vat_ledger)

        self.btn_cols_vat = QPushButton("Columns ⚙")
        self.btn_cols_vat.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_cols_vat.clicked.connect(self.open_column_settings_dialog)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_vat_count)
        top_bar.addStretch()
        top_bar.addWidget(self.vat_search)
        top_bar.addWidget(self.btn_cols_vat)
        top_bar.addWidget(self.btn_sync_vat)
        vbox.addLayout(top_bar)

        # Table with all authentic columns from Tally Ledger Rows
        self.vat_table = QTableWidget()
        self.vat_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.vat_table.setAlternatingRowColors(True)
        self.vat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vat_table.verticalHeader().setVisible(False)
        self.vat_table.setItemDelegate(UniversalCellDelegate(self.vat_table))

        headers = ["VAT Ledger Name" if idx == 0 else c[1] for idx, c in enumerate(TALLY_LEDGER_COLUMNS)]
        self.vat_table.setColumnCount(len(headers))
        self.vat_table.setHorizontalHeaderLabels(headers)

        header = self.vat_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for idx, col in enumerate(TALLY_LEDGER_COLUMNS):
            self.vat_table.setColumnWidth(idx, col[2])

        self.vat_footer = TableFooterWidget(self.vat_table)
        self.vat_footer_container = TableFooterContainer(self.vat_table, self.vat_footer)

        self.apply_column_visibility()

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.vat_table, stretch=1)
        table_layout.addWidget(self.vat_footer_container)

        vbox.addWidget(table_container, stretch=1)

        # ── VAT Company Configuration: Exclusively in Vat Ledger View ──
        vat_comp_bar = QHBoxLayout()
        vat_comp_bar.setContentsMargins(4, 6, 4, 4)

        self.lbl_active_vat = QLabel("Active VAT Company: None")
        self.lbl_active_vat.setStyleSheet("font-weight: 600; color: #1e293b; font-size: 13px;")

        self.btn_vat_company = QPushButton("VAT Company")
        self.btn_vat_company.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                font-weight: 600;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #047857;
            }
        """)
        self.btn_vat_company.clicked.connect(self.open_vat_company_dialog)

        vat_comp_bar.addWidget(self.lbl_active_vat)
        vat_comp_bar.addStretch()
        vat_comp_bar.addWidget(self.btn_vat_company)

        vbox.addLayout(vat_comp_bar)
        return widget

    def _create_mapping_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Clean Top Bar: Search filter only, no extra clutter or descriptive paragraphs
        top_bar = QHBoxLayout()
        self.mapping_search = QLineEdit()
        self.mapping_search.setPlaceholderText("Search mapping...")
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
        self.mapping_table.verticalHeader().setVisible(False)

        headers = ["VAT Ledger", "Internal Ledger", "Manual Name"]
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
            MappingItemDelegate(
                lambda: get_vat_debtor_names(self.db_name, self.active_vat_company),
                lambda: get_internal_debtor_names(self.db_name),
                parent_table=self.mapping_table,
                parent=self.mapping_table
            )
        )
        self.mapping_table.itemChanged.connect(self._on_mapping_item_changed)

        vbox.addWidget(self.mapping_table)
        return widget

    def _create_debtor_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Title + Search + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("Debtor")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_debtor_count = QLabel("")
        self.lbl_debtor_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.debtor_search = QLineEdit()
        self.debtor_search.setPlaceholderText("Filter Debtor name...")
        self.debtor_search.setFixedWidth(240)
        self.debtor_search.textChanged.connect(lambda txt: self._filter_conf_table(self.debtor_table, txt))

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_debtor_count)
        top_bar.addStretch()
        top_bar.addWidget(self.debtor_search)
        vbox.addLayout(top_bar)

        self.debtor_table = self._build_vat_conf_table("Debtor")
        self.debtor_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.debtor_footer = TableFooterWidget(self.debtor_table)
        self.debtor_footer_container = TableFooterContainer(self.debtor_table, self.debtor_footer)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.debtor_table, stretch=1)
        table_layout.addWidget(self.debtor_footer_container)

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _create_creditor_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Top Bar: Title + Search + Count
        top_bar = QHBoxLayout()
        lbl = QLabel("Creditor")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #0f172a;")

        self.lbl_creditor_count = QLabel("")
        self.lbl_creditor_count.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569; "
            "padding: 3px 10px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )

        self.creditor_search = QLineEdit()
        self.creditor_search.setPlaceholderText("Filter Creditor name...")
        self.creditor_search.setFixedWidth(240)
        self.creditor_search.textChanged.connect(lambda txt: self._filter_conf_table(self.creditor_table, txt))

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_creditor_count)
        top_bar.addStretch()
        top_bar.addWidget(self.creditor_search)
        vbox.addLayout(top_bar)

        self.creditor_table = self._build_vat_conf_table("Creditor")
        self.creditor_table.setStyleSheet(TABLE_WITH_FOOTER_STYLE)
        self.creditor_footer = TableFooterWidget(self.creditor_table)
        self.creditor_footer_container = TableFooterContainer(self.creditor_table, self.creditor_footer)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.creditor_table, stretch=1)
        table_layout.addWidget(self.creditor_footer_container)

        vbox.addWidget(table_container, stretch=1)
        return widget

    def _filter_conf_table(self, tbl: QTableWidget, query: str):
        q = query.strip().lower()
        for r in range(tbl.rowCount()):
            it = tbl.item(r, 1)  # Name column
            tbl.setRowHidden(r, q not in it.text().lower() if it else False)
        if tbl == getattr(self, 'debtor_table', None) and hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
        elif tbl == getattr(self, 'creditor_table', None) and hasattr(self, 'creditor_footer'):
            self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))

    def _build_vat_conf_table(self, group_type: str) -> QTableWidget:
        tbl = VatConfTableWidget()
        tbl.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        tbl.verticalHeader().setVisible(False)

        headers = [
            "SN.", "Name", "Opening Amount", "Closing Amount",
            "Need Print ?", "Did You Print", "CRM", "Get Back",
            "Opening ?", "Closing ?"
        ]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)

        # Compact, readable human-friendly column widths (Total: ~1130px)
        header = tbl.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tbl.setColumnWidth(0, 60)   # SN.
        tbl.setColumnWidth(1, 260)  # Name
        tbl.setColumnWidth(2, 120)  # Opening Amount
        tbl.setColumnWidth(3, 120)  # Closing Amount
        tbl.setColumnWidth(4, 95)   # Need Print ?
        tbl.setColumnWidth(5, 95)   # Did You Print
        tbl.setColumnWidth(6, 140)  # CRM
        tbl.setColumnWidth(7, 90)   # Get Back
        tbl.setColumnWidth(8, 110)  # Opening ?
        tbl.setColumnWidth(9, 110)  # Closing ?

        tbl.setItemDelegate(
            VatConfDelegate(lambda: load_crm_list(self.current_company_path), tbl)
        )
        tbl.itemChanged.connect(lambda item, gt=group_type, t=tbl: self._on_vat_conf_item_changed(item, gt, t))
        return tbl

    # ── DATA LOADING ─────────────────────────────────────────────────

    def load_data(self, company_path: str, force: bool = False):
        """Called by MainWindow when company changes or tab opens.

        Uses a dedup guard to avoid redundant reloads when the path hasn't
        changed (e.g. repeated tab switches).  Pass force=True to bypass
        (used after Tally sync or VAT Company reconfigure).

        Heavy DB queries run on a background thread; the page shows instantly.
        """
        company_path = company_path or ""
        # ── Dedup guard: skip if already loaded or currently loading for this path ──
        if not force and company_path and (
            company_path == self._last_loaded_path
            or (self._load_worker is not None and self._load_worker.isRunning() and getattr(self, '_loading_path', None) == company_path)
        ):
            return

        self.current_company_path = company_path
        self.current_company_name = os.path.basename(company_path) if company_path else ""
        self.db_name = build_logical_name(self.current_company_name, company_path=self.current_company_path) if company_path else ""

        if not self.db_name or not self.db.database_exists(self.db_name):
            return

        # Fast metadata queries (< 5 ms each) — safe on UI thread
        ensure_vat_tables(self.db, self.db_name)
        self.active_vat_company = get_active_vat_company(self.db_name)
        self.lbl_active_vat.setText(f"Active VAT Company: {self.active_vat_company or 'None (Click Configure)'}")

        # ── Cancel any in-flight worker for previous company or forced reload ──
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

        # ── Kick off background data fetch ──
        self._load_worker = _VatBalanceLoadWorker(self.db_name, self.active_vat_company, parent=self)
        self._load_worker.finished.connect(self._on_data_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    # ── Async callbacks ──────────────────────────────────────────────

    def _on_data_loaded(self, data: dict):
        """Populate all tables from background-fetched data (runs on UI thread)."""
        self._last_loaded_path = self.current_company_path
        self._loading_path = None
        self._load_worker = None

        # Int. Ledger
        self._populate_ledger_table(self.int_table, data.get("int_debtors", []))
        self.apply_column_visibility()
        self._update_int_totals()

        # Vat Ledger
        self._populate_ledger_table(self.vat_table, data.get("vat_debtors", []))
        self.apply_column_visibility()
        self._update_vat_totals()

        # Mapping
        self._populate_mapping_from_data(data.get("mappings", []))

        # Vat Conf — Debtor + Creditor
        self._populate_vat_conf_table_from_data(self.debtor_table, "Debtor", data.get("debtor_conf", []))
        self._populate_vat_conf_table_from_data(self.creditor_table, "Creditor", data.get("creditor_conf", []))

    def _on_load_error(self, msg: str):
        """Handle background load failure gracefully."""
        self._loading_path = None
        self._load_worker = None
        logger.error(f"[BalanceUI._on_load_error] {msg}")

    def _populate_ledger_table(self, table: QTableWidget, debtors: list[dict]):
        """Fill table with only the authentic fields from Tally ledger data."""
        table.blockSignals(True)
        table.setRowCount(len(debtors))

        for row, d in enumerate(debtors):
            for col_idx, (field_key, _, _, is_numeric) in enumerate(TALLY_LEDGER_COLUMNS):
                raw_val = d.get(field_key)
                if is_numeric:
                    if raw_val is None:
                        val_str = "0.00"
                    elif field_key == "BillwiseOn":
                        try:
                            val_str = str(int(float(raw_val)))
                        except Exception:
                            val_str = str(raw_val)
                    else:
                        try:
                            val_str = f"{float(raw_val):,.2f}"
                        except Exception:
                            val_str = str(raw_val)
                else:
                    val_str = str(raw_val or "") if raw_val is not None else ""

                item = QTableWidgetItem(val_str)
                if is_numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                table.setItem(row, col_idx, item)

        table.blockSignals(False)

    # ── COLUMN VISIBILITY SETTINGS ───────────────────────────────────

    def get_visible_column_keys(self) -> set:
        s = QSettings("JKCatalog", "VatBalanceLedgerColumns")
        val = s.value("visible_columns", None)
        if val is None:
            return set(LedgerColumnSettingsDialog.DEFAULT_COLUMNS)
        if isinstance(val, str):
            res = set(x.strip() for x in val.split(",") if x.strip())
            res.add("Name")
            return res
        if isinstance(val, (list, set)):
            res = set(val)
            res.add("Name")
            return res
        return {c[0] for c in TALLY_LEDGER_COLUMNS}

    def save_visible_column_keys(self, cols: set):
        s = QSettings("JKCatalog", "VatBalanceLedgerColumns")
        s.setValue("visible_columns", ",".join(sorted(cols)))

    def apply_column_visibility(self):
        visible_cols = self.get_visible_column_keys()
        for idx, (col_key, _, _, _) in enumerate(TALLY_LEDGER_COLUMNS):
            hidden = (col_key not in visible_cols)
            if hasattr(self, 'int_table'):
                self.int_table.setColumnHidden(idx, hidden)
            if hasattr(self, 'int_footer'):
                self.int_footer.setColumnHidden(idx, hidden)
            if hasattr(self, 'vat_table'):
                self.vat_table.setColumnHidden(idx, hidden)
            if hasattr(self, 'vat_footer'):
                self.vat_footer.setColumnHidden(idx, hidden)

    def open_column_settings_dialog(self):
        current_visible = self.get_visible_column_keys()
        dlg = LedgerColumnSettingsDialog(current_visible, self)
        if dlg.exec():
            new_visible = dlg.get_selected_columns()
            self.save_visible_column_keys(new_visible)
            self.apply_column_visibility()
            self._update_int_totals()
            self._update_vat_totals()

    def refresh_int_ledger_table(self):
        """Populate Int. Ledger table from dbo.row_ledger_data with authentic Tally fields."""
        if not self.db_name:
            self.int_table.setRowCount(0)
            self._update_int_totals()
            return
        debtors = load_internal_debtors(self.db_name)
        self._populate_ledger_table(self.int_table, debtors)
        self.apply_column_visibility()
        self._update_int_totals()

    def _update_int_totals(self):
        if not hasattr(self, 'lbl_int_count') or not hasattr(self, 'int_table'):
            return

        numeric_col_indices = [
            i for i, col in enumerate(TALLY_LEDGER_COLUMNS)
            if col[3] and col[0] != "BillwiseOn"
        ]

        visible_count = 0
        totals = {idx: 0.0 for idx in numeric_col_indices}

        for r in range(self.int_table.rowCount()):
            if not self.int_table.isRowHidden(r):
                visible_count += 1
                for idx in numeric_col_indices:
                    it = self.int_table.item(r, idx)
                    if it and it.text().strip():
                        try:
                            totals[idx] += float(it.text().replace(",", ""))
                        except Exception:
                            pass

        total_rows = self.int_table.rowCount()
        if visible_count < total_rows:
            self.lbl_int_count.setText(f"<b>{visible_count}</b> / {total_rows} ledgers")
        else:
            self.lbl_int_count.setText(f"<b>{visible_count}</b> ledgers")

        if hasattr(self, 'int_footer'):
            formatted_totals = {
                idx: (f"-₹{abs(val):,.2f}" if val < 0 else f"₹{val:,.2f}")
                for idx, val in totals.items()
            }
            self.int_footer.update_totals(formatted_totals, label_col=0, label_text="Grand Total")

    def refresh_vat_ledger_table(self):
        """Populate VAT Ledger table from dbo.vat_row_ledger_data with authentic Tally fields."""
        if not self.db_name or not self.active_vat_company:
            self.vat_table.setRowCount(0)
            self._update_vat_totals()
            return
        debtors = load_vat_debtors(self.db_name, self.active_vat_company)
        self._populate_ledger_table(self.vat_table, debtors)
        self.apply_column_visibility()
        self._update_vat_totals()

    def _update_vat_totals(self):
        if not hasattr(self, 'lbl_vat_count') or not hasattr(self, 'vat_table'):
            return

        numeric_col_indices = [
            i for i, col in enumerate(TALLY_LEDGER_COLUMNS)
            if col[3] and col[0] != "BillwiseOn"
        ]

        visible_count = 0
        totals = {idx: 0.0 for idx in numeric_col_indices}

        for r in range(self.vat_table.rowCount()):
            if not self.vat_table.isRowHidden(r):
                visible_count += 1
                for idx in numeric_col_indices:
                    it = self.vat_table.item(r, idx)
                    if it and it.text().strip():
                        try:
                            totals[idx] += float(it.text().replace(",", ""))
                        except Exception:
                            pass

        total_rows = self.vat_table.rowCount()
        if visible_count < total_rows:
            self.lbl_vat_count.setText(f"<b>{visible_count}</b> / {total_rows} ledgers")
        else:
            self.lbl_vat_count.setText(f"<b>{visible_count}</b> ledgers")

        if hasattr(self, 'vat_footer'):
            formatted_totals = {
                idx: (f"-₹{abs(val):,.2f}" if val < 0 else f"₹{val:,.2f}")
                for idx, val in totals.items()
            }
            self.vat_footer.update_totals(formatted_totals, label_col=0, label_text="Grand Total")

    def _update_conf_totals(self, tbl: QTableWidget, footer: TableFooterWidget, lbl_count: QLabel = None):
        """Compute and display column-aligned totals for Vat Conf (Debtor / Creditor)."""
        if not tbl or not footer:
            return
        visible_count = 0
        tot_op = 0.0
        tot_cl = 0.0
        tot_exp_op = 0.0
        tot_exp_cl = 0.0

        for r in range(tbl.rowCount()):
            if not tbl.isRowHidden(r):
                visible_count += 1
                it_op = tbl.item(r, 2)
                if it_op and it_op.text().strip():
                    try:
                        tot_op += float(it_op.text().replace(",", ""))
                    except Exception:
                        pass
                it_cl = tbl.item(r, 3)
                if it_cl and it_cl.text().strip():
                    try:
                        tot_cl += float(it_cl.text().replace(",", ""))
                    except Exception:
                        pass
                it_eop = tbl.item(r, 8)
                if it_eop and it_eop.text().strip():
                    try:
                        tot_exp_op += float(it_eop.text().replace(",", ""))
                    except Exception:
                        pass
                it_ecl = tbl.item(r, 9)
                if it_ecl and it_ecl.text().strip():
                    try:
                        tot_exp_cl += float(it_ecl.text().replace(",", ""))
                    except Exception:
                        pass

        def _fmt(val):
            return f"-₹{abs(val):,.2f}" if val < 0 else f"₹{val:,.2f}"

        totals_dict = {
            2: _fmt(tot_op),
            3: _fmt(tot_cl),
        }
        if tot_exp_op != 0.0:
            totals_dict[8] = _fmt(tot_exp_op)
        if tot_exp_cl != 0.0:
            totals_dict[9] = _fmt(tot_exp_cl)

        footer.update_totals(totals_dict, label_col=1, label_text="Grand Total")
        if lbl_count:
            total_rows = tbl.rowCount()
            if visible_count < total_rows:
                lbl_count.setText(f"<b>{visible_count}</b> / {total_rows} records")
            else:
                lbl_count.setText(f"<b>{visible_count}</b> records")

    def refresh_mapping_table(self):
        """Populate Mapping table for active VAT company.

        Includes all VAT and Internal ledgers; unmatched rows appear at the top in RED per requirements.
        """
        if not self.db_name or not self.active_vat_company:
            self.mapping_table.setRowCount(0)
            return

        mappings = load_vat_mappings(self.db_name, self.active_vat_company)
        self._populate_mapping_from_data(mappings)

    def _populate_mapping_from_data(self, mappings: list):
        """Fill the mapping table from pre-fetched data (used by both sync and async paths)."""
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(mappings))

        for row, m in enumerate(mappings):
            rec_id = m.get("id", 0)
            vat_ledger = m.get("vat_ledger", "") or ""
            int_ledger = m.get("internal_ledger", "") or ""
            man_name = m.get("manual_name", "") or ""
            is_unmapped = (not vat_ledger.strip() or not int_ledger.strip())

            vat_item = QTableWidgetItem(vat_ledger)
            int_item = QTableWidgetItem(int_ledger)
            man_item = QTableWidgetItem(man_name)

            for item in (vat_item, int_item, man_item):
                item.setData(Qt.ItemDataRole.UserRole, rec_id)
                if not self._can_edit:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if is_unmapped:
                red_bg = QColor("#fecaca")
                red_fg = QColor("#991b1b")
                for item in (vat_item, int_item, man_item):
                    item.setBackground(red_bg)
                    item.setForeground(red_fg)
                int_item.setToolTip("Unmapped - click to search and select matching Internal Ledger")
            else:
                normal_fg = QColor("#0f172a")
                normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
                for item in (vat_item, int_item, man_item):
                    item.setBackground(normal_bg)
                    item.setForeground(normal_fg)

            self.mapping_table.setItem(row, 0, vat_item)
            self.mapping_table.setItem(row, 1, int_item)
            self.mapping_table.setItem(row, 2, man_item)

        self.mapping_table.blockSignals(False)

    def refresh_vat_conf_tables(self):
        """Populate Debtor and Creditor Vat Conf tables."""
        self._populate_vat_conf_table(self.debtor_table, "Debtor")
        self._populate_vat_conf_table(self.creditor_table, "Creditor")

    def _populate_vat_conf_table(self, tbl: QTableWidget, group_type: str):
        """Fetch conf data from DB and populate the table (sync path)."""
        if not self.db_name or not self.active_vat_company:
            tbl.setRowCount(0)
            if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
                self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
            elif group_type == "Creditor" and hasattr(self, 'creditor_footer'):
                self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))
            return

        rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, group_type)
        self._populate_vat_conf_table_from_data(tbl, group_type, rows)

    def _populate_vat_conf_table_from_data(self, tbl: QTableWidget, group_type: str, rows: list):
        """Populate Debtor or Creditor Vat Conf table from pre-fetched rows."""
        tbl.blockSignals(True)
        tbl.setRowCount(len(rows))

        for r_idx, r in enumerate(rows):
            # 0: SN. (Editable Cartoon Number validated against reserved numbers)
            it_sn = QTableWidgetItem(r["sn"])
            it_sn.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_sn._prev_sn = r["sn"]
            if not self._can_edit:
                it_sn.setFlags(it_sn.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 0, it_sn)

            # 1: Name (Read-only)
            it_name = QTableWidgetItem(r["name"])
            it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 1, it_name)

            # 2: Opening Amount (Read-only, right-aligned)
            it_op = QTableWidgetItem(f"{r['opening_amount']:,.2f}")
            it_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it_op.setFlags(it_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 2, it_op)

            # 3: Closing Amount (Read-only, right-aligned)
            it_cl = QTableWidgetItem(f"{r['closing_amount']:,.2f}")
            it_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it_cl.setFlags(it_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 3, it_cl)

            # 4: Need Print ? (Read-only, centered)
            it_np = QTableWidgetItem(r["need_print"])
            it_np.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r["need_print"] == "Yes":
                it_np.setForeground(QColor("#059669"))
                font = it_np.font()
                font.setBold(True)
                it_np.setFont(font)
            it_np.setFlags(it_np.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 4, it_np)

            # 5: Did You Print (Editable Yes/No, accepts 1/0, Y/N, T/F)
            it_dyp = QTableWidgetItem(r["did_you_print"])
            it_dyp.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not self._can_edit:
                it_dyp.setFlags(it_dyp.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 5, it_dyp)

            # 6: CRM (Editable autocomplete)
            it_crm = QTableWidgetItem(r["crm"])
            if not self._can_edit:
                it_crm.setFlags(it_crm.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 6, it_crm)

            # 7: Get Back (Editable Yes/No, accepts 1/0, Y/N, T/F)
            it_gb = QTableWidgetItem(r["get_back"])
            it_gb.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not self._can_edit:
                it_gb.setFlags(it_gb.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 7, it_gb)

            # 8: Opening ? (Editable numeric, compared against Opening Amount)
            it_exp_op = QTableWidgetItem(r["expected_opening"])
            it_exp_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if not self._can_edit:
                it_exp_op.setFlags(it_exp_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 8, it_exp_op)

            # 9: Closing ? (Editable numeric, compared against Closing Amount)
            it_exp_cl = QTableWidgetItem(r["expected_closing"])
            it_exp_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if not self._can_edit:
                it_exp_cl.setFlags(it_exp_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 9, it_exp_cl)

            # Apply full row solid red highlight if mismatched or empty
            self._update_vat_conf_row_style(tbl, r_idx)

        tbl.blockSignals(False)
        if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
        elif group_type == "Creditor" and hasattr(self, 'creditor_footer'):
            self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))

    def _update_vat_conf_row_style(self, tbl: QTableWidget, row: int):
        """If expected amount does not match actual amount or either is empty, paint the FULL ROW in RED."""
        act_op_item = tbl.item(row, 2)
        act_cl_item = tbl.item(row, 3)
        exp_op_item = tbl.item(row, 8)
        exp_cl_item = tbl.item(row, 9)

        try:
            act_op_val = float(act_op_item.text().replace(",", "").strip()) if act_op_item else 0.0
        except ValueError:
            act_op_val = 0.0

        try:
            act_cl_val = float(act_cl_item.text().replace(",", "").strip()) if act_cl_item else 0.0
        except ValueError:
            act_cl_val = 0.0

        exp_op_text = exp_op_item.text().strip() if exp_op_item else ""
        exp_cl_text = exp_cl_item.text().strip() if exp_cl_item else ""

        # Empty expected fields are NOT mismatches (check_amount_match returns True for empty)
        op_matches = check_amount_match(act_op_val, exp_op_text)
        cl_matches = check_amount_match(act_cl_val, exp_cl_text)
        is_mismatch = not (op_matches and cl_matches)

        red_bg = QColor("#fecaca")
        red_fg = QColor("#991b1b")
        normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
        normal_fg = QColor("#0f172a")

        for c in range(tbl.columnCount()):
            it = tbl.item(row, c)
            if not it:
                continue
            if is_mismatch:
                it.setBackground(red_bg)
                it.setForeground(red_fg)
            else:
                it.setBackground(normal_bg)
                if c == 4 and it.text() == "Yes":
                    it.setForeground(QColor("#059669"))
                else:
                    it.setForeground(normal_fg)

    # ── EDIT EVENT HANDLERS ──────────────────────────────────────────

    def _on_mapping_item_changed(self, item: QTableWidgetItem):
        """User modified a cell (VAT Ledger, Internal Ledger, or Manual Name) in Mapping table."""
        if not self._can_edit:
            return
        try:
            row = item.row()
            if row < 0:
                return
            vat_item = self.mapping_table.item(row, 0)
            int_item = self.mapping_table.item(row, 1)
            man_item = self.mapping_table.item(row, 2)
            if not vat_item or not int_item or not man_item:
                return

            vat_name = vat_item.text().strip()
            int_name = int_item.text().strip()
            man_name = man_item.text().strip()

            # Update visual highlight based on whether mapped (full row red if either ledger is empty)
            is_unmapped = (not vat_name or not int_name)
            self.mapping_table.blockSignals(True)
            try:
                if not is_unmapped:
                    # Successfully mapped -> restore normal appearance
                    normal_fg = QColor("#0f172a")
                    normal_bg = QColor("#ffffff") if row % 2 == 0 else QColor("#f8fafc")
                    for it in (vat_item, int_item, man_item):
                        it.setBackground(normal_bg)
                        it.setForeground(normal_fg)
                        it.setToolTip("")
                else:
                    # Unmapped (one ledger cell is empty) -> full row marked red
                    red_bg = QColor("#fecaca")
                    red_fg = QColor("#991b1b")
                    for it in (vat_item, int_item, man_item):
                        it.setBackground(red_bg)
                        it.setForeground(red_fg)
                    int_item.setToolTip("Unmapped - click to search and select matching Internal Ledger")
            finally:
                self.mapping_table.blockSignals(False)
            self.mapping_table.viewport().update()

            active_comp = self.active_vat_company
            if not active_comp and self.db_name:
                active_comp = get_active_vat_company(self.db_name)
                self.active_vat_company = active_comp
            if not active_comp:
                logger.warning(f"[_on_mapping_item_changed] No active VAT company configured for db '{self.db_name}'")
                return

            rec_id = item.data(Qt.ItemDataRole.UserRole)
            if not rec_id:
                rec_id = vat_item.data(Qt.ItemDataRole.UserRole) or int_item.data(Qt.ItemDataRole.UserRole) or 0

            new_id = save_manual_mapping(self.db_name, active_comp, rec_id or 0, vat_name, int_name, man_name)
            if new_id:
                self.mapping_table.blockSignals(True)
                vat_item.setData(Qt.ItemDataRole.UserRole, new_id)
                int_item.setData(Qt.ItemDataRole.UserRole, new_id)
                man_item.setData(Qt.ItemDataRole.UserRole, new_id)
                self.mapping_table.blockSignals(False)
        except Exception as e:
            logger.error(f"[_on_mapping_item_changed] Failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Save Error", f"Failed to save mapping: {e}")

    def _on_vat_conf_item_changed(self, item: QTableWidgetItem, group_type: str, tbl: QTableWidget):
        """User modified an editable cell in Vat Conf (Debtor/Creditor)."""
        col = item.column()
        row = item.row()
        name_item = tbl.item(row, 1)
        if not name_item:
            return
        ledger_name = name_item.text().strip()
        val = item.text().strip()

        active_comp = self.active_vat_company
        if not active_comp and self.db_name:
            active_comp = get_active_vat_company(self.db_name)
            self.active_vat_company = active_comp
        if not active_comp:
            logger.warning(f"[_on_vat_conf_item_changed] No active VAT company configured for db '{self.db_name}'")
            return

        # 0: Carton Number (SN.) Validation & Persistence
        if col == 0:
            is_valid, err_msg = validate_cartoon_number(val)
            if not is_valid:
                old_val = getattr(item, '_prev_sn', '')
                tbl.blockSignals(True)
                item.setText(old_val)
                tbl.blockSignals(False)
                QTimer.singleShot(0, lambda msg=err_msg: QMessageBox.warning(self, "Invalid Cartoon Number", msg))
                return
            item._prev_sn = val
            try:
                save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "sn", val)
            except Exception as e:
                logger.error(f"Failed to save SN: {e}")
            return

        # 5 & 7: Normalize Yes/No input
        if col in (5, 7):
            val = normalize_yes_no(val)
            tbl.blockSignals(True)
            item.setText(val)
            tbl.blockSignals(False)

        field_map = {
            5: "did_you_print",
            6: "crm",
            7: "get_back",
            8: "expected_opening",
            9: "expected_closing",
        }
        field_name = field_map.get(col)
        if not field_name:
            return

        try:
            save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, field_name, val)

            # Update comparison highlight across the full row whenever Opening ? or Closing ? is modified
            if col in (8, 9):
                tbl.blockSignals(True)
                self._update_vat_conf_row_style(tbl, row)
                tbl.blockSignals(False)
                tbl.viewport().update()
                if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
                    self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
                elif group_type == "Creditor" and hasattr(self, 'creditor_footer'):
                    self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))

        except Exception as e:
            logger.error(f"[_on_vat_conf_item_changed] error: {e}")

    # ── SEARCH FILTERS ───────────────────────────────────────────────

    def _filter_int_table(self, query: str):
        q = query.strip().lower()
        for r in range(self.int_table.rowCount()):
            it = self.int_table.item(r, 0)
            match = q in it.text().lower() if it else False
            self.int_table.setRowHidden(r, not match)
        self._update_int_totals()

    def _filter_vat_table(self, query: str):
        q = query.strip().lower()
        for r in range(self.vat_table.rowCount()):
            it = self.vat_table.item(r, 0)
            match = q in it.text().lower() if it else False
            self.vat_table.setRowHidden(r, not match)
        self._update_vat_totals()

    def _filter_mapping_table(self, query: str):
        q = query.strip().lower()
        for r in range(self.mapping_table.rowCount()):
            vat_it = self.mapping_table.item(r, 0)
            int_it = self.mapping_table.item(r, 1)
            man_it = self.mapping_table.item(r, 2)
            t0 = vat_it.text().lower() if vat_it else ""
            t1 = int_it.text().lower() if int_it else ""
            t2 = man_it.text().lower() if man_it else ""
            self.mapping_table.setRowHidden(r, (q not in t0) and (q not in t1) and (q not in t2))

    # ── SYNCHRONIZATION ──────────────────────────────────────────────

    def sync_int_ledger(self):
        """Trigger sync for Internal Ledger from running Tally instance."""
        if hasattr(self, '_int_worker') and self._int_worker and self._int_worker.isRunning():
            QMessageBox.warning(self, "Sync in Progress", "Internal Ledger sync is already running.")
            return

        if not self.current_company_name:
            QMessageBox.warning(self, "No Company", "Please select a company first.")
            return

        if not hasattr(self, '_int_service') or self._int_service is None:
            self._int_service = TallyService()
        else:
            self._int_service.cancelled = False

        self._int_progress = QProgressDialog("Syncing Internal Ledger from Tally...", "Cancel", 0, 0, self)
        self._int_progress.setWindowTitle("Internal Ledger Sync")
        self._int_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._int_progress.canceled.connect(self._int_service.cancel)
        self._int_progress.show()

        self._int_worker = _InternalLedgerWorker(
            self.current_company_name, self.current_company_path, self._int_service
        )
        self._int_worker.finished.connect(self._on_int_sync_done)
        self._int_worker.start()

    def _on_int_sync_done(self, count: int, error: str):
        if hasattr(self, '_int_progress') and self._int_progress:
            self._int_progress.close()

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "Internal Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync Internal Ledger:\n{error}")
        else:
            QMessageBox.information(self, "Sync Complete", f"Synced {count} internal ledger entries.")
            self.refresh_int_ledger_table()
            self.refresh_mapping_table()

    def sync_vat_ledger(self):
        """Trigger sync for VAT Ledger from running Tally instance."""
        if hasattr(self, '_vat_worker') and self._vat_worker and self._vat_worker.isRunning():
            QMessageBox.warning(self, "Sync in Progress", "VAT Ledger sync is already running.")
            return

        if not self.active_vat_company:
            QMessageBox.warning(
                self, "VAT Company Missing",
                "Please configure an active VAT Company first by clicking 'VAT Company'."
            )
            return

        if not hasattr(self, '_vat_service') or self._vat_service is None:
            self._vat_service = TallyService()
        else:
            self._vat_service.cancelled = False

        self._vat_progress = QProgressDialog(
            f"Syncing VAT Ledgers from Tally for '{self.active_vat_company}'...", "Cancel", 0, 0, self
        )
        self._vat_progress.setWindowTitle("VAT Ledger Sync")
        self._vat_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._vat_progress.canceled.connect(self._vat_service.cancel)
        self._vat_progress.show()

        self._vat_worker = _VatLedgerWorker(
            self.active_vat_company, self.current_company_name, self.current_company_path, self._vat_service
        )
        self._vat_worker.finished.connect(self._on_vat_sync_done)
        self._vat_worker.start()

    def _on_vat_sync_done(self, count: int, error: str):
        if hasattr(self, '_vat_progress') and self._vat_progress:
            self._vat_progress.close()

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "VAT Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync VAT Ledgers:\n{error}")
        else:
            QMessageBox.information(
                self, "Sync Complete",
                f"Successfully synced {count} VAT ledger entries for '{self.active_vat_company}'."
            )
            self.refresh_vat_ledger_table()
            self.refresh_mapping_table()
            self.refresh_vat_conf_tables()

    # ── VAT COMPANY POPUP ────────────────────────────────────────────

    def open_vat_company_dialog(self):
        """Open the multi-profile VAT company management dialog."""
        if not self.db_name:
            QMessageBox.warning(self, "No Company", "Please select an active company first.")
            return

        dlg = VatCompanyDialog(self.db_name, self)
        dlg.company_changed.connect(self._on_vat_company_changed)
        dlg.exec()

    def _on_vat_company_changed(self, new_company: str):
        self.active_vat_company = new_company.strip()
        self.lbl_active_vat.setText(f"Active VAT Company: {self.active_vat_company}")
        # Refresh all VAT views
        self.refresh_vat_ledger_table()
        self.refresh_mapping_table()
        self.refresh_vat_conf_tables()

    # ── PERMISSION CONTROL ───────────────────────────────────────────

    def apply_edit_mode(self, can_edit: bool):
        """Enforce display-only mode based on user permissions."""
        self._can_edit = can_edit
        self.btn_vat_company.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_int'):
            self.btn_tab_sync_int.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_vat'):
            self.btn_tab_sync_vat.setEnabled(can_edit)
        # Lock mapping table editing across all 3 columns
        for r in range(self.mapping_table.rowCount()):
            for c in range(3):
                it = self.mapping_table.item(r, c)
                if it:
                    if can_edit:
                        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Propagate _can_edit to conf tables so VatConfDelegate can check it
        self.debtor_table._can_edit = can_edit
        self.creditor_table._can_edit = can_edit

        # Lock vat conf tables editing (Col 0 and Cols 5-9)
        for tbl in (self.debtor_table, self.creditor_table):
            for r in range(tbl.rowCount()):
                for c in [0, 5, 6, 7, 8, 9]:
                    it = tbl.item(r, c)
                    if it:
                        if can_edit:
                            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

    # ── EXPORT / PRINT INTEGRATION HELPER ────────────────────────────

    def get_current_table(self) -> tuple[str, QTableWidget]:
        """Return (title, table_widget) for the currently focused/active tab."""
        idx = self.tabs.currentIndex()
        if idx == 0:
            return "VAT Working - Int. Ledger", self.int_table
        elif idx == 1:
            return f"VAT Working - Vat Ledger ({self.active_vat_company})", self.vat_table
        elif idx == 2:
            return f"VAT Working - Mapping ({self.active_vat_company})", self.mapping_table
        elif idx == 3:
            if hasattr(self, 'conf_tabs') and self.conf_tabs.currentIndex() == 1:
                return f"VAT Conf - Creditor ({self.active_vat_company})", self.creditor_table
            return f"VAT Conf - Debtor ({self.active_vat_company})", self.debtor_table
        return "VAT Working Table", self.int_table
