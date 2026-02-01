import sqlite3

conn = sqlite3.connect('data/super_master.db')
cursor = conn.cursor()

# Get tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"Tables: {tables}")

# Check super_master table
if ('super_master',) in tables:
    cursor.execute("SELECT COUNT(*) FROM super_master")
    print(f"Row count: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT * FROM super_master LIMIT 3")
    print(f"Sample rows: {cursor.fetchall()}")
else:
    print("super_master table not found!")

conn.close()
