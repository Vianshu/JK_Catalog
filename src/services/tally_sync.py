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
                cursor.execute(f"IF OBJECT_ID('dbo.{staging_table}', 'U') IS NOT NULL DROP TABLE dbo.[{staging_table}]")
                conn.commit()
            except Exception:
                pass

            # Bulk insert rows into staging using SQLAlchemy fast_executemany
            engine = self._get_sqlalchemy_engine(db_name)
            
            logger.info("Writing stock items to staging via SQLAlchemy (fast_executemany=True)")
            # Force NVARCHAR for all string columns so Hindi/Unicode text is preserved
            nvarchar_dtype = {col: NVARCHAR(length=None) for col in export_df.select_dtypes(include=['object']).columns}
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
            # All columns except GUID are updated on match
            merge_cols = [c for c in export_df.columns if c != "GUID"]
            update_set = ", ".join([f"target.[{c}] = source.[{c}]" for c in merge_cols])
            insert_cols = ", ".join([f"[{c}]" for c in export_df.columns])
            source_cols = ", ".join([f"source.[{c}]" for c in export_df.columns])

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

            if company_name:
                # Guard: cancel() may have fired between connect() and here
                self._check_cancelled("before company check")
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
            # cancel() closes self.connection, which causes pd.read_sql to raise
            # a pyodbc.Error (not InterruptedError).  Detect that case here so
            # the whole chain correctly surfaces as 'cancelled', not as an error.
            if self.cancelled:
                raise InterruptedError("Tally sync cancelled during ODBC fetch")
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


def _clean_xml_text(text: str) -> str:
    import re
    def replace_entity(match):
        try:
            val = int(match.group(1))
            if val in (9, 10, 13) or val >= 32:
                return chr(val)
            return ""
        except Exception:
            return ""
    text = re.sub(r'&#(\d+);', replace_entity, text)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def fetch_tally_voucher_breakdown(service=None, company_name=None):
    """Fetch Sales, Purchase, Receipts, and Payments voucher totals per party via Tally HTTP XML API.
    
    Uses per-user configured Tally port with automatic fallback candidates.
    Verifies company presence and parses voucher entries with robust error handling and logging.
    
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
        import xml.etree.ElementTree as ET

        user_port = get_tally_port() or 9000
        candidate_ports = [user_port]

        target_company = (company_name or "").strip()
        comp_tag = f"<SVCURRENTCOMPANY>{target_company}</SVCURRENTCOMPANY>" if target_company else ""

        xml_req = f"""<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Voucher Register</REPORTNAME>
        <STATICVARIABLES>
          <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
          {comp_tag}
        </STATICVARIABLES>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""

        req_bytes = xml_req.encode("utf-8")

        # Try candidate ports
        last_error = None
        for port in candidate_ports:
            if service and getattr(service, 'cancelled', False):
                break

            url = f"http://localhost:{port}"
            logger.info(f"[tally_sync] Attempting Voucher XML fetch on port {port} for company '{target_company or 'Active'}'...")
            req = urllib.request.Request(
                url,
                data=req_bytes,
                headers={"Content-Type": "text/xml; charset=utf-8"}
            )
            try:
                with urllib.request.urlopen(req, timeout=6) as resp:
                    raw_xml = resp.read().decode("utf-8", errors="ignore")
                    cleaned = _clean_xml_text(raw_xml)
                root = ET.fromstring(cleaned)

                # Check if Tally returned an explicit error (e.g. company not open)
                line_err = root.findtext(".//LINEERROR")
                if line_err:
                    logger.warning(
                        f"[tally_sync] Tally returned error on port {port} for company '{target_company}': {line_err.strip()}"
                    )
                    return sales_map, purchase_map, receipts_map, payments_map

                vouchers = root.findall(".//VOUCHER")
                logger.info(
                    f"[tally_sync] Voucher XML received from port {port} for '{target_company or 'Active'}': "
                    f"{len(raw_xml):,} bytes, {len(vouchers)} vouchers found."
                )

                for vch in vouchers:
                    vtype = (vch.findtext("VOUCHERTYPENAME") or "").strip().lower()
                    header_party = (vch.findtext("PARTYLEDGERNAME") or "").strip()

                    # Exclude non-financial / order / inventory voucher types
                    if any(ex in vtype for ex in ("order", "note", "payroll", "rejection", "attendance")):
                        continue

                    # Avoid duplicate entry iteration if XML renders both lists
                    entries = vch.findall(".//ALLLEDGERENTRIES.LIST")
                    if not entries:
                        entries = vch.findall(".//LEDGERENTRIES.LIST")

                    is_sale = "sale" in vtype
                    is_purchase = "purch" in vtype
                    is_receipt = "receipt" in vtype
                    is_payment = "pay" in vtype

                    if not (is_sale or is_purchase or is_receipt or is_payment):
                        continue

                    party_found = False
                    for le in entries:
                        lname = (le.findtext("LEDGERNAME") or "").strip()
                        amt_str = le.findtext("AMOUNT", "0")
                        is_party = (le.findtext("ISPARTYLEDGER") or "").strip().lower() == "yes"

                        try:
                            amt = abs(float(amt_str))
                        except ValueError:
                            amt = 0.0

                        if not lname or amt == 0.0:
                            continue

                        # Check if this entry is the party ledger
                        if is_party or (header_party and lname.lower() == header_party.lower()):
                            party_found = True
                            if is_sale:
                                sales_map[lname] = round(sales_map.get(lname, 0.0) + amt, 2)
                            elif is_purchase:
                                purchase_map[lname] = round(purchase_map.get(lname, 0.0) + amt, 2)
                            elif is_receipt:
                                receipts_map[lname] = round(receipts_map.get(lname, 0.0) + amt, 2)
                            elif is_payment:
                                payments_map[lname] = round(payments_map.get(lname, 0.0) + amt, 2)

                    # Fallback for vouchers where header party is set but entries lack ISPARTYLEDGER flag
                    if not party_found and header_party:
                        max_amt = 0.0
                        for le in entries:
                            try:
                                max_amt = max(max_amt, abs(float(le.findtext("AMOUNT", "0"))))
                            except ValueError:
                                pass
                        if max_amt > 0:
                            if is_sale:
                                sales_map[header_party] = round(sales_map.get(header_party, 0.0) + max_amt, 2)
                            elif is_purchase:
                                purchase_map[header_party] = round(purchase_map.get(header_party, 0.0) + max_amt, 2)
                            elif is_receipt:
                                receipts_map[header_party] = round(receipts_map.get(header_party, 0.0) + max_amt, 2)
                            elif is_payment:
                                payments_map[header_party] = round(payments_map.get(header_party, 0.0) + max_amt, 2)

                logger.info(
                    f"[tally_sync] Voucher breakdown summary for '{target_company or 'Active'}': "
                    f"{len(sales_map)} parties with sales, {len(purchase_map)} with purchase, "
                    f"{len(receipts_map)} with receipts, {len(payments_map)} with payments."
                )
                return sales_map, purchase_map, receipts_map, payments_map

            except urllib.error.URLError as ue:
                last_error = f"URLError on port {port}: {ue.reason if hasattr(ue, 'reason') else ue}"
                logger.debug(f"[tally_sync] {last_error}")
            except TimeoutError:
                last_error = f"Timeout (6s) connecting to Tally on port {port}"
                logger.debug(f"[tally_sync] {last_error}")
            except ET.ParseError as pe:
                last_error = f"XML parse error on port {port}: {pe}"
                logger.warning(f"[tally_sync] {last_error}")
                break
            except Exception as e:
                last_error = f"Error fetching voucher XML on port {port}: {e}"
                logger.warning(f"[tally_sync] {last_error}")

        if last_error:
            logger.warning(
                f"[tally_sync] Could not retrieve voucher XML across candidate ports {candidate_ports}. Last note: {last_error}"
            )
    except Exception as ge:
        logger.warning(f"[tally_sync] Unexpected voucher XML error: {ge}")

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
        # Force NVARCHAR for all string columns so Hindi/Unicode text is preserved
        nvarchar_dtype = {col: NVARCHAR(length=None) for col in ledger_df.select_dtypes(include=['object']).columns}
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
        # With autocommit=False, both statements run in the same implicit
        # transaction — conn.commit() makes them atomic.
        try:
            cursor.execute("IF OBJECT_ID('dbo.row_ledger_data', 'U') IS NOT NULL DROP TABLE dbo.row_ledger_data")
            cursor.execute(f"EXEC sp_rename 'dbo.{staging_table}', 'row_ledger_data'")
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
        sales_map, purchase_map, receipts_map, payments_map = fetch_tally_voucher_breakdown(service, company_name=vch_company)

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

        # Verify VAT company is open in Tally
        try:
            comp_df = pd.read_sql("SELECT $Name from Company", service.connection)
            if comp_df.empty:
                return 0, "No companies found running in Tally."
            open_comps = [str(c).strip() for c in comp_df.iloc[:, 0].tolist()]
            # Case-insensitive match
            matched = any(c.lower() == vat_company.lower() for c in open_comps)
            if not matched:
                return 0, (
                    f"VAT company '{vat_company}' is not active/open in Tally.\n"
                    f"Open companies in Tally: {', '.join(open_comps)}\n"
                    f"Please open '{vat_company}' in Tally and try again."
                )
        except Exception as ce:
            logger.warning(f"VAT Company check warning: {ce}")

        service._check_cancelled("before VAT ledger fetch")

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
            WHERE $_PrimaryGroup = 'Sundry Debtors' OR $_PrimaryGroup = 'Sundry Creditors'
        """

        logger.info(f"Fetching VAT ledger data for '{vat_company}' from Tally...")
        ledger_df = pd.read_sql(vat_sql, service.connection)

        if ledger_df.empty:
            return 0, f"No ledger data received from Tally for '{vat_company}'."

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
        # Avoids Tally ODBC's fragile SQL WHERE parser ('HY000: The driver did not supply an error!')
        target_groups = {"sundry debtors", "sundry creditors"}
        is_debtor_or_creditor = pd.Series(False, index=ledger_df.index)
        if "Group" in ledger_df.columns:
            is_debtor_or_creditor |= ledger_df["Group"].astype(str).str.strip().str.lower().isin(target_groups)
        if "Sub_Group" in ledger_df.columns:
            is_debtor_or_creditor |= ledger_df["Sub_Group"].astype(str).str.strip().str.lower().isin(target_groups)

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
                ledger_df[col] = ledger_df[col].fillna(0).astype(float) * -1

        # Fetch and map Sales, Purchase, Receipts, Payments from Vouchers
        sales_map, purchase_map, receipts_map, payments_map = fetch_tally_voucher_breakdown(service, company_name=vat_company)
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
        nvarchar_dtype = {col: NVARCHAR(length=None) for col in ledger_df.select_dtypes(include=['object']).columns}
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

