import json
import os
import warnings
from pathlib import Path

import pandas as pd
import pyodbc
import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.types import NVARCHAR
from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*pandas only supports SQLAlchemy connectable.*",
)


class TallyService:
    def __init__(self):
        self.connection = None
        self.cancelled = False  # Cancellation flag for background threads

        # प्रोजेक्ट का बेस पाथ (JSON फाइल ढूँढने के लिए)
        from src.utils.path_utils import get_app_dir

        self.app_path = get_app_dir()
        self.db = get_db_manager()

    def cancel(self):
        """Signal cancellation — safe to call from any thread."""
        self.cancelled = True
        # Close the Tally ODBC connection to interrupt any running pd.read_sql
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def _check_cancelled(self, stage=""):
        """Raise if cancelled. Call at key checkpoints."""
        if self.cancelled:
            raise InterruptedError(f"Tally sync cancelled{' at ' + stage if stage else ''}")

    def connect(self):
        try:
            for dsn in ["DSN=TallyODBC64_9000", "DSN=TallyODBC_9000"]:
                try:
                    self.connection = pyodbc.connect(dsn, timeout=2)
                    return True
                except pyodbc.Error:
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
                except pyodbc.Error:
                    pass

            return False

        except Exception:
            return False

    def _get_sqlalchemy_engine(self, db_name):
        """Create a SQLAlchemy engine using the server name from db_manager (not hardcoded)."""
        server = self.db.server_name or r".\SQLEXPRESS"
        params = urllib.parse.quote_plus(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={db_name};"
            f"Trusted_Connection=yes;"
        )
        return create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)

    def _ensure_row_data_db(self, company_path):
        """Ensure the RowData database exists on SQL Server, returning the logical name."""
        company_name = os.path.basename(company_path)
        db_name = build_logical_name(company_name, company_path=company_path)
        self.db.ensure_database_exists(db_name, company_path)
        return db_name

    def _ensure_stock_items_table(self, db_name):
        """Ensure stock_items table exists with a GUID primary key."""
        self.db.ensure_table(db_name, "stock_items", """
            CREATE TABLE stock_items (
                GUID NVARCHAR(255) PRIMARY KEY,
                Item_Name NVARCHAR(MAX),
                SubGroup NVARCHAR(MAX),
                Category NVARCHAR(MAX),
                Part_No NVARCHAR(MAX),
                Weight NVARCHAR(MAX),
                Note NVARCHAR(MAX),
                FIFO NVARCHAR(MAX),
                Valuation NVARCHAR(MAX),
                Unit NVARCHAR(MAX),
                Closing_Qty NVARCHAR(MAX),
                Closing_Rate NVARCHAR(MAX),
                Opening_Stock NVARCHAR(MAX),
                Opening_Value NVARCHAR(MAX),
                Opening_Rate NVARCHAR(MAX),
                Closing_Value NVARCHAR(MAX),
                LastPurcParty NVARCHAR(MAX),
                LastPurcPrice NVARCHAR(MAX),
                LastPurcCost NVARCHAR(MAX),
                LastPurcQty NVARCHAR(MAX),
                FirstAlias NVARCHAR(MAX),
                MRP NVARCHAR(MAX)
            )
        """)

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

            # Ensure the RowData DB exists on SQL Server
            db_name = self._ensure_row_data_db(folder_path)

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
            logger.debug(f"Raw Tally columns: {raw_cols}")
            
            current_cols = {c.lower(): c for c in export_df.columns}
            resolved_mapping = {}
            for old_name, new_name in column_mapping.items():
                actual_col = current_cols.get(old_name.lower())
                if actual_col:
                    resolved_mapping[actual_col] = new_name
            export_df.rename(columns=resolved_mapping, inplace=True)
            
            final_cols = list(export_df.columns)
            logger.debug(f"Final columns after rename: {final_cols}")
            
            # Verify critical column exists
            if "GUID" not in export_df.columns:
                logger.warning(f"GUID column missing after rename! Columns: {final_cols}")

            self._check_cancelled("before SQL Server write")

            # Ensure the stock_items table exists (for MERGE)
            self._ensure_stock_items_table(db_name)

            # Write to staging table for MERGE
            conn = self.db.get_connection(db_name)
            if not conn:
                raise Exception(f"Could not connect to SQL Server DB: {db_name}")

            cursor = conn.cursor()
            
            # Drop staging table if leftover from a previous failed sync
            staging_table = "stock_items_staging"
            try:
                cursor.execute(f"IF OBJECT_ID('{staging_table}', 'U') IS NOT NULL DROP TABLE [{staging_table}]")
                conn.commit()
            except Exception:
                pass

            # Bulk insert rows into staging using SQLAlchemy fast_executemany
            engine = self._get_sqlalchemy_engine(db_name)
            
            logger.info("Writing stock items to staging via SQLAlchemy (fast_executemany=True)")
            # Force NVARCHAR for all string columns so Hindi/Unicode text is preserved
            nvarchar_dtype = {col: NVARCHAR(length=None) for col in export_df.select_dtypes(include=['object']).columns}
            export_df.to_sql(staging_table, con=engine, if_exists="replace", index=False, dtype=nvarchar_dtype)
            engine.dispose()

            self._check_cancelled("after staging write")

            # Verify staging has data before merging
            cursor.execute(f"SELECT COUNT(*) FROM [{staging_table}]")
            staging_count = cursor.fetchone()[0]
            if staging_count == 0:
                logger.warning("Staging table is empty, aborting merge")
                cursor.execute(f"DROP TABLE [{staging_table}]")
                conn.commit()
                raise Exception("Staging table was empty after insert")

            # MERGE: UPSERT changed/new rows + DELETE removed rows
            # All columns except GUID are updated on match
            merge_cols = [c for c in export_df.columns if c != "GUID"]
            update_set = ", ".join([f"target.[{c}] = source.[{c}]" for c in merge_cols])
            insert_cols = ", ".join([f"[{c}]" for c in export_df.columns])
            source_cols = ", ".join([f"source.[{c}]" for c in export_df.columns])

            merge_sql = f"""
                MERGE stock_items AS target
                USING [{staging_table}] AS source
                ON target.GUID = source.GUID
                WHEN MATCHED THEN
                    UPDATE SET {update_set}
                WHEN NOT MATCHED BY TARGET THEN
                    INSERT ({insert_cols}) VALUES ({source_cols})
                WHEN NOT MATCHED BY SOURCE THEN
                    DELETE;
            """

            try:
                cursor.execute(merge_sql)
                inserted = cursor.rowcount  # Total rows affected by MERGE
                conn.commit()
                logger.info(f"MERGE complete: {inserted} rows affected")
            except Exception:
                conn.rollback()
                raise

            # Clean up staging table
            try:
                cursor.execute(f"DROP TABLE [{staging_table}]")
                conn.commit()
            except Exception:
                pass

            logger.info(f"Row data saved to SQL Server: db='{db_name}', rows={len(export_df)}")
            return True

        except InterruptedError:
            # Cancellation — clean up staging if it exists
            logger.info("Tally sync cancelled — cleaning up")
            try:
                conn = self.db.get_connection(db_name)
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("IF OBJECT_ID('stock_items_staging', 'U') IS NOT NULL DROP TABLE stock_items_staging")
                    conn.commit()
            except Exception:
                pass
            raise

        except Exception as e:
            logger.error(f"SQL Server save error: {e}", exc_info=True)
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
                    raise Exception(
                        f"Wrong company open in Tally: '{active_company}'"
                    )

            self._check_cancelled("before Tally fetch")

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

            logger.info(f"Fetching stock items from Tally...")
            df = pd.read_sql(sql, self.connection)

            if df.empty:
                return pd.DataFrame()

            self._check_cancelled("after Tally fetch")

            if company_name or company_path:
                self.save_to_sql_file(df, company_name, company_path)

            return df

        except InterruptedError:
            raise  # Let cancellation propagate cleanly

        except Exception as e:
            raise Exception(f"Tally data fetch failed: {e}")

        finally:
            if self.connection:
                try:
                    self.connection.close()
                except Exception:
                    pass
                self.connection = None


def fetch_tally_data(company_name=None, company_path=None, service=None):
    """Fetch stock items from Tally and save to SQL Server.
    
    Args:
        service: Optional TallyService instance (for cancellation support).
                 If None, a new one is created.
    """
    if service is None:
        service = TallyService()

    try:
        df = service.fetch_stock_items(
            company_name=company_name,
            company_path=company_path,
        )
        return df, ""

    except InterruptedError:
        return pd.DataFrame(), "cancelled"

    except Exception as e:
        return pd.DataFrame(), str(e)


warnings.filterwarnings("ignore")


def fetch_tally_ledger_data(company_name=None, company_path=None, service=None):
    """Fetch Ledger data from Tally and save to company's LedgerData DB on SQL Server.
    
    Args:
        service: Optional TallyService instance (for cancellation support).
    
    Returns: (row_count: int, error: str) — error is empty string on success.
    """
    if service is None:
        service = TallyService()

    try:
        if not service.connect():
            return 0, "Could not connect to Tally. Please ensure Tally is running."

        # ── Company mismatch check (same as stock sync) ──────────────────────
        if company_name:
            try:
                comp_df = pd.read_sql("SELECT $Name from Company", service.connection)
                active_company = comp_df.iloc[0, 0].strip()
                if active_company.lower() != company_name.strip().lower():
                    return 0, (
                        f"Wrong company open in Tally: '{active_company}'\n"
                        f"Please open '{company_name}' in Tally and try again."
                    )
            except Exception as ce:
                logger.warning(f"Company check failed (proceeding anyway): {ce}")
        # ─────────────────────────────────────────────────────────────────────

        service._check_cancelled("before ledger fetch")


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

        logger.info("Fetching ledger data from Tally...")
        ledger_df = pd.read_sql(ledger_sql, service.connection)

        if ledger_df.empty:
            return 0, "No ledger data received from Tally."

        service._check_cancelled("after ledger fetch")

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

        service._check_cancelled("before ledger SQL write")

        # Save to SQL Server LedgerData DB
        company_name = os.path.basename(company_path) if company_path else "default"
        db_name = build_logical_name(company_name, company_path=company_path) if company_path else build_logical_name(company_name)
        service.db.ensure_database_exists(db_name, company_path or service.app_path)

        conn = service.db.get_connection(db_name)
        if not conn:
            return 0, f"Could not connect to SQL Server DB: {db_name}"

        cursor = conn.cursor()

        # Use staging table pattern to prevent data loss on failure
        staging_table = "row_ledger_data_staging"
        try:
            cursor.execute(f"IF OBJECT_ID('{staging_table}', 'U') IS NOT NULL DROP TABLE [{staging_table}]")
            conn.commit()
        except Exception:
            pass

        # Bulk insert rows into staging using SQLAlchemy fast_executemany
        engine = service._get_sqlalchemy_engine(db_name)
        
        logger.info("Writing ledger data to staging via SQLAlchemy (fast_executemany=True)")
        # Force NVARCHAR for all string columns so Hindi/Unicode text is preserved
        nvarchar_dtype = {col: NVARCHAR(length=None) for col in ledger_df.select_dtypes(include=['object']).columns}
        ledger_df.to_sql(staging_table, con=engine, if_exists="replace", index=False, dtype=nvarchar_dtype)
        engine.dispose()

        service._check_cancelled("after ledger staging write")

        # Verify staging before swap
        cursor.execute(f"SELECT COUNT(*) FROM [{staging_table}]")
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"DROP TABLE [{staging_table}]")
            conn.commit()
            return 0, "Staging table empty after insert — original data preserved."

        # Atomic swap: drop old → rename staging
        # With autocommit=False, both statements run in the same implicit
        # transaction — conn.commit() makes them atomic.
        try:
            cursor.execute("IF OBJECT_ID('row_ledger_data', 'U') IS NOT NULL DROP TABLE row_ledger_data")
            cursor.execute(f"EXEC sp_rename '{staging_table}', 'row_ledger_data'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        logger.info(f"Ledger data saved to SQL Server: db='{db_name}', rows={len(ledger_df)}")
        return len(ledger_df), ""

    except InterruptedError:
        logger.info("Ledger sync cancelled")
        return 0, "cancelled"

    except Exception as e:
        return 0, str(e)

    finally:
        if service.connection:
            try:
                service.connection.close()
            except Exception:
                pass
            service.connection = None
