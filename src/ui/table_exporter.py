import os
import xlsxwriter
from PyQt6.QtWidgets import QMessageBox
from src.ui.table_nav_mixin import get_visual_text

def export_tables_to_excel(export_folder: str, filename: str, tables_data: list, parent=None, grid_cols=1, title_on_left=False):
    """
    Export one or more QTableWidgets to a single Excel sheet.
    tables_data: list of dicts with keys: 'title', 'table'
    """
    if not export_folder:
        if parent:
            QMessageBox.warning(parent, "Set Location", "Please set an export location first using the 'Set Location' button (or equivalent).")
        return False

    path = os.path.join(export_folder, filename)
    
    try:
        workbook = xlsxwriter.Workbook(path)
        sheet = workbook.add_worksheet("Data")
        
        bold_format = workbook.add_format({'bold': True})
        title_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 13,
            'bg_color': '#f8fafc',
            'border': 1
        })
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#f1f5f9',
            'border': 1
        })
        cell_format = workbook.add_format({'border': 1})
        
        # Track the maximum row used in each column so we know where to place the next item
        # We divide the layout into `grid_cols` columns.
        col_max_rows = [0] * grid_cols
        
        for i, table_info in enumerate(tables_data):
            title = table_info.get("title")
            table = table_info.get("table")
            
            # Find the grid column with the minimum height
            grid_c = col_max_rows.index(min(col_max_rows))
            
            # Start position
            current_row = col_max_rows[grid_c]
            
            # Determine how many columns this item takes
            col_count = table.columnCount()
            total_cols_needed = col_count + (1 if title_on_left and title else 0)
            
            # Assuming each grid column gets spaced by a fixed gap (e.g. 1 blank col)
            # Find the starting excel column for this grid column
            # We'll calculate it by looking at previous items, but for simplicity, 
            # let's just make each grid column a fixed width of max cols
            max_cols_per_grid = max([t.get("table").columnCount() + (1 if title_on_left else 0) for t in tables_data], default=1)
            start_col = grid_c * (max_cols_per_grid + 1)
            
            title_written = False
            
            if title:
                if title_on_left:
                    # Write title on the left, spanning all rows of the table
                    row_count = table.rowCount()
                    end_row = current_row + max(row_count - 1, 0)
                    if table.horizontalHeader().isVisible():
                        end_row += 1 # account for header row
                    if end_row > current_row:
                        sheet.merge_range(current_row, start_col, end_row, start_col, title, title_format)
                    else:
                        sheet.write(current_row, start_col, title, title_format)
                    
                    # Shift table to the right
                    start_col += 1
                    title_written = True
                else:
                    # Write title above the table
                    end_col = start_col + max(col_count - 1, 0)
                    if end_col > start_col:
                        sheet.merge_range(current_row, start_col, current_row, end_col, title, title_format)
                    else:
                        sheet.write(current_row, start_col, title, title_format)
                    current_row += 1
                
            # Write Headers (only if visible)
            if table.horizontalHeader().isVisible():
                for c in range(col_count):
                    h_item = table.horizontalHeaderItem(c)
                    h_text = h_item.text() if h_item else f"Col {c}"
                    sheet.write(current_row, start_col + c, h_text, header_format)
                current_row += 1
            
            # Write Data
            row_count = table.rowCount()
            for r in range(row_count):
                is_empty = True
                row_data = []
                for c in range(col_count):
                    val = get_visual_text(table, r, c)
                    row_data.append(val)
                    if val:
                        is_empty = False
                
                # If we have title on left, we MUST write even empty rows to maintain alignment
                if not is_empty or title_on_left:
                    for c, val in enumerate(row_data):
                        try:
                            if val and val.replace('.','',1).isdigit():
                                sheet.write_number(current_row, start_col + c, float(val), cell_format)
                            else:
                                sheet.write(current_row, start_col + c, val, cell_format)
                        except:
                            sheet.write(current_row, start_col + c, val, cell_format)
                    current_row += 1
            
            # Blank spacer row between tables
            current_row += 2
            
            # Update the max row tracker for this grid column
            col_max_rows[grid_c] = current_row
            
        workbook.close()
        return True
        
    except Exception as e:
        if parent:
            QMessageBox.critical(parent, "Export Error", f"Failed to export Excel:\n{str(e)}")
        else:
            print(f"[Export Error] {e}")
        return False
