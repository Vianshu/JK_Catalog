from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QLabel,
    QSpinBox, QComboBox, QCheckBox, QScrollArea, QGroupBox,
    QGridLayout, QProgressBar, QWidget, QLineEdit, QColorDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from Config.Layout import Colors, Dimensions, Typography, AnimatedButton
from Config.UiComponents import ColorUtils, PremiumCard



# ========== HELPER WIDGETS ==========


class AnimatedSpinBox(QSpinBox):
    """SpinBox with hover effect"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self._apply_base_style()


    def _apply_base_style(self):
        self.setStyleSheet(f"""
            QSpinBox {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 6px;
                color: {Colors.TEXT_PRIMARY};
                font-size: {Typography.FONT_SIZE_BASE}px;
            }}
            QSpinBox:focus {{
                border: 1px solid {Colors.PRIMARY};
            }}
        """)


    def enterEvent(self, event):
        self.setStyleSheet(f"""
            QSpinBox {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.PRIMARY};
                border-radius: 6px;
                padding: 6px;
                color: {Colors.TEXT_PRIMARY};
                font-size: {Typography.FONT_SIZE_BASE}px;
            }}
        """)
        super().enterEvent(event)


    def leaveEvent(self, event):
        self._apply_base_style()
        super().leaveEvent(event)



class ColorPickerWidget(QWidget):
    """Color input with picker button"""
    def __init__(self, default_color="#ffffff", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)


        # Text input
        self.input = QLineEdit(default_color)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                color: {Colors.TEXT_PRIMARY};
                font-size: {Typography.FONT_SIZE_BASE}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Colors.PRIMARY};
            }}
            QLineEdit::placeholder {{
                color: {Colors.TEXT_TERTIARY};
            }}
        """)
        layout.addWidget(self.input, 1)


        # Color preview + picker button
        self.btn_picker = QPushButton()
        self.btn_picker.setFixedSize(36, 36)
        self.btn_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button_color(default_color)
        self.btn_picker.clicked.connect(self.open_color_picker)
        layout.addWidget(self.btn_picker)


        # Connect text changes to update button
        self.input.textChanged.connect(self.on_text_changed)


    def update_button_color(self, color):
        """Update button background to show color preview"""
        self.btn_picker.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                border: 2px solid {Colors.BORDER};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 2px solid {Colors.PRIMARY};
            }}
        """)


    def on_text_changed(self):
        """Update button when text changes"""
        color = self.input.text().strip()
        if color and (color.startswith('#') or color.startswith('rgb')):
            self.update_button_color(color)


    def open_color_picker(self):
        """Open color picker dialog"""
        current_color = QColor(self.input.text().strip())
        if not current_color.isValid():
            current_color = QColor("#ffffff")
        color = QColorDialog.getColor(current_color, self, "Choose Color")
        if color.isValid():
            self.input.setText(color.name())
            self.update_button_color(color.name())


    def text(self):
        """Get current color value"""
        return self.input.text()


    def setText(self, text):
        """Set color value"""
        self.input.setText(text)
        self.update_button_color(text)


    def textChanged(self):
        """Return the textChanged signal"""
        return self.input.textChanged



# ========== MAIN UI CLASS ==========


class Ui_CatalogTab:
    def setup_ui(self, parent):
        # Global Style
        parent.setStyleSheet(f"""
            QWidget {{
                background-color: {Colors.BG_MAIN};
                color: {Colors.TEXT_PRIMARY};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QGroupBox {{
                border: 1px solid {Colors.BORDER_LIGHT};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
                font-weight: 700;
                color: {Colors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 4px 8px;
                background: {Colors.BG_MAIN};
                border-radius: 4px;
            }}
        """)


        # Main Layout
        self.layout = QVBoxLayout(parent)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)


        # ========== TOP TOOLBAR ==========
        self._build_toolbar(parent)


        # ========== MAIN CONTENT ==========
        content_box = QWidget()
        self.content_layout = QHBoxLayout(content_box)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)


        # Sidebar
        self._build_sidebar()
        # self.content_layout.addWidget(self.sidebar)


        # Preview Area
        self._build_preview_area()
        self.content_layout.addWidget(self.preview_container)


        self.layout.addWidget(content_box)


    def _build_toolbar(self, parent):
        """Build the top toolbar"""
        top_bar = QFrame()
        top_bar.setFixedHeight(70)
        top_bar.setStyleSheet(f"""
            QFrame {{
                border-bottom: 1px solid {Colors.BORDER_LIGHT};
                background: {Colors.BG_CARD};
            }}
        """)


        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(Dimensions.MARGIN_COMFORTABLE, Dimensions.SPACING_MEDIUM, 
                                      Dimensions.MARGIN_COMFORTABLE, Dimensions.SPACING_MEDIUM)
        tb_layout.setSpacing(Dimensions.SPACING_XLARGE)


        # Toggle Button
        self.btn_toggle = QPushButton("☰")
        self.btn_toggle.setFixedSize(44, 44)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 2px solid {Colors.BORDER};
                border-radius: 8px;
                color: {Colors.TEXT_SECONDARY};
                font-size: 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.HOVER};
                color: {Colors.TEXT_PRIMARY};
                border: 2px solid {Colors.PRIMARY};
            }}
            QPushButton:checked {{
                background: {Colors.PRIMARY};
                color: {Colors.TEXT_INVERSE};
                border: none;
            }}
        """)
        tb_layout.addWidget(self.btn_toggle)


        # Title
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(Dimensions.SPACING_MEDIUM)


        title = QLabel("Catalog Builder")
        title.setStyleSheet(f"""
            font-size: 22px;
            font-weight: 900;
            color: {Colors.TEXT_PRIMARY};
            letter-spacing: 0.5px;
        """)
        title_layout.addWidget(title)


        tb_layout.addWidget(title_container)
        tb_layout.addStretch()


        # Navigation & Action Buttons
        self._build_navigation(tb_layout)


        # Progress Bar
        self.progress = QProgressBar()
        self.progress.setFixedWidth(120)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background: {Colors.BG_INPUT};
                border-radius: 4px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {Colors.PRIMARY};
                border-radius: 4px;
            }}
        """)
        self.progress.setVisible(False)


        progress_container = QWidget()
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.addStretch()
        progress_layout.addWidget(self.progress)
        progress_layout.addStretch()


        tb_layout.addWidget(progress_container)


        self.layout.addWidget(top_bar)



    def _build_navigation(self, layout):
        """Build navigation buttons and page controls"""
        # ========== PAGE NAVIGATION ==========
        nav_container = QFrame()
        nav_container.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_SIDEBAR};
                border-radius: 20px;
                border: 1px solid {Colors.BORDER};
            }}
        """)

        nav_layout = QHBoxLayout(nav_container)
        nav_layout.setContentsMargins(8, 4, 8, 4)
        nav_layout.setSpacing(Dimensions.SPACING_MEDIUM)

        # Previous Button
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(34, 34)
        self.btn_prev.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {Colors.TEXT_PRIMARY};
                font-weight: bold;
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: {Colors.PRIMARY}; color: {Colors.TEXT_INVERSE}; }}
        """)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)

        # Page Spinner
        self.spin_page = QSpinBox()
        self.spin_page.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_page.setFixedSize(70, 30)
        self.spin_page.setStyleSheet(f"""
            QSpinBox {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
                color: {Colors.TEXT_PRIMARY};
                padding: 2px;
            }}
        """)

        # Total Pages Label
        self.lbl_total = QLabel("/ 0")
        self.lbl_total.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-weight: 700; font-size: 14px; border: none;")

        # Next Button
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(34, 34)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {Colors.TEXT_PRIMARY};
                font-weight: bold;
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: {Colors.PRIMARY}; color: {Colors.TEXT_INVERSE}; }}
        """)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.spin_page)
        nav_layout.addWidget(self.lbl_total)
        nav_layout.addWidget(self.btn_next)

        # Add nav to LEFT (no centering)
        layout.addWidget(nav_container)

        # ========== ACTION BUTTONS ==========
        # Build Button
        self.btn_refresh = QPushButton("🔄 Build")
        self.btn_refresh.setFixedHeight(Dimensions.BTN_HEIGHT_MEDIUM)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.PRIMARY};
                color: {Colors.TEXT_INVERSE};
                border: none;
                border-radius: 6px;
                padding: 0px {Dimensions.BTN_PADDING_X}px;
                font-weight: 700;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {ColorUtils.lighten(Colors.PRIMARY, 10)};
            }}
        """)
        layout.addWidget(self.btn_refresh)

        # Export PDF Button
        self.btn_pdf = QPushButton("📄 Export PDF")
        self.btn_pdf.setFixedHeight(Dimensions.BTN_HEIGHT_MEDIUM)
        self.btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pdf.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.SUCCESS};
                color: {Colors.TEXT_INVERSE};
                border: none;
                border-radius: 6px;
                padding: 0px {Dimensions.BTN_PADDING_X}px;
                font-weight: 700;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {ColorUtils.lighten(Colors.SUCCESS, 10)};
            }}
        """)
        layout.addWidget(self.btn_pdf)

    def _build_sidebar(self):
        """Build sidebar settings"""
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(300)
        self.sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SIDEBAR};
                border-right: 1px solid {Colors.BORDER_LIGHT};
            }}
        """)


        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(Dimensions.MARGIN_COMFORTABLE, Dimensions.MARGIN_COMFORTABLE,
                                      Dimensions.MARGIN_COMFORTABLE, Dimensions.MARGIN_COMFORTABLE)
        sb_layout.setSpacing(Dimensions.SPACING_LARGE)


        # Settings Groups
        self.sets_layout = QVBoxLayout()
        self.sets_layout.setSpacing(Dimensions.SPACING_LARGE)


        scroll = QScrollArea()
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {Colors.BG_SIDEBAR};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.BORDER};
                border-radius: 4px;
            }}
        """)
        scroll.setWidgetResizable(True)


        sets_content = QWidget()
        sets_content.setLayout(self.sets_layout)


        # Build all setting groups
        self._build_page_settings()
        self._build_card_design()
        self._build_product_info_colors()
        self._build_table_design()
        self._build_typography()
        self._build_visibility()


        self.sets_layout.addStretch()
        scroll.setWidget(sets_content)
        sb_layout.addWidget(scroll)


    def _build_page_settings(self):
        """Page Settings Group"""
        g = QGroupBox("📄 PAGE SETTINGS")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QVBoxLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        self.chk_auto_layout = QCheckBox("⚡ Auto-Calculate Height")
        self.chk_auto_layout.setChecked(False)
        self.chk_auto_layout.setStyleSheet(f"""
            QCheckBox {{
                spacing: 8px;
                font-weight: 600;
                color: {Colors.TEXT_PRIMARY};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {Colors.BORDER};
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.PRIMARY};
                border: none;
            }}
        """)
        l.addWidget(self.chk_auto_layout)


        grid = QGridLayout()
        grid.setSpacing(Dimensions.SPACING_MEDIUM)


        self.spin_cols = AnimatedSpinBox()
        self.spin_cols.setRange(1, 10)
        self.spin_rows = AnimatedSpinBox()
        self.spin_rows.setRange(1, 20)


        grid.addWidget(QLabel("Columns:"), 0, 0)
        grid.addWidget(self.spin_cols, 0, 1)
        grid.addWidget(QLabel("Rows:"), 1, 0)
        grid.addWidget(self.spin_rows, 1, 1)


        l.addLayout(grid)


        l.addWidget(QLabel("Card Style:"))
        self.combo_layout_mode = QComboBox()
        self.combo_layout_mode.addItems(["Side-by-Side (Compact)", "Stacked (Top-Down)"])
        self.combo_layout_mode.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 6px 10px;
                color: {Colors.TEXT_PRIMARY};
                font-weight: 600;
            }}
            QComboBox:hover {{ border: 1px solid {Colors.PRIMARY}; }}
            QComboBox QAbstractItemView {{
                background: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                selection-background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)
        l.addWidget(self.combo_layout_mode)


        dim_grid = QGridLayout()
        dim_grid.setSpacing(Dimensions.SPACING_MEDIUM)


        self.spin_img_h = AnimatedSpinBox()
        self.spin_img_h.setRange(20, 600)
        self.spin_gap_v = AnimatedSpinBox()
        self.spin_gap_v.setRange(0, 100)


        dim_grid.addWidget(QLabel("Image Height (px):"), 0, 0)
        dim_grid.addWidget(self.spin_img_h, 0, 1)
        dim_grid.addWidget(QLabel("Grid Gap (px):"), 1, 0)
        dim_grid.addWidget(self.spin_gap_v, 1, 1)


        l.addLayout(dim_grid)
        self.sets_layout.addWidget(g)


    def _build_card_design(self):
        """Card Design Group"""
        g = QGroupBox("🎨 CARD DESIGN")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QGridLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        l.addWidget(QLabel("Background:"), 0, 0)
        self.input_card_bg = ColorPickerWidget("#ffffff")
        l.addWidget(self.input_card_bg, 0, 1)


        l.addWidget(QLabel("Border Color:"), 1, 0)
        self.input_border_color = ColorPickerWidget("#d0d0d8")
        l.addWidget(self.input_border_color, 1, 1)


        l.addWidget(QLabel("Border Width:"), 2, 0)
        self.spin_border_width = AnimatedSpinBox()
        self.spin_border_width.setRange(0, 10)
        l.addWidget(self.spin_border_width, 2, 1)


        l.addWidget(QLabel("Corner Radius:"), 3, 0)
        self.spin_border_radius = AnimatedSpinBox()
        self.spin_border_radius.setRange(0, 20)
        l.addWidget(self.spin_border_radius, 3, 1)


        self.sets_layout.addWidget(g)


    def _build_product_info_colors(self):
        """Product Info Colors Group"""
        g = QGroupBox("📝 PRODUCT INFO COLORS")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QGridLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        l.addWidget(QLabel("Name BG:"), 0, 0)
        self.input_product_name_bg = ColorPickerWidget("#ffffff")
        l.addWidget(self.input_product_name_bg, 0, 1)


        l.addWidget(QLabel("Name Text:"), 1, 0)
        self.input_product_name_text = ColorPickerWidget("#1a1a1f")
        l.addWidget(self.input_product_name_text, 1, 1)


        l.addWidget(QLabel("Base Units BG:"), 2, 0)
        self.input_base_units_bg = ColorPickerWidget("#ffffff")
        l.addWidget(self.input_base_units_bg, 2, 1)


        l.addWidget(QLabel("Base Units Text:"), 3, 0)
        self.input_base_units_text = ColorPickerWidget("#6b6b7a")
        l.addWidget(self.input_base_units_text, 3, 1)


        self.sets_layout.addWidget(g)


    def _build_table_design(self):
        """Table Design Group"""
        g = QGroupBox("📊 TABLE DESIGN")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QGridLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        l.addWidget(QLabel("Header BG:"), 0, 0)
        self.input_table_header_bg = ColorPickerWidget("#2563eb")
        l.addWidget(self.input_table_header_bg, 0, 1)


        l.addWidget(QLabel("Header Text:"), 1, 0)
        self.input_table_header_text = ColorPickerWidget("#ffffff")
        l.addWidget(self.input_table_header_text, 1, 1)


        l.addWidget(QLabel("Cell BG:"), 2, 0)
        self.input_table_cell_bg = ColorPickerWidget("#ffffff")
        l.addWidget(self.input_table_cell_bg, 2, 1)


        l.addWidget(QLabel("Cell Text:"), 3, 0)
        self.input_table_cell_text = ColorPickerWidget("#1a1a1f")
        l.addWidget(self.input_table_cell_text, 3, 1)


        l.addWidget(QLabel("Row Separator:"), 4, 0)
        self.input_table_separator = ColorPickerWidget("#e5e5ec")
        l.addWidget(self.input_table_separator, 4, 1)


        self.sets_layout.addWidget(g)


    def _build_typography(self):
        """Typography Group"""
        g = QGroupBox("🔤 TYPOGRAPHY")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QGridLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        fields = [
            ("Product Title:", "spin_txt_title", 8, 36),
            ("Base Units:", "spin_fs_base_units", 6, 24),
            ("Table Header:", "spin_txt_header", 8, 24),
            ("Table Cell:", "spin_txt_cell", 6, 20),
            ("Category:", "spin_fs_category", 6, 20),
            ("Master Pack:", "spin_fs_master_packing", 6, 20),
            ("Company Name:", "spin_fs_company", 6, 24),
            ("Page Heading:", "spin_fs_heading", 6, 24),
            ("Page Number:", "spin_fs_page_num", 6, 24),
            ("CRM Name:", "spin_fs_crm", 6, 24),
            ("Date:", "spin_fs_date", 6, 24),
        ]


        for idx, (label, attr, min_val, max_val) in enumerate(fields):
            l.addWidget(QLabel(label), idx, 0)
            spin = AnimatedSpinBox()
            spin.setRange(min_val, max_val)
            setattr(self, attr, spin)
            l.addWidget(spin, idx, 1)


        self.sets_layout.addWidget(g)


    def _build_visibility(self):
        """Visibility Group"""
        g = QGroupBox("👁️ VISIBILITY")
        g.setStyleSheet(f"QGroupBox {{ font-size: 13px; padding-top: 12px; }}")
        l = QVBoxLayout(g)
        l.setSpacing(Dimensions.SPACING_MEDIUM)


        self.chk_moq = QCheckBox("📦 Show MOQ")
        self.chk_master = QCheckBox("📊 Show Master Packing")
        self.chk_footer = QCheckBox("📝 Show Footer")


        for c in [self.chk_moq, self.chk_master, self.chk_footer]:
            c.setChecked(True)
            c.setStyleSheet(f"""
                QCheckBox {{
                    spacing: 8px;
                    font-weight: 600;
                    color: {Colors.TEXT_PRIMARY};
                }}
                QCheckBox::indicator {{
                    width: 18px;
                    height: 18px;
                    border-radius: 4px;
                    border: 1px solid {Colors.BORDER};
                }}
                QCheckBox::indicator:checked {{
                    background: {Colors.SUCCESS};
                    border: none;
                }}
            """)
            l.addWidget(c)


        self.sets_layout.addWidget(g)


    def _build_preview_area(self):
        """Build preview area"""
        self.preview_container = QWidget()
        self.preview_container.setStyleSheet(f"""
            QWidget {{
                background: {Colors.BG_MAIN};
            }}
        """)


        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)


        self.preview_scroll = QScrollArea()
        self.preview_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {Colors.BG_MAIN};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {Colors.BG_MAIN};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.BORDER};
                border-radius: 5px;
            }}
        """)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setWidgetResizable(True)


        # Page Container
        self.page_container = QWidget()
        self.page_container.setStyleSheet(f"background: {Colors.BG_MAIN};")
        self.page_layout = QVBoxLayout(self.page_container)
        self.page_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_layout.setContentsMargins(5 , 5, 5, 30)


        self.preview_scroll.setWidget(self.page_container)
        self.preview_layout.addWidget(self.preview_scroll)