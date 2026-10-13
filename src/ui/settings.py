import json

from src.logic.report_store import load_crm_list, save_crm_to_json, update_crm_in_json, load_report_json, save_report_json, add_pages_to_all_crms
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QMessageBox,
    QWidget, QFrame, QInputDialog, QScrollArea, QCheckBox, QGridLayout, QGroupBox
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

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
        
# --- User Manager Dialog (RBAC-aware) ---

class UserManagerDialog(QDialog):
    """Manage users within a company — create, edit roles, reset passwords, deactivate."""
    def __init__(self, company_name, company_path, security_mgr=None, parent=None):
        super().__init__(parent)
        self.company_name = company_name
        self.company_path = company_path
        self.roles = []
        
        # Use provided security manager or create one
        if security_mgr:
            self.security = security_mgr
        else:
            from src.logic.security_manager import SecurityManager
            data_path = os.path.dirname(company_path) if company_path else ""
            try:
                self.security = SecurityManager(data_path)
            except Exception as e:
                self.security = None
                QMessageBox.warning(self, "Security Error", f"Could not connect.\n{e}")
        
        self.setObjectName("UserManagerDialog")
        self.setWindowTitle(f"User Management — {company_name}")
        self.setFixedSize(850, 500)

        layout = QVBoxLayout(self)
        title = QLabel(f"<h3>Users — {company_name}</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # User table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Username", "Role", "Active", "Last Login", "Actions"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 130)
        layout.addWidget(self.table)

        # Add user section
        add_frame = QFrame()
        add_layout = QHBoxLayout(add_frame)
        add_layout.setContentsMargins(0, 5, 0, 5)
        add_layout.addWidget(QLabel("New:"))
        self.new_user_edit = QLineEdit()
        self.new_user_edit.setPlaceholderText("Username")
        self.new_user_edit.setFixedWidth(120)
        add_layout.addWidget(self.new_user_edit)
        self.new_pass_edit = QLineEdit()
        self.new_pass_edit.setPlaceholderText("Password")
        self.new_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass_edit.setFixedWidth(120)
        add_layout.addWidget(self.new_pass_edit)
        self.new_role_combo = QComboBox()
        self.new_role_combo.setFixedWidth(140)
        add_layout.addWidget(self.new_role_combo)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_user)
        add_layout.addWidget(add_btn)
        add_layout.addStretch()
        layout.addWidget(add_frame)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self._load_roles()
        self._load_users()

    def _get_company_id(self):
        if not self.security:
            return None
        return self.security.get_company_id_by_path(self.company_path)

    def _load_roles(self):
        self.new_role_combo.clear()
        cid = self._get_company_id()
        if not cid or not self.security:
            return
        self.roles = self.security.get_roles_for_company(cid)
        for r in self.roles:
            self.new_role_combo.addItem(r["role_name"], r["id"])

    def _load_users(self):
        if not self.security:
            return
        users = self.security.get_users_for_company(self.company_path)
        self.table.setRowCount(len(users))
        
        for i, u in enumerate(users):
            name_item = QTableWidgetItem(f"{'(Admin) ' if u['is_admin'] else ''}{u['username'] or '(empty)'}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, name_item)
            
            role_combo = QComboBox()
            for r in self.roles:
                role_combo.addItem(r["role_name"], r["id"])
            for idx in range(role_combo.count()):
                if role_combo.itemText(idx) == u["role_name"]:
                    role_combo.setCurrentIndex(idx)
                    break
            if u["is_admin"]:
                role_combo.setEnabled(False)
            else:
                uid = u["id"]
                role_combo.activated.connect(
                    lambda _, uid=uid, cb=role_combo: self._update_user_role(uid, cb.currentData()))
            self.table.setCellWidget(i, 1, role_combo)
            
            active_item = QTableWidgetItem("Yes" if u["is_active"] else "No")
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            active_item.setFlags(active_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, active_item)
            
            login_text = str(u["last_login"])[:16] if u["last_login"] else "Never"
            login_item = QTableWidgetItem(login_text)
            login_item.setFlags(login_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 3, login_item)
            
            if not u["is_admin"]:
                action_w = QWidget()
                al = QHBoxLayout(action_w)
                al.setContentsMargins(2, 2, 2, 2)
                al.setSpacing(4)
                uid, uname, is_active = u["id"], u["username"], u["is_active"]
                
                rb = QPushButton("Reset")
                rb.setToolTip("Reset Password")
                rb.setFixedHeight(28)
                rb.setObjectName("BtnResetPw")
                rb.clicked.connect(lambda _, uid=uid, un=uname: self._reset_pw(uid, un))
                al.addWidget(rb)
                
                tb = QPushButton("Disable" if is_active else "Enable")
                tb.setToolTip("Deactivate" if is_active else "Activate")
                tb.setFixedHeight(28)
                if is_active:
                    tb.setObjectName("BtnDisableUser")
                else:
                    tb.setObjectName("BtnEnableUser")
                tb.clicked.connect(lambda _, uid=uid, a=is_active: self._toggle(uid, a))
                al.addWidget(tb)
                
                db = QPushButton("Delete")
                db.setToolTip("Delete User")
                db.setFixedHeight(28)
                db.setObjectName("BtnDeleteUser")
                db.clicked.connect(lambda _, uid=uid, un=uname: self._del(uid, un))
                al.addWidget(db)
                self.table.setCellWidget(i, 4, action_w)

    def _get_session(self):
        return getattr(self.parent(), "user_session", None)

    def _reset_pw(self, uid, uname):
        pw, ok = QInputDialog.getText(self, "Reset Password", f"New password for '{uname}':", QLineEdit.EchoMode.Password)
        if ok:
            self.security.update_user(uid, password=pw)
            self.security.log_action(self._get_session(), "USER_EDIT", "Users", f"Reset password for '{uname}'")
            if hasattr(self.parent(), "refresh_user_permissions"):
                self.parent().refresh_user_permissions()
            QMessageBox.information(self, "Done", f"Password reset for '{uname}'.")

    def _update_user_role(self, uid, role_id):
        self.security.update_user(uid, role_id=role_id)
        self.security.log_action(self._get_session(), "USER_EDIT", "Users", f"Changed role for user ID {uid} to {role_id}")
        if hasattr(self.parent(), "refresh_user_permissions"):
            self.parent().refresh_user_permissions()
            
    def _toggle(self, uid, is_active):
        self.security.update_user(uid, is_active=not is_active)
        self.security.log_action(self._get_session(), "USER_EDIT", "Users", f"Toggled active state for user ID {uid} to {not is_active}")
        if hasattr(self.parent(), "refresh_user_permissions"):
            self.parent().refresh_user_permissions()
        self._load_users()

    def _del(self, uid, uname):
        if QMessageBox.question(self, "Delete", f"Delete '{uname}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.security.delete_user(uid)
            self.security.log_action(self._get_session(), "USER_DELETE", "Users", f"Deleted user '{uname}'")
            self._load_users()

    def _add_user(self):
        uname = self.new_user_edit.text().strip()
        pw = self.new_pass_edit.text()
        rid = self.new_role_combo.currentData()
        if not uname:
            QMessageBox.warning(self, "Error", "Username required."); return
        if self.security.add_user(self.company_path, uname, pw, rid):
            self.security.log_action(self._get_session(), "USER_CREATE", "Users", f"Created user '{uname}' with role {rid}")
            self.new_user_edit.clear(); self.new_pass_edit.clear()
            self._load_users()
        else:
            QMessageBox.warning(self, "Error", f"User '{uname}' already exists.")


# --- Role / Security Manager Dialog ---
# ─────────────────────────────────────────────────────────────────────────────
# QComboBox that ignores scroll-wheel events (value only changes on click)
# ─────────────────────────────────────────────────────────────────────────────
from PyQt6.QtGui import QWheelEvent

class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse-wheel events so accidental scrolling never
    changes the selected permission.  Only explicit clicks work."""
    def wheelEvent(self, event: QWheelEvent):
        event.ignore()  # pass the scroll up to the parent scroll area



# ─────────────────────────────────────────────────────────────────────────────
# Main SecurityUI widget
# ─────────────────────────────────────────────────────────────────────────────
class SecurityUI(QWidget):
    """Role & permission manager — clean redesigned UI."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.mw = parent
        self.company_name = getattr(parent, 'current_company', "") if parent else ""
        self.company_path = getattr(parent, 'current_company_path', "") if parent else ""
        self.roles = []
        self.security = None
        self.setObjectName("SecurityUI")

        # Debounce timer for auto-save (300 ms after last change)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_auto_save)

        # Status-clear timer
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear_status)

        # ── Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top header — page title only, clean white surface
        header_frame = QFrame()
        header_frame.setObjectName("SecurityHeaderBanner")
        header_frame.setStyleSheet("""
            #SecurityHeaderBanner {
                background: #ffffff;
                border-bottom: 1px solid #e2e8f0;
                min-height: 60px; max-height: 60px;
            }
        """)
        hdr_lay = QHBoxLayout(header_frame)
        hdr_lay.setContentsMargins(24, 0, 24, 0)
        hdr_lay.setSpacing(0)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        self._title_lbl = QLabel("Security & Permissions")
        self._title_lbl.setObjectName("SecurityTitle")
        self._title_lbl.setStyleSheet(
            "color: #0f172a; font-size: 17px; font-weight: 700;"
        )
        self._sub_lbl = QLabel(self.company_name or "No company loaded")
        self._sub_lbl.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: 400;"
        )
        title_block.addWidget(self._title_lbl)
        title_block.addWidget(self._sub_lbl)
        hdr_lay.addLayout(title_block)
        hdr_lay.addStretch()

        root.addWidget(header_frame)

        # ── Role management bar — selector + actions in one grouped section
        role_bar = QFrame()
        role_bar.setObjectName("SecurityRoleBar")
        role_bar.setStyleSheet("""
            #SecurityRoleBar {
                background: #f8fafc;
                border-bottom: 1px solid #e2e8f0;
                min-height: 56px; max-height: 56px;
            }
        """)
        role_bar_lay = QHBoxLayout(role_bar)
        role_bar_lay.setContentsMargins(24, 0, 24, 0)
        role_bar_lay.setSpacing(10)

        editing_lbl = QLabel("Editing role")
        editing_lbl.setStyleSheet(
            "color: #64748b; font-size: 12px; font-weight: 500;"
        )
        role_bar_lay.addWidget(editing_lbl)

        self.role_combo = NoScrollComboBox()
        self.role_combo.setObjectName("SecurityRoleCombo")
        self.role_combo.setMinimumWidth(200)
        self.role_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.role_combo.setStyleSheet("""
            QComboBox#SecurityRoleCombo {
                background: #ffffff;
                color: #0f172a;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 32px 5px 12px;
                font-size: 13px;
                font-weight: 600;
                min-height: 32px;
            }
            QComboBox#SecurityRoleCombo:hover { border-color: #2563eb; }
            QComboBox#SecurityRoleCombo::drop-down { border: none; width: 28px; }
            QComboBox#SecurityRoleCombo::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #64748b;
                width: 0; height: 0;
                margin-right: 8px;
            }
            QComboBox#SecurityRoleCombo QAbstractItemView {
                background: #ffffff; color: #0f172a;
                border: 1px solid #e2e8f0;
                padding: 4px;
                selection-background-color: #eff6ff;
                selection-color: #1d4ed8;
                outline: none;
            }
        """)
        self.role_combo.currentIndexChanged.connect(self._on_role_selected)
        role_bar_lay.addWidget(self.role_combo)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #e2e8f0;")
        sep.setFixedHeight(24)
        role_bar_lay.addWidget(sep)

        self.btn_new = QPushButton("+ New Role")
        self.btn_new.setObjectName("SecurityNewBtn")
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setStyleSheet("""
            QPushButton {
                background: #2563eb; color: white; border: none;
                border-radius: 6px; padding: 7px 16px;
                font-size: 12px; font-weight: 600;
                min-height: 32px;
            }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:pressed { background: #1e40af; }
        """)
        self.btn_new.clicked.connect(self._create_role)
        role_bar_lay.addWidget(self.btn_new)

        self.btn_del = QPushButton("Delete Role")
        self.btn_del.setObjectName("SecurityDelBtn")
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.setStyleSheet("""
            QPushButton {
                background: transparent; color: #ef4444;
                border: 1px solid #fca5a5; border-radius: 6px;
                padding: 7px 14px; font-size: 12px; font-weight: 500;
                min-height: 32px;
            }
            QPushButton:hover { background: #fef2f2; border-color: #ef4444; }
            QPushButton:pressed { background: #fee2e2; }
            QPushButton:disabled { color: #94a3b8; border-color: #e2e8f0; }
        """)
        self.btn_del.clicked.connect(self._delete_role)
        role_bar_lay.addWidget(self.btn_del)

        role_bar_lay.addStretch()

        # Auto-save status indicator — right side of role bar
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("SecurityStatusLbl")
        self._status_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        role_bar_lay.addWidget(self._status_lbl)

        root.addWidget(role_bar)

        # ── Facility groups data
        self.facility_combos = {}
        self.facility_groups = [
            ("Catalog", [
                ("Sync Tally",          ["tab.final_data"],     ["final_data.sync"]),
                ("Super Master",        ["tab.super_master"],   ["super_master.edit"]),
                ("Final Data",          ["tab.final_data"],     ["final_data.edit", "final_data.export"]),
                ("Full Catalog (Tab)",  ["tab.catalog"],        []),
                (" \u21b3 Build Button",     [],                     ["catalog.build"]),
                (" \u21b3 Auto Build",       [],                     ["catalog.build_auto"]),
                (" \u21b3 Print / Export",   [],                     ["catalog.print"]),
                (" \u21b3 Reshuffle",        [],                     ["catalog.reshuffle"]),
                (" \u21b3 Page Manage",      [],                     ["catalog.page_management"]),
                ("Reports",             ["tab.reports"],        ["reports.print", "reports.mark_done"]),
                ("Catalog Price List",  ["tab.cat_price_list"], ["cat_price_list.edit"]),
                ("Create / Alter CRM",  [],                     ["settings.manage_crm"]),
            ]),
            ("Vat Working", [
                ("Vat Balance",         ["tab.vat_balance"],    ["vat_balance.edit", "vat_balance.sync"]),
                (" ↳ Clear Mapping",    [],                     ["vat_balance.clear_mapping"]),
                ("Vat Stock",           ["tab.vat_stock"],      ["vat_stock.edit"]),
                ("Export / Print",      [],                     ["vat.export_print"]),
            ]),
            ("Tally Internal", [
                ("Sync Ledger",         ["tab.ledger"],         ["ledger.sync"]),
                ("Ledger Rows",         ["tab.ledger"],         []),
                ("On Account",          ["tab.on_account"],     []),
                ("Cheque List",         ["tab.cheque_list"],    ["cheque_list.edit"]),
                ("Godown List",         ["tab.godown"],         ["godown.edit"]),
                ("Sales Chat",          ["tab.sales_chat"],     ["sales_chat.edit"]),
                ("Supplier Payment",    ["tab.supp_payment"],   ["supp_payment.edit"]),
                ("Price List",          ["tab.price_list"],     ["price_list.edit"]),
                ("Purchase Import",     ["tab.pur_import"],     ["pur_import.import"]),
                ("Internal Cost Sheet", ["tab.int_cost_sheet"], ["int_cost_sheet.edit"]),
                ("For Branch",          ["tab.for_branch"],     []),
            ]),
            ("Settings", [
                ("Calendar",            ["tab.calendar"],       ["calendar.edit"]),
                ("Backup Data",         [],                     ["data.export"]),
                ("Import Data",         [],                     ["data.import"]),
                ("Admin / Users",       [],                     ["settings.manage_users", "settings.manage_roles",
                                                                 "settings.company_config",
                                                                 "settings.change_path"]),
            ]),
        ]

        # ── Permission grid
        self._build_perm_grid(root)
        self._load_roles()


    def _build_perm_grid(self, parent_layout):
        """Build 4 section cards side-by-side with clean, modern styling."""

        self.master_combos = {}        # group_name → NoScrollComboBox
        self.group_facility_names = {} # group_name → [fac_name, ...]

        # ── Shared dropdown style: white bg, explicit affordance cues
        combo_style = """
            QComboBox {
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #e2e8f0;
                border-radius: 5px;
                padding: 4px 28px 4px 10px;
                font-size: 12px;
                font-weight: 500;
                min-height: 28px;
                min-width: 90px;
            }
            QComboBox:hover {
                border-color: #2563eb;
                background: #f8fafc;
            }
            QComboBox:focus {
                border-color: #2563eb;
                border-width: 1.5px;
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
                subcontrol-position: right center;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #94a3b8;
                width: 0; height: 0;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 4px 0;
                selection-background-color: #eff6ff;
                selection-color: #1d4ed8;
                font-size: 12px;
                outline: none;
            }
        """

        master_combo_style = """
            QComboBox {
                background: #f1f5f9;
                color: #374151;
                border: 1px solid #e2e8f0;
                border-radius: 5px;
                padding: 4px 28px 4px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 28px;
                min-width: 90px;
            }
            QComboBox:hover {
                border-color: #2563eb;
                background: #e8f0fe;
            }
            QComboBox::drop-down { border: none; width: 26px; }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #94a3b8;
                width: 0; height: 0;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #e2e8f0;
                padding: 4px 0;
                selection-background-color: #eff6ff;
                selection-color: #1d4ed8;
                font-size: 12px;
                outline: none;
            }
        """

        # ── Outer scroll area — light neutral canvas
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setObjectName("SecurityOuterScroll")
        outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_scroll.setStyleSheet("""
            QScrollArea#SecurityOuterScroll { background: #f1f5f9; border: none; }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1; border-radius: 3px; min-height: 28px;
            }
            QScrollBar::handle:vertical:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        outer_widget = QWidget()
        outer_widget.setObjectName("SecurityOuterWidget")
        outer_widget.setStyleSheet("#SecurityOuterWidget { background: #f1f5f9; }")
        outer_lay = QHBoxLayout(outer_widget)
        outer_lay.setContentsMargins(20, 20, 20, 20)
        outer_lay.setSpacing(16)

        for group_name, items in self.facility_groups:

            # ── Card: white surface, subtle border, no heavy drop-shadow
            card = QFrame()
            card.setObjectName("SecurityCard")
            card.setStyleSheet("""
                QFrame#SecurityCard {
                    background: #ffffff;
                    border-radius: 8px;
                    border: 1px solid #e2e8f0;
                }
            """)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(0, 0, 0, 0)
            card_lay.setSpacing(0)

            # ── Section header: light, with strong title and demoted count
            header_frame = QFrame()
            header_frame.setObjectName("SecurityCardHeader")
            header_frame.setStyleSheet("""
                QFrame#SecurityCardHeader {
                    background: #f8fafc;
                    border-radius: 8px 8px 0 0;
                    border-bottom: 1px solid #e2e8f0;
                    min-height: 48px; max-height: 48px;
                }
            """)
            hdr_inner = QHBoxLayout(header_frame)
            hdr_inner.setContentsMargins(16, 0, 12, 0)
            hdr_inner.setSpacing(8)

            # Left accent line for visual column separation
            accent = QFrame()
            accent.setFixedWidth(3)
            accent.setFixedHeight(22)
            accent.setStyleSheet(
                "background: #2563eb; border-radius: 2px;"
            )
            hdr_inner.addWidget(accent)

            # Group title — primary visual element
            hdr_title = QLabel(group_name)
            hdr_title.setStyleSheet(
                "color: #0f172a; font-size: 13px; font-weight: 700;"
            )
            hdr_inner.addWidget(hdr_title)
            hdr_inner.addStretch()

            # Item count — secondary, subtle
            count_lbl = QLabel(f"{len(items)} items")
            count_lbl.setStyleSheet(
                "color: #94a3b8; font-size: 10px; font-weight: 500;"
            )
            hdr_inner.addWidget(count_lbl)

            card_lay.addWidget(header_frame)

            # ── "Set All" master row — distinct from content rows
            master_wrap = QFrame()
            master_wrap.setObjectName("SecurityMasterWrap")
            master_wrap.setStyleSheet("""
                QFrame#SecurityMasterWrap {
                    background: #f1f5f9;
                    border-bottom: 1px solid #e2e8f0;
                }
            """)
            master_inner = QHBoxLayout(master_wrap)
            master_inner.setContentsMargins(16, 8, 12, 8)
            master_inner.setSpacing(8)

            set_all_lbl = QLabel("Set all to")
            set_all_lbl.setStyleSheet(
                "color: #64748b; font-size: 11px; font-weight: 500;"
            )
            master_inner.addWidget(set_all_lbl)
            master_inner.addStretch()

            master_cb = NoScrollComboBox()
            master_cb.addItem("— Mixed", "mixed")
            master_cb.addItem("None",    "none")
            master_cb.addItem("Display", "display")
            master_cb.addItem("Full",    "full")
            master_cb.setStyleSheet(master_combo_style)
            master_cb.setCursor(Qt.CursorShape.PointingHandCursor)
            master_inner.addWidget(master_cb)
            card_lay.addWidget(master_wrap)

            self.master_combos[group_name] = master_cb
            fac_names_in_group = [fac_name for fac_name, _, _ in items]
            self.group_facility_names[group_name] = fac_names_in_group

            master_cb.currentIndexChanged.connect(
                lambda idx, gn=group_name: self._on_master_changed(gn, idx)
            )

            # ── Permission rows
            rows_widget = QWidget()
            rows_widget.setObjectName("SecurityRowsWidget")
            rows_widget.setStyleSheet(
                "QWidget#SecurityRowsWidget { background: #ffffff; }"
            )
            rows_lay = QVBoxLayout(rows_widget)
            rows_lay.setContentsMargins(0, 4, 0, 8)
            rows_lay.setSpacing(0)

            for idx_item, (fac_name, view_keys, edit_keys) in enumerate(items):
                is_sub = fac_name.startswith(" ↳")
                display_name = fac_name.strip()

                row = QFrame()
                row.setObjectName("SecurityPermRow")
                # Alternating rows inside the white card
                row_bg = "#f8fafc" if idx_item % 2 == 0 else "#ffffff"
                row.setStyleSheet(f"""
                    QFrame#SecurityPermRow {{
                        background: {row_bg};
                        border-bottom: 1px solid #f1f5f9;
                    }}
                    QFrame#SecurityPermRow:hover {{
                        background: #eff6ff;
                    }}
                """)

                row_inner = QHBoxLayout(row)
                # Sub-rows get extra indentation
                left_pad = 28 if is_sub else 16
                row_inner.setContentsMargins(left_pad, 7, 12, 7)
                row_inner.setSpacing(8)

                # Sub-item indent indicator
                if is_sub:
                    pipe = QLabel("┊")
                    pipe.setStyleSheet(
                        "color: #cbd5e1; font-size: 14px; font-weight: 300;"
                    )
                    pipe.setFixedWidth(8)
                    row_inner.addWidget(pipe)

                # Permission label — clear hierarchy between parent and sub
                name_lbl = QLabel(display_name)
                if is_sub:
                    name_lbl.setStyleSheet(
                        "color: #64748b; font-size: 11.5px; font-weight: 400;"
                    )
                else:
                    name_lbl.setStyleSheet(
                        "color: #1e293b; font-size: 12px; font-weight: 600;"
                    )
                row_inner.addWidget(name_lbl)
                row_inner.addStretch()

                # Permission dropdown — consistent background with row
                combo = NoScrollComboBox()
                combo.addItem("None",    "none")
                if view_keys:
                    combo.addItem("Display", "display")
                if edit_keys:
                    combo.addItem("Full",    "full")
                combo.setCursor(Qt.CursorShape.PointingHandCursor)
                # Use same bg as row so there's no background clash
                row_combo_style = combo_style.replace(
                    "background: #ffffff;",
                    f"background: {row_bg};"
                )
                combo.setStyleSheet(row_combo_style)
                combo.setObjectName("SecurityPermCombo")

                combo.currentIndexChanged.connect(
                    lambda idx, gn=group_name: self._update_master_state(gn)
                )
                combo.currentIndexChanged.connect(
                    lambda idx: self._auto_save()
                )
                if fac_name == "Full Catalog (Tab)":
                    combo.currentIndexChanged.connect(self._on_catalog_tab_changed)

                self.facility_combos[fac_name] = combo
                row_inner.addWidget(combo)
                rows_lay.addWidget(row)

            rows_lay.addStretch()
            card_lay.addWidget(rows_widget, 1)
            outer_lay.addWidget(card, 1)

        outer_scroll.setWidget(outer_widget)
        parent_layout.addWidget(outer_scroll, 1)


    def _on_master_changed(self, group_name, index):
        """When 'Set All' master dropdown changes, cascade to all child rows then auto-save.

        Rules:
          None    → all children set to None (hard cascade — always works)
          Display → each child gets 'display' if available, else 'none'
          Full    → each child gets 'full' if available, else 'display', else 'none'
        """
        master_cb = self.master_combos.get(group_name)
        if not master_cb:
            return
        level = master_cb.currentData()
        if level == "mixed":
            return  # read-only state — not a user action

        fac_names = self.group_facility_names.get(group_name, [])
        for fac_name in fac_names:
            combo = self.facility_combos.get(fac_name)
            if not combo:
                continue
            combo.blockSignals(True)
            if level == "none":
                # Hard cascade: always available on every row
                target = combo.findData("none")
            elif level == "display":
                # Best available: display → none
                target = combo.findData("display")
                if target < 0:
                    target = combo.findData("none")
            else:  # "full"
                # Best available: full → display → none
                target = combo.findData("full")
                if target < 0:
                    target = combo.findData("display")
                if target < 0:
                    target = combo.findData("none")
            if target >= 0:
                combo.setCurrentIndex(target)
            combo.blockSignals(False)

        self._auto_save()


    def _on_catalog_tab_changed(self, index):
        """If Full Catalog (Tab) is set to None, cascade to sub-items."""
        tab_combo = self.facility_combos.get("Full Catalog (Tab)")
        if not tab_combo or tab_combo.currentData() != "none":
            return
        sub_items = [" \u21b3 Build Button", " \u21b3 Auto Build",
                     " \u21b3 Print / Export", " \u21b3 Reshuffle", " \u21b3 Page Manage"]
        for sub in sub_items:
            combo = self.facility_combos.get(sub)
            if combo:
                idx = combo.findData("none")
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)

    def _update_master_state(self, group_name):
        """Reflect current sub-row states back onto the 'Set All' master dropdown."""
        master_cb = self.master_combos.get(group_name)
        if not master_cb:
            return
        fac_names = self.group_facility_names.get(group_name, [])

        levels = set()
        for fac_name in fac_names:
            combo = self.facility_combos.get(fac_name)
            if combo:
                levels.add(combo.currentData())

        master_cb.blockSignals(True)
        if len(levels) == 1:
            idx = master_cb.findData(levels.pop())
            master_cb.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            master_cb.setCurrentIndex(0)  # — Mixed
        master_cb.blockSignals(False)


    def _flat_facilities(self):
        """Flatten grouped facilities into a single list for iteration."""
        flat = []
        for _, items in self.facility_groups:
            flat.extend(items)
        return flat

    def refresh_data(self):
        """Called when navigating to this page to refresh context."""
        if not self.mw: return
        self.company_name = getattr(self.mw, 'current_company', "")
        self.company_path = getattr(self.mw, 'current_company_path', "")

        from src.logic.security_manager import SecurityManager
        data_path = os.path.dirname(self.company_path) if self.company_path else ""
        try:
            self.security = SecurityManager(data_path)
        except Exception:
            self.security = None

        # Update subtitle label
        if hasattr(self, '_sub_lbl'):
            self._sub_lbl.setText(self.company_name or "No company loaded")

        self._load_roles()

    def _go_back(self):
        if self.mw and hasattr(self.mw, "go_back_to_main"):
            self.mw.go_back_to_main()

    def _get_company_id(self):
        if not self.security:
            return None
        return self.security.get_company_id_by_path(self.company_path)

    def _load_roles(self):
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        cid = self._get_company_id()
        if cid and self.security:
            self.roles = self.security.get_roles_for_company(cid)
            for r in self.roles:
                sfx = " (system)" if r["is_system"] else ""
                self.role_combo.addItem(f"{r['role_name']}{sfx}", r["id"])
        self.role_combo.blockSignals(False)
        if self.role_combo.count() > 0:
            self._on_role_selected()

    def _on_role_selected(self):
        rid = self.role_combo.currentData()
        if not rid:
            return
        info = next((r for r in self.roles if r["id"] == rid), None)
        if info:
            self.btn_del.setEnabled(not info.get("is_system", False))
        perms = self.security.get_role_permissions(rid)
        
        for fac_name, view_keys, edit_keys in self._flat_facilities():
            sel = self.facility_combos.get(fac_name)
            if not sel: continue

            has_view = any(k in perms for k in view_keys) if view_keys else False
            has_edit = any(k in perms for k in edit_keys) if edit_keys else False

            if not view_keys:
                value = "full" if has_edit else "none"
            else:
                if has_edit and has_view:
                    value = "full"
                elif has_view:
                    value = "display"
                else:
                    value = "none"

            idx = sel.findData(value)
            if idx >= 0:
                sel.blockSignals(True)
                sel.setCurrentIndex(idx)
                sel.blockSignals(False)

        for group_name in self.master_combos:
            self._update_master_state(group_name)


    def _save_role(self):
        """Direct save — also used as the auto-save backend."""
        rid = self.role_combo.currentData()
        if not rid or not self.security:
            return False
        selected = []
        for fac_name, view_keys, edit_keys in self._flat_facilities():
            combo = self.facility_combos.get(fac_name)
            if not combo: continue
            level = combo.currentData()
            if level == "display":
                selected.extend(view_keys)
            elif level == "full":
                selected.extend(view_keys)
                selected.extend(edit_keys)
        selected = list(set(selected))
        desc = ""
        ok = self.security.update_role(rid, description=desc, permission_keys=selected)
        if ok and hasattr(self.mw, "refresh_user_permissions"):
            self.mw.refresh_user_permissions()
        return ok

    # ── Auto-save machinery ─────────────────────────────────────────────────

    def _auto_save(self):
        """Schedule a save 300 ms after the last change (debounced)."""
        self._save_timer.stop()
        self._set_save_status("saving")
        self._save_timer.start(300)

    def _do_auto_save(self):
        """Execute the actual save and update the status indicator."""
        ok = self._save_role()
        self._set_save_status("saved" if ok else "error")

    def _set_save_status(self, state: str):
        """Update the inline status label in the role bar."""
        self._clear_timer.stop()
        if state == "saving":
            self._status_lbl.setText("Saving\u2026")
            self._status_lbl.setStyleSheet(
                "color: #94a3b8; font-size: 11px;"
            )
        elif state == "saved":
            self._status_lbl.setText("\u2713 Saved just now")
            self._status_lbl.setStyleSheet(
                "color: #16a34a; font-size: 11px; font-weight: 500;"
            )
            self._clear_timer.start(2500)
        elif state == "error":
            self._status_lbl.setText("\u2715 Failed to save")
            self._status_lbl.setStyleSheet(
                "color: #dc2626; font-size: 11px; font-weight: 500;"
            )
            self._clear_timer.start(4000)

    def _clear_status(self):
        self._status_lbl.setText("")



    def _create_role(self):
        name, ok = QInputDialog.getText(self, "New Role", "Role name:")
        if ok and name.strip():
            cid = self._get_company_id()
            if cid:
                rid = self.security.create_role(cid, name.strip(), "", [])
                if rid:
                    self._load_roles()
                    for i in range(self.role_combo.count()):
                        if self.role_combo.itemData(i) == rid:
                            self.role_combo.setCurrentIndex(i)
                            break
                else:
                    QMessageBox.warning(self, "Error", f"Role '{name}' already exists.")

    def _delete_role(self):
        rid = self.role_combo.currentData()
        rname = self.role_combo.currentText()
        if not rid or not self.security:
            return

        # Check which active users are assigned to this role
        affected = self.security.get_users_assigned_to_role(rid)

        if affected:
            user_list = "\n".join(f"  • {u}" for u in affected)
            msg = (
                f"The role '{rname}' is currently assigned to "
                f"{len(affected)} user(s):\n\n"
                f"{user_list}\n\n"
                f"Deleting this role will remove all their permissions immediately.\n"
                f"They will lose access to all tabs until a new role is assigned.\n\n"
                f"Are you sure you want to delete '{rname}'?"
            )
            btn = QMessageBox.warning(
                self, "Delete Role — Users Affected",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,   # default to No (safer)
            )
        else:
            btn = QMessageBox.question(
                self, "Delete Role",
                f"Delete '{rname}'? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

        if btn == QMessageBox.StandardButton.Yes:
            if self.security.delete_role(rid):
                self._load_roles()
            else:
                QMessageBox.warning(self, "Error", "Cannot delete system roles.")


# --- Audit Log Viewer ---
class AuditLogDialog(QDialog):
    """View login history, failed attempts, and user actions."""
    def __init__(self, company_name="", company_path="", security_mgr=None, parent=None):
        super().__init__(parent)
        self.company_name = company_name
        self.company_path = company_path
        
        if security_mgr:
            self.security = security_mgr
        else:
            from src.logic.security_manager import SecurityManager
            try:
                self.security = SecurityManager(os.path.dirname(company_path) if company_path else "")
            except Exception:
                self.security = None
        
        self.setWindowTitle(f"Audit Log — {company_name}")
        self.setFixedSize(850, 500)
        
        layout = QVBoxLayout(self)
        title = QLabel(f"<h3>Audit Log — {company_name}</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "login", "failed_login", "logout", "role_change", "user_created"])
        self.filter_combo.currentTextChanged.connect(self._load_log)
        filter_bar.addWidget(self.filter_combo)
        
        self.filter_user = QLineEdit()
        self.filter_user.setPlaceholderText("Username...")
        self.filter_user.setFixedWidth(120)
        self.filter_user.textChanged.connect(self._load_log)
        filter_bar.addWidget(self.filter_user)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_log)
        filter_bar.addWidget(refresh_btn)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)
        
        # Log table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Time", "User", "Action", "Module", "Detail"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 80)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self._load_log()

    def _get_company_id(self):
        if not self.security:
            return None
        return self.security.get_company_id_by_path(self.company_path)

    def _load_log(self):
        if not self.security:
            return
        cid = self._get_company_id()
        if not cid:
            return
        
        from src.logic.db_manager import build_shared_db_name, DB_SECURITY
        data_path = os.path.dirname(self.company_path) if self.company_path else ""
        sec_db = build_shared_db_name(DB_SECURITY, data_path) if data_path else DB_SECURITY
        conn = self.security.db.get_connection(sec_db)
        if not conn:
            return
        try:
            cursor = conn.cursor()
            query = "SELECT TOP 200 timestamp, username, action, module, detail FROM audit_log WHERE company_id = ?"
            params = [cid]
            
            action_filter = self.filter_combo.currentText()
            if action_filter != "All":
                query += " AND action = ?"
                params.append(action_filter)
            
            user_filter = self.filter_user.text().strip()
            if user_filter:
                query += " AND username LIKE ?"
                params.append(f"%{user_filter}%")
            
            query += " ORDER BY timestamp DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                ts = str(r[0])[:19] if r[0] else ""
                self.table.setItem(i, 0, QTableWidgetItem(ts))
                self.table.setItem(i, 1, QTableWidgetItem(r[1] or ""))
                
                action_item = QTableWidgetItem(r[2] or "")
                # Color-code actions
                if r[2] == "failed_login":
                    action_item.setForeground(Qt.GlobalColor.red)
                elif r[2] == "login":
                    action_item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(i, 2, action_item)
                
                self.table.setItem(i, 3, QTableWidgetItem(r[3] or ""))
                self.table.setItem(i, 4, QTableWidgetItem(r[4] or ""))
        except Exception as e:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem(f"Error: {e}"))


# --- Change Password Dialog (self-service) ---
class ChangePasswordDialog(QDialog):
    """Admin-only dialog to change a user's password."""
    def __init__(self, user_session=None, security_mgr=None, parent=None):
        super().__init__(parent)
        self.user_session = user_session
        self.security = security_mgr
        
        self.setWindowTitle("Change Password")
        self.setFixedSize(400, 280)
        
        layout = QVBoxLayout(self)
        title = QLabel(f"<h3>Change Password</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Admin-only gate: block non-admin users immediately
        if user_session and not user_session.is_admin:
            denied_lbl = QLabel("Only administrators can change passwords.")
            denied_lbl.setObjectName("DeniedLabel")
            denied_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            denied_lbl.setWordWrap(True)
            layout.addWidget(denied_lbl)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return  # Don't build the rest of the form
        
        if user_session:
            layout.addWidget(QLabel(f"User: <b>{user_session.username or '(admin)'}</b>"))
        
        form = QGridLayout()
        form.addWidget(QLabel("Current Password:"), 0, 0)
        self.current_pw = QLineEdit()
        self.current_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self.current_pw, 0, 1)
        
        form.addWidget(QLabel("New Password:"), 1, 0)
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self.new_pw, 1, 1)
        
        form.addWidget(QLabel("Confirm Password:"), 2, 0)
        self.confirm_pw = QLineEdit()
        self.confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self.confirm_pw, 2, 1)
        layout.addLayout(form)
        
        self.error_lbl = QLabel("")
        self.error_lbl.setObjectName("SettingsErrorLabel")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.error_lbl)
        
        btn_bar = QHBoxLayout()
        save_btn = QPushButton("Change Password")
        save_btn.clicked.connect(self._save)
        btn_bar.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)
        layout.addLayout(btn_bar)

    def _save(self):
        if not self.user_session or not self.security:
            self.error_lbl.setText("Session error.")
            return
        
        current = self.current_pw.text()
        new = self.new_pw.text()
        confirm = self.confirm_pw.text()
        
        if new != confirm:
            self.error_lbl.setText("New passwords don't match.")
            return
        
        # Verify current password
        session = self.security.verify_login(
            self.user_session.company_path,
            self.user_session.username,
            current,
            company_name=self.user_session.company_name
        )
        if not session:
            self.error_lbl.setText("Current password is wrong.")
            return
        
        # Update password
        if self.security.update_user(self.user_session.user_id, password=new):
            QMessageBox.information(self, "Success", "Password changed successfully!")
            self.accept()
        else:
            self.error_lbl.setText("Failed to update password.")



