import json
import os
import sys
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QFrame, QStackedWidget, QMenu, QMessageBox, QProgressDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
import sqlite3
import pandas as pd
# UI Imports
from src.ui.company_login_ui import CompanyLoginUI
from src.ui.welcome import WelcomeUI
from src.ui.full_catalog import FullCatalogUI
from src.ui.row_data import RowDataUI
from src.ui.final_data import FinalDataUI
from src.ui.reports import ReportsUI
from src.ui.payment_list import PaymentListUI
from src.ui.price_list import PriceListUI
from src.ui.godown_list import GodownListUI
from src.ui.sales_chat import SalesChatUI
from src.ui.supp_payment import SuppPaymentUI
from src.ui.vat_pages import BalanceUI, StockUI
from src.ui.super_master import SuperMasterUI
from src.ui.pur_import import PurImportUI
from src.ui.int_cost_sheet import IntCostSheetUI
from src.ui.catalog_price_list import CatalogPriceListUI
from src.ui.cheque_list import ChequeListUI
from src.ui.calendar_mapping import CalendarMappingUI
from src.utils.path_utils import get_writable_data_path

# Settings & Services
# Settings & Services
from src.ui.settings import (
    CRMDialog, UserManagerDialog, SecurityDialog,
    save_users_to_json, load_crm_list, save_crm_to_json, update_crm_in_json
)
from src.services.tally_sync import fetch_tally_data

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        self.current_company = ""
        self.is_maximized = True
        self.current_active_btn = None
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_min_max)
        self.setup_ui()
    
    def toggle_min_max(self):
        if self.isMinimized():
            self.showMaximized()
        else:
            self.showMinimized()
    
    def setup_ui(self):
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # ========== LEFT SIDEBAR ==========
        self.sidebar = QFrame()
        self.sidebar.setObjectName("MainSidebar")
        self.sidebar.setFixedWidth(220)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 10)
        sidebar_layout.setSpacing(0)

        # Company Display Button
        self.company_btn = QPushButton("🏢 Select Company ▼")
        self.company_btn.setObjectName("CompanyDisplayBtn")
        self.company_btn.clicked.connect(self.show_company_dropdown)
        self.company_btn.hide()
        sidebar_layout.addWidget(self.company_btn)

        # Menu Navigation Stack
        self.nav_stack = QStackedWidget()
        self.nav_stack.setObjectName("NavStack")
        
        # 0: Empty, 1: Main, 2: Catalog, 3: Settings, 4: Tally, 5: Vat, 6: Branch
        self.init_nav_menus()
        
        sidebar_layout.addWidget(self.nav_stack)
        sidebar_layout.addStretch()

        # Quit Hint
        # Quit Hint
        quit_lbl = QLabel("Press Ctrl+Q to Quit")
        quit_lbl.setObjectName("QuitHint")
        sidebar_layout.addWidget(quit_lbl)

        # Logout Button (User Request)
        self.logout_btn = QPushButton("🚪 LOGOUT")
        self.logout_btn.setObjectName("MenuButton") # Use standard style base
        # Override specific colors for logout
        self.logout_btn.setStyleSheet("""
            background-color: #c0392b; 
            color: white; 
            font-weight: bold; 
            margin-top: 10px;
        """)
        self.logout_btn.clicked.connect(self.back_to_login_screen)
        sidebar_layout.addWidget(self.logout_btn)

        self.root_layout.addWidget(self.sidebar)

        # ========== RIGHT CONTENT AREA ==========
        self.content_container = QFrame()
        self.content_container.setObjectName("ContentArea")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        self.main_stack = QStackedWidget()
        self.init_main_pages()
        
        self.content_layout.addWidget(self.main_stack)
        self.root_layout.addWidget(self.content_container, 1)

    def init_nav_menus(self):
        """सभी लेफ्ट मेनू लेआउट्स को यहाँ डिफाइन किया गया है"""
        # Index 0: Blank (Login Screen ke liye)
        self.nav_stack.addWidget(QWidget())

        # Index 1: Main Menu
        m_main = self.create_menu_widget([
            ("📁 Catalog", self.show_catalog_submenu),
            ("📊 Vat Working", self.show_vat_submenu),
            ("⚙️ Tally Internal", self.show_tally_internal_submenu),
            ("⚙️ Settings", self.show_settings_submenu)
        ], enable_hotkeys=True)
        self.nav_stack.addWidget(m_main)

        # Index 2: Catalog Menu
        m_catalog = self.create_menu_widget([
            ("⬅️ Back", self.go_back_to_main, True),
            ("🔄 Sync Tally", self.on_sync_tally_clicked),
            ("📝 Row Data", self.on_row_data_clicked),
            ("📑 Super Master", self.handle_super_master),
            ("✅ Final Data", self.final_data),
            ("📖 Full Catalog", lambda: self.main_stack.setCurrentIndex(2)),
            ("📈 Reports", lambda: self.main_stack.setCurrentIndex(7)),
            ("🏷 Price List", self.handle_catalog_price_list),
            ("➕ Create CRM", self.handle_create_crm, False, "F1"),
            ("✏️ Alter CRM", self.handle_alter_crm, False, "F2")
        ])
        self.nav_stack.addWidget(m_catalog)

        # Index 3: Settings Menu
        m_settings = self.create_menu_widget([
            ("⬅️ Back", self.go_back_to_main, True),
            ("🏢 Alter Company", self.handle_alter_company),
            ("🔄 Switch Co.", self.back_to_login_screen),
            ("👤 Create User", self.handle_create_user),
            ("✏️ Alter User", self.handle_alter_user),
            ("🛡️ Security", self.handle_security),
            ("📅 Calendar", self.handle_calendar_mapping)
        ]) # Bracket yahan band hoga
        self.nav_stack.addWidget(m_settings)

        # Index 4: Tally Internal
        m_tally = self.create_menu_widget([
            ("⬅️ Back", self.go_back_to_main, True),
            ("💰 On Account", lambda: self.main_stack.setCurrentIndex(9)),
            ("🧾 Chq. list", self.handle_cheque_list),
            ("🏠 Godown List", lambda: self.main_stack.setCurrentIndex(10)),
            ("📈 Sales Chat", lambda: self.main_stack.setCurrentIndex(11)),
            ("💸 Supp. Payment", lambda: self.main_stack.setCurrentIndex(12)),
            ("🏷 Price List", lambda: self.main_stack.setCurrentIndex(8)),
            ("📥 Pur Import", self.handle_pur_import),
            ("📊 Cost Sheet", self.handle_int_cost_sheet),
            ("🏢 For Branch", self.show_branch_submenu)
        ])
        self.nav_stack.addWidget(m_tally)

        # Index 5: Vat Working
        m_vat = self.create_menu_widget([
            ("⬅️ Back", self.go_back_to_main, True),
            ("💰 Balance", lambda: self.main_stack.setCurrentIndex(13)),
            ("📦 Stock", lambda: self.main_stack.setCurrentIndex(14))
        ])
        self.nav_stack.addWidget(m_vat)

        # Index 6: Branch Menu
        m_branch = self.create_menu_widget([
            ("⬅️ Back", self.show_tally_internal_submenu, True),
            ("📦 BTM Order", None),
            ("📦 NGT Order", None),
            ("📥 BTM Receive", None),
            ("📥 NGT Receive", None)
        ])
        self.nav_stack.addWidget(m_branch)

    def init_main_pages(self):
        """राइट साइड के सभी पेजों को लोड करना"""
        self.company_login = CompanyLoginUI()
        self.company_login.login_success_signal.connect(self.handle_login_success)
        
        self.row_data_page = RowDataUI()
        self.final_data_page = FinalDataUI()
        self.super_master_page = SuperMasterUI()
        self.reports_page = ReportsUI()
        self.payment_list_page = PaymentListUI()
        self.godown_page = GodownListUI(get_writable_data_path("Temp"))
        # Stack Pages
        self.full_catalog_page = FullCatalogUI()
        self.main_stack.addWidget(self.company_login)      # 0
        self.main_stack.addWidget(WelcomeUI())             # 1
        self.main_stack.addWidget(self.full_catalog_page)  # 2
        self.main_stack.addWidget(QLabel("Sync..."))       # 3
        self.main_stack.addWidget(self.row_data_page)      # 4
        self.main_stack.addWidget(self.final_data_page)    # 5
        self.main_stack.addWidget(self.super_master_page)  # 6
        self.main_stack.addWidget(self.reports_page)       # 7
        self.main_stack.addWidget(PriceListUI())           # 8
        self.main_stack.addWidget(QLabel("On Account"))    # 9
        self.main_stack.addWidget(self.godown_page)        # 10
        
        self.main_stack.addWidget(SalesChatUI())           # 11
        self.main_stack.addWidget(SuppPaymentUI())         # 12
        self.main_stack.addWidget(BalanceUI())             # 13
        self.main_stack.addWidget(StockUI())               # 14
        self.cheque_list_page = ChequeListUI()
        self.main_stack.addWidget(self.cheque_list_page) # Maan lijiye index 15 hai
        
        self.calendar_page = CalendarMappingUI()
        self.main_stack.addWidget(self.calendar_page) # Maan lijiye index 16 hai
    # --- Helper UI Functions ---
    # --- Helper UI Functions ---
    def create_menu_widget(self, buttons_data, enable_hotkeys=False):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 10, 5, 10)
        layout.setSpacing(10)
        
        shortcut_counter = 1
        
        for data in buttons_data:
            text = data[0]
            func = data[1]
            is_back = data[2] if len(data) > 2 else False # Check if tuple has 3rd element
            custom_key = data[3] if len(data) > 3 else None
            
            sc = None
            display_text = text

            # --- Hotkey Logic ---
            if custom_key:
                display_text = f"{text} ({custom_key})"
                sc = QShortcut(QKeySequence(custom_key), self)
            elif enable_hotkeys and not is_back:
                key_seq = f"Shift+{shortcut_counter}"
                display_text = f"{text} ({key_seq})"
                sc = QShortcut(QKeySequence(key_seq), self)
                shortcut_counter += 1

            btn = QPushButton(display_text)
            btn.setObjectName("MenuButton")
            if is_back:
                btn.setObjectName("MenuBackButton")
            
            # --- Click & Active Logic ---
            if func:
                # We wrap to ensure highlighting happens
                btn.clicked.connect(lambda checked=False, b=btn: self.set_active_menu_btn(b))
                btn.clicked.connect(func)
                
            # --- Connect Hotkey ---
            if sc:
                # Capture 'widget' (container) and 'btn'
                # Note: We must bind arguments to lambda properly
                sc.activated.connect(lambda w=widget, b=btn: self.safe_trigger_menu(w, b))

            layout.addWidget(btn)
        
        layout.addStretch()
        return widget

    def safe_trigger_menu(self, parent_widget, btn):
        """Global trigger for main menu hotkeys (Works from any tab)"""
        # User requested global access, so we removed the visibility check
        btn.animateClick()

    def set_active_menu_btn(self, btn):
        """Highlights the clicked menu button"""
        if self.current_active_btn:
            self.current_active_btn.setProperty("active", False)
            self.style().unpolish(self.current_active_btn)
            self.style().polish(self.current_active_btn)
            
        self.current_active_btn = btn
        if btn:
            btn.setProperty("active", True)
            self.style().unpolish(btn)
            self.style().polish(btn)

    def go_back_to_main(self):
        self.nav_stack.setCurrentIndex(1)
        self.main_stack.setCurrentIndex(1)

    # --- Navigation Triggers ---
    def show_catalog_submenu(self): self.nav_stack.setCurrentIndex(2)
    def show_settings_submenu(self): self.nav_stack.setCurrentIndex(3)
    def show_tally_internal_submenu(self): self.nav_stack.setCurrentIndex(4)
    def show_vat_submenu(self): self.nav_stack.setCurrentIndex(5)
    def show_branch_submenu(self): self.nav_stack.setCurrentIndex(6)

    # --- Business Logic Methods (Login, Sync, CRM etc.) ---
    def handle_login_success(self, comp_name, company_path):
        try:
            self.current_company = comp_name
            self.company_btn.setText(f"🏢 {comp_name} ▼")
            self.company_btn.show()

            if not company_path or not os.path.exists(company_path):
                print(f"Error: Path not found for company {comp_name}: {company_path}")
                QMessageBox.critical(self, "Error", f"Company path not found:\n{company_path}")
                return

            # 1. Final Data Loads
            self.final_data_page.load_and_sync_data(comp_name) 
            self.final_data_page.set_company_path(company_path)

            # 2. Super Master
            self.super_master_page.load_super_master_data(company_path) 

            # 3. Godown - UPDATE existing instance
            # Use change_data_folder instead of creating new instance
            final_df = getattr(self.final_data_page, 'final_df', None)
            self.godown_page.change_data_folder(company_path, final_df)

            # 4. Other pages
            if hasattr(self, 'calendar_page'):
                self.calendar_page.set_company_path(company_path)

            if hasattr(self, 'cheque_list_page'):
                self.cheque_list_page.set_company_path(company_path)
        
            if hasattr(self, 'reports_page'):
                 self.reports_page.current_company_path = company_path
                 self.reports_page.refresh_report_data()

            if hasattr(self, 'full_catalog_page'):
                self.full_catalog_page.set_company_path(company_path)

            # Row Data
            self.row_data_page.load_data(comp_name)
            
            # Go to Welcome
            self.nav_stack.setCurrentIndex(1) 
            self.main_stack.setCurrentIndex(1)
            
        except Exception as e:
            QMessageBox.critical(self, "Login Error", f"Failed to load company data:\n{str(e)}")
            print(f"Login Crash: {e}")

    def on_sync_tally_clicked(self):
        if not self.current_company: return
        progress = QProgressDialog("Syncing Tally Data...", None, 0, 0, self)
        progress.show()
        try:
            df, error = fetch_tally_data(company_name=self.current_company)
            progress.close()
            if not error and not df.empty:
                self.row_data_page.load_data(self.current_company)
                QMessageBox.information(self, "Success", "Data Synced!")
                self.main_stack.setCurrentIndex(4)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", str(e))

    def on_row_data_clicked(self):
        if self.current_company:
            self.row_data_page.load_data(self.current_company)
            self.main_stack.setCurrentIndex(4)

    def final_data(self):
        if self.current_company:
            self.final_data_page.load_and_sync_data(self.current_company)
            self.main_stack.setCurrentIndex(5)

    def handle_super_master(self):
        if self.current_company:
            self.super_master_page.load_super_master_data(self.current_company)
            self.main_stack.setCurrentIndex(6)

    def handle_catalog_price_list(self): CatalogPriceListUI(self).exec()
    def handle_int_cost_sheet(self): IntCostSheetUI(self).exec()
    def handle_pur_import(self): PurImportUI(self).exec()
    def handle_security(self): SecurityDialog(self).exec()
    def handle_alter_user(self): UserManagerDialog(self.current_company, mode="alter", parent=self).exec()
    
    def handle_cheque_list(self):
        self.main_stack.setCurrentIndex(15)
    
    def handle_calendar_mapping(self):
        self.main_stack.setCurrentIndex(16)
    
    def handle_create_user(self):
        dlg = UserManagerDialog(self.current_company, parent=self)
        if dlg.exec():
            new_users = dlg.get_table_data()
            if new_users: save_users_to_json(self.current_company, new_users)

    def back_to_login_screen(self):
        self.set_active_menu_btn(None) # Clear highlighting
        self.company_btn.hide()
        self.nav_stack.setCurrentIndex(0)
        self.main_stack.setCurrentIndex(0)
        self.company_login.show_list()

    def show_company_dropdown(self):
        menu = QMenu(self)
        menu.setObjectName("CompanyDropDown")
        menu.addAction(f"Active: {self.current_company}").setEnabled(False)
        menu.addSeparator()
        menu.addAction("🔄 Switch Company", self.back_to_login_screen)
        menu.exec(self.company_btn.mapToGlobal(self.company_btn.rect().bottomLeft()))

    def handle_alter_company(self):
        if self.current_company:
            self.company_login.form_screen.load_for_alter(self.current_company)
            self.main_stack.setCurrentIndex(0)
            self.company_login.stack.setCurrentIndex(1)

    def handle_create_crm(self):
        # Get company path from full_catalog_page
        company_path = getattr(self.full_catalog_page, 'company_path', '') if hasattr(self, 'full_catalog_page') else ''
        crm_file_path = os.path.join(company_path, "crm_data.json") if company_path else "crm_data.json"
        
        dlg = CRMDialog(mode="create", parent=self)
        if dlg.exec():
            name = dlg.get_data().strip()
            if name:
                # Check if CRM already exists
                existing_crms = load_crm_list(crm_file_path)
                if name.lower() in [crm.lower() for crm in existing_crms]:
                    QMessageBox.warning(self, "Duplicate CRM", 
                        f"A CRM with the name '{name}' already exists.\n\nPlease choose a different name.")
                    return
                
                if save_crm_to_json(name, crm_file_path):
                    QMessageBox.information(self, "Success", f"CRM '{name}' created successfully!")
                    # Refresh reports page if available
                    if hasattr(self, 'reports_page'):
                        self.reports_page.refresh_report_data()
                else:
                    QMessageBox.critical(self, "Error", "Failed to save CRM data.")

    def handle_alter_crm(self):
        # Get company path from full_catalog_page
        company_path = getattr(self.full_catalog_page, 'company_path', '') if hasattr(self, 'full_catalog_page') else ''
        crm_file_path = os.path.join(company_path, "crm_data.json") if company_path else "crm_data.json"
        
        crms = load_crm_list(crm_file_path)
        if not crms:
            QMessageBox.warning(self, "Warning", "No CRMs found to alter.")
            return

        dlg = CRMDialog(mode="alter", crm_list=crms, parent=self)
        if dlg.exec():
            old_name, new_name = dlg.get_data()
            if old_name and new_name:
                if update_crm_in_json(old_name, new_name, crm_file_path):
                    QMessageBox.information(self, "Success", f"CRM updated from '{old_name}' to '{new_name}'")
                    # Refresh reports page if available
                    if hasattr(self, 'reports_page'):
                        self.reports_page.refresh_report_data()
                else:
                    QMessageBox.critical(self, "Error", "Failed to update CRM.")