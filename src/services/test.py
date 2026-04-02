import pyodbc
import pandas as pd
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*pandas only supports SQLAlchemy connectable.*",
)

output_dir = Path("tally_odbc_output")
output_dir.mkdir(exist_ok=True)


class TallyLedgerColumnTester:
    def __init__(self):
        self.connection = None

    def connect(self):
        for dsn in ["DSN=TallyODBC64_9000", "DSN=TallyODBC_9000"]:
            try:
                print(f"Trying {dsn} ...")
                self.connection = pyodbc.connect(dsn, timeout=2)
                print("Connected using DSN")
                return True
            except Exception as e:
                print(f"Failed: {e}")

        drivers = [d for d in pyodbc.drivers() if "Tally" in d]
        print("Available Tally drivers:", drivers)

        if not drivers:
            return False

        driver = drivers[0]
        for port in [9000, 9001]:
            try:
                conn_str = f"DRIVER={{{driver}}};SERVER=(local);PORT={port}"
                print(f"Trying {conn_str} ...")
                self.connection = pyodbc.connect(conn_str, timeout=2)
                print(f"Connected using driver on port {port}")
                return True
            except Exception as e:
                print(f"Failed on port {port}: {e}")

        return False

    def run_query(self, sql, title, file_name):
        print("\n" + "=" * 100)
        print(title)
        print("SQL:", sql)
        print("=" * 100)

        try:
            df = pd.read_sql(sql, self.connection)
            print("Rows:", len(df))
            print("Columns:", list(df.columns))
            if not df.empty:
                print(df.head(10).to_string(index=False))
            df.to_csv(output_dir / file_name, index=False, encoding="utf-8-sig")
            print(f"Saved CSV: {output_dir / file_name}")
            return True
        except Exception as e:
            print("FAILED:", e)
            return False

    def explore(self):
        if not self.connect():
            print("Could not connect to Tally ODBC")
            return

        try:
            test_queries = [
                ("SELECT $Name FROM Ledger", "Only Name", "01_name.csv"),
                ("SELECT $Name, $Parent FROM Ledger", "Name + Parent", "02_name_parent.csv"),
                ("SELECT $Name, $Parent, $_PrimaryGroup FROM Ledger", "Name + Parent + PrimaryGroup", "03_primary_group.csv"),
                ("SELECT $Name, $Parent, $_PrimaryGroup, $_FirstAlias FROM Ledger", "Alias Check", "04_alias.csv"),
                ("SELECT $Name, $Parent, $_PrimaryGroup FROM Ledger WHERE $_PrimaryGroup = 'Sundry Debtors'", "Sundry Debtors", "05_sundry_debtors.csv"),
            ]

            for sql, title, file_name in test_queries:
                self.run_query(sql, title, file_name)

        finally:
            if self.connection:
                self.connection.close()
                self.connection = None
                print("\nConnection closed.")


if __name__ == "__main__":
    tester = TallyLedgerColumnTester()
    tester.explore()
