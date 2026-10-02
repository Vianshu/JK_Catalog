"""
Year End Dialog - 3-step wizard for the Year End feature.

Pages:
  0 - Company name input + validation
  1 - Progress bar while worker runs
  2 - Done/error summary with optional 'Switch to New Company' button
"""

import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QStackedWidget, QWidget,
)


# ─── Background Worker ────────────────────────────────────────────────────────

class _YearEndWorker(QThread):
    progress = pyqtSignal(str, int, int)          # step_text, current, total
    finished = pyqtSignal(bool, str, str)         # success, message, new_path

    def __init__(self, company_path, new_company_name):
        super().__init__()
        self.company_path     = company_path
        self.new_company_name = new_company_name

    def run(self):
        from src.logic.year_end import perform_year_end
        try:
            success, msg, new_path = perform_year_end(
                self.company_path,
                self.new_company_name,
                lambda text, cur, tot: self.progress.emit(text, cur, tot),
            )
            self.finished.emit(success, msg, new_path)
        except Exception as exc:
            self.finished.emit(False, str(exc), "")


# ─── Dialog ───────────────────────────────────────────────────────────────────

class YearEndDialog(QDialog):
    """3-step Year End wizard.

    Emits switch_company(new_path) when the user clicks 'Switch to New Company'.
    Connect this signal in the caller to trigger company switching.
    """
    switch_company = pyqtSignal(str)

    def __init__(self, company_path, parent=None):
        super().__init__(parent)
        self.company_path     = company_path
        self.new_company_path = ""
        self._worker          = None

        self.setWindowTitle("Year End")
        self.setMinimumWidth(500)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.stack.addWidget(self._page_input())
        self.stack.addWidget(self._page_progress())
        self.stack.addWidget(self._page_done())

    def _page_input(self):
        """Page 0 - Enter new company name."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        title = QLabel("<b>Year End — Create New Company</b>")
        title.setStyleSheet("font-size: 15px;")
        lay.addWidget(title)

        info = QLabel(
            "A new company will be created at the same location as the current one.\n"
            "• All data (catalog, godown, reports) is copied as-is.\n"
            "• In the new company: cleared cheques are removed; pending cheques are kept with their original SN numbers."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; margin-bottom: 8px;")
        lay.addWidget(info)

        lay.addWidget(QLabel("New Company Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g.  HW Division 082-83")
        self.name_edit.returnPressed.connect(self._start)
        lay.addWidget(self.name_edit)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #e74c3c;")
        lay.addWidget(self.lbl_error)

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton("Start Year End")
        self.btn_start.setDefault(True)
        self.btn_start.setObjectName("BtnPrimary")
        self.btn_start.clicked.connect(self._start)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_start)
        lay.addLayout(btn_row)
        return w

    def _page_progress(self):
        """Page 1 - Progress bar while worker runs."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        lay.addWidget(QLabel("<b>Year End in Progress…</b>"))

        self.lbl_status = QLabel("Please wait…")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 6)
        self.progress_bar.setValue(0)
        lay.addWidget(self.progress_bar)

        lay.addStretch()
        return w

    def _page_done(self):
        """Page 2 - Result summary + optional switch button."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        self.lbl_done_title = QLabel("")
        self.lbl_done_title.setStyleSheet("font-size: 15px;")
        lay.addWidget(self.lbl_done_title)

        self.lbl_done_msg = QLabel("")
        self.lbl_done_msg.setWordWrap(True)
        lay.addWidget(self.lbl_done_msg)

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        self.btn_switch = QPushButton("Switch to New Company")
        self.btn_switch.setObjectName("BtnPrimary")
        self.btn_switch.clicked.connect(self._on_switch)
        btn_row.addWidget(btn_close)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_switch)
        lay.addLayout(btn_row)
        return w

    # ── Handlers ───────────────────────────────────────────────────────────────

    def _start(self):
        name = self.name_edit.text().strip()
        if not name:
            self.lbl_error.setText("Company name cannot be empty.")
            return

        data_path  = os.path.dirname(os.path.normpath(self.company_path))
        new_path   = os.path.join(data_path, name)
        if os.path.exists(new_path):
            self.lbl_error.setText(
                f"A folder named '{name}' already exists.\nPlease choose a different name."
            )
            return

        self.lbl_error.setText("")
        self.stack.setCurrentIndex(1)

        self._worker = _YearEndWorker(self.company_path, name)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, text, current, total):
        self.lbl_status.setText(text)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_finished(self, success, message, new_path):
        self.new_company_path = new_path
        if success:
            self.lbl_done_title.setText("<b>Year End Complete</b>")
        else:
            self.lbl_done_title.setText("<b>Year End Failed</b>")
        self.lbl_done_msg.setText(message)
        self.btn_switch.setVisible(success and bool(new_path))
        self.stack.setCurrentIndex(2)

    def _on_switch(self):
        """User clicked 'Switch to New Company' — accept dialog and emit signal."""
        self.accept()
        if self.new_company_path:
            self.switch_company.emit(self.new_company_path)
