import sqlite3, datetime
import sys
sys.path.append(r"C:\Users\HP\Desktop\project\backup code")
from src.logic.catalog_logic import CatalogLogic

conn=sqlite3.connect(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\final_data.db')
c=conn.cursor()
c.execute("SELECT [Product Name] FROM catalog LIMIT 1")
print('Editing:', c.fetchone()[0])

now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
c.execute("UPDATE catalog SET Lenth='3|0', Update_date=? WHERE rowid=1", (now,))
conn.commit()

logic = CatalogLogic(r'C:\Users\HP\Desktop\Testing\super_master.db')
logic.set_paths(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\catalog.db', r'C:\Users\HP\Desktop\Testing\HW Divison 082083\final_data.db')
logic.invalidate_cache()
print('Changed:', len(logic.detect_changed_pages()))
