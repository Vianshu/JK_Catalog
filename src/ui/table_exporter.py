import os
import xlsxwriter
from PyQt6.QtWidgets import QMessageBox
from src.ui.table_nav_mixin import get_visual_text

def export_tables_to_excel(export_folder: str, filename: str, tables_data: list, parent=None, two_column=False):
    """
    Export one or more QTableWidgets to a single Excel sheet.
    tables_data: list of tuples (title_string_or_None, QTableWidget)
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
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#f1f5f9',
            'border': 1
        })
        cell_format = workbook.add_format({'border': 1})
        
        # Calculate offset for right column if two_column mode is on
        right_col_start = 0
        if two_column and tables_data:
            # Maximum columns across all even-indexed (left) tables
            max_left_cols = max((table_info.get("table").columnCount() for i, table_info in enumerate(tables_data) if i % 2 == 0), default=0)
            right_col_start = max_left_cols + 1  # 1 column gap

        left_row = 0
        right_row = 0
        
        for i, table_info in enumerate(tables_data):
            title = table_info.get("title")
            table = table_info.get("table")
            
            # Determine starting row and col based on two_column mode
            is_right = two_column and (i % 2 != 0)
            current_row = right_row if is_right else left_row
            start_col = right_col_start if is_right else 0

            if title:
                sheet.write(current_row, start_col, title, bold_format)
                current_row += 1
                
            # Write Headers (only if visible)
            col_count = table.columnCount()
            if table.horizontalHeader().isVisible():
                for c in range(col_count):
                    h_item = table.horizontalHeaderItem(c)
                    h_text = h_item.text() if h_item else f"Col {c}"
                    sheet.write(current_row, start_col + c, h_text, header_format)
                current_row += 1
            
            # Write Data (skip completely empty rows)
            row_count = table.rowCount()
            for r in range(row_count):
                # Check if row has data
                is_empty = True
                row_data = []
                for c in range(col_count):
                    val = get_visual_text(table, r, c)
                    row_data.append(val)
                    if val:
                        is_empty = False
                
                if not is_empty:
                    for c, val in enumerate(row_data):
                        # Attempt to write as number if possible, else string
                        try:
                            # Only if it looks like a clean number
                            if val and val.replace('.','',1).isdigit():
                                sheet.write_number(current_row, start_col + c, float(val), cell_format)
                            else:
                                sheet.write(current_row, start_col + c, val, cell_format)
                        except:
                            sheet.write(current_row, start_col + c, val, cell_format)
                    current_row += 1
            
            # Blank spacer row between tables
            current_row += 2
            
            # Update the correct row tracker
            if is_right:
                right_row = current_row
            else:
                left_row = current_row
            
        workbook.close()
        return True
        
    except Exception as e:
        if parent:
            QMessageBox.critical(parent, "Export Error", f"Failed to export Excel:\n{str(e)}")
        else:
            print(f"[Export Error] {e}")
        return False
