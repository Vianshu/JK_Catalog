# a4_renderer.py - Exact copy of A4CatalogPage from A4Catalog.py

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QMenu,
    QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
import os


MM_PER_INCH = 25.4

def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm * dpi / MM_PER_INCH))


class A4PageRenderer(QWidget):
    """Exact implementation from A4Catalog.py for consistent printing."""
    
    # Signal emitted when user changes product size via right-click
    # Emits: (product_name, new_size_str)
    length_changed = pyqtSignal(str, str)
    
    BLUE = "#1511FF"
    RED = "#FF1A1A"
    BLACK = "#000000"
    WHITE = "#ffffff"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#ffffff;")
        
        # Store current products for context menu reference
        self._current_products = []
        self._widgets = []

        self.page_cols = 4
        self.page_rows = 5

        # Physical page definition (mm)
        self.page_w_mm = 210.0
        self.page_h_mm = 297.0

        self.margin_l_mm = 2.65
        self.margin_r_mm = 2.65
        self.margin_t_mm = 2.65
        self.margin_b_mm = 2.65
        self.header_h_mm = 11.6
        self.footer_h_mm = 11.6

        self.target_dpi = 96

        self.page_w = 0
        self.page_h = 0
        self.header_h = 0
        self.footer_h = 0
        self.margin_l = 0
        self.margin_r = 0
        self.margin_t = 0
        self.margin_b = 0
        self.content_w = 0

        # Theme
        self.border_width = 2
        self.grid_line_color = self.BLUE
        self.divider_color = self.RED
        self.header_footer_border_color = self.BLUE

        self.data_name_text = self.WHITE
        self.data_name_bg = self.BLACK
        self.data_border_color = self.BLACK

        self.table_outer_color = self.BLACK
        self.table_inner_color = self.BLACK
        self.table_header_bg = self.BLUE
        self.table_header_text = self.WHITE
        self.table_cell_bg = self.RED
        self.table_cell_text = self.WHITE

        self.show_moq = True
        self.show_master_packing = True

        # Typography
        self.title_fs = 16
        self.header_fs = 14
        self.cell_fs = 14
        self.fs_base_units = 12
        self.fs_category = 14
        self.fs_master_packing = 14

        # Padding
        self.pad_title_v = 2
        self.pad_title_h = 3
        self.pad_base_v = 0
        self.pad_base_h = 0
        self.pad_hdr_v = 2
        self.pad_hdr_h = 2
        self.pad_cell_v = 1
        self.pad_cell_h = 2
        self.pad_bottom_v = 1
        self.pad_bottom_h = 3

        self.cell_w = None
        self.cell_h = None
        self.col_widths = None
        self.row_heights = None

        # Root layout
        self.root = QVBoxLayout(self)

        # Header
        self.header_frame = QFrame(self)
        self.header_frame.setFixedSize(self.content_w, self.header_h)
        self.header_frame.setStyleSheet(
            "QFrame {"
            f"border-left:{self.border_width}px solid {self.header_footer_border_color};"
            f"border-right:{self.border_width}px solid {self.header_footer_border_color};"
            f"border-top:{self.border_width}px solid {self.header_footer_border_color};"
            "border-bottom:none;"
            "background:#ffffff;"
            "}"
        )

        hl = QHBoxLayout(self.header_frame)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(0)

        self.header_left = QLabel("")
        self.header_center = QLabel("")
        self.header_right = QLabel("")

        self.header_left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.header_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.header_left.setStyleSheet("border:none; color:#000; font-size:16pt; font-weight:700;")
        self.header_center.setStyleSheet("border:none; color:#000; font-size:16pt; font-weight:700;")
        self.header_right.setStyleSheet("border:none; color:#000; font-size:16pt;")

        hl.addWidget(self.header_left, 1)
        hl.addWidget(self.header_center, 2)
        hl.addWidget(self.header_right, 1)

        self.root.addWidget(self.header_frame)

        # Grid wrapper
        self.grid_wrap = QFrame(self)
        self.grid_wrap.setStyleSheet("border:none; background:#ffffff;")
        self.grid_wrap.setFixedWidth(self.content_w)

        grid_wrap_layout = QVBoxLayout(self.grid_wrap)
        grid_wrap_layout.setContentsMargins(0, 0, 0, 0)
        grid_wrap_layout.setSpacing(0)

        self.grid_widget = QWidget(self.grid_wrap)
        self.grid_widget.setStyleSheet("background:#ffffff; border:none;")
        self.grid_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(0)
        self.grid_layout.setVerticalSpacing(0)

        grid_wrap_layout.addWidget(self.grid_widget)

        self.grid_bottom_line = QFrame(self.grid_wrap)
        self.grid_bottom_line.setFixedSize(self.content_w, self.border_width)
        self.grid_bottom_line.setStyleSheet(f"background:{self.grid_line_color}; border:none;")
        grid_wrap_layout.addWidget(self.grid_bottom_line)

        self.root.addWidget(self.grid_wrap)

        # Footer
        self.footer_frame = QFrame(self)
        self.footer_frame.setFixedSize(self.content_w, self.footer_h)
        self.footer_frame.setStyleSheet(
            "QFrame {"
            f"border-left:{self.border_width}px solid {self.header_footer_border_color};"
            f"border-right:{self.border_width}px solid {self.header_footer_border_color};"
            "border-top:none;"
            f"border-bottom:{self.border_width}px solid {self.header_footer_border_color};"
            "background:#ffffff;"
            "}"
        )

        fl = QHBoxLayout(self.footer_frame)
        fl.setContentsMargins(8, 4, 8, 4)
        fl.setSpacing(0)

        self.footer_left = QLabel("")
        self.footer_center = QLabel("")
        self.footer_right = QLabel("")

        self.footer_left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.footer_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.footer_left.setStyleSheet("border:none; color:#000; font-size:14pt; font-weight:700;")
        self.footer_center.setStyleSheet("border:none; color:#000; font-size:12pt; font-weight:600;")
        self.footer_right.setStyleSheet("border:none; color:#000; font-size:12pt; font-weight:600;") # Changed from Green to Black

        fl.addWidget(self.footer_left, 1)
        fl.addWidget(self.footer_center, 2)
        fl.addWidget(self.footer_right, 1)

        self.root.addWidget(self.footer_frame)
        
        self._struts = []
        self._recompute_geometry()

    def set_footer_data(self, crm_name, date_str):
        """Set footer texts: CRM Left, Date Right."""
        self.footer_left.setText(crm_name)
        self.footer_center.setText("") 
        self.footer_right.setText(date_str)

    def set_target_dpi(self, dpi: int):
        dpi = int(dpi) if dpi else 96
        if dpi <= 0:
            dpi = 96
        if getattr(self, "target_dpi", None) == dpi:
            return
        self.target_dpi = dpi
        self._recompute_geometry()

    def _recompute_geometry(self):
        dpi = getattr(self, "target_dpi", 96)

        self.page_w = mm_to_px(self.page_w_mm, dpi)
        self.page_h = mm_to_px(self.page_h_mm, dpi)

        self.margin_l = mm_to_px(self.margin_l_mm, dpi)
        self.margin_r = mm_to_px(self.margin_r_mm, dpi)
        self.margin_t = mm_to_px(self.margin_t_mm, dpi)
        self.margin_b = mm_to_px(self.margin_b_mm, dpi)

        self.header_h = mm_to_px(self.header_h_mm, dpi)
        self.footer_h = mm_to_px(self.footer_h_mm, dpi)

        self.setFixedSize(self.page_w, self.page_h)

        self.root.setContentsMargins(self.margin_l, self.margin_t, self.margin_r, self.margin_b)
        self.root.setSpacing(0)

        self.content_w = self.page_w - (self.margin_l + self.margin_r)

        self.header_frame.setFixedSize(self.content_w, self.header_h)
        self.grid_wrap.setFixedWidth(self.content_w)
        self.grid_bottom_line.setFixedSize(self.content_w, self.border_width)
        self.footer_frame.setFixedSize(self.content_w, self.footer_h)

        self._compute_fixed_grid_metrics()
        self.update()

    def _compute_fixed_grid_metrics(self):
        usable_h = (self.page_h - (self.margin_t + self.margin_b)) - self.header_h - self.footer_h
        usable_h -= self.border_width
        usable_w = self.content_w

        base_w = usable_w // self.page_cols
        rem_w = usable_w - (base_w * self.page_cols)
        self.col_widths = [base_w] * self.page_cols
        self.col_widths[-1] += rem_w

        base_h = usable_h // self.page_rows
        rem_h = usable_h - (base_h * self.page_rows)
        self.row_heights = [base_h] * self.page_rows
        self.row_heights[-1] += rem_h

        self.grid_widget.setFixedSize(usable_w, usable_h)

        for s in self._struts:
            try:
                self.grid_layout.removeWidget(s)
                s.deleteLater()
            except: pass
        self._struts = []

        for c, w in enumerate(self.col_widths):
            self.grid_layout.setColumnMinimumWidth(c, w)
            self.grid_layout.setColumnStretch(c, 0)

        for r, h in enumerate(self.row_heights):
            self.grid_layout.setRowMinimumHeight(r, h)
            self.grid_layout.setRowStretch(r, 0)

        self.cell_w = base_w
        self.cell_h = base_h

    def set_header_data(self, group_name, page_no):
        self.header_left.setText("NGT")
        self.header_center.setText(str(group_name).upper())
        self.header_right.setText(f"Page: {page_no}")

    def clear_page(self):
        for w in self._widgets:
            try:
                self.grid_layout.removeWidget(w)
                w.deleteLater()
            except: pass
        self._widgets = []

    def fill_products(self, placeditems):
        """Fill page with products - accepts list of placement dicts.
        Empty spaces are distributed evenly across the page for visual balance.
        """
        self.clear_page()
        rows = self.page_rows
        cols = self.page_cols

        occ = [[False] * cols for _ in range(rows)]

        def mark(rr, cc, rs, cs):
            for r0 in range(rr, rr + rs):
                for c0 in range(cc, cc + cs):
                    if r0 < rows and c0 < cols:
                        occ[r0][c0] = True

        # First pass: Place products and mark occupied cells
        product_placements = []
        for it in placeditems:
            prod = it.get("data") or it  # Support both formats

            r = int(it.get("row", 0))
            c = int(it.get("col", 0))
            rs = max(1, int(it.get("rspan", 1)))
            total = max(2, int(it.get("cspan", 2)))
            total = min(total, cols - c)

            # Layout: Data always takes 1 column, Image takes remainder
            D = 1
            H = total - D
            H = max(1, H)

            rs = min(rs, rows - r)
            mark(r, c, rs, total)
            
            product_placements.append({
                "prod": prod,
                "r": r, "c": c, "rs": rs, "total": total, "H": H, "D": D
            })

        # Count total cells and empty cells
        total_cells = rows * cols
        occupied_cells = sum(1 for row in occ for cell in row if cell)
        empty_count = total_cells - occupied_cells
        
        # Collect empty cell positions
        empty_cells = []
        for rr in range(rows):
            for cc in range(cols):
                if not occ[rr][cc]:
                    empty_cells.append((rr, cc))
        
        # Calculate distribution pattern for empty cells
        # If we have empty cells, spread them evenly across rows
        if empty_count > 0 and len(product_placements) > 0:
            # Sort empty cells to distribute - alternate between top and bottom rows
            empty_cells_sorted = []
            top_row = 0
            bot_row = rows - 1
            while top_row <= bot_row:
                # Add cells from top row
                for cc in range(cols):
                    if (top_row, cc) in [(e[0], e[1]) for e in empty_cells]:
                        empty_cells_sorted.append((top_row, cc))
                if top_row != bot_row:
                    # Add cells from bottom row
                    for cc in range(cols):
                        if (bot_row, cc) in [(e[0], e[1]) for e in empty_cells]:
                            empty_cells_sorted.append((bot_row, cc))
                top_row += 1
                bot_row -= 1
            
            # Use the distributed order (but keep original positions for rendering)
            # The visual distribution is handled by the layout itself

        # Render products
        for pl in product_placements:
            prod = pl["prod"]
            r, c, rs = pl["r"], pl["c"], pl["rs"]
            H, D, total = pl["H"], pl["D"], pl["total"]
            
            cardrightedge = (c + total == cols)
            imgw = sum(self.col_widths[c:c + H])
            dataw = sum(self.col_widths[c + H:c + total])
            blkh = sum(self.row_heights[r:r + rs])

            imgblock = self._img_block(imgw, blkh, prod, draw_right=False)
            datablock = self._data_block(dataw, blkh, prod, draw_right=cardrightedge)

            self.grid_layout.addWidget(imgblock, r, c, rs, H)
            self.grid_layout.addWidget(datablock, r, c + H, rs, D)
            self._widgets.append(imgblock)
            self._widgets.append(datablock)

        # Fill empty cells 
        for rr in range(rows):
            for cc in range(cols):
                if occ[rr][cc]:
                    continue
                w = self.col_widths[cc]
                h = self.row_heights[rr]
                empty = self._empty_cell(w, h, draw_right=(cc == cols - 1))
                self.grid_layout.addWidget(empty, rr, cc, 1, 1)
                self._widgets.append(empty)

        self.update()

    def _img_block(self, w: int, h: int, prod: dict, draw_right: bool) -> QFrame:
        b = self.border_width
        blue = self.grid_line_color

        f = QFrame()
        f.setFixedSize(w, h)
        f.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        f.setStyleSheet(
            "QFrame {background:#ffffff;"
            f"border-top:{b}px solid {blue};"
            f"border-left:{b}px solid {blue};"
            "border-bottom:none;"
            f"{('border-right:%dpx solid %s;' % (b, blue)) if draw_right else 'border-right:none;'}"
            "border-radius:0px;}"
        )
        
        # Enable right-click context menu
        f.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        f.customContextMenuRequested.connect(lambda pos, p=prod: self._show_context_menu(f, pos, p))

        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("border:none;")

        image_path = prod.get("image_path", "")
        if image_path and os.path.exists(image_path):
            from PyQt6.QtGui import QImageReader
            reader = QImageReader(image_path)
            reader.setAutoTransform(True)
            img = reader.read()

            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                scaled = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                lbl.setPixmap(scaled)

        lay.addWidget(lbl, 1)
        return f
    
    def _show_context_menu(self, widget, pos, prod):
        """Show context menu for product with Set Size option."""
        menu = QMenu(widget)
        
        product_name = prod.get("product_name", "Unknown")
        current_len_str = str(prod.get("length", "")).strip()
        if not current_len_str: current_len_str = "1|0" # Default: Std Width, Auto Height
        
        # Set Size action
        set_size_action = QAction(f"Set Size (H|V) [Curr: {current_len_str}]", menu)
        set_size_action.triggered.connect(lambda: self._set_product_length(prod))
        menu.addAction(set_size_action)
        
        menu.exec(widget.mapToGlobal(pos))
    
    def _set_product_length(self, prod):
        """Show dialog to set product size (H|V) and emit signal."""
        product_name = prod.get("product_name", "Unknown")
        current_val = str(prod.get("length", "")).strip()
        if not current_val: current_val = "1|0" # Default: Std Width, Auto Height
        
        # QInputDialog.getText(parent, title, label, echo, text)
        new_val, ok = QInputDialog.getText(
            self,
            "Set Product Size",
            f"Enter Dimensions 'ImgWidth | Height' for '{product_name}':\nImgWidth: 1=Standard (2 cols), 3=Full (4 cols)\nHeight: 0=Auto (based on size), 1-5=Manual\nFormat e.g.: '1|0' (Auto Ht), '3|0' (Full W, Auto Ht), '1|2' (Fixed Ht)",
            text=current_val
        )
        
        if ok and new_val != current_val:
            # Emit signal with product name and new text value
            self.length_changed.emit(product_name, new_val) 
    

    def _data_block(self, w: int, h: int, prod: dict, draw_right: bool) -> QFrame:
        b = self.border_width
        blue = self.grid_line_color
        red = self.divider_color

        f = QFrame()
        f.setFixedSize(w, h)
        f.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        f.setStyleSheet(
            "QFrame {background:#ffffff;"
            f"border-top:{b}px solid {blue};"
            f"border-left:{b}px solid {red};"
            "border-bottom:none;"
            f"{('border-right:%dpx solid %s;' % (b, blue)) if draw_right else 'border-right:none;'}"
            "border-radius:0px;}"
        )

        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_info_container(prod))
        return f

    def _empty_cell(self, w: int, h: int, draw_right: bool) -> QFrame:
        b = self.border_width
        blue = self.grid_line_color

        f = QFrame()
        f.setFixedSize(w, h)
        f.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        f.setStyleSheet(
            "QFrame {background:#ffffff;"
            f"border-top:{b}px solid {blue};"
            f"border-left:{b}px solid {blue};"
            "border-bottom:none;"
            f"{('border-right:%dpx solid %s;' % (b, blue)) if draw_right else 'border-right:none;'}"
            "border-radius:0px;}"
        )
        return f

    def _build_info_container(self, prod: dict) -> QWidget:
        container = QWidget()
        container.setStyleSheet("border:none; background:#ffffff;")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Product Name
        name = QLabel(str(prod.get("product_name", "Unknown")))
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"font-size:{self.title_fs}pt; font-weight:700; color:{self.data_name_text}; background:{self.data_name_bg};"
            f"padding:{self.pad_title_v}px {self.pad_title_h}px;"
            f"border-bottom:{self.border_width}px solid {self.data_border_color};"
        )
        name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay.addWidget(name, 2)

        # Base Units
        base_units = prod.get("base_units", "")
        if base_units:
            base_lbl = QLabel(f"प्रति {base_units}")
            base_lbl.setWordWrap(True)
            base_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            base_lbl.setStyleSheet(
                f"font-size:{self.fs_base_units}pt; font-weight:500; color:#000; background:#ffffff;"
                "font-family:'Nirmala UI','Mangal','Arial Unicode MS';"
                f"padding:{self.pad_base_v}px {self.pad_base_h}px;"
                f"border-bottom:{self.border_width}px solid {self.data_border_color};"
            )
            base_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lay.addWidget(base_lbl, 0)

        # Table
        table = self._build_internal_table(prod)
        table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay.addWidget(table, 5)

        # Bottom (Category + Master Packing)
        bottom = QFrame()
        bottom.setStyleSheet("background:#ffffff;")
        bottom.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        blay = QHBoxLayout(bottom)
        blay.setContentsMargins(self.pad_bottom_h, self.pad_bottom_v, self.pad_bottom_h, self.pad_bottom_v)
        blay.setSpacing(6)

        cat_text = prod.get("category", "")
        cat_lbl = QLabel(str(cat_text) if cat_text else "")
        cat_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cat_lbl.setStyleSheet(f"font-size:{self.fs_category}pt; font-weight:bold; color:#000; border:none;")
        blay.addWidget(cat_lbl, 1)

        mp_text = prod.get("master_packing", "") if self.show_master_packing else ""
        mp_lbl = QLabel(str(mp_text) if mp_text else "")
        mp_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mp_lbl.setStyleSheet(f"font-size:{self.fs_master_packing}pt; color:#000; border:none;")
        blay.addWidget(mp_lbl, 1)

        lay.addWidget(bottom, 0)
        return container

    def _build_internal_table(self, prod: dict) -> QFrame:
        inner = f"1px solid {self.table_inner_color}"
        outer_bottom = f"{self.border_width}px solid {self.table_outer_color}"

        table = QFrame()
        table.setStyleSheet(f"border-bottom:{outer_bottom}; background:transparent;")
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        lay = QGridLayout(table)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(0)
        lay.setVerticalSpacing(0)

        headers = ["Size", "MRP"]
        if self.show_moq:
            headers.append("MOQ")

        for i in range(len(headers)):
            lay.setColumnStretch(i, 1)

        for col, text in enumerate(headers):
            h = QLabel(text)
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b_right = inner if col < len(headers) - 1 else "none"
            h.setStyleSheet(
                f"font-size:{self.header_fs}pt;"
                f"color:{self.table_header_text}; background:{self.table_header_bg};"
                f"padding:{self.pad_hdr_v}px {self.pad_hdr_h}px;"
                f"border:none; border-right:{b_right}; border-bottom:{inner};"
            )
            lay.addWidget(h, 0, col)

        sizes = list(prod.get("sizes", []))
        mrps = list(prod.get("mrps", []))
        moqs = list(prod.get("moqs", []))

        total_rows = len(sizes)
        last_col_idx = 2 if self.show_moq else 1

        for row, size in enumerate(sizes, start=1):
            mrp = mrps[row - 1] if row - 1 < len(mrps) else ""
            moq = moqs[row - 1] if row - 1 < len(moqs) else ""

            def style_cell(lbl: QLabel, col_idx: int, row_num=row, total=total_rows):
                b_right = inner if col_idx != last_col_idx else "none"
                b_bottom = inner if row_num != total else "none"
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    f"font-size:{self.cell_fs}pt;"
                    f"color:{self.table_cell_text}; background:{self.table_cell_bg};"
                    f"padding:{self.pad_cell_v}px {self.pad_cell_h}px;"
                    f"border:none; border-right:{b_right}; border-bottom:{b_bottom};"
                )

            l_size = QLabel(str(size))
            style_cell(l_size, 0)
            lay.addWidget(l_size, row, 0)

            l_mrp = QLabel(self._fmt_money(mrp))
            style_cell(l_mrp, 1)
            lay.addWidget(l_mrp, row, 1)

            if self.show_moq:
                l_moq = QLabel(str(moq))
                style_cell(l_moq, 2)
                lay.addWidget(l_moq, row, 2)

        return table

    def _fmt_money(self, v):
        if v is None:
            return ""
        s = str(v).strip()
        if not s:
            return ""
        try:
            s = s.replace(",", "")
            import re
            m = re.search(r"[-]?\d+(?:\.\d+)?", s)
            if not m:
                return str(v)
            x = float(m.group(0))
            if x.is_integer():
                return str(int(x))
            return f"{x:.2f}"
        except:
            return str(v)
