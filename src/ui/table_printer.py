from PyQt6.QtGui import QPainter, QFont, QColor, QPen, QPageLayout, QPageSize
from PyQt6.QtWidgets import QLineEdit, QDialog
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPrintDialog
from PyQt6.QtCore import Qt, QRect, QMarginsF
from src.ui.table_nav_mixin import get_visual_text

class _TablePrinterCache:
    """Internal cache to hold the pre-calculated pages so the custom print dialog can use them."""
    def __init__(self):
        self.pages = []
        self.printer = None
        self.preview_ref = None
        self.current_title = ""
        self.tables_data = []
        self.no_border_cols = []

_cache = _TablePrinterCache()

def print_tables_via_preview(tables_data: list, parent, title="Print Preview", landscape=True, no_border_cols=None):
    """
    Open a QPrintPreviewDialog to print one or more QTableWidgets sequentially.
    tables_data: list of dicts with keys:
      - 'title': str (optional title above table)
      - 'table': QTableWidget
      - 'truncate_groups': list of tuples of column indices (optional). If the table is too wide
                           to fit on the page, groups are popped from the END of this list, and those
                           columns are dropped, until the table fits.
    """
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    if landscape:
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    else:
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(
        QMarginsF(5, 5, 5, 5),
        QPageLayout.Unit.Millimeter
    )

    _cache.tables_data = tables_data
    _cache.no_border_cols = no_border_cols or []
    _cache.printer = printer
    _cache.current_title = title
    _cache.pages = []

    preview = QPrintPreviewDialog(printer, parent)
    _cache.preview_ref = preview

    preview.paintRequested.connect(_paint_tables)

    from PyQt6.QtWidgets import QToolBar
    for toolbar in preview.findChildren(QToolBar):
        for action in toolbar.actions():
            tip = (action.toolTip() or "").lower()
            txt = (action.text() or "").replace("&", "").strip().lower()
            if tip == "print" or txt == "print":
                action.triggered.disconnect()
                action.triggered.connect(_custom_print_from_preview)
                break

    preview.resize(900, 680)
    preview.exec()


def _custom_print_from_preview():
    total = len(_cache.pages) if _cache.pages else 1
    printer = _cache.printer

    dlg = QPrintDialog(printer, _cache.preview_ref)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange)
    dlg.setMinMax(1, total)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    fp = printer.fromPage()
    tp = printer.toPage()
    if fp == 0 or tp == 0:
        start_pg, end_pg = 0, total - 1
    else:
        start_pg = max(0, fp - 1)
        end_pg   = min(tp - 1, total - 1)

    _paint_tables(printer, page_range=(start_pg, end_pg))


def _paint_tables(printer, page_range=None):
    painter = QPainter()
    if not painter.begin(printer):
        return

    page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
    page_w = page_rect.width()
    page_h = page_rect.height()

    title_font = QFont("Noto Sans Devanagari", 15, QFont.Weight.Bold)
    header_font = QFont("Noto Sans Devanagari", 13, QFont.Weight.Normal)
    cell_font = QFont("Noto Sans Devanagari", 12)

    painter.setFont(title_font)
    title_height = int(painter.fontMetrics().height() * 1.5)

    painter.setFont(header_font)
    fm_h = painter.fontMetrics()
    header_height = int(fm_h.height() * 1.2)

    painter.setFont(cell_font)
    fm_cell = painter.fontMetrics()
    row_height = int(fm_cell.height() * 1.1)
    h_pad = int(fm_cell.averageCharWidth() * 0.3)

    pages = []  # list of lists of draw items for each physical page
    # NOTE: The global title (_cache.current_title) is drawn *outside* the pages[]
    # structure, directly on page 0 during the render pass. To prevent items on
    # page 0 from overflowing onto the title area, we pre-account for its height
    # when tracking 'used' space for the very first page.

    # We will build physical pages.
    # Each physical page contains a list of "items" to draw:
    # ("title", text, y)
    # ("header", col_texts, col_widths, y)
    # ("row", col_texts, col_widths, y)
    
    # We loop over tables, calculating widths, dropping columns if needed.
    for table_info in _cache.tables_data:
        t_title = table_info.get("title", "")
        table = table_info.get("table")
        show_headers = not table.horizontalHeader().isHidden()
        truncate_groups = table_info.get("truncate_groups", [])
        
        # Collect all rows (with bg colors and rounding)
        round_int_cols = set(table_info.get("round_int_cols", []))
        header_color   = table_info.get("header_color", None)  # hex string like '#dbeafe'
        no_h_borders   = table_info.get("no_h_borders", set())
        
        data_rows = []
        data_row_bgs = []  # parallel list: list of per-cell (r,g,b) tuples or None
        data_row_noh = []  # parallel list: list of booleans indicating if horizontal borders are hidden
        
        for r in range(table.rowCount()):
            if table.isRowHidden(r):
                continue
            row_data = []
            row_bgs  = []
            row_noh  = []
            for c in range(table.columnCount()):
                val = get_visual_text(table, r, c)
                if val and c in round_int_cols:
                    try:
                        f = float(val.replace(",", "").strip())
                        val = str(int(round(f)))
                    except Exception:
                        pass
                row_data.append(val)
                row_noh.append((r, c) in no_h_borders)
                
                item = table.item(r, c)
                if item:
                    brush = item.background()
                    if brush.style() != Qt.BrushStyle.NoBrush:
                        bg = brush.color()
                        if bg.isValid() and bg.red() + bg.green() + bg.blue() < 760:  # skip near-white
                            row_bgs.append((bg.red(), bg.green(), bg.blue()))
                        else:
                            row_bgs.append(None)
                    else:
                        row_bgs.append(None)
                else:
                    row_bgs.append(None)
            # ALWAYS keep empty rows for visual spacing!
            data_rows.append(row_data)
            data_row_bgs.append(row_bgs)
            data_row_noh.append(row_noh)
                
        # Calculate raw widths for all columns
        all_cols = list(range(table.columnCount()))
        headers = []
        for c in range(table.columnCount()):
            h_item = table.horizontalHeaderItem(c)
            headers.append(h_item.text() if h_item else f"Col {c}")
            
        def measure_widths(active_cols):
            widths = []
            for c in active_cols:
                max_w = fm_h.horizontalAdvance(headers[c]) + 2 * h_pad
                for rd in data_rows:
                    w = fm_cell.horizontalAdvance(rd[c]) + 2 * h_pad
                    if w > max_w:
                        max_w = w
                widths.append(max(max_w, h_pad * 3))
            return widths
            
        active_cols = all_cols[:]
        # If caller specifies a col_range, restrict to those columns only
        col_range = table_info.get("col_range", None)
        if col_range is not None:
            active_cols = [c for c in active_cols if c in col_range]
        raw_widths = measure_widths(active_cols)
        
        # Truncate logic
        if truncate_groups:
            # groups are prioritized, we pop from the end (rightmost) if it doesn't fit
            tg = list(truncate_groups)
            while sum(raw_widths) > page_w and tg:
                drop_group = tg.pop() # remove lowest priority (rightmost)
                active_cols = [c for c in active_cols if c not in drop_group]
                raw_widths = measure_widths(active_cols)
                
        total_raw = sum(raw_widths) or 1
        # Scale to fit page_w if it still exceeds or if we want to expand it
        col_widths = [int(page_w * w / total_raw) for w in raw_widths]
        if col_widths:
            col_widths[-1] = page_w - sum(col_widths[:-1])
            
        # Filter headers and data
        active_headers = [headers[c] for c in active_cols]
        active_data = [[rd[c] for c in active_cols] for rd in data_rows]
        active_data_bgs = [[row_bgs[c] for c in active_cols] for row_bgs in data_row_bgs]
        active_data_noh = [[row_noh[c] for c in active_cols] for row_noh in data_row_noh]
        
        # --- Measure the height this supplier table would occupy ---
        table_h = 0
        if t_title:
            table_h += title_height
        if show_headers:
            table_h += header_height
        table_h += len(active_data) * row_height
        # account for the spacer gap after each supplier
        table_h += row_height  # conservative spacer

        # Pagination — smart bin-packing: start a new page only if the table
        # doesn't fit on the current page (avoids one-supplier-per-page waste).
        # We also respect explicit page breaks requested by the caller.
        force_break = table_info.get("page_break_before", False)
        
        if not pages:
            pages.append([])
            used = 0
        elif (used + table_h > page_h) or (force_break and used > 0):
            # This table won't fit, or a page break was explicitly requested
            pages.append([])
            used = 0

        if t_title:
            if used + title_height > page_h:
                pages.append([])
                used = 0
            pages[-1].append(("title", t_title, title_height))
            used += title_height

        if show_headers:
            if used + header_height > page_h:
                pages.append([])
                used = 0
            pages[-1].append(("header", active_headers, col_widths, header_height, header_color))
            used += header_height

        for rd_idx, rd in enumerate(active_data):
            rd_bgs = active_data_bgs[rd_idx]
            rd_noh = active_data_noh[rd_idx]
            if used + row_height > page_h:
                pages.append([])
                used = 0
                # Reprint header on the new page so the reader knows what each column is
                if show_headers:
                    pages[-1].append(("header", active_headers, col_widths, header_height, header_color))
                    used += header_height

            pages[-1].append(("row", rd, col_widths, row_height, rd_bgs, rd_noh))
            used += row_height

        # Add a visible gap between suppliers if there is room on the current page
        if used + title_height <= page_h:
            pages[-1].append(("spacer", None, title_height))
            used += title_height

    _cache.pages = pages
    total_pages = len(pages)

    # Guard: nothing to print
    if total_pages == 0 or not pages:
        painter.end()
        return

    if page_range is None:
        start_pg, end_pg = 0, total_pages - 1
    else:
        start_pg, end_pg = page_range[0], min(page_range[1], total_pages - 1)

    pen = QPen(QColor(0, 0, 0), 2)
    
    first = True
    for pg_idx in range(start_pg, end_pg + 1):
        if not first:
            printer.newPage()
        first = False
        
        y = 0
            
        for item in pages[pg_idx]:
            item_type = item[0]
            if item_type == "title":
                _, text, height = item
                painter.setFont(title_font)
                painter.setPen(pen)
                rect = QRect(0, y, page_w, height)
                painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)
                y += height
            elif item_type == "header":
                _, col_texts, col_widths, height, *_hdr_extra = item
                hdr_color_hex = _hdr_extra[0] if _hdr_extra else None
                if hdr_color_hex:
                    try:
                        hdr_fill = QColor(hdr_color_hex)
                    except Exception:
                        hdr_fill = QColor(220, 220, 220)
                else:
                    hdr_fill = QColor(220, 220, 220)
                painter.setFont(header_font)
                painter.setPen(pen)
                
                c = 0
                x = 0
                while c < len(col_texts):
                    text = col_texts[c]
                    span = 1
                    span_w = col_widths[c]
                    while c + span < len(col_texts) and col_texts[c+span] == "":
                        span_w += col_widths[c+span]
                        span += 1
                        
                    rect = QRect(x, y, span_w, height)
                    if text.strip():
                        painter.fillRect(rect, hdr_fill)
                        painter.drawRect(rect)
                        
                    text_rect = QRect(x + h_pad, y, span_w - 2 * h_pad, height)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)
                    
                    x += span_w
                    c += span
                y += height
            elif item_type == "row":
                _, col_texts, col_widths, height, *_row_extra = item
                rd_bgs = _row_extra[0] if len(_row_extra) > 0 else None
                rd_noh = _row_extra[1] if len(_row_extra) > 1 else None
                painter.setFont(cell_font)
                painter.setPen(pen)
                x = 0
                is_empty = not any(v.strip() for v in col_texts)
                for c, text in enumerate(col_texts):
                    rect = QRect(x, y, col_widths[c], height)
                    
                    if not is_empty:
                        # Apply cell background color if present
                        cell_bg = rd_bgs[c] if rd_bgs and c < len(rd_bgs) else None
                        if cell_bg:
                            painter.fillRect(rect, QColor(*cell_bg))
                            
                        hide_h = (rd_noh[c] if rd_noh and c < len(rd_noh) else False)
                        
                        if c in _cache.no_border_cols:
                            # Only draw vertical sides
                            painter.drawLine(x, y, x, y + height)           # left
                            painter.drawLine(x + col_widths[c], y, x + col_widths[c], y + height)  # right
                        else:
                            # Always draw vertical sides
                            painter.drawLine(x, y, x, y + height)           # left
                            painter.drawLine(x + col_widths[c], y, x + col_widths[c], y + height)  # right
                            
                            # For horizontal lines, we only draw them if they are not explicitly hidden.
                            # To prevent double-drawing or overlapping with a cell that WANTS it hidden,
                            # we look at the row index.
                            
                            # We can check the previous and next row's `hide_h` status if we look at `active_data_noh`.
                            # rd_idx is available.
                            prev_hide_h = active_data_noh[rd_idx - 1][c] if rd_idx > 0 else False
                            next_hide_h = active_data_noh[rd_idx + 1][c] if rd_idx < len(active_data_noh) - 1 else False
                            
                            # We draw the TOP line if WE don't hide it AND the PREV doesn't hide it.
                            if not hide_h and not prev_hide_h:
                                painter.drawLine(x, y, x + col_widths[c], y)
                            
                            # We draw the BOTTOM line if WE don't hide it AND the NEXT doesn't hide it.
                            if not hide_h and not next_hide_h:
                                painter.drawLine(x, y + height, x + col_widths[c], y + height)
                    # Empty rows: draw nothing (acts as spacer)
                            
                    text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, height)
                    
                    # Try to align numbers to the right (handling commas and negatives)
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    if text:
                        clean_text = text.replace('.', '', 1).replace(',', '').replace('-', '', 1)
                        if clean_text.isdigit():
                            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

                        
                    painter.drawText(text_rect, align, text)
                    x += col_widths[c]
                y += height
            elif item_type == "spacer":
                _, _, height = item
                y += height
                
    painter.end()
