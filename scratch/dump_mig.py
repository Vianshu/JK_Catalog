import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.logic.db_manager import get_db_manager, build_logical_name

def dump_migration_failures():
    company_path = r"C:\Users\HP\Desktop\Test\HW Divison 082083"
    company_name = os.path.basename(os.path.normpath(company_path))
    db_name = build_logical_name(company_name, company_path=company_path)
    
    db = get_db_manager()
    conn = db.get_connection(db_name)
    cur = conn.cursor()
    
    cur.execute("SELECT DISTINCT party FROM cheques WHERE party_guid IS NULL OR party_guid = ''")
    rows = cur.fetchall()
    
    print(f"Total distinct parties that failed migration: {len(rows)}")
    
    # Also load the Tally names
    cur.execute("SELECT Name, Alias FROM row_ledger_data WHERE [Group] LIKE '%Sundry Debtors%'")
    tally_rows = cur.fetchall()
    tally_names = []
    for nm, al in tally_rows:
        if nm: tally_names.append(str(nm).strip().lower())
        if al: tally_names.append(str(al).strip().lower())
        
    for i, (pty,) in enumerate(rows[:5]):
        pty_str = str(pty).strip().lower() if pty else ""
        print(f"Failed Party: {repr(pty)}")
        
        # See if there's any close match
        import difflib
        matches = difflib.get_close_matches(pty_str, tally_names, n=1, cutoff=0.8)
        if matches:
            print(f"  -> Closest Tally match: {repr(matches[0])}")
        else:
            print("  -> No close match found")
        
if __name__ == '__main__':
    dump_migration_failures()
