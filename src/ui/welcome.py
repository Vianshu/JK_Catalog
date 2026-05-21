from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class WelcomeUI(QWidget):
    """Card-based welcome dashboard with enterprise-grade layout."""

    def __init__(self):
        super().__init__()
        self.setObjectName("WelcomePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # ── Welcome Card ──
        welcome_card = QFrame()
        welcome_card.setObjectName("WelcomeCard")
        wc_layout = QVBoxLayout(welcome_card)
        wc_layout.setContentsMargins(28, 24, 28, 20)
        wc_layout.setSpacing(4)

        welcome_sub = QLabel("Welcome to")
        welcome_sub.setObjectName("WelcomeSubtitle")
        wc_layout.addWidget(welcome_sub)

        welcome_title = QLabel("JK Catalog Multi")
        welcome_title.setObjectName("WelcomeTitle")
        wc_layout.addWidget(welcome_title)

        tagline = QLabel("Manage your enterprise resources efficiently.")
        tagline.setObjectName("WelcomeTagline")
        wc_layout.addWidget(tagline)

        layout.addWidget(welcome_card)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #E5E7EB; border: none;")
        layout.addWidget(sep)

        # ── Cards Row ──
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        # ── Tips Card ──
        tips_card = QFrame()
        tips_card.setObjectName("TipsCard")
        tc_layout = QVBoxLayout(tips_card)
        tc_layout.setContentsMargins(20, 16, 20, 16)
        tc_layout.setSpacing(8)

        tips_title = QLabel("Quick Tips")
        tips_title.setObjectName("TipsTitle")
        tc_layout.addWidget(tips_title)

        tips = [
            "Select a company and navigate to Catalog \u2192 Sync Tally to get started.",
            "Use the left menu to switch between modules.",
            "Hold Alt to reveal keyboard shortcuts on menu items.",
        ]
        for tip in tips:
            tip_lbl = QLabel(f"\u00b7  {tip}")
            tip_lbl.setObjectName("TipItem")
            tip_lbl.setWordWrap(True)
            tc_layout.addWidget(tip_lbl)

        tc_layout.addStretch()
        cards_row.addWidget(tips_card, 1)

        # ── Keyboard Shortcuts Card ──
        shortcuts_card = QFrame()
        shortcuts_card.setObjectName("ShortcutsCard")
        sc_layout = QVBoxLayout(shortcuts_card)
        sc_layout.setContentsMargins(20, 16, 20, 16)
        sc_layout.setSpacing(8)

        sc_title = QLabel("Keyboard Shortcuts")
        sc_title.setObjectName("ShortcutsTitle")
        sc_layout.addWidget(sc_title)

        shortcuts_grid = QGridLayout()
        shortcuts_grid.setSpacing(8)
        shortcuts_grid.setColumnMinimumWidth(0, 70)

        shortcuts = [
            ("Alt", "Reveal menu hotkeys"),
            ("Ctrl+M", "Minimize window"),
            ("Ctrl+Q", "Quit application"),
            ("Enter", "Select / confirm"),
            ("Esc", "Go back"),
        ]
        for i, (key, desc) in enumerate(shortcuts):
            key_lbl = QLabel(key)
            key_lbl.setObjectName("ShortcutKey")
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key_lbl.setFixedWidth(64)
            shortcuts_grid.addWidget(key_lbl, i, 0)

            desc_lbl = QLabel(desc)
            desc_lbl.setObjectName("ShortcutDesc")
            shortcuts_grid.addWidget(desc_lbl, i, 1)

        sc_layout.addLayout(shortcuts_grid)
        sc_layout.addStretch()
        cards_row.addWidget(shortcuts_card, 1)

        layout.addLayout(cards_row)
        layout.addStretch()
