# =============================================================================
# supp_payment/__init__.py — Package entry point (thin orchestrator)
# All business logic lives in the sub-modules below.
# =============================================================================
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QPushButton,
    QInputDialog, QMessageBox, QMenu,
)
from PyQt6.QtCore import Qt, QObject, QEvent


from .shared          import _BTN_PRIMARY, _styled_get_text, _styled_question, _styled_info
from .today_payment   import TodayPaymentTabV2
from .bank_ac         import RecordTab
from .anil_hisab      import AnilHisabTab
from .bonus_team      import TeamListTab, BonusTab
from .insurance       import InsuranceTab
from .payment_sheet   import PaymentSheet
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
class _TabNavFilter(QObject):
    """Application-level event filter that intercepts Ctrl+PageUp/Down for the
    supp_payment tab widget.  Installed on QApplication so it fires BEFORE any
    child widget (including QTableWidget) can consume the key event.
    Only acts when a descendant of the owning SuppPaymentV2UI has focus.
    """
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = owner   # SuppPaymentV2UI instance

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            # Use bitwise AND (&) because other modifiers (like NumLock) might be active
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                key = event.key()
                if key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                    # Only intercept when focus is inside our widget
                    from PyQt6.QtWidgets import QApplication
                    fw = QApplication.focusWidget()
                    if fw is not None:
                        w = fw
                        while w is not None:
                            if w is self._owner:
                                # Focus is inside SuppPaymentV2UI — handle it
                                if event.type() == QEvent.Type.KeyPress:
                                    if key == Qt.Key.Key_PageDown:
                                        self._owner._next_tab()
                                    else:
                                        self._owner._prev_tab()
                                return True   # swallow — don't pass to child
                            w = w.parentWidget()
        return False   # pass everything else through unchanged


# ===========================================================================
class SuppPaymentV2UI(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SuppPaymentMain")
        self._can_edit = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("PaymentTabContainer")
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: #e2e8f0; color: #475569;
                padding: 7px 18px; border-radius: 6px 6px 0 0;
                margin-right: 2px; font-size: 10pt;
            }
            QTabBar::tab:selected {
                background: #059669; color: white; font-weight: bold;
            }
            QTabBar::tab:hover:!selected { background: #cbd5e1; }
        """)

        self.add_button = QPushButton("+")
        self.add_button.setObjectName("AddNewSheetBtn")
        self.add_button.setFixedSize(36, 30)
        self.add_button.setStyleSheet(_BTN_PRIMARY)
        self.add_button.clicked.connect(self.add_new_sheet)
        self.tabs.setCornerWidget(self.add_button, Qt.Corner.BottomLeftCorner)

        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)

        # Core tabs
        self._today_payment_tab = TodayPaymentTabV2()
        self.tabs.addTab(self._today_payment_tab, "Today Payment")

        self._record_tab = RecordTab()
        self.tabs.addTab(self._record_tab, "Bank A/C")

        self._anil_tab = AnilHisabTab()
        self.tabs.addTab(self._anil_tab, "Anil Dai Hisab")

        self._team_tab  = TeamListTab()
        self._bonus_tab = BonusTab()
        self._ins_tab   = InsuranceTab()
        self.tabs.addTab(self._team_tab,  "Team-List")
        self.tabs.addTab(self._bonus_tab, "Bonus Details")
        self.tabs.addTab(self._ins_tab,   "Insurance")

        self.tabs.setCurrentIndex(0)
        layout.addWidget(self.tabs)

        # App-level event filter: the ONLY reliable way to catch Ctrl+PageUp/Down
        # before QTableWidget's own keyPressEvent accepts and swallows them.
        from PyQt6.QtWidgets import QApplication
        self._tab_key_filter = _TabNavFilter(self)
        QApplication.instance().installEventFilter(self._tab_key_filter)

    def closeEvent(self, event):
        """Remove the app-level filter when the widget is destroyed."""
        from PyQt6.QtWidgets import QApplication
        try:
            QApplication.instance().removeEventFilter(self._tab_key_filter)
        except Exception:
            pass
        super().closeEvent(event)

    def _next_tab(self):
        idx = self.tabs.currentIndex() + 1
        if idx >= self.tabs.count():
            idx = 0
        self.tabs.setCurrentIndex(idx)

    def _prev_tab(self):
        idx = self.tabs.currentIndex() - 1
        if idx < 0:
            idx = self.tabs.count() - 1
        self.tabs.setCurrentIndex(idx)


    def set_company_path(self, path: str):
        self._company_path = path  # remember for newly-added sheets
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, 'set_company_path'):
                w.set_company_path(path)

    def refresh_ledger_maps(self):
        """Propagate ledger refresh down to TodayPaymentTabV2 after a Tally sync."""
        if hasattr(self, '_today_payment_tab'):
            try:
                self._today_payment_tab.refresh_ledger_maps()
            except Exception as e:
                logger.error(f"[SuppPaymentV2UI] refresh_ledger_maps error: {e}")

    def add_new_sheet(self):
        if not self._can_edit:
            return
        blank = {
            "tab": f"Sheet {self.tabs.count() + 1}",
            "columns": [(chr(65 + i), 100) for i in range(10)],
            "sections": {0: ("Data", "#059669")},
        }
        sheet = PaymentSheet(blank)
        # Give the new sheet DB access using the already-loaded company path
        if getattr(self, '_company_path', None):
            sheet.set_company_path(self._company_path)
        self.tabs.addTab(sheet, blank["tab"])
        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    # Number of fixed core tabs that must never be deleted or renamed
    _CORE_TAB_COUNT = 6  # Today Payment, Bank A/C, Anil Dai Hisab, Team-List, Bonus, Insurance

    def rename_tab(self, index: int):
        if not self._can_edit or index == -1 or index < self._CORE_TAB_COUNT:
            return
        old = self.tabs.tabText(index)
        new, ok = _styled_get_text(self, "Rename", "New name:", text=old)
        if ok and new.strip():
            self.tabs.setTabText(index, new.strip())

    def show_tab_menu(self, point):
        idx = self.tabs.tabBar().tabAt(point)
        if idx == -1:
            return
        menu = QMenu(self)
        # Only non-core (user-added) tabs can be renamed or deleted
        is_core = idx < self._CORE_TAB_COUNT
        ra = menu.addAction("\u270e  Rename Sheet")
        ra.setEnabled(not is_core)
        da = menu.addAction("\u2715  Delete Sheet")
        da.setEnabled(not is_core)
        act = menu.exec(self.tabs.tabBar().mapToGlobal(point))
        if act == ra and not is_core:
            self.rename_tab(idx)
        elif act == da and not is_core:
            if self.tabs.count() > self._CORE_TAB_COUNT:
                tab_name = self.tabs.tabText(idx)
                if (_styled_question(
                        self, "Delete",
                        f"Delete '{tab_name}'? All data in this sheet will be lost.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        == QMessageBox.StandardButton.Yes):
                    # Clean up DB data before removing the widget
                    w = self.tabs.widget(idx)
                    if isinstance(w, PaymentSheet):
                        w.delete_from_db()
                    self.tabs.removeTab(idx)
            else:
                _styled_info(self, "Info", "No user-created sheets to delete.")

    def apply_edit_mode(self, can_edit: bool):
        self._can_edit = can_edit
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "apply_edit_mode"):
                w.apply_edit_mode(can_edit)
        self.add_button.setEnabled(can_edit)
        self.tabs.setMovable(can_edit)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu if can_edit
            else Qt.ContextMenuPolicy.NoContextMenu)


__all__ = ["SuppPaymentV2UI"]
