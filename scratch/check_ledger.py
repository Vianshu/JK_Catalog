import sys
import os
from src.logic.db_manager import get_db_manager

db = get_db_manager()
conn = db.get_master_connection()
cur = conn.cursor()
cur.execute("SELECT name FROM sys.databases WHERE name LIKE '%HW%'")
dbs = cur.fetchall()
print("Databases:", dbs)

if dbs:
    db_name = dbs[0][0]
    conn2 = db.get_connection(db_name)
    cur2 = conn2.cursor()
    cur2.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='row_ledger_data'")
    cols = cur2.fetchall()
    print("row_ledger_data columns:", [c[0] for c in cols])
