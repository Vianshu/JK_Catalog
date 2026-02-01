import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, 
    QListWidgetItem, QFrame, QLineEdit, QGridLayout, 
    QPushButton, QFileDialog, QStackedWidget, QDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal 
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
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
    def __init__(self, company_name, correct_user, correct_pass, parent=None):
        super().__init__(parent)
        self.correct_user = correct_user
        self.correct_pass = correct_pass
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
        if self.user_edit.text() == self.correct_user and self.pass_edit.text() == self.correct_pass: 
            self.accept()
        else: 
            self.error_lbl.setText("❌ Invalid Credentials!")
            self.user_edit.setFocus()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.user_edit.hasFocus(): self.pass_edit.setFocus()
            else: self.verify_login()
        elif event.key() == Qt.Key.Key_Escape: self.reject()

# ================= 3. COMPANY CREATE FORM =================
class CompanyCreateForm(QWidget):
    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        self.app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.fields = [] 
        self.edit_mode = False 
        self.target_folder_path = "" 
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
        
        labels = ["Display Name :-", "User Name :-", "Password :-", "Confirm Password :-", "Folder Path :-", "Image Location :-"]
        
        for i, text in enumerate(labels):
            grid.addWidget(QLabel(f"<b>{text}</b>"), i, 0)
            edit = QLineEdit()
            edit.setObjectName("FormInput") 
            if "Password" in text: edit.setEchoMode(QLineEdit.EchoMode.Password)
            
            if "Folder Path" in text:
                edit.setReadOnly(True) # Path is usually set from caller
                
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
    
    def load_for_create(self, folder_path, folder_name):
        self.edit_mode = False
        self.target_folder_path = folder_path
        self.header_label.setText(f"  Setup: {folder_name}")
        self.save_btn.setText("CREATE LOGIN")
        
        for f in self.fields: f.clear()
        
        self.fields[0].setText(folder_name) # Display Name
        self.fields[4].setText(folder_path) # Path
        self.fields[1].setFocus()

    def browse_img(self, target):
        p = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if p: target.setText(p)

    def back_to_list(self):
        self.back_callback()

    def save_data(self):
        display_name = self.fields[0].text().strip()
        user = self.fields[1].text().strip()
        password = self.fields[2].text().strip()
        conf_pass = self.fields[3].text().strip()
        path = self.fields[4].text().strip()
        img_path = self.fields[5].text().strip()

        if not display_name or not user or not password:
            self.error_lbl.setText("❌ Name, User, and Password are required!")
            return
            
        if password != conf_pass:
            self.error_lbl.setText("❌ Passwords do not match!")
            return
            
        try:
            target_path = Path(path)
            target_path.mkdir(parents=True, exist_ok=True)
            
            # 1. Create company_info.json inside the folder
            info = {
                "display_name": display_name,
                "user": user,
                "pass": password, # In real app, hash this!
                "image_path": img_path
            }
            
            info_file = target_path / "company_info.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4)
                
            # 2. Init Report Data if missing
            report_file = target_path / "REPORT_DATA.JSON"
            if not report_file.exists():
                save_report_json({}, str(report_file))

            QMessageBox.information(self, "Success", f"Company '{display_name}' configured successfully!")
            self.back_to_list()
            
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")

# ================= 4. MAIN UI MANAGER =================
class CompanyLoginUI(QWidget):
    # Sends (Company Name, Company Path)
    login_success_signal = pyqtSignal(str, str) 

    def __init__(self):
        super().__init__()
        self.app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_file = os.path.join(self.app_path, "config.json")
        self.history_file = os.path.join(self.app_path, "company_history.json") # Replaces vault
        self.current_data_path = self.load_saved_path()
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        self.list_screen = QWidget()
        self.init_list_ui()
        self.stack.addWidget(self.list_screen)

        self.form_screen = CompanyCreateForm(self.show_list)
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
        
        # Path Selector
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("<b>Looking in:</b>"))
        self.lbl_path = QLabel(self.current_data_path)
        path_row.addWidget(self.lbl_path)
        btn_change = QPushButton("Change")
        btn_change.clicked.connect(self.change_path)
        path_row.addWidget(btn_change)
        path_row.addStretch()
        cl.addLayout(path_row)
        
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
        self.lbl_path.setText(self.current_data_path)
        
        # 1. Scan Data Directory
        found_folders = []
        if os.path.exists(self.current_data_path):
            try:
                for d in os.listdir(self.current_data_path):
                    full = os.path.join(self.current_data_path, d)
                    if os.path.isdir(full):
                        found_folders.append(full)
            except: pass
            
        # 2. Add History Folders (if valid)
        history = self.load_history()
        for h_path in history:
            if os.path.exists(h_path) and h_path not in found_folders:
                found_folders.append(h_path)
                
        if not found_folders:
             self.add_item("(No company folders found)", role=None)
             return

        # 3. Process Folders
        for path in found_folders:
            info_file = os.path.join(path, "company_info.json")
            folder_name = os.path.basename(path)
            
            if os.path.exists(info_file):
                # Registered Company
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        disp_name = data.get("display_name", folder_name)
                        img_path = data.get("image_path", "")
                        
                        itm = self.add_item(f"🏢 {disp_name}", role="login")
                        itm.setData(Qt.ItemDataRole.UserRole + 1, path)
                        itm.setToolTip(path)
                except:
                    self.add_item(f"⚠️ {folder_name} (Corrupt Config)", role="error")
            else:
                # Unregistered
                itm = self.add_item(f"📂 {folder_name} (Unconfigured)", role="setup")
                itm.setData(Qt.ItemDataRole.UserRole + 1, path)
                # Style logic for unconfigured can be in QSS

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except: return []
        return []

    def save_history(self, new_path):
        hist = self.load_history()
        if new_path not in hist:
            hist.append(new_path)
            with open(self.history_file, 'w') as f:
                json.dump(hist, f)

    def add_item(self, text, role=None, align_right=False, is_bold=False):
        item = QListWidgetItem(text)
        if align_right: item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        if is_bold: 
            font = QFont()
            font.setBold(True)
            item.setFont(font)
        item.setData(Qt.ItemDataRole.UserRole, role)
        self.list.addItem(item)
        return item

    def change_path(self):
        dlg = PathDialog(self.current_data_path, self)
        if dlg.exec():
            new_p = dlg.get_path()
            if os.path.exists(new_p):
                with open(self.config_file, 'w') as f: 
                    json.dump({"default_path": new_p}, f)
                self.current_data_path = new_p
                self.load_main_list()

    def on_enter(self, item):
        if not item: return
        role = item.data(Qt.ItemDataRole.UserRole)
        path = item.data(Qt.ItemDataRole.UserRole + 1)
        
        if role == "login":
            self.handle_login(path)
        elif role == "setup":
            folder_name = os.path.basename(path)
            self.stack.setCurrentIndex(1)
            self.form_screen.load_for_create(path, folder_name)
    
    def handle_login(self, path):
        info_file = os.path.join(path, "company_info.json")
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            name = data.get("display_name", "Unknown")
            user = data.get("user", "")
            pwd = data.get("pass", "")
            
            dlg = LoginDialog(name, user, pwd, self)
            if dlg.exec():
                # Success!
                self.save_history(path)
                self.login_success_signal.emit(name, path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read company data:\n{e}")

    def show_list(self):
        self.stack.setCurrentIndex(0)
        self.load_main_list()