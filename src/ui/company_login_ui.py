import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, 
    QListWidgetItem, QFrame, QLineEdit, QGridLayout, 
    QPushButton, QFileDialog, QStackedWidget, QDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal 
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QColor
from pathlib import Path
from src.logic.report_store import save_report_json
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# Check for first-run super admin setup
def _check_first_run_setup(parent=None):
    """If no super admin exists, prompt for first-time setup."""
    from src.logic.security_manager import SecurityManager
    if not SecurityManager.super_admin_exists():
        from src.ui.admin_panel import SuperAdminSetupDialog
        dlg = SuperAdminSetupDialog(parent)
        dlg.exec()

# ================= 1. SET DATA PATH DIALOG =================
class PathDialog(QDialog):
    def __init__(self, current_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Data Directory")
        self.setFixedSize(450, 160)
        self.setObjectName("PathDialog") 
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        path_box = QHBoxLayout()
        self.path_edit = QLineEdit(current_path)
        self.path_edit.setObjectName("PathLineEdit") 
        path_box.addWidget(self.path_edit)
        
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.setObjectName("BrowseButtonSmall")
        btn_browse.clicked.connect(self.browse_folder)
        path_box.addWidget(btn_browse)
        layout.addLayout(path_box)
        
        self.btn_save = QPushButton("APPLY PATH")
        self.btn_save.setFixedHeight(35)
        self.btn_save.setObjectName("ApplyButton")
        self.btn_save.clicked.connect(self.accept)
        layout.addWidget(self.btn_save)

    def browse_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Select Folder")
        if p: self.path_edit.setText(p)
    def get_path(self): return self.path_edit.text()

# ================= 2. LOGIN DIALOG =================
class LoginDialog(QDialog):
    def __init__(self, company_name, folder_path, security_mgr, parent=None):
        super().__init__(parent)
        self.company_name = company_name
        self.folder_path = folder_path
        self.security = security_mgr
        self.session = None  # UserSession set on successful login
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setFixedSize(450, 260) 
        self.setModal(True)
        self.setObjectName("LoginDialog") 
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(50)
        header.setObjectName("LoginHeader") 
        h_layout = QHBoxLayout(header)
        title = QLabel(f"🏢 Company Login: {company_name}")
        title.setObjectName("LoginTitle")
        h_layout.addWidget(title)
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setObjectName("LoginCloseBtn")
        close_btn.clicked.connect(self.reject)
        h_layout.addWidget(close_btn)
        
        layout.addWidget(header)

        content = QFrame()
        content.setObjectName("LoginContent")
        form_grid = QGridLayout(content)
        form_grid.setContentsMargins(30, 20, 30, 10)
        form_grid.setSpacing(12)
        
        lbl_user = QLabel("User Name :-")
        lbl_user.setObjectName("LoginLabel")
        form_grid.addWidget(lbl_user, 0, 0)
        
        self.user_edit = QLineEdit()
        self.user_edit.setObjectName("LoginInput")
        self.user_edit.setPlaceholderText("Enter username")
        form_grid.addWidget(self.user_edit, 0, 1)
        
        lbl_pass = QLabel("Password :-")
        lbl_pass.setObjectName("LoginLabel")
        form_grid.addWidget(lbl_pass, 1, 0)
        
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setObjectName("LoginInput")
        self.pass_edit.setPlaceholderText("Enter password")
        form_grid.addWidget(self.pass_edit, 1, 1)
        layout.addWidget(content)

        self.error_lbl = QLabel("")
        self.error_lbl.setObjectName("LoginErrorLabel") 
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.error_lbl)

        self.btn_login = QPushButton("Login")
        self.btn_login.setFixedHeight(45)
        self.btn_login.setObjectName("LoginActionButton") 
        self.btn_login.clicked.connect(self.verify_login)
        layout.addWidget(self.btn_login)
        
        # Make the username field automatically focused when form opens
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self.user_edit.setFocus)

    def verify_login(self):
        username = self.user_edit.text()
        password = self.pass_edit.text()
        
        # Verify via SecurityManager (returns UserSession on success, None on failure)
        # Empty username + password is allowed — handled by normal bcrypt flow
        session = self.security.verify_login(self.folder_path, username, password,
                                              company_name=self.company_name)
        if session:
            self.session = session
            logger.info(f"Login successful: {session}")
            self.accept()
            return

        logger.warning(f"Login failed: company='{self.company_name}', user='{username}'")
        self.error_lbl.setText("❌ Invalid Credentials!")
        self.user_edit.setFocus()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.user_edit.hasFocus(): self.pass_edit.setFocus()
            else: self.verify_login()
        elif event.key() == Qt.Key.Key_Escape: self.reject()

# ================= 3. COMPANY CREATE FORM (DECENTRALIZED LOGIC) =================
class CompanyCreateForm(QWidget):
    def __init__(self, back_callback, security_mgr):
        super().__init__()
        self.back_callback = back_callback
        self.security = security_mgr
        self.fields = [] 
        self.edit_mode = False 
        self.base_folder_path = "" # Parent folder where new company folder will be created
        self.defined_company_path = "" # Actual company folder path (for Edit mode)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("FormHeader") 
        hl = QHBoxLayout(header)
        self.header_label = QLabel("  Company Configuration")
        self.header_label.setObjectName("FormHeaderTitle")
        hl.addWidget(self.header_label)
        
        hl.addStretch()
        esc_label = QLabel("[Esc: Back]  ")
        esc_label.setObjectName("EscHint")
        hl.addWidget(esc_label)
        layout.addWidget(header)

        content = QWidget()
        content.setObjectName("FormContent") 
        grid = QGridLayout(content)
        grid.setContentsMargins(50, 40, 50, 40)
        grid.setSpacing(15)
        
        # Labels modified to reflect logic: "Location" instead of "Folder Path"
        labels = ["Display Name :-", "User Name :-", "Password :-", "Confirm Password :-", "Location :-", "Image Location :-", "Backup Location :-"]
        
        for i, text in enumerate(labels):
            grid.addWidget(QLabel(f"<b>{text}</b>"), i, 0)
            edit = QLineEdit()
            edit.setObjectName("FormInput") 
            if "Password" in text: edit.setEchoMode(QLineEdit.EchoMode.Password)
            
            if "Location" in text and "Image" not in text and "Backup" not in text:
                edit.setReadOnly(True) 
                edit.setPlaceholderText("Selected Data Folder")
                
            if "Image Location" in text or "Backup Location" in text:
                 hb = QHBoxLayout()
                 hb.addWidget(edit)
                 btn = QPushButton("Browse")
                 btn.clicked.connect(lambda _, e=edit: self.browse_dir(e))
                 hb.addWidget(btn)
                 grid.addLayout(hb, i, 1)
            else:
                grid.addWidget(edit, i, 1)
            self.fields.append(edit)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("SAVE CONFIG")
        self.save_btn.setFixedSize(140, 40)
        self.save_btn.setObjectName("FormSaveButton")
        self.save_btn.clicked.connect(self.save_data)
        
        back = QPushButton("BACK")
        back.setFixedSize(140, 40)
        back.setObjectName("FormBackButton")
        back.clicked.connect(self.back_to_list)
        
        btns.addWidget(self.save_btn)
        btns.addWidget(back)
        btns.addStretch()
        grid.addLayout(btns, 7, 1)

        self.error_lbl = QLabel("")
        self.error_lbl.setObjectName("FormErrorLabel")
        grid.addWidget(self.error_lbl, 8, 1)
        layout.addWidget(content, 1)
        
    def browse_dir(self, edit_field):
        p = QFileDialog.getExistingDirectory(self, "Select Folder")
        if p: edit_field.setText(p)

    def load_for_setup(self, parent_path):
        """Called when Creating specific new company inside parent_path"""
        self.edit_mode = False
        self.base_folder_path = parent_path
        self.defined_company_path = ""
        self.header_label.setText("  Create New Company")
        
        for f in self.fields: 
            if isinstance(f, QLineEdit): f.clear()
            
        # Show parent path to user
        self.fields[4].setText(parent_path) 
        
        # Load global backup path
        from src.utils.path_utils import get_app_dir
        config_file = os.path.join(get_app_dir(), "config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.fields[6].setText(json.load(f).get("backup_path", ""))
            except Exception: pass
        
    def load_for_alter(self, company_path):
        """Called when Editing existing company at company_path"""
        self.edit_mode = True
        self.defined_company_path = company_path
        self.base_folder_path = os.path.dirname(company_path)
        self.header_label.setText("  Edit Company Config")
        
        loaded = False
        # Primary: Read from SQL (source of truth)
        try:
            from src.logic.security_manager import SecurityManager
            sm = SecurityManager(self.base_folder_path)
            from src.logic.db_manager import get_db_manager
            conn = get_db_manager().get_connection(sm._db_security)
            if conn:
                cursor = conn.cursor()
                norm = os.path.normpath(os.path.abspath(company_path))
                cursor.execute(
                    "SELECT display_name, image_path FROM companies WHERE folder_path = ?",
                    (norm,))
                row = cursor.fetchone()
                if row:
                    self.fields[0].setText(row[0] or "")
                    self.fields[4].setText(self.base_folder_path)
                    self.fields[5].setText(row[1] or "")
                    loaded = True
        except Exception:
            pass
        
        # Fallback: Read from company_info.json (for unregistered or copied companies)
        if not loaded:
            try:
                info_p = os.path.join(company_path, "company_info.json")
                if os.path.exists(info_p):
                    with open(info_p, 'r') as f:
                        d = json.load(f)
                        self.fields[0].setText(d.get("display_name", ""))
                        self.fields[4].setText(self.base_folder_path)
                        self.fields[5].setText(d.get("image_path", ""))
            except Exception: pass
            
        # Load global backup path
        from src.utils.path_utils import get_app_dir
        config_file = os.path.join(get_app_dir(), "config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.fields[6].setText(json.load(f).get("backup_path", ""))
            except Exception: pass

    def back_to_list(self):
        self.back_callback()

    def sanitize_filename(self, name):
        # Remove invalid chars for folder name
        return "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '_', '-')]).strip()

    def save_data(self):
        display_name = self.fields[0].text().strip()
        user = self.fields[1].text().strip()
        password = self.fields[2].text().strip()
        conf_pass = self.fields[3].text().strip()
        img_path = self.fields[5].text().strip()
        backup_path = self.fields[6].text().strip()

        if not display_name:
            self.error_lbl.setText("❌ Display Name is required!")
            return
            
        if password != conf_pass:
            self.error_lbl.setText("❌ Passwords do not match!")
            return
            
        try:
            # Determine Final Folder Path
            if self.edit_mode and self.defined_company_path:
                # In Edit Mode, we generally don't rename the folder to avoid breaking paths
                # But we update the info inside
                final_folder_path = self.defined_company_path
            else:
                # Create Mode: Create folder inside base_folder_path
                clean_name = self.sanitize_filename(display_name)
                if not clean_name: clean_name = "Company_Data"
                
                final_folder_path = os.path.join(self.base_folder_path, clean_name)
                
                # Check for duplicacy
                if os.path.exists(final_folder_path) and not self.edit_mode:
                    QMessageBox.warning(self, "Exists", f"Folder already exists:\n{final_folder_path}\nUsing existing folder.")
            
            target_path = Path(final_folder_path)
            target_path.mkdir(parents=True, exist_ok=True)
            
            # 1. Update/Create Legacy JSON (for compatibility/backup)
            info = {
                "display_name": display_name,
                "image_path": img_path
            }
            
            info_file = target_path / "company_info.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4)
                
            # Save global backup path
            from src.utils.path_utils import get_app_dir
            config_file = os.path.join(get_app_dir(), "config.json")
            c_data = {}
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        c_data = json.load(f)
                except Exception: pass
            c_data["backup_path"] = backup_path
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(c_data, f, indent=4)
            except Exception: pass
                
            # Initialize empty report data in SQL (ensures table exists)
            save_report_json({}, str(target_path))

            # 2. Register in Secure DB
            cid = self.security.register_company(display_name, str(final_folder_path), img_path, user, password)
            if cid:
                logger.info(f"Company registered: name='{display_name}', path='{final_folder_path}', id={cid}")
            else:
                logger.info(f"Company already exists: name='{display_name}', path='{final_folder_path}'")

            QMessageBox.information(self, "Success", f"Company '{display_name}' configured successfully!\nLocation: {final_folder_path}")
            self.back_to_list()
            
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")

# ================= 4. MAIN UI MANAGER (DECENTRALIZED) =================
class CompanyLoginUI(QWidget):
    login_success_signal = pyqtSignal(str, str, object)  # (company_name, path, UserSession)

    def __init__(self):
        super().__init__()
        from src.utils.path_utils import get_app_dir
        self.app_path = get_app_dir()
        self.config_file = os.path.join(self.app_path, "config.json")
        self.history_file = os.path.join(self.app_path, "company_history.json") 
        self.current_data_path = self.load_saved_path()
        
        # Initialize Security Manager (deferred if no valid path yet)
        self.security = None
        if self.current_data_path and os.path.isdir(self.current_data_path):
            self._init_security(self.current_data_path)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        self.list_screen = QWidget()
        # Use simple List UI from request
        self.init_list_ui()
        self.stack.addWidget(self.list_screen)

        self.form_screen = CompanyCreateForm(self.show_list, self.security)
        self.stack.addWidget(self.form_screen)

        self.load_main_list()
        
        # First-run: prompt for super admin setup (deferred so splash can finish)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, lambda: _check_first_run_setup(self))
        
        # Auto-focus the company list so arrow keys work immediately
        QTimer.singleShot(100, self._auto_focus_list)
    
    def _auto_focus_list(self):
        """Give keyboard focus to the company list and select the first navigable item."""
        self.list.setFocus()
        if self.list.count() > 0:
            # Skip to first actual company item (skip Create, Path, separator, path label)
            for i in range(self.list.count()):
                item = self.list.item(i)
                if item and item.flags() & Qt.ItemFlag.ItemIsSelectable:
                    self.list.setCurrentRow(i)
                    break

    def _init_security(self, data_path):
        """Initialize SecurityManager for the given data path.
        Handles errors gracefully so the app never crashes on startup."""
        try:
            from src.logic.security_manager import SecurityManager
            self.security = SecurityManager(data_path)
            if hasattr(self, 'form_screen'):
                self.form_screen.security = self.security
        except Exception as e:
            logger.error(f"SecurityManager init failed for '{data_path}': {e}")
            self.security = None

    def load_saved_path(self):
        """Load the saved data path with fallback chain:
        1. User config: %APPDATA%/JK_Catalog/config.json
        2. Global config: next to the EXE
        3. No path found: return '' (never default to C:\\)
        """
        # 1. Check user-specific config
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    path = json.load(f).get("default_path", "")
                    if path and os.path.isdir(path):
                        return path
            except Exception:
                pass
        
        # 2. Check global config next to the EXE
        try:
            from src.utils.path_utils import get_exe_dir
            global_config = os.path.join(get_exe_dir(), "config.json")
            if global_config != self.config_file and os.path.exists(global_config):
                with open(global_config, 'r') as f:
                    path = json.load(f).get("default_path", "")
                    if path and os.path.isdir(path):
                        # Auto-save to user's local config
                        try:
                            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                            with open(self.config_file, 'w') as uf:
                                json.dump({"default_path": path}, uf)
                            logger.info(f"Inherited global data path: '{path}'")
                        except Exception:
                            pass
                        return path
        except Exception:
            pass
        
        return ""

    def init_list_ui(self):
        layout = QVBoxLayout(self.list_screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("ListHeader")
        hl = QVBoxLayout(header)
        title = QLabel("  Select Company")
        title.setObjectName("ListHeaderTitle")
        hl.addWidget(title)
        layout.addWidget(header)
        
        cl = QVBoxLayout()
        cl.setContentsMargins(20, 10, 20, 10)
        
        self.list = QListWidget()
        self.list.setObjectName("CompanyListWidget") 
        cl.addWidget(self.list)
        
        cw = QWidget()
        cw.setLayout(cl)
        layout.addWidget(cw)
        
        self.list.itemActivated.connect(self.on_enter)
        QShortcut(QKeySequence("Return"), self.list, activated=lambda: self.on_enter(self.list.currentItem()))

    def load_main_list(self):
        self.list.clear()
        
        # User Requested Layout: Create and Path as Items
        self.add_item("➕ Create New Company", align_right=True, role="create")
        self.add_item("📂 Change Data Path", align_right=True, role="set_path")
        
        line = QListWidgetItem()
        line.setFlags(Qt.ItemFlag.NoItemFlags)
        line.setSizeHint(QSize(100, 2))
        self.list.addItem(line)
        f = QFrame(); f.setFixedHeight(2); f.setObjectName("ListSeparator")
        self.list.setItemWidget(line, f)
        
        self.add_item(f"Current Path: {self.current_data_path}", is_bold=True)
        
        # DECENTRALIZED SCANNING
        found_folders = []
        seen_paths = set()
        
        if os.path.exists(self.current_data_path):
            try:
                for d in os.listdir(self.current_data_path):
                    full = os.path.normpath(os.path.abspath(os.path.join(self.current_data_path, d)))
                    if os.path.isdir(full):
                        if full.lower() not in seen_paths:
                            found_folders.append(full)
                            seen_paths.add(full.lower())
            except Exception: pass
        
        if not found_folders:
             self.add_item("(No folders found)", role=None)
        
        for path in found_folders:
            info_file = os.path.join(path, "company_info.json")
            folder_name = os.path.basename(path)
            
            if os.path.exists(info_file):
                # Registered
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        disp_name = data.get("display_name", folder_name)
                        itm = self.add_item(f"🏢 {disp_name}", role="login")
                        itm.setData(Qt.ItemDataRole.UserRole + 1, path)
                except Exception:
                    self.add_item(f"⚠️ {folder_name} (Error)", role="error")
            # Unconfigured folders are intentionally ignored

    def add_item(self, text, role=None, align_right=False, is_bold=False):
        item = QListWidgetItem(text)
        if align_right: item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        if is_bold: 
            font = QFont()
            font.setBold(True)
            item.setFont(font)
            
        if role:
            item.setData(Qt.ItemDataRole.UserRole, role)
            if role == "error": item.setForeground(QColor("red"))
            if role == "setup": item.setForeground(QColor("gray"))
            if role == "create": item.setForeground(QColor("#28a745")); item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        self.list.addItem(item)
        return item

    def on_enter(self, item):
        if not item: return
        role = item.data(Qt.ItemDataRole.UserRole)
        
        if role == "create": 
            self.create_new_company()
        elif role == "set_path":
            self.change_path()
        elif role == "login": 
            path = item.data(Qt.ItemDataRole.UserRole + 1)
            self.handle_login(path)
        elif role == "setup": 
            path = item.data(Qt.ItemDataRole.UserRole + 1)
            self.form_screen.load_for_setup(path)
            self.stack.setCurrentIndex(1)
    def create_new_company(self):
        # Automatically use the stored data path that was set using 'Change Data Path'
        if self.current_data_path and os.path.exists(self.current_data_path):
            self.form_screen.load_for_setup(self.current_data_path)
            self.stack.setCurrentIndex(1)
        else:
            QMessageBox.warning(self, "No Data Path", "Please set a valid Data Path first using 'Change Data Path'.")

    def open_admin_panel(self):
        """Open the admin panel (requires super admin login)."""
        from src.logic.security_manager import SecurityManager
        if not SecurityManager.super_admin_exists():
            QMessageBox.warning(self, "No Super Admin",
                                "Super admin has not been set up.\nPlease restart the application.")
            return
        
        from src.ui.admin_panel import SuperAdminLoginDialog, AdminPanelDialog
        login_dlg = SuperAdminLoginDialog(self)
        if login_dlg.exec() and login_dlg.authenticated:
            if not self.security:
                QMessageBox.warning(self, "No Data Path", "Please set a data path first.")
                return
            panel = AdminPanelDialog(self.security, self.current_data_path, self)
            panel.exec()
            if panel.data_changed:
                self._init_security(self.current_data_path)
                self.load_main_list()

    def export_data(self):
        """Export the current data path to a .jkbackup file."""
        if not self.current_data_path or not os.path.isdir(self.current_data_path):
            QMessageBox.warning(self, "No Data Path", "Please set a valid data path first.")
            return
        
        output_file, _ = QFileDialog.getSaveFileName(
            self, "Backup Data",
            os.path.expanduser("~/Desktop/JK_Backup.jkbackup"),
            "JK Backup Files (*.jkbackup)"
        )
        if not output_file:
            return
        
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import QCoreApplication
        
        progress = QProgressDialog("Starting export...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Exporting Data")
        progress.setMinimumDuration(0)
        progress.show()
        
        def on_progress(text, current, total):
            if progress.wasCanceled():
                return
            progress.setLabelText(text)
            progress.setMaximum(total)
            progress.setValue(current)
            QCoreApplication.processEvents()
        
        from src.logic.data_transfer import export_data_path
        success, msg = export_data_path(self.current_data_path, output_file, on_progress)
        progress.close()
        
        if success:
            QMessageBox.information(self, "Export Complete", msg)
        else:
            QMessageBox.critical(self, "Export Failed", msg)

    def import_data(self):
        """Import data from a .jkbackup file."""
        backup_file, _ = QFileDialog.getOpenFileName(
            self, "Select Backup File",
            os.path.expanduser("~/Desktop"),
            "JK Backup Files (*.jkbackup)"
        )
        if not backup_file:
            return
        
        # Ask for target data path
        target_path = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder for Import"
        )
        if not target_path:
            return
        
        reply = QMessageBox.question(
            self, "Confirm Import",
            f"Import data from:\n  {os.path.basename(backup_file)}\n\n"
            f"Into folder:\n  {target_path}\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import QCoreApplication
        
        progress = QProgressDialog("Starting import...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Importing Data")
        progress.setMinimumDuration(0)
        progress.show()
        
        def on_progress(text, current, total):
            if progress.wasCanceled():
                return
            progress.setLabelText(text)
            progress.setMaximum(total)
            progress.setValue(current)
            QCoreApplication.processEvents()
        
        from src.logic.data_transfer import import_data_path
        success, msg = import_data_path(backup_file, target_path, on_progress)
        progress.close()
        
        if success:
            QMessageBox.information(self, "Import Complete", msg)
            # Switch to the imported data path
            self.current_data_path = target_path
            # Save to config
            try:
                config_data = {"default_path": target_path}
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                with open(self.config_file, 'w') as f:
                    json.dump(config_data, f)
            except Exception:
                pass
            self._init_security(target_path)
            self.load_main_list()
        else:
            QMessageBox.critical(self, "Import Failed", msg)
            
    def change_path(self):
        dlg = PathDialog(self.current_data_path, self)
        if dlg.exec():
            new_p = dlg.get_path()
            if os.path.exists(new_p):
                # Save to user-specific config (preserve sql_server_name if set)
                try:
                    config_data = {"default_path": new_p}
                    if os.path.exists(self.config_file):
                        with open(self.config_file, 'r') as f:
                            old = json.load(f)
                            if "sql_server_name" in old:
                                config_data["sql_server_name"] = old["sql_server_name"]
                    os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                    with open(self.config_file, 'w') as f: 
                        json.dump(config_data, f)
                except Exception as e:
                    logger.warning(f"Could not save user config: {e}")
                
                # Also save global config next to EXE (for other server users)
                try:
                    from src.utils.path_utils import get_exe_dir
                    global_config = os.path.join(get_exe_dir(), "config.json")
                    if global_config != self.config_file:
                        with open(global_config, 'w') as f:
                            json.dump(config_data, f)
                        logger.info(f"Global config updated: '{global_config}'")
                except Exception:
                    pass
                
                self.current_data_path = new_p
                logger.info(f"Data path changed: new='{new_p}'")
                # Re-init SecurityManager for new data path
                self._init_security(new_p)
                self.load_main_list()

    def handle_login(self, path):
        path = os.path.normpath(os.path.abspath(path))
        
        # Ensure SecurityManager is ready
        if not self.security:
            self._init_security(self.current_data_path)
        if not self.security:
            QMessageBox.critical(self, "Security Error",
                "Could not connect to Security database.\n"
                "Please ensure SQL Server is running and the Data Path is set correctly.")
            return
        
        info_file = os.path.join(path, "company_info.json")
        try:
            # We only read JSON for the Display Name now.
            display_name = os.path.basename(path)
            
            if os.path.exists(info_file):
                with open(info_file, 'r', encoding='utf-8') as f: 
                    data = json.load(f)
                    display_name = data.get("display_name", display_name)
            
            # Pass only the path and security manager. No legacy credentials!
            dlg = LoginDialog(display_name, path, self.security, self)
            
            if dlg.exec() and dlg.session:
                self.save_history(path)
                self.login_success_signal.emit(display_name, path, dlg.session)
        except Exception as e:
            QMessageBox.critical(self, "Login Error", str(e))

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f: return json.load(f)
            except Exception: return []
        return []

    def save_history(self, new_path):
        hist = self.load_history()
        if new_path not in hist:
            hist.append(new_path)
            with open(self.history_file, 'w') as f: json.dump(hist, f)

    def show_list(self):
        self.stack.setCurrentIndex(0)
        self.load_main_list()