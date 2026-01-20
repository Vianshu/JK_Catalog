# A4Catalog.py 

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QGridLayout,
    QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
import os



MM_PER_INCH = 25.4

def mm_to_px(mm: float, dpi: int) -> int:
    # pixels = mm * (dpi / 25.4)
    return int(round(mm * dpi / MM_PER_INCH))


class A4CatalogPage(QWidget):
    BLUE = "#1511FF"
    RED = "#FF1A1A"
    BLACK = "#000000"
    WHITE = "#ffffff"

    def __init__(self, parent=None):
        super().__init__(parent)

        # Outer page bg (important for some PDF/viewers)
        self.setStyleSheet("background:#ffffff;")

        self.page_cols = 4
        self.page_rows = 5

        # --- Physical page definition (mm) ---
        self.page_w_mm = 210.0
        self.page_h_mm = 297.0

        # 10px at ~96dpi ≈ 2.65mm, 44px at ~96dpi ≈ 11.6mm
        self.margin_l_mm = 2.65
        self.margin_r_mm = 2.65
        self.margin_t_mm = 2.65
        self.margin_b_mm = 2.65
        self.header_h_mm = 11.6
        self.footer_h_mm = 11.6

        # Preview default; printer/export will override this via set_target_dpi()
        self.target_dpi = 96

        # pixel fields will be computed
        self.page_w = 0
        self.page_h = 0
        self.header_h = 0
        self.footer_h = 0
        self.margin_l = 0
        self.margin_r = 0
        self.margin_t = 0
        self.margin_b = 0

        # content width placeholder (needed before _recompute_geometry runs)
        self.content_w = 0

        # -----------------------------
        # Locked configuration
        # -----------------------------

        # Borders / theme
        self.border_width = 2
        self.grid_line_color = self.BLUE
        self.divider_color = self.RED
        self.header_footer_border_color = self.BLUE

        # Data Name
        self.data_name_text = self.WHITE
        self.data_name_bg = self.BLACK
        self.data_border_color = self.BLACK

        # Table theme
        self.table_outer_color = self.BLACK
        self.table_inner_color = self.BLACK
        self.table_header_bg = self.BLUE
        self.table_header_text = self.WHITE
        self.table_cell_bg = self.RED
        self.table_cell_text = self.WHITE

        # Data-only toggles
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

        # Derived metrics
        self.cell_w = None
        self.cell_h = None
        self.col_widths = None
        self.row_heights = None

        # -----------------------------
        # Root layout with margins
        # -----------------------------
        self.root = QVBoxLayout(self)
        root = self.root
        # margins + content_w will be set in _recompute_geometry()

        # -----------------------------
        # Header (no bottom border)
        # -----------------------------
        self.header_frame = QFrame(self)
        # temporarily 0; real size set in _recompute_geometry()
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

        root.addWidget(self.header_frame)

        # -----------------------------
        # Grid wrapper (NO top line, grid, bottom line)
        # -----------------------------
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

        # bottom closing line (blue)
        self.grid_bottom_line = QFrame(self.grid_wrap)
        self.grid_bottom_line.setFixedSize(self.content_w, self.border_width)
        self.grid_bottom_line.setStyleSheet(f"background:{self.grid_line_color}; border:none;")
        grid_wrap_layout.addWidget(self.grid_bottom_line)

        root.addWidget(self.grid_wrap)

        # -----------------------------
        # Footer (no top border)
        # -----------------------------
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
        self.footer_right = QLabel("")

        self.footer_left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.footer_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.footer_left.setStyleSheet("border:none; color:#000; font-size:16pt; font-weight:600;")
        self.footer_right.setStyleSheet("border:none; color:#00FF00; font-size:16pt; font-weight:600;")

        fl.addWidget(self.footer_left, 1)
        fl.addWidget(self.footer_right, 1)

        root.addWidget(self.footer_frame)

        # runtime structures
        self._widgets = []
        self._struts = []

        # compute real sizes from mm + dpi and update all .setFixedSize/.setFixedWidth
        self._recompute_geometry()

        
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
        self._create_footer_corner_connectors()
        self.update()

    # -----------------------------
    # Footer corner connectors
    # -----------------------------
    def _create_footer_corner_connectors(self):
        """
        With footer border-top removed, sometimes there is a tiny corner discontinuity.
        These 2x2 connectors visually close the junction at bottom-left/bottom-right.
        """
        for attr in ("footer_corner_left", "footer_corner_right"):
            old = getattr(self, attr, None)
            if old is not None:
                old.deleteLater()

        y = self.grid_widget.height()  # bottom of grid_widget (top line removed)

        self.footer_corner_left = QFrame(self.grid_wrap)
        self.footer_corner_left.setFixedSize(self.border_width, self.border_width)
        self.footer_corner_left.setStyleSheet(f"background:{self.header_footer_border_color}; border:none;")
        self.footer_corner_left.move(0, y)
        self.footer_corner_left.show()

        self.footer_corner_right = QFrame(self.grid_wrap)
        self.footer_corner_right.setFixedSize(self.border_width, self.border_width)
        self.footer_corner_right.setStyleSheet(f"background:{self.header_footer_border_color}; border:none;")
        self.footer_corner_right.move(self.content_w - self.border_width, y)
        self.footer_corner_right.show()

    # -----------------------------
    # Header/Footer API
    # -----------------------------
    def set_header(self, company_code, master_title, page_number):
        self.header_left.setText(str(company_code or ""))
        self.header_center.setText(str(master_title or ""))
        self.header_right.setText(str(page_number or ""))

    def set_footer_left(self, text):
        self.footer_left.setText(str(text or ""))

    def set_footer_date(self, date_text):
        self.footer_right.setText(str(date_text or ""))

    def update_options(self, **options):
        if "show_moq" in options:
            self.show_moq = bool(options["show_moq"])
        if "show_master_packing" in options:
            self.show_master_packing = bool(options["show_master_packing"])

    # -----------------------------
    # Grid sizing (exact right edge alignment)
    # -----------------------------
    def _compute_fixed_grid_metrics(self):
        # Space inside margins between header and footer
        usable_h = (self.page_h - (self.margin_t + self.margin_b)) - self.header_h - self.footer_h

        # remove only the bottom closing line (top line removed)
        usable_h -= self.border_width

        usable_w = self.content_w

        # Distribute remainder so columns sum EXACTLY
        base_w = usable_w // self.page_cols
        rem_w = usable_w - (base_w * self.page_cols)
        self.col_widths = [base_w] * self.page_cols
        self.col_widths[-1] += rem_w

        # Distribute remainder so rows sum EXACTLY
        base_h = usable_h // self.page_rows
        rem_h = usable_h - (base_h * self.page_rows)
        self.row_heights = [base_h] * self.page_rows
        self.row_heights[-1] += rem_h

        self.grid_widget.setFixedSize(usable_w, usable_h)

        # Clear old struts
        for s in self._struts:
            try:
                self.grid_layout.removeWidget(s)
            except Exception:
                pass
            try:
                s.deleteLater()
            except Exception:
                pass
        self._struts = []

        # Force exact sizes with struts
        for c, w in enumerate(self.col_widths):
            self.grid_layout.setColumnMinimumWidth(c, w)
            self.grid_layout.setColumnStretch(c, 0)
            strut = QWidget()
            strut.setFixedSize(w, 1)
            strut.setStyleSheet("background:transparent; border:none;")
            self.grid_layout.addWidget(strut, 0, c, 1, 1)
            self._struts.append(strut)

        for r, h in enumerate(self.row_heights):
            self.grid_layout.setRowMinimumHeight(r, h)
            self.grid_layout.setRowStretch(r, 0)
            strut = QWidget()
            strut.setFixedSize(1, h)
            strut.setStyleSheet("background:transparent; border:none;")
            self.grid_layout.addWidget(strut, r, 0, 1, 1)
            self._struts.append(strut)

        self.cell_w = base_w
        self.cell_h = base_h

    # -----------------------------
    # Page rendering helpers
    # -----------------------------
    def clear_page(self):
        for w in self._widgets:
            try:
                self.grid_layout.removeWidget(w)
            except Exception:
                pass
            try:
                w.deleteLater()
            except Exception:
                pass
        self._widgets = []

    def fill_page(self, placeditems):
        # if placeditems:
            # it0 = placeditems[0]
            # print("[FILLPAGE] keys:", list(it0.keys()))
            # print("[FILLPAGE] rspan raw:", it0.get("rspan"), it0.get("r_span"))
            # print("[FILLPAGE] cspan raw:", it0.get("cspan"), it0.get("c_span"))


        self.clear_page()
        rows = self.page_rows
        cols = self.page_cols

        occ = [[False] * cols for _ in range(rows)]

        def canplace(rr, cc, rs, cs):
            if rr + rs > rows or cc + cs > cols:
                return False
            for r0 in range(rr, rr + rs):
                for c0 in range(cc, cc + cs):
                    if occ[r0][c0]:
                        return False
            return True

        def mark(rr, cc, rs, cs):
            for r0 in range(rr, rr + rs):
                for c0 in range(cc, cc + cs):
                    occ[r0][c0] = True

        def findspot(startrow, startcol, rs, cs):
            for rr in range(startrow, rows):
                for cc in range(startcol, cols - cs + 1):
                    if canplace(rr, cc, rs, cs):
                        return rr, cc
                startcol = 0
            return None

        for it in placeditems:
            prod = it.get("data") or {}

            preferredr = int(it.get("row", 0))
            preferredc = int(it.get("col", 0))

            rs = max(1, int(it.get("rspan", 1)))

            # IMPORTANT: builder sends TOTAL columns in cspan now
            total = max(2, int(it.get("cspan", 2)))
            total = min(total, cols)

            # Image span is total-1 (last column is data)
            H = total - 1
            H = max(1, min(H, cols - 1))

            preferredr = max(0, min(preferredr, rows - 1))
            preferredc = max(0, min(preferredc, cols - total))

            rs = max(1, min(rs, rows - preferredr))

            spot = findspot(preferredr, preferredc, rs, total)
            if not spot:
                continue

            r, c = spot
            mark(r, c, rs, total)

            cardrightedge = (c + total == cols)
            imgw = sum(self.col_widths[c:c + H])
            dataw = self.col_widths[c + H]
            blkh = sum(self.row_heights[r:r + rs])

            imgblock = self._img_block(imgw, blkh, prod, draw_right=False)
            datablock = self._data_block(dataw, blkh, prod, draw_right=cardrightedge)

            self.grid_layout.addWidget(imgblock, r, c, rs, H)
            self.grid_layout.addWidget(datablock, r, c + H, rs, 1)
            self._widgets.append(imgblock)
            self._widgets.append(datablock)

        # fill empties (keep your existing)
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

    # ============================================================
    # LOCKED borders (grid blue, divider red, no per-cell bottom)
    # ============================================================

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

        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0) 
        lay.setSpacing(0)
        
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        lbl.setStyleSheet("border:none;")

        # --- NEW IMAGE LOGIC ---
        image_path = prod.get("image_path", "")
        # if(not os.path.exists(image_path)):
        #     image_path=r'C:\Users\HP\Desktop\new_version\JK_Catalog\images\image.png'
        if image_path and os.path.exists(image_path):

            from PyQt6.QtGui import QImageReader, QPixmap

            reader = QImageReader(image_path)
            reader.setAutoTransform(True)  # apply EXIF orientation
            img = reader.read()
            
            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                pixmap = QPixmap.fromImage(img)

                scaled = pixmap.scaled(
                    w,
                    h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

                lbl.setPixmap(scaled)
                lbl.setScaledContents(False)
        # -----------------------
        lay.addWidget(lbl, 1)
        return f
    

    def _fmt_money(self,v):
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
        except Exception:
            return str(v)

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
        lay.addWidget(self.build_info_container(prod))
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

    # ============================================================
    # DATA ONLY (internal borders black + table colors)
    # ============================================================
    #  base unit no stretch
    def build_info_container(self, prod: dict) -> QWidget:

        container = QWidget()
        container.setStyleSheet("border:none; background:#ffffff;")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        name = QLabel(str(prod.get("product_name", "Unknown")))
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"font-size:{self.title_fs}pt; font-weight:700; color:{self.data_name_text}; background:{self.data_name_bg};"
            f"padding:{self.pad_title_v}px {self.pad_title_h}px;"
            f"border-bottom:{self.border_width}px solid {self.data_border_color};"
        )
        # Name can expand
        name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay.addWidget(name, 2)  # more stretch than before

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
            # IMPORTANT: base unit should NOT expand; keep it tight
            base_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lay.addWidget(base_lbl, 0)  # no stretch

        table = self.build_internal_table(prod)
        table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay.addWidget(table, 5)  # table gets most stretch

        bottom = QFrame()
        bottom.setStyleSheet(f"background:#ffffff;")
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


    def build_internal_table(self, prod: dict) -> QFrame:
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

            def style_cell(lbl: QLabel, col_idx: int):
                b_right = inner if col_idx != last_col_idx else "none"
                b_bottom = inner if row != total_rows else "none"
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    f"font-size:{self.cell_fs}pt;"
                    f"color:{self.table_cell_text}; background:{self.table_cell_bg};"
                    f"padding:{self.pad_cell_v}px {self.pad_cell_h}px;"
                    f"border:none; border-right:{b_right}; border-bottom:{b_bottom};"
                )

            l_size = QLabel(str(size)); style_cell(l_size, 0); lay.addWidget(l_size, row, 0)

            l_mrp = QLabel(self._fmt_money(mrp));  style_cell(l_mrp, 1); lay.addWidget(l_mrp, row, 1)

            if self.show_moq:
                l_moq = QLabel(str(moq)); style_cell(l_moq, 2); lay.addWidget(l_moq, row, 2)

        return table
    

