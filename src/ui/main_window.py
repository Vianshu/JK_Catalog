import json
import os
import sys
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QFrame, QStackedWidget, QMenu, QMessageBox, QProgressDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QShortcut, QKeySequence
import sqlite3
import pandas as pd
import re
from src.logic.session_manager import SessionManager
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
from src.ui.group_test_tab import GroupTestTab
from src.utils.path_utils import get_writable_data_path

# Settings & Services
# Settings & Services
from src.ui.settings import (
    CRMDialog, UserManagerDialog, SecurityDialog,
    load_crm_list, save_crm_to_json, update_crm_in_json
)
from src.services.tally_sync import fetch_tally_data

class AltKeyFilter(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
             if event.key() == Qt.Key.Key_Alt:
                 self.mw.toggle_hotkey_hints(True)
        elif event.type() == QEvent.Type.KeyRelease:
             if event.key() == Qt.Key.Key_Alt:
                 self.mw.toggle_hotkey_hints(False)
        return False

class MenuButtonWidget(QFrame):
    clicked = pyqtSignal()
    
    def __init__(self, text, is_back=False, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuButtonWidget") 
        self.setProperty("active", False)
        self.hotkey_char = None 
        
        # Prepare content
        self.plain_text = text.replace("&", "")
        self.html_text = self.plain_text
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(0)
        
        if "&" in text:
            try:
                idx = text.index("&")
                if idx < len(text) - 1:
                    char = text[idx+1]
                    # BADGE STYLE (Front) - High Contrast Red Badge
                    # User requested: "add the letter on the front itself"
                    self.html_text = f"<font color='#ff4d4d'><b>[{char.upper()}]</b></font> {self.plain_text}"
                    self.hotkey_char = char.upper()
            except: pass
            
        # Default to PLAIN text (Clean state)
        self.lbl = QLabel(self.plain_text)
        self.lbl.setObjectName("MenuLabel")
        layout.addWidget(self.lbl)
        layout.addStretch()
        
        # Inline Style
        self.setStyleSheet("""
            #MenuButtonWidget {
                background: transparent;
                border-radius: 8px;
                margin: 4px 12px;
            }
            #MenuButtonWidget:hover {
                background-color: rgba(255, 255, 255, 0.08);
            }
            #MenuButtonWidget[active="true"] {
                background-color: rgba(255, 255, 255, 0.15);
                border-left: 4px solid #3498db;
            }
            QLabel {
                color: #dcdde1;
                font-size: 14px;
                background: transparent;
            }
            #MenuButtonWidget:hover QLabel {
                color: #3498db;
                font-weight: bold;
            }
            #MenuButtonWidget[active="true"] QLabel {
                color: #3498db;
                font-weight: bold;
            }
        """)

    def set_hotkey_visibility(self, visible):
        """Toggle between Plain text and HTML Badge."""
        if visible and self.hotkey_char:
            self.lbl.setText(self.html_text)
        else:
            self.lbl.setText(self.plain_text)

    def mousePressEvent(self, e):
        self.clicked.emit()
        
    def animateClick(self):
        self.clicked.emit()



class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # Global Event Filter for Alt Key
        self.alt_filter = AltKeyFilter(self)
        QApplication.instance().installEventFilter(self.alt_filter)

        self.current_company = ""
        self.is_maximized = True
        self.current_active_btn = None
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_min_max)
        self.setup_ui()
    
    def toggle_hotkey_hints(self, visible):
        """Show/Hide hotkey highlights on current menu."""
        current_page = self.nav_stack.currentWidget()
        if current_page:
            for btn in current_page.findChildren(MenuButtonWidget):
                btn.set_hotkey_visibility(visible)

    def keyPressEvent(self, event):
        """Handle Alt+Key shortcuts contextually and Toggle Highlights."""
        if event.key() == Qt.Key.Key_Alt:
            self.toggle_hotkey_hints(True)

        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            txt = event.text()
            if txt:
                key = txt.upper()
                # Find current menu page
                current_page = self.nav_stack.currentWidget()
                if current_page:
                    # Find buttons in this page
                    buttons = current_page.findChildren(MenuButtonWidget)
                    for btn in buttons:
                        if hasattr(btn, 'hotkey_char') and btn.hotkey_char == key:
                            btn.animateClick()
                            return # Handled
        
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Hide highlights when Alt is released."""
        if event.key() == Qt.Key.Key_Alt:
            self.toggle_hotkey_hints(False)
        super().keyReleaseEvent(event)

    
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
        self.sidebar.setFixedWidth(180)
        
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
        self.main_stack.currentChanged.connect(self.on_main_stack_change)
        self.root_layout.addWidget(self.content_container, 1)

    def init_nav_menus(self):
        """Define menus with Tally-style mnemonics (&Letter)."""
        self.nav_stack.addWidget(QWidget()) # 0: Blank

        # Index 1: Main Menu
        m_main = self.create_menu_widget([
            ("📁 &Catalog", self.show_catalog_submenu),
            ("📊 &Vat Working", self.show_vat_submenu),
            ("⚙️ &Tally Internal", self.show_tally_internal_submenu),
            ("⚙️ &Settings", self.show_settings_submenu)
        ])
        self.nav_stack.addWidget(m_main)

        # Index 2: Catalog Menu
        m_catalog = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🔄 S&ync Tally", self.on_sync_tally_clicked),
            ("📑 Super &Master", self.handle_super_master),
            ("✅ &Final Data", self.final_data),
            ("📖 Full Catalo&g", lambda: self.main_stack.setCurrentIndex(2)),
            ("📈 Rep&orts", lambda: self.main_stack.setCurrentIndex(7)),
            ("🏷 Cat / &Price List", self.handle_catalog_price_list),
            ("🧪 Preview &Rows", lambda: self.main_stack.setCurrentIndex(17)),
            ("➕ Create CRM", self.handle_create_crm, False, "F1"),
            ("✏️ Alter CRM", self.handle_alter_crm, False, "F2")
        ])
        self.nav_stack.addWidget(m_catalog)

        # Index 3: Settings Menu
        m_settings = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🏢 &Alter Company", self.handle_alter_company),
            ("🔄 S&witch Co.", self.back_to_login_screen),
            ("👤 &Create User", self.handle_create_user),
            ("✏️ Alter &User", self.handle_alter_user),
            ("🛡️ Secu&rity", self.handle_security),
            ("📅 Ca&lendar", self.handle_calendar_mapping)
        ])
        self.nav_stack.addWidget(m_settings)

        # Index 4: Tally Internal
        m_tally = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("💰 &On Account", lambda: self.main_stack.setCurrentIndex(9)),
            ("🧾 C&hq. List", self.handle_cheque_list),
            ("🏠 &Godown List", lambda: self.main_stack.setCurrentIndex(10)),
            ("📈 &Sales Chat", lambda: self.main_stack.setCurrentIndex(11)),
            ("💸 Supp. Pa&yment", lambda: self.main_stack.setCurrentIndex(12)),
            ("🏷 Pri&ce List", lambda: self.main_stack.setCurrentIndex(8)),
            ("📥 Pur &Import", self.handle_pur_import),
            ("📊 Cos&t Sheet", self.handle_int_cost_sheet),
            ("🏢 For &Branch", self.show_branch_submenu)
        ])
        self.nav_stack.addWidget(m_tally)

        # Index 5: Vat Working
        m_vat = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("💰 Ba&lance", lambda: self.main_stack.setCurrentIndex(13)),
            ("📦 Stoc&k", lambda: self.main_stack.setCurrentIndex(14))
        ])
        self.nav_stack.addWidget(m_vat)

        # Index 6: Branch Menu
        m_branch = self.create_menu_widget([
            ("⬅️ &Back", self.show_tally_internal_submenu, True),
            ("📦 &BTM Order", None),
            ("📦 &NGT Order", None),
            ("📥 BTM &Receive", None),
            ("📥 N&GT Receive", None)
        ])
        self.nav_stack.addWidget(m_branch)

    def on_main_stack_change(self, idx):
        """Handle main tab changes -> Auto-save/Build Catalog if needed."""
        # If entering Reports (7) or Full Catalog (2), ensure catalog layout is updated
        # This acts as the "Auto Save" feature when switching tabs
        if idx in [2, 7]:
            if hasattr(self, 'full_catalog_page'):
                # Silent build (only processes changes if any)
                self.full_catalog_page.build_catalog(silent=True)

    def init_main_pages(self):
        """राइट साइड के सभी पेजों को लोड करना"""
        self.company_login = CompanyLoginUI()
        self.company_login.login_success_signal.connect(self.handle_login_success)
        
        self.row_data_page = RowDataUI()
        self.final_data_page = FinalDataUI()
        self.super_master_page = SuperMasterUI()
        self.reports_page = ReportsUI()
        self.payment_list_page = PaymentListUI()
        self.godown_page = GodownListUI("") # Will be initialized on login
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

        self.group_test_page = GroupTestTab()
        self.main_stack.addWidget(self.group_test_page) # Index 17
    # --- Helper UI Functions ---
    # --- Helper UI Functions ---
    def create_menu_widget(self, buttons_data):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 10, 5, 10)
        layout.setSpacing(10)
        
        for data in buttons_data:
            text = data[0]
            func = data[1]
            is_back = data[2] if len(data) > 2 else False
            custom_key = data[3] if len(data) > 3 else None
            
            # --- Shortcut Logic (Custom Keys only) ---
            sc = None
            if custom_key:
                 sc = QShortcut(QKeySequence(custom_key), self)
                 
            # --- Create Custom Menu Widget ---
            # Append custom key to text for display
            display_text = text
            if custom_key: 
                 display_text = f"{text} ({custom_key})"
                 
            btn = MenuButtonWidget(display_text, is_back)
            
            if func:
                btn.clicked.connect(lambda checked=False, b=btn: self.set_active_menu_btn(b))
                btn.clicked.connect(func)
                
            if sc:
                 sc.activated.connect(lambda w=widget, b=btn: self.safe_trigger_menu(w, b))

            layout.addWidget(btn)
        
        layout.addStretch()
        return widget

    def safe_trigger_menu(self, parent_widget, btn):
        """Global trigger for main menu hotkeys (Context Sensitive)"""
        # Only trigger if the button is actually visible (Context Sensitive)
        if btn.isVisible():
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
            self.current_company_path = company_path
            
            # Update UI with company name
            clean_name = re.sub(r'\s*\(\d{4}[-/].*?\)', '', comp_name)
            self.company_btn.setText(f"\U0001f3e2 {clean_name} \u25bc")
            self.company_btn.setStyleSheet("text-align: left; padding-left: 10px;")
            self.company_btn.show()

            if not company_path or not os.path.exists(company_path):
                QMessageBox.critical(self, "Error", f"Company path not found:\n{company_path}")
                return

            # --- Use SessionManager for structured page initialization ---
            session = SessionManager()
            
            # Register all pages with their setup functions
            session.register("Final Data", self.final_data_page,
                lambda page, path: (page.load_and_sync_data(comp_name, path), page.set_company_path(path)))
            
            session.register("Super Master", self.super_master_page,
                lambda page, path: page.load_super_master_data(path))
            
            final_df = getattr(self.final_data_page, 'final_df', None)
            session.register("Godown", self.godown_page,
                lambda page, path: page.change_data_folder(path, final_df))
            
            if hasattr(self, 'calendar_page'):
                session.register("Calendar", self.calendar_page,
                    lambda page, path: page.set_company_path(path))

            if hasattr(self, 'cheque_list_page'):
                session.register("Cheque List", self.cheque_list_page,
                    lambda page, path: page.set_company_path(path))
        
            if hasattr(self, 'reports_page'):
                session.register("Reports", self.reports_page,
                    lambda page, path: (setattr(page, 'current_company_path', path), page.refresh_report_data()))

            if hasattr(self, 'full_catalog_page'):
                session.register("Full Catalog", self.full_catalog_page,
                    lambda page, path: page.set_company_path(path))

            if hasattr(self, 'group_test_page') and hasattr(self, 'full_catalog_page'):
                session.register("Group Test", self.group_test_page,
                    lambda page, path: page.set_logic(self.full_catalog_page.logic, path))

            session.register("Row Data", self.row_data_page,
                lambda page, path: page.load_data(path))
            
            # Activate session — all pages get initialized
            result = session.activate(comp_name, company_path)
            
            if result["errors"]:
                error_names = [e[0] for e in result["errors"]]
                print(f"[SESSION] Partial errors in: {', '.join(error_names)}")
            
            self.session = session  # Store for later use
            
            # Navigate to welcome
            self.nav_stack.setCurrentIndex(1) 
            self.main_stack.setCurrentIndex(1)
            
        except Exception as e:
            QMessageBox.critical(self, "Login Error", f"Failed to load company data:\n{str(e)}")
            print(f"Login Crash: {e}")

    def on_sync_tally_clicked(self):
        if not self.current_company: return
        progress = QProgressDialog("Syncing Tally Data...", None, 0, 0, self)
        progress.setWindowTitle("Please Wait")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        
        try:
            df, error = fetch_tally_data(company_name=self.current_company, company_path=self.current_company_path)
            progress.close()
            
            if not error and not df.empty:
                self.row_data_page.load_data(self.current_company_path)
                
                # Sync Final Data and Refresh Full Catalog automatically
                if hasattr(self, 'final_data_page'):
                    self.final_data_page.load_and_sync_data(self.current_company, self.current_company_path)
                if hasattr(self, 'full_catalog_page'):
                    if hasattr(self.full_catalog_page, 'logic'):
                        self.full_catalog_page.logic.invalidate_cache()
                    self.full_catalog_page.refresh_catalog_data()
                    
                QMessageBox.information(self, "Sync Complete", f"Data Synced Successfully!\nLoaded {len(df)} rows.\n\nClick OK to close.")
            else:
                msg = error if error else "No data received from Tally. Check connection."
                QMessageBox.warning(self, "Sync Issue", f"{msg}\n\nClick OK to close.")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Sync Failed: {str(e)}")

    def on_row_data_clicked(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.row_data_page.load_data(self.current_company_path)
            self.main_stack.setCurrentIndex(4)

    def final_data(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.final_data_page.load_and_sync_data(self.current_company, self.current_company_path)
            self.main_stack.setCurrentIndex(5)

    def handle_super_master(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.super_master_page.load_super_master_data(self.current_company_path)
            self.main_stack.setCurrentIndex(6)

    def handle_catalog_price_list(self): CatalogPriceListUI(self).exec()
    def handle_int_cost_sheet(self): IntCostSheetUI(self).exec()
    def handle_pur_import(self): PurImportUI(self).exec()
    def handle_security(self): SecurityDialog(self).exec()
    def handle_alter_user(self): 
        if self.current_company and hasattr(self, 'current_company_path'):
            UserManagerDialog(self.current_company, self.current_company_path, parent=self).exec()
    
    def handle_cheque_list(self):
        self.main_stack.setCurrentIndex(15)
    
    def handle_calendar_mapping(self):
        self.main_stack.setCurrentIndex(16)
    
    def handle_create_user(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            # Dialog handles saving internally now via SecurityManager
            UserManagerDialog(self.current_company, self.current_company_path, parent=self).exec()

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