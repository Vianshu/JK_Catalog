import sqlite3
import os

db_path = r"data\NGT Branch (2082_83)\final_data.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("--- Checking Columns in catalog table ---")
try:
    cur.execute("PRAGMA table_info(catalog)")
    cols = [c[1] for c in cur.fetchall()]
    print(f"Columns: {cols}")
    
    required = ["Product Name", "Item_Name", "Image_Path", "Length", "MRP"]
    for r in required:
        if r not in cols:
            print(f"❌ MISSING: [{r}]")
        else:
            print(f"✅ Found: [{r}]")
            
except Exception as e:
    print(f"Error: {e}")

conn.close()
