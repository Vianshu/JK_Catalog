import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

db_path = r"C:\Users\HP\Desktop\Test\HW Divison 082083\row_data.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all tables
tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Database: {db_path}")
print(f"Tables found: {len(tables)}")

for (table_name,) in tables:
    print(f"\n{'='*60}")
    print(f"TABLE: {table_name}")
    print(f"{'='*60}")
    
    # Get column info
    cols = cursor.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    print(f"Columns ({len(cols)}):")
    for col in cols:
        print(f"  {col[1]} ({col[2]}){' PRIMARY KEY' if col[5] else ''}")
    
    # Get row count
    count = cursor.execute(f"SELECT COUNT(*) FROM '{table_name}'").fetchone()[0]
    print(f"\nTotal rows: {count}")
    
    # Show sample rows
    rows = cursor.execute(f"SELECT * FROM '{table_name}' LIMIT 10").fetchall()
    if rows:
        col_names = [c[1] for c in cols]
        print(f"\nSample data (up to 10 rows):")
        for i, row in enumerate(rows):
            print(f"\n  Row {i+1}:")
            for name, val in zip(col_names, row):
                print(f"    {name}: {val}")

conn.close()
