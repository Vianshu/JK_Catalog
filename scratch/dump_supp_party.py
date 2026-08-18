import os
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.logic.db_manager import get_db_manager, build_logical_name

def dump_party():
    company_path = r"C:\Users\HP\Desktop\Test\HW Divison 082083"
    company_name = os.path.basename(os.path.normpath(company_path))
    db_name = build_logical_name(company_name, company_path=company_path)
    print(f"DB Name: {db_name}")

    db = get_db_manager()
    conn = db.get_connection(db_name)
    if not conn:
        print("Could not connect")
        return
    
    try:
        cur = conn.cursor()
        cur.execute("SELECT GUID, Alias, Name FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
        rows = cur.fetchall()
        print(f"Loaded {len(rows)} rows from row_ledger_data")
        
        guid_to_name = {}
        for guid, alias, name in rows:
            guid_str = str(guid).strip() if guid else ""
            if not guid_str: continue
            
            alias_str = str(alias).strip() if alias and str(alias).strip().lower() != "none" else ""
            name_str  = str(name).strip()  if name  and str(name).strip().lower()  != "none" else ""
            
            if name_str:
                guid_to_name[guid_str] = name_str
        
        print(f"guid_to_name has {len(guid_to_name)} keys")
        if guid_to_name:
            sample_guid = list(guid_to_name.keys())[0]
            print(f"Sample: {sample_guid} -> {guid_to_name[sample_guid]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    dump_party()
