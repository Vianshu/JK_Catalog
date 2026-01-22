import json
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QMessageBox
)

class EmptyPagesDialog(QDialog):
    def __init__(self, empty_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Empty Pages Found")
        self.resize(500, 400)
        self.empty_pages = empty_pages
        
        layout = QVBoxLayout(self)
        
        if not empty_pages:
            layout.addWidget(QLabel("No empty pages found!"))
            ok_btn = QPushButton("OK")
            ok_btn.clicked.connect(self.accept)
            layout.addWidget(ok_btn)
            return

        layout.addWidget(QLabel(f"Found {len(empty_pages)} empty pages:"))
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Group", "SubGroup (SN)", "Page No"])
        self.table.setRowCount(len(empty_pages))
        
        for i, (g, s, p) in enumerate(empty_pages):
            self.table.setItem(i, 0, QTableWidgetItem(str(g)))
            self.table.setItem(i, 1, QTableWidgetItem(str(s)))
            self.table.setItem(i, 2, QTableWidgetItem(str(p)))
            
        layout.addWidget(self.table)
        
        btn_box = QHBoxLayout()
        self.btn_delete = QPushButton("Delete All Empty Pages")
        self.btn_delete.setObjectName("BtnDeleteEmptyPages")
        self.btn_close = QPushButton("Close")
        
        self.btn_delete.clicked.connect(self.accept) # Accept means delete
        self.btn_close.clicked.connect(self.reject)
        
        btn_box.addWidget(self.btn_delete)
        btn_box.addWidget(self.btn_close)
        layout.addLayout(btn_box)
from PyQt6.QtCore import Qt

# --- CRM Dialog ---
class CRMDialog(QDialog):
    def __init__(self, mode="create", current_name="", crm_list=None, parent=None):
        super().__init__(parent)
        self.setObjectName("CRMManagerDialog")
        self.setWindowTitle("CRM Manager")
        self.setFixedSize(300, 180)
        layout = QVBoxLayout(self)
        self.mode = mode
        self.crm_list = crm_list if crm_list else []
        
        if mode == "alter":
            self.combo = QComboBox()
            self.combo.setObjectName("CRMCombo")
            self.combo.addItems(self.crm_list)
            layout.addWidget(QLabel("Select CRM to Alter:"))
            layout.addWidget(self.combo)
            layout.addWidget(QLabel("New Name:"))
        else:
            layout.addWidget(QLabel("Enter CRM Name:"))

        self.input_name = QLineEdit(current_name)
        self.input_name.setObjectName("CRMInput") # Style Tag
        layout.addWidget(self.input_name)
        
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryActionButton") # Style Tag
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def get_data(self):
        if self.mode == "alter":
            return self.combo.currentText(), self.input_name.text().strip()
        return self.input_name.text().strip()

    def accept(self):
        new_name = self.input_name.text().strip()
        
        if not new_name:
            QMessageBox.warning(self, "Error", "CRM Name cannot be empty!")
            return

        if self.mode == "create":
            existing_crms = load_crm_list()
            if any(name.lower() == new_name.lower() for name in existing_crms):
                QMessageBox.critical(
                    self, 
                    "Duplicate Name", 
                    f"Error: '{new_name}' already exists!\nPlease use a different name."
                )
                return 

        super().accept()
        
# --- User Manager Dialog ---
class UserManagerDialog(QDialog):
    def __init__(self, company_name, mode="create", parent=None):
        super().__init__(parent)
        self.setObjectName("UserManagerDialog") # Style Tag
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setFixedSize(550, 450)
        # इनलाइन स्टाइल को कम करके क्लास लेवल पर रखा है
        # self.setStyleSheet("QDialog#UserManagerDialog { background-color: #f4f4f4; border: 2px solid #333; }")

        layout = QVBoxLayout(self)
        title = QLabel("List of User")
        title.setObjectName("UserDialogTitle") # Style Tag
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # title.setStyleSheet("font-size: 22px; font-weight: bold; text-decoration: underline;")
        layout.addWidget(title)

        layout.addWidget(QLabel(f"<b>Company:</b> {company_name}"))

        self.table = QTableWidget(10, 3)
        self.table.setObjectName("UserSetupTable") # Style Tag
        self.table.setHorizontalHeaderLabels(["User Roles", "Username", "Password"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save (Yes/No)")
        save_btn.setObjectName("ExecuteImportBtn") # Style Tag
        save_btn.clicked.connect(self.confirm_save)
        cancel_btn = QPushButton("Cancel / Close")
        cancel_btn.clicked.connect(self.reject)

        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def confirm_save(self):
        reply = QMessageBox.question(self, 'Save Data', 'Do you want to save?', 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.accept()

    def get_table_data(self):
        user_list = []
        rows = self.table.rowCount()
        for row in range(rows):
            role_item = self.table.item(row, 0)
            user_item = self.table.item(row, 1)
            pwd_item = self.table.item(row, 2)

            if role_item is not None and user_item is not None and pwd_item is not None:
                r = role_item.text().strip()
                u = user_item.text().strip()
                p = pwd_item.text().strip()
                if r and u and p:
                    user_list.append({
                        "role": r,
                        "username": u,
                        "password": p
                    })
        return user_list
    
# --- Security Dialog ---
class SecurityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SecurityDialog") # Style Tag
        self.setWindowTitle("Security Level")
        self.setFixedSize(600, 450)
        layout = QVBoxLayout(self)
        
        header = QLabel("<h2>Security Level</h2>")
        header.setObjectName("SecurityHeader") # Style Tag
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name of Security Level:"))
        self.sec_name = QLineEdit()
        self.sec_name.setObjectName("SecurityNameInput") # Style Tag
        name_layout.addWidget(self.sec_name)
        layout.addLayout(name_layout)

        self.table = QTableWidget(10, 4)
        self.table.setObjectName("SecurityTable") # Style Tag
        self.table.setHorizontalHeaderLabels(["Type", "Disallow", "Type", "Allow"])
        layout.addWidget(self.table)

        save_btn = QPushButton("Save Security Level")
        save_btn.setObjectName("PrimaryActionButton") # Style Tag
        save_btn.clicked.connect(self.accept)
        layout.addWidget(save_btn)

# --- आपके फंक्शन्स (बिना किसी बदलाव के) ---

def save_users_to_json(company, users):
    filename = "users_data.json"
    all_data = {}
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding='utf-8') as f:
                all_data = json.load(f)
        except: all_data = {}

    all_data[company] = users
    try:
        with open(filename, "w", encoding='utf-8') as f:
            json.dump(all_data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        return True
    except: return False

def load_crm_list(file_path="crm_data.json"):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding='utf-8') as f:
                return json.load(f)
        except: return []
    return []

def save_crm_to_json(name, file_path="crm_data.json"):
    try:
        data = load_crm_list(file_path)
        if name not in data:
            data.append(name)
            folder = os.path.dirname(file_path)
            if folder and not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
                
            with open(file_path, "w", encoding='utf-8') as f: 
                json.dump(data, f, indent=4)
        return True
    except: return False

def update_crm_in_json(old_name, new_name, file_path="crm_data.json"):
    try:
        data = load_crm_list(file_path)
        if old_name in data:
            data[data.index(old_name)] = new_name
            with open(file_path, "w", encoding='utf-8') as f: 
                json.dump(data, f, indent=4)
        return True
    except: return False
    
def load_report_json(file_path="REPORT_DATA.JSON"):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_report_json(data, file_path="REPORT_DATA.JSON"):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def add_pages_to_all_crms(page_serial_numbers, company_path):
    """Add page serial numbers to all CRMs' pending lists.
    
    Args:
        page_serial_numbers: List of page serial numbers (from catalog_pages.serial_no)
        company_path: Path to company folder for finding crm_data.json and REPORT_DATA.JSON
    
    Returns:
        Number of CRMs updated
    """
    if not page_serial_numbers:
        return 0
    
    # Convert to strings for JSON storage
    pages_to_add = [str(p) for p in page_serial_numbers]
    
    # Load CRM list
    crm_path = os.path.join(company_path, "crm_data.json") if company_path else "crm_data.json"
    crm_list = load_crm_list(crm_path)
    
    if not crm_list:
        return 0
    
    # Load report data
    report_path = os.path.join(company_path, "REPORT_DATA.JSON") if company_path else "REPORT_DATA.JSON"
    report_data = load_report_json(report_path)
    
    updated_count = 0
    
    for crm_name in crm_list:
        if crm_name not in report_data:
            report_data[crm_name] = {"pending": [], "recent": []}
        
        # Get current pending (ensure it's a list)
        current_pending = report_data[crm_name].get("pending", [])
        if not isinstance(current_pending, list):
            current_pending = []
        
        # Add new pages (unique only)
        added_any = False
        for page in pages_to_add:
            if page not in current_pending:
                current_pending.append(page)
                added_any = True
        
        if added_any:
            report_data[crm_name]["pending"] = current_pending
            updated_count += 1
    
    # Save updated report data
    save_report_json(report_data, report_path)
    
    return updated_count