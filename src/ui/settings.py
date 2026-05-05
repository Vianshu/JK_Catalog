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
    def __init__(self, company_name, company_path, parent=None):
        super().__init__(parent)
        self.company_name = company_name
        self.company_path = company_path
        
        # Initialize Security Manager (SQL Server — takes data_path, not .db file)
        from src.logic.security_manager import SecurityManager
        data_path = os.path.dirname(company_path) if company_path else ""
        try:
            self.security = SecurityManager(data_path)
        except Exception as e:
            self.security = None
            QMessageBox.warning(self, "Security Error",
                f"Could not connect to Security database.\n{e}")
        
        self.setObjectName("UserManagerDialog") # Style Tag
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setFixedSize(550, 450)

        layout = QVBoxLayout(self)
        title = QLabel("List of User")
        title.setObjectName("UserDialogTitle") # Style Tag
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(QLabel(f"<b>Company:</b> {company_name}"))

        self.table = QTableWidget(10, 3)
        self.table.setObjectName("UserSetupTable") # Style Tag
        self.table.setHorizontalHeaderLabels(["User Roles", "Username", "Password"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # Load existing users from DB
        self.load_users()

        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save (Yes/No)")
        save_btn.setObjectName("ExecuteImportBtn") # Style Tag
        save_btn.clicked.connect(self.confirm_save)
        cancel_btn = QPushButton("Cancel / Close")
        cancel_btn.clicked.connect(self.reject)

        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def load_users(self):
        try:
            users = self.security.get_users_for_company(self.company_path)
            # Users is a list of dicts: [{'username': 'a', 'role': 'r'}, ...]
            # Note: We CANNOT retrieve passwords because they are hashed.
            # We will show empty password fields (or placeholder).
            
            self.table.setRowCount(max(10, len(users) + 5))
            
            for i, u in enumerate(users):
                self.table.setItem(i, 0, QTableWidgetItem(u['role']))
                self.table.setItem(i, 1, QTableWidgetItem(u['username']))
                self.table.setItem(i, 2, QTableWidgetItem("")) # Password empty for security
        except Exception as e:
            print(f"Error loading users: {e}")

    def confirm_save(self):
        reply = QMessageBox.question(self, 'Save Data', 'Do you want to save users?\n(Only rows with passwords will be updated/added)', 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.save_users()
            self.accept()

    def save_users(self):
        rows = self.table.rowCount()
        for row in range(rows):
            role_item = self.table.item(row, 0)
            user_item = self.table.item(row, 1)
            pwd_item = self.table.item(row, 2)

            if role_item and user_item and pwd_item:
                r = role_item.text().strip()
                u = user_item.text().strip()
                p = pwd_item.text().strip()
                
                # Only add/update if password is provided (since we can't read old hash back to UI)
                if r and u and p:
                    success = self.security.add_user(self.company_path, u, p, r)
                    if not success:
                        print(f"Failed to add user {u} (might already exist)")
        
        QMessageBox.information(self, "Success", "Users updated in secure database.")

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

# --- CRM & Report Data Functions (SQL Server via db_manager) ---

from src.logic.db_manager import get_db_manager, build_logical_name

def _get_catalog_db(company_path):
    """Resolve the Catalog DB logical name from a company_path.
    
    Accepts either:
      - A company folder path (e.g., 'D:\\Data\\HW Divison 082083')
      - A legacy file_path (e.g., 'D:\\Data\\HW Divison 082083\\crm_data.json') — extracts dirname
    """
    if not company_path:
        return ""
    # If caller passed a file path, extract the directory
    if os.path.splitext(company_path)[1]:  # has file extension
        company_path = os.path.dirname(company_path)
    company_name = os.path.basename(company_path)
    return build_logical_name(company_name, "catalog")

def _ensure_crm_table(db, db_name):
    """Ensure the crm_names table exists."""
    db.ensure_table(db_name, "crm_names", """
        CREATE TABLE crm_names (
            id INT IDENTITY(1,1) PRIMARY KEY,
            crm_name NVARCHAR(255) NOT NULL UNIQUE
        )
    """)

def _ensure_report_table(db, db_name):
    """Ensure the report_data table exists."""
    db.ensure_table(db_name, "report_data", """
        CREATE TABLE report_data (
            id INT IDENTITY(1,1) PRIMARY KEY,
            crm_name NVARCHAR(255) NOT NULL,
            serial_no NVARCHAR(50) NOT NULL,
            status NVARCHAR(20) DEFAULT 'pending'
        )
    """)


def load_crm_list(company_path=""):
    """Load all CRM names from the Catalog DB's crm_names table.
    
    Args:
        company_path: Company folder path, or legacy file path (e.g., crm_data.json)
    
    Returns:
        List of CRM name strings.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return []
    db = get_db_manager()
    _ensure_crm_table(db, db_name)
    rows = db.execute_query(db_name, "SELECT crm_name FROM crm_names ORDER BY id")
    return [r[0] for r in rows] if rows else []


def save_crm_to_json(name, company_path=""):
    """Add a new CRM name to the Catalog DB's crm_names table.
    
    Args:
        name: CRM name to add
        company_path: Company folder path, or legacy file path
    
    Returns:
        True on success, False on failure.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return False
    db = get_db_manager()
    _ensure_crm_table(db, db_name)
    try:
        conn = db.get_connection(db_name)
        if not conn:
            return False
        cursor = conn.cursor()
        # Check if already exists (case-insensitive)
        cursor.execute("SELECT COUNT(*) FROM crm_names WHERE crm_name = ?", name)
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO crm_names (crm_name) VALUES (?)", name)
            conn.commit()
        return True
    except Exception:
        return False


def update_crm_in_json(old_name, new_name, company_path=""):
    """Rename a CRM in the Catalog DB's crm_names table.
    
    Args:
        old_name: Current CRM name
        new_name: New CRM name
        company_path: Company folder path, or legacy file path
    
    Returns:
        True on success, False on failure.
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return False
    db = get_db_manager()
    try:
        conn = db.get_connection(db_name)
        if not conn:
            return False
        cursor = conn.cursor()
        cursor.execute("UPDATE crm_names SET crm_name = ? WHERE crm_name = ?", (new_name, old_name))
        # Also update report_data references
        cursor.execute("UPDATE report_data SET crm_name = ? WHERE crm_name = ?", (new_name, old_name))
        conn.commit()
        return True
    except Exception:
        return False

    
def load_report_json(company_path=""):
    """Load report data from the Catalog DB's report_data table.
    
    Returns a dict matching the legacy JSON structure:
        { "CRM_Name": { "pending": [...], "recent": [...] }, ... }
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return {}
    db = get_db_manager()
    _ensure_report_table(db, db_name)
    rows = db.execute_query(db_name,
        "SELECT crm_name, serial_no, status FROM report_data ORDER BY crm_name, id")
    if not rows:
        return {}
    result = {}
    for crm_name, serial_no, status in rows:
        if crm_name not in result:
            result[crm_name] = {"pending": [], "recent": []}
        bucket = "pending" if status == "pending" else "recent"
        result[crm_name][bucket].append(serial_no)
    return result


def save_report_json(data, company_path=""):
    """Save report data to the Catalog DB's report_data table.
    
    Args:
        data: Dict matching legacy structure { "CRM_Name": {"pending": [...], "recent": [...]} }
        company_path: Company folder path, or legacy file path
    """
    db_name = _get_catalog_db(company_path)
    if not db_name:
        return
    db = get_db_manager()
    _ensure_report_table(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM report_data")
        for crm_name, buckets in data.items():
            if not isinstance(buckets, dict):
                continue
            for serial_no in buckets.get("pending", []):
                cursor.execute(
                    "INSERT INTO report_data (crm_name, serial_no, status) VALUES (?, ?, 'pending')",
                    (crm_name, str(serial_no)))
            for serial_no in buckets.get("recent", []):
                cursor.execute(
                    "INSERT INTO report_data (crm_name, serial_no, status) VALUES (?, ?, 'completed')",
                    (crm_name, str(serial_no)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] save_report_json failed: {e}")


def add_pages_to_all_crms(page_serial_numbers, company_path):
    """Add page serial numbers to all CRMs' pending lists.
    
    Args:
        page_serial_numbers: List of page serial numbers (from catalog_pages.serial_no)
        company_path: Path to company folder
    
    Returns:
        Number of CRMs updated
    """
    if not page_serial_numbers:
        return 0
    
    pages_to_add = [str(p) for p in page_serial_numbers]
    crm_list = load_crm_list(company_path)
    
    if not crm_list:
        return 0
    
    report_data = load_report_json(company_path)
    
    updated_count = 0
    
    for crm_name in crm_list:
        if crm_name not in report_data:
            report_data[crm_name] = {"pending": [], "recent": []}
        
        current_pending = report_data[crm_name].get("pending", [])
        if not isinstance(current_pending, list):
            current_pending = []
        
        added_any = False
        for page in pages_to_add:
            if page not in current_pending:
                current_pending.append(page)
                added_any = True
        
        if added_any:
            report_data[crm_name]["pending"] = current_pending
            updated_count += 1
    
    save_report_json(report_data, company_path)
    
    return updated_count