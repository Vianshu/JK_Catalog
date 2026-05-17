import sqlite3

db = sqlite3.connect(r'c:\Users\HP\Desktop\project\backup code\super_master.db')
cursor = db.cursor()
cursor.execute('SELECT * FROM super_master')
cols = [d[0] for d in cursor.description]
rows = cursor.fetchall()
print(f'Columns: {cols}')
print(f'Rows: {len(rows)}')

with open(r'c:\Users\HP\Desktop\super_master_import.sql', 'w', encoding='utf-8') as f:
    f.write('USE JK_Super_Master;\nGO\n')
    col_defs = ', '.join([f'[{c}] NVARCHAR(MAX)' for c in cols])
    f.write(f'IF OBJECT_ID(\'super_master\',\'U\') IS NULL CREATE TABLE super_master ({col_defs});\nGO\n')
    f.write('DELETE FROM super_master;\nGO\n')
    for row in rows:
        vals = ', '.join(["N'" + str(v).replace("'", "''") + "'" if v is not None else 'NULL' for v in row])
        f.write(f'INSERT INTO super_master VALUES ({vals});\n')
    f.write('GO\n')

print('Done! Saved to: c:\\Users\\HP\\Desktop\\super_master_import.sql')
db.close()
