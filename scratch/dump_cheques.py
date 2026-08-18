import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.logic.db_manager import get_db_manager, build_logical_name

def dump_cheques():
    company_path = r"C:\Users\HP\Desktop\Test\HW Divison 082083"
    company_name = os.path.basename(os.path.normpath(company_path))
    db_name = build_logical_name(company_name, company_path=company_path)
    
    db = get_db_manager()
    conn = db.get_connection(db_name)
    cur = conn.cursor()
    
    cur.execute("SELECT sn, date, party, party_guid FROM cheques WHERE party_guid IS NOT NULL AND party_guid != ''")
    rows = cur.fetchall()
    
    print(f"Total cheques with party_guid: {len(rows)}")
    for i, (sn, dt, pty, guid) in enumerate(rows[:10]):
        print(f"[{i}] SN: {sn}, Party: {pty}, GUID: {guid}")
        
if __name__ == '__main__':
    dump_cheques()
