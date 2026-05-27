"""
Admin Panel — Super Admin management dialog.

Accessed from the login page via 🔒 Admin button.
Requires super admin authentication to open.
Provides:
  - View/delete companies for the current data path
  - Delete entire data path
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFrame, QLineEdit, QGridLayout
)
from PyQt6.QtCore import Qt
from src.logic.security_manager import SecurityManager
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class SuperAdminLoginDialog(QDialog):
    """Small login dialog for super admin authentication."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔒 Admin Login")
        self.setFixedSize(350, 200)
        self.setObjectName("SuperAdminLoginDialog")
        self.authenticated = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)
        
        title = QLabel("Enter Super Admin Credentials")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)
        
        grid = QGridLayout()
        grid.setSpacing(8)
        
        grid.addWidget(QLabel("Username:"), 0, 0)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Admin username")
        grid.addWidget(self.user_edit, 0, 1)
        
        grid.addWidget(QLabel("Password:"), 1, 0)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Admin password")
        grid.addWidget(self.pass_edit, 1, 1)
        layout.addLayout(grid)
        
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e74c3c;")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.error_lbl)
        
        btn = QPushButton("Login")
        btn.setFixedHeight(35)
        btn.setObjectName("LoginActionButton")
        btn.clicked.connect(self._verify)
        layout.addWidget(btn)
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self.user_edit.setFocus)
    
    def _verify(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        
        if SecurityManager.verify_super_admin(username, password):
            self.authenticated = True
            self.accept()
        else:
            self.error_lbl.setText("❌ Invalid credentials")
            self.user_edit.setFocus()
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.user_edit.hasFocus():
                self.pass_edit.setFocus()
            else:
                self._verify()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()


class SuperAdminSetupDialog(QDialog):
    """First-time super admin setup dialog."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔒 Super Admin Setup")
        self.setFixedSize(400, 300)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setObjectName("SuperAdminSetupDialog")
        self.created = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)
        
        title = QLabel("Create Super Admin Account")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        info = QLabel("This is a one-time setup. The super admin can\n"
                       "delete companies and manage data paths.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)
        
        grid = QGridLayout()
        grid.setSpacing(8)
        
        grid.addWidget(QLabel("Username:"), 0, 0)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Choose a username")
        grid.addWidget(self.user_edit, 0, 1)
        
        grid.addWidget(QLabel("Password:"), 1, 0)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Choose a password")
        grid.addWidget(self.pass_edit, 1, 1)
        
        grid.addWidget(QLabel("Confirm:"), 2, 0)
        self.conf_edit = QLineEdit()
        self.conf_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.conf_edit.setPlaceholderText("Confirm password")
        grid.addWidget(self.conf_edit, 2, 1)
        layout.addLayout(grid)
        
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e74c3c;")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.error_lbl)
        
        btn = QPushButton("Create Super Admin")
        btn.setFixedHeight(35)
        btn.setObjectName("FormSaveButton")
        btn.clicked.connect(self._create)
        layout.addWidget(btn)
    
    def _create(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        confirm = self.conf_edit.text()
        
        if not username:
            self.error_lbl.setText("❌ Username is required")
            return
        if not password:
            self.error_lbl.setText("❌ Password is required")
            return
        if password != confirm:
            self.error_lbl.setText("❌ Passwords do not match")
            return
        
        try:
            SecurityManager.setup_super_admin(username, password)
            self.created = True
            QMessageBox.information(self, "Success",
                                    f"Super admin '{username}' created successfully!")
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"❌ Error: {e}")
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._create()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()


class AdminPanelDialog(QDialog):
    """Main admin panel for managing companies and data paths."""
    
    def __init__(self, security_mgr, data_path, parent=None):
        super().__init__(parent)
        self.security = security_mgr
        self.data_path = data_path
        self.data_changed = False  # Set to True if anything was deleted
        
        self.setWindowTitle(f"🔒 Admin Panel — {data_path}")
        self.setMinimumSize(600, 400)
        self.setObjectName("AdminPanelDialog")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header
        header = QLabel(f"📂 Data Path: {data_path}")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 5px;")
        layout.addWidget(header)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)
        
        # Company table
        lbl = QLabel("Companies:")
        lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl)
        
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Company Name", "Folder Path"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Buttons
        btn_row = QHBoxLayout()
        
        self.btn_delete_company = QPushButton("🗑  Delete Selected Company")
        self.btn_delete_company.setFixedHeight(35)
        self.btn_delete_company.setStyleSheet(
            "background-color: #e74c3c; color: white; font-weight: bold; padding: 0 15px;")
        self.btn_delete_company.clicked.connect(self._delete_company)
        btn_row.addWidget(self.btn_delete_company)
        
        btn_row.addStretch()
        
        self.btn_delete_path = QPushButton("⚠  Delete Entire Data Path")
        self.btn_delete_path.setFixedHeight(35)
        self.btn_delete_path.setStyleSheet(
            "background-color: #c0392b; color: white; font-weight: bold; padding: 0 15px;")
        self.btn_delete_path.clicked.connect(self._delete_data_path)
        btn_row.addWidget(self.btn_delete_path)
        
        layout.addLayout(btn_row)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self._load_companies()
    
    def _load_companies(self):
        """Load companies from the Security DB into the table."""
        self.table.setRowCount(0)
        
        if not self.security:
            return
        
        companies = self.security.get_companies_list()
        for company in companies:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            name_item = QTableWidgetItem(company["display_name"])
            name_item.setData(Qt.ItemDataRole.UserRole, company["folder_path"])
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(company["folder_path"]))
    
    def _delete_company(self):
        """Delete the selected company after confirmation."""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a company to delete.")
            return
        
        company_name = self.table.item(row, 0).text()
        folder_path = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        
        # Confirmation
        reply = QMessageBox.warning(
            self, "Delete Company",
            f"⚠️ This will PERMANENTLY delete:\n\n"
            f"  Company: {company_name}\n"
            f"  Database: (SQL Server)\n"
            f"  Folder: {folder_path}\n\n"
            f"This cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        success, msg = self.security.delete_company(folder_path)
        if success:
            QMessageBox.information(self, "Deleted", f"Company '{company_name}' deleted.")
            self.data_changed = True
            self._load_companies()
        else:
            QMessageBox.critical(self, "Error", f"Failed to delete company:\n{msg}")
    
    def _delete_data_path(self):
        """Delete the entire data path after double confirmation."""
        # First confirmation
        reply1 = QMessageBox.warning(
            self, "Delete Data Path",
            f"⚠️ This will PERMANENTLY delete:\n\n"
            f"  ALL companies under: {self.data_path}\n"
            f"  ALL SQL Server databases for this path\n"
            f"  ALL files and folders\n\n"
            f"This CANNOT be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply1 != QMessageBox.StandardButton.Yes:
            return
        
        # Second confirmation
        reply2 = QMessageBox.critical(
            self, "FINAL WARNING",
            f"Are you ABSOLUTELY sure?\n\n"
            f"Deleting: {self.data_path}\n\n"
            f"Type 'DELETE' below is not possible in this dialog,\n"
            f"so this is your last chance to cancel.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply2 != QMessageBox.StandardButton.Yes:
            return
        
        success, msg = self.security.delete_data_path(self.data_path)
        if success:
            QMessageBox.information(self, "Deleted", 
                                    f"Data path deleted:\n{self.data_path}\n\n"
                                    f"Please set a new data path.")
            self.data_changed = True
            self.accept()
        else:
            QMessageBox.critical(self, "Error", f"Failed:\n{msg}")
