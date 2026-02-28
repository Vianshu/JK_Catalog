import pyodbc
import pandas as pd
import warnings
import os
import json
from pathlib import Path

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
                except: pass

            drivers = [d for d in pyodbc.drivers() if "Tally" in d]
            if not drivers: return False

            driver = drivers[0]
            for port in [9000, 9001]:
                try:
                    conn_str = f"DRIVER={{{driver}}};SERVER=(local);PORT={port}"
                    self.connection = pyodbc.connect(conn_str, timeout=2)
                    return True
                except: pass
            return False
        except: return False

    def save_to_sql_file(self, df, company_name, company_path=None):
        import sqlite3
        try:
            folder_path = ""
            if company_path and os.path.exists(company_path):
                folder_path = company_path
            else:
                # Fallback to vault (Legacy/Centralized Mode)
                vault_path = os.path.join(self.app_path, "company_vault.json")
                if not os.path.exists(vault_path):
                    # If vault missing and no path provided -> Error
                    if not company_path: raise Exception("Company Path not provided and Vault missing")
                
                else:
                    with open(vault_path, 'r', encoding='utf-8') as f:
                        vault = json.load(f)

                    if company_name not in vault:
                         if not company_path: raise Exception(f"Company '{company_name}' not found in vault")
                    else:
                        folder_path = vault[company_name]['path']
            
            # Final check
            if not folder_path: folder_path = company_path
            
            if not folder_path or not os.path.exists(folder_path):
                 raise Exception(f"Invalid Data Folder: {folder_path}")

            db_file_path = os.path.join(folder_path, "row_data.db")

            # 2. SQLite डेटाबेस से कनेक्ट करें
            conn = sqlite3.connect(db_file_path)
            
            # 3. डेटा को साफ़ करें और नाम बदलें (यह हिस्सा नया है)
            export_df = df.copy()
            
            # --- यहाँ हम Tally के $ वाले नाम को अपनी पसंद के नाम से बदल रहे हैं ---
            column_mapping = {
                '$GUID': 'GUID',
                '$Name': 'Item_Name',
                '$Parent': 'SubGroup',
                '$Category': 'Category',
                '$MailingName': 'Part_No',
                '$Narration': 'Weight',
                '$Description': 'Note',
                '$CostingMethod': 'FIFO',
                '$ValuationMethod': 'Valuation',
                '$BaseUnits': 'Unit',
                '$_ClosingBalance': 'Closing_Qty',
                '$_ClosingRate': 'Closing_Rate',
                '$OpeningBalance': 'Opening_Stock',
                '$OpeningValue': 'Opening_Value',
                '$OpeningRate': 'Opening_Rate',
                '$_ClosingValue': 'Closing_Value',
                '$_LastPurcParty': 'LastPurcParty',
                '$_LastPurcPrice': 'LastPurcPrice',
                '$_LastPurcCost': 'LastPurcCost',
                '$_LastPurcQty': 'LastPurcQty',
                '$_FirstAlias': 'FirstAlias',
                '$StandardPrice': 'MRP'
            }

            # कॉलम नाम बदलें
            export_df.rename(columns=column_mapping, inplace=True)
            
            # 4. Pandas के जरिए डेटाबेस में टेबल बनाएँ
            export_df.to_sql('stock_items', conn, if_exists='replace', index=False)
            
            conn.close()
            print(f"✅ SQLite Database created with clean headers: {db_file_path}")
            return True

        except Exception as e:
            print(f"❌ SQLite Save Error: {e}")
            raise e # Raise to notify Caller

    def fetch_stock_items(self, company_name=None, company_path=None):
        try:
            if not self.connection:
                if not self.connect():
                    raise Exception("Could not connect to Tally")

            if company_name:
                comp_df = pd.read_sql("SELECT $Name from Company", self.connection)
                active_company = comp_df.iloc[0, 0].strip()
                
                # Check active company (Case insensitive match helps)
                if active_company.lower() != company_name.strip().lower():
                    # Check if date range part causes mismatch (e.g. 2082/83)
                    if company_name.split('(')[0].strip().lower() not in active_company.lower():
                        raise Exception(f"Wrong company open in Tally: '{active_company}'")

            # --- अपडेटेड SQL QUERY सभी कॉलम्स के साथ ---
            sql = """
            SELECT 
                $GUID, $Name, $Parent, $Category, $MailingName, $StandardPrice,
                $Narration, $Description, $CostingMethod, $ValuationMethod, 
                $BaseUnits, $_ClosingBalance, $_ClosingRate, $OpeningBalance,
                $OpeningValue, $OpeningRate, $_ClosingValue, $_LastPurcParty, 
                $_LastPurcPrice, $_LastPurcCost, $_LastPurcQty, $_FirstAlias
            FROM StockItem
            """
            print("Fetching data from Tally...")
            df = pd.read_sql(sql, self.connection)

            if df.empty: return pd.DataFrame()

            # डेटा फेच होते ही SQL फाइल में सेव करें
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
        df = service.fetch_stock_items(company_name=company_name, company_path=company_path)
        return df, ""
    except Exception as e:
        return pd.DataFrame(), str(e)