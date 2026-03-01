import os
import sys
base_path = r"c:\Users\HP\Desktop\project\backup code"
sys.path.insert(0, base_path)

from src.logic.catalog_logic import CatalogLogic

comp_path = r"c:\Users\HP\Desktop\CATALOG UPDATE V1.0\backup code\data\NGT Branch (2082_83)"
# super_master.db is usually in the parent directory
super_db_path = os.path.dirname(comp_path)
logic = CatalogLogic(os.path.join(super_db_path, "super_master.db"))
logic.catalog_db_path = os.path.join(comp_path, "catalog.db")
logic.final_db_path = os.path.join(comp_path, "final_data.db")

print("Valid logic connection:", os.path.exists(logic.catalog_db_path))
res = logic.detect_changed_pages()
print("\n--- RESULT ---")
print("Changed Pages:", res)
