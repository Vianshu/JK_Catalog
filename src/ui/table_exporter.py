import os
import xlsxwriter
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QColor
from src.ui.table_nav_mixin import get_visual_text
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


def _round_int(val: str) -> str:
    """Try to parse val as a float and return as rounded int string. Returns val unchanged on failure."""
    try:
        cleaned = val.replace(",", "").strip()
        f = float(cleaned)
        return str(int(round(f)))
    except Exception:
        return val


def _qt_color_to_hex(qt_color) -> str | None:
    """Convert a QColor or QBrush to a hex string like '#rrggbb', or None if it's default/white."""
    try:
        if hasattr(qt_color, "color"):
            qt_color = qt_color.color()   # QBrush -> QColor
        if not isinstance(qt_color, QColor) or not qt_color.isValid():
            return None
        r, g, b = qt_color.red(), qt_color.green(), qt_color.blue()
        if (r, g, b) == (255, 255, 255) or (r, g, b) == (0, 0, 0):
            return None  # skip default white/black backgrounds
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None


def export_tables_to_excel(export_folder: str, filename: str, tables_data: list,
                           parent=None, grid_cols=1, title_on_left=False):
    """
    Export one or more QTableWidgets to a single Excel sheet.
    tables_data: list of dicts with keys:
      - 'title': str
      - 'table': QTableWidget
      - 'grid_col': int (optional, explicit grid column)
      - 'header_color': str (optional, hex color for the header row, e.g. '#dbeafe')
      - 'round_int_cols': set of column indices to round to nearest integer
    """
    if not export_folder:
        if parent:
            QMessageBox.warning(parent, "Set Location",
                                "Please set an export location first using the 'Set Location' button (or equivalent).")
        return False

    path = os.path.join(export_folder, filename)

    try:
        workbook = xlsxwriter.Workbook(path)
        sheet = workbook.add_worksheet("Data")

        # Format cache: keyed by (bold, bg_color_hex_or_None, border)
        _fmt_cache = {}

        def _get_fmt(bold=False, bg=None, border=1, align_right=False, num_format=None):
            key = (bold, bg, border, align_right, num_format)
            if key not in _fmt_cache:
                props = {"border": border}
                if bold:
                    props["bold"] = True
                if bg:
                    props["bg_color"] = bg
                if align_right:
                    props["align"] = "right"
                if num_format:
                    props["num_format"] = num_format
                _fmt_cache[key] = workbook.add_format(props)
            return _fmt_cache[key]

        title_format = workbook.add_format({
            "bold": True, "align": "center", "valign": "vcenter",
            "font_size": 13, "bg_color": "#f8fafc", "border": 1
        })

        # Pre-compute per-grid-column widths when explicit grid_col is used,
        # so we get exactly 1 blank separator column between grid columns.
        grid_col_starts = {}  # grid_col_index -> excel start column
        has_explicit_gc = any("grid_col" in t for t in tables_data)
        if has_explicit_gc:
            per_gc_max = {}  # grid_col -> max table col count in that column
            for t in tables_data:
                gc = min(t.get("grid_col", 0), grid_cols - 1)
                tbl = t.get("table")
                n = len([c for c in range(tbl.columnCount()) if not tbl.isColumnHidden(c)]) + (1 if not tbl.verticalHeader().isHidden() else 0) + (1 if title_on_left else 0)
                per_gc_max[gc] = max(per_gc_max.get(gc, 0), n)
            offset = 0
            for gc in range(grid_cols):
                grid_col_starts[gc] = offset
                offset += per_gc_max.get(gc, 0) + 1  # +1 = exactly one blank separator col

        # Track the maximum row used in each column so we know where to place the next item
        col_max_rows = [0] * grid_cols

        for i, table_info in enumerate(tables_data):
            title          = table_info.get("title")
            table          = table_info.get("table")
            header_color   = table_info.get("header_color", "#f1f5f9")
            round_int_cols = set(table_info.get("round_int_cols", []))
            no_border_cells = set(table_info.get("no_border_cells", [])) # set of (r, c)
            
            merged_cells_to_skip = set()

            # Use explicit grid_col if provided, otherwise pick the shortest column
            if "grid_col" in table_info:
                grid_c = min(table_info["grid_col"], grid_cols - 1)
                start_col = grid_col_starts[grid_c]
            else:
                grid_c = col_max_rows.index(min(col_max_rows))
                # For auto-placement, use even spacing based on widest table
                max_cols_per_grid = max(
                    [len([c for c in range(t.get("table").columnCount()) if not t.get("table").isColumnHidden(c)]) + (1 if not t.get("table").verticalHeader().isHidden() else 0) + (1 if title_on_left else 0) for t in tables_data],
                    default=1
                )
                start_col = grid_c * (max_cols_per_grid + 1)


            current_row = col_max_rows[grid_c]

            valid_cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
            include_sn = not table.verticalHeader().isHidden()
            total_cols = len(valid_cols) + (1 if include_sn else 0)

            if title:
                if title_on_left:
                    row_count = table.rowCount()
                    end_row = current_row + max(row_count - 1, 0)
                    if not table.horizontalHeader().isHidden():
                        end_row += 1
                    if end_row > current_row:
                        sheet.merge_range(current_row, start_col, end_row, start_col, title, title_format)
                    else:
                        sheet.write(current_row, start_col, title, title_format)
                    start_col += 1
                else:
                    end_col = start_col + max(total_cols - 1, 0)
                    if end_col > start_col:
                        sheet.merge_range(current_row, start_col, current_row, end_col, title, title_format)
                    else:
                        sheet.write(current_row, start_col, title, title_format)
                    current_row += 1

            # Write Headers
            if not table.horizontalHeader().isHidden():
                hdr_fmt = _get_fmt(bold=True, bg=header_color or "#f1f5f9", border=1)
                cur_c = start_col
                if include_sn:
                    sheet.write(current_row, cur_c, "S.N", hdr_fmt)
                    cur_c += 1
                for c in valid_cols:
                    h_item = table.horizontalHeaderItem(c)
                    h_text = h_item.text() if h_item else f"Col {c}"
                    sheet.write(current_row, cur_c, h_text, hdr_fmt)
                    cur_c += 1
                current_row += 1

            # Write Data
            row_count = table.rowCount()
            for r in range(row_count):
                is_empty = True
                row_data  = []
                row_bgs   = []
                if include_sn:
                    row_data.append(str(r + 1))
                    row_bgs.append(None)
                for c in valid_cols:
                    val = get_visual_text(table, r, c)
                    # Round to int for specified columns
                    if val and c in round_int_cols:
                        val = _round_int(val)
                    row_data.append(val)
                    if val:
                        is_empty = False

                    # Read cell background color
                    item = table.item(r, c)
                    bg_hex = None
                    if item:
                        bg_hex = _qt_color_to_hex(item.background())
                    row_bgs.append(bg_hex)

                if not is_empty or title_on_left:
                    for out_idx, val in enumerate(row_data):
                        cur_out_col = start_col + out_idx
                        if (current_row, cur_out_col) in merged_cells_to_skip:
                            continue
                            
                        bg_hex = row_bgs[out_idx]
                        is_num = bool(val and val.replace(".", "", 1).replace(",", "").replace("-", "", 1).isdigit())
                        
                        c_orig = valid_cols[out_idx - 1] if (include_sn and out_idx > 0) else (valid_cols[out_idx] if not include_sn else -1)
                        has_border = 0 if (c_orig >= 0 and (r, c_orig) in no_border_cells) else 1
                        num_fmt = "#,##0" if is_num else None
                        fmt = _get_fmt(bg=bg_hex, border=has_border, align_right=is_num, num_format=num_fmt)
                        
                        r_span = table.rowSpan(r, c_orig) if c_orig >= 0 else 1
                        c_span = table.columnSpan(r, c_orig) if c_orig >= 0 else 1
                        
                        # Apply merge
                        if r_span > 1 or c_span > 1:
                            for rr in range(r_span):
                                for cc in range(c_span):
                                    if rr == 0 and cc == 0: continue
                                    merged_cells_to_skip.add((current_row + rr, cur_out_col + cc))
                            
                            # Write merge range
                            try:
                                if is_num:
                                    num_val = float(val.replace(",", ""))
                                    if c_orig >= 0 and c_orig in round_int_cols:
                                        num_val = int(round(num_val))
                                    sheet.merge_range(current_row, cur_out_col, current_row + r_span - 1, cur_out_col + c_span - 1, num_val, fmt)
                                else:
                                    sheet.merge_range(current_row, cur_out_col, current_row + r_span - 1, cur_out_col + c_span - 1, val, fmt)
                            except Exception:
                                sheet.merge_range(current_row, cur_out_col, current_row + r_span - 1, cur_out_col + c_span - 1, val or "", fmt)
                            continue

                        try:
                            if is_num:
                                num_val = float(val.replace(",", ""))
                                if c_orig >= 0 and c_orig in round_int_cols:
                                    sheet.write_number(current_row, cur_out_col, int(round(num_val)), fmt)
                                else:
                                    sheet.write_number(current_row, cur_out_col, num_val, fmt)
                            else:
                                sheet.write(current_row, cur_out_col, val, fmt)
                        except Exception:
                            sheet.write(current_row, cur_out_col, val or "", fmt)
                    current_row += 1

            # Blank spacer row between tables
            current_row += 2

            col_max_rows[grid_c] = current_row

        workbook.close()
        return True

    except Exception as e:
        logger.error(f"[Export Error] {e}")
        if parent:
            QMessageBox.critical(parent, "Export Error", f"Failed to export Excel:\n{str(e)}")
        return False
