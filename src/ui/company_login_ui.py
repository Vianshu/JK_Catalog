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
from settings import save_report_json

# ================= 1. SET DATA PATH DIALOG =================
class PathDialog(QDialog):
    def __init__(self, current_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Data Directory")
        self.setFixedSize(450, 160)
        self.setObjectName("PathDialog") # QSS: #PathDialog
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        path_box = QHBoxLayout()
        self.path_edit = QLineEdit(current_path)
        self.path_edit.setObjectName("PathLineEdit") # QSS: #PathLineEdit
        path_box.addWidget(self.path_edit)
        
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.setObjectName("BrowseButtonSmall")
        btn_browse.clicked.connect(self.browse_folder)
        path_box.addWidget(btn_browse)
        layout.addLayout(path_box)
        
        self.btn_save = QPushButton("APPLY PATH")
        self.btn_save.setFixedHeight(35)
        self.btn_save.setObjectName("ApplyButton") # QSS: #ApplyButton
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
        self.setObjectName("LoginDialog") # QSS: #LoginDialog
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(50)
        header.setObjectName("LoginHeader") # QSS: #LoginHeader
        h_layout = QHBoxLayout(header)
        title = QLabel(f"🏢 Company Login: {company_name}")
        title.setObjectName("LoginTitle")
        h_layout.addWidget(title)
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
        self.error_lbl.setObjectName("LoginErrorLabel") # QSS: #LoginErrorLabel
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.error_lbl)

        self.btn_login = QPushButton("Login")
        self.btn_login.setFixedHeight(45)
        self.btn_login.setObjectName("LoginActionButton") # QSS: #LoginActionButton
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
        self.old_name = "" 
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("FormHeader") # QSS: #FormHeader
        hl = QHBoxLayout(header)
        self.header_label = QLabel("  Company Creation")
        self.header_label.setObjectName("FormHeaderTitle")
        hl.addWidget(self.header_label)
        
        hl.addStretch()
        esc_label = QLabel("[Esc: Back]  ")
        esc_label.setObjectName("EscHint")
        hl.addWidget(esc_label)
        layout.addWidget(header)

        content = QWidget()
        content.setObjectName("FormContent") # QSS: #FormContent
        grid = QGridLayout(content)
        grid.setContentsMargins(50, 40, 50, 40)
        grid.setSpacing(15)
        
        labels = ["Company Name :-", "User Name :-", "Password :-", "Confirm Password :-", "Data Location :-", "Image Location :-"]
        
        for i, text in enumerate(labels):
            grid.addWidget(QLabel(f"<b>{text}</b>"), i, 0)
            edit = QLineEdit()
            edit.setObjectName("FormInput") # QSS: #FormInput
            if "Password" in text: edit.setEchoMode(QLineEdit.EchoMode.Password)
            
            if "Location" in text:
                hb = QHBoxLayout()
                hb.addWidget(edit)
                btn = QPushButton("Browse")
                btn.setObjectName("BrowseButton")
                btn.clicked.connect(lambda _, e=edit: self.browse(e))
                hb.addWidget(btn)
                grid.addLayout(hb, i, 1)
            else:
                grid.addWidget(edit, i, 1)
            self.fields.append(edit)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("SAVE")
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
    
    def load_for_alter(self, company_name):
        self.edit_mode = True  
        self.old_name = company_name 
        vault_file = Path(self.app_path) / "company_vault.json"
        
        if vault_file.exists():
            with open(vault_file, 'r', encoding='utf-8') as f:
                db = json.load(f)
                if company_name in db:
                    data = db[company_name]
                    self.header_label.setText("  Alter Company") 
                    self.save_btn.setText("Update Company")
                    self.fields[0].setText(data.get("display_name", company_name))
                    self.fields[1].setText(data.get("user", ""))
                    self.fields[2].setText(data.get("pass", ""))
                    self.fields[3].setText(data.get("pass", ""))
                    full_path = data.get("path", "")
                    base_loc = os.path.dirname(full_path)
                    self.fields[4].setText(base_loc)
                    self.fields[5].setText(data.get("image_path", ""))
    
    def browse(self, target):
        p = QFileDialog.getExistingDirectory(self, "Select Folder")
        if p: target.setText(p)

    def back_to_list(self):
        for f in self.fields: f.clear()
        self.edit_mode = False
        self.header_label.setText("  Company Creation")
        self.back_callback()

    def save_data(self):
        original_name = self.fields[0].text().strip()
        user = self.fields[1].text().strip()
        password = self.fields[2].text().strip()
        base_location = self.fields[4].text().strip()
        image_location = self.fields[5].text().strip()

        if not original_name or not base_location:
            self.error_lbl.setText("❌ Company Name & Location are required!")
            return
        
        folder_safe_name = original_name.replace("/", "_").replace("\\", "_")
        try:
            target_path = Path(base_location) / folder_safe_name
            if not self.edit_mode:
                target_path.mkdir(parents=True, exist_ok=True)
                report_file_path = str(target_path / "REPORT_DATA.JSON")
                save_report_json({}, report_file_path)

            vault_file = Path(self.app_path) / "company_vault.json"
            db = {}
            if vault_file.exists():
                with open(vault_file, 'r', encoding='utf-8') as f:
                    try: db = json.load(f)
                    except: db = {}

            if self.edit_mode and self.old_name != original_name:
                if self.old_name in db: del db[self.old_name]

            db[original_name] = {
                "display_name": original_name,
                "user": user,
                "pass": password,
                "path": str(target_path),
                "image_path": image_location
            }

            with open(vault_file, 'w', encoding='utf-8') as f:
                json.dump(db, f, indent=4, ensure_ascii=False)

            msg = "Updated!" if self.edit_mode else "Created!"
            QMessageBox.information(self, "Success", f"Company '{original_name}' {msg}")
            self.edit_mode = False
            self.back_to_list()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")

# ================= 4. MAIN UI MANAGER =================
class CompanyLoginUI(QWidget):
    login_success_signal = pyqtSignal(str) 

    def __init__(self):
        super().__init__()
        self.app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_file = os.path.join(self.app_path, "config.json")
        self.vault_file = os.path.join(self.app_path, "company_vault.json")
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
        title = QLabel("  List of Company")
        title.setObjectName("ListHeaderTitle")
        hl.addWidget(title)
        layout.addWidget(header)
        
        cl = QVBoxLayout()
        cl.setContentsMargins(40, 20, 40, 20)
        cl.addWidget(QLabel("<b>Data Path / Name</b>"))
        
        self.list = QListWidget()
        self.list.setObjectName("CompanyListWidget") # QSS: #CompanyListWidget
        cl.addWidget(self.list)
        
        cw = QWidget()
        cw.setLayout(cl)
        layout.addWidget(cw)
        
        self.list.itemActivated.connect(self.on_enter)
        QShortcut(QKeySequence("Return"), self.list, activated=lambda: self.on_enter(self.list.currentItem()))

    def load_main_list(self):
        self.list.clear()
        self.add_item("Create Company", align_right=True, role="create")
        self.add_item("Data Path", align_right=True, role="set_path")
        
        line = QListWidgetItem()
        line.setFlags(Qt.ItemFlag.NoItemFlags)
        line.setSizeHint(QSize(100, 2))
        self.list.addItem(line)
        f = QFrame()
        f.setObjectName("ListSeparator") # QSS: #ListSeparator
        f.setFixedHeight(2)
        self.list.setItemWidget(line, f)
        
        self.add_item(self.current_data_path, is_bold=True)

        if os.path.exists(self.vault_file):
            with open(self.vault_file, 'r', encoding='utf-8') as f:
                try:
                    vault = json.load(f)
                    for comp_name in vault.keys():
                        self.add_item(comp_name, role="company_folder")
                except: pass
        self.list.setCurrentRow(0)

    def add_item(self, text, role=None, align_right=False, is_bold=False):
        item = QListWidgetItem(text)
        if align_right: item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        if is_bold: 
            font = QFont()
            font.setBold(True)
            item.setFont(font)
        item.setData(Qt.ItemDataRole.UserRole, role)
        self.list.addItem(item)

    def on_enter(self, item):
        if not item: return
        role = item.data(Qt.ItemDataRole.UserRole)
        
        if role == "create": 
            self.stack.setCurrentIndex(1)
        elif role == "set_path":
            dlg = PathDialog(self.current_data_path, self)
            if dlg.exec():
                new_p = dlg.get_path()
                if os.path.exists(new_p):
                    with open(self.config_file, 'w') as f: 
                        json.dump({"default_path": new_p}, f)
                    self.current_data_path = new_p
                    self.load_main_list()
        elif role == "company_folder": 
            self.handle_company_login(item.text())

    def handle_company_login(self, comp_name):
        vault = {}
        if os.path.exists(self.vault_file):
            with open(self.vault_file, 'r', encoding='utf-8') as f:
                vault = json.load(f)
            
        if comp_name in vault:
            dlg = LoginDialog(comp_name, vault[comp_name]["user"], vault[comp_name]["pass"], self)
            if dlg.exec():
                self.login_success_signal.emit(comp_name) 
        else:
            QMessageBox.warning(self, "Security", f"Company '{comp_name}' not in Vault!")
            
    def show_list(self):
        self.stack.setCurrentIndex(0)
        self.load_main_list()