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

_cache = _TablePrinterCache()

def print_tables_via_preview(tables_data: list, parent, title="Print Preview", landscape=True):
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
        show_headers = table.horizontalHeader().isVisible()
        truncate_groups = table_info.get("truncate_groups", [])
        
        # Collect all rows
        data_rows = []
        for r in range(table.rowCount()):
            if table.isRowHidden(r):
                continue
            
            row_data = [get_visual_text(table, r, c) for c in range(table.columnCount())]
            if any(v.strip() for v in row_data):
                data_rows.append(row_data)
                
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
        if not pages:
            pages.append([])
            used = 0
        elif used + table_h > page_h:
            # This supplier won't fit — start a fresh page
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
            pages[-1].append(("header", active_headers, col_widths, header_height))
            used += header_height

        for rd in active_data:
            if used + row_height > page_h:
                pages.append([])
                used = 0
                # Reprint header on the new page so the reader knows what each column is
                if show_headers:
                    pages[-1].append(("header", active_headers, col_widths, header_height))
                    used += header_height

            pages[-1].append(("row", rd, col_widths, row_height))
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
                _, col_texts, col_widths, height = item
                painter.setFont(header_font)
                painter.setPen(pen)
                x = 0
                for c, text in enumerate(col_texts):
                    rect = QRect(x, y, col_widths[c], height)
                    painter.fillRect(rect, QColor(220, 220, 220))
                    painter.drawRect(rect)
                    text_rect = QRect(x + h_pad, y, col_widths[c] - 2 * h_pad, height)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)
                    x += col_widths[c]
                y += height
            elif item_type == "row":
                _, col_texts, col_widths, height = item
                painter.setFont(cell_font)
                painter.setPen(pen)
                x = 0
                for c, text in enumerate(col_texts):
                    rect = QRect(x, y, col_widths[c], height)
                    painter.drawRect(rect)
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
