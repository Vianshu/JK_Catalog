import sqlite3, datetime
import sys
sys.path.append(r"C:\Users\HP\Desktop\project\backup code")
from src.logic.catalog_logic import CatalogLogic

conn=sqlite3.connect(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\catalog.db')
c=conn.cursor()
c.execute("SELECT serial_no, group_name, sg_sn FROM catalog_pages")
pages = c.fetchall()
conn.close()

logic = CatalogLogic(r'C:\Users\HP\Desktop\Testing\super_master.db')
logic.set_paths(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\catalog.db', r'C:\Users\HP\Desktop\Testing\HW Divison 082083\final_data.db')
logic.invalidate_cache()

# See what's returned for the first page
for serial_no, group_name, sg_sn in pages:
    items = logic.get_items_for_page_dynamic(group_name, sg_sn, 1)
    for idx, item in enumerate(items):
        if item and 'data' in item and 'product_name' in item['data']:
            if "वाटर पम्प (बिमल)" in item['data']['product_name']:
                print(f"FOUND ON PAGE {serial_no}!")
                print("CURRENT HASH:", logic.get_page_content_hash(serial_no))
                
                conn = sqlite3.connect(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\catalog.db')
                c = conn.cursor()
                c.execute("SELECT content_hash FROM page_snapshots WHERE serial_no=?", (serial_no,))
                row = c.fetchone()
                print("DB HASH     :", row[0] if row else "NONE")
                
                # Print the exact details
                data = item['data']
                print("DATA LENGTH :", data.get("length"))
                print("DATA DATES  :", data.get("all_update_dates"))
                sys.exit(0)
