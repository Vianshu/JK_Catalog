import sqlite3
import os

db_path = r"data\NGT Branch (2082_83)\final_data.db"
print(f"Connecting to {db_path}")

group_name = "Gi Fitting"
sg_sn = "1" # Try int string
sg_sn_alt = "01" # Try zero pad

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def try_fetch(g, s, label):
    print(f"\n--- TRYING {label}: Group='{g}', SG_SN='{s}' ---")
    query = """
                SELECT [Product Name]
                FROM catalog
                WHERE TRIM([Group])=? COLLATE NOCASE 
                  AND CAST([SG_SN] AS INTEGER) = CAST(? AS INTEGER)
                  AND (
                      [True/False] IS NULL 
                      OR [True/False] = '' 
                      OR CAST([True/False] AS TEXT) COLLATE NOCASE != 'false'
                  )
            """
    cursor.execute(query, (g.strip(), s))
    rows = cursor.fetchall()
    print(f"Found: {len(rows)}")
    if rows: print(f"Sample: {rows[0]}")

try_fetch(group_name, sg_sn, "INT String 1")
try_fetch(group_name, sg_sn_alt, "Zero Pad 01")
try_fetch("GI Fitting", "1", "Different Case GI")
try_fetch(" Gi Fitting ", "1", "Spaces")

conn.close()
