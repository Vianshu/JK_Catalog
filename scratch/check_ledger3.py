import sys
from src.logic.db_manager import get_db_manager

db = get_db_manager()
conn = db.get_connection('JK_HW_Divison_082083_38532a08')
cur = conn.cursor()
cur.execute("SELECT TOP 10 Name, Alias FROM row_ledger_data WHERE Alias IS NOT NULL AND Alias != ''")
rows = cur.fetchall()

with open("scratch/aliases.txt", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(f"{r.Name} || {r.Alias}\n")
