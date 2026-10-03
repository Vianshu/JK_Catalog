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
    QDialog, QCheckBox, QScrollArea, QSplitter, QListWidget, QListWidgetItem, QMenu,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings, QEvent
from PyQt6.QtGui import QColor, QFont, QIcon

from src.logic.db_manager import get_db_manager, build_logical_name
from src.logic.vat_manager import (
    get_active_vat_company, load_internal_debtors, load_vat_debtors,
    load_vat_mappings, save_manual_mapping, get_internal_debtor_names,
    get_vat_debtor_names, load_vat_conf_table_data, save_vat_conf_field,
    check_amount_match, ensure_vat_tables, normalize_yes_no, validate_cartoon_number,
    _EXCLUDED_CNS,
    get_unassigned_internal_debtors, assign_internal_ledger_to_group,
    remove_internal_ledger_from_group, unmap_vat_group, merge_mapping_groups,
    demerge_mapping_group, set_group_internal_ledgers, set_group_vat_ledgers,
    set_group_manual_name, update_group_internal_ledger, update_group_vat_ledger
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
            unassigned_int = get_unassigned_internal_debtors(self._db_name, self._vat_company) if self._vat_company else []
            debtor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Debtor") if self._vat_company else []
            creditor_conf = load_vat_conf_table_data(self._db_name, self._vat_company, "Creditor") if self._vat_company else []

            self.finished.emit({
                "int_debtors": int_debtors,
                "vat_debtors": vat_debtors,
                "mappings": mappings,
                "unassigned_int": unassigned_int,
                "debtor_conf": debtor_conf,
                "creditor_conf": creditor_conf,
            })
        except Exception as e:
            logger.error(f"[_VatBalanceLoadWorker] error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            get_db_manager().close_thread_connections()


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
        "Name", "Alias", "Group", "Opening_Balance",
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
        finally:
            get_db_manager().close_thread_connections()


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
        finally:
            get_db_manager().close_thread_connections()


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
        # Unmapped VAT rows are painted in light red (#fecaca)
        table = self.parent_table or (self.parent() if isinstance(self.parent(), QAbstractItemView) else None)
        if table:
            it0 = table.item(index.row(), 0)
            mapping_data = getattr(it0, '_mapping_group', {}) if it0 else {}
            if mapping_data.get("is_unmapped", False):
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
        if col in (0, 2, 4):  # #, VAT Alias, Internal Alias are read-only
            return None

        if col == 1:  # VAT Ledger (editable with completer)
            ed = QLineEdit(parent)
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)

            callback = self.get_vat_options_callback
            options = callback() if callable(callback) else []
            completer = _TallyCompleter(options or [], ed)
            completer.setMaxVisibleItems(12)
            completer.popup().setMinimumWidth(340)
            ed.setCompleter(completer)
            ed.textEdited.connect(completer.update_prefix)

            def _on_vat_activated(selected, e=ed, c=completer):
                c._typed_text = selected
                e.setText(selected)
                QTimer.singleShot(0, lambda: self._commit_and_close(e))

            completer.activated.connect(_on_vat_activated)
            return ed

        elif col == 3:  # Internal Ledger (editable with completer)
            ed = QLineEdit(parent)
            ed.setFrame(False)
            ed.setAutoFillBackground(True)
            ed.setStyleSheet(
                "QLineEdit { background: #ffffff; border: 1px solid #059669; "
                "padding: 0px 4px; margin: 0px; color: #0f172a; font-size: 10pt; }"
            )
            ed.setTextMargins(0, 0, 0, 0)
            ed.setContentsMargins(0, 0, 0, 0)

            callback = self.get_int_options_callback
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

        elif col == 5:  # Manual Name column
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

        if col in (0, 5, 6, 8):
            ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif col in (3, 4, 9, 10):
            ed.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            ed.setAlignment(Qt.AlignmentFlag.AlignLeft)

        if col == 0 and table:
            it = table.item(index.row(), 0)
            if it:
                it._prev_sn = it.text().strip()

        if col in (6, 8):
            ed.setPlaceholderText("Y/N or 1/0")
        elif col == 7:  # CRM autocomplete
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
            if col in (6, 8):
                val = normalize_yes_no(val)
            model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class VatConfTableWidget(QTableWidget):
    """QTableWidget with spacebar toggle for Did You Print (Col 6) and Get Back (Col 8)."""
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.state() != QTableWidget.State.EditingState:
            col = self.currentColumn()
            row = self.currentRow()
            if col in (6, 8) and row >= 0:
                item = self.item(row, col)
                if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    cur_val = (item.text() or "").strip()
                    new_val = "No" if cur_val.lower() in ("yes", "y", "1", "t", "true") else "Yes"
                    item.setText(new_val)
                    return
        super().keyPressEvent(event)


class MappingTableWidget(QTableWidget):
    """QTableWidget with keyboard shortcuts for Mapping table:
    - Delete / Backspace on Col 3 (Internal Ledger): removes that internal ledger from group
    - Delete / Backspace on Col 5 (Manual Name): clears manual name
    - Delete / Backspace on Col 0 / row selection: unmaps the entire group
    """
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.state() != QTableWidget.State.EditingState:
            if getattr(self, '_can_edit', True):
                selected_indexes = self.selectedIndexes()
                if selected_indexes:
                    selected_rows = sorted(list({idx.row() for idx in selected_indexes}))
                    selected_cols = {idx.column() for idx in selected_indexes}
                    if selected_cols == {5}:
                        for r in selected_rows:
                            it = self.item(r, 5)
                            if it and it.text().strip():
                                it.setText("")
                        return
                    elif selected_cols == {3}:
                        for r in selected_rows:
                            it = self.item(r, 3)
                            if it and it.text().strip():
                                it.setText("")
                        return
                    else:
                        parent_ui = getattr(self, '_parent_ui', None)
                        if parent_ui and hasattr(parent_ui, '_unmap_selected_mapping'):
                            parent_ui._unmap_selected_mapping()
                            return
                        else:
                            for r in selected_rows:
                                it = self.item(r, 3)
                                if it and it.text().strip():
                                    it.setText("")
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
        self._cached_data = {}            # cached data for lazy tab rendering
        self._rendered_tabs = set()       # set of tab keys that have been rendered

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

        self.tabs.currentChanged.connect(self._on_tab_changed)
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

        self.conf_tabs.currentChanged.connect(self._on_conf_tab_changed)
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
        self._render_current_tab()

    def _get_internal_ledger_options(self) -> list[str]:
        """Return list of internal debtor names and aliases for mapping autocomplete."""
        if not self.db_name:
            return []
        try:
            debtors = load_internal_debtors(self.db_name)
            opts = []
            for d in debtors:
                name = str(d.get("Name") or "").strip()
                alias = str(d.get("Alias") or "").strip()
                if name.lower() in ("none", "nan", "null"):
                    name = ""
                if alias.lower() in ("none", "nan", "null"):
                    alias = ""
                if name and name not in opts:
                    opts.append(name)
                if alias and alias not in opts:
                    opts.append(alias)
            return opts
        except Exception:
            return []

    def _get_vat_ledger_options(self) -> list[str]:
        """Return list of VAT debtor names and aliases for mapping autocomplete."""
        if not self.db_name or not self.active_vat_company:
            return []
        try:
            debtors = load_vat_debtors(self.db_name, self.active_vat_company)
            opts = []
            for d in debtors:
                name = str(d.get("Name") or "").strip()
                alias = str(d.get("Alias") or "").strip()
                if name.lower() in ("none", "nan", "null"):
                    name = ""
                if alias.lower() in ("none", "nan", "null"):
                    alias = ""
                if name and name not in opts:
                    opts.append(name)
                if alias and alias not in opts:
                    opts.append(alias)
            return opts
        except Exception:
            return []

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
        self.int_search.setPlaceholderText("Search name or alias...")
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

        self.btn_toggle_int_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_int_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_int_alias.clicked.connect(self._toggle_ledger_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_int_count)
        top_bar.addStretch()
        top_bar.addWidget(self.int_search)
        top_bar.addWidget(self.btn_toggle_int_alias)
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
        self.vat_search.setPlaceholderText("Search name or alias...")
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

        self.btn_toggle_vat_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_vat_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_vat_alias.clicked.connect(self._toggle_ledger_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_vat_count)
        top_bar.addStretch()
        top_bar.addWidget(self.vat_search)
        top_bar.addWidget(self.btn_toggle_vat_alias)
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

        # Top Bar: Search filter, Unmapped badge, Merge/Demerge buttons, Clear mapping, Toggle unassigned panel
        top_bar = QHBoxLayout()
        self.mapping_search = QLineEdit()
        self.mapping_search.setPlaceholderText("Search name or alias...")
        self.mapping_search.setFixedWidth(220)
        self.mapping_search.textChanged.connect(self._filter_mapping_table)
        top_bar.addWidget(self.mapping_search)

        self.lbl_unmapped_badge = QLabel("")
        self.lbl_unmapped_badge.setStyleSheet(
            "background: #fee2e2; color: #991b1b; font-size: 11px; font-weight: 700; "
            "padding: 3px 8px; border-radius: 10px; border: 1px solid #fca5a5;"
        )
        self.lbl_unmapped_badge.setVisible(False)
        top_bar.addWidget(self.lbl_unmapped_badge)

        top_bar.addStretch()

        self.btn_merge_mapping = QPushButton("🔗 Merge Selected")
        self.btn_merge_mapping.setEnabled(False)
        self.btn_merge_mapping.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #047857; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        self.btn_merge_mapping.clicked.connect(self._merge_selected_mappings)
        top_bar.addWidget(self.btn_merge_mapping)

        self.btn_demerge_mapping = QPushButton("✂️ Demerge")
        self.btn_demerge_mapping.setEnabled(False)
        self.btn_demerge_mapping.setStyleSheet("""
            QPushButton {
                background: #475569; color: white; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #334155; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        self.btn_demerge_mapping.clicked.connect(self._demerge_selected_mapping)
        top_bar.addWidget(self.btn_demerge_mapping)

        self.btn_unmap_mapping = QPushButton("Clear Mapping")
        self.btn_unmap_mapping.setEnabled(False)
        self.btn_unmap_mapping.setStyleSheet("""
            QPushButton {
                background: #ef4444; color: white; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #dc2626; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        self.btn_unmap_mapping.clicked.connect(self._unmap_selected_mapping)
        top_bar.addWidget(self.btn_unmap_mapping)

        self.btn_toggle_mapping_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_mapping_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_mapping_alias.clicked.connect(self._toggle_mapping_alias_visibility)
        top_bar.addWidget(self.btn_toggle_mapping_alias)

        self.btn_toggle_unassigned = QPushButton("📋 Unassigned Internal (0) ❯")
        self.btn_toggle_unassigned.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #1e293b; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_unassigned.clicked.connect(self._toggle_unassigned_panel)
        top_bar.addWidget(self.btn_toggle_unassigned)

        vbox.addLayout(top_bar)

        # Splitter: Left is Main Mapping Table, Right is Minimizable Unassigned Internal List
        self.mapping_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Container (Main Mapping Table)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.mapping_table = MappingTableWidget()
        self.mapping_table._parent_ui = self
        self.mapping_table._can_edit = self._can_edit
        self.mapping_table.setStyleSheet(UNIVERSAL_TABLE_STYLE)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.mapping_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mapping_table.verticalHeader().setVisible(False)

        headers = ["#", "VAT Ledger", "VAT Alias", "Internal Ledger", "Internal Alias", "Manual Name"]
        self.mapping_table.setColumnCount(6)
        self.mapping_table.setHorizontalHeaderLabels(headers)

        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.mapping_table.setColumnWidth(0, 45)   # #
        self.mapping_table.setColumnWidth(1, 260)  # VAT Ledger
        self.mapping_table.setColumnWidth(2, 130)  # VAT Alias
        self.mapping_table.setColumnWidth(3, 280)  # Internal Ledger
        self.mapping_table.setColumnWidth(4, 130)  # Internal Alias
        self.mapping_table.setColumnWidth(5, 180)  # Manual Name

        # Set mapping delegate with seamless QLineEdit + _TallyCompleter for both sides
        self.mapping_table.setItemDelegate(
            MappingItemDelegate(
                self._get_vat_ledger_options,
                self._get_internal_ledger_options,
                parent_table=self.mapping_table,
                parent=self.mapping_table
            )
        )
        self.mapping_table.itemSelectionChanged.connect(self._on_mapping_selection_changed)
        self.mapping_table.itemChanged.connect(self._on_mapping_item_changed)
        self.mapping_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mapping_table.customContextMenuRequested.connect(self._show_mapping_context_menu)

        left_layout.addWidget(self.mapping_table)
        self.mapping_splitter.addWidget(left_widget)

        # Right Container (Unassigned Internal Ledgers Panel)
        self.unassigned_panel = QWidget()
        self.unassigned_panel.setStyleSheet("background: #ffffff; border-left: 1px solid #e2e8f0;")
        panel_layout = QVBoxLayout(self.unassigned_panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(8)

        # Panel Header
        p_hdr = QHBoxLayout()
        p_lbl = QLabel("Unassigned Internal")
        p_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #0f172a;")
        self.lbl_unassigned_count = QLabel("0")
        self.lbl_unassigned_count.setStyleSheet(
            "background: #e0e7ff; color: #3730a3; font-size: 11px; font-weight: 700; "
            "padding: 2px 7px; border-radius: 10px;"
        )
        p_hdr.addWidget(p_lbl)
        p_hdr.addWidget(self.lbl_unassigned_count)
        p_hdr.addStretch()

        self.btn_collapse_unassigned = QPushButton("⮞")
        self.btn_collapse_unassigned.setFixedSize(24, 24)
        self.btn_collapse_unassigned.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #475569; font-weight: bold; border-radius: 12px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; color: #0f172a; }
        """)
        self.btn_collapse_unassigned.clicked.connect(self._collapse_unassigned_panel)
        p_hdr.addWidget(self.btn_collapse_unassigned)
        panel_layout.addLayout(p_hdr)

        # Panel Search
        self.unassigned_search = QLineEdit()
        self.unassigned_search.setPlaceholderText("Filter internal debtors...")
        self.unassigned_search.setStyleSheet(
            "QLineEdit { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
        )
        self.unassigned_search.textChanged.connect(self._filter_unassigned_list)
        panel_layout.addWidget(self.unassigned_search)

        # Panel Action: Assign button
        self.btn_assign_internal = QPushButton("← Assign to Selected VAT")
        self.btn_assign_internal.setEnabled(False)
        self.btn_assign_internal.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; font-size: 12px;
                padding: 6px 12px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #047857; }
            QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }
        """)
        self.btn_assign_internal.clicked.connect(self._assign_selected_internal_ledger)
        panel_layout.addWidget(self.btn_assign_internal)

        # Panel List
        self.unassigned_list = QListWidget()
        self.unassigned_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #e2e8f0; border-radius: 4px; background: #ffffff;
                font-size: 12px; color: #0f172a; padding: 2px;
            }
            QListWidget::item {
                padding: 6px 8px; border-radius: 4px; border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:hover {
                background: #f1f5f9;
            }
            QListWidget::item:selected {
                background: #e0f2fe; color: #0369a1; font-weight: 600;
            }
        """)
        self.unassigned_list.itemDoubleClicked.connect(self._on_unassigned_item_double_clicked)
        self.unassigned_list.itemSelectionChanged.connect(self._on_unassigned_selection_changed)
        panel_layout.addWidget(self.unassigned_list, stretch=1)

        self.mapping_splitter.addWidget(self.unassigned_panel)
        self.mapping_splitter.setStretchFactor(0, 7)
        self.mapping_splitter.setStretchFactor(1, 3)

        vbox.addWidget(self.mapping_splitter, stretch=1)
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
        self.debtor_search.setPlaceholderText("Search name or alias...")
        self.debtor_search.setFixedWidth(240)
        self.debtor_search.textChanged.connect(lambda txt: self._filter_conf_table(self.debtor_table, txt))

        self.btn_toggle_debtor_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_debtor_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_debtor_alias.clicked.connect(self._toggle_conf_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_debtor_count)
        top_bar.addStretch()
        top_bar.addWidget(self.debtor_search)
        top_bar.addWidget(self.btn_toggle_debtor_alias)
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
        self.creditor_search.setPlaceholderText("Search name or alias...")
        self.creditor_search.setFixedWidth(240)
        self.creditor_search.textChanged.connect(lambda txt: self._filter_conf_table(self.creditor_table, txt))

        self.btn_toggle_creditor_alias = QPushButton("👁️ Hide Alias")
        self.btn_toggle_creditor_alias.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #334155; font-weight: 600; font-size: 12px;
                padding: 5px 12px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_toggle_creditor_alias.clicked.connect(self._toggle_conf_alias_visibility)

        top_bar.addWidget(lbl)
        top_bar.addSpacing(10)
        top_bar.addWidget(self.lbl_creditor_count)
        top_bar.addStretch()
        top_bar.addWidget(self.creditor_search)
        top_bar.addWidget(self.btn_toggle_creditor_alias)
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
            it_alias = tbl.item(r, 2)  # Alias column
            if not it:
                tbl.setRowHidden(r, bool(q))
                continue
            name = str(it.data(Qt.ItemDataRole.UserRole) or it.text() or "").lower()
            alias = str(it_alias.text() if it_alias else "").lower()
            match = (not q) or (q in name) or (q in alias)
            tbl.setRowHidden(r, not match)
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
            "SN.", "Name", "Alias", "Opening Amount", "Closing Amount",
            "Need Print ?", "Did You Print", "CRM", "Get Back",
            "Opening ?", "Closing ?"
        ]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)

        header = tbl.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tbl.setColumnWidth(0, 60)   # SN.
        tbl.setColumnWidth(1, 240)  # Name
        tbl.setColumnWidth(2, 130)  # Alias
        tbl.setColumnWidth(3, 120)  # Opening Amount
        tbl.setColumnWidth(4, 120)  # Closing Amount
        tbl.setColumnWidth(5, 95)   # Need Print ?
        tbl.setColumnWidth(6, 95)   # Did You Print
        tbl.setColumnWidth(7, 140)  # CRM
        tbl.setColumnWidth(8, 90)   # Get Back
        tbl.setColumnWidth(9, 110)  # Opening ?
        tbl.setColumnWidth(10, 110) # Closing ?

        tbl.setItemDelegate(
            VatConfDelegate(lambda: load_crm_list(self.current_company_path), tbl)
        )
        tbl.itemChanged.connect(lambda item, gt=group_type, t=tbl: self._on_vat_conf_item_changed(item, gt, t))
        return tbl

    # ── DATA LOADING ─────────────────────────────────────────────────

    def load_data(self, company_path: str, company_name: str = None, force: bool = False):
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
        self.current_company_name = company_name or (os.path.basename(os.path.normpath(company_path)) if company_path else "")
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
        """Cache data and lazily render only the currently visible tab (runs on UI thread)."""
        self._last_loaded_path = self.current_company_path
        self._loading_path = None
        self._load_worker = None
        self._cached_data = data or {}
        self._rendered_tabs.clear()
        self._render_current_tab()

    def _render_current_tab(self):
        """Lazily populate only the currently active tab from cached data."""
        if not getattr(self, '_cached_data', None):
            return

        current_idx = self.tabs.currentIndex()

        if current_idx == 0:
            if "int_ledger" not in self._rendered_tabs:
                self._populate_ledger_table(self.int_table, self._cached_data.get("int_debtors", []))
                self.apply_column_visibility()
                self._update_int_totals()
                self._rendered_tabs.add("int_ledger")

        elif current_idx == 1:
            if "vat_ledger" not in self._rendered_tabs:
                self._populate_ledger_table(self.vat_table, self._cached_data.get("vat_debtors", []))
                self.apply_column_visibility()
                self._update_vat_totals()
                self._rendered_tabs.add("vat_ledger")

        elif current_idx == 2:
            if "mapping" not in self._rendered_tabs:
                self._populate_mapping_from_data(self._cached_data.get("mappings", []))
                self._populate_unassigned_list(self._cached_data.get("unassigned_int", []))
                self._rendered_tabs.add("mapping")

        elif current_idx == 3:
            conf_idx = self.conf_tabs.currentIndex() if hasattr(self, 'conf_tabs') else 0
            if conf_idx == 0:
                if "debtor_conf" not in self._rendered_tabs:
                    self._populate_vat_conf_table_from_data(
                        self.debtor_table, "Debtor", self._cached_data.get("debtor_conf", [])
                    )
                    self._rendered_tabs.add("debtor_conf")
            elif conf_idx == 1:
                if "creditor_conf" not in self._rendered_tabs:
                    self._populate_vat_conf_table_from_data(
                        self.creditor_table, "Creditor", self._cached_data.get("creditor_conf", [])
                    )
                    self._rendered_tabs.add("creditor_conf")

    def _on_tab_changed(self, index: int):
        self._render_current_tab()

    def _on_conf_tab_changed(self, index: int):
        self._render_current_tab()

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
                    if val_str.lower() in ("none", "nan", "null"):
                        val_str = ""
                    if field_key == "Name":
                        raw_name = str(d.get("Name", "") or "").strip()
                        if raw_name.lower() in ("none", "nan", "null"):
                            raw_name = ""
                        val_str = raw_name
                    elif field_key == "Alias":
                        raw_alias = str(d.get("Alias", "") or "").strip()
                        if raw_alias.lower() in ("none", "nan", "null"):
                            raw_alias = ""
                        val_str = raw_alias

                item = QTableWidgetItem(val_str)
                if field_key == "Name":
                    item.setData(Qt.ItemDataRole.UserRole, str(d.get("Name", "") or "").strip())
                    item.setData(Qt.ItemDataRole.UserRole + 1, str(d.get("Alias", "") or "").strip())

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

        is_alias_hidden = "Alias" not in visible_cols
        txt = "👁️ Show Alias" if is_alias_hidden else "👁️ Hide Alias"
        if hasattr(self, 'btn_toggle_int_alias'):
            self.btn_toggle_int_alias.setText(txt)
        if hasattr(self, 'btn_toggle_vat_alias'):
            self.btn_toggle_vat_alias.setText(txt)

    def _toggle_ledger_alias_visibility(self):
        """Toggle visibility of Alias column in Int. and VAT Ledger tables."""
        visible_cols = self.get_visible_column_keys()
        if "Alias" in visible_cols:
            visible_cols.remove("Alias")
        else:
            visible_cols.add("Alias")
        self.save_visible_column_keys(visible_cols)
        self.apply_column_visibility()
        self._update_int_totals()
        self._update_vat_totals()

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
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["int_debtors"] = debtors
        self._populate_ledger_table(self.int_table, debtors)
        self.apply_column_visibility()
        self._update_int_totals()
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("int_ledger")

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
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["vat_debtors"] = debtors
        self._populate_ledger_table(self.vat_table, debtors)
        self.apply_column_visibility()
        self._update_vat_totals()
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("vat_ledger")

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
                it_op = tbl.item(r, 3)
                if it_op and it_op.text().strip():
                    try:
                        tot_op += float(it_op.text().replace(",", ""))
                    except Exception:
                        pass
                it_cl = tbl.item(r, 4)
                if it_cl and it_cl.text().strip():
                    try:
                        tot_cl += float(it_cl.text().replace(",", ""))
                    except Exception:
                        pass
                it_eop = tbl.item(r, 9)
                if it_eop and it_eop.text().strip():
                    try:
                        tot_exp_op += float(it_eop.text().replace(",", ""))
                    except Exception:
                        pass
                it_ecl = tbl.item(r, 10)
                if it_ecl and it_ecl.text().strip():
                    try:
                        tot_exp_cl += float(it_ecl.text().replace(",", ""))
                    except Exception:
                        pass

        def _fmt(val):
            return f"-₹{abs(val):,.2f}" if val < 0 else f"₹{val:,.2f}"

        totals_dict = {
            3: _fmt(tot_op),
            4: _fmt(tot_cl),
        }
        if tot_exp_op != 0.0:
            totals_dict[9] = _fmt(tot_exp_op)
        if tot_exp_cl != 0.0:
            totals_dict[10] = _fmt(tot_exp_cl)

        footer.setColumnHidden(2, tbl.isColumnHidden(2))
        footer.update_totals(totals_dict, label_col=1, label_text="Grand Total")
        if lbl_count:
            total_rows = tbl.rowCount()
            if visible_count < total_rows:
                lbl_count.setText(f"<b>{visible_count}</b> / {total_rows} records")
            else:
                lbl_count.setText(f"<b>{visible_count}</b> records")

    def _toggle_conf_alias_visibility(self):
        """Toggle visibility of Alias column (Col 2) in Debtor and Creditor Vat Conf tables."""
        self._hide_conf_alias = not getattr(self, '_hide_conf_alias', False)
        if hasattr(self, 'debtor_table'):
            self.debtor_table.setColumnHidden(2, self._hide_conf_alias)
            if hasattr(self, 'debtor_footer'):
                self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
        if hasattr(self, 'creditor_table'):
            self.creditor_table.setColumnHidden(2, self._hide_conf_alias)
            if hasattr(self, 'creditor_footer'):
                self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))
        txt = "👁️ Show Alias" if self._hide_conf_alias else "👁️ Hide Alias"
        if hasattr(self, 'btn_toggle_debtor_alias'):
            self.btn_toggle_debtor_alias.setText(txt)
        if hasattr(self, 'btn_toggle_creditor_alias'):
            self.btn_toggle_creditor_alias.setText(txt)

    def _toggle_mapping_alias_visibility(self):
        """Toggle visibility of VAT Alias (Col 2) and Internal Alias (Col 4) in Mapping table."""
        self._hide_mapping_alias = not getattr(self, '_hide_mapping_alias', False)
        if hasattr(self, 'mapping_table'):
            self.mapping_table.setColumnHidden(2, self._hide_mapping_alias)
            self.mapping_table.setColumnHidden(4, self._hide_mapping_alias)
        txt = "👁️ Show Alias" if self._hide_mapping_alias else "👁️ Hide Alias"
        if hasattr(self, 'btn_toggle_mapping_alias'):
            self.btn_toggle_mapping_alias.setText(txt)

    def refresh_mapping_table(self, select_group_id: int = 0):
        """Populate Mapping table and Unassigned Internal Ledgers panel for active VAT company."""
        if not self.db_name or not self.active_vat_company:
            self.mapping_table.setRowCount(0)
            if hasattr(self, 'unassigned_list'):
                self.unassigned_list.clear()
            if hasattr(self, 'lbl_unmapped_badge'):
                self.lbl_unmapped_badge.setVisible(False)
            return

        mappings = load_vat_mappings(self.db_name, self.active_vat_company)
        unassigned_int = get_unassigned_internal_debtors(self.db_name, self.active_vat_company)
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["mappings"] = mappings
        self._cached_data["unassigned_int"] = unassigned_int
        self._populate_mapping_from_data(mappings)
        self._populate_unassigned_list(unassigned_int)
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("mapping")

        if select_group_id:
            for r in range(self.mapping_table.rowCount()):
                it = self.mapping_table.item(r, 0)
                if it and it.data(Qt.ItemDataRole.UserRole) == select_group_id:
                    self.mapping_table.selectRow(r)
                    self.mapping_table.scrollToItem(it)
                    break

    def _populate_mapping_from_data(self, mappings: list):
        """Fill the mapping table using vertical sub-row cells for multiple ledgers per group.

        Columns:
        0: # (spanned across group rows)
        1: VAT Ledger
        2: VAT Alias
        3: Internal Ledger
        4: Internal Alias
        5: Manual Name (spanned across group rows)
        6: Status (spanned across group rows)
        """
        self.mapping_table.blockSignals(True)
        self.mapping_table.clearSpans()

        total_rows = 0
        group_specs = []
        unmapped_count = 0

        for m in mappings:
            v_ledgers = [v for v in m.get("vat_ledgers", []) if v and v.strip()]
            v_aliases = m.get("vat_aliases", [])
            i_ledgers = [i for i in m.get("internal_ledgers", []) if i and i.strip()]
            i_aliases = m.get("internal_aliases", [])

            if not v_ledgers and m.get("vat_ledger"):
                v_ledgers = [m.get("vat_ledger")]
                v_aliases = [""]
            if not i_ledgers and m.get("internal_ledger"):
                i_ledgers = [m.get("internal_ledger")]
                i_aliases = [""]

            n_rows = max(len(v_ledgers), len(i_ledgers), 1)
            group_specs.append((m, v_ledgers, v_aliases, i_ledgers, i_aliases, n_rows))
            total_rows += n_rows

            is_unmapped = m.get("is_unmapped", False) or (not i_ledgers)
            if is_unmapped:
                unmapped_count += 1

        self.mapping_table.setRowCount(total_rows)

        cur_row = 0
        for grp_idx, (m, v_ledgers, v_aliases, i_ledgers, i_aliases, n_rows) in enumerate(group_specs, start=1):
            start_row = cur_row
            group_id = m.get("group_id", 0) or m.get("id", 0)
            man_name = m.get("manual_name", "") or ""
            is_unmapped = m.get("is_unmapped", False) or (not i_ledgers)
            is_merged = m.get("is_merged", False) or (len(v_ledgers) > 1)

            if is_unmapped:
                status_text = "🔴 Unmapped"
            elif is_merged:
                v_cnt = len(v_ledgers)
                i_cnt = len(i_ledgers)
                status_text = f"🔗 Merged ({v_cnt} VAT : {i_cnt} Int)" if i_cnt > 1 else f"🔗 Merged ({v_cnt} VAT)"
            elif len(i_ledgers) > 1:
                status_text = f"1 : {len(i_ledgers)}"
            else:
                status_text = "Mapped"

            if is_unmapped:
                bg_color = QColor("#fecaca")
                fg_color = QColor("#991b1b")
                status_fg = QColor("#991b1b")
            else:
                bg_color = QColor("#ffffff") if (grp_idx % 2 == 1) else QColor("#f8fafc")
                fg_color = QColor("#0f172a")
                status_fg = QColor("#2563eb") if is_merged else QColor("#059669")

            for k in range(n_rows):
                r = start_row + k

                # Col 0: #
                it_num = QTableWidgetItem(str(grp_idx) if k == 0 else "")
                it_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_num.setBackground(bg_color)
                it_num.setForeground(fg_color)
                it_num.setData(Qt.ItemDataRole.UserRole, group_id)
                it_num._mapping_group = m
                it_num.setFlags(it_num.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_unmapped:
                    f = it_num.font()
                    f.setBold(True)
                    it_num.setFont(f)
                self.mapping_table.setItem(r, 0, it_num)

                # Col 1: VAT Ledger
                v_name = v_ledgers[k] if k < len(v_ledgers) else ""
                if v_name.lower() in ("none", "nan", "null"):
                    v_name = ""
                it_vl = QTableWidgetItem(v_name)
                it_vl.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                it_vl.setBackground(bg_color)
                it_vl.setForeground(fg_color)
                it_vl.setData(Qt.ItemDataRole.UserRole, group_id)
                it_vl.setData(Qt.ItemDataRole.UserRole + 2, v_name)
                it_vl._mapping_group = m
                if is_unmapped:
                    f = it_vl.font()
                    f.setBold(True)
                    it_vl.setFont(f)
                if not self._can_edit:
                    it_vl.setFlags(it_vl.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 1, it_vl)

                # Col 2: VAT Alias (Read-only)
                v_alias = v_aliases[k] if k < len(v_aliases) else ""
                if v_alias.lower() in ("none", "nan", "null"):
                    v_alias = ""
                it_va = QTableWidgetItem(v_alias)
                it_va.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                it_va.setBackground(bg_color)
                it_va.setForeground(fg_color)
                it_va.setData(Qt.ItemDataRole.UserRole, group_id)
                it_va._mapping_group = m
                it_va.setFlags(it_va.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 2, it_va)

                # Col 3: Internal Ledger
                i_name = i_ledgers[k] if k < len(i_ledgers) else ""
                if i_name.lower() in ("none", "nan", "null"):
                    i_name = ""
                it_il = QTableWidgetItem(i_name)
                it_il.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                it_il.setBackground(bg_color)
                it_il.setForeground(fg_color)
                it_il.setData(Qt.ItemDataRole.UserRole, group_id)
                it_il.setData(Qt.ItemDataRole.UserRole + 2, i_name)
                it_il._mapping_group = m
                if is_unmapped:
                    f = it_il.font()
                    f.setBold(True)
                    it_il.setFont(f)
                if not self._can_edit:
                    it_il.setFlags(it_il.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 3, it_il)

                # Col 4: Internal Alias (Read-only)
                i_alias = i_aliases[k] if k < len(i_aliases) else ""
                if i_alias.lower() in ("none", "nan", "null"):
                    i_alias = ""
                it_ia = QTableWidgetItem(i_alias)
                it_ia.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                it_ia.setBackground(bg_color)
                it_ia.setForeground(fg_color)
                it_ia.setData(Qt.ItemDataRole.UserRole, group_id)
                it_ia._mapping_group = m
                it_ia.setFlags(it_ia.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 4, it_ia)

                # Col 5: Manual Name
                it_mn = QTableWidgetItem(man_name if k == 0 else "")
                it_mn.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                it_mn.setBackground(bg_color)
                it_mn.setForeground(fg_color)
                it_mn.setData(Qt.ItemDataRole.UserRole, group_id)
                it_mn._mapping_group = m
                if not self._can_edit:
                    it_mn.setFlags(it_mn.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mapping_table.setItem(r, 5, it_mn)

            if n_rows > 1:
                self.mapping_table.setSpan(start_row, 0, n_rows, 1)
                self.mapping_table.setSpan(start_row, 5, n_rows, 1)

            cur_row += n_rows

        # Maintain alias column visibility
        hide_alias = getattr(self, '_hide_mapping_alias', False)
        self.mapping_table.setColumnHidden(2, hide_alias)
        self.mapping_table.setColumnHidden(4, hide_alias)

        self.mapping_table.blockSignals(False)

        # Update Unmapped VAT badge
        if hasattr(self, 'lbl_unmapped_badge'):
            if unmapped_count > 0:
                self.lbl_unmapped_badge.setText(f"🔴 {unmapped_count} Unmapped VAT")
                self.lbl_unmapped_badge.setVisible(True)
            else:
                self.lbl_unmapped_badge.setVisible(False)

        # Reset button states
        self._on_mapping_selection_changed()

    def _populate_unassigned_list(self, unassigned_items: list = None):
        """Populate the right-side Unassigned Internal Ledgers list."""
        if not hasattr(self, 'unassigned_list'):
            return

        if unassigned_items is None:
            if hasattr(self, '_cached_data') and self._cached_data and "unassigned_int" in self._cached_data:
                unassigned_items = self._cached_data.get("unassigned_int", [])
            elif self.db_name and self.active_vat_company:
                unassigned_items = get_unassigned_internal_debtors(self.db_name, self.active_vat_company)
            else:
                unassigned_items = []

        self._cached_unassigned = unassigned_items or []
        query = self.unassigned_search.text().strip().lower() if hasattr(self, 'unassigned_search') else ""

        self.unassigned_list.blockSignals(True)
        self.unassigned_list.clear()

        for entry in self._cached_unassigned:
            if isinstance(entry, dict):
                name = (entry.get("Name") or "").strip()
                alias = (entry.get("Alias") or "").strip()
            else:
                name = str(entry).strip()
                alias = ""

            if name.lower() in ("none", "nan", "null"):
                name = ""
            if alias.lower() in ("none", "nan", "null"):
                alias = ""

            if not name:
                continue

            if query:
                match = (query in name.lower()) or (query in alias.lower())
                if not match:
                    continue

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setData(Qt.ItemDataRole.UserRole + 1, alias)
            self.unassigned_list.addItem(item)

        self.unassigned_list.blockSignals(False)

        count_total = len(self._cached_unassigned)
        if hasattr(self, 'lbl_unassigned_count'):
            self.lbl_unassigned_count.setText(str(count_total))

        if hasattr(self, 'btn_toggle_unassigned'):
            arrow = "❯" if hasattr(self, 'unassigned_panel') and self.unassigned_panel.isVisible() else "❮"
            self.btn_toggle_unassigned.setText(f"📋 Unassigned Internal ({count_total}) {arrow}")

        self._on_unassigned_selection_changed()

    def refresh_vat_conf_tables(self):
        """Populate Debtor and Creditor Vat Conf tables."""
        if not self.db_name or not self.active_vat_company:
            self.debtor_table.setRowCount(0)
            self.creditor_table.setRowCount(0)
            return
        d_rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, "Debtor")
        c_rows = load_vat_conf_table_data(self.db_name, self.active_vat_company, "Creditor")
        if not hasattr(self, '_cached_data') or self._cached_data is None:
            self._cached_data = {}
        self._cached_data["debtor_conf"] = d_rows
        self._cached_data["creditor_conf"] = c_rows
        self._populate_vat_conf_table_from_data(self.debtor_table, "Debtor", d_rows)
        self._populate_vat_conf_table_from_data(self.creditor_table, "Creditor", c_rows)
        if hasattr(self, '_rendered_tabs'):
            self._rendered_tabs.add("debtor_conf")
            self._rendered_tabs.add("creditor_conf")

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

            # 1: Name (Read-only, pure name, no parentheses)
            raw_name = (r.get("name") or "").strip()
            if raw_name.lower() in ("none", "nan", "null"):
                raw_name = ""
            it_name = QTableWidgetItem(raw_name)
            it_name.setData(Qt.ItemDataRole.UserRole, raw_name)
            it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 1, it_name)

            # 2: Alias (Read-only, pure alias, no parentheses)
            raw_alias = (r.get("alias") or "").strip()
            if raw_alias.lower() in ("none", "nan", "null"):
                raw_alias = ""
            it_alias = QTableWidgetItem(raw_alias)
            it_alias.setData(Qt.ItemDataRole.UserRole, raw_alias)
            it_alias.setFlags(it_alias.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 2, it_alias)

            # 3: Opening Amount (Read-only, right-aligned)
            it_op = QTableWidgetItem(f"{r['opening_amount']:,.2f}")
            it_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it_op.setFlags(it_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 3, it_op)

            # 4: Closing Amount (Read-only, right-aligned)
            it_cl = QTableWidgetItem(f"{r['closing_amount']:,.2f}")
            it_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it_cl.setFlags(it_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 4, it_cl)

            # 5: Need Print ? (Read-only, centered)
            it_np = QTableWidgetItem(r["need_print"])
            it_np.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r["need_print"] == "Yes":
                it_np.setForeground(QColor("#059669"))
                font = it_np.font()
                font.setBold(True)
                it_np.setFont(font)
            it_np.setFlags(it_np.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 5, it_np)

            # 6: Did You Print (Editable Yes/No, accepts 1/0, Y/N, T/F)
            it_dyp = QTableWidgetItem(r["did_you_print"])
            it_dyp.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not self._can_edit:
                it_dyp.setFlags(it_dyp.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 6, it_dyp)

            # 7: CRM (Editable autocomplete)
            it_crm = QTableWidgetItem(r["crm"])
            if not self._can_edit:
                it_crm.setFlags(it_crm.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 7, it_crm)

            # 8: Get Back (Editable Yes/No, accepts 1/0, Y/N, T/F)
            it_gb = QTableWidgetItem(r["get_back"])
            it_gb.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not self._can_edit:
                it_gb.setFlags(it_gb.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 8, it_gb)

            # 9: Opening ? (Editable numeric, compared against Opening Amount)
            it_exp_op = QTableWidgetItem(r["expected_opening"])
            it_exp_op.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if not self._can_edit:
                it_exp_op.setFlags(it_exp_op.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 9, it_exp_op)

            # 10: Closing ? (Editable numeric, compared against Closing Amount)
            it_exp_cl = QTableWidgetItem(r["expected_closing"])
            it_exp_cl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if not self._can_edit:
                it_exp_cl.setFlags(it_exp_cl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r_idx, 10, it_exp_cl)

            # Apply full row solid red highlight if mismatched or empty
            self._update_vat_conf_row_style(tbl, r_idx)

        # Maintain alias column visibility
        tbl.setColumnHidden(2, getattr(self, '_hide_conf_alias', False))

        tbl.blockSignals(False)
        if group_type == "Debtor" and hasattr(self, 'debtor_footer'):
            self._update_conf_totals(self.debtor_table, self.debtor_footer, getattr(self, 'lbl_debtor_count', None))
        elif group_type == "Creditor" and hasattr(self, 'creditor_footer'):
            self._update_conf_totals(self.creditor_table, self.creditor_footer, getattr(self, 'lbl_creditor_count', None))

    def _update_vat_conf_row_style(self, tbl: QTableWidget, row: int):
        """If expected amount does not match actual amount or either is empty, paint the FULL ROW in RED."""
        act_op_item = tbl.item(row, 3)
        act_cl_item = tbl.item(row, 4)
        exp_op_item = tbl.item(row, 9)
        exp_cl_item = tbl.item(row, 10)

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
                if c == 5 and it.text() == "Yes":
                    it.setForeground(QColor("#059669"))
                else:
                    it.setForeground(normal_fg)

    # ── MAPPING EVENT HANDLERS & PANEL CONTROLS ─────────────────────

    def _on_mapping_selection_changed(self):
        """Update button enabled states based on current selection in Mapping table."""
        if not hasattr(self, 'btn_merge_mapping'):
            return

        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        count = len(group_ids)

        if count >= 2:
            self.btn_merge_mapping.setEnabled(True)
            self.btn_merge_mapping.setText(f"🔗 Merge Selected ({count})")
        else:
            self.btn_merge_mapping.setEnabled(False)
            self.btn_merge_mapping.setText("🔗 Merge Selected")

        has_any_mapped = False
        has_merged = False
        for gid in group_ids:
            for r in range(self.mapping_table.rowCount()):
                it = self.mapping_table.item(r, 0)
                if it and it.data(Qt.ItemDataRole.UserRole) == gid:
                    mapping_data = getattr(it, '_mapping_group', {})
                    if not mapping_data.get("is_unmapped", False):
                        has_any_mapped = True
                    if mapping_data.get("is_merged", False) or len(mapping_data.get("vat_ledgers", [])) > 1:
                        has_merged = True
                    break

        self.btn_demerge_mapping.setEnabled(count == 1 and has_merged)
        self.btn_unmap_mapping.setEnabled(has_any_mapped)

        has_unassigned_sel = bool(self.unassigned_list.selectedItems()) if hasattr(self, 'unassigned_list') else False
        if hasattr(self, 'btn_assign_internal'):
            self.btn_assign_internal.setEnabled(has_unassigned_sel and count == 1)

    def _on_unassigned_selection_changed(self):
        """Update assign button when an unassigned internal debtor is selected."""
        if not hasattr(self, 'btn_assign_internal'):
            return
        has_unassigned_sel = bool(self.unassigned_list.selectedItems())
        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)
        self.btn_assign_internal.setEnabled(has_unassigned_sel and len(group_ids) == 1)

    def _filter_unassigned_list(self, text: str):
        """Filter the unassigned internal list in real time matching Name and Alias."""
        q = text.strip().lower()
        visible_cnt = 0
        total_cnt = self.unassigned_list.count()
        for r in range(total_cnt):
            it = self.unassigned_list.item(r)
            if not it:
                continue
            name = str(it.data(Qt.ItemDataRole.UserRole) or "").lower()
            alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").lower()
            txt = it.text().lower()
            match = (not q) or (q in txt) or (q in name) or (q in alias)
            it.setHidden(not match)
            if match:
                visible_cnt += 1
        if hasattr(self, 'lbl_unassigned_count'):
            if q and visible_cnt < total_cnt:
                self.lbl_unassigned_count.setText(f"{visible_cnt} / {total_cnt}")
            else:
                self.lbl_unassigned_count.setText(str(total_cnt))

    def _toggle_unassigned_panel(self):
        """Toggle visibility of right-side Unassigned Internal Ledgers panel."""
        if not hasattr(self, 'unassigned_panel'):
            return
        is_vis = self.unassigned_panel.isVisible()
        self.unassigned_panel.setVisible(not is_vis)
        arrow = "❯" if not is_vis else "❮"
        cnt = len(getattr(self, '_cached_unassigned', []))
        self.btn_toggle_unassigned.setText(f"📋 Unassigned Internal ({cnt}) {arrow}")

    def _collapse_unassigned_panel(self):
        """Collapse the unassigned internal panel to the right."""
        if hasattr(self, 'unassigned_panel'):
            self.unassigned_panel.hide()
            cnt = len(getattr(self, '_cached_unassigned', []))
            self.btn_toggle_unassigned.setText(f"📋 Unassigned Internal ({cnt}) ❮")

    def _assign_selected_internal_ledger(self):
        """Assign the selected unassigned internal debtor to the selected VAT group in the table."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        if len(group_ids) != 1:
            QMessageBox.information(self, "Select VAT Row", "Please select exactly one VAT group in the mapping table to assign to.")
            return

        unassigned_items = self.unassigned_list.selectedItems()
        if not unassigned_items:
            QMessageBox.information(self, "Select Internal Ledger", "Please select an internal ledger from the unassigned list.")
            return

        group_id = group_ids[0]
        int_name = str(unassigned_items[0].data(Qt.ItemDataRole.UserRole) or unassigned_items[0].text()).strip()
        ok = assign_internal_ledger_to_group(self.db_name, self.active_vat_company, group_id, int_name)
        if ok:
            self.refresh_mapping_table(select_group_id=group_id)

    def _on_unassigned_item_double_clicked(self, item: QListWidgetItem):
        """Double-clicking an unassigned internal debtor assigns it to selected VAT group (or first unmapped)."""
        if not self._can_edit:
            return
        int_name = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
        selected_indexes = self.mapping_table.selectedIndexes()
        target_group_id = None
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid:
                target_group_id = gid
                break

        if not target_group_id:
            for r in range(self.mapping_table.rowCount()):
                it = self.mapping_table.item(r, 0)
                if it and getattr(it, '_mapping_group', {}).get("is_unmapped", False):
                    target_group_id = it.data(Qt.ItemDataRole.UserRole)
                    break

        if not target_group_id:
            QMessageBox.information(self, "Select VAT Row", "Please select a VAT row in the mapping table to assign to.")
            return

        ok = assign_internal_ledger_to_group(self.db_name, self.active_vat_company, target_group_id, int_name)
        if ok:
            self.refresh_mapping_table(select_group_id=target_group_id)

    def _merge_selected_mappings(self):
        """Merge selected VAT mapping rows into a unified group."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        if len(group_ids) < 2:
            return

        target_gid = merge_mapping_groups(self.db_name, self.active_vat_company, group_ids)
        if target_gid:
            self.refresh_mapping_table(select_group_id=target_gid)

    def _demerge_selected_mapping(self):
        """Demerge the selected merged group back into individual VAT ledger groups."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        if len(group_ids) != 1:
            return

        group_id = group_ids[0]
        ok = demerge_mapping_group(self.db_name, self.active_vat_company, group_id)
        if ok:
            self.refresh_mapping_table(select_group_id=group_id)

    def _unmap_selected_mapping(self):
        """Clear/unmap all internal ledgers from the selected group, returning them to unassigned list."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in group_ids:
                group_ids.append(gid)

        if not group_ids:
            return

        for gid in group_ids:
            unmap_vat_group(self.db_name, self.active_vat_company, gid)

        self.refresh_mapping_table()

    def _on_mapping_item_changed(self, item: QTableWidgetItem):
        """User modified an editable cell in Mapping table."""
        if not self._can_edit:
            return
        try:
            row = item.row()
            col = item.column()
            if row < 0 or col not in (1, 3, 5):
                return

            group_id = item.data(Qt.ItemDataRole.UserRole)
            if not group_id:
                it0 = self.mapping_table.item(row, 0)
                group_id = it0.data(Qt.ItemDataRole.UserRole) if it0 else 0
            if not group_id:
                return

            active_comp = self.active_vat_company
            if not active_comp and self.db_name:
                active_comp = get_active_vat_company(self.db_name)
                self.active_vat_company = active_comp
            if not active_comp:
                logger.warning(f"[_on_mapping_item_changed] No active VAT company configured for db '{self.db_name}'")
                return

            if col == 1:  # VAT Ledger
                old_name = str(item.data(Qt.ItemDataRole.UserRole + 2) or "").strip()
                v_val = item.text().strip()
                if not v_val:
                    self.refresh_mapping_table(select_group_id=group_id)
                    return
                if v_val != old_name:
                    update_group_vat_ledger(self.db_name, active_comp, group_id, old_name, v_val)
                    QTimer.singleShot(150, lambda gid=group_id: self.refresh_mapping_table(select_group_id=gid))

            elif col == 3:  # Internal Ledger
                old_name = str(item.data(Qt.ItemDataRole.UserRole + 2) or "").strip()
                i_val = item.text().strip()
                if i_val != old_name:
                    update_group_internal_ledger(self.db_name, active_comp, group_id, old_name, i_val)
                    QTimer.singleShot(150, lambda gid=group_id: self.refresh_mapping_table(select_group_id=gid))

            elif col == 5:  # Manual Name
                m_val = item.text().strip()
                set_group_manual_name(self.db_name, active_comp, group_id, m_val)
        except Exception as e:
            logger.error(f"[_on_mapping_item_changed] Failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Save Error", f"Failed to save mapping: {e}")

    def _show_mapping_context_menu(self, pos):
        """Right-click context menu on Mapping table."""
        if not self._can_edit:
            return
        selected_indexes = self.mapping_table.selectedIndexes()
        selected_group_ids = []
        for idx in selected_indexes:
            it = self.mapping_table.item(idx.row(), 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
            if gid and gid not in selected_group_ids:
                selected_group_ids.append(gid)

        if not selected_group_ids:
            row = self.mapping_table.rowAt(pos.y())
            if row >= 0:
                self.mapping_table.selectRow(row)
                it = self.mapping_table.item(row, 0)
                gid = it.data(Qt.ItemDataRole.UserRole) if it else 0
                if gid:
                    selected_group_ids = [gid]
            else:
                return

        menu = QMenu(self)

        # If 2 or more distinct groups selected: offer Merge and Unmap Selected
        if len(selected_group_ids) >= 2:
            act_merge = menu.addAction(f"🔗 Merge Selected ({len(selected_group_ids)})")
            act_unmap_all = menu.addAction(f"Clear / Unmap Selected ({len(selected_group_ids)})")
            menu.addSeparator()
            txt = "👁️ Show Alias Columns" if getattr(self, '_hide_mapping_alias', False) else "👁️ Hide Alias Columns"
            act_toggle_alias = menu.addAction(txt)
            selected_act = menu.exec(self.mapping_table.viewport().mapToGlobal(pos))
            if selected_act == act_merge:
                self._merge_selected_mappings()
            elif selected_act == act_unmap_all:
                self._unmap_selected_mapping()
            elif selected_act == act_toggle_alias:
                self._toggle_mapping_alias_visibility()
            return

        group_id = selected_group_ids[0]
        target_item = None
        for r in range(self.mapping_table.rowCount()):
            it = self.mapping_table.item(r, 0)
            if it and it.data(Qt.ItemDataRole.UserRole) == group_id:
                target_item = it
                break

        if not target_item:
            return

        mapping_data = getattr(target_item, '_mapping_group', {})
        is_merged = mapping_data.get("is_merged", False) or len(mapping_data.get("vat_ledgers", [])) > 1
        is_unmapped = mapping_data.get("is_unmapped", False) or not mapping_data.get("internal_ledgers")
        has_manual = bool(mapping_data.get("manual_name", "").strip())

        act_unmap = None
        act_demerge = None
        act_assign_selected = None
        act_clear_manual = None

        if not is_unmapped:
            act_unmap = menu.addAction("Remove Mapping (Unmap)")

        if is_merged:
            act_demerge = menu.addAction("✂️ Demerge Group")

        # If an unassigned internal ledger is selected in the right panel, offer quick assign
        if hasattr(self, 'unassigned_list') and self.unassigned_list.selectedItems():
            sel_un = self.unassigned_list.selectedItems()[0]
            un_name = sel_un.data(Qt.ItemDataRole.UserRole) or sel_un.text()
            act_assign_selected = menu.addAction(f"Assign '{un_name}'")

        if has_manual:
            act_clear_manual = menu.addAction("Clear Manual Name")

        if is_unmapped and not act_assign_selected:
            act_unmap = menu.addAction("Clear / Reset Row")

        menu.addSeparator()
        txt = "👁️ Show Alias Columns" if getattr(self, '_hide_mapping_alias', False) else "👁️ Hide Alias Columns"
        act_toggle_alias = menu.addAction(txt)

        selected_act = menu.exec(self.mapping_table.viewport().mapToGlobal(pos))
        if selected_act == act_unmap:
            self._unmap_selected_mapping()
        elif selected_act == act_demerge:
            self._demerge_selected_mapping()
        elif selected_act == act_assign_selected:
            self._assign_selected_internal_ledger()
        elif selected_act == act_clear_manual:
            active_comp = self.active_vat_company or get_active_vat_company(self.db_name)
            set_group_manual_name(self.db_name, active_comp, group_id, "")
            self.refresh_mapping_table(select_group_id=group_id)
        elif selected_act == act_toggle_alias:
            self._toggle_mapping_alias_visibility()

    def _on_vat_conf_item_changed(self, item: QTableWidgetItem, group_type: str, tbl: QTableWidget):
        """User modified an editable cell in Vat Conf (Debtor/Creditor)."""
        col = item.column()
        row = item.row()
        name_item = tbl.item(row, 1)
        if not name_item:
            return
        ledger_name = str(name_item.data(Qt.ItemDataRole.UserRole) or name_item.text()).strip()
        val = item.text().strip()

        active_comp = self.active_vat_company
        if not active_comp and self.db_name:
            active_comp = get_active_vat_company(self.db_name)
            self.active_vat_company = active_comp
        if not active_comp:
            logger.warning(f"[_on_vat_conf_item_changed] No active VAT company configured for db '{self.db_name}'")
            return

        # 0: Cartoon Number (SN.) Validation, Swap on Duplicate & Persistence
        if col == 0:
            old_val = getattr(item, '_prev_sn', '')
            if val == old_val:
                return

            is_valid, err_msg = validate_cartoon_number(val)
            if not is_valid:
                tbl.blockSignals(True)
                item.setText(old_val)
                tbl.blockSignals(False)
                QTimer.singleShot(0, lambda msg=err_msg: QMessageBox.warning(self, "Invalid Cartoon Number", msg))
                return

            # Check if this CN already exists on another row in the table
            duplicate_row = -1
            other_ledger_name = ""
            if val:
                for r in range(tbl.rowCount()):
                    if r == row:
                        continue
                    other_it = tbl.item(r, 0)
                    if other_it and other_it.text().strip() == val:
                        duplicate_row = r
                        other_name_it = tbl.item(r, 1)
                        other_ledger_name = str(other_name_it.data(Qt.ItemDataRole.UserRole) or other_name_it.text()).strip() if other_name_it else ""
                        break

            if duplicate_row >= 0:
                # Target CN is already assigned to another ledger — swap CNs to maintain uniqueness
                other_it = tbl.item(duplicate_row, 0)
                swap_sn = old_val
                if not swap_sn or (swap_sn.isdigit() and int(swap_sn) in _EXCLUDED_CNS):
                    # Find next available non-reserved CN
                    used = set()
                    for r in range(tbl.rowCount()):
                        if r in (row, duplicate_row):
                            continue
                        it_tmp = tbl.item(r, 0)
                        t_tmp = it_tmp.text().strip() if it_tmp else ""
                        if t_tmp.isdigit() and int(t_tmp) > 0:
                            used.add(int(t_tmp))
                    if val.isdigit():
                        used.add(int(val))
                    num = 1
                    while num in used or num in _EXCLUDED_CNS:
                        num += 1
                    swap_sn = str(num)

                tbl.blockSignals(True)
                other_it.setText(swap_sn)
                other_it._prev_sn = swap_sn
                item._prev_sn = val
                tbl.blockSignals(False)

                try:
                    save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "sn", val)
                    if other_ledger_name:
                        save_vat_conf_field(self.db_name, active_comp, group_type, other_ledger_name, "sn", swap_sn)
                except Exception as e:
                    logger.error(f"Failed to swap SN: {e}")
                return

            item._prev_sn = val
            try:
                save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, "sn", val)
            except Exception as e:
                logger.error(f"Failed to save SN: {e}")
            return

        # 6 & 8: Normalize Yes/No input
        if col in (6, 8):
            val = normalize_yes_no(val)
            tbl.blockSignals(True)
            item.setText(val)
            tbl.blockSignals(False)

        field_map = {
            6: "did_you_print",
            7: "crm",
            8: "get_back",
            9: "expected_opening",
            10: "expected_closing",
        }
        field_name = field_map.get(col)
        if not field_name:
            return

        try:
            save_vat_conf_field(self.db_name, active_comp, group_type, ledger_name, field_name, val)

            # Update comparison highlight across the full row whenever Opening ? or Closing ? is modified
            if col in (9, 10):
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
            if not it:
                self.int_table.setRowHidden(r, bool(q))
                continue
            name = str(it.data(Qt.ItemDataRole.UserRole) or "").lower()
            alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").lower()
            txt = it.text().lower()
            match = (not q) or (q in txt) or (q in name) or (q in alias)
            self.int_table.setRowHidden(r, not match)
        self._update_int_totals()

    def _filter_vat_table(self, query: str):
        q = query.strip().lower()
        for r in range(self.vat_table.rowCount()):
            it = self.vat_table.item(r, 0)
            if not it:
                self.vat_table.setRowHidden(r, bool(q))
                continue
            name = str(it.data(Qt.ItemDataRole.UserRole) or "").lower()
            alias = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").lower()
            txt = it.text().lower()
            match = (not q) or (q in txt) or (q in name) or (q in alias)
            self.vat_table.setRowHidden(r, not match)
        self._update_vat_totals()

    def _filter_mapping_table(self, query: str):
        q = query.strip().lower()
        total_rows = self.mapping_table.rowCount()
        if total_rows == 0:
            return
        if not q:
            for r in range(total_rows):
                self.mapping_table.setRowHidden(r, False)
            return

        # Group row indices by group_id
        groups = {}
        for r in range(total_rows):
            it = self.mapping_table.item(r, 0)
            gid = it.data(Qt.ItemDataRole.UserRole) if it else r
            groups.setdefault(gid, []).append(r)

        for gid, rows in groups.items():
            first_it = self.mapping_table.item(rows[0], 0)
            m = getattr(first_it, "_mapping_group", {}) if first_it else {}
            v_names = " ".join(m.get("vat_ledgers", [])).lower()
            v_aliases = " ".join(m.get("vat_aliases", [])).lower()
            i_names = " ".join(m.get("internal_ledgers", [])).lower()
            i_aliases = " ".join(m.get("internal_aliases", [])).lower()
            m_names = str(m.get("manual_name") or "").lower()

            group_match = (
                (q in v_names) or (q in v_aliases) or
                (q in i_names) or (q in i_aliases) or (q in m_names)
            )

            if not group_match:
                for r in rows:
                    for c in range(self.mapping_table.columnCount()):
                        it = self.mapping_table.item(r, c)
                        if it and q in it.text().lower():
                            group_match = True
                            break
                    if group_match:
                        break

            for r in rows:
                self.mapping_table.setRowHidden(r, not group_match)

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

        if hasattr(self, '_int_worker') and self._int_worker:
            self._int_worker.wait()
            self._int_worker = None

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "Internal Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync Internal Ledger:\n{error}")
        else:
            QMessageBox.information(self, "Sync Complete", f"Synced {count} internal ledger entries.")
            self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

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

        if hasattr(self, '_vat_worker') and self._vat_worker:
            self._vat_worker.wait()
            self._vat_worker = None

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "VAT Ledger sync was cancelled.")
        elif error:
            QMessageBox.warning(self, "Sync Issue", f"Failed to sync VAT Ledgers:\n{error}")
        else:
            QMessageBox.information(
                self, "Sync Complete",
                f"Successfully synced {count} VAT ledger entries for '{self.active_vat_company}'."
            )
            self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

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
        # Refresh all VAT views off-thread with lazy rendering
        self.load_data(self.current_company_path, company_name=self.current_company_name, force=True)

    # ── PERMISSION CONTROL ───────────────────────────────────────────

    def apply_edit_mode(self, can_edit: bool):
        """Enforce display-only mode based on user permissions."""
        self._can_edit = can_edit
        self.mapping_table._can_edit = can_edit
        self.btn_vat_company.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_int'):
            self.btn_tab_sync_int.setEnabled(can_edit)
        if hasattr(self, 'btn_tab_sync_vat'):
            self.btn_tab_sync_vat.setEnabled(can_edit)
        # Lock mapping table editing across editable columns (1: VAT, 3: Int, 5: Manual)
        for r in range(self.mapping_table.rowCount()):
            for c in (1, 3, 5):
                it = self.mapping_table.item(r, c)
                if it:
                    if can_edit:
                        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Propagate _can_edit to conf tables so VatConfDelegate can check it
        self.debtor_table._can_edit = can_edit
        self.creditor_table._can_edit = can_edit

        # Lock vat conf tables editing (Col 0: SN, Col 6: Did You Print, Col 7: CRM, Col 8: Get Back, Col 9: Opening ?, Col 10: Closing ?)
        for tbl in (self.debtor_table, self.creditor_table):
            for r in range(tbl.rowCount()):
                for c in [0, 6, 7, 8, 9, 10]:
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
