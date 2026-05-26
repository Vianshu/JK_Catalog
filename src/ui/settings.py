import json
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QMessageBox,
    QWidget, QFrame, QInputDialog, QScrollArea, QCheckBox, QGridLayout, QGroupBox
)
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
        title = QLabel(f"<h3>👤 Users — {company_name}</h3>")
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
        add_btn = QPushButton("➕ Add")
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
            name_item = QTableWidgetItem(f"{'👑 ' if u['is_admin'] else ''}{u['username'] or '(empty)'}")
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
                role_combo.currentIndexChanged.connect(
                    lambda _, uid=uid, cb=role_combo: self._update_user_role(uid, cb.currentData()))
            self.table.setCellWidget(i, 1, role_combo)
            
            active_item = QTableWidgetItem("✅" if u["is_active"] else "❌")
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
                
                rb = QPushButton("🔑 Reset")
                rb.setToolTip("Reset Password")
                rb.setFixedHeight(28)
                rb.setObjectName("BtnResetPw")
                rb.clicked.connect(lambda _, uid=uid, un=uname: self._reset_pw(uid, un))
                al.addWidget(rb)
                
                tb = QPushButton("🚫 Disable" if is_active else "✅ Enable")
                tb.setToolTip("Deactivate" if is_active else "Activate")
                tb.setFixedHeight(28)
                if is_active:
                    tb.setObjectName("BtnDisableUser")
                else:
                    tb.setObjectName("BtnEnableUser")
                tb.clicked.connect(lambda _, uid=uid, a=is_active: self._toggle(uid, a))
                al.addWidget(tb)
                
                db = QPushButton("🗑 Delete")
                db.setToolTip("Delete User")
                db.setFixedHeight(28)
                db.setObjectName("BtnDeleteUser")
                db.clicked.connect(lambda _, uid=uid, un=uname: self._del(uid, un))
                al.addWidget(db)
                self.table.setCellWidget(i, 4, action_w)

    def _reset_pw(self, uid, uname):
        pw, ok = QInputDialog.getText(self, "Reset Password", f"New password for '{uname}':", QLineEdit.EchoMode.Password)
        if ok:
            self.security.update_user(uid, password=pw)
            if hasattr(self.parent(), "refresh_user_permissions"):
                self.parent().refresh_user_permissions()
            QMessageBox.information(self, "Done", f"Password reset for '{uname}'.")

    def _update_user_role(self, uid, role_id):
        self.security.update_user(uid, role_id=role_id)
        if hasattr(self.parent(), "refresh_user_permissions"):
            self.parent().refresh_user_permissions()
            
    def _toggle(self, uid, is_active):
        self.security.update_user(uid, is_active=not is_active)
        if hasattr(self.parent(), "refresh_user_permissions"):
            self.parent().refresh_user_permissions()
        self._load_users()

    def _del(self, uid, uname):
        if QMessageBox.question(self, "Delete", f"Delete '{uname}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.security.delete_user(uid)
            self._load_users()

    def _add_user(self):
        uname = self.new_user_edit.text().strip()
        pw = self.new_pass_edit.text()
        rid = self.new_role_combo.currentData()
        if not uname:
            QMessageBox.warning(self, "Error", "Username required."); return
        if self.security.add_user(self.company_path, uname, pw, rid):
            self.new_user_edit.clear(); self.new_pass_edit.clear()
            self._load_users()
        else:
            QMessageBox.warning(self, "Error", f"User '{uname}' already exists.")


# --- Role / Security Manager Dialog ---
class SecurityUI(QWidget):
    """Manage roles and permissions with a 4-column card layout (one per main tab)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = parent  # MainWindow reference
        self.company_name = getattr(parent, 'current_company', "") if parent else ""
        self.company_path = getattr(parent, 'current_company_path', "") if parent else ""
        self.roles = []
        
        self.security = None
        self.setObjectName("SecurityUI")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        
        # --- Title ---
        title = QLabel(f"<h3>🛡️ Security Roles — {self.company_name}</h3>")
        title.setObjectName("SecurityTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # --- Role Selector Bar ---
        details_frame = QFrame()
        details_frame.setObjectName("SecurityDetailsFrame")
        details_layout = QHBoxLayout(details_frame)
        details_layout.setContentsMargins(12, 8, 12, 8)
        
        details_layout.addWidget(QLabel("Security Level:"))
        
        self.role_combo = QComboBox()
        self.role_combo.setMinimumWidth(200)
        self.role_combo.currentIndexChanged.connect(self._on_role_selected)
        details_layout.addWidget(self.role_combo)
        
        self.btn_new = QPushButton("➕ New")
        self.btn_new.setObjectName("SecurityNewBtn")
        self.btn_new.clicked.connect(self._create_role)
        details_layout.addWidget(self.btn_new)
        
        self.btn_del = QPushButton("🗑 Delete")
        self.btn_del.setObjectName("SecurityDelBtn")
        self.btn_del.clicked.connect(self._delete_role)
        details_layout.addWidget(self.btn_del)
        
        details_layout.addStretch()
        layout.addWidget(details_frame)
        
        # --- Facility Groups (data — unchanged) ---
        self.facility_combos = {}
        self.facility_groups = [
            ("📁 Catalog", [
                ("Sync Tally",          ["tab.final_data"],     ["final_data.sync"]),
                ("Super Master",        ["tab.super_master"],   ["super_master.edit"]),
                ("Final Data",          ["tab.final_data"],     ["final_data.edit", "final_data.export"]),
                ("Full Catalog",        ["tab.catalog"],        ["catalog.build", "catalog.print", "catalog.edit_assignment"]),
                ("Reports",             ["tab.reports"],        ["reports.print", "reports.mark_done"]),
                ("Catalog Price List",  ["tab.cat_price_list"], []),
            ]),
            ("📊 Vat Working", [
                ("Vat Balance",         ["tab.vat_balance"],    []),
                ("Vat Stock",           ["tab.vat_stock"],      []),
            ]),
            ("⚙️ Tally Internal", [
                ("Sync Ledger",         ["tab.ledger"],         ["ledger.sync"]),
                ("Ledger Rows",         ["tab.ledger"],         []),
                ("Row Data",            ["tab.row_data"],       []),
                ("On Account",          ["tab.payment_list"],   []),
                ("Cheque List",         ["tab.cheque_list"],    ["cheque_list.edit"]),
                ("Godown List",         ["tab.godown"],         []),
                ("Sales Chat",          ["tab.sales_chat"],     []),
                ("Supplier Payment",    ["tab.supp_payment"],   []),
                ("Price List",          ["tab.price_list"],     []),
                ("Purchase Import",     ["tab.pur_import"],     []),
                ("Internal Cost Sheet", ["tab.int_cost_sheet"], []),
                ("For Branch",          ["tab.for_branch"],     []),
            ]),
            ("⚙️ Settings", [
                ("Calendar",            ["tab.calendar"],       ["calendar.edit"]),
                ("Admin / Users",       [],                     ["settings.manage_users", "settings.manage_roles",
                                                                 "settings.manage_crm", "settings.company_config",
                                                                 "settings.change_path"]),
            ]),
        ]
        
        # --- 4-Column Card Layout ---
        self._build_perm_grid(layout)
        
        # --- Bottom Button Bar ---
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        save_btn = QPushButton("💾 Save Permissions")
        save_btn.setObjectName("PrimaryActionButton")
        save_btn.clicked.connect(self._save_role)
        btn_bar.addWidget(save_btn)
        close_btn = QPushButton("Cancel")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self._go_back)
        btn_bar.addWidget(close_btn)
        layout.addLayout(btn_bar)
        
        self._load_roles()

    def _build_perm_grid(self, parent_layout):
        """Build 4-column card layout — one column per main tab.
        Each column has a master selector that sets all sub-facilities at once."""
        from PyQt6.QtWidgets import QScrollArea
        
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(10)
        
        # Track master combos per group for bulk set
        self.master_combos = {}  # group_name → QComboBox
        self.group_facility_names = {}  # group_name → [fac_name, ...]
        
        for group_name, items in self.facility_groups:
            # --- Column Card Frame ---
            card = QFrame()
            card.setObjectName("SecurityColumn")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            
            # Header
            header = QLabel(group_name)
            header.setObjectName("SecurityColumnHeader")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(header)
            
            # ── Master Selector ──
            master_frame = QFrame()
            master_frame.setObjectName("SecurityMasterRow")
            master_frame.setStyleSheet("""
                #SecurityMasterRow {
                    background: #e8f0fe; border: 1px solid #c0d0e8;
                    border-radius: 4px; margin: 4px 6px;
                }
            """)
            master_lay = QHBoxLayout(master_frame)
            master_lay.setContentsMargins(8, 4, 8, 4)
            master_lay.setSpacing(6)
            master_lbl = QLabel("🔒 Set All:")
            master_lbl.setStyleSheet("font-weight: 600; font-size: 11px;")
            master_lay.addWidget(master_lbl)
            
            master_combo = QComboBox()
            master_combo.addItem("—", "mixed")
            master_combo.addItem("None", "none")
            master_combo.addItem("Display", "display")
            master_combo.addItem("Full Access", "full")
            master_combo.setObjectName("SecurityMasterCombo")
            master_combo.setStyleSheet("font-weight: 600;")
            master_lay.addWidget(master_combo, 1)
            card_layout.addWidget(master_frame)
            
            self.master_combos[group_name] = master_combo
            fac_names_in_group = [fac_name for fac_name, _, _ in items]
            self.group_facility_names[group_name] = fac_names_in_group
            
            # Connect master combo — use closure to capture group_name
            master_combo.currentIndexChanged.connect(
                lambda idx, gn=group_name: self._on_master_changed(gn, idx)
            )
            
            # Scrollable content area for permission rows
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName("SecurityColumnScroll")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(10, 8, 10, 8)
            content_layout.setSpacing(6)
            
            for fac_name, view_keys, edit_keys in items:
                row_frame = QFrame()
                row_frame.setObjectName("SecurityPermRow")
                row_layout = QVBoxLayout(row_frame)
                row_layout.setContentsMargins(8, 6, 8, 6)
                row_layout.setSpacing(4)
                
                lbl = QLabel(fac_name)
                lbl.setObjectName("SecurityPermLabel")
                row_layout.addWidget(lbl)
                
                combo = QComboBox()
                combo.addItem("None", "none")
                if view_keys:
                    combo.addItem("Display", "display")
                if edit_keys:
                    combo.addItem("Full Access", "full")
                combo.setObjectName("SecurityPermCombo")
                row_layout.addWidget(combo)
                
                # When sub-combo changes, update the master combo state
                combo.currentIndexChanged.connect(
                    lambda idx, gn=group_name: self._update_master_state(gn)
                )
                
                self.facility_combos[fac_name] = combo
                content_layout.addWidget(row_frame)
            
            content_layout.addStretch()
            scroll.setWidget(content)
            card_layout.addWidget(scroll, 1)
            
            columns_layout.addWidget(card, 1)
        
        parent_layout.addLayout(columns_layout, 1)

    def _on_master_changed(self, group_name, index):
        """When master combo changes, set all sub-combos in this group."""
        master_combo = self.master_combos.get(group_name)
        if not master_combo:
            return
        level = master_combo.currentData()
        if level == "mixed":
            return  # '—' is just a display state, not a user action
        
        fac_names = self.group_facility_names.get(group_name, [])
        for fac_name in fac_names:
            combo = self.facility_combos.get(fac_name)
            if not combo:
                continue
            idx = combo.findData(level)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
            elif level == "full":
                # Some combos don't have "Full Access" — set to highest available
                best = combo.count() - 1
                combo.blockSignals(True)
                combo.setCurrentIndex(best)
                combo.blockSignals(False)
            elif level == "display":
                # Some combos don't have "Display" — set to None
                idx_none = combo.findData("none")
                if idx_none >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx_none)
                    combo.blockSignals(False)

    def _update_master_state(self, group_name):
        """Update the master combo to reflect current sub-combo states.
        Shows '—' (mixed) if sub-combos differ, otherwise shows the common value."""
        master_combo = self.master_combos.get(group_name)
        if not master_combo:
            return
        fac_names = self.group_facility_names.get(group_name, [])
        
        levels = set()
        for fac_name in fac_names:
            combo = self.facility_combos.get(fac_name)
            if combo:
                levels.add(combo.currentData())
        
        master_combo.blockSignals(True)
        if len(levels) == 1:
            common = levels.pop()
            idx = master_combo.findData(common)
            if idx >= 0:
                master_combo.setCurrentIndex(idx)
            else:
                master_combo.setCurrentIndex(0)  # '—'
        else:
            master_combo.setCurrentIndex(0)  # '—' (mixed)
        master_combo.blockSignals(False)

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
            
        # Update title
        title_lbl = self.findChild(QLabel, "SecurityTitle")
        if title_lbl:
            title_lbl.setText(f"<h3>🛡️ Security Roles — {self.company_name}</h3>")
            
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
            combo = self.facility_combos.get(fac_name)
            if not combo: continue
            
            combo.blockSignals(True)
            # Determine state based on keys
            has_view = any(k in perms for k in view_keys) if view_keys else False
            has_edit = any(k in perms for k in edit_keys) if edit_keys else False
            
            # Edge case for Settings / Admin (no view keys)
            if not view_keys:
                if has_edit:
                    idx = combo.findData("full")
                else:
                    idx = combo.findData("none")
            else:
                if has_edit and has_view:
                    idx = combo.findData("full")
                elif has_view:
                    idx = combo.findData("display")
                else:
                    idx = combo.findData("none")
                    
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        
        # Update all master combos to reflect loaded state
        for group_name in self.master_combos:
            self._update_master_state(group_name)

    def _save_role(self):
        rid = self.role_combo.currentData()
        if not rid:
            return
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
                
        # Remove duplicates
        selected = list(set(selected))
        
        desc = "" # Description removed from UI
        if self.security.update_role(rid, description=desc, permission_keys=selected):
            if hasattr(self.mw, "refresh_user_permissions"):
                self.mw.refresh_user_permissions()
            QMessageBox.information(self, "Saved", f"Updated with {len(selected)} permissions.")
        else:
            QMessageBox.warning(self, "Error", "Save failed.")

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
        if rid and QMessageBox.question(self, "Delete", f"Delete '{rname}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
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
        title = QLabel(f"<h3>📋 Audit Log — {company_name}</h3>")
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
        
        refresh_btn = QPushButton("🔄 Refresh")
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
        
        conn = self.security.db.get_connection('JK_Security')
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
        title = QLabel(f"<h3>🔑 Change Password</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Admin-only gate: block non-admin users immediately
        if user_session and not user_session.is_admin:
            denied_lbl = QLabel("🔒 Only administrators can change passwords.")
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
        save_btn = QPushButton("💾 Change Password")
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
            self.error_lbl.setText("❌ New passwords don't match.")
            return
        
        # Verify current password
        session = self.security.verify_login(
            self.user_session.company_path,
            self.user_session.username,
            current,
            company_name=self.user_session.company_name
        )
        if not session:
            self.error_lbl.setText("❌ Current password is wrong.")
            return
        
        # Update password
        if self.security.update_user(self.user_session.user_id, password=new):
            QMessageBox.information(self, "Success", "Password changed successfully!")
            self.accept()
        else:
            self.error_lbl.setText("❌ Failed to update password.")



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
    return build_logical_name(company_name, company_path=company_path)

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