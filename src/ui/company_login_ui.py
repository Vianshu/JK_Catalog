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
from src.ui.settings import save_report_json

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
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setFixedSize(450, 300) 
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
        
        close_btn = QPushButton("X")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("color:white; border:none; font-weight:bold;")
        close_btn.clicked.connect(self.reject)
        h_layout.addWidget(close_btn)
        
        layout.addWidget(header)

        content = QFrame()
        content.setObjectName("LoginContent")
        form_grid = QGridLayout(content)
        form_grid.setContentsMargins(40, 30, 40, 10)
        form_grid.setSpacing(15)
        
        lbl_user = QLabel("User Name :-")
        lbl_user.setObjectName("LoginLabel")
        form_grid.addWidget(lbl_user, 0, 0)
        
        self.user_edit = QLineEdit()
        self.user_edit.setObjectName("LoginInput")
        form_grid.addWidget(self.user_edit, 0, 1)
        
        lbl_pass = QLabel("Password :-")
        lbl_pass.setObjectName("LoginLabel")
        form_grid.addWidget(lbl_pass, 1, 0)
        
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setObjectName("LoginInput")
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

    def verify_login(self):
        username = self.user_edit.text()
        password = self.pass_edit.text()
        
        # STRICT SECURITY MODE: Only DB Login allowed
        db_user = self.security.verify_login(self.folder_path, username, password)
        if db_user:
            self.accept()
            return

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
        labels = ["Display Name :-", "User Name :-", "Password :-", "Confirm Password :-", "Location :-", "Image Location :-"]
        
        for i, text in enumerate(labels):
            grid.addWidget(QLabel(f"<b>{text}</b>"), i, 0)
            edit = QLineEdit()
            edit.setObjectName("FormInput") 
            if "Password" in text: edit.setEchoMode(QLineEdit.EchoMode.Password)
            
            if "Location" in text and "Image" not in text:
                edit.setReadOnly(True) 
                edit.setPlaceholderText("Selected Data Folder")
                
            if "Image Location" in text:
                 hb = QHBoxLayout()
                 hb.addWidget(edit)
                 btn = QPushButton("Browse")
                 btn.clicked.connect(lambda _, e=edit: self.browse_img(e))
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
        grid.addLayout(btns, 6, 1)

        self.error_lbl = QLabel("")
        self.error_lbl.setObjectName("FormErrorLabel")
        grid.addWidget(self.error_lbl, 7, 1)
        layout.addWidget(content, 1)
        
    def browse_img(self, edit_field):
        p = QFileDialog.getExistingDirectory(self, "Select Image Folder")
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
        
    def load_for_alter(self, company_path):
        """Called when Editing existing company at company_path"""
        self.edit_mode = True
        self.defined_company_path = company_path
        self.base_folder_path = os.path.dirname(company_path)
        self.header_label.setText("  Edit Company Config")
        
        try:
             info_p = os.path.join(company_path, "company_info.json")
             if os.path.exists(info_p):
                 with open(info_p, 'r') as f:
                     d = json.load(f)
                     self.fields[0].setText(d.get("display_name", ""))
                     # Security Update: We no longer store/load credentials from JSON
                     self.fields[4].setText(self.base_folder_path) # Show parent loc
                     self.fields[5].setText(d.get("image_path", ""))
        except: pass

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
                
            report_file = target_path / "REPORT_DATA.JSON"
            if not report_file.exists():
                save_report_json({}, str(report_file))

            # 2. Register in Secure DB
            cid = self.security.register_company(display_name, str(final_folder_path), img_path, user, password)
            if cid:
                print(f"Company registered in Security DB with ID: {cid}")
            else:
                print("Company already exists in DB or path conflict.")

            QMessageBox.information(self, "Success", f"Company '{display_name}' configured successfully!\nLocation: {final_folder_path}")
            self.back_to_list()
            
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")

# ================= 4. MAIN UI MANAGER (DECENTRALIZED) =================
class CompanyLoginUI(QWidget):
    login_success_signal = pyqtSignal(str, str) 

    def __init__(self):
        super().__init__()
        self.app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_file = os.path.join(self.app_path, "config.json")
        self.history_file = os.path.join(self.app_path, "company_history.json") 
        self.current_data_path = self.load_saved_path()
        
        # Initialize Security Manager
        from src.logic.security_manager import SecurityManager
        from src.utils.path_utils import get_secure_data_dir
        self.security = SecurityManager(os.path.join(get_secure_data_dir(), "security.db"))
        
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

    def load_saved_path(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f: return json.load(f).get("default_path", "C:\\")
        return "C:\\"

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
        cl.setContentsMargins(40, 20, 40, 20)
        
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
        f = QFrame(); f.setFixedHeight(2); f.setStyleSheet("background-color: #eee;") 
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
            except: pass
            
        # Add History
        history = self.load_history()
        for h_path in history:
            norm_h = os.path.normpath(os.path.abspath(h_path))
            if os.path.exists(norm_h) and norm_h.lower() not in seen_paths:
                found_folders.append(norm_h)
                seen_paths.add(norm_h.lower())
        
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
                except:
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
            
    def change_path(self):
        dlg = PathDialog(self.current_data_path, self)
        if dlg.exec():
            new_p = dlg.get_path()
            if os.path.exists(new_p):
                with open(self.config_file, 'w') as f: 
                    json.dump({"default_path": new_p}, f)
                self.current_data_path = new_p
                self.load_main_list()

    def handle_login(self, path):
        path = os.path.normpath(os.path.abspath(path))
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
            
            if dlg.exec():
                self.save_history(path)
                self.login_success_signal.emit(display_name, path)
        except Exception as e:
            QMessageBox.critical(self, "Login Error", str(e))

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f: return json.load(f)
            except: return []
        return []

    def save_history(self, new_path):
        hist = self.load_history()
        if new_path not in hist:
            hist.append(new_path)
            with open(self.history_file, 'w') as f: json.dump(hist, f)

    def show_list(self):
        self.stack.setCurrentIndex(0)
        self.load_main_list()