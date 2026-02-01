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
    QDialog,
    QSpinBox,
    QCheckBox,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
import os


MM_PER_INCH = 25.4

def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm * dpi / MM_PER_INCH))


class ProductSizeDialog(QDialog):
    def __init__(self, current_str, prod_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Product Dimensions Setup")
        self.setFixedSize(400, 300)
        self.result_str = current_str
        self.prod_data = prod_data
        
        # Calculate Auto Height
        num_sizes = len(prod_data.get("sizes", []))
        if num_sizes > 10: self.auto_h = 3
        elif num_sizes > 5: self.auto_h = 2
        else: self.auto_h = 1
        
        product_name = prod_data.get("product_name", "Unknown")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(QLabel(f"<b>Set Size for: {product_name}</b>"))
        
        # Parse current
        curr_img_w, curr_data_w, curr_h = 2, 1, 0  # Defaults
        parts = current_str.split("|")
        if len(parts) > 0:
            w_part = parts[0]
            if ":" in w_part:
                d = w_part.split(":")
                if len(d) > 1 and d[0].isdigit() and d[1].isdigit():
                    curr_img_w = int(d[0])
                    curr_data_w = int(d[1])
            elif w_part.isdigit():
                curr_img_w = int(w_part)
                curr_data_w = 1 
        
        if len(parts) > 1 and parts[1].isdigit():
            curr_h = int(parts[1])

        # Form
        form = QGridLayout()
        form.setVerticalSpacing(15)
        
        # Image Width
        form.addWidget(QLabel("Image Width (Cols):"), 0, 0)
        self.spin_img = QSpinBox()
        self.spin_img.setRange(1, 4)
        self.spin_img.setValue(curr_img_w)
        form.addWidget(self.spin_img, 0, 1)
        
        # Data Width
        form.addWidget(QLabel("Data Width (Cols):"), 1, 0)
        self.spin_data = QSpinBox()
        self.spin_data.setRange(1, 4)
        self.spin_data.setValue(curr_data_w)
        form.addWidget(self.spin_data, 1, 1)
        
        # Total Preview
        self.lbl_total = QLabel("Total Width: -")
        form.addWidget(self.lbl_total, 2, 1)
        
        # Height
        form.addWidget(QLabel("Vertical Height (Rows):"), 3, 0)
        self.spin_h = QSpinBox()
        self.spin_h.setRange(1, 5) # Minimum 1 visually
        # Set initial value (if curr_h is 0, show auto_h)
        val_to_show = self.auto_h if curr_h == 0 else curr_h
        self.spin_h.setValue(val_to_show)
        form.addWidget(self.spin_h, 3, 1)
        
        self.check_auto = QCheckBox(f"Automatic Height (Calc: {self.auto_h})")
        self.check_auto.setChecked(curr_h == 0)
        self.check_auto.toggled.connect(self.toggle_auto)
        form.addWidget(self.check_auto, 4, 1)
        
        # Initial state update (disable spin if auto)
        self.toggle_auto(self.check_auto.isChecked())
        
        layout.addLayout(form)
        
        # Update Total Calc
        self.spin_img.valueChanged.connect(self.update_total)
        self.spin_data.valueChanged.connect(self.update_total)
        self.update_total()

        # Buttons
        btns = QHBoxLayout()
        ok = QPushButton("Apply")
        ok.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; border-radius: 4px; padding: 6px;")
        ok.clicked.connect(self.save)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; border-radius: 4px; padding: 6px;")
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        
    def toggle_auto(self, checked):
        self.spin_h.setEnabled(not checked)
        if checked: 
            self.spin_h.setValue(self.auto_h)
        
    def update_total(self):
        sender = self.sender()
        i = self.spin_img.value()
        d = self.spin_data.value()
        
        # Enforce max 4 columns (Page Width)
        if i + d > 4:
            if sender == self.spin_img:
                # Prioritize Image change, reduce Data
                new_d = 4 - i
                if new_d < 1: # If Image set to 4, clamp to 3
                    new_d = 1
                    self.spin_img.blockSignals(True)
                    self.spin_img.setValue(3)
                    self.spin_img.blockSignals(False)
                self.spin_data.blockSignals(True)
                self.spin_data.setValue(new_d)
                self.spin_data.blockSignals(False)
            
            elif sender == self.spin_data:
                # Prioritize Data change, reduce Image
                new_i = 4 - d
                if new_i < 1: # If Data set to 4, clamp to 3
                    new_i = 1
                    self.spin_data.blockSignals(True)
                    self.spin_data.setValue(3)
                    self.spin_data.blockSignals(False)
                self.spin_img.blockSignals(True)
                self.spin_img.setValue(new_i)
                self.spin_img.blockSignals(False)
        
        # Refresh values
        i = self.spin_img.value()
        d = self.spin_data.value()
        tot = i + d
        self.lbl_total.setText(f"Total Width: {tot} Columns (Max 4)")
        
    def save(self):
        i = self.spin_img.value()
        d = self.spin_data.value()
        # If Auto checked, save 0, else save spin value
        h = 0 if self.check_auto.isChecked() else self.spin_h.value()
        self.result_str = f"{i}:{d}|{h}"
        self.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            fw = self.focusWidget()
            if fw == self.spin_img:
                self.spin_data.setFocus()
            elif fw == self.spin_data:
                if self.spin_h.isEnabled(): self.spin_h.setFocus()
                else: self.check_auto.setFocus()
            elif fw == self.spin_h:
                self.check_auto.setFocus()
            elif fw == self.check_auto:
                self.save() # Last field -> Apply
            else:
                 from PyQt6.QtWidgets import QPushButton
                 if isinstance(fw, QPushButton): fw.animateClick()
                 else: self.focusNextChild()
            return
        super().keyPressEvent(event)

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

            # Determine split from stored data string to respect custom layout
            D = 1
            H = total - 1
            
            p_len = str(prod.get("length", "")).strip()
            if "|" in p_len:
                w_str = p_len.split("|")[0]
                if ":" in w_str:
                    try:
                        pts = w_str.split(":")
                        iw = int(pts[0])
                        dw = int(pts[1])
                        # Only apply if it matches total cspan or fits
                        if iw + dw == total:
                            H = iw
                            D = dw
                        elif iw + dw > total:
                            # Always Priority Image (User Request)
                            H = total - 1
                            D = 1 
                    except: pass
            
            # Fallback / Safety
            H = max(1, H)
            D = max(1, D)

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
            
            # Optimization: Scale extremely large images during read
            # This prevents loading 4K/8K images for small thumbnails
            if w > 0 and h > 0:
                orig_size = reader.size()
                if orig_size.isValid() and (orig_size.width() > w * 3 or orig_size.height() > h * 3):
                    # Scale to 3x target size (preserves good quality while reducing memory I/O)
                    new_size = orig_size.scaled(w * 3, h * 3, Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(new_size)

            img = reader.read()

            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                scaled = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
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
        if not current_len_str: current_len_str = "1|0" 
        
        # Set Size action
        set_size_action = QAction(f"Set Size/Layout... [Curr: {current_len_str}]", menu)
        set_size_action.triggered.connect(lambda: self._set_product_length(prod))
        menu.addAction(set_size_action)
        
        menu.exec(widget.mapToGlobal(pos))
    
    def _set_product_length(self, prod):
        """Show dialog to set product size (ImgW:DataW|Height) and emit signal."""
        product_name = prod.get("product_name", "Unknown")
        current_val = str(prod.get("length", "")).strip()
        if not current_val: current_val = "1|0"
        
        dlg = ProductSizeDialog(current_val, prod, self)
        if dlg.exec():
            new_val = dlg.result_str
            if new_val != current_val:
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
        
        # Enable right-click context menu (Same as Image Block)
        f.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        f.customContextMenuRequested.connect(lambda pos, p=prod: self._show_context_menu(f, pos, p))

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

        raw_sizes = prod.get("sizes", [])
        raw_mrps = prod.get("mrps", [])
        raw_moqs = prod.get("moqs", [])
        
        # Combine and Sort
        combined = []
        for i in range(len(raw_sizes)):
            s = str(raw_sizes[i])
            m = raw_mrps[i] if i < len(raw_mrps) else ""
            q = raw_moqs[i] if i < len(raw_moqs) else ""
            
            # Helper for sorting price
            try:
                import re
                clean_m = re.sub(r"[^\d\.]", "", str(m))
                p_val = float(clean_m) if clean_m else 0.0
            except:
                p_val = 0.0
                
            combined.append((p_val, s, m, q))
            
        # Sort by Price ASC, then Size ASC
        combined.sort(key=lambda x: (x[0], x[1]))
        
        sizes = [x[1] for x in combined]
        mrps = [x[2] for x in combined]
        moqs = [x[3] for x in combined]

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
