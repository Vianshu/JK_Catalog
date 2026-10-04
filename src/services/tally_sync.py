import json
import os
import re
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
    b1 = re.sub(r'\d+', '', n1)
    b2 = re.sub(r'\d+', '', n2)
    if b1 and b1 == b2:
        return True
    return False


class TallyService:
    def __init__(self):
        self.connection = None
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
            
            # Drop staging table if leftover from a previous failed sync
            staging_table = "stock_items_staging"
            try:
                cursor.execute(f"IF OBJECT_ID('dbo.{staging_table}', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
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
            # Cancellation — clean up staging if it exists
            logger.info("Tally sync cancelled — cleaning up")
            try:
                conn = self.db.get_connection(db_name)
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("IF OBJECT_ID('dbo.stock_items_staging', 'U') IS NOT NULL DROP TABLE dbo.stock_items_staging")
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


def _parse_json_vouchers(data, start_date=None, end_date=None, party_case_map=None, sales_map=None, purchase_map=None, receipts_map=None, payments_map=None):
    """Extract Sales, Purchase, Receipts, Payments voucher totals from Tally JsonEx/JSON output.
    
    Operates directly on native Python dict/list structures produced by json.loads()
    with zero XML overhead, minimal memory allocation, and maximum throughput.
    """
    if sales_map is None: sales_map = {}
    if purchase_map is None: purchase_map = {}
    if receipts_map is None: receipts_map = {}
    if payments_map is None: payments_map = {}
    party_case_map = party_case_map or {}

    vouchers = []

    def _find_vouchers(obj):
        if isinstance(obj, list):
            for item in obj:
                _find_vouchers(item)
        elif isinstance(obj, dict):
            cleaned_keys = {re.sub(r'[^A-Z0-9]', '', k.upper()): k for k in obj.keys()}
            has_type = any(k in cleaned_keys for k in ("VOUCHERTYPENAME", "VCHTYPE", "PARTYLEDGERNAME", "VOUCHERNUMBER", "VCHNUM"))
            has_entries = any("LEDGERENTRIES" in k for k in cleaned_keys)
            if has_type and has_entries:
                vouchers.append(obj)
                return
            for k, v in obj.items():
                if "VOUCHER" in k.upper() and isinstance(v, (list, dict)):
                    _find_vouchers(v)
                elif isinstance(v, (list, dict)):
                    _find_vouchers(v)

    _find_vouchers(data)

    def _get_val(d, *possible_keys, default=""):
        d_clean = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in d.items()}
        for pk in possible_keys:
            clean_k = re.sub(r'[^a-z0-9]', '', pk.lower())
            if clean_k in d_clean:
                val = d_clean[clean_k]
                return str(val).strip() if val is not None else default
        return default

    def _get_num_val(d, *possible_keys, default=0.0):
        d_clean = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in d.items()}
        for pk in possible_keys:
            clean_k = re.sub(r'[^a-z0-9]', '', pk.lower())
            if clean_k in d_clean:
                val = d_clean[clean_k]
                if isinstance(val, (int, float)):
                    return abs(float(val))
                try:
                    return abs(float(str(val).replace(",", "").strip()))
                except (ValueError, TypeError):
                    return default
        return default

    def _get_entries(vch):
        all_entries = None
        ledger_entries = None
        for k, v in vch.items():
            k_clean = re.sub(r'[^a-z0-9]', '', k.lower())
            if "allledgerentries" in k_clean:
                all_entries = v if isinstance(v, list) else [v]
            elif "ledgerentries" in k_clean:
                ledger_entries = v if isinstance(v, list) else [v]
        if all_entries is not None:
            return all_entries
        if ledger_entries is not None:
            return ledger_entries
        return []

    for vch in vouchers:
        vch_date = _get_val(vch, "DATE")
        if vch_date and start_date and end_date:
            clean_date = "".join(c for c in vch_date if c.isdigit())
            if len(clean_date) == 8:
                if not (start_date <= clean_date <= end_date):
                    continue

        is_canc = _get_val(vch, "ISCANCELLED").lower() == "yes"
        is_opt = _get_val(vch, "ISOPTIONAL").lower() == "yes"
        is_del = _get_val(vch, "ISDELETED").lower() == "yes"
        if is_canc or is_opt or is_del:
            continue

        vtype = _get_val(vch, "VOUCHERTYPENAME", "VCHTYPE").lower()
        header_party = _get_val(vch, "PARTYLEDGERNAME")

        if any(ex in vtype for ex in ("order", "note", "payroll", "rejection", "attendance", "memo", "physical stock")):
            continue

        is_sale = ("sale" in vtype or "invoice" in vtype) and "purch" not in vtype
        is_purchase = "purch" in vtype
        is_receipt = "receipt" in vtype or "rcpt" in vtype
        is_payment = "pay" in vtype or "pymt" in vtype

        if not (is_sale or is_purchase or is_receipt or is_payment):
            continue

        entries = _get_entries(vch)
        party_found = False

        for le in entries:
            if not isinstance(le, dict):
                continue
            lname = _get_val(le, "LEDGERNAME", "NAME")
            amt = _get_num_val(le, "AMOUNT", "BILLEDAMOUNT", default=0.0)
            is_party_tag = _get_val(le, "ISPARTYLEDGER").lower() == "yes"

            if not lname or amt == 0.0:
                continue

            matched_party = lname
            is_known = False
            if party_case_map:
                canon = party_case_map.get(lname.lower())
                if canon:
                    is_known = True
                    matched_party = canon

            is_party = is_known or is_party_tag or (header_party and lname.lower() == header_party.lower())
            if not is_party and not party_case_map:
                lower_l = lname.lower()
                non_parties = ("cash", "bank", "vat", "tax", "discount", "round off", "sales", "purchase", "cgst", "sgst", "igst")
                if not any(np in lower_l for np in non_parties):
                    is_party = True

            if is_party:
                party_found = True
                if is_sale:
                    sales_map[matched_party] = round(sales_map.get(matched_party, 0.0) + amt, 2)
                elif is_purchase:
                    purchase_map[matched_party] = round(purchase_map.get(matched_party, 0.0) + amt, 2)
                elif is_receipt:
                    receipts_map[matched_party] = round(receipts_map.get(matched_party, 0.0) + amt, 2)
                elif is_payment:
                    payments_map[matched_party] = round(payments_map.get(matched_party, 0.0) + amt, 2)

        if not party_found and header_party:
            canon_header = party_case_map.get(header_party.lower(), header_party) if party_case_map else header_party
            max_amt = 0.0
            for le in entries:
                if isinstance(le, dict):
                    max_amt = max(max_amt, _get_num_val(le, "AMOUNT", default=0.0))
            if max_amt > 0:
                if is_sale:
                    sales_map[canon_header] = round(sales_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_purchase:
                    purchase_map[canon_header] = round(purchase_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_receipt:
                    receipts_map[canon_header] = round(receipts_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_payment:
                    payments_map[canon_header] = round(payments_map.get(canon_header, 0.0) + max_amt, 2)

    return sales_map, purchase_map, receipts_map, payments_map


def _parse_xml_vouchers(
    raw_xml: str,
    start_date: str = None,
    end_date: str = None,
    party_case_map: dict = None,
    sales_map: dict = None,
    purchase_map: dict = None,
    receipts_map: dict = None,
    payments_map: dict = None,
):
    """Parse Tally TDL Collection XML export into sales, purchase, receipts, and payments maps."""
    if sales_map is None: sales_map = {}
    if purchase_map is None: purchase_map = {}
    if receipts_map is None: receipts_map = {}
    if payments_map is None: payments_map = {}

    import xml.etree.ElementTree as ET

    def _clean_entities(match):
        code = int(match.group(1))
        if code in (9, 10, 13) or (32 <= code <= 0xD7FF) or (0xE000 <= code <= 0xFFFD):
            return chr(code)
        return ""

    cleaned_xml = re.sub(r'&#(\d+);', _clean_entities, raw_xml)
    cleaned_xml = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned_xml)

    # Fix unescaped ampersands in party names or text fields (e.g. M/S A & B -> M/S A &amp; B)
    cleaned_xml = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', cleaned_xml)

    # Strip unbound namespace prefixes from tags (e.g. <UDF:VATDEALERTYPE> -> <VATDEALERTYPE>)
    # and attributes to prevent Expat "unbound prefix" fatal parse error
    cleaned_xml = re.sub(r'(</?)[a-zA-Z0-9_.-]+:([a-zA-Z0-9_.-]+)', r'\1\2', cleaned_xml)
    cleaned_xml = re.sub(r'(\s+)[a-zA-Z0-9_.-]+:([a-zA-Z0-9_.-]+)=', r'\1\2=', cleaned_xml)

    try:
        root = ET.fromstring(cleaned_xml)
    except Exception as e:
        logger.warning(f"[tally_sync] Voucher XML parse error: {e}")
        return sales_map, purchase_map, receipts_map, payments_map

    vch_elements = root.findall(".//VOUCHER")

    for vch in vch_elements:
        v_date = vch.findtext("DATE", "").strip()
        if v_date and start_date and end_date:
            clean_date = "".join(c for c in v_date if c.isdigit())
            if len(clean_date) == 8 and not (start_date <= clean_date <= end_date):
                continue

        is_canc = vch.findtext("ISCANCELLED", "").strip().lower() == "yes"
        is_opt = vch.findtext("ISOPTIONAL", "").strip().lower() == "yes"
        is_del = vch.findtext("ISDELETED", "").strip().lower() == "yes"
        if is_canc or is_opt or is_del:
            continue

        vtype = vch.findtext("VOUCHERTYPENAME", "").strip().lower()
        if any(ex in vtype for ex in ("order", "note", "payroll", "rejection", "attendance", "memo", "physical stock")):
            continue

        is_sale = ("sale" in vtype or "invoice" in vtype) and "purch" not in vtype
        is_purchase = "purch" in vtype
        is_receipt = "receipt" in vtype or "rcpt" in vtype
        is_payment = "pay" in vtype or "pymt" in vtype

        if not (is_sale or is_purchase or is_receipt or is_payment):
            continue

        header_party = vch.findtext("PARTYLEDGERNAME", "").strip()
        party_found = False

        entries = []
        for child in vch:
            if child.tag in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"):
                lname = child.findtext("LEDGERNAME", "").strip()
                amt_str = child.findtext("AMOUNT", "0").strip()
                is_party_tag = child.findtext("ISPARTYLEDGER", "No").strip().lower() == "yes"
                try:
                    amt_num = abs(float(amt_str))
                except (ValueError, TypeError):
                    amt_num = 0.0

                if not lname or amt_num == 0.0:
                    continue

                entries.append((lname, amt_num, is_party_tag))

                matched_party = None
                if party_case_map:
                    matched_party = party_case_map.get(lname.lower())

                if not matched_party and is_party_tag:
                    matched_party = lname

                if not matched_party and not party_case_map:
                    lower_l = lname.lower()
                    non_parties = ("cash", "bank", "vat", "tax", "discount", "round off", "sales", "purchase", "cgst", "sgst", "igst")
                    if not any(np in lower_l for np in non_parties):
                        matched_party = lname

                if matched_party:
                    party_found = True
                    if is_sale:
                        sales_map[matched_party] = round(sales_map.get(matched_party, 0.0) + amt_num, 2)
                    elif is_purchase:
                        purchase_map[matched_party] = round(purchase_map.get(matched_party, 0.0) + amt_num, 2)
                    elif is_receipt:
                        receipts_map[matched_party] = round(receipts_map.get(matched_party, 0.0) + amt_num, 2)
                    elif is_payment:
                        payments_map[matched_party] = round(payments_map.get(matched_party, 0.0) + amt_num, 2)

        # Fallback to header party if no entry matched
        if not party_found and header_party:
            canon_header = party_case_map.get(header_party.lower(), header_party) if party_case_map else header_party
            max_amt = max((e[1] for e in entries), default=0.0)
            if max_amt > 0:
                if is_sale:
                    sales_map[canon_header] = round(sales_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_purchase:
                    purchase_map[canon_header] = round(purchase_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_receipt:
                    receipts_map[canon_header] = round(receipts_map.get(canon_header, 0.0) + max_amt, 2)
                elif is_payment:
                    payments_map[canon_header] = round(payments_map.get(canon_header, 0.0) + max_amt, 2)

    return sales_map, purchase_map, receipts_map, payments_map


def fetch_tally_voucher_breakdown(service=None, company_name=None, known_parties=None, from_date=None, to_date=None):
    """Fetch Sales, Purchase, Receipts, and Payments voucher totals per party.
    
    Uses official TDL Collection Export XML (CustomVoucherColl) fetching DATE,
    VOUCHERTYPENAME, VOUCHERNUMBER, PARTYLEDGERNAME, ALLLEDGERENTRIES.LIST.
    Bypasses GUI visual reports to prevent modal TDL error popups.
    Strictly constrains voucher retrieval to the current fiscal year of the target company.
    
    Returns: (sales_map: dict, purchase_map: dict, receipts_map: dict, payments_map: dict)
    """
    sales_map = {}
    purchase_map = {}
    receipts_map = {}
    payments_map = {}

    if service and getattr(service, 'cancelled', False):
        return sales_map, purchase_map, receipts_map, payments_map

    try:
        import urllib.request
        import urllib.error
        import socket
        import time

        party_case_map = {}
        if known_parties:
            if isinstance(known_parties, dict):
                for k, v in known_parties.items():
                    if k and v:
                        party_case_map[str(k).strip().lower()] = str(v).strip()
            else:
                for p in known_parties:
                    p_str = str(p).strip()
                    if p_str:
                        party_case_map[p_str.lower()] = p_str

        user_port = get_tally_port() or 9000
        candidate_ports = [user_port]
        if user_port != 9000:
            candidate_ports.append(9000)

        # Strictly constrain vouchers to the company's current fiscal year
        start_date, end_date = resolve_company_fiscal_dates(
            service=service, company_name=company_name, from_date=from_date, to_date=to_date
        )

        exact_comp = getattr(service, '_exact_company_name', None) if service else None
        target_company = exact_comp or (company_name or "").strip()
        escaped_company = (
            target_company
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        comp_tag = f"<SVCURRENTCOMPANY>{escaped_company}</SVCURRENTCOMPANY>" if target_company else ""
        logger.info(
            f"[tally_sync] Fiscal year voucher date scope for '{target_company or 'Active'}': {start_date} to {end_date}"
        )

        date_tags = ""
        if start_date and end_date:
            date_tags = f"""<SVFROMDATE TYPE="Date">{start_date}</SVFROMDATE>
          <SVTODATE TYPE="Date">{end_date}</SVTODATE>"""

        xml_request = f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>EXPORT</TALLYREQUEST>
    <TYPE>COLLECTION</TYPE>
    <ID>CustomVoucherColl</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {date_tags}
        {comp_tag}
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="CustomVoucherColl" ISINITIALIZE="Yes">
            <TYPE>Voucher</TYPE>
            <FETCH>DATE,VOUCHERTYPENAME,VOUCHERNUMBER,PARTYLEDGERNAME,ALLLEDGERENTRIES.LIST</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""

        req_bytes = xml_request.encode("utf-8")
        last_error = None
        http_timeout = 15  # Fast 15s timeout to protect UI responsiveness

        for port in candidate_ports:
            if service and getattr(service, 'cancelled', False):
                break

            url = f"http://127.0.0.1:{port}"
            logger.info(f"[tally_sync] Requesting Vouchers XML on port {port} for '{target_company or 'Active'}'...")
            req = urllib.request.Request(
                url,
                data=req_bytes,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "Content-Length": str(len(req_bytes)),
                }
            )
            try:
                start_t = time.time()
                with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                    raw_data = resp.read().decode("utf-8", errors="ignore")
                    elapsed = time.time() - start_t

                cleaned = raw_data.strip()
                if cleaned:
                    logger.info(
                        f"[tally_sync] Received Voucher XML payload ({len(cleaned):,} bytes) from port {port} in {elapsed:.2f}s."
                    )
                    _parse_xml_vouchers(
                        cleaned, start_date=start_date, end_date=end_date,
                        party_case_map=party_case_map, sales_map=sales_map,
                        purchase_map=purchase_map, receipts_map=receipts_map,
                        payments_map=payments_map
                    )
                    logger.info(
                        f"[tally_sync] Voucher breakdown for '{target_company or 'Active'}': "
                        f"{len(sales_map)} sales, {len(purchase_map)} purchases, "
                        f"{len(receipts_map)} receipts, {len(payments_map)} payments."
                    )
                    return sales_map, purchase_map, receipts_map, payments_map

            except urllib.error.URLError as ue:
                reason = getattr(ue, 'reason', ue)
                if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                    last_error = f"Timeout ({http_timeout}s) connecting to Tally on port {port}"
                else:
                    last_error = f"URLError on port {port}: {reason}"
                logger.warning(f"[tally_sync] {last_error}")
                continue
            except TimeoutError:
                last_error = f"Timeout ({http_timeout}s) connecting to Tally on port {port}"
                logger.warning(f"[tally_sync] {last_error}")
                continue
            except Exception as e:
                last_error = f"Error fetching vouchers on port {port}: {e}"
                logger.warning(f"[tally_sync] {last_error}")
                continue

        if last_error:
            logger.warning(
                f"[tally_sync] Could not retrieve vouchers across candidate ports {candidate_ports}. Last note: {last_error}"
            )
    except Exception as ge:
        logger.warning(f"[tally_sync] Unexpected voucher sync error: {ge}")

    return sales_map, purchase_map, receipts_map, payments_map


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

        service._check_cancelled("before ledger SQL write")

        # Save to SQL Server LedgerData DB (clean standard columns only)
        resolved_comp_name = os.path.basename(company_path) if company_path else (company_name or "default")
        db_name = build_logical_name(resolved_comp_name, company_path=company_path) if company_path else build_logical_name(resolved_comp_name)
        service.db.ensure_database_exists(db_name, company_path or service.app_path)

        conn = service.db.get_connection(db_name)
        if not conn:
            return 0, f"Could not connect to SQL Server DB: {db_name}"

        cursor = conn.cursor()

        # Use staging table pattern to prevent data loss on failure
        staging_table = "row_ledger_data_staging"
        try:
            cursor.execute(f"IF OBJECT_ID('dbo.{staging_table}', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
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
            cursor.execute(f"EXEC sp_rename 'dbo.{staging_table}', 'row_ledger_data'")
            try:
                cursor.execute("CREATE NONCLUSTERED INDEX IX_row_ledger_data_name ON dbo.row_ledger_data ([Name])")
            except Exception:
                pass
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
    """Fetch Internal Ledger data AND voucher breakdown for VAT Working.
    
    1. Syncs standard ledger data to dbo.row_ledger_data (clean master columns only).
    2. Fetches voucher breakdown (Sales, Purchase, Receipts, Payments) and saves to
       dedicated table dbo.vat_int_voucher_totals for VAT Working only.
    """
    if service is None:
        service = TallyService()

    # 1. Sync standard ledger data (keeps row_ledger_data clean)
    rc, err = fetch_tally_ledger_data(company_name=company_name, company_path=company_path, service=service)
    if err and err != "cancelled":
        return rc, err
    if getattr(service, 'cancelled', False):
        return 0, "cancelled"

    # 2. Fetch voucher breakdown for VAT Working
    try:
        resolved_comp_name = os.path.basename(company_path) if company_path else (company_name or "default")
        db_name = build_logical_name(resolved_comp_name, company_path=company_path) if company_path else build_logical_name(resolved_comp_name)

        vch_company = company_name or (os.path.basename(company_path) if company_path else "")
        
        # Pre-load known debtors and creditors from row_ledger_data to ensure accurate receipt/payment party matching
        internal_parties = {}
        try:
            conn = service.db.get_connection(db_name)
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT [Name], [Alias] FROM dbo.row_ledger_data
                    WHERE LOWER(LTRIM(RTRIM([Group]))) IN ('sundry debtors', 'sundry creditors')
                       OR LOWER(LTRIM(RTRIM(Sub_Group))) IN ('sundry debtors', 'sundry creditors')
                """)
                for row in cursor.fetchall():
                    p_name = str(row[0]).strip() if row[0] else ""
                    p_alias = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    if p_name:
                        internal_parties[p_name.lower()] = p_name
                        if p_alias:
                            internal_parties[p_alias.lower()] = p_name
        except Exception as pe:
            logger.debug(f"[fetch_tally_vat_internal_data] Could not pre-load party names: {pe}")

        sales_map, purchase_map, receipts_map, payments_map = fetch_tally_voucher_breakdown(
            service, company_name=vch_company, known_parties=internal_parties
        )

        # Build list of distinct parties across maps
        all_parties = set(sales_map.keys()) | set(purchase_map.keys()) | set(receipts_map.keys()) | set(payments_map.keys())
        
        from src.logic.vat_manager import ensure_vat_tables, save_internal_voucher_breakdown
        ensure_vat_tables(service.db, db_name)

        party_records = []
        for p in all_parties:
            p_name = str(p).strip()
            if not p_name:
                continue
            s_amt = sales_map.get(p, 0.0)
            pu_amt = purchase_map.get(p, 0.0)
            r_amt = receipts_map.get(p, 0.0)
            py_amt = payments_map.get(p, 0.0)
            party_records.append({
                "Name": p_name,
                "Sales_Amount": round(s_amt, 2),
                "Purchase_Amount": round(pu_amt, 2),
                "Sales_Plus_Purchase": round(s_amt + pu_amt, 2),
                "Receipt_Amount": round(r_amt, 2),
                "Payment_Amount": round(py_amt, 2)
            })

        save_internal_voucher_breakdown(db_name, party_records)
        return rc, ""
    except Exception as e:
        logger.error(f"[fetch_tally_vat_internal_data] voucher breakdown error: {e}", exc_info=True)
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

        # Verify VAT company is open in Tally and capture fiscal dates
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

            if comp_df is None or comp_df.empty:
                return 0, "No companies found running in Tally."
            open_comps = [str(c).strip() for c in comp_df.iloc[:, 0].tolist()]
            matched = any(_are_company_names_matching(c, vat_company) for c in open_comps)
            if not matched:
                return 0, (
                    f"VAT company '{vat_company}' is not active/open in Tally.\n"
                    f"Open companies in Tally: {', '.join(open_comps)}\n"
                    f"Please open '{vat_company}' in Tally and try again."
                )

            # Cache fiscal dates for voucher fetching
            for _, row in comp_df.iterrows():
                c_name = str(row.iloc[0]).strip().lower()
                sf = _to_tally_date_str(row.get("$StartingFrom"))
                ea = _to_tally_date_str(row.get("$EndingAt"))
                if sf and ea:
                    if not hasattr(service, '_company_fiscal_dates'):
                        service._company_fiscal_dates = {}
                    service._company_fiscal_dates[c_name] = (sf, ea)
                    if _are_company_names_matching(c_name, vat_company):
                        service._company_fiscal_dates[vat_company.lower()] = (sf, ea)
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

        # Collect known debtor/creditor names and aliases from VAT ledger dataframe
        vat_party_map = {}
        for _, r in ledger_df.iterrows():
            p_name = str(r.get("Name", "")).strip()
            p_alias = str(r.get("Alias", "")).strip() if "Alias" in ledger_df.columns else ""
            if p_name and p_name != "nan":
                vat_party_map[p_name.lower()] = p_name
                if p_alias and p_alias != "nan":
                    vat_party_map[p_alias.lower()] = p_name

        # Fetch and map Sales, Purchase, Receipts, Payments from Vouchers
        sales_map, purchase_map, receipts_map, payments_map = fetch_tally_voucher_breakdown(
            service, company_name=vat_company, known_parties=vat_party_map
        )
        # Map voucher amounts: exact match first, case-insensitive fallback to prevent dropping party totals
        def _map_amounts(name_series, amount_map):
            clean_map = {str(k).strip(): v for k, v in amount_map.items()}
            res = name_series.map(clean_map)
            if res.isna().any():
                lower_map = {str(k).strip().lower(): v for k, v in amount_map.items()}
                fallback = name_series.str.lower().map(lower_map)
                res = res.fillna(fallback)
            return res.fillna(0.0).round(2)

        name_col = ledger_df["Name"].astype(str).str.strip()
        ledger_df["Sales_Amount"] = _map_amounts(name_col, sales_map)
        ledger_df["Purchase_Amount"] = _map_amounts(name_col, purchase_map)
        ledger_df["Receipt_Amount"] = _map_amounts(name_col, receipts_map)
        ledger_df["Payment_Amount"] = _map_amounts(name_col, payments_map)
        ledger_df["Sales_Plus_Purchase"] = (ledger_df["Sales_Amount"] + ledger_df["Purchase_Amount"]).round(2)

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

        staging_table = "vat_row_ledger_staging"
        try:
            cursor.execute(f"IF OBJECT_ID('dbo.{staging_table}', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
            conn.commit()
        except Exception:
            pass

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

