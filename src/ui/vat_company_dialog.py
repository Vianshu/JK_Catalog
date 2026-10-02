"""
VAT Company Configuration Dialog (Multi-Profile).

Allows the user to:
- View the currently active VAT Company
- Select from previously configured VAT companies via a dropdown
- Add a new VAT Company
- Edit the name of a VAT Company
- Save and set the selected VAT Company as active persistently in SQL Server
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from src.logic.vat_manager import (
    get_active_vat_company, set_active_vat_company, get_all_vat_companies
)
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class VatCompanyDialog(QDialog):
    company_changed = pyqtSignal(str)

    def __init__(self, db_name: str, parent=None):
        super().__init__(parent)
        self.db_name = db_name
        self.setObjectName("VatCompanyDialog")
        self.setWindowTitle("VAT Company Configuration")
        self.resize(440, 240)
        self.setModal(True)
        self.init_ui()
        self.load_companies()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Info
        header = QLabel("Configure VAT Company")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #0f172a;")
        layout.addWidget(header)

        desc = QLabel(
            "Select an existing VAT company or add a new one. "
            "Each VAT company keeps its own independent ledger data, mappings, and VAT Conf details."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(desc)

        # Active company selector
        form_frame = QFrame()
        form_frame.setStyleSheet("background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px;")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(10)

        select_lbl = QLabel("Select Active VAT Company:")
        select_lbl.setStyleSheet("font-weight: 600; color: #334155;")
        form_layout.addWidget(select_lbl)

        self.company_combo = QComboBox()
        self.company_combo.setEditable(True)
        self.company_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.company_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 10px;
                background: white;
                font-size: 13px;
            }
            QComboBox:focus {
                border-color: #3b82f6;
            }
        """)
        form_layout.addWidget(self.company_combo)

        layout.addWidget(form_frame)

        # Button Box
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 7px 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #e2e8f0;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("Save & Set Active")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 7px 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #047857;
            }
        """)
        self.btn_save.clicked.connect(self.save_and_activate)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def load_companies(self):
        """Populate the combo box with all saved VAT companies."""
        if not self.db_name:
            return
        try:
            comps = get_all_vat_companies(self.db_name)
            active = get_active_vat_company(self.db_name)

            self.company_combo.clear()
            for c in comps:
                self.company_combo.addItem(c)

            if active:
                idx = self.company_combo.findText(active)
                if idx >= 0:
                    self.company_combo.setCurrentIndex(idx)
                else:
                    self.company_combo.setEditText(active)
            elif comps:
                self.company_combo.setCurrentIndex(0)
        except Exception as e:
            logger.error(f"[load_companies] error: {e}")

    def save_and_activate(self):
        """Persist the selected or entered VAT company name and close."""
        comp_name = self.company_combo.currentText().strip()
        if not comp_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter or select a valid VAT Company name.")
            return

        try:
            set_active_vat_company(self.db_name, comp_name)
            self.company_changed.emit(comp_name)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to save VAT Company: {e}")
