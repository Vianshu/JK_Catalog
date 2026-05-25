import json
import os
import sys
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QFrame, QStackedWidget, QMenu, QMessageBox, QProgressDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QShortcut, QKeySequence, QIcon
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
from src.ui.ledger_row_data import LedgerRowDataUI
from src.utils.app_logger import get_logger, set_company_context

logger = get_logger(__name__)

# Settings & Services
# Settings & Services
from src.ui.settings import (
    CRMDialog, UserManagerDialog, SecurityUI,
    AuditLogDialog, ChangePasswordDialog,
    load_crm_list, save_crm_to_json, update_crm_in_json
)
from src.services.tally_sync import fetch_tally_data, fetch_tally_ledger_data

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
        layout.setContentsMargins(6, 12, 6, 12)
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
        # Direct style on label — required because Fusion style engine overrides
        # QSS child selectors from app-level stylesheet on QFrame children.
        self.lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 600; background: transparent; border: none;")
        layout.addWidget(self.lbl)
        layout.addStretch()
        
        # Styling handled by style.qss via #MenuButtonWidget selector

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
        # Native title bar with minimize/maximize/close buttons
        self.setWindowTitle("JK Catalog Multi")
        # Allow the window to shrink to any size — prevents children from
        # pushing the window behind the taskbar on smaller screens.
        self.setMinimumSize(0, 0)
        
        # Set Application Icon
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "JK_Icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self._apply_titlebar_color()
        
        # Global Event Filter for Alt Key
        self.alt_filter = AltKeyFilter(self)
        QApplication.instance().installEventFilter(self.alt_filter)

        self.current_company = ""
        self.is_maximized = True
        self.current_active_btn = None
        self.user_session = None  # UserSession set after login
        
        # Session timeout timer (30 min default, reset on user activity)
        from PyQt6.QtCore import QTimer
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_session_timeout)
        self._timeout_minutes = 0  # Disabled per user request (was 30)
        
        # Live permission polling timer (60s interval)
        self._perm_poll_timer = QTimer(self)
        self._perm_poll_timer.setInterval(60_000)  # 60 seconds
        self._perm_poll_timer.timeout.connect(self._poll_permissions)
        self._security_mgr = None  # Initialized on login
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_min_max)
        
        # Listen for taskbar toggling or screen size changes dynamically
        screen = QApplication.primaryScreen()
        if screen:
            screen.availableGeometryChanged.connect(self._on_screen_changed)
            
        self.setup_ui()

    def _on_screen_changed(self, rect):
        """Update window boundaries if user changes taskbar settings mid-session."""
        if not self.isMinimized():
            self.maximize_window()
    
    def toggle_hotkey_hints(self, visible):
        """Show/Hide hotkey highlights on current menu."""
        current_page = self.nav_stack.currentWidget()
        if current_page:
            for btn in current_page.findChildren(MenuButtonWidget):
                btn.set_hotkey_visibility(visible)

    def keyPressEvent(self, event):
        """Handle Alt+Key shortcuts contextually and Toggle Highlights."""
        self._reset_timeout()  # Reset session timeout on keyboard activity
        if event.key() == Qt.Key.Key_Alt:
            self.toggle_hotkey_hints(True)

        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            txt = event.text()
            if txt:
                key = txt.upper()
                current_page = self.nav_stack.currentWidget()
                if current_page:
                    buttons = current_page.findChildren(MenuButtonWidget)
                    for btn in buttons:
                        if hasattr(btn, 'hotkey_char') and btn.hotkey_char == key:
                            btn.animateClick()
                            return
        
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Hide highlights when Alt is released."""
        if event.key() == Qt.Key.Key_Alt:
            self.toggle_hotkey_hints(False)
        super().keyReleaseEvent(event)

    def _apply_titlebar_color(self):
        """Set Windows title bar color to match the teal theme using DWM API."""
        try:
            import ctypes
            from ctypes import wintypes
            dwmapi = ctypes.windll.dwmapi
            hwnd = int(self.winId())
            
            # DWMWA_CAPTION_COLOR = 35 (Windows 11 22H2+)
            # DWMWA_TEXT_COLOR = 36
            # Color format is COLORREF (0x00BBGGRR)
            # Darker Teal #045E54 → R=0x04, G=0x5E, B=0x54 → COLORREF = 0x00545E04
            caption_color = ctypes.c_int(0x00545E04)
            dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
            
            # White title text
            text_color = ctypes.c_int(0x00FFFFFF)
            dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
        except Exception:
            pass  # Silently fail on non-Windows or older Windows versions

    def toggle_min_max(self):
        if self.isMinimized():
            self.maximize_window()
        else:
            self.showMinimized()

    def maximize_window(self):
        """Use native maximize since we have a standard title bar."""
        self.showMaximized()
    
    def setup_ui(self):
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        # Prevent child minimum sizes from forcing the window behind the taskbar
        from PyQt6.QtWidgets import QLayout
        self.root_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # ========== LEFT SIDEBAR ==========
        self.sidebar = QFrame()
        self.sidebar.setObjectName("MainSidebar")
        self.sidebar.setFixedWidth(180)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 10)
        sidebar_layout.setSpacing(0)

        # Company Display Button
        self.company_btn = QPushButton("🏢 Select Company  ▼")
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
        quit_lbl = QLabel("Press Ctrl+Q to Quit")
        quit_lbl.setObjectName("QuitHint")
        sidebar_layout.addWidget(quit_lbl)

        # Logout Button
        self.logout_btn = QPushButton("🚪 LOGOUT")
        self.logout_btn.setObjectName("LogoutBtn")
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

        # Index 2: Catalog Menu (permission keys for access control)
        m_catalog = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🔄 S&ync Tally", self.on_sync_tally_clicked, False, None, "final_data.sync"),
            ("📑 Super &Master", self.handle_super_master, False, None, "tab.super_master"),
            ("✅ &Final Data", self.final_data, False, None, "tab.final_data"),
            ("📖 Full Catalo&g", lambda: self.main_stack.setCurrentIndex(2), False, None, "tab.catalog"),
            ("📈 Rep&orts", lambda: self.main_stack.setCurrentIndex(7), False, None, "tab.reports"),
            ("🏷 Cat / &Price List", self.handle_catalog_price_list, False, None, "tab.cat_price_list"),
            ("➕ &Create CRM", self.handle_create_crm, False, None, "settings.manage_crm"),
            ("✏️ &Alter CRM", self.handle_alter_crm, False, None, "settings.manage_crm")
        ])
        self.nav_stack.addWidget(m_catalog)

        # Index 3: Settings Menu
        m_settings = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🏢 &Alter Company", self.handle_alter_company, False, None, "settings.company_config"),
            ("🔄 S&witch Co.", self.back_to_login_screen),
            ("👥 &Users", self.handle_manage_users, False, None, "settings.manage_users"),
            ("🛡️ User &Roles", self.handle_security, False, None, "settings.manage_roles"),
            ("📋 Audit &Log", self.handle_audit_log, False, None, "settings.manage_roles"),
            ("🔑 Change &Password", self.handle_change_password, False, None, "settings.manage_users"),
            ("📅 Ca&lendar", self.handle_calendar_mapping, False, None, "tab.calendar")
        ])
        self.nav_stack.addWidget(m_settings)

        # Index 4: Tally Internal
        m_tally = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🔄 Sync &Ledger", self.on_sync_ledger_clicked, False, None, "ledger.sync"),
            ("🧪 Ledger &Rows", self.on_ledger_row_data_clicked, False, None, "tab.ledger"),
            ("💰 &On Account", lambda: self.main_stack.setCurrentIndex(9), False, None, "tab.payment_list"),
            ("🧾 C&hq. List", self.handle_cheque_list, False, None, "tab.cheque_list"),
            ("🏠 &Godown List", lambda: self.main_stack.setCurrentIndex(10), False, None, "tab.godown"),
            ("📈 &Sales Chat", lambda: self.main_stack.setCurrentIndex(11), False, None, "tab.sales_chat"),
            ("💸 Supp. Pa&yment", lambda: self.main_stack.setCurrentIndex(12), False, None, "tab.supp_payment"),
            ("🏷 Pri&ce List", lambda: self.main_stack.setCurrentIndex(8), False, None, "tab.price_list"),
            ("📥 Pur &Import", self.handle_pur_import, False, None, "tab.pur_import"),
            ("📊 Cos&t Sheet", self.handle_int_cost_sheet, False, None, "tab.int_cost_sheet"),
            ("🏢 For &Branch", self.show_branch_submenu, False, None, "tab.for_branch")
        ])
        self.nav_stack.addWidget(m_tally)

        # Index 5: Vat Working
        m_vat = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("💰 Ba&lance", lambda: self.main_stack.setCurrentIndex(13), False, None, "tab.vat_balance"),
            ("📦 Stoc&k", lambda: self.main_stack.setCurrentIndex(14), False, None, "tab.vat_stock")
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

    def on_sync_ledger_clicked(self):
        """Sync Ledger data from Tally into the company's ledger DB (background thread)."""
        if not self.current_company:
            return
        if not self._check_permission("ledger.sync", "Ledger Sync"):
            return

        # Prevent concurrent syncs
        if hasattr(self, '_ledger_worker') and self._ledger_worker and self._ledger_worker.isRunning():
            return

        self._ledger_progress = QProgressDialog("Syncing Ledger Data...", None, 0, 0, self)
        self._ledger_progress.setWindowTitle("Please Wait")
        self._ledger_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._ledger_progress.setMinimumDuration(0)
        self._ledger_progress.setCancelButton(None)
        self._ledger_progress.show()

        company_path = getattr(self, 'current_company_path', None)

        # Run in background thread
        from PyQt6.QtCore import QThread, pyqtSignal
        class _LedgerWorker(QThread):
            finished = pyqtSignal(int, str)  # row_count, error
            def __init__(self, path):
                super().__init__()
                self.path = path
            def run(self):
                try:
                    rc, err = fetch_tally_ledger_data(company_path=self.path)
                    self.finished.emit(rc or 0, err or "")
                except Exception as e:
                    self.finished.emit(0, str(e))

        self._ledger_worker = _LedgerWorker(company_path)
        self._ledger_worker.finished.connect(self._on_ledger_sync_done)
        self._ledger_worker.start()

    def _on_ledger_sync_done(self, row_count, error):
        """Handle ledger sync completion (runs on main thread)."""
        if hasattr(self, '_ledger_progress') and self._ledger_progress:
            self._ledger_progress.close()
        if not error and row_count > 0:
            QMessageBox.information(
                self, "Sync Complete",
                f"Ledger data synced successfully!\nLoaded {row_count} ledger entries."
            )
        else:
            msg = error if error else "No ledger data received from Tally."
            QMessageBox.warning(self, "Sync Issue", msg)

    def on_main_stack_change(self, idx):
        """Handle main tab changes -> Auto-build Catalog only on relevant tabs."""
        # Silent catalog build ONLY on Catalog (2) and Reports (7) tabs
        # Other tabs have zero dependency on catalog build output
        if idx in (2, 7) and hasattr(self, 'full_catalog_page'):
            self.full_catalog_page.build_catalog(silent=True)
            
        # If entering Reports tab, check if it's currently building
        if idx == 7 and hasattr(self, 'reports_page'):
            is_running = hasattr(self.full_catalog_page, '_build_worker') and self.full_catalog_page._build_worker is not None and self.full_catalog_page._build_worker.isRunning()
            self.reports_page.set_refreshing(is_running)

    def on_catalog_built(self):
        """Called when Full Catalog finishes building in the background"""
        if hasattr(self, 'reports_page'):
            self.reports_page.set_refreshing(False)
            self.reports_page.refresh_report_data()

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
        self.full_catalog_page.catalog_built.connect(self.on_catalog_built)
        
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


        self.ledger_row_data_page = LedgerRowDataUI()
        self.main_stack.addWidget(self.ledger_row_data_page) # Index 17

        self.security_page = SecurityUI(self)
        self.main_stack.addWidget(self.security_page) # Index 18
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
            perm_key = data[4] if len(data) > 4 else None
            
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
            
            # Store permission key on the button for later enforcement
            if perm_key:
                btn.setProperty("permission_key", perm_key)
            
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
    def handle_login_success(self, comp_name, company_path, user_session=None):
        try:
            self.current_company = comp_name
            self.current_company_path = company_path
            self.user_session = user_session
            set_company_context(comp_name)
            
            # Update UI with company name
            clean_name = re.sub(r'\s*\(\d{4}[-/].*?\)', '', comp_name)
            self.company_btn.setText(f"\U0001f3e2 {clean_name} \u25bc")
            self.company_btn.show()

            if not company_path or not os.path.exists(company_path):
                QMessageBox.critical(self, "Error", f"Company path not found:\n{company_path}")
                return

            # --- Use SessionManager for structured page initialization ---
            session = SessionManager()
            
            # Register all pages with their setup functions
            session.register("Final Data", self.final_data_page,
                lambda page, path: (page.set_company_path(path), page.refresh_table()))
            
            session.register("Super Master", self.super_master_page,
                lambda page, path: page.load_super_master_data(path))
            
            session.register("Godown", self.godown_page,
                lambda page, path: page.change_data_folder(path, getattr(self.final_data_page, 'final_df', None)))
            
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


            session.register("Row Data", self.row_data_page,
                lambda page, path: page.load_data(path))

            session.register("Ledger Row Data", self.ledger_row_data_page,
                lambda page, path: page.load_data(path))
            
            # Activate session — all pages get initialized
            result = session.activate(comp_name, company_path)
            
            if result["errors"]:
                error_names = [e[0] for e in result["errors"]]
                logger.warning(f"Session partial errors: {', '.join(error_names)}")
            
            self.session = session  # Store for later use
            
            logger.info(f"Session started: company='{comp_name}', path='{company_path}'")

            # Navigate to welcome
            self.nav_stack.setCurrentIndex(1) 
            self.main_stack.setCurrentIndex(1)
            
            # Apply RBAC permissions to menu buttons and inside-tab controls
            # Propagate session to pages that need internal permission checks
            for page in [self.final_data_page, self.super_master_page,
                         self.full_catalog_page, self.reports_page,
                         self.godown_page]:
                page._user_session = self.user_session
            if hasattr(self, 'cheque_list_page'):
                self.cheque_list_page._user_session = self.user_session
            if hasattr(self, 'calendar_page'):
                self.calendar_page._user_session = self.user_session
            
            self._apply_permissions()
            self._start_timeout()  # Start session timeout
            
            # Start live permission polling
            from src.logic.security_manager import SecurityManager
            self._security_mgr = SecurityManager(
                os.path.dirname(company_path) if company_path else "")
            self._perm_poll_timer.start()
            
            # CRITICAL FIX: Lock the window size again so the dashboard
            # cannot push the bottom out of bounds.
            self.maximize_window()
            
        except Exception as e:
            logger.error(f"Login failed: company='{comp_name}', error={e}", exc_info=True)
            QMessageBox.critical(self, "Login Error", f"Failed to load company data:\n{str(e)}")

    def _apply_permissions(self):
        """Enforce RBAC on menu buttons AND inside-tab controls after login.
        
        Two layers:
        1. Menu buttons — scanned for 'permission_key' property
        2. Inside-tab controls — buttons/tables disabled based on permission keys
        """
        if not self.user_session:
            return
        
        s = self.user_session  # shorthand
        
        # ── Layer 1: Menu Buttons ──
        for menu_widget in [self.nav_stack.widget(i) for i in range(self.nav_stack.count())]:
            if not menu_widget:
                continue
            for btn in menu_widget.findChildren(MenuButtonWidget):
                perm_key = btn.property("permission_key")
                if perm_key and isinstance(perm_key, str):
                    allowed = s.can(perm_key)
                    btn.setEnabled(allowed)
                    if not allowed:
                        btn.setToolTip(f"🔒 Access denied — requires '{perm_key}' permission")
                    else:
                        btn.setToolTip("")
        
        # ── Layer 2: Inside-Tab Controls ──
        
        # Final Data — table editing
        if hasattr(self, 'final_data_page'):
            page = self.final_data_page
            can_edit = s.can("final_data.edit")
            if hasattr(page, 'table'):
                if can_edit:
                    page.table.setEditTriggers(
                        page.table.EditTrigger.CurrentChanged | page.table.EditTrigger.EditKeyPressed)
                else:
                    page.table.setEditTriggers(page.table.EditTrigger.NoEditTriggers)
        
        # Full Catalog — build, print, export, reshuffle, page management
        if hasattr(self, 'full_catalog_page'):
            page = self.full_catalog_page
            if hasattr(page, 'btn_build'):
                page.btn_build.setEnabled(s.can("catalog.build"))
            if hasattr(page, 'btn_print'):
                page.btn_print.setEnabled(s.can("catalog.print"))
            if hasattr(page, 'btn_export'):
                page.btn_export.setEnabled(s.can("catalog.print"))
            if hasattr(page, 'btn_reshuffle'):
                page.btn_reshuffle.setEnabled(s.can("catalog.edit_assignment"))
            if hasattr(page, 'btn_add_page'):
                page.btn_add_page.setEnabled(s.can("catalog.edit_assignment"))
            if hasattr(page, 'btn_remove_page'):
                page.btn_remove_page.setEnabled(s.can("catalog.edit_assignment"))
        
        # Reports — print and mark done
        if hasattr(self, 'reports_page'):
            page = self.reports_page
            can_print = s.can("reports.print")
            can_mark = s.can("reports.mark_done")
            # Reports page buttons may have different naming — guard safely
            for attr in ['btn_print', 'print_btn', 'btn_print_all']:
                if hasattr(page, attr):
                    getattr(page, attr).setEnabled(can_print)
            for attr in ['btn_mark_done', 'mark_done_btn', 'btn_done']:
                if hasattr(page, attr):
                    getattr(page, attr).setEnabled(can_mark)
        
        # Super Master — editing
        if hasattr(self, 'super_master_page'):
            page = self.super_master_page
            can_edit = s.can("super_master.edit")
            if hasattr(page, 'table'):
                if can_edit:
                    page.table.setEditTriggers(
                        page.table.EditTrigger.CurrentChanged | page.table.EditTrigger.EditKeyPressed)
                else:
                    page.table.setEditTriggers(page.table.EditTrigger.NoEditTriggers)
        
        # Cheque List — editing
        if hasattr(self, 'cheque_list_page'):
            page = self.cheque_list_page
            can_edit = s.can("cheque_list.edit")
            if hasattr(page, 'table'):
                if can_edit:
                    page.table.setEditTriggers(
                        page.table.EditTrigger.CurrentChanged | page.table.EditTrigger.EditKeyPressed)
                else:
                    page.table.setEditTriggers(page.table.EditTrigger.NoEditTriggers)
        
        # Calendar — editing
        if hasattr(self, 'calendar_page'):
            page = self.calendar_page
            can_edit = s.can("calendar.edit")
            if hasattr(page, 'table'):
                if can_edit:
                    page.table.setEditTriggers(
                        page.table.EditTrigger.CurrentChanged | page.table.EditTrigger.EditKeyPressed)
                else:
                    page.table.setEditTriggers(page.table.EditTrigger.NoEditTriggers)
        
        logger.info(f"Permissions applied: user='{s.username}', "
                     f"role='{s.role_name}', admin={s.is_admin}")

    def _poll_permissions(self):
        """Called every 60s to silently refresh permissions from SQL.
        
        If the admin changed this user's role or permissions while
        the app is open, the sidebar and tab controls update automatically.
        If the user was deactivated, they are force-logged out.
        """
        if not self.user_session or not self._security_mgr:
            return
        
        try:
            changed = self._security_mgr.refresh_session_permissions(self.user_session)
            if not changed:
                return  # Nothing to do
            
            # Check if user was deactivated
            if self.user_session.role_name == "Deactivated":
                self._perm_poll_timer.stop()
                QMessageBox.warning(self, "Account Deactivated",
                    "Your account has been deactivated by an administrator.\n"
                    "You will be logged out now.")
                self.back_to_login_screen()
                return
            
            # Permissions changed — re-apply to UI
            self._apply_permissions()
            logger.info("Live permission refresh applied")
            
        except Exception as e:
            logger.error(f"Permission polling error: {e}")

    def _check_permission(self, permission_key, action_name="this action"):
        """Action-gate: verify permission at the exact moment of action.
        
        Call this at the top of any handler that performs a protected action.
        Returns True if allowed, False if denied (shows a popup).
        
        Usage:
            def on_sync_tally_clicked(self):
                if not self._check_permission("final_data.sync", "Tally Sync"):
                    return
                # ... proceed with sync
        """
        if not self.user_session:
            return False
        
        # Admins always pass
        if self.user_session.is_admin:
            return True
        
        # Do a live micro-check from the database
        if self._security_mgr:
            self._security_mgr.refresh_session_permissions(self.user_session)
        
        if self.user_session.can(permission_key):
            return True
        
        QMessageBox.warning(self, "Access Denied",
            f"🔒 You do not have permission to perform {action_name}.\n\n"
            f"Required: '{permission_key}'\n"
            f"Your role: '{self.user_session.role_name}'\n\n"
            "Contact your administrator to request access.")
        
        # Also refresh the UI since permissions may have changed
        self._apply_permissions()
        return False

    def _start_timeout(self):
        """Start/restart the session timeout timer after login."""
        if self._timeout_minutes > 0:
            self._timeout_timer.start(self._timeout_minutes * 60 * 1000)

    def _reset_timeout(self):
        """Reset the timer on any user activity (called from event handlers)."""
        if self.user_session and self._timeout_timer.isActive():
            self._timeout_timer.start(self._timeout_minutes * 60 * 1000)

    def _on_session_timeout(self):
        """Auto-logout when session times out."""
        if not self.user_session:
            return
        logger.warning(f"Session timeout: user='{self.user_session.username}'")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Session Expired",
            f"Your session has timed out after {self._timeout_minutes} minutes of inactivity.\n"
            "You will be logged out.")
        self.back_to_login_screen()

    def mousePressEvent(self, event):
        """Reset timeout on mouse click."""
        self._reset_timeout()
        super().mousePressEvent(event)

    def on_sync_tally_clicked(self):
        if not self.current_company: return
        if not self._check_permission("final_data.sync", "Tally Sync"): return
        logger.info(f"Tally sync started")
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
                
                # Chain: Final Data sync (async) → catalog build → success message
                row_count = len(df)
                logger.info(f"Tally sync received: {row_count} rows")
                def _after_sync():
                    self.final_data_page.sync_complete.disconnect(_after_sync)
                    # Trigger a silent catalog build
                    if hasattr(self, 'full_catalog_page'):
                        if hasattr(self.full_catalog_page, 'logic'):
                            self.full_catalog_page.logic.invalidate_cache()
                        self.full_catalog_page.build_catalog(silent=True)
                    QMessageBox.information(self, "Sync Complete", f"Data Synced Successfully!\nLoaded {row_count} rows.\n\nClick OK to close.")
                    # L-6: Audit log for Tally sync
                    if self._security_mgr and self.user_session:
                        self._security_mgr.log_action(self.user_session, "tally_sync",
                            module="final_data", detail=f"Synced {row_count} rows")
                
                if hasattr(self, 'final_data_page'):
                    self.final_data_page.sync_complete.connect(_after_sync)
                    self.final_data_page.load_and_sync_data(self.current_company, self.current_company_path)
                else:
                    QMessageBox.information(self, "Sync Complete", f"Data Synced Successfully!\nLoaded {row_count} rows.")
            else:
                msg = error if error else "No data received from Tally. Check connection."
                logger.warning(f"Tally sync issue: {msg}")
                QMessageBox.warning(self, "Sync Issue", f"{msg}\n\nClick OK to close.")
        except Exception as e:
            progress.close()
            logger.error(f"Tally sync failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Sync Failed: {str(e)}")

    def on_row_data_clicked(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.row_data_page.load_data(self.current_company_path)
            self.main_stack.setCurrentIndex(4)

    def on_ledger_row_data_clicked(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.ledger_row_data_page.load_data(self.current_company_path)
            self.main_stack.setCurrentIndex(17)

    def final_data(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.main_stack.setCurrentIndex(5)
            # Only refresh the table view, don't re-sync from scratch
            self.final_data_page.refresh_table()

    def handle_super_master(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.super_master_page.load_super_master_data(self.current_company_path)
            self.main_stack.setCurrentIndex(6)

    def handle_catalog_price_list(self): CatalogPriceListUI(self).exec()
    def handle_int_cost_sheet(self): IntCostSheetUI(self).exec()
    def handle_pur_import(self): PurImportUI(self).exec()
    def handle_security(self): 
        if self.current_company and hasattr(self, 'current_company_path'):
            self.security_page.refresh_data()
            self.main_stack.setCurrentIndex(18)
    
    def handle_audit_log(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            AuditLogDialog(self.current_company, self.current_company_path, parent=self).exec()
    
    def handle_change_password(self):
        if not self.user_session:
            return
        # Admin-only: block at UI level as well
        if not self.user_session.is_admin:
            QMessageBox.warning(self, "Access Denied",
                "Only administrators can change passwords.")
            return
        # Reuse existing SecurityManager instance instead of creating a new one
        sm = self._security_mgr
        if not sm:
            from src.logic.security_manager import SecurityManager
            sm = SecurityManager(os.path.dirname(self.current_company_path) if hasattr(self, 'current_company_path') else "")
        ChangePasswordDialog(self.user_session, sm, parent=self).exec()
    
    def handle_cheque_list(self):
        self.main_stack.setCurrentIndex(15)
    
    def handle_calendar_mapping(self):
        self.main_stack.setCurrentIndex(16)
    
    def handle_manage_users(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            UserManagerDialog(self.current_company, self.current_company_path, parent=self).exec()

    def back_to_login_screen(self):
        logger.info(f"User logged out")
        set_company_context("")
        self.user_session = None  # Clear session
        self._timeout_timer.stop()  # Stop session timeout
        self._perm_poll_timer.stop()  # Stop permission polling
        self._security_mgr = None
        self.set_active_menu_btn(None) # Clear highlighting
        self.company_btn.hide()
        
        # Re-enable all menu buttons (clear permission locks from previous session)
        for menu_widget in [self.nav_stack.widget(i) for i in range(self.nav_stack.count())]:
            if not menu_widget:
                continue
            for btn in menu_widget.findChildren(MenuButtonWidget):
                btn.setEnabled(True)
                btn.setToolTip("")
        
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
        if self.current_company and hasattr(self, 'current_company_path'):
            self.company_login.form_screen.load_for_alter(self.current_company_path)
            self.main_stack.setCurrentIndex(0)
            self.company_login.stack.setCurrentIndex(1)

    def handle_create_crm(self):
        # Get company path from full_catalog_page
        company_path = getattr(self.full_catalog_page, 'company_path', '') if hasattr(self, 'full_catalog_page') else ''
        
        dlg = CRMDialog(mode="create", parent=self)
        if dlg.exec():
            name = dlg.get_data().strip()
            if name:
                # Check if CRM already exists
                existing_crms = load_crm_list(company_path)
                if name.lower() in [crm.lower() for crm in existing_crms]:
                    QMessageBox.warning(self, "Duplicate CRM", 
                        f"A CRM with the name '{name}' already exists.\n\nPlease choose a different name.")
                    return
                
                if save_crm_to_json(name, company_path):
                    logger.info(f"CRM created: name='{name}'")
                    QMessageBox.information(self, "Success", f"CRM '{name}' created successfully!")
                    # L-6: Audit log for CRM creation
                    if self._security_mgr and self.user_session:
                        self._security_mgr.log_action(self.user_session, "crm_create",
                            module="crm", detail=f"Created CRM: {name}")
                    # Refresh reports page if available
                    if hasattr(self, 'reports_page'):
                        self.reports_page.refresh_report_data()
                else:
                    QMessageBox.critical(self, "Error", "Failed to save CRM data.")

    def handle_alter_crm(self):
        # Get company path from full_catalog_page
        company_path = getattr(self.full_catalog_page, 'company_path', '') if hasattr(self, 'full_catalog_page') else ''
        
        crms = load_crm_list(company_path)
        if not crms:
            QMessageBox.warning(self, "Warning", "No CRMs found to alter.")
            return

        dlg = CRMDialog(mode="alter", crm_list=crms, parent=self)
        if dlg.exec():
            old_name, new_name = dlg.get_data()
            if old_name and new_name:
                if update_crm_in_json(old_name, new_name, company_path):
                    logger.info(f"CRM renamed: '{old_name}' -> '{new_name}'")
                    QMessageBox.information(self, "Success", f"CRM updated from '{old_name}' to '{new_name}'")
                    # L-6: Audit log for CRM alteration
                    if self._security_mgr and self.user_session:
                        self._security_mgr.log_action(self.user_session, "crm_rename",
                            module="crm", detail=f"Renamed: {old_name} -> {new_name}")
                    # Refresh reports page if available
                    if hasattr(self, 'reports_page'):
                        self.reports_page.refresh_report_data()
                else:
                    QMessageBox.critical(self, "Error", "Failed to update CRM.")