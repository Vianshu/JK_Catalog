import sqlite3
import os

# Define the exact path provided by the user
db_path = r"C:\Users\HP\Desktop\CATALOG UPDATE V1.0\CheckData\final_data.db"

if not os.path.exists(db_path):
    print(f"ERROR: Database not found at {db_path}")
    exit()

print(f"--- TESTING SUMMARY CALCULATION ---")
print(f"Database: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Final Data Total (Simple Count)
    final_data_total = cursor.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] or 0
    print(f"\n1. Final Data Total (All Rows): {final_data_total}")

    # 2. Catalog Total
    # Logic: TF='1' OR (TF is Empty AND Stock > 0)
    # Note: We use CASE INSENSITIVE checks for '1', 'true', 'yes'
    catalog_total_query = """
        SELECT COUNT(*) FROM catalog 
        WHERE (LOWER(TRIM(CAST([True/False] AS TEXT))) IN ('1', 'true', 'yes'))
        OR (
            (IFNULL(TRIM([True/False]), '') = '') 
            AND (IFNULL(CAST(REPLACE(REPLACE(Stock, ',', ''), ' ', '') AS REAL), 0) > 0)
        )
    """
    catalog_total = cursor.execute(catalog_total_query).fetchone()[0] or 0
    print(f"2. Catalog Total (TF='1' or (Empty & Stock>0)): {catalog_total}")

    # 3. Out of Stock (Excluded)
    # Logic: Stock <= 0 AND TF is Empty
    # (Items that WOULD have been included if they had stock, but are excluded due to lack of stock)
    out_of_stock_query = """
        SELECT COUNT(*) FROM catalog 
        WHERE (IFNULL(CAST(REPLACE(REPLACE(Stock, ',', ''), ' ', '') AS REAL), 0) <= 0)
        AND (IFNULL(TRIM([True/False]), '') = '')
    """
    out_of_stock = cursor.execute(out_of_stock_query).fetchone()[0] or 0
    print(f"3. Excluded (Stock): {out_of_stock}")

    # 4. Manual False
    # Logic: TF is explicitly 'false', '0', 'no'
    manual_false_query = """
        SELECT COUNT(*) FROM catalog 
        WHERE LOWER(TRIM(CAST([True/False] AS TEXT))) IN ('false', '0', 'no')
    """
    manual_false = cursor.execute(manual_false_query).fetchone()[0] or 0
    print(f"4. Manual False (Explicit 'false'): {manual_false}")

    # 5. Mismatch Check
    # Total = Catalog + Excluded(Stock) + Manual False + Mismatch
    sum_parts = catalog_total + out_of_stock + manual_false
    mismatch = final_data_total - sum_parts
    print(f"\n--- CALCULATION CHECK ---")
    print(f"Sum of Parts (2+3+4): {sum_parts}")
    print(f"Mismatch (Total - Sum): {mismatch}")

    conn.close()

except Exception as e:
    print(f"Error: {e}")
