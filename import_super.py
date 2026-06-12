import sqlite3
from src.logic.db_manager import get_db_manager, build_shared_db_name, DB_SUPER
import pyodbc

def main():
    db = get_db_manager()
    sql_db_name = build_shared_db_name(DB_SUPER, r'C:\Users\HP\Desktop\testttt')
    print(f"Target SQL Server DB: {sql_db_name}")

    conn_sqlite = sqlite3.connect(r'C:\Users\HP\Desktop\super_master.db')
    cur_sqlite = conn_sqlite.cursor()
    cur_sqlite.execute('SELECT id, MG_SN, Group_Name, SG_SN, Sub_Group FROM super_master')
    rows = cur_sqlite.fetchall()
    conn_sqlite.close()

    conn_sql = db.get_connection(sql_db_name)
    if not conn_sql:
        print("Failed to connect to SQL Server")
        return
    cur_sql = conn_sql.cursor()
    
    count = 0
    for r in rows:
        sub_group = r[4]
        if not sub_group: continue
        
        # Replace empty strings with None or keep as is? Let's keep what we read from sqlite
        _id, mg, gp, sg = r[0], r[1], r[2], r[3]
        
        cur_sql.setinputsizes([(pyodbc.SQL_WVARCHAR, 255)] * 10)
        cur_sql.execute('''
            MERGE super_master AS target
            USING (SELECT ? AS Sub_Group) AS source
            ON target.Sub_Group = source.Sub_Group
            WHEN MATCHED THEN
                UPDATE SET id = ?, MG_SN = ?, Group_Name = ?, SG_SN = ?
            WHEN NOT MATCHED THEN
                INSERT (id, MG_SN, Group_Name, SG_SN, Sub_Group)
                VALUES (?, ?, ?, ?, ?);
        ''', (sub_group, _id, mg, gp, sg, _id, mg, gp, sg, sub_group))
        count += 1
        
    conn_sql.commit()
    db.close_connection(sql_db_name)
    print(f'Imported {count} rows into {sql_db_name}')

if __name__ == '__main__':
    main()
