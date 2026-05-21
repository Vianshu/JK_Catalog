from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class WelcomeUI(QWidget):
    """Card-based welcome dashboard matching the Stitch reference design."""

    def __init__(self):
        super().__init__()
        self.setObjectName("WelcomePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # ── Welcome Card ──
        welcome_card = QFrame()
        welcome_card.setObjectName("WelcomeCard")
        wc_layout = QVBoxLayout(welcome_card)
        wc_layout.setContentsMargins(40, 35, 40, 35)
        wc_layout.setSpacing(8)

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

        # ── Tips Card ──
        tips_card = QFrame()
        tips_card.setObjectName("TipsCard")
        tc_layout = QVBoxLayout(tips_card)
        tc_layout.setContentsMargins(24, 20, 24, 20)
        tc_layout.setSpacing(10)

        tips_title = QLabel("💡 Quick Tips")
        tips_title.setObjectName("TipsTitle")
        tc_layout.addWidget(tips_title)

        tips = [
            "Press Alt to reveal keyboard shortcuts on the sidebar menu.",
            "Use Ctrl+M to minimize / Ctrl+Q to quit the application.",
            "Select a company and navigate to Catalog → Sync Tally to get started.",
        ]
        for tip in tips:
            tip_lbl = QLabel(f"  •  {tip}")
            tip_lbl.setObjectName("TipItem")
            tip_lbl.setWordWrap(True)
            tc_layout.addWidget(tip_lbl)

        layout.addWidget(tips_card)
        layout.addStretch()
