import json
import os
import sqlite3
import warnings
from pathlib import Path

import pandas as pd
import pyodbc


warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*pandas only supports SQLAlchemy connectable.*",
)


class TallyService:
    def __init__(self):
        self.connection = None

        # प्रोजेक्ट का बेस पाथ (JSON फाइल ढूँढने के लिए)
        from src.utils.path_utils import get_app_dir

        self.app_path = get_app_dir()

    def connect(self):
        try:
            for dsn in ["DSN=TallyODBC64_9000", "DSN=TallyODBC_9000"]:
                try:
                    self.connection = pyodbc.connect(dsn, timeout=2)
                    return True
                except:
                    pass

            drivers = [d for d in pyodbc.drivers() if "Tally" in d]
            if not drivers:
                return False

            driver = drivers[0]

            for port in [9000, 9001]:
                try:
                    conn_str = f"DRIVER={{{driver}}};SERVER=(local);PORT={port}"
                    self.connection = pyodbc.connect(conn_str, timeout=2)
                    return True
                except:
                    pass

            return False

        except:
            return False

    def save_to_sql_file(self, df, company_name, company_path=None):
        try:
            folder_path = ""

            if company_path and os.path.exists(company_path):
                folder_path = company_path
            else:
                # Fallback to vault (Legacy/Centralized Mode)
                vault_path = os.path.join(self.app_path, "company_vault.json")

                if not os.path.exists(vault_path):
                    if not company_path:
                        raise Exception(
                            "Company Path not provided and Vault missing"
                        )
                else:
                    with open(vault_path, "r", encoding="utf-8") as f:
                        vault = json.load(f)

                    if company_name not in vault:
                        if not company_path:
                            raise Exception(
                                f"Company '{company_name}' not found in vault"
                            )
                    else:
                        folder_path = vault[company_name]["path"]

            if not folder_path:
                folder_path = company_path

            if not folder_path or not os.path.exists(folder_path):
                raise Exception(f"Invalid Data Folder: {folder_path}")

            db_file_path = os.path.join(folder_path, "row_data.db")

            conn = sqlite3.connect(db_file_path)

            export_df = df.copy()

            column_mapping = {
                "$GUID": "GUID",
                "$Name": "Item_Name",
                "$Parent": "SubGroup",
                "$Category": "Category",
                "$MailingName": "Part_No",
                "$Narration": "Weight",
                "$Description": "Note",
                "$CostingMethod": "FIFO",
                "$ValuationMethod": "Valuation",
                "$BaseUnits": "Unit",
                "$_ClosingBalance": "Closing_Qty",
                "$_ClosingRate": "Closing_Rate",
                "$OpeningBalance": "Opening_Stock",
                "$OpeningValue": "Opening_Value",
                "$OpeningRate": "Opening_Rate",
                "$_ClosingValue": "Closing_Value",
                "$_LastPurcParty": "LastPurcParty",
                "$_LastPurcPrice": "LastPurcPrice",
                "$_LastPurcCost": "LastPurcCost",
                "$_LastPurcQty": "LastPurcQty",
                "$_FirstAlias": "FirstAlias",
                "$StandardPrice": "MRP",
            }

            # Case-insensitive rename: different Tally ODBC versions may
            # return column names in different cases (e.g. $Guid vs $GUID)
            raw_cols = list(export_df.columns)
            print(f"[DEBUG] Raw Tally columns: {raw_cols}")
            
            current_cols = {c.lower(): c for c in export_df.columns}
            resolved_mapping = {}
            for old_name, new_name in column_mapping.items():
                actual_col = current_cols.get(old_name.lower())
                if actual_col:
                    resolved_mapping[actual_col] = new_name
            export_df.rename(columns=resolved_mapping, inplace=True)
            
            final_cols = list(export_df.columns)
            print(f"[DEBUG] Final columns after rename: {final_cols}")
            
            # Verify critical column exists
            if "GUID" not in export_df.columns:
                print(f"[WARNING] GUID column missing after rename! Columns: {final_cols}")
            
            export_df.to_sql("stock_items", conn, if_exists="replace", index=False)

            conn.close()
            print(f"[OK] SQLite Database created with clean headers: {db_file_path}")
            return True

        except Exception as e:
            print(f"[ERROR] SQLite Save Error: {e}")
            raise e

    def fetch_stock_items(self, company_name=None, company_path=None):
        try:
            if not self.connection:
                if not self.connect():
                    raise Exception("Could not connect to Tally")

            if company_name:
                comp_df = pd.read_sql("SELECT $Name from Company", self.connection)
                active_company = comp_df.iloc[0, 0].strip()

                if active_company.lower() != company_name.strip().lower():
                    if (
                        company_name.split("(")[0].strip().lower()
                        not in active_company.lower()
                    ):
                        raise Exception(
                            f"Wrong company open in Tally: '{active_company}'"
                        )

            sql = """
                SELECT
                    $GUID,
                    $Name,
                    $Parent,
                    $Category,
                    $MailingName,
                    $StandardPrice,
                    $Narration,
                    $Description,
                    $CostingMethod,
                    $ValuationMethod,
                    $BaseUnits,
                    $_ClosingBalance,
                    $_ClosingRate,
                    $OpeningBalance,
                    $OpeningValue,
                    $OpeningRate,
                    $_ClosingValue,
                    $_LastPurcParty,
                    $_LastPurcPrice,
                    $_LastPurcCost,
                    $_LastPurcQty,
                    $_FirstAlias
                FROM StockItem
            """

            print("Fetching data from Tally...")
            df = pd.read_sql(sql, self.connection)

            if df.empty:
                return pd.DataFrame()

            if company_name or company_path:
                self.save_to_sql_file(df, company_name, company_path)

            return df

        except Exception as e:
            raise Exception(f"Tally data fetch failed: {e}")

        finally:
            if self.connection:
                self.connection.close()
                self.connection = None


def fetch_tally_data(company_name=None, company_path=None):
    service = TallyService()

    try:
        df = service.fetch_stock_items(
            company_name=company_name,
            company_path=company_path,
        )
        return df, ""

    except Exception as e:
        return pd.DataFrame(), str(e)


warnings.filterwarnings("ignore")


def fetch_tally_ledger_data(company_path=None):
    """Fetch Ledger data from Tally and save to company's ledger_internal_data.db.
    
    Uses TallyService for consistent connection handling.
    Returns: (row_count: int, error: str) — error is empty string on success.
    """
    service = TallyService()

    try:
        if not service.connect():
            return 0, "Could not connect to Tally. Please ensure Tally is running."

        ledger_sql = """
            SELECT
                $GUID,
                $Name,
                $_Address1,
                $SalesTaxNumber,
                $_FirstAlias,
                $LedgerContact,
                $LedgerPhone,
                $LedgerMobile,
                $_PrimaryGroup,
                $Parent,
                $CreditLimit,
                $OpeningBalance,
                $_ClosingBalance,
                $_OverdueBills,
                $_OnAccountValue,
                $_CashInFlow,
                $_CashOutFlow,
                $_Performance,
                $_ThisQuarterBalance,
                $_PrevQuarterBalance,
                $IsBillWiseOn
            FROM Ledger
        """

        print("Fetching ledger data from Tally...")
        ledger_df = pd.read_sql(ledger_sql, service.connection)

        if ledger_df.empty:
            return 0, "No ledger data received from Tally."

        ledger_mapping = {
            "$GUID": "GUID",
            "$Name": "Name",
            "$_Address1": "Address",
            "$SalesTaxNumber": "Pan_No.",
            "$_FirstAlias": "Alias",
            "$LedgerContact": "Contact_Person",
            "$LedgerPhone": "Phone",
            "$LedgerMobile": "Mobile",
            "$_PrimaryGroup": "Group",
            "$Parent": "Sub_Group",
            "$CreditLimit": "Credit_Limit",
            "$OpeningBalance": "Opening_Balance",
            "$_ClosingBalance": "Closing_Balance",
            "$_OverdueBills": "Overdue_Bills",
            "$_OnAccountValue": "On_Account_Value",
            "$_CashInFlow": "CashInFlow",
            "$_CashOutFlow": "CashOutFlow",
            "$_Performance": "Performance",
            "$_ThisQuarterBalance": "This_Qtr_Balance",
            "$_PrevQuarterBalance": "Prev_Qtr_Balance",
            "$IsBillWiseOn": "BillwiseOn",
        }

        # Case-insensitive rename (same fix as stock_items)
        current_cols = {c.lower(): c for c in ledger_df.columns}
        resolved_mapping = {}
        for old_name, new_name in ledger_mapping.items():
            actual_col = current_cols.get(old_name.lower())
            if actual_col:
                resolved_mapping[actual_col] = new_name
        ledger_df.rename(columns=resolved_mapping, inplace=True)

        numeric_cols = [
            "Credit_Limit", "Opening_Balance", "Closing_Balance",
            "Overdue_Bills", "On_Account_Value", "CashInFlow",
            "CashOutFlow", "This_Qtr_Balance", "Prev_Qtr_Balance",
        ]
        for col in numeric_cols:
            if col in ledger_df.columns:
                ledger_df[col] = ledger_df[col].fillna(0).astype(float) * -1

        # Save to company folder if provided, otherwise fallback to app dir
        if company_path and os.path.exists(company_path):
            db_path = os.path.join(company_path, "ledger_internal_data.db")
        else:
            db_path = os.path.join(service.app_path, "ledger_internal_data.db")

        conn_db = sqlite3.connect(db_path)
        ledger_df.to_sql(
            "row_leger_data", conn_db,
            if_exists="replace", index=False,
        )
        conn_db.close()

        print(f"[OK] Ledger data saved: {db_path} ({len(ledger_df)} rows)")
        return len(ledger_df), ""

    except Exception as e:
        return 0, str(e)

    finally:
        if service.connection:
            service.connection.close()
            service.connection = None
