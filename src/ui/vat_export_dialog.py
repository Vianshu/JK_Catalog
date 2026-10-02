"""
vat_export_dialog.py — Excel Export Dialog for VAT Working Tables.

Auto-selects the currently active table from the open screen/tab/subtab.
Provides clear export path display, quick path change, filename customization,
and persistent export folder setting via QSettings.
"""

import os
import re
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QSettings

from src.ui.table_exporter import export_tables_to_excel
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class VatExportDialog(QDialog):
    """Clean, focused Excel Export Dialog for the active VAT Working table."""

    def __init__(self, table_title: str, table_widget, parent=None):
        super().__init__(parent)
        self.table_title = table_title or "VAT Table"
        self.table_widget = table_widget
        self.settings = QSettings("JKCatalog", "ExportSettings")

        self.setObjectName("VatExportDialog")
        self.setWindowTitle("Export to Excel — VAT Working")
        self.setFixedSize(520, 260)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        # ── 1. Dialog Header ──
        hdr_layout = QVBoxLayout()
        hdr_layout.setSpacing(6)
        title_lbl = QLabel("Export to Excel")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #0f172a;")
        hdr_layout.addWidget(title_lbl)

        # ── 2. Target Info Card (Auto-selected from current screen/tab/subtab) ──
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }
        """)
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(12, 8, 12, 8)

        row_count = self.table_widget.rowCount() if self.table_widget else 0
        info_lbl = QLabel(f"Target: <b>{self.table_title}</b> ({row_count} rows)")
        info_lbl.setStyleSheet("color: #334155; font-size: 13px; border: none; background: transparent;")
        card_lay.addWidget(info_lbl)
        card_lay.addStretch()
        hdr_layout.addWidget(card)
        layout.addLayout(hdr_layout)

        # ── 3. Export Path Row ──
        path_box = QVBoxLayout()
        path_box.setSpacing(4)
        lbl_path = QLabel("Export Location:")
        lbl_path.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        path_box.addWidget(lbl_path)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)

        default_folder = self.settings.value("export_folder", None)
        if not default_folder or not os.path.exists(str(default_folder)):
            legacy_settings = QSettings("TallySync", "VatWorking")
            default_folder = legacy_settings.value("export_folder", None)
        if not default_folder or not os.path.exists(str(default_folder)):
            default_folder = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(default_folder):
            default_folder = os.path.expanduser("~")

        self.path_input = QLineEdit(default_folder)
        self.path_input.setReadOnly(True)
        self.path_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 10px;
                color: #0f172a;
                font-size: 12px;
            }
        """)
        path_row.addWidget(self.path_input, stretch=1)

        self.btn_change_path = QPushButton("Browse / Change...")
        self.btn_change_path.setToolTip("Click to choose or change the export folder")
        self.btn_change_path.setStyleSheet("""
            QPushButton {
                background: #f1f5f9;
                color: #334155;
                font-weight: 600;
                font-size: 12px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: #e2e8f0;
            }
        """)
        self.btn_change_path.clicked.connect(self._choose_folder)
        path_row.addWidget(self.btn_change_path)
        path_box.addLayout(path_row)
        layout.addLayout(path_box)

        # ── 4. File Name Row ──
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        lbl_name = QLabel("File Name:")
        lbl_name.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        name_box.addWidget(lbl_name)

        # Preserve all Unicode characters (Devanagari, Hindi, Nepali, letters, numbers, etc.)
        # Strip only illegal Windows filename characters: \ / : * ? " < > | \r \n \t
        clean_prefix = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', self.table_title)
        clean_prefix = re.sub(r'[\s_]+', '_', clean_prefix).strip(' ._')
        if not clean_prefix:
            clean_prefix = "VAT_Export"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_file = f"{clean_prefix}_{ts}.xlsx"

        self.filename_input = QLineEdit(default_file)
        self.filename_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 10px;
                color: #0f172a;
                font-size: 12px;
            }
        """)
        name_box.addWidget(self.filename_input)
        layout.addLayout(name_box)

        # ── 5. Action Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 7px 16px;
                font-weight: 500;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #e2e8f0;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_export = QPushButton("Export to Excel")
        self.btn_export.setDefault(True)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background: #059669;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 7px 20px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #047857;
            }
        """)
        self.btn_export.clicked.connect(self._do_export)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_export)
        layout.addLayout(btn_row)

    def _choose_folder(self):
        cur = self.path_input.text().strip()
        start = cur if os.path.exists(cur) else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Select Export Folder", start)
        if chosen:
            self.path_input.setText(chosen)
            self.settings.setValue("export_folder", chosen)
            QSettings("TallySync", "VatWorking").setValue("export_folder", chosen)

    def _do_export(self):
        folder = self.path_input.text().strip()
        filename = self.filename_input.text().strip()

        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Please select an export folder.")
            return

        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create folder:\n{e}")
                return

        if not filename:
            filename = f"Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        elif not filename.lower().endswith(".xlsx"):
            filename += ".xlsx"

        full_path = os.path.join(folder, filename)

        tables_data = [{"title": self.table_title, "table": self.table_widget}]
        try:
            success = export_tables_to_excel(folder, filename, tables_data, parent=self)
            if success:
                self.settings.setValue("export_folder", folder)
                QSettings("TallySync", "VatWorking").setValue("export_folder", folder)
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Export Successful")
                msg_box.setText(f"File saved successfully to:\n{full_path}")
                msg_box.setIcon(QMessageBox.Icon.Information)
                btn_open = msg_box.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
                msg_box.addButton(QMessageBox.StandardButton.Ok)
                msg_box.exec()

                if msg_box.clickedButton() == btn_open:
                    try:
                        os.startfile(folder)
                    except Exception:
                        pass
                self.accept()
        except Exception as e:
            logger.error(f"[VatExportDialog._do_export] error: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export to Excel:\n{e}")
