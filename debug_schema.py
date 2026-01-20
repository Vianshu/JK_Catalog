import sqlite3
import os

db_path = "data/NGT Branch (2082_83)/final_data.db"
if not os.path.exists(db_path):
    print("DB not found at:", db_path)
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(catalog)")
    cols = cur.fetchall()
    print("Colums in catalog:")
    for c in cols:
        print(c[1])
    conn.close()
