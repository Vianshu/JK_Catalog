import json
import os
import sys
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QFrame, QStackedWidget, QMenu, QMessageBox, QProgressDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QSettings, QThread, pyqtSignal, QObject, QEvent
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
from src.ui.supp_payment import SuppPaymentV2UI
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
from src.ui.supp_payment.shared import get_icon
# Settings & Services
from src.ui.settings import (
    CRMDialog, UserManagerDialog, SecurityUI,
    AuditLogDialog, ChangePasswordDialog,
    load_crm_list, save_crm_to_json, update_crm_in_json
)
from src.services.tally_sync import fetch_tally_data, fetch_tally_ledger_data, TallyService
from PyQt6.QtCore import QThread, pyqtSignal

class _LedgerWorker(QThread):
    finished = pyqtSignal(int, str)  # row_count, error
    def __init__(self, company_name, path, service=None):
        super().__init__()
        self.company_name = company_name
        self.path = path
        self.service = service
    def run(self):
        try:
            rc, err = fetch_tally_ledger_data(
                company_name=self.company_name,
                company_path=self.path,
                service=self.service
            )
            self.finished.emit(rc or 0, err or "")
        except Exception as e:
            self.finished.emit(0, str(e))

class _TallyWorker(QThread):
    finished = pyqtSignal(object, str)  # (df_or_None, error)
    def __init__(self, service, company_name, company_path):
        super().__init__()
        self.service = service
        self.company_name = company_name
        self.company_path = company_path
    def run(self):
        try:
            df, error = fetch_tally_data(
                company_name=self.company_name,
                company_path=self.company_path,
                service=self.service
            )
            self.finished.emit(df, error)
        except Exception as e:
            self.finished.emit(None, str(e))

class _ExportWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, data_path, output_file):
        super().__init__()
        self.data_path = data_path
        self.output_file = output_file
        self.is_cancelled = False

    def run(self):
        from src.logic.data_transfer import export_data_path
        def on_progress(text, current, total):
            if self.is_cancelled:
                raise Exception("cancelled")
            self.progress.emit(text, current, total)
        try:
            success, msg = export_data_path(self.data_path, self.output_file, on_progress)
            self.finished.emit(success, msg)
        except Exception as e:
            if str(e) == "cancelled":
                self.finished.emit(False, "Export cancelled by user")
            else:
                self.finished.emit(False, str(e))


class _CompanyExportWorker(QThread):
    """Worker thread for single-company backup."""
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, company_path, output_file):
        super().__init__()
        self.company_path = company_path
        self.output_file = output_file
        self.is_cancelled = False

    def run(self):
        from src.logic.data_transfer import export_single_company
        def on_progress(text, current, total):
            if self.is_cancelled:
                raise Exception("cancelled")
            self.progress.emit(text, current, total)
        try:
            success, msg = export_single_company(
                self.company_path, self.output_file, on_progress
            )
            self.finished.emit(success, msg)
        except Exception as e:
            if str(e) == "cancelled":
                self.finished.emit(False, "Export cancelled by user")
            else:
                self.finished.emit(False, str(e))

class _ImportWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, backup_file, target_path):
        super().__init__()
        self.backup_file = backup_file
        self.target_path = target_path
        self.is_cancelled = False

    def run(self):
        from src.logic.data_transfer import import_data_path
        def on_progress(text, current, total):
            if self.is_cancelled:
                raise Exception("cancelled")
            self.progress.emit(text, current, total)
        try:
            success, msg = import_data_path(self.backup_file, self.target_path, on_progress)
            self.finished.emit(success, msg)
        except Exception as e:
            if str(e) == "cancelled":
                self.finished.emit(False, "Import cancelled by user")
            else:
                self.finished.emit(False, str(e))


class _SelectiveImportWorker(QThread):
    """Worker thread for selective restore (Temp DB merge approach)."""
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, backup_file, data_path, company_folder, modules):
        super().__init__()
        self.backup_file = backup_file
        self.data_path = data_path
        self.company_folder = company_folder
        self.modules = modules  # list or dict
        self.is_cancelled = False

    def run(self):
        from src.logic.db_manager import get_db_manager
        from src.logic.data_transfer import selective_restore_company
        def on_progress(text, current, total):
            if self.is_cancelled:
                raise Exception("cancelled")
            self.progress.emit(text, current, total)
        try:
            success, msg = selective_restore_company(
                self.backup_file,
                self.data_path,
                self.company_folder,
                self.modules,
                on_progress,
            )
            self.finished.emit(success, msg)
        except Exception as e:
            if str(e) == "cancelled":
                self.finished.emit(False, "Selective restore cancelled")
            else:
                self.finished.emit(False, str(e))
        finally:
            try:
                get_db_manager().close_thread_connections()
            except Exception:
                pass


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

    _SS_NORMAL = (
        "QLabel { color: #ffffff; font-size: 15px; font-weight: 600;"
        " background: transparent; border: none; }"
        " QLabel:disabled { color: rgba(255,255,255,0.35); }"
    )
    _SS_HOVER = (
        "QLabel { color: #ffffff; font-size: 15px; font-weight: 700;"
        " background: transparent; border: none; }"
        " QLabel:disabled { color: rgba(255,255,255,0.35); }"
    )

    def __init__(self, text, is_back=False, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuButtonWidget")
        self.setProperty("active", False)
        self.hotkey_char = None

        if is_back:
            self.setProperty("is_back", True)

        # Prepare content
        self.plain_text = text.replace("&", "")
        self.html_text = self.plain_text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 12, 10, 12)
        layout.setSpacing(0)

        if "&" in text:
            try:
                idx = text.index("&")
                if idx < len(text) - 1:
                    char = text[idx+1]
                    self.html_text = f"<font color='#ff4d4d'><b>[{char.upper()}]</b></font> {self.plain_text}"
                    self.hotkey_char = char.upper()
            except Exception:
                pass

        self.lbl = QLabel(self.plain_text)
        self.lbl.setObjectName("MenuLabel")
        # Inline stylesheet needed — Fusion style engine ignores QSS on child labels.
        self.lbl.setStyleSheet(self._SS_NORMAL)
        # Pass hover hit-tests through to the parent frame so enterEvent/leaveEvent fire.
        self.lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.lbl)
        layout.addStretch()

    # ── hover: manually update bg (frame) + weight (label) ──────────────────
    def enterEvent(self, event):
        if self.isEnabled():
            self.setStyleSheet(
                "#MenuButtonWidget { background-color: rgba(255,255,255,0.2);"
                " border-radius: 6px; border-left: 3px solid transparent; }"
            )
            self.lbl.setStyleSheet(self._SS_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("")          # let QSS (active / default) take over
        self.lbl.setStyleSheet(self._SS_NORMAL)
        super().leaveEvent(event)

    # ────────────────────────────────────────────────────────────────────────
    def set_hotkey_visibility(self, visible):
        """Toggle between plain text and hotkey badge."""
        if visible and self.hotkey_char:
            self.lbl.setText(self.html_text)
        else:
            self.lbl.setText(self.plain_text)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def animateClick(self):
        self.clicked.emit()






class NavIndex:
    EMPTY = 0
    WELCOME = 1
    CATALOG = 2
    SETTINGS = 3
    TALLY = 4
    VAT = 5
    BRANCH = 6

class PageIndex:
    LOGIN = 0
    WELCOME = 1
    FULL_CATALOG = 2
    SYNC_TALLY = 3
    ROW_DATA = 4
    FINAL_DATA = 5
    SUPER_MASTER = 6
    REPORTS = 7
    PRICE_LIST = 8
    ON_ACCOUNT = 9
    GODOWN = 10
    SALES_CHAT = 11
    SUPP_PAYMENT = 12
    VAT_BALANCE = 13
    VAT_STOCK = 14
    CHEQUE_LIST = 15
    CALENDAR = 16
    LEDGER_ROW_DATA = 17
    SECURITY = 18

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
        self._dual_sync_in_progress = False  # Guard against double sync (item 6)
        
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

        # ── 12-hour automatic backup ──────────────────────────────────────────
        # Hybrid trigger: fires every 12h while the app is open AND on
        # login if the company hasn’t been backed up in the past 12 hours.
        # Backups are PER-COMPANY and saved to a user-chosen folder.
        _12H_MS = 12 * 60 * 60 * 1_000  # 12 hours in milliseconds
        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.setInterval(_12H_MS)
        self._auto_backup_timer.timeout.connect(self._run_auto_backup)
        # Persistent settings for backup: folder path + per-company last-run timestamps
        self._backup_settings = QSettings("TallySync", "AutoBackup")
        self._auto_backup_folder = self._backup_settings.value("backup_folder", "")
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_min_max)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)
        
        # Listen for taskbar toggling or screen size changes dynamically
        screen = QApplication.primaryScreen()
        if screen:
            screen.availableGeometryChanged.connect(self._on_screen_changed)
            
        self.setup_ui()

    def _on_screen_changed(self, rect):
        """Update window boundaries if user changes taskbar settings mid-session."""
        if not self.isMinimized():
            self.maximize_window()

    def showEvent(self, event):
        """Called once when the window is first shown — set a sensible minimum size
        based on the actual available screen geometry so the app never starts
        partially off-screen on small / low-resolution displays."""
        super().showEvent(event)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            # Minimum: 70% of available width × 65% of available height, floored
            # at a safe baseline (800 × 550) so tiny VM screens are also fine.
            min_w = max(800, int(avail.width() * 0.70))
            min_h = max(550, int(avail.height() * 0.65))
            self.setMinimumSize(min_w, min_h)

    def changeEvent(self, event):
        """Detect when the window moves to a different monitor and update the
        sidebar width to match the new screen's DPI."""
        from PyQt6.QtCore import QEvent as _QEvent
        super().changeEvent(event)
        if event.type() == _QEvent.Type.WindowStateChange:
            return
        # WindowScreenChange fires when the window is dragged to another monitor
        try:
            from PyQt6.QtGui import QScreen  # noqa: F401
            if event.type() == _QEvent.Type.ScreenChangeInternal:
                self._recalc_sidebar_width()
        except Exception:
            pass  # Non-critical — only affects multi-monitor DPI scenarios

    def _recalc_sidebar_width(self):
        """Recalculate and apply a DPI-aware sidebar width for the current screen."""
        if not hasattr(self, 'sidebar'):
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            dpi = screen.logicalDotsPerInch()
            new_width = max(170, int(185 * dpi / 96))
            new_width = min(new_width, 260)
            self.sidebar.setFixedWidth(new_width)

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
        

    def toggle_sidebar(self):
        """Collapse or expand the sidebar with a smooth animation.
        Animations are created once and reused to prevent memory leaks
        from repeated object creation on every toggle call.
        """
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QParallelAnimationGroup

        if not hasattr(self, '_sidebar_expanded'):
            self._sidebar_expanded = True

        is_expanded = self._sidebar_expanded

        # The width we want to expand back to
        target_expanded_width = getattr(self, '_sidebar_last_width', self.sidebar.width())
        if target_expanded_width < 100:
            target_expanded_width = 185

        start_w = self.sidebar.width()
        end_w = 40 if is_expanded else target_expanded_width

        if is_expanded:
            self._sidebar_last_width = start_w
            # Zero margins so the 36px icon fits inside the 40px rail without clipping
            self.sidebar.layout().setContentsMargins(0, 4, 0, 4)
            # Hide contents immediately so they don't squish during animation
            self.company_btn.hide()
            self.nav_stack.hide()
            self.lbl_logged_user.hide()
            self.logout_btn.hide()

        # Create animation objects once; reuse on subsequent calls
        if not hasattr(self, '_sidebar_anim_group'):
            self._sidebar_anim1 = QPropertyAnimation(self.sidebar, b"minimumWidth", self)
            self._sidebar_anim1.setDuration(250)
            self._sidebar_anim1.setEasingCurve(QEasingCurve.Type.InOutQuad)

            self._sidebar_anim2 = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
            self._sidebar_anim2.setDuration(250)
            self._sidebar_anim2.setEasingCurve(QEasingCurve.Type.InOutQuad)

            self._sidebar_anim_group = QParallelAnimationGroup(self)
            self._sidebar_anim_group.addAnimation(self._sidebar_anim1)
            self._sidebar_anim_group.addAnimation(self._sidebar_anim2)

        # Stop any running animation before reconfiguring
        if self._sidebar_anim_group.state() == QParallelAnimationGroup.State.Running:
            self._sidebar_anim_group.stop()

        self._sidebar_anim1.setStartValue(start_w)
        self._sidebar_anim1.setEndValue(end_w)
        self._sidebar_anim2.setStartValue(start_w)
        self._sidebar_anim2.setEndValue(end_w)

        # Always disconnect before connecting to prevent duplicate slot accumulation.
        # PyQt6 raises TypeError (not RuntimeError) when there are no connections yet.
        try:
            self._sidebar_anim_group.finished.disconnect()
        except (RuntimeError, TypeError):
            pass  # No connections yet on first call — safe to ignore

        if is_expanded:
            self._sidebar_anim_group.finished.connect(self._floating_toggle.show)
        else:
            self._floating_toggle.hide()
            def on_expanded():
                # Restore sidebar margins when expanding back to full width
                self.sidebar.layout().setContentsMargins(10, 0, 10, 10)
                if getattr(self, 'user_session', None):
                    self.company_btn.show()
                    self.lbl_logged_user.show()
                    self.logout_btn.show()
                self.nav_stack.show()
            self._sidebar_anim_group.finished.connect(on_expanded)

        self._sidebar_anim_group.start()
        self._sidebar_expanded = not is_expanded
    
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
        
        # --- DPI-aware sidebar width ---
        # Use the primary screen's logical DPI to scale the sidebar width.
        # At 96 dpi (100% scale) → 185px; at 120 dpi (125%) → ~231px, etc.
        screen = QApplication.primaryScreen()
        base_width = 185
        if screen:
            dpi = screen.logicalDotsPerInch()
            base_width = max(170, int(185 * dpi / 96))
            # Cap at 260 so it never eats too much space on 4K displays
            base_width = min(base_width, 260)
        self.sidebar.setFixedWidth(base_width)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 0, 10, 10)
        sidebar_layout.setSpacing(0)

        # Company Display Button (Acts as collapse toggle)
        self.company_btn = QPushButton("Company Name")
        self.company_btn.setObjectName("CompanyDisplayBtn")
        self.company_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.company_btn.clicked.connect(self.toggle_sidebar)
        self.company_btn.hide()
        sidebar_layout.addWidget(self.company_btn)

        # Item 2: Logged-in user label — added to sidebar near logout button
        self.lbl_logged_user = QLabel("")
        self.lbl_logged_user.setObjectName("LoggedUserLabel")
        self.lbl_logged_user.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_logged_user.hide()

        # Menu Navigation Stack — each page manages its own scrollbar
        self.nav_stack = QStackedWidget()
        self.nav_stack.setObjectName("NavStack")
        self.nav_stack.setStyleSheet("background: transparent;")
        
        # 0: Empty, 1: Main, 2: Catalog, 3: Settings, 4: Tally, 5: Vat, 6: Branch
        # NOTE: create_menu_widget wraps each page in its own QScrollArea so that
        # only the overflowing menu (e.g. Tally Internal) shows a scrollbar.
        self.init_nav_menus()
        
        # Add nav_stack directly — no outer scroll wrapper needed
        sidebar_layout.addWidget(self.nav_stack, 1)

        # User Row (Name only)
        sidebar_layout.addWidget(self.lbl_logged_user)

        # Logout Button (Full width)
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

        # ── Backup status toast (slim bar at the bottom, hidden by default) ──
        self._backup_toast = QWidget(self.content_container)
        self._backup_toast.setObjectName("BackupToast")
        self._backup_toast.setFixedHeight(28)
        toast_lay = QHBoxLayout(self._backup_toast)
        toast_lay.setContentsMargins(12, 0, 12, 0)
        toast_lay.setSpacing(8)
        self._toast_icon = QLabel("")
        self._toast_msg  = QLabel("")
        self._toast_icon.setFixedWidth(18)
        toast_lay.addWidget(self._toast_icon)
        toast_lay.addWidget(self._toast_msg, 1)
        self._backup_toast.setStyleSheet("""
            QWidget#BackupToast {
                background: #1e3a5f;
                border-top: 1px solid #2d5f9e;
            }
            QLabel { color: #cce0ff; font-size: 12px; }
        """)
        self._backup_toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._backup_toast.hide)
        # Spinner tick timer for animation
        self._spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_idx = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._backup_worker = None

        self.content_layout.addWidget(self._backup_toast)
        self.root_layout.addWidget(self.content_container, 1)

        # Floating Toggle Button (Visible only when sidebar is collapsed)
        # Created last to ensure it sits on top of all other widgets in z-order
        self._floating_toggle = QPushButton(self)
        self._floating_toggle.setIcon(get_icon("menu.svg"))
        from PyQt6.QtCore import QSize
        self._floating_toggle.setIconSize(QSize(20, 20))
        self._floating_toggle.setFixedSize(36, 36)
        self._floating_toggle.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border-radius: 6px;
                border: 1px solid transparent;
            } 
            QPushButton:hover { 
                background: rgba(255, 255, 255, 0.1); 
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
        """)
        self._floating_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._floating_toggle.move(2, 12)
        self._floating_toggle.clicked.connect(self.toggle_sidebar)
        self._floating_toggle.hide()

    def init_nav_menus(self):
        """Define menus with Tally-style mnemonics (&Letter)."""
        self.nav_stack.addWidget(QWidget()) # 0: Blank

        # Index 1: Main Menu
        # NOTE: Submenu trigger buttons (Catalog, Vat Working, Tally Internal) do NOT
        # have a perm_key. They open the submenu where individual items enforce their
        # own permissions. Layer 1b in _apply_permissions() hides the parent button
        # only when ALL its children are denied.
        m_main = self.create_menu_widget([
            ("📁 &Catalog", self.show_catalog_submenu, False),
            ("📊 &Vat Working", self.show_vat_submenu, False),
            ("⚙️ &Tally Internal", self.show_tally_internal_submenu, False),
            ("⚙️ &Settings", self.show_settings_submenu)
        ])
        m_main.setObjectName("MainMenuScroll")  # Slightly more breathing room for main nav
        self.nav_stack.addWidget(m_main)

        # Index 2: Catalog Menu (permission keys for access control)
        m_catalog = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🔄 S&ync Tally", self.on_sync_tally_clicked, False, None, "final_data.sync"),
            ("📑 Super &Master", self.handle_super_master, False, None, "tab.super_master"),
            ("✅ &Final Data", self.final_data, False, None, "tab.final_data"),
            ("📖 Full Catalo&g", self.show_full_catalog_page, False, None, "tab.catalog"),
            ("📈 Rep&orts", self.show_reports_page, False, None, "tab.reports"),
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
            ("⚙️ Tally &Port", self.handle_tally_port),
            ("🔑 Change &Password", self.handle_change_password, False, None, "settings.manage_users"),
            ("🔒 &Admin Panel", self.handle_admin_panel, False, None, "settings.manage_users"),
            ("📅 Ca&lendar", self.handle_calendar_mapping, False, None, "tab.calendar"),
            ("💾 &Backup Data", self.handle_export_data, False, None, "data.export"),
            ("📥 &Import Data", self.handle_import_data, False, None, "data.import"),
            ("🗓️ &Year End",    self.handle_year_end,   False, None, "settings.year_end"),
        ])
        self.nav_stack.addWidget(m_settings)

        # Index 4: Tally Internal
        m_tally = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("🔄 Sync &Ledger", self.on_sync_ledger_clicked, False, None, "ledger.sync"),
            ("🧪 Ledger &Rows", self.on_ledger_row_data_clicked, False, None, "tab.ledger"),
            ("💰 &On Account", lambda: self.main_stack.setCurrentIndex(PageIndex.ON_ACCOUNT), False, None, "tab.payment_list"),
            ("🧾 C&hq. List", self.handle_cheque_list, False, None, "tab.cheque_list"),
            ("🏠 &Godown List", lambda: self.main_stack.setCurrentIndex(PageIndex.GODOWN), False, None, "tab.godown"),
            ("📈 &Sales Chat", lambda: self.main_stack.setCurrentIndex(PageIndex.SALES_CHAT), False, None, "tab.sales_chat"),
            ("💸 Supp. Pa&yment", lambda: self.main_stack.setCurrentIndex(PageIndex.SUPP_PAYMENT), False, None, "tab.supp_payment"),
            ("🏷 Pri&ce List", lambda: self.main_stack.setCurrentIndex(PageIndex.PRICE_LIST), False, None, "tab.price_list"),
            ("📥 Pur &Import", self.handle_pur_import, False, None, "tab.pur_import"),
            ("📊 Cos&t Sheet", self.handle_int_cost_sheet, False, None, "tab.int_cost_sheet"),
            ("🏢 For &Branch", self.show_branch_submenu, False, None, "tab.for_branch")
        ])
        self.nav_stack.addWidget(m_tally)

        # Index 5: Vat Working
        m_vat = self.create_menu_widget([
            ("⬅️ &Back", self.go_back_to_main, True),
            ("💰 Ba&lance", lambda: self.main_stack.setCurrentIndex(PageIndex.VAT_BALANCE), False, None, "tab.vat_balance"),
            ("📦 Stoc&k", lambda: self.main_stack.setCurrentIndex(PageIndex.VAT_STOCK), False, None, "tab.vat_stock")
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
        """Run ledger-only sync — does NOT sync stock. For Stock+Ledger use Sync Tally."""
        if not self.current_company:
            return
        if not self._check_permission("ledger.sync", "Ledger Sync"):
            return
        if hasattr(self, '_ledger_worker') and self._ledger_worker and self._ledger_worker.isRunning():
            return

        company_path = getattr(self, 'current_company_path', None)
        self._ledger_service = TallyService()

        # Clean up any stale progress dialog from a previous run
        if hasattr(self, '_ledger_progress') and self._ledger_progress:
            try:
                self._ledger_progress.canceled.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._ledger_progress.deleteLater()

        self._ledger_progress = QProgressDialog(
            "Syncing Ledger from Tally...", "Cancel", 0, 0, self
        )
        self._ledger_progress.setWindowTitle("Ledger Sync")
        self._ledger_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._ledger_progress.setMinimumDuration(0)
        self._ledger_progress.canceled.connect(
            lambda: self._ledger_service.cancel() if self._ledger_service else None
        )
        self._ledger_progress.show()

        self._ledger_worker = _LedgerWorker(
            self.current_company, company_path, service=self._ledger_service
        )
        self._ledger_worker.finished.connect(self._on_ledger_sync_done)
        self._ledger_worker.start()

    def _run_full_sync(self):
        """Item 6: Run Tally Stock sync, then automatically chain Ledger sync.

        Guard against concurrent calls — if a sync is already running, do nothing.
        """
        if not self.current_company:
            return
        if self._dual_sync_in_progress:
            return
        if not self._check_permission("final_data.sync", "Tally Sync"):
            return
        # If either worker is already running, bail out
        tally_busy = hasattr(self, '_tally_worker') and self._tally_worker and self._tally_worker.isRunning()
        ledger_busy = hasattr(self, '_ledger_worker') and self._ledger_worker and self._ledger_worker.isRunning()
        if tally_busy or ledger_busy:
            return

        self._dual_sync_in_progress = True
        # Phase 1: run the existing stock sync.  When it finishes, _on_tally_sync_done
        # will call _run_ledger_sync_phase() to chain Phase 2.
        self.on_sync_tally_clicked(_chain_ledger=True)

    def _run_ledger_sync_phase(self):
        """Item 6: Phase 2 — run Ledger sync silently after stock sync completes."""
        if not self._check_permission("ledger.sync", "Ledger Sync"):
            self._dual_sync_in_progress = False
            return
        if hasattr(self, '_ledger_worker') and self._ledger_worker and self._ledger_worker.isRunning():
            self._dual_sync_in_progress = False
            return

        company_path = getattr(self, 'current_company_path', None)
        self._ledger_service = TallyService()
        self._ledger_worker = _LedgerWorker(self.current_company, company_path, service=self._ledger_service)
        self._ledger_worker.finished.connect(self._on_ledger_sync_done_dual)
        self._ledger_worker.start()

    def _on_ledger_sync_done_dual(self, row_count, error):
        """Item 6: Dual-sync ledger completion handler."""
        self._dual_sync_in_progress = False
        if error:
            QMessageBox.warning(self, "Ledger Sync Issue", f"Ledger sync: {error}")
        else:
            QMessageBox.information(
                self, "Full Sync Complete",
                f"✅ Stock + Ledger Sync Complete\n"
                f"Ledger entries loaded: {row_count}"
            )

    def _on_ledger_sync_done(self, row_count, error):
        """Handle ledger sync completion (standalone, runs on main thread)."""
        if hasattr(self, '_ledger_progress') and self._ledger_progress:
            try:
                self._ledger_progress.canceled.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._ledger_progress.close()

        if error == "cancelled":
            QMessageBox.information(self, "Cancelled", "Ledger sync was cancelled.\nExisting data is preserved.")
        elif not error and row_count > 0:
            QMessageBox.information(
                self, "Sync Complete",
                f"Ledger data synced successfully!\nLoaded {row_count} ledger entries."
            )
            # Refresh cheque list party names live (no restart needed)
            self._refresh_cheque_ledger_maps()
        else:
            msg = error if error else "No ledger data received from Tally."
            QMessageBox.warning(self, "Sync Issue", msg)

    def _refresh_cheque_ledger_maps(self):
        """Tell the Cheque List and Today Payment to re-read guid_to_name from the freshly-synced ledger DB."""
        if hasattr(self, 'cheque_list_page') and hasattr(self.cheque_list_page, 'refresh_ledger_maps'):
            try:
                self.cheque_list_page.refresh_ledger_maps()
            except Exception as e:
                logger.warning(f"[_refresh_cheque_ledger_maps] cheque: {e}")
        if hasattr(self, 'supp_payment_page') and hasattr(self.supp_payment_page, 'refresh_ledger_maps'):
            try:
                self.supp_payment_page.refresh_ledger_maps()
            except Exception as e:
                logger.warning(f"[_refresh_cheque_ledger_maps] today_payment: {e}")

    def on_main_stack_change(self, idx):
        """Handle main tab changes -> Auto-build Catalog only on relevant tabs."""
        # When leaving Super Master (6), re-map Final Data group assignments
        prev_idx = getattr(self, '_prev_stack_idx', -1)
        self._prev_stack_idx = idx
        if prev_idx == 6 and idx != 6 and hasattr(self, 'final_data_page'):
            updated = self.final_data_page.remap_from_super_master(
                getattr(self, 'current_company_path', '')
            )
            if updated > 0:
                logger.info(f"Re-mapped {updated} items after Super Master edit")
                # Invalidate catalog cache so it picks up new group assignments
                if hasattr(self, 'full_catalog_page') and hasattr(self.full_catalog_page, 'logic'):
                    self.full_catalog_page.logic.invalidate_cache()
                    self.full_catalog_page.logic._last_clean_check_time = None

        # ── Auto-image sync on Final Data (5), Catalog (2), Reports (7) tabs ─
        # Runs a fast fingerprint pre-check.  If the image folder is unchanged
        # the check returns in < 1ms (cache hit).  If changed, the lightweight
        # AutoImageSyncWorker updates catalog.Image_Path in the background and
        # emits image_sync_done when committed.  main_window catches that signal
        # and rebuilds the catalog if Catalog/Reports is currently visible.
        _fd = getattr(self, 'final_data_page', None)
        if idx in (2, 5, 7) and _fd and hasattr(_fd, 'check_and_sync_images'):
            _fd.check_and_sync_images()
            # On Final Data tab: also trigger a table refresh so ✅/❌ image status
            # reflects any DB changes made by a prior auto-sync (even if the user
            # navigated away while the sync was running).
            if idx == 5:
                _fd.refresh_table()
        # ─────────────────────────────────────────────────────────────────────

        # Silent catalog build ONLY on Catalog (2) and Reports (7) tabs.
        if idx in (2, 7) and hasattr(self, 'full_catalog_page'):
            session = self.user_session
            can_auto_build = (session is None) or session.can("catalog.build_auto")
            if can_auto_build:
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

    def _on_image_sync_done(self):
        """Called when AutoImageSyncWorker commits image changes to the DB.

        If the user is currently on Catalog (2) or Reports (7), rebuild the
        catalog immediately so the fresh Image_Path values are rendered.
        Debounce is reset so the build is never silently skipped.
        """
        current = self.main_stack.currentIndex()
        if current not in (2, 7):
            return  # User isn't viewing catalog — build will happen on next tab switch
        if not hasattr(self, 'full_catalog_page'):
            return
        session = self.user_session
        can_auto_build = (session is None) or session.can("catalog.build_auto")
        if not can_auto_build:
            return
        fcp = self.full_catalog_page
        if hasattr(fcp, 'logic'):
            fcp.logic.invalidate_cache()
        fcp._last_build_no_changes = False  # Bypass debounce
        # image_sync=True: if a catalog build is already running (race with the
        # tab-switch build that fired simultaneously), set _pending_image_sync so
        # _on_build_finished queues a follow-up build instead of silently dropping.
        fcp.build_catalog(silent=True, image_sync=True)
        logger.info(f"_on_image_sync_done: triggered catalog rebuild (tab={current})")

    def init_main_pages(self):
        """राइट साइड के सभी पेजों को लोड करना"""
        self.company_login = CompanyLoginUI()
        self.company_login.login_success_signal.connect(self.handle_login_success)
        
        self.row_data_page = RowDataUI()
        self.final_data_page = FinalDataUI()
        self.super_master_page = SuperMasterUI()
        self.reports_page = ReportsUI()
        # "Go to Final Data" from missing-image warning — navigate and auto-select affected rows
        def _go_to_final_data_with_selection(guids):
            self.main_stack.setCurrentIndex(PageIndex.FINAL_DATA)
            if guids and hasattr(self, 'final_data_page'):
                self.final_data_page.filter_to_guids(guids)
        self.reports_page.navigate_to_final_data.connect(_go_to_final_data_with_selection)
        self.payment_list_page = PaymentListUI()
        self.godown_page = GodownListUI("") # Will be initialized on login
        # Stack Pages
        self.full_catalog_page = FullCatalogUI()
        self.full_catalog_page.catalog_built.connect(self.on_catalog_built)
        # Item 3: "Let's Check" button on missing-image alert navigates to Final Data
        self.full_catalog_page.navigate_to_final_data.connect(
            lambda: self.main_stack.setCurrentIndex(PageIndex.FINAL_DATA)
        )
        # When auto-image sync commits, rebuild catalog if it's currently visible
        self.final_data_page.image_sync_done.connect(self._on_image_sync_done)
        
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
        self.supp_payment_page = SuppPaymentV2UI()
        self.main_stack.addWidget(self.supp_payment_page)  # 12
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

    # Shared teal-themed scrollbar style for all per-menu QScrollAreas
    _SIDEBAR_SCROLL_STYLE = """
        QScrollArea { background: transparent; border: none; }
        QScrollArea > QWidget > QScrollBar:vertical {
            background: rgba(255,255,255,0.08);
            width: 6px;
            border: none;
            border-radius: 3px;
            margin: 0px;
        }
        QScrollArea > QWidget > QScrollBar::handle:vertical {
            background: rgba(255,255,255,0.45);
            min-height: 24px;
            border-radius: 3px;
        }
        QScrollArea > QWidget > QScrollBar::handle:vertical:hover {
            background: rgba(255,255,255,0.70);
        }
        QScrollArea > QWidget > QScrollBar::add-line:vertical,
        QScrollArea > QWidget > QScrollBar::sub-line:vertical { height: 0; }
        QScrollArea > QWidget > QScrollBar::add-page:vertical,
        QScrollArea > QWidget > QScrollBar::sub-page:vertical { background: none; }
    """

    def create_menu_widget(self, buttons_data):
        """Build a menu page and wrap it in its own QScrollArea.

        Each page has an independent scroll area so the scrollbar appears
        ONLY on the specific menu that overflows the sidebar height (e.g.
        Tally Internal with 12 entries). Short menus (Main, Vat) never
        show a scrollbar because their content fits comfortably.
        """
        from PyQt6.QtWidgets import QScrollArea

        # Inner widget holds the actual buttons
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(5, 5, 5, 10)
        layout.setSpacing(4)

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
                sc.activated.connect(lambda w=inner, b=btn: self.safe_trigger_menu(w, b))

            layout.addWidget(btn)

        layout.addStretch()

        # Wrap the inner widget in a per-page QScrollArea.
        # ScrollBarAsNeeded means the scrollbar is invisible when all items
        # fit, and appears automatically only when they overflow.
        scroll = QScrollArea()
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(self._SIDEBAR_SCROLL_STYLE)
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.viewport().setAutoFillBackground(False)

        # Expose the inner widget so findChildren(MenuButtonWidget) still works
        # on the scroll area (Qt searches child widgets recursively).
        return scroll

    def safe_trigger_menu(self, parent_widget, btn):
        """Global trigger for main menu hotkeys (Context Sensitive)"""
        # Only trigger if the button is actually visible and enabled
        if not btn.isVisible() or not btn.isEnabled():
            return
            
        # Defense in depth: Verify permission one last time before simulating click
        perm_key = btn.property("permission_key")
        if perm_key and self.user_session and not self.user_session.can(perm_key):
            return
            
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

    def show_full_catalog_page(self):
        if not self._check_permission("tab.catalog", "Full Catalog"): return
        self.main_stack.setCurrentIndex(PageIndex.FULL_CATALOG)

    def show_reports_page(self):
        if not self._check_permission("tab.reports", "Reports"): return
        self.main_stack.setCurrentIndex(PageIndex.REPORTS)

    def go_back_to_main(self):
        self.nav_stack.setCurrentIndex(NavIndex.WELCOME)
        self.main_stack.setCurrentIndex(PageIndex.WELCOME)

    # --- Navigation Triggers ---
    def show_catalog_submenu(self): self.nav_stack.setCurrentIndex(NavIndex.CATALOG)
    def show_settings_submenu(self): self.nav_stack.setCurrentIndex(NavIndex.SETTINGS)
    def show_tally_internal_submenu(self): self.nav_stack.setCurrentIndex(NavIndex.TALLY)
    def show_vat_submenu(self): self.nav_stack.setCurrentIndex(NavIndex.VAT)
    def show_branch_submenu(self): self.nav_stack.setCurrentIndex(NavIndex.BRANCH)

    # --- Business Logic Methods (Login, Sync, CRM etc.) ---
    def handle_login_success(self, comp_name, company_path, user_session=None):
        try:
            self.current_company = comp_name
            self.current_company_path = company_path
            self.user_session = user_session
            set_company_context(comp_name)

            # Update UI with company name (no building logo or dropdown arrow)
            clean_name = re.sub(r'\s*\(\d{4}[-/].*?\)', '', comp_name)
            self.company_btn.setText(clean_name)
            self.company_btn.show()

            # Item 2: show logged-in username below company button
            if user_session and hasattr(user_session, 'username'):
                role = getattr(user_session, 'role_name', '')
                display = f"👤 {user_session.username}"
                if role:
                    display += f"\n({role})"
                self.lbl_logged_user.setText(display)
                self.lbl_logged_user.show()

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

            # Register Supp. Payment (Today Payment tab loads from DB)
            supp_widget = self.main_stack.widget(PageIndex.SUPP_PAYMENT)
            if supp_widget and hasattr(supp_widget, 'set_company_path'):
                session.register("Supp. Payment", supp_widget,
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
            
            # Create progress dialog for synchronous load
            progress = QProgressDialog("Loading company data...", None, 0, len(session._registrations), self)
            progress.setWindowTitle("Please Wait")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setAutoClose(True)
            progress.show()

            def update_progress(current, total, text):
                progress.setValue(current)
                progress.setLabelText(text)

            # Activate session — all pages get initialized
            result = session.activate(comp_name, company_path, progress_cb=update_progress)
            
            progress.setValue(len(session._registrations))
            
            if result["errors"]:
                error_names = [e[0] for e in result["errors"]]
                logger.warning(f"Session partial errors: {', '.join(error_names)}")
            
            self.session = session  # Store for later use
            
            logger.info(f"Session started: company='{comp_name}', path='{company_path}'")

            # Navigate to welcome
            self.nav_stack.setCurrentIndex(NavIndex.WELCOME) 
            self.main_stack.setCurrentIndex(PageIndex.WELCOME)
            
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

            # Propagate security manager to pages that need audit logging
            for page in [self.reports_page, self.full_catalog_page]:
                page._security_mgr = self._security_mgr

            self._perm_poll_timer.start()

            # ── Hybrid 24-hour auto-backup ──────────────────────────────────
            # 1. Check if this company was last backed up more than 24 h ago.
            #    If so, run a backup immediately (covers the ‘app was closed’ gap).
            # 2. (Re)start the repeating 24 h timer for as long as the app runs.
            if company_path and os.path.isdir(company_path):
                self._auto_backup_timer.start()   # restarts if already running
                logger.info("[AutoBackup] 24-hour backup timer started.")
                self._check_startup_backup(company_path)

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
        # Build set of denied parent tabs so children inherit denial
        # e.g. if tab.catalog is denied, catalog.build and catalog.print are also denied
        _TAB_TO_PREFIX = {
            "tab.final_data": "final_data.",
            "tab.super_master": "super_master.",
            "tab.catalog": "catalog.",
            "tab.reports": "reports.",
            "tab.cheque_list": "cheque_list.",
            "tab.calendar": "calendar.",
            "tab.godown": "godown.",
            "tab.ledger": "ledger.",
        }
        denied_prefixes = set()
        for tab_key, prefix in _TAB_TO_PREFIX.items():
            if not s.can(tab_key):
                denied_prefixes.add(prefix)
        
        for menu_widget in [self.nav_stack.widget(i) for i in range(self.nav_stack.count())]:
            if not menu_widget:
                continue
            for btn in menu_widget.findChildren(MenuButtonWidget):
                perm_key = btn.property("permission_key")
                if perm_key and isinstance(perm_key, str):
                    # Check if this subtab's parent tab is denied
                    parent_denied = any(perm_key.startswith(p) for p in denied_prefixes)
                    allowed = (not parent_denied) and s.can(perm_key)
                    btn.setEnabled(allowed)
                    if not allowed:
                        btn.setToolTip(f"🔒 Access denied — requires '{perm_key}' permission")
                    else:
                        btn.setToolTip("")
        
        # ── Layer 1b: Block parent menu buttons if ALL children are disabled ──
        _PARENT_TO_SUBMENU = {
            "Catalog": 2,
            "Settings": 3,
            "Tally Internal": 4,
            "Vat Working": 5,
        }
        
        main_menu = self.nav_stack.widget(1)
        if main_menu:
            for btn in main_menu.findChildren(MenuButtonWidget):
                btn_text = btn.lbl.text() if hasattr(btn, 'lbl') else btn.toolTip()
                for parent_name, submenu_idx in _PARENT_TO_SUBMENU.items():
                    if parent_name in btn_text:
                        submenu = self.nav_stack.widget(submenu_idx)
                        if submenu:
                            child_btns = [
                                b for b in submenu.findChildren(MenuButtonWidget)
                                if not b.property("is_back")
                            ]
                            all_disabled = child_btns and all(not b.isEnabled() for b in child_btns)
                            if all_disabled:
                                btn.setEnabled(False)
                                btn.setToolTip(f"🔒 No accessible items in {parent_name}")
                        break
        
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
            if hasattr(page, 'btn_reshuffle'):
                page.btn_reshuffle.setEnabled(s.can("catalog.reshuffle"))
            if hasattr(page, 'btn_add_page'):
                page.btn_add_page.setEnabled(s.can("catalog.page_management"))
            if hasattr(page, 'btn_remove_page'):
                page.btn_remove_page.setEnabled(s.can("catalog.page_management"))
            if hasattr(page, 'btn_check_empty'):
                page.btn_check_empty.setEnabled(s.can("catalog.page_management"))
        
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

        # Godown — editing, autocomplete search, and action buttons
        if hasattr(self, 'godown_page'):
            page = self.godown_page
            can_edit = s.can("godown.edit")
            page.apply_edit_mode(can_edit)

        # Vat Balance — editable Excel sheet
        vat_balance = self.main_stack.widget(13)
        if vat_balance and hasattr(vat_balance, 'apply_edit_mode'):
            vat_balance.apply_edit_mode(s.can("vat_balance.edit"))

        # Vat Stock — editable Excel sheet
        vat_stock = self.main_stack.widget(14)
        if vat_stock and hasattr(vat_stock, 'apply_edit_mode'):
            vat_stock.apply_edit_mode(s.can("vat_stock.edit"))

        # Sales Chat — editable Excel sheet
        sales_chat = self.main_stack.widget(11)
        if sales_chat and hasattr(sales_chat, 'apply_edit_mode'):
            sales_chat.apply_edit_mode(s.can("sales_chat.edit"))

        # Supplier Payment
        supp_payment = self.main_stack.widget(PageIndex.SUPP_PAYMENT)
        if supp_payment and hasattr(supp_payment, 'apply_edit_mode'):
            supp_payment.apply_edit_mode(s.can("supp_payment.edit"))


        # Price List — editable Excel sheet
        price_list = self.main_stack.widget(8)
        if price_list and hasattr(price_list, 'apply_edit_mode'):
            price_list.apply_edit_mode(s.can("price_list.edit"))

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

    def handle_tally_port(self):
        """Let the current RDP user choose their own Tally port.

        Each Windows / RDP user session has a separate Tally instance
        that may listen on a different port.  The choice is stored per-user
        in the Windows Registry via QSettings so it survives restarts.
        """
        from PyQt6.QtWidgets import QInputDialog
        from src.services.tally_sync import get_tally_port, set_tally_port

        current_port = get_tally_port()
        port, ok = QInputDialog.getInt(
            self,
            "Tally Port",
            "Enter the Tally port for your session\n"
            "(Each RDP user should set their own port):",
            value=current_port,
            min=1,
            max=65535,
        )
        if ok:
            set_tally_port(port)
            QMessageBox.information(
                self,
                "Tally Port Updated",
                f"Tally port set to {port} for your Windows account.\n"
                f"This applies only to your RDP session."
            )
            # Audit log
            if self._security_mgr and self.user_session:
                self._security_mgr.log_action(
                    self.user_session,
                    "tally_port_change",
                    module="settings",
                    detail=f"Tally port changed from {current_port} to {port}"
                )

    def on_sync_tally_clicked(self, _chain_ledger=True):
        """Sync stock from Tally, then automatically chain Ledger sync.

        Always chains to ledger after stock so Sync Tally = Stock + Ledger.
        Pass _chain_ledger=False only if you explicitly want stock-only (internal use).
        """
        if not self.current_company: return
        if not self._check_permission("final_data.sync", "Tally Sync"): return

        # Prevent concurrent syncs
        if hasattr(self, '_tally_worker') and self._tally_worker and self._tally_worker.isRunning():
            return

        logger.info(f"Tally sync started")

        # Reset user-cancel flag so a previous cancel doesn't bleed into this run
        self._tally_sync_user_cancelled = False
        # Pass through the chain-ledger flag for dual-sync mode
        self._chain_ledger_after_sync = _chain_ledger

        # Create a shared TallyService so we can cancel it
        self._tally_service = TallyService()

        # Clean up any leftover progress dialog from a previous sync to prevent
        # stale canceled signals from firing on the new sync's service.
        if hasattr(self, '_tally_progress') and self._tally_progress:
            try:
                self._tally_progress.canceled.disconnect(self._on_tally_cancel)
            except (TypeError, RuntimeError):
                pass
            self._tally_progress.deleteLater()

        self._tally_progress = QProgressDialog("Syncing Tally Data...", "Cancel", 0, 0, self)
        self._tally_progress.setWindowTitle("Please Wait")
        self._tally_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._tally_progress.setMinimumDuration(0)
        self._tally_progress.canceled.connect(self._on_tally_cancel)
        self._tally_progress.show()

        # Run in background thread

        self._tally_worker = _TallyWorker(
            self._tally_service,
            self.current_company,
            self.current_company_path
        )
        self._tally_worker.finished.connect(self._on_tally_sync_done)
        self._tally_worker.start()

    def _on_tally_cancel(self):
        """Handle cancel button click — signal the TallyService to stop."""
        logger.info("Tally sync cancelled by user")
        # Set flag immediately on main thread — this is the authoritative cancel
        # signal even if the background thread finishes before service.cancel() takes effect.
        self._tally_sync_user_cancelled = True
        if hasattr(self, '_tally_service') and self._tally_service:
            self._tally_service.cancel()

    def _on_tally_sync_done(self, df, error):
        """Handle Tally sync completion (runs on main thread)."""
        if hasattr(self, '_tally_progress') and self._tally_progress:
            # IMPORTANT: disconnect canceled BEFORE close(). QProgressDialog in
            # indeterminate mode (max=0) emits canceled() when close() is called,
            # which would fire _on_tally_cancel() mid-execution and incorrectly
            # poison _tally_sync_user_cancelled for every successful sync.
            try:
                self._tally_progress.canceled.disconnect(self._on_tally_cancel)
            except (TypeError, RuntimeError):
                pass
            self._tally_progress.close()

        if error == "cancelled":
            self._dual_sync_in_progress = False
            QMessageBox.information(self, "Cancelled", "Tally sync was cancelled.\nExisting data is preserved.")
            return

        # Layer 2: user clicked Cancel but Phase 1 finished just before the
        # InterruptedError could propagate (race).  Honour the user's intent.
        if getattr(self, '_tally_sync_user_cancelled', False):
            logger.info("_on_tally_sync_done: user cancelled — suppressing Phase 2")
            self._dual_sync_in_progress = False
            QMessageBox.information(self, "Cancelled", "Tally sync was cancelled.\nExisting data is preserved.")
            return

        # Layer 3: service flag set but error string didn't come back as 'cancelled'
        # (e.g. pyodbc error raced with cancel flag before our guard could catch it).
        if hasattr(self, '_tally_service') and self._tally_service and self._tally_service.cancelled:
            logger.info("_on_tally_sync_done: service was cancelled — suppressing Phase 2")
            self._dual_sync_in_progress = False
            QMessageBox.information(self, "Cancelled", "Tally sync was cancelled.\nExisting data is preserved.")
            return

        if not error and df is not None and not df.empty:
            self.row_data_page.load_data(self.current_company_path)

            # Chain: Final Data sync (async) → catalog build → success message
            row_count = len(df)
            logger.info(f"Tally sync received: {row_count} rows")
            def _after_sync():
                self._pending_after_sync_cb = None
                self.final_data_page.sync_complete.disconnect(_after_sync)
                # Also disconnect cancel handler if still connected
                try:
                    self.final_data_page.sync_cancelled.disconnect(_after_sync_cancelled)
                except (TypeError, RuntimeError):
                    pass
                # Trigger a silent catalog build only if user has auto-build permission
                session = self.user_session
                can_auto_build = (session is None) or session.can("catalog.build_auto")
                if hasattr(self, 'full_catalog_page') and can_auto_build:
                    if hasattr(self.full_catalog_page, 'logic'):
                        self.full_catalog_page.logic.invalidate_cache()

                    # Connect a one-shot callback to catalog_built so the success
                    # popup fires AFTER the engine has written pages to report_data.
                    # This prevents the race where the user opens Reports before the
                    # build worker has finished updating the pending lists.
                    # Guard: if user runs sync twice quickly, disconnect any
                    # previous _after_catalog_built that is still pending.
                    # Each sync creates a new closure, so we track it on self.
                    if hasattr(self, '_pending_sync_catalog_cb') and self._pending_sync_catalog_cb:
                        try:
                            self.full_catalog_page.catalog_built.disconnect(self._pending_sync_catalog_cb)
                        except (TypeError, RuntimeError):
                            pass
                        self._pending_sync_catalog_cb = None

                    def _after_catalog_built():
                        self._pending_sync_catalog_cb = None
                        try:
                            self.full_catalog_page.catalog_built.disconnect(_after_catalog_built)
                        except (TypeError, RuntimeError):
                            pass
                        # Item 6: if this was a dual sync, chain ledger instead of showing popup here
                        if getattr(self, '_chain_ledger_after_sync', False):
                            self._chain_ledger_after_sync = False
                            self._run_ledger_sync_phase()
                        else:
                            QMessageBox.information(self, "Sync Complete",
                                f"Data Synced Successfully!\nLoaded {row_count} rows.\n\nClick OK to close.")
                        # L-6: Audit log for Tally sync
                        if self._security_mgr and self.user_session:
                            self._security_mgr.log_action(self.user_session, "tally_sync",
                                module="final_data", detail=f"Synced {row_count} rows")

                    self._pending_sync_catalog_cb = _after_catalog_built
                    self.full_catalog_page.catalog_built.connect(_after_catalog_built)
                    # Reset debounce so a post-sync build is never silently skipped
                    self.full_catalog_page._last_build_no_changes = False
                    self.full_catalog_page.build_catalog(silent=True)
                else:
                    # No auto-build permission — show popup immediately, then chain ledger if needed
                    if not getattr(self, '_chain_ledger_after_sync', False):
                        QMessageBox.information(self, "Sync Complete",
                            f"Data Synced Successfully!\nLoaded {row_count} rows.\n\nClick OK to close.")
                    # L-6: Audit log for Tally sync
                    if self._security_mgr and self.user_session:
                        self._security_mgr.log_action(self.user_session, "tally_sync",
                            module="final_data", detail=f"Synced {row_count} rows")
                    if getattr(self, '_chain_ledger_after_sync', False):
                        self._chain_ledger_after_sync = False
                        self._run_ledger_sync_phase()

            def _after_sync_cancelled():
                self._pending_after_sync_cancelled_cb = None
                # Disconnect both handlers so they don't fire again
                try:
                    self.final_data_page.sync_cancelled.disconnect(_after_sync_cancelled)
                except (TypeError, RuntimeError):
                    pass
                try:
                    self.final_data_page.sync_complete.disconnect(_after_sync)
                except (TypeError, RuntimeError):
                    pass
                logger.info("Final Data sync cancelled — skipping success popup")
                QMessageBox.information(self, "Cancelled", "Sync was cancelled.\nExisting data is preserved.")

            if hasattr(self, 'final_data_page'):
                # Disconnect any stale handlers from a previous sync run before
                # connecting new ones — otherwise cancelled signals accumulate and
                # fire multiple "Tally sync cancelled" popups on unrelated actions.
                if hasattr(self, '_pending_after_sync_cb') and self._pending_after_sync_cb:
                    try:
                        self.final_data_page.sync_complete.disconnect(self._pending_after_sync_cb)
                    except (TypeError, RuntimeError):
                        pass
                if hasattr(self, '_pending_after_sync_cancelled_cb') and self._pending_after_sync_cancelled_cb:
                    try:
                        self.final_data_page.sync_cancelled.disconnect(self._pending_after_sync_cancelled_cb)
                    except (TypeError, RuntimeError):
                        pass

                self._pending_after_sync_cb = _after_sync
                self._pending_after_sync_cancelled_cb = _after_sync_cancelled
                self.final_data_page.sync_complete.connect(_after_sync)
                self.final_data_page.sync_cancelled.connect(_after_sync_cancelled)
                self.final_data_page.load_and_sync_data(self.current_company, self.current_company_path)
            else:
                QMessageBox.information(self, "Sync Complete", f"Data Synced Successfully!\nLoaded {row_count} rows.")
        else:
            self._dual_sync_in_progress = False
            msg = error if error else "No data received from Tally. Check connection."
            logger.warning(f"Tally sync issue: {msg}")
            QMessageBox.warning(self, "Sync Issue", f"{msg}\n\nClick OK to close.")

    def on_row_data_clicked(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.row_data_page.load_data(self.current_company_path)
            self.main_stack.setCurrentIndex(PageIndex.ROW_DATA)

    def on_ledger_row_data_clicked(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.ledger_row_data_page.load_data(self.current_company_path)
            self.main_stack.setCurrentIndex(PageIndex.LEDGER_ROW_DATA)

    def final_data(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.main_stack.setCurrentIndex(PageIndex.FINAL_DATA)
            # Only refresh the table view, don't re-sync from scratch
            self.final_data_page.refresh_table()

    def handle_super_master(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            self.super_master_page.load_super_master_data(self.current_company_path)
            self.main_stack.setCurrentIndex(PageIndex.SUPER_MASTER)

    def handle_catalog_price_list(self):
        if not self._check_permission("tab.cat_price_list", "Catalog Price List"): return
        dlg = CatalogPriceListUI(self)
        can_edit = self.user_session.can("cat_price_list.edit") if self.user_session else True
        dlg.apply_edit_mode(can_edit)
        dlg.exec()

    def handle_int_cost_sheet(self):
        if not self._check_permission("tab.int_cost_sheet", "Internal Cost Sheet"): return
        dlg = IntCostSheetUI(self)
        can_edit = self.user_session.can("int_cost_sheet.edit") if self.user_session else True
        # IntCostSheetUI has no apply_edit_mode — lock directly
        if not can_edit:
            dlg.table.setEditTriggers(dlg.table.EditTrigger.NoEditTriggers)
            dlg.save_btn.setEnabled(False)
            dlg.save_btn.setToolTip("🔒 Editing disabled — display only")
            dlg.calc_btn.setEnabled(False)
            dlg.calc_btn.setToolTip("🔒 Editing disabled — display only")
        dlg.exec()

    def handle_pur_import(self):
        if not self._check_permission("tab.pur_import", "Purchase Import"): return
        dlg = PurImportUI(self)
        can_import = self.user_session.can("pur_import.import") if self.user_session else True
        dlg.apply_edit_mode(can_import)
        dlg.exec()
    def handle_security(self): 
        if self.current_company and hasattr(self, 'current_company_path'):
            self.security_page.refresh_data()
            self.main_stack.setCurrentIndex(PageIndex.SECURITY)
    
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
    
    def handle_admin_panel(self):
        """Open the Admin Panel for managing companies (Super Admin / Admin)."""
        if not self.user_session or not self.user_session.is_admin:
            QMessageBox.warning(self, "Access Denied", "Only administrators can access the Admin Panel.")
            return
            
        data_path = os.path.dirname(self.current_company_path) if hasattr(self, 'current_company_path') else ""
        if not data_path:
            return
            
        from src.ui.admin_panel import AdminPanelDialog
        dlg = AdminPanelDialog(self._security_mgr, data_path, parent=self)
        dlg.exec()
        if dlg.data_changed:
            self.back_to_login_screen()

    def handle_cheque_list(self):
        self.main_stack.setCurrentIndex(PageIndex.CHEQUE_LIST)
    
    def handle_calendar_mapping(self):
        self.main_stack.setCurrentIndex(PageIndex.CALENDAR)
    
    def handle_manage_users(self):
        if self.current_company and hasattr(self, 'current_company_path'):
            UserManagerDialog(self.current_company, self.current_company_path, parent=self).exec()

    def _check_startup_backup(self, company_path: str):
        """Run a backup immediately on login if the last backup is >12 hours old.

        Reads the per-data-path last-backup timestamp from QSettings and triggers
        _run_auto_backup if needed.  Uses a short QTimer.singleShot delay so the
        main window has fully painted before the (potentially slow) backup starts.
        All companies sharing the same data path share one backup cycle per 12h.
        """
        from datetime import datetime, timezone
        _12H = 12 * 60 * 60  # seconds

        # Key is based on the DATA PATH folder (parent of company), not the company.
        # This ensures all companies in the same data path share one backup per 24h.
        data_path = os.path.dirname(os.path.normpath(company_path))
        data_key  = os.path.basename(data_path) if os.path.basename(data_path) else "DataRoot"
        ts_key    = f"last_backup/{data_key}"
        last_ts   = self._backup_settings.value(ts_key, 0, type=float)
        now_ts    = datetime.now(timezone.utc).timestamp()

        elapsed = now_ts - last_ts
        if elapsed >= _12H:
            logger.info(
                f"[AutoBackup] Last backup for data path '{data_key}' was "
                f"{elapsed/3600:.1f}h ago — running startup backup."
            )
            # Delay 3 s so the UI is fully ready before the backup thread blocks disk I/O
            from PyQt6.QtCore import QTimer as _QT
            _QT.singleShot(3_000, self._run_auto_backup)
        else:
            logger.info(
                f"[AutoBackup] Data path '{data_key}' backed up "
                f"{elapsed/3600:.1f}h ago — no startup backup needed."
            )

    # ─── BACKUP WORKER ────────────────────────────────────────────────────────

    class _BackupWorker(QThread):
        """Background thread that runs export_data_path without blocking the UI."""
        finished = pyqtSignal(bool, str)   # (success, message)

        def __init__(self, data_path, output_file, company_key, lock_name, parent=None):
            super().__init__(parent)
            self.data_path   = data_path
            self.output_file = output_file
            self.company_key = company_key
            self.lock_name   = lock_name

        def run(self):
            from src.logic.db_manager import get_db_manager
            from src.logic.data_transfer import export_data_path
            db = get_db_manager()
            # Acquire the SQL Server app-lock (non-blocking: skip if another user holds it)
            if not db.acquire_app_lock(self.lock_name, timeout_ms=0):
                self.finished.emit(False, "skipped:locked")
                return
            try:
                success, msg = export_data_path(self.data_path, self.output_file)
                self.finished.emit(success, msg)
            except Exception as exc:
                self.finished.emit(False, str(exc))
            finally:
                db.release_app_lock(self.lock_name)

    # ─── TOAST HELPERS ────────────────────────────────────────────────────────

    def _tick_spinner(self):
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_frames)
        self._toast_icon.setText(self._spinner_frames[self._spinner_idx])

    def _show_backup_toast(self, message: str, running: bool = True):
        """Show the slim backup toast bar with an optional spinner."""
        self._toast_timer.stop()
        if running:
            self._spinner_timer.start()
            self._toast_icon.setText(self._spinner_frames[0])
        else:
            self._spinner_timer.stop()
        self._toast_msg.setText(message)
        self._backup_toast.show()

    def _hide_backup_toast_after(self, ms: int = 5000):
        """Hide the toast after a delay."""
        self._spinner_timer.stop()
        self._toast_timer.start(ms)

    def _on_backup_done(self, success: bool, msg: str):
        """Slot called when the background backup thread finishes."""
        from datetime import datetime, timezone
        # _pending_backup_key is the data path key set by _run_auto_backup
        data_key = getattr(self, '_pending_backup_key', '')

        if msg == "skipped:locked":
            logger.info(f"[AutoBackup] Skipped — another user is already backing up.")
            self._show_backup_toast("⏭ Auto-backup skipped (another user is running it)", running=False)
        elif success:
            logger.info(f"[AutoBackup] Backup complete for data path '{data_key}'.")
            self._show_backup_toast("✅  Auto-backup complete", running=False)
            # Record timestamp so next login (any company in this data path) sees it as done
            ts_key = f"last_backup/{data_key}"
            self._backup_settings.setValue(ts_key, datetime.now(timezone.utc).timestamp())
            # Audit log
            if self._security_mgr and self.user_session:
                self._security_mgr.log_action(
                    self.user_session, "auto_backup", module="system",
                    detail=f"Auto-backup: {getattr(self, '_pending_backup_file', '')}"
                )
            # Prune: keep only the 14 most recent backups for this data path
            try:
                folder = getattr(self, '_pending_backup_dir', '')
                prefix = f"JK_AutoBackup_{data_key}_"
                backups = sorted(
                    f for f in os.listdir(folder)
                    if f.startswith(prefix) and f.endswith(".jkbackup")
                )
                for old in backups[:max(0, len(backups) - 14)]:
                    try:
                        os.remove(os.path.join(folder, old))
                        logger.info(f"[AutoBackup] Pruned: {old}")
                    except OSError as e:
                        logger.warning(f"[AutoBackup] Could not delete {old}: {e}")
            except Exception as e:
                logger.warning(f"[AutoBackup] Pruning failed: {e}")
        else:
            logger.error(f"[AutoBackup] Backup FAILED: {msg}")
            self._show_backup_toast(f"❌  Auto-backup failed: {msg[:60]}", running=False)

        self._hide_backup_toast_after(5000)
        self._backup_worker = None

    # ─── AUTO-BACKUP TRIGGER ─────────────────────────────────────────────────

    def _run_auto_backup(self):
        """Fire the per-company automatic backup on a background thread.

        Guards:
          1. Same-day file check  — if today's .jkbackup already exists in the
             backup folder, skip entirely (works cross-user via shared FS).
          2. SQL Server app-lock  — prevents two instances from starting backup
             simultaneously even if the file check races.
          3. QThread worker       — backup never blocks the UI thread.
          4. Toast bar            — non-intrusive progress indicator at the bottom.
        """
        if getattr(self, '_backup_worker', None) is not None:
            logger.info("[AutoBackup] Backup already in progress — skipping.")
            return

        company_path = getattr(self, 'current_company_path', '')
        if not company_path or not os.path.isdir(company_path):
            logger.warning("[AutoBackup] Skipped — no company loaded.")
            return

        # Load backup folder — SQL first (company-specific, shared across users),
        # fallback to local config.json for old installs.
        backup_folder = ""
        try:
            data_path = os.path.dirname(os.path.normpath(company_path))
            from src.logic.security_manager import SecurityManager
            _sm = SecurityManager(data_path)
            backup_folder = _sm.get_backup_path(company_path)
        except Exception:
            pass

        if not backup_folder:
            # Fallback: local config.json (backwards compat for installs before SQL backup_path)
            from src.utils.path_utils import get_app_dir
            config_file = os.path.join(get_app_dir(), "config.json")
            if os.path.exists(config_file):
                try:
                    import json as _json
                    with open(config_file, 'r', encoding='utf-8') as f:
                        backup_folder = _json.load(f).get("backup_path", "").strip()
                except Exception:
                    pass

        if not backup_folder or not os.path.isdir(backup_folder):
            logger.warning("[AutoBackup] Skipped — backup folder not set or missing.")
            return

        from datetime import datetime
        # Derive keys from the DATA PATH (parent of company), not the company itself.
        # This ensures all companies in the same data path share one backup per 12h.
        data_path        = os.path.dirname(os.path.normpath(company_path))
        data_key         = os.path.basename(data_path) if os.path.basename(data_path) else "DataRoot"
        # Include AM/PM so we allow 2 backups per day (12-hour schedule)
        today_str        = datetime.now().strftime("%Y-%m-%d_%p")
        data_backup_dir  = os.path.join(backup_folder, data_key)

        try:
            os.makedirs(data_backup_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"[AutoBackup] Could not create backup folder: {e}")
            return

        # Guard 1: same half-day file check (cross-user, cross-company)
        prefix = f"JK_AutoBackup_{data_key}_{today_str}"
        existing = [f for f in os.listdir(data_backup_dir)
                    if f.startswith(prefix) and f.endswith(".jkbackup")]
        if existing:
            logger.info(f"[AutoBackup] This half-day's backup already exists for '{data_key}': {existing[0]} — skipping.")
            return

        timestamp   = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_file = os.path.join(data_backup_dir,
                                   f"JK_AutoBackup_{data_key}_{timestamp}.jkbackup")
        lock_name   = f"JK_AutoBackup_{data_key}"

        # Stash for use in the done-callback
        self._pending_backup_key  = data_key
        self._pending_backup_file = os.path.basename(output_file)
        self._pending_backup_dir  = data_backup_dir

        logger.info(f"[AutoBackup] Launching background backup: {output_file}")
        self._show_backup_toast(f"🔄  Auto-backup running for {data_key}…")

        self._backup_worker = self._BackupWorker(
            data_path, output_file, data_key, lock_name, parent=self
        )
        self._backup_worker.finished.connect(self._on_backup_done)
        self._backup_worker.start()


    def handle_export_data(self):
        """Backup data — prompts for Full Path or Company-only backup (RBAC-protected)."""
        if not self._check_permission("data.export", "Backup Data"):
            return
        if not hasattr(self, 'current_company_path') or not self.current_company_path:
            QMessageBox.warning(self, "No Company", "No company is currently loaded.")
            return

        company_path = self.current_company_path
        data_path = os.path.dirname(company_path)
        company_folder = os.path.basename(company_path)

        if not data_path or not os.path.isdir(data_path):
            QMessageBox.warning(self, "No Data Path", "Data path not found.")
            return

        # ── Backup mode picker ────────────────────────────────────────────────
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QPushButton, QFrame, QFileDialog
        )

        mode_dlg = QDialog(self)
        mode_dlg.setWindowTitle("Backup — Choose What to Back Up")
        mode_dlg.setFixedWidth(460)
        mode_dlg.setModal(True)
        mode_lay = QVBoxLayout(mode_dlg)
        mode_lay.setContentsMargins(20, 20, 20, 16)
        mode_lay.setSpacing(12)

        hdr = QLabel("💾  What would you like to back up?")
        hdr.setStyleSheet("font-size: 15px; font-weight: 700; color: #0f172a;")
        mode_lay.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        mode_lay.addWidget(sep)

        _choice = {"mode": None}

        def _make_card(icon, title, description, color, key):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: #ffffff; border: 1.5px solid #e2e8f0; "
                f"border-radius: 8px; }}"
                f"QFrame:hover {{ border-color: {color}; }}"
            )
            from PyQt6.QtWidgets import QHBoxLayout
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(4)
            t_lbl = QLabel(f"{icon}  <b>{title}</b>")
            t_lbl.setStyleSheet(f"font-size: 13px; color: {color};")
            cl.addWidget(t_lbl)
            d_lbl = QLabel(description)
            d_lbl.setWordWrap(True)
            d_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
            cl.addWidget(d_lbl)
            btn = QPushButton(f"  {title}  ")
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; color: #ffffff; border: none; "
                f"border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 14px; }}"
            )
            bl = QHBoxLayout()
            bl.addStretch()
            bl.addWidget(btn)
            cl.addLayout(bl)
            def _pick(_, k=key):
                _choice["mode"] = k
                mode_dlg.accept()
            btn.clicked.connect(_pick)
            return card

        mode_lay.addWidget(_make_card(
            "🏢", "This Company Only",
            f"Back up only '{company_folder}'. Faster — ideal as a daily safety "
            "snapshot before making catalog or payment changes.",
            "#059669", "company"
        ))
        mode_lay.addWidget(_make_card(
            "💾", "Full Data Path",
            "Back up ALL companies in this data path. Use this for machine migration "
            "or full disaster recovery.",
            "#1d4ed8", "full"
        ))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #374151; border: 1px solid #e2e8f0; "
            "border-radius: 5px; font-size: 11px; padding: 0 14px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        cancel_btn.clicked.connect(mode_dlg.reject)
        mode_lay.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

        if mode_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode = _choice["mode"]

        # ── File save dialog ──────────────────────────────────────────────────
        import datetime
        date_str = datetime.date.today().strftime("%Y%m%d")
        if mode == "company":
            default_name = f"{company_folder}_{date_str}.jkbackup"
            title = f"Save Company Backup — {company_folder}"
        else:
            default_name = f"JK_FullPath_{date_str}.jkbackup"
            title = "Save Full Data Path Backup"

        output_file, _ = QFileDialog.getSaveFileName(
            self, title,
            os.path.join(os.path.expanduser("~/Desktop"), default_name),
            "JK Backup Files (*.jkbackup)"
        )
        if not output_file:
            return

        # ── Progress dialog ───────────────────────────────────────────────────
        self._export_progress = QProgressDialog("Starting backup...", "Cancel", 0, 100, self)
        self._export_progress.setWindowTitle(
            "Backing Up Company" if mode == "company" else "Backing Up Full Path"
        )
        self._export_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress.setMinimumDuration(0)
        self._export_progress.show()

        if mode == "company":
            self._export_worker = _CompanyExportWorker(company_path, output_file)
        else:
            self._export_worker = _ExportWorker(data_path, output_file)

        def update_progress(text, current, total):
            self._export_progress.setLabelText(text)
            self._export_progress.setMaximum(max(total, 1))
            self._export_progress.setValue(current)

        def on_cancel():
            self._export_worker.is_cancelled = True

        def on_finished(success, msg):
            self._export_progress.close()
            if success:
                QMessageBox.information(self, "Backup Complete", msg)
                if self._security_mgr and self.user_session:
                    self._security_mgr.log_action(
                        self.user_session, "data_export",
                        module="settings",
                        detail=f"[{mode}] Exported to: {os.path.basename(output_file)}"
                    )
            else:
                if msg != "Export cancelled by user":
                    QMessageBox.critical(self, "Backup Failed", msg)
                else:
                    QMessageBox.information(self, "Cancelled", msg)

        self._export_worker.progress.connect(update_progress)
        self._export_progress.canceled.connect(on_cancel)
        self._export_worker.finished.connect(on_finished)
        self._export_worker.start()


    # ─── SELECTIVE RESTORE DIALOG ─────────────────────────────────────────────

    def _show_selective_restore_dialog(self, backup_file, manifest):
        """Show the SelectiveRestoreDialog and run the selective restore worker if confirmed."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
            QGroupBox, QCheckBox, QListWidget, QListWidgetItem,
            QPushButton, QFrame, QScrollArea, QWidget
        )

        data_path = os.path.dirname(self.current_company_path) if \
            hasattr(self, 'current_company_path') and self.current_company_path else ""

        dlg = QDialog(self)
        dlg.setWindowTitle("Selective Restore — Choose What to Restore")
        dlg.setFixedWidth(520)
        dlg.setModal(True)

        root = QVBoxLayout(dlg)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 16)

        # ── Header ────────────────────────────────────────────────────────────
        title_lbl = QLabel("🎯  Selective Restore")
        title_lbl.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #0f172a;"
        )
        root.addWidget(title_lbl)

        sub_lbl = QLabel(f"File: <b>{os.path.basename(backup_file)}</b>")
        sub_lbl.setStyleSheet("color: #475569; font-size: 13px;")
        root.addWidget(sub_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        root.addWidget(sep)

        # ── Company picker ────────────────────────────────────────────────────
        companies = [c["folder_name"] for c in manifest.get("company_databases", [])]
        if not companies:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Companies",
                "No company databases found in this backup file.")
            dlg.reject()
            return

        co_box = QGroupBox("Company to Restore Into")
        co_box.setStyleSheet(
            "QGroupBox { font-weight: 600; font-size: 12px; color: #1e293b; "
            "border: 1px solid #e2e8f0; border-radius: 6px; margin-top: 8px; padding-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        co_lay = QVBoxLayout(co_box)
        co_combo = QComboBox()
        co_combo.addItems(companies)
        # Pre-select current company if it's in the backup
        current_folder = os.path.basename(self.current_company_path) if \
            hasattr(self, 'current_company_path') and self.current_company_path else ""
        if current_folder in companies:
            co_combo.setCurrentIndex(companies.index(current_folder))
        co_lay.addWidget(co_combo)
        root.addWidget(co_box)

        # ── Module selection ──────────────────────────────────────────────────
        mod_box = QGroupBox("Modules to Restore")
        mod_box.setStyleSheet(co_box.styleSheet())
        mod_lay = QVBoxLayout(mod_box)
        mod_lay.setSpacing(6)

        chk_catalog = QCheckBox("📁  Catalog, Final Data, CRM & Godown List")
        chk_catalog.setStyleSheet("font-size: 12px; color: #0f172a; padding: 4px;")
        chk_catalog.setChecked(True)
        mod_lay.addWidget(chk_catalog)

        # Supplier Payment + Cheque List + Ledger + sheet sub-selection
        chk_supp = QCheckBox("💳  Supplier Payments, Cheque List & Ledgers")
        chk_supp.setStyleSheet("font-size: 12px; color: #0f172a; padding: 4px;")
        mod_lay.addWidget(chk_supp)

        # Sheet sub-selection list (shown when chk_supp is checked)
        sheet_frame = QFrame()
        sheet_frame.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 5px; }"
        )
        sheet_lay = QVBoxLayout(sheet_frame)
        sheet_lay.setContentsMargins(8, 6, 8, 6)
        sheet_lay.setSpacing(4)

        sheet_hint = QLabel("Select specific sheets, or leave blank to restore all:")
        sheet_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        sheet_lay.addWidget(sheet_hint)

        sheet_list = QListWidget()
        sheet_list.setFixedHeight(120)
        sheet_list.setStyleSheet(
            "QListWidget { background: #ffffff; border: 1px solid #e2e8f0; "
            "border-radius: 4px; font-size: 12px; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:selected { background: #eff6ff; color: #1d4ed8; }"
        )
        sheet_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        sheet_lay.addWidget(sheet_list)

        all_sheets_lbl = QLabel("(no sheets checked = restore ALL sheets)")
        all_sheets_lbl.setStyleSheet("color: #94a3b8; font-size: 10px; font-style: italic;")
        sheet_lay.addWidget(all_sheets_lbl)

        sheet_frame.setVisible(False)
        mod_lay.addWidget(sheet_frame)

        def _update_warning():
            msgs = []
            if not any(cb.isChecked() for cb in (chk_catalog, chk_supp)):
                msgs.append("⚠  Select at least one module group.")
            
            self._warn_lbl.setText("\n".join(msgs))
            self._warn_lbl.setVisible(bool(msgs))

        def _load_sheet_keys():
            """Load distinct sheet_key values from the manifest (or live DB fallback) into sheet_list."""
            sheet_list.clear()
            folder = co_combo.currentText()
            if not folder or not data_path:
                sheet_list.addItem("(no company selected)")
                sheet_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
                return

            # Try to read payment_sheets from the manifest first (accurate to the backup)
            company_meta = next((c for c in manifest.get("company_databases", []) 
                               if c["folder_name"] == folder), None)
            
            if company_meta and "payment_sheets" in company_meta:
                sheets = company_meta["payment_sheets"]
                if sheets:
                    for key in sheets:
                        item = QListWidgetItem(str(key))
                        sheet_list.addItem(item)
                    all_sheets_lbl.setText("(Leave blank to restore all sheets)")
                else:
                    sheet_list.addItem("(no payment sheets found in backup)")
                    sheet_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
                    all_sheets_lbl.setText("(Leave blank to restore all empty sheets)")
                return

            # Fallback for older backups: we cannot read the sheets from the .bak file
            # without restoring it first. So we just tell the user we will restore everything.
            sheet_list.addItem("✓ All Payment Sheets will be restored")
            sheet_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            all_sheets_lbl.setText("(Older backup: All sheets will be restored)")

        def _toggle_sheet_frame(checked):
            sheet_frame.setVisible(checked)
            if checked:
                _load_sheet_keys()

        # Reload sheet list when the company selection changes (only if panel is visible)
        co_combo.currentIndexChanged.connect(
            lambda _: _load_sheet_keys() if sheet_frame.isVisible() else None
        )

        chk_supp.toggled.connect(_toggle_sheet_frame)
        chk_catalog.toggled.connect(lambda _: _update_warning())
        chk_supp.toggled.connect(lambda _: _update_warning())
        root.addWidget(mod_box)

        # ── Warning label ─────────────────────────────────────────────────────
        self._warn_lbl = QLabel()
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setStyleSheet(
            "color: #b45309; font-size: 11px; background: #fffbeb; "
            "border: 1px solid #fcd34d; border-radius: 5px; padding: 6px 10px;"
        )
        self._warn_lbl.setVisible(False)
        root.addWidget(self._warn_lbl)

        _update_warning()


        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #374151; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding: 0 18px; font-size: 12px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        btn_cancel.clicked.connect(dlg.reject)

        btn_restore = QPushButton("🎯  Restore Selected")
        btn_restore.setFixedHeight(34)
        btn_restore.setDefault(True)
        btn_restore.setStyleSheet(
            "QPushButton { background: #2563eb; color: #ffffff; border: none; "
            "border-radius: 6px; padding: 0 18px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:pressed { background: #1e40af; }"
        )

        def _on_restore():
            if not any(cb.isChecked() for cb in (chk_catalog, chk_supp)):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(dlg, "Nothing Selected",
                    "Please select at least one module group to restore.")
                return
            dlg.accept()

        btn_restore.clicked.connect(_on_restore)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_restore)
        root.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # ── Build modules parameter ───────────────────────────────────────────
        company_folder = co_combo.currentText()
        modules = []
        if chk_catalog.isChecked():
            modules.append("catalog_bundle")
            modules.append("godown")
        if chk_supp.isChecked():
            modules.append("cheque_list")
            # Sheet filtering: if user selected specific items in the list, use them
            selected_sheets = [
                sheet_list.item(i).text()
                for i in range(sheet_list.count())
                if sheet_list.item(i).isSelected()
                   and sheet_list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable
            ]
            if selected_sheets:
                # Pass as dict to trigger per-sheet filtering
                modules_param = {k: (selected_sheets if k == "supp_payment" else [])
                                 for k in (modules + ["supp_payment"])}
                modules = modules_param
            else:
                modules.append("supp_payment")

        # ── Confirm ───────────────────────────────────────────────────────────
        mod_labels = []
        _modules_keys = modules if isinstance(modules, list) else modules.keys()
        if "catalog_bundle" in _modules_keys:
            mod_labels.append("Catalog, Final Data & Godown List")
        if "supp_payment" in _modules_keys:
            mod_labels.append("Supplier Payments, Cheque List & Ledgers")

        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Confirm Selective Restore",
            f"Company:  {company_folder}\n\n"
            f"Modules:  {', '.join(mod_labels)}\n\n"
            f"⚠  The selected tables in the live database will be "
            f"replaced with data from the backup.\n\n"
            f"Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # ── Run worker ────────────────────────────────────────────────────────
        self._sel_import_progress = QProgressDialog(
            "Starting selective restore...", "Cancel", 0, 10, self
        )
        self._sel_import_progress.setWindowTitle("Selective Restore")
        self._sel_import_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._sel_import_progress.setMinimumDuration(0)
        self._sel_import_progress.show()

        self._sel_import_worker = _SelectiveImportWorker(
            backup_file, data_path, company_folder, modules
        )

        def _update_sel_progress(text, current, total):
            self._sel_import_progress.setLabelText(text)
            self._sel_import_progress.setMaximum(max(total, 1))
            self._sel_import_progress.setValue(current)

        def _cancel_sel():
            self._sel_import_worker.is_cancelled = True

        def _on_sel_finished(success, msg):
            self._sel_import_progress.close()
            if success:
                # ── Refresh affected UI pages so changes appear immediately ──
                _modules_restored = modules if isinstance(modules, list) else list(modules.keys())
                _company_path = getattr(self, 'current_company_path', None)

                if "supp_payment" in _modules_restored:
                    if hasattr(self, 'supp_payment_page') and _company_path:
                        try:
                            self.supp_payment_page.set_company_path(_company_path)
                        except Exception as _e:
                            pass  # non-fatal

                if "godown" in _modules_restored:
                    if hasattr(self, 'godown_page') and hasattr(self.godown_page, 'load_data_from_db'):
                        try:
                            self.godown_page.load_data_from_db()
                        except Exception:
                            pass

                if "cheque_list" in _modules_restored:
                    if hasattr(self, 'cheque_list_page') and hasattr(self.cheque_list_page, 'set_company_path') and _company_path:
                        try:
                            self.cheque_list_page.set_company_path(_company_path)
                        except Exception:
                            pass

                QMessageBox.information(self, "Selective Restore Complete",
                    f"{msg}\n\nChanges are live immediately — no restart required.")
                if self._security_mgr and self.user_session:
                    self._security_mgr.log_action(
                        self.user_session, "selective_restore",
                        module="settings",
                        detail=f"Restored {mod_labels} for '{company_folder}' "
                               f"from {os.path.basename(backup_file)}"
                    )
            else:
                cancelled_msgs = ("Selective restore cancelled", "cancelled")
                if any(m in msg for m in cancelled_msgs):
                    QMessageBox.information(self, "Cancelled", msg)
                else:
                    QMessageBox.critical(self, "Selective Restore Failed",
                        f"{msg}\n\n✅ Your live data was NOT modified.")


        self._sel_import_worker.progress.connect(_update_sel_progress)
        self._sel_import_progress.canceled.connect(_cancel_sel)
        self._sel_import_worker.finished.connect(_on_sel_finished)
        self._sel_import_worker.start()

    def handle_import_data(self):
        """Import data from a .jkbackup file (RBAC-protected).

        Presents two paths:
          • Full System Restore  — original behaviour (RESTORE DATABASE into new path)
          • Selective Restore    — Temp DB merge; only chosen modules are overwritten
        """
        if not self._check_permission("data.import", "Import Data"):
            return

        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        backup_file, _ = QFileDialog.getOpenFileName(
            self, "Select Backup File",
            os.path.expanduser("~/Desktop"),
            "JK Backup Files (*.jkbackup)"
        )
        if not backup_file:
            return

        # ── Read manifest (fast — no SQL involved) ────────────────────────────
        from src.logic.data_transfer import list_companies_in_backup
        manifest, err = list_companies_in_backup(backup_file)
        if not manifest:
            QMessageBox.critical(self, "Invalid Backup File",
                f"Cannot read backup:\n{err}")
            return

        # ── Ask user which import mode they want ──────────────────────────────
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
        mode_dlg = QDialog(self)
        mode_dlg.setWindowTitle("Import — Choose Restore Mode")
        mode_dlg.setFixedWidth(480)
        mode_dlg.setModal(True)
        mode_lay = QVBoxLayout(mode_dlg)
        mode_lay.setContentsMargins(20, 20, 20, 16)
        mode_lay.setSpacing(12)

        hdr = QLabel("📥  How would you like to import?")
        hdr.setStyleSheet("font-size: 15px; font-weight: 700; color: #0f172a;")
        mode_lay.addWidget(hdr)

        file_lbl = QLabel(f"Backup: <b>{os.path.basename(backup_file)}</b>")
        file_lbl.setStyleSheet("color: #475569; font-size: 12px;")
        mode_lay.addWidget(file_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        mode_lay.addWidget(sep)

        _mode_result = {"choice": None}

        def _make_mode_card(icon, title, description, color, key):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: #ffffff; border: 1.5px solid #e2e8f0; "
                f"border-radius: 8px; }}"
                f"QFrame:hover {{ border-color: {color}; }}"
            )
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(4)
            t_lbl = QLabel(f"{icon}  <b>{title}</b>")
            t_lbl.setStyleSheet(f"font-size: 13px; color: {color};")
            cl.addWidget(t_lbl)
            d_lbl = QLabel(description)
            d_lbl.setWordWrap(True)
            d_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
            cl.addWidget(d_lbl)

            btn = QPushButton(f"  {title}  ")
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; color: #ffffff; border: none; "
                f"border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 14px; }}"
                f"QPushButton:hover {{ opacity: 0.9; }}"
            )
            bl = QHBoxLayout()
            bl.addStretch()
            bl.addWidget(btn)
            cl.addLayout(bl)

            def _pick(_, k=key):
                _mode_result["choice"] = k
                mode_dlg.accept()
            btn.clicked.connect(_pick)
            return card

        mode_lay.addWidget(_make_mode_card(
            "💾", "Full System Restore",
            "Restore EVERYTHING into a new folder. Use this when moving to a new PC "
            "or recovering from a total data loss. Existing data in the target folder "
            "will be completely replaced.",
            "#1d4ed8", "full"
        ))
        mode_lay.addWidget(_make_mode_card(
            "🎯", "Selective Restore",
            "Choose which modules to restore (Catalog Bundle or Supplier Payment) "
            "into the current company. Only the selected tables are overwritten — "
            "all other live data remains untouched.",
            "#059669", "selective"
        ))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #374151; border: 1px solid #e2e8f0; "
            "border-radius: 5px; font-size: 11px; padding: 0 14px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        cancel_btn.clicked.connect(mode_dlg.reject)
        mode_lay.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

        if mode_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        choice = _mode_result["choice"]

        # ── FULL SYSTEM RESTORE (original path) ───────────────────────────────
        if choice == "full":
            target_path = QFileDialog.getExistingDirectory(
                self, "Select Destination Folder for Full Restore"
            )
            if not target_path:
                return

            reply = QMessageBox.question(
                self, "Confirm Full Restore",
                f"Import data from:\n  {os.path.basename(backup_file)}\n\n"
                f"Into folder:\n  {target_path}\n\n"
                f"⚠  All existing data in that folder will be replaced.\n\n"
                f"Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            self._import_progress = QProgressDialog(
                "Starting import...", "Cancel", 0, 100, self
            )
            self._import_progress.setWindowTitle("Full System Restore")
            self._import_progress.setWindowModality(Qt.WindowModality.WindowModal)
            self._import_progress.setMinimumDuration(0)
            self._import_progress.show()

            self._import_worker = _ImportWorker(backup_file, target_path)

            def update_progress(text, current, total):
                self._import_progress.setLabelText(text)
                self._import_progress.setMaximum(total)
                self._import_progress.setValue(current)

            def on_cancel():
                self._import_worker.is_cancelled = True

            def on_finished(success, msg):
                self._import_progress.close()
                if success:
                    QMessageBox.information(self, "Import Complete",
                        f"{msg}\n\nPlease switch company or restart to use imported data.")
                    if self._security_mgr and self.user_session:
                        self._security_mgr.log_action(
                            self.user_session, "data_import",
                            module="settings",
                            detail=f"Full restore from: {os.path.basename(backup_file)} to {target_path}"
                        )
                else:
                    if msg != "Import cancelled by user":
                        QMessageBox.critical(self, "Import Failed", msg)
                    else:
                        QMessageBox.information(self, "Cancelled", msg)

            self._import_worker.progress.connect(update_progress)
            self._import_progress.canceled.connect(on_cancel)
            self._import_worker.finished.connect(on_finished)
            self._import_worker.start()

        # ── SELECTIVE RESTORE (Temp DB merge) ─────────────────────────────────
        elif choice == "selective":
            if not hasattr(self, 'current_company_path') or not self.current_company_path:
                QMessageBox.warning(self, "No Company Loaded",
                    "Please open a company first before using Selective Restore.\n"
                    "Selective restore works within your current data path.")
                return
            self._show_selective_restore_dialog(backup_file, manifest)



    def handle_year_end(self):
        """Open the Year End wizard (permission: settings.year_end).

        Creates a new company at the same location as the current one,
        copies all data, then applies Option A cheque processing.
        If the user clicks 'Switch to New Company', the app returns to the
        company-selection screen so they can open the new company.
        """
        if not self._check_permission("settings.year_end", "Year End"):
            return
        if not hasattr(self, 'current_company_path') or not self.current_company_path:
            QMessageBox.warning(self, "No Company", "No company is currently loaded.")
            return

        from src.ui.year_end_dialog import YearEndDialog
        dlg = YearEndDialog(self.current_company_path, parent=self)
        # Bug 4 fix: pass new_path so the company list can pre-select it
        dlg.switch_company.connect(self.back_to_login_screen)
        dlg.exec()

    def back_to_login_screen(self, preselect_path=""):
        """Return to the company selection screen.

        Args:
            preselect_path: If given, the company list will scroll to and
                highlight the item whose path matches this value.  Used after
                Year End so the user can immediately open the new company.
        """
        logger.info(f"User logged out")
        set_company_context("")
        self.user_session = None  # Clear session
        self._timeout_timer.stop()  # Stop session timeout
        self._perm_poll_timer.stop()  # Stop permission polling
        self._security_mgr = None
        self.set_active_menu_btn(None) # Clear highlighting
        self.company_btn.hide()
        self.lbl_logged_user.hide()   # Item 2: clear user badge on logout
        self.lbl_logged_user.setText("")
        # Re-enable all menu buttons (clear permission locks from previous session)
        for menu_widget in [self.nav_stack.widget(i) for i in range(self.nav_stack.count())]:
            if not menu_widget:
                continue
            for btn in menu_widget.findChildren(MenuButtonWidget):
                btn.setEnabled(True)
                btn.setToolTip("")

        self.nav_stack.setCurrentIndex(NavIndex.EMPTY)
        self.main_stack.setCurrentIndex(PageIndex.LOGIN)
        self.company_login.show_list()

        # Bug 4 fix: pre-select the new company in the list after Year End
        if preselect_path:
            self._preselect_company(preselect_path)

    def _preselect_company(self, target_path):
        """Scroll to and select the company list item that matches target_path."""
        try:
            lst = self.company_login.list
            target_norm = os.path.normpath(target_path).lower()
            for i in range(lst.count()):
                item = lst.item(i)
                if not item:
                    continue
                item_path = item.data(Qt.ItemDataRole.UserRole + 1)
                if item_path and os.path.normpath(str(item_path)).lower() == target_norm:
                    lst.setCurrentItem(item)
                    lst.scrollToItem(item)
                    break
        except Exception as e:
            logger.debug(f"_preselect_company failed: {e}")


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
            self.main_stack.setCurrentIndex(PageIndex.LOGIN)
            self.company_login.stack.setCurrentIndex(PageIndex.WELCOME)

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

    # ─── CLOSE EVENT — wait for any running backup ────────────────────────────

    def closeEvent(self, event):
        """If a backup is currently running, wait for it to finish before closing.
        
        Rule (per AGENTS.md user preference):
          - If a backup is already running → ignore the close, show a message,
            connect to the worker's finished signal to close automatically when done.
          - If no backup is running → close immediately (no new backup triggered here).
        
        The backup-on-12h-rule is handled at startup / periodic timer, not on close.
        """
        worker = getattr(self, '_backup_worker', None)
        if worker is not None and worker.isRunning():
            # Ignore the close request — tell user we're waiting
            event.ignore()
            self._show_backup_toast("🔄  Waiting for backup to finish before closing…", running=True)

            # Connect a one-shot slot that will close the app once backup is done
            def _close_when_done(success: bool, msg: str):
                # Disconnect to avoid being called again if worker somehow re-emits
                try:
                    worker.finished.disconnect(_close_when_done)
                except (TypeError, RuntimeError):
                    pass
                logger.info(f"[AutoBackup] Backup finished (success={success}) — closing app now.")
                # Use QApplication.quit() so the event loop exits cleanly
                from PyQt6.QtWidgets import QApplication
                QApplication.quit()

            try:
                worker.finished.connect(_close_when_done)
            except Exception:
                # If connection fails for any reason, close immediately to avoid being stuck
                event.accept()
        else:
            # No backup running — close normally
            event.accept()
