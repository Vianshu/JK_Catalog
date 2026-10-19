"""
CRM Mapping Dialog for VAT Working -> Balance -> VAT Conf. -> Debtor tab.

Allows users to map unique VAT Debtor Sub Groups to CRM Names with autocomplete.
Mappings are persisted to dbo.vat_subgroup_crm_mapping in SQL Server.
"""

import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

from src.ui.table_nav_mixin import _TallyCompleter
from src.ui.settings import load_crm_list
from src.logic.vat_manager import (
    get_unique_vat_debtor_subgroups,
    load_vat_subgroup_crm_mappings,
    save_vat_subgroup_crm_mappings
)

logger = logging.getLogger(__name__)


class _CrmMappingDelegate(QStyledItemDelegate):
    """Delegate providing seamless CRM autocomplete with _TallyCompleter for the CRM Name column."""

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
        ed = QLineEdit(parent)
        ed.setFrame(False)
        ed.setAutoFillBackground(True)
        ed.setStyleSheet(
            "QLineEdit { background: #ffffff; border: 1px solid #059669; "
            "padding: 2px 6px; margin: 0px; color: #0f172a; font-size: 11px; }"
        )

        crms = self.get_crm_callback() or []
        completer = _TallyCompleter(crms, ed)
        completer.setMaxVisibleItems(10)
        completer.popup().setMinimumWidth(260)
        ed.setCompleter(completer)
        ed.textEdited.connect(completer.update_prefix)

        def _on_crm_activated(selected, e=ed, c=completer):
            c._typed_text = selected
            e.setText(selected)
            self._commit_and_close(e)

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
            val = editor.text().strip()
            model.setData(index, val, Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class VatSubgroupCrmMappingDialog(QDialog):
    """Popup dialog to map Debtor Sub Groups to CRM Names."""

    def __init__(self, db_name: str, vat_company: str, company_path: str = "", parent=None):
        super().__init__(parent)
        self.db_name = db_name
        self.vat_company = vat_company
        self.company_path = company_path

        self.setWindowTitle(f"CRM Mapping — {vat_company}")
        self.resize(640, 520)
        self.setMinimumSize(540, 400)
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(12)

        # Header Title & Description
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        lbl_title = QLabel("Debtor Sub Group to CRM Mapping")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #0f172a;")
        lbl_desc = QLabel("Assign a CRM Name to each Sub Group. Debtor ledgers under that Sub Group will inherit the CRM.")
        lbl_desc.setStyleSheet("font-size: 11px; color: #64748b;")
        header_layout.addWidget(lbl_title)
        header_layout.addWidget(lbl_desc)
        vbox.addLayout(header_layout)

        # Top Bar: Search + Count
        top_bar = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search Sub Group or CRM...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1; border-radius: 4px; background: #ffffff;
                padding: 5px 8px; font-size: 11px; color: #0f172a;
            }
            QLineEdit:focus { border: 1px solid #059669; }
        """)
        self.search_box.textChanged.connect(self._filter_table)
        top_bar.addWidget(self.search_box, stretch=1)

        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #475569; "
            "padding: 4px 8px; background: #f8fafc; border-radius: 4px; border: 1px solid #cbd5e1;"
        )
        top_bar.addWidget(self.lbl_count)
        vbox.addLayout(top_bar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Sub Group Name", "CRM Name"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                font-size: 11px;
                color: #0f172a;
            }
            QHeaderView::section {
                background-color: #f1f5f9;
                color: #334155;
                font-weight: 600;
                font-size: 11px;
                padding: 6px;
                border: none;
                border-bottom: 2px solid #cbd5e1;
                border-right: 1px solid #e2e8f0;
            }
            QTableWidget::item:selected {
                background-color: #ecfdf5;
                color: #065f46;
            }
        """)

        # Install CRM delegate on Column 1
        self.table.setItemDelegateForColumn(
            1, _CrmMappingDelegate(lambda: load_crm_list(self.company_path), self.table)
        )
        vbox.addWidget(self.table, stretch=1)

        # Bottom Buttons Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_clear_all = QPushButton("Clear All")
        self.btn_clear_all.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #475569; font-weight: 600; font-size: 11px;
                padding: 6px 14px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self.btn_clear_all.clicked.connect(self._clear_all_mappings)
        btn_bar.addWidget(self.btn_clear_all)

        btn_bar.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: #ffffff; color: #475569; font-weight: 600; font-size: 11px;
                padding: 6px 16px; border-radius: 4px; border: 1px solid #cbd5e1;
            }
            QPushButton:hover { background: #f8fafc; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save Mapping")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background: #059669; color: white; font-weight: 600; font-size: 11px;
                padding: 6px 20px; border-radius: 4px; border: none;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.btn_save.clicked.connect(self._save_mappings)
        btn_bar.addWidget(self.btn_save)

        vbox.addLayout(btn_bar)

    def _load_data(self):
        """Fetch distinct Debtor Sub Groups and current CRM mappings."""
        subgroups = get_unique_vat_debtor_subgroups(self.db_name, self.vat_company)
        saved_mappings = load_vat_subgroup_crm_mappings(self.db_name, self.vat_company)

        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(subgroups))

        for row, sg in enumerate(subgroups):
            # Col 0: Sub Group Name (Read-only)
            item_sg = QTableWidgetItem(sg)
            item_sg.setFlags(item_sg.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = item_sg.font()
            font.setWeight(QFont.Weight.Medium)
            item_sg.setFont(font)
            item_sg.setForeground(QColor("#0f172a"))
            self.table.setItem(row, 0, item_sg)

            # Col 1: CRM Name (Editable)
            crm_val = saved_mappings.get(sg, "")
            item_crm = QTableWidgetItem(crm_val)
            item_crm.setForeground(QColor("#059669") if crm_val else QColor("#0f172a"))
            self.table.setItem(row, 1, item_crm)

        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._update_count()

    def _update_count(self):
        total = self.table.rowCount()
        visible = sum(1 for r in range(total) if not self.table.isRowHidden(r))
        if visible < total:
            self.lbl_count.setText(f"{visible} / {total} Sub Groups")
        else:
            self.lbl_count.setText(f"{total} Sub Groups")

    def _filter_table(self, query: str):
        q = (query or "").strip().lower()
        for r in range(self.table.rowCount()):
            it_sg = self.table.item(r, 0)
            it_crm = self.table.item(r, 1)
            sg_text = (it_sg.text() if it_sg else "").lower()
            crm_text = (it_crm.text() if it_crm else "").lower()
            match = (not q) or (q in sg_text) or (q in crm_text)
            self.table.setRowHidden(r, not match)
        self._update_count()

    def _clear_all_mappings(self):
        """Clear all CRM names in the table without immediately writing to DB."""
        for r in range(self.table.rowCount()):
            it_crm = self.table.item(r, 1)
            if it_crm:
                it_crm.setText("")

    def _save_mappings(self):
        """Persist all mappings in the table to SQL Server."""
        # Force commit of any active editor in the table before reading
        for ed in self.table.findChildren(QLineEdit):
            idx = self.table.indexAt(ed.pos())
            if idx.isValid() and idx.column() == 1:
                it = self.table.item(idx.row(), 1)
                if it:
                    it.setText(ed.text().strip())
        if self.table.state() == QAbstractItemView.State.EditingState:
            self.table.setCurrentItem(None)

        mappings = {}
        for r in range(self.table.rowCount()):
            it_sg = self.table.item(r, 0)
            it_crm = self.table.item(r, 1)
            if not it_sg:
                continue
            sg = it_sg.text().strip()
            crm = it_crm.text().strip() if it_crm else ""
            if sg:
                mappings[sg] = crm

        success = save_vat_subgroup_crm_mappings(self.db_name, self.vat_company, mappings)
        if success:
            QMessageBox.information(self, "Success", "CRM Mappings saved successfully.")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to save CRM Mappings to database.")
