"""
Named column constants for the FinalData table.

Replaces hardcoded numeric indices (e.g., column 5, column 21)
with readable names. This prevents bugs when columns are reordered
and makes the code self-documenting.

Usage:
    from src.logic.column_constants import COL
    
    value = self.table.item(row, COL.PRODUCT_NAME).text()
    # Instead of: self.table.item(row, 5).text()
"""


class _ColumnIndex:
    """Column index mapping for the final_data table."""
    
    # These match the order in FinalDataUI.headers
    GUID = 0
    ID = 1
    ITEM_NAME = 2
    ALIAS = 3
    PART_NO = 4
    PRODUCT_NAME = 5
    PRODUCT_SIZE = 6
    CATEGORY = 7
    UNIT = 8
    MOQ = 9
    M_PACKING = 10
    MRP = 11
    STOCK = 12
    MG_SN = 13
    GROUP = 14
    SG_SN = 15
    SUB_GROUP = 16
    IMAGE_NAME = 17
    IMAGE_PATH = 18
    LENGTH = 19       # Note: DB column is "Lenth" (typo preserved)
    IMAGE_DATE = 20
    TRUE_FALSE = 21
    UPDATE_DATE = 22
    
    # Total column count
    COUNT = 23
    
    # Column names as they appear in the DB/headers
    # Useful for building SQL queries
    DB_NAMES = [
        "GUID", "ID", "Item_Name", "Alias", "Part_No", "Product Name",
        "Product_Size", "Category", "Unit", "MOQ", "M_Packing", "MRP",
        "Stock", "MG_SN", "Group", "SG_SN", "Sub_Group", "Image_Name",
        "Image_Path", "Lenth", "Image_Date", "True/False", "Update_date"
    ]


# Singleton instance — import this
COL = _ColumnIndex()
