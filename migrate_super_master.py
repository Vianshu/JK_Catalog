"""
One-time migration: SQLite super_master.db → SQL Server super_master table.

Usage:
    python migrate_super_master.py <sqlite_file> <data_path>

Example:
    python migrate_super_master.py "C:\Data\super_master.db" "C:\Data"

Arguments:
    sqlite_file : Path to the existing super_master.db (SQLite)
    data_path   : Root data folder (parent of company folders) — this
                  determines which SQL Server DB the data goes into.
"""

import sys
import os
import sqlite3
import hashlib
import pyodbc
import json


# ─── Config ───
DB_SUPER = "JK_SuperMaster"
SQL_SERVER_NAME = None  # Auto-read from %APPDATA%/JK_Catalog/config.json


def get_sql_server_name():
    """Read SQL Server name from app config."""
    config_path = os.path.join(os.environ.get("APPDATA", ""), "JK_Catalog", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cfg = json.load(f)
            return cfg.get("sql_server_name", ".\\SQLEXPRESS")
    return ".\\SQLEXPRESS"


def build_shared_db_name(base_name, data_path):
    norm_path = os.path.normpath(data_path).lower()
    path_hash = hashlib.md5(norm_path.encode()).hexdigest()[:8]
    return f"{base_name}_{path_hash}"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    sqlite_path = sys.argv[1]
    data_path = sys.argv[2]

    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    # ─── Read from SQLite ───
    print(f"Reading from SQLite: {sqlite_path}")
    conn_lite = sqlite3.connect(sqlite_path)
    cursor_lite = conn_lite.cursor()
    cursor_lite.execute("SELECT MG_SN, Group_Name, SG_SN, Sub_Group FROM super_master")
    rows = cursor_lite.fetchall()
    conn_lite.close()

    print(f"Found {len(rows)} rows in SQLite super_master")
    if not rows:
        print("Nothing to migrate.")
        return

    # ─── Connect to SQL Server ───
    server = get_sql_server_name()
    db_name = build_shared_db_name(DB_SUPER, data_path)
    print(f"SQL Server: {server}")
    print(f"Target DB:  {db_name}")

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE=master;"
        f"Trusted_Connection=yes;"
    )
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()

    # Create DB if not exists
    cursor.execute(f"""
        IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = '{db_name}')
        CREATE DATABASE [{db_name}]
    """)
    conn.close()

    # Connect to the target DB
    conn_str2 = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={db_name};"
        f"Trusted_Connection=yes;"
    )
    conn = pyodbc.connect(conn_str2, autocommit=True)
    cursor = conn.cursor()

    # Create table if not exists
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'super_master')
        CREATE TABLE super_master (
            id NVARCHAR(50),
            MG_SN NVARCHAR(50),
            Group_Name NVARCHAR(255),
            SG_SN NVARCHAR(50),
            Sub_Group NVARCHAR(255) PRIMARY KEY
        )
    """)

    # ─── Insert rows ───
    inserted = 0
    skipped = 0
    for mg_sn, group_name, sg_sn, sub_group in rows:
        if not sub_group:
            skipped += 1
            continue
        mg_sn = str(mg_sn) if mg_sn else ""
        sg_sn = str(sg_sn) if sg_sn else ""
        group_name = str(group_name) if group_name else ""
        row_id = mg_sn + sg_sn

        try:
            cursor.execute("""
                MERGE super_master AS target
                USING (SELECT ? AS id, ? AS MG_SN, ? AS Group_Name, ? AS SG_SN, ? AS Sub_Group) AS source
                ON target.Sub_Group = source.Sub_Group
                WHEN MATCHED THEN UPDATE SET
                    id = source.id, MG_SN = source.MG_SN,
                    Group_Name = source.Group_Name, SG_SN = source.SG_SN
                WHEN NOT MATCHED THEN INSERT (id, MG_SN, Group_Name, SG_SN, Sub_Group)
                    VALUES (source.id, source.MG_SN, source.Group_Name, source.SG_SN, source.Sub_Group);
            """, (row_id, mg_sn, group_name, sg_sn, sub_group))
            inserted += 1
        except Exception as e:
            print(f"  SKIP '{sub_group}': {e}")
            skipped += 1

    conn.close()
    print(f"\nDone! Inserted/updated: {inserted}, Skipped: {skipped}")
    print(f"SQL Server DB: {db_name}")


if __name__ == "__main__":
    main()
