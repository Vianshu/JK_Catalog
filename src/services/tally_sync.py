import json
import os
import re
import uuid
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc
import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.types import NVARCHAR
from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


# ─── PER-USER TALLY PORT ───────────────────────────────────────────────────────
# Each RDP session / Windows user may have a different Tally instance running
# on a different port.  QSettings with UserScope persists the choice per-user
# in the Windows registry, so RDP User A and User B each get their own setting.

def get_tally_port() -> int:
    """Return the Tally port for the current OS user (default 9000)."""
    from PyQt6.QtCore import QSettings, QSettings as _QS
    s = _QS("JKCatalog", "TallyPort")
    return int(s.value("port", 9000))


def set_tally_port(port: int):
    """Persist the Tally port for the current OS user."""
    from PyQt6.QtCore import QSettings as _QS
    s = _QS("JKCatalog", "TallyPort")
    s.setValue("port", int(port))
    logger.info(f"Tally port set to {port} for current user")


warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*pandas only supports SQLAlchemy connectable.*",
)


def _normalize_comp_name_for_match(name: str) -> str:
    """Normalize company name for comparison by removing non-alphanumeric characters."""
    if not name:
        return ""
    return re.sub(r'[^a-zA-Z0-9]+', '', name.lower())


def _are_company_names_matching(tally_name: str, target_name: str) -> bool:
    """Check if Tally company name matches target name (exact or normalized)."""
    if not tally_name or not target_name:
        return False
    t_clean = tally_name.strip().lower()
    tgt_clean = target_name.strip().lower()
    if t_clean == tgt_clean:
        return True
    n1 = _normalize_comp_name_for_match(t_clean)
    n2 = _normalize_comp_name_for_match(tgt_clean)
    if n1 == n2:
        return True
    return False


class TallyService:
    def __init__(self):
        self.connection = None
        self.port = 9000
        self.cancelled = False  # Cancellation flag for background threads
        self.last_error = ""

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
        """Connect to Tally ODBC.

        Connection order:
          1. User-configured port (from QSettings) — tried first.
          2. Named DSNs TallyODBC64_9000 / TallyODBC_9000.
          3. Auto-discovery across ports [9000, 9001].
        Each RDP user stores their own port so multiple sessions can run
        separate Tally instances simultaneously.
        """
        try:
            user_port = get_tally_port()
            self.port = user_port
            logger.info(f"[TALLY CONNECT] Connecting strictly to user-configured port: {user_port}")

            # Strictly use the user-configured port — never attempt or fall back to other ports
            candidate_dsns = [
                f"DSN=TallyODBC64_{user_port}",
                f"DSN=TallyODBC_{user_port}",
            ]

            logger.info(f"[TALLY CONNECT] Trying candidate DSNs for port {user_port}: {candidate_dsns}")

            # 1. Try DSNs for user_port
            for dsn in candidate_dsns:
                conn = None
                try:
                    logger.debug(f"[TALLY CONNECT] Trying DSN: {dsn}")
                    conn = pyodbc.connect(dsn, timeout=2)
                    conn.timeout = 30  # Query timeout (seconds) — prevents pd.read_sql from hanging
                    # Verify connection is actually responsive to Tally
                    cur = conn.cursor()
                    cur.execute("SELECT $Name from Company")
                    cur.close()
                    self.connection = conn
                    logger.info(f"Connected to Tally via DSN: {dsn}")
                    return True
                except Exception as e:
                    logger.warning(f"[TALLY CONNECT] DSN {dsn} failed: {e}")
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            # 2. Driver-based fallback strictly on user_port
            all_drivers = pyodbc.drivers()
            drivers = [d for d in all_drivers if "Tally" in d]
            
            if not drivers:
                self.last_error = f"No 'Tally' ODBC drivers found in system to connect on port {user_port}."
                logger.error(f"[TALLY CONNECT] {self.last_error}")
                return False

            driver = drivers[0]
            logger.info(f"[TALLY CONNECT] Trying driver '{driver}' on user port {user_port}")
            
            conn = None
            try:
                conn_str = f"DRIVER={{{driver}}};SERVER=(local);PORT={user_port}"
                logger.debug(f"[TALLY CONNECT] Trying Driver string: {conn_str}")
                conn = pyodbc.connect(conn_str, timeout=2)
                conn.timeout = 30  # Query timeout (seconds)
                cur = conn.cursor()
                cur.execute("SELECT $Name from Company")
                cur.close()
                self.connection = conn
                logger.info(f"Connected to Tally via driver '{driver}' on port {user_port}")
                return True
            except Exception as e:
                logger.warning(f"[TALLY CONNECT] Driver string {conn_str} failed: {e}")
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

            self.last_error = (
                f"Could not connect to Tally on port {user_port}.\n"
                f"Please ensure Tally is running with ODBC enabled on port {user_port}."
            )
            logger.error(f"[TALLY CONNECT] Failed to connect on user port {user_port}. {self.last_error}")
            return False

        except Exception as e:
            logger.error(f"[TALLY CONNECT] Unhandled exception in connect(): {e}", exc_info=True)
            return False

    def _get_sqlalchemy_engine(self, db_name):
        """Create a SQLAlchemy engine using the server name and driver from db_manager."""
        server = self.db.server_name or r".\SQLEXPRESS"
        driver = self.db._get_best_driver() if hasattr(self.db, '_get_best_driver') else "ODBC Driver 17 for SQL Server"
        conn_parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={server}",
            f"DATABASE={db_name}",
            "Trusted_Connection=yes",
        ]
        if "18" in driver:
            conn_parts.append("TrustServerCertificate=yes")
        params = urllib.parse.quote_plus(";".join(conn_parts) + ";")
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
            
            # Verify critical column exists and sanitize GUIDs
            if "GUID" in export_df.columns:
                export_df["GUID"] = export_df["GUID"].fillna("").astype(str).str.strip()
                blank_guids = (export_df["GUID"] == "")
                if blank_guids.any():
                    import hashlib
                    export_df.loc[blank_guids, "GUID"] = export_df.loc[blank_guids, "Item_Name"].apply(
                        lambda x: "GEN_" + hashlib.md5(str(x).encode("utf-8")).hexdigest()
                    )
                export_df.drop_duplicates(subset=["GUID"], keep="last", inplace=True)
            else:
                logger.warning(f"GUID column missing after rename! Columns: {final_cols}")

            self._check_cancelled("before SQL Server write")

            # Ensure the stock_items table exists (for MERGE)
            self._ensure_stock_items_table(db_name)

            # Write to staging table for MERGE
            conn = self.db.get_connection(db_name)
            if not conn:
                raise Exception(f"Could not connect to SQL Server DB: {db_name}")

            cursor = conn.cursor()
            
            # Use a unique staging table per sync to eliminate multi-user collision
            staging_table = f"stock_items_staging_{uuid.uuid4().hex[:8]}"
            try:
                cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                pass

            # Bulk insert rows into staging using SQLAlchemy fast_executemany
            engine = self._get_sqlalchemy_engine(db_name)
            
            logger.info("Writing stock items to staging via SQLAlchemy (fast_executemany=True)")
            # Force NVARCHAR for strings with GUID/Item_Name sized to enable fast indexing
            col_type_overrides = {
                "GUID": NVARCHAR(255),
                "Item_Name": NVARCHAR(255),
                "SubGroup": NVARCHAR(255),
                "Category": NVARCHAR(255),
                "Part_No": NVARCHAR(255),
            }
            nvarchar_dtype = {
                col: col_type_overrides.get(col, NVARCHAR(length=None))
                for col in export_df.select_dtypes(include=['object']).columns
            }
            export_df.to_sql(staging_table, con=engine, if_exists="replace", index=False, dtype=nvarchar_dtype, schema="dbo")
            engine.dispose()

            self._check_cancelled("after staging write")

            # Verify staging has data before merging
            cursor.execute(f"SELECT COUNT(*) FROM dbo.[{staging_table}]")
            staging_count = cursor.fetchone()[0]
            if staging_count == 0:
                logger.warning("Staging table is empty, aborting merge")
                cursor.execute(f"DROP TABLE dbo.[{staging_table}]")
                conn.commit()
                raise Exception("Staging table was empty after insert")

            # MERGE: UPSERT changed/new rows + DELETE removed rows
            # Strictly filter to valid columns existing in dbo.stock_items to prevent schema mismatch
            cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'stock_items'")
            target_cols = set(r[0] for r in cursor.fetchall())
            valid_cols = [c for c in export_df.columns if c in target_cols]
            merge_cols = [c for c in valid_cols if c != "GUID"]
            update_set = ", ".join([f"target.[{c}] = source.[{c}]" for c in merge_cols])
            insert_cols = ", ".join([f"[{c}]" for c in valid_cols])
            source_cols = ", ".join([f"source.[{c}]" for c in valid_cols])

            merge_sql = f"""
                MERGE dbo.stock_items AS target
                USING dbo.[{staging_table}] AS source
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

            # Check for late cancellation — MERGE already committed but we
            # can still stop here before Final Data pipeline starts.
            self._check_cancelled("after MERGE")

            # Clean up staging table
            try:
                cursor.execute(f"DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                pass

            logger.info(f"Row data saved to SQL Server: db='{db_name}', rows={len(export_df)}")
            return True

        except InterruptedError:
            # Cancellation -- clean up staging if it exists
            logger.info("Tally sync cancelled -- cleaning up")
            if staging_table:
                try:
                    conn = self.db.get_connection(db_name)
                    if conn:
                        cursor = conn.cursor()
                        cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                        conn.commit()
                except Exception:
                    pass
            raise

        except Exception as e:
            logger.error(f"SQL Server save error: {e}", exc_info=True)
            if staging_table:
                try:
                    conn = self.db.get_connection(db_name)
                    if conn:
                        cursor = conn.cursor()
                        cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                        conn.commit()
                except Exception:
                    pass
            raise e

    def fetch_stock_items(self, company_name=None, company_path=None):
        try:
            if not self.connection:
                if not self.connect():
                    raise Exception("Could not connect to Tally")

            open_comps = []
            if company_name:
                # Guard: cancel() may have fired between connect() and here
                self._check_cancelled("before company check")
                comp_df = pd.read_sql("SELECT $Name from Company", self.connection)
                if comp_df is None or comp_df.empty:
                    raise Exception("No companies found running in Tally.")
                open_comps = [str(c).strip() for c in comp_df.iloc[:, 0].tolist() if str(c).strip()]
                matched_comp = next((c for c in open_comps if _are_company_names_matching(c, company_name)), None)
                if not matched_comp:
                    raise Exception(
                        f"Company '{company_name}' is not open in Tally.\n\n"
                        f"Open companies in Tally: {', '.join(open_comps)}\n"
                        f"Please open '{company_name}' in Tally and try again."
                    )
                self._exact_company_name = matched_comp

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
                open_str = f"Open companies in Tally: {', '.join(open_comps)}.\n\n" if len(open_comps) > 1 else ""
                hint_str = (
                    f"'{company_name}' is open in Tally, but is not the active (top) company.\n"
                    f"Please switch to '{company_name}' in Tally (press F3 to select it), then try syncing again."
                    if len(open_comps) > 1
                    else f"Check that '{company_name or 'the company'}' contains stock items in Tally."
                )
                raise Exception(
                    f"No stock items received from Tally for '{company_name or 'Active'}'.\n\n"
                    f"{open_str}{hint_str}"
                )

            self._check_cancelled("after Tally fetch")

            if company_name or company_path:
                self.save_to_sql_file(df, company_name, company_path)

            return df

        except InterruptedError:
            raise  # Let cancellation propagate cleanly

        except Exception as e:
            # cancel() closes self.connection, which causes pd.read_sql to raise
            # a pyodbc.Error (not InterruptedError).  Detect that case here so
            # the whole chain correctly surfaces as 'cancelled', not as an error.
            if self.cancelled:
                raise InterruptedError("Tally sync cancelled during ODBC fetch")
            raise e

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


def _to_tally_date_str(val) -> str:
    """Format a date value from Tally ODBC/pandas into Tally YYYYMMDD string."""
    if val is None or pd.isna(val):
        return ""
    import datetime
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return val.strftime("%Y%m%d")
    s = str(val).strip()
    if not s:
        return ""
    if re.match(r'^\d{8}$', s):
        return s
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    try:
        dt = pd.to_datetime(s)
        return dt.strftime("%Y%m%d")
    except Exception:
        return ""


def _parse_fiscal_year_from_name(company_name: str) -> tuple[str, str]:
    """Derive fiscal year YYYYMMDD start and end dates from company name tokens.
    
    Handles:
    - Nepali Bikram Sambat (BS) fiscal years: e.g. 'Jkhw and Company (2083/84)', 'H/W Divison (083/084)'
      BS 2083 -> Gregorian 2026 (Starts ~16 July 2026, Ends ~15 July 2027)
    - Indian / Gregorian fiscal years: e.g. 'Company (2024-25)' -> Starts 01 April 2024, Ends 31 March 2025
    """
    name = (company_name or "").strip()
    if not name:
        return "", ""

    # 1. Nepali BS Fiscal Year pattern: (2083/84), (083/084), (2082/83), 2082-83, etc.
    np_match = re.search(r'(?:20)?(7\d|8\d|9\d)\s*[/_-]\s*(?:20)?(\d{2,3})', name)
    if np_match:
        bs_start_yy = int(np_match.group(1))
        bs_start_year = 2000 + bs_start_yy
        ad_start_year = bs_start_year - 57
        # Nepali FY: Shrawan 1 (~July 16) to Ashad end (~July 15 of next year).
        # Bounds July 15 to July 17 safely cover calendar/leap day shifts.
        start_date = f"{ad_start_year}0715"
        end_date = f"{ad_start_year + 1}0717"
        return start_date, end_date

    # 2. Indian / Gregorian Fiscal Year pattern: (2024-25), (2025/26), 2024-2025
    ad_match = re.search(r'(20\d{2})\s*[/_-]\s*(20\d{2}|\d{2})', name)
    if ad_match:
        ad_start_year = int(ad_match.group(1))
        start_date = f"{ad_start_year}0401"
        end_date = f"{ad_start_year + 1}0331"
        return start_date, end_date

    return "", ""


def resolve_company_fiscal_dates(service=None, company_name=None, from_date=None, to_date=None) -> tuple[str, str]:
    """Resolve (start_date, end_date) in YYYYMMDD format for the company's fiscal year.
    
    Checks in order:
    1. Explicit arguments (if valid YYYYMMDD).
    2. Cached fiscal dates on service.
    3. Querying Tally ODBC Company table ($StartingFrom, $EndingAt) if connection is active.
    4. Parsing Nepali / Indian fiscal year tokens from company name.
    5. Fallback to current calendar year.
    """
    if from_date and to_date and len(str(from_date)) == 8 and len(str(to_date)) == 8:
        return str(from_date), str(to_date)

    target_name = (company_name or "").strip()

    # 2. Check service cache
    if service:
        cached = getattr(service, '_company_fiscal_dates', {}).get(target_name.lower())
        if cached and len(cached[0]) == 8 and len(cached[1]) == 8:
            return cached

    # 3. Query Tally ODBC Company table if connection is active
    if service and getattr(service, 'connection', None):
        try:
            comp_df = None
            for q in [
                "SELECT $Name, $StartingFrom, $EndingAt, $BooksFrom FROM Company",
                "SELECT $Name, $StartingFrom, $EndingAt FROM Company",
                "SELECT $Name FROM Company"
            ]:
                try:
                    comp_df = pd.read_sql(q, service.connection)
                    break
                except Exception:
                    continue

            if comp_df is not None and not comp_df.empty:
                matched_row = None
                # Pass 1: match using company name matcher (exact or normalized)
                for _, row in comp_df.iterrows():
                    c_name = str(row.iloc[0]).strip()
                    if _are_company_names_matching(c_name, target_name):
                        matched_row = row
                        break
                # Pass 2: substring match
                if matched_row is None and target_name:
                    for _, row in comp_df.iterrows():
                        c_name = str(row.iloc[0]).strip().lower()
                        if target_name.lower() in c_name or c_name in target_name.lower():
                            matched_row = row
                            break
                # Pass 3: default to first company if target_name is empty
                if matched_row is None and not target_name:
                    matched_row = comp_df.iloc[0]

                if matched_row is not None:
                    sf = _to_tally_date_str(matched_row.get("$StartingFrom"))
                    ea = _to_tally_date_str(matched_row.get("$EndingAt"))
                    derived_f, derived_t = _parse_fiscal_year_from_name(target_name)
                    if sf and len(sf) == 8:
                        start_year = int(sf[:4])
                        end_year = start_year + 1
                        fy_end = f"{end_year}{sf[4:]}"
                        actual_start = min(sf, derived_f) if derived_f else sf
                        actual_end = max(ea or "", fy_end, derived_t or "")
                        c_exact = str(matched_row.iloc[0]).strip()
                        if not hasattr(service, '_company_fiscal_dates'):
                            service._company_fiscal_dates = {}
                        service._company_fiscal_dates[target_name.lower()] = (actual_start, actual_end)
                        service._company_fiscal_dates[c_exact.lower()] = (actual_start, actual_end)
                        if hasattr(service, '__dict__'):
                            service._exact_company_name = c_exact
                        return actual_start, actual_end
        except Exception as e:
            logger.debug(f"[resolve_company_fiscal_dates] ODBC date lookup notice: {e}")

    # 4. Parse from company name
    f_date, t_date = _parse_fiscal_year_from_name(target_name)
    if f_date and t_date:
        return f_date, t_date

    # 5. Fallback to current calendar year
    import datetime
    today = datetime.date.today()
    return f"{today.year}0101", f"{today.year}1231"







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
            err = getattr(service, 'last_error', '') or "Could not connect to Tally. Please ensure Tally is running."
            return 0, err

        # ── Company mismatch check & fiscal date capture ─────────────────────
        if company_name:
            try:
                comp_df = None
                for q in [
                    "SELECT $Name, $StartingFrom, $EndingAt, $BooksFrom FROM Company",
                    "SELECT $Name, $StartingFrom, $EndingAt FROM Company",
                    "SELECT $Name FROM Company"
                ]:
                    try:
                        comp_df = pd.read_sql(q, service.connection)
                        break
                    except Exception:
                        continue

                if comp_df is not None and not comp_df.empty:
                    open_comps = [str(c).strip() for c in comp_df.iloc[:, 0].tolist() if str(c).strip()]
                    matched_comp = next((c for c in open_comps if _are_company_names_matching(c, company_name)), None)
                    if not matched_comp:
                        return 0, (
                            f"Company '{company_name}' is not open in Tally.\n"
                            f"Open companies in Tally: {', '.join(open_comps)}\n"
                            f"Please open '{company_name}' in Tally and try again."
                        )

                    if hasattr(service, '__dict__'):
                        service._exact_company_name = matched_comp

                    # Cache fiscal dates for voucher fetching
                    for _, row in comp_df.iterrows():
                        c_name = str(row.iloc[0]).strip().lower()
                        sf = _to_tally_date_str(row.get("$StartingFrom"))
                        ea = _to_tally_date_str(row.get("$EndingAt"))
                        if sf and ea:
                            if not hasattr(service, '_company_fiscal_dates'):
                                service._company_fiscal_dates = {}
                            service._company_fiscal_dates[c_name] = (sf, ea)
                            if _are_company_names_matching(c_name, company_name):
                                service._company_fiscal_dates[company_name.lower()] = (sf, ea)
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
                $DebitTotals,
                $CreditTotals,
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
            open_str = f"Open companies in Tally: {', '.join(open_comps)}.\n\n" if ('open_comps' in locals() and len(open_comps) > 1) else ""
            hint_str = (
                f"'{company_name}' is open in Tally, but is not the active (top) company.\n"
                f"Please switch to '{company_name}' in Tally (press F3 to select it), then try syncing again."
                if ('open_comps' in locals() and len(open_comps) > 1)
                else f"Check that '{company_name or 'the company'}' contains ledgers in Tally."
            )
            return 0, f"No ledger data received from Tally for '{company_name or 'Active'}'.\n\n{open_str}{hint_str}"

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
            "$DebitTotals": "Debit_Totals",
            "$CreditTotals": "Credit_Totals",
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
                ledger_df[col] = pd.to_numeric(ledger_df[col], errors='coerce').fillna(0.0) * -1

        for col in ["Debit_Totals", "Credit_Totals"]:
            if col in ledger_df.columns:
                ledger_df[col] = pd.to_numeric(ledger_df[col], errors='coerce').fillna(0.0).abs().round(2)
            else:
                ledger_df[col] = 0.0

        service._check_cancelled("before ledger SQL write")

        # Save to SQL Server LedgerData DB (clean standard columns only)
        resolved_comp_name = os.path.basename(company_path) if company_path else (company_name or "default")
        db_name = build_logical_name(resolved_comp_name, company_path=company_path) if company_path else build_logical_name(resolved_comp_name)
        service.db.ensure_database_exists(db_name, company_path or service.app_path)

        conn = service.db.get_connection(db_name)
        if not conn:
            return 0, f"Could not connect to SQL Server DB: {db_name}"

        cursor = conn.cursor()

        # Clean up any stale staging tables (> 2 hrs) from prior crashes
        try:
            cursor.execute("""
                SELECT name FROM sys.tables
                WHERE (name LIKE 'row_ledger_staging_%' OR name LIKE 'vat_row_ledger_staging_%')
                  AND create_date < DATEADD(hour, -2, GETDATE())
            """)
            stale_tables = [r[0] for r in cursor.fetchall()]
            for st in stale_tables:
                cursor.execute(f"IF OBJECT_ID('dbo.[{st}]', 'U') IS NOT NULL DROP TABLE dbo.[{st}]")
            if stale_tables:
                conn.commit()
        except Exception:
            pass

        # Session-isolated staging table pattern to prevent data loss or collisions on multi-user concurrency
        session_id = uuid.uuid4().hex[:8]
        staging_table = f"row_ledger_staging_{session_id}"
        try:
            cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
            conn.commit()
        except Exception:
            pass

        # Bulk insert rows into staging using SQLAlchemy fast_executemany
        engine = service._get_sqlalchemy_engine(db_name)
        
        logger.info("Writing ledger data to staging via SQLAlchemy (fast_executemany=True)")
        # Sized NVARCHAR for key columns to enable fast search indexes
        col_type_overrides = {
            "GUID": NVARCHAR(255),
            "Name": NVARCHAR(255),
            "Alias": NVARCHAR(255),
            "Group": NVARCHAR(255),
            "Sub_Group": NVARCHAR(255),
            "Pan_No.": NVARCHAR(255),
        }
        nvarchar_dtype = {
            col: col_type_overrides.get(col, NVARCHAR(length=None))
            for col in ledger_df.select_dtypes(include=['object']).columns
        }
        ledger_df.to_sql(staging_table, con=engine, if_exists="replace", index=False, dtype=nvarchar_dtype, schema="dbo")
        engine.dispose()

        service._check_cancelled("after ledger staging write")

        # Verify staging before swap
        cursor.execute(f"SELECT COUNT(*) FROM dbo.[{staging_table}]")
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"DROP TABLE dbo.[{staging_table}]")
            conn.commit()
            return 0, "Staging table empty after insert — original data preserved."

        # Atomic swap: drop old → rename staging
        try:
            cursor.execute("IF OBJECT_ID('dbo.row_ledger_data', 'U') IS NOT NULL DROP TABLE dbo.row_ledger_data")
            cursor.execute(f"EXEC sp_rename 'dbo.[{staging_table}]', 'row_ledger_data'")
            try:
                cursor.execute("CREATE NONCLUSTERED INDEX IX_row_ledger_data_name ON dbo.row_ledger_data ([Name])")
            except Exception:
                pass
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                pass
            cursor.close()

        logger.info(f"Ledger data saved to SQL Server: db='{db_name}', rows={len(ledger_df)}")
        return len(ledger_df), ""

    except InterruptedError:
        logger.info("Ledger sync cancelled")
        return 0, "cancelled"

    except Exception as e:
        # cancel() closes service.connection, which causes pd.read_sql to raise
        # a pyodbc.Error instead of InterruptedError — detect it here.
        if service.cancelled:
            logger.info("Ledger sync cancelled (via connection close)")
            return 0, "cancelled"
        return 0, str(e)

    finally:
        if service.connection:
            try:
                service.connection.close()
            except Exception:
                pass
            service.connection = None


def fetch_tally_vat_internal_data(company_name=None, company_path=None, service=None):
    """Fetch Internal Ledger data for VAT Working.
    
    Syncs standard ledger data directly to dbo.row_ledger_data (including Debit_Totals & Credit_Totals).
    """
    if service is None:
        service = TallyService()

    rc, err = fetch_tally_ledger_data(company_name=company_name, company_path=company_path, service=service)
    if err:
        return rc, err

    try:
        from src.logic.vat_manager import ensure_vat_tables, get_active_vat_company, run_auto_mapping_on_sync
        resolved_comp_name = os.path.basename(company_path) if company_path else (company_name or "default")
        db_name = build_logical_name(resolved_comp_name, company_path=company_path) if company_path else build_logical_name(resolved_comp_name)
        ensure_vat_tables(service.db, db_name)
        active_vat = get_active_vat_company(db_name)
        if active_vat:
            run_auto_mapping_on_sync(db_name, active_vat)
    except Exception as e:
        logger.warning(f"[fetch_tally_vat_internal_data] ensure_vat_tables warning: {e}")

    return rc, ""


def fetch_tally_vat_ledger_data(vat_company_name: str, company_name=None, company_path=None, service=None):
    """Fetch Sundry Debtors and Sundry Creditors for the configured VAT company from Tally.
    
    Args:
        vat_company_name: The configured VAT company name to match in Tally.
        company_name: Application company display name.
        company_path: Application company folder path.
        service: Optional TallyService instance for cancellation support.
        
    Returns:
        tuple (row_count: int, error: str)
    """
    if not vat_company_name or not vat_company_name.strip():
        return 0, "No VAT company configured. Please set VAT Company first."

    vat_company = vat_company_name.strip()
    if service is None:
        service = TallyService()

    try:
        if not service.connect():
            err = getattr(service, 'last_error', '') or "Could not connect to Tally. Please ensure Tally is running."
            return 0, err

        # Verify VAT company is open in Tally
        try:
            comp_df = pd.read_sql("SELECT $Name FROM Company", service.connection)
            if comp_df.empty:
                return 0, "No companies found running in Tally."
            
            open_comps = [str(c).strip() for c in comp_df.iloc[:, 0].tolist() if str(c).strip()]
            matched = any(_are_company_names_matching(c, vat_company) for c in open_comps)
            if not matched:
                return 0, (
                    f"VAT company '{vat_company}' is not active/open in Tally.\n"
                    f"Open companies in Tally: {', '.join(open_comps)}\n"
                    f"Please open '{vat_company}' in Tally and try again."
                )
        except Exception as ce:
            logger.warning(f"VAT Company check warning: {ce}")

        service._check_cancelled("before VAT ledger fetch")

        # Strictly required: Filter exclusively for Sundry Groups ('Sundry Debtors' and 'Sundry Creditors') as intended by system design
        vat_sql = """
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
                $DebitTotals,
                $CreditTotals,
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

        logger.info(f"Fetching VAT ledger data for '{vat_company}' from Tally...")
        ledger_df = pd.read_sql(vat_sql, service.connection)

        if ledger_df.empty:
            open_str = f"Open companies in Tally: {', '.join(open_comps)}.\n\n" if ('open_comps' in locals() and len(open_comps) > 1) else ""
            hint_str = (
                f"'{vat_company}' is open in Tally, but is not the active (top) company.\n"
                f"Please switch to '{vat_company}' in Tally (press F3 to select it), then try syncing again."
                if ('open_comps' in locals() and len(open_comps) > 1)
                else f"Check that '{vat_company}' contains ledgers in Tally."
            )
            return 0, f"No ledger data received from Tally for '{vat_company}'.\n\n{open_str}{hint_str}"

        service._check_cancelled("after VAT ledger fetch")

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
            "$DebitTotals": "Debit_Totals",
            "$CreditTotals": "Credit_Totals",
            "$_OverdueBills": "Overdue_Bills",
            "$_OnAccountValue": "On_Account_Value",
            "$_CashInFlow": "CashInFlow",
            "$_CashOutFlow": "CashOutFlow",
            "$_Performance": "Performance",
            "$_ThisQuarterBalance": "This_Qtr_Balance",
            "$_PrevQuarterBalance": "Prev_Qtr_Balance",
            "$IsBillWiseOn": "BillwiseOn",
        }

        # Case-insensitive column rename
        current_cols = {c.lower(): c for c in ledger_df.columns}
        resolved_mapping = {}
        for old_name, new_name in ledger_mapping.items():
            actual_col = current_cols.get(old_name.lower())
            if actual_col:
                resolved_mapping[actual_col] = new_name
        ledger_df.rename(columns=resolved_mapping, inplace=True)

        # Filter for Sundry Debtors and Sundry Creditors in pandas
        # Strictly required: Only Sundry Groups ('Sundry Debtors' and 'Sundry Creditors' and their subgroups) are included
        target_groups = {"sundry debtors", "sundry creditors"}
        is_debtor_or_creditor = pd.Series(False, index=ledger_df.index)
        if "Group" in ledger_df.columns:
            grp_s = ledger_df["Group"].astype(str).str.strip().str.lower()
            is_debtor_or_creditor |= grp_s.isin(target_groups) | grp_s.str.contains("sundry debtor|sundry creditor", regex=True)
        if "Sub_Group" in ledger_df.columns:
            sub_s = ledger_df["Sub_Group"].astype(str).str.strip().str.lower()
            is_debtor_or_creditor |= sub_s.isin(target_groups) | sub_s.str.contains("sundry debtor|sundry creditor", regex=True)

        # Exclude 'Othere Account' / 'Other Account'
        if "Sub_Group" in ledger_df.columns:
            sub_s = ledger_df["Sub_Group"].astype(str).str.strip().str.lower()
            is_other_account = sub_s.isin({"othere account", "other account", "othere accounts", "other accounts"}) | sub_s.str.contains(r"other.*account|othere.*account", regex=True)
            is_debtor_or_creditor &= ~is_other_account

        ledger_df = ledger_df[is_debtor_or_creditor].copy()

        if ledger_df.empty:
            return 0, f"No Sundry Debtor or Creditor ledgers found in Tally for '{vat_company}'."

        numeric_cols = [
            "Credit_Limit", "Opening_Balance", "Closing_Balance",
            "Overdue_Bills", "On_Account_Value", "CashInFlow",
            "CashOutFlow", "This_Qtr_Balance", "Prev_Qtr_Balance",
        ]
        for col in numeric_cols:
            if col in ledger_df.columns:
                ledger_df[col] = pd.to_numeric(ledger_df[col], errors='coerce').fillna(0.0) * -1

        for col in ["Debit_Totals", "Credit_Totals"]:
            if col in ledger_df.columns:
                ledger_df[col] = pd.to_numeric(ledger_df[col], errors='coerce').fillna(0.0).abs().round(2)
            else:
                ledger_df[col] = 0.0

        ledger_df["vat_company"] = vat_company

        service._check_cancelled("before VAT ledger SQL write")

        # Save to company DB on SQL Server
        from src.logic.vat_manager import ensure_vat_tables, run_auto_mapping_on_sync

        resolved_comp_name = os.path.basename(company_path) if company_path else (company_name or "default")
        db_name = build_logical_name(resolved_comp_name, company_path=company_path) if company_path else build_logical_name(resolved_comp_name)
        service.db.ensure_database_exists(db_name, company_path or service.app_path)
        ensure_vat_tables(service.db, db_name)

        conn = service.db.get_connection(db_name)
        if not conn:
            return 0, f"Could not connect to SQL Server DB: {db_name}"

        cursor = conn.cursor()

        staging_table = f"vat_row_ledger_staging_{uuid.uuid4().hex[:8]}"
        try:
            try:
                cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception as e:
                logger.debug(f"Could not drop pre-existing staging table {staging_table}: {e}")

            engine = service._get_sqlalchemy_engine(db_name)
            logger.info(f"Writing VAT ledger data to staging table '{staging_table}'...")
            col_type_overrides = {
                "GUID": NVARCHAR(255),
                "Name": NVARCHAR(255),
                "Alias": NVARCHAR(255),
                "Group": NVARCHAR(255),
                "Sub_Group": NVARCHAR(255),
                "Pan_No.": NVARCHAR(255),
                "vat_company": NVARCHAR(255),
            }
            nvarchar_dtype = {
                col: col_type_overrides.get(col, NVARCHAR(length=None))
                for col in ledger_df.select_dtypes(include=['object']).columns
            }
            ledger_df.to_sql(staging_table, con=engine, if_exists="replace", index=False, dtype=nvarchar_dtype, schema="dbo")
            engine.dispose()

            service._check_cancelled("after VAT ledger staging write")

            # Replace rows for this vat_company in dbo.vat_row_ledger_data
            try:
                # Query common columns between staging table and target table
                cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{staging_table}'")
                stg_cols = set(r[0] for r in cursor.fetchall())
                cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'vat_row_ledger_data'")
                target_cols = set(r[0] for r in cursor.fetchall())
                common_cols = [c for c in stg_cols if c in target_cols and c != 'id']
                cols_str = ", ".join(f"[{c}]" for c in common_cols)

                cursor.execute("DELETE FROM dbo.vat_row_ledger_data WHERE vat_company = ?", (vat_company,))
                cursor.execute(f"""
                    INSERT INTO dbo.vat_row_ledger_data ({cols_str})
                    SELECT {cols_str}
                    FROM dbo.[{staging_table}]
                """)
                cursor.execute(f"DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            try:
                cursor.execute(f"IF OBJECT_ID('dbo.[{staging_table}]', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                pass
            cursor.close()

        logger.info(f"VAT ledger data saved for '{vat_company}' in DB '{db_name}': {len(ledger_df)} rows")

        # Run auto-mapping for unmapped rows (without touching manual mappings)
        run_auto_mapping_on_sync(db_name, vat_company)

        return len(ledger_df), ""

    except InterruptedError:
        logger.info("VAT Ledger sync cancelled")
        return 0, "cancelled"

    except Exception as e:
        if service.cancelled:
            logger.info("VAT Ledger sync cancelled (via connection close)")
            return 0, "cancelled"
        logger.error(f"VAT Ledger sync error: {e}", exc_info=True)
        return 0, str(e)

    finally:
        if service.connection:
            try:
                service.connection.close()
            except Exception:
                pass
            service.connection = None

