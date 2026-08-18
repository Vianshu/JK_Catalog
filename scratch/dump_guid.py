import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.logic.db_manager import get_db_manager, build_logical_name

def dump_party():
    company_path = r"C:\Users\HP\Desktop\Test\HW Divison 082083"
    company_name = os.path.basename(os.path.normpath(company_path))
    db_name = build_logical_name(company_name, company_path=company_path)
    
    db = get_db_manager()
    conn = db.get_connection(db_name)
    cur = conn.cursor()
    cur.execute("SELECT GUID, Alias, Name FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
    rows = cur.fetchall()
    
    if rows:
        guid, alias, name = rows[0]
        print(f"Sample GUID: {repr(guid)}")
        
        # Safely print Alias and Name
        try:
            print(f"Sample Alias: {repr(alias)}")
        except Exception:
            print("Could not print Alias")
            
        try:
            print(f"Sample Name: {repr(name)}")
        except Exception:
            print("Could not print Name")
            
        print(f"Alias == GUID? {alias == guid}")
        print(f"Name == GUID? {name == guid}")
        print(f"Name == Alias? {name == alias}")

if __name__ == '__main__':
    dump_party()
