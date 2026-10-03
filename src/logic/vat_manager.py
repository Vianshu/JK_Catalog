"""
VAT Working Data Layer and Business Logic.

Manages:
- VAT company configuration (multi-profile)
- VAT row ledger data storage (Sundry Debtors & Creditors)
- Internal vs. VAT ledger mapping (exact auto-match + persistent manual mappings)
- VAT Conf persistence (Did You Print, CRM, Get Back, Opening ?, Closing ?)
- Godown cartoon numbering sequence for SN. column
- Need Print ? evaluation (threshold > 100,000 abs on transactions/balances)
"""

import os
from decimal import Decimal, InvalidOperation
from src.logic.db_manager import get_db_manager, build_logical_name
from src.utils.app_logger import get_logger

logger = get_logger(__name__)




def ensure_vat_tables(db, db_name: str):
    """Ensure all required VAT tables exist in the company's SQL Server database."""
    if not db_name or not db.database_exists(db_name):
        return

    # 1. VAT Config table (key/value, e.g. active_vat_company)
    db.ensure_table(db_name, "vat_config", """
        CREATE TABLE vat_config (
            setting_key NVARCHAR(100) PRIMARY KEY,
            setting_value NVARCHAR(MAX),
            updated_at DATETIME DEFAULT GETDATE()
        )
    """)

    # 2. VAT Companies list (multi-profile)
    db.ensure_table(db_name, "vat_companies", """
        CREATE TABLE vat_companies (
            id INT IDENTITY PRIMARY KEY,
            company_name NVARCHAR(255) UNIQUE NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    """)

    # 3. VAT Row Ledger Data (imported from Tally for VAT company - full schema)
    db.ensure_table(db_name, "vat_row_ledger_data", """
        CREATE TABLE vat_row_ledger_data (
            id INT IDENTITY PRIMARY KEY,
            vat_company NVARCHAR(255) NOT NULL,
            GUID NVARCHAR(255) NOT NULL,
            Name NVARCHAR(255) NOT NULL,
            Address NVARCHAR(MAX),
            [Pan_No.] NVARCHAR(255),
            Alias NVARCHAR(255),
            Contact_Person NVARCHAR(255),
            Phone NVARCHAR(255),
            Mobile NVARCHAR(255),
            [Group] NVARCHAR(255),
            Sub_Group NVARCHAR(255),
            Credit_Limit FLOAT DEFAULT 0,
            Opening_Balance FLOAT DEFAULT 0,
            Closing_Balance FLOAT DEFAULT 0,
            Overdue_Bills FLOAT DEFAULT 0,
            On_Account_Value FLOAT DEFAULT 0,
            CashInFlow FLOAT DEFAULT 0,
            CashOutFlow FLOAT DEFAULT 0,
            Sales_Amount FLOAT DEFAULT 0,
            Purchase_Amount FLOAT DEFAULT 0,
            Sales_Plus_Purchase FLOAT DEFAULT 0,
            Receipt_Amount FLOAT DEFAULT 0,
            Payment_Amount FLOAT DEFAULT 0,
            Performance FLOAT DEFAULT 0,
            This_Qtr_Balance FLOAT DEFAULT 0,
            Prev_Qtr_Balance FLOAT DEFAULT 0,
            BillwiseOn FLOAT DEFAULT 0,
            synced_at DATETIME DEFAULT GETDATE(),
            CONSTRAINT UQ_vat_row_ledger UNIQUE (vat_company, GUID)
        )
    """)

    # 4. VAT Ledger Mapping (VAT Ledger -> Internal Ledger -> Manual Name -> Group ID)
    db.ensure_table(db_name, "vat_ledger_mapping", """
        CREATE TABLE vat_ledger_mapping (
            id INT IDENTITY PRIMARY KEY,
            vat_company NVARCHAR(255) NOT NULL,
            vat_ledger_name NVARCHAR(255) NOT NULL DEFAULT '',
            internal_ledger_name NVARCHAR(255) NOT NULL DEFAULT '',
            manual_name NVARCHAR(255) NOT NULL DEFAULT '',
            is_manual BIT NOT NULL DEFAULT 0,
            group_id INT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            updated_at DATETIME DEFAULT GETDATE()
        )
    """)
    try:
        conn = db.get_connection(db_name)
        if conn:
            cur = conn.cursor()
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns 
                    WHERE object_id = OBJECT_ID('dbo.vat_ledger_mapping') 
                      AND name = 'group_id'
                )
                BEGIN
                    ALTER TABLE dbo.vat_ledger_mapping ADD group_id INT NULL;
                END
            """)
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping 
                SET group_id = id 
                WHERE group_id IS NULL;
            """)
            conn.commit()
    except Exception as e:
        logger.debug(f"[ensure_vat_tables] group_id migration note: {e}")

    # 5. VAT Conf User Data (persists user-entered fields across syncs)
    db.ensure_table(db_name, "vat_conf_data", """
        CREATE TABLE vat_conf_data (
            id INT IDENTITY PRIMARY KEY,
            vat_company NVARCHAR(255) NOT NULL,
            group_type NVARCHAR(50) NOT NULL,
            ledger_name NVARCHAR(255) NOT NULL,
            sn NVARCHAR(50) DEFAULT '',
            did_you_print NVARCHAR(10) DEFAULT 'No',
            crm NVARCHAR(255) DEFAULT '',
            get_back NVARCHAR(10) DEFAULT 'No',
            expected_opening NVARCHAR(50) DEFAULT '',
            expected_closing NVARCHAR(50) DEFAULT '',
            updated_at DATETIME DEFAULT GETDATE(),
            CONSTRAINT UQ_vat_conf_data UNIQUE (vat_company, group_type, ledger_name)
        )
    """)

    # 6. VAT Internal Voucher Totals (stores commercial totals for Internal Debtors without cluttering row_ledger_data)
    db.ensure_table(db_name, "vat_int_voucher_totals", """
        CREATE TABLE vat_int_voucher_totals (
            Name NVARCHAR(255) PRIMARY KEY,
            Sales_Amount FLOAT DEFAULT 0,
            Purchase_Amount FLOAT DEFAULT 0,
            Sales_Plus_Purchase FLOAT DEFAULT 0,
            Receipt_Amount FLOAT DEFAULT 0,
            Payment_Amount FLOAT DEFAULT 0,
            updated_at DATETIME DEFAULT GETDATE()
        )
    """)

    # 7. VAT Stock Mapping (VAT Stock Item <-> Internal Stock Item <-> Manual Name)
    db.ensure_table(db_name, "vat_stock_mapping", """
        CREATE TABLE vat_stock_mapping (
            id INT IDENTITY PRIMARY KEY,
            company_name NVARCHAR(255) NOT NULL DEFAULT '',
            vat_stock_item NVARCHAR(255) NOT NULL DEFAULT '',
            internal_stock_item NVARCHAR(255) NOT NULL DEFAULT '',
            manual_name NVARCHAR(255) NOT NULL DEFAULT '',
            is_manual BIT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT GETDATE(),
            updated_at DATETIME DEFAULT GETDATE()
        )
    """)


    # Migration guard: add missing columns if upgrading existing tables
    try:
        conn = db.get_connection(db_name)
        if conn:
            cur = conn.cursor()
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = 'vat_conf_data' AND COLUMN_NAME = 'sn'
                )
                BEGIN
                    ALTER TABLE dbo.vat_conf_data ADD sn NVARCHAR(50) NULL;
                END
            """)

            vat_cols_to_add = [
                ("Address", "NVARCHAR(MAX) NULL"),
                ("Pan_No.", "NVARCHAR(255) NULL"),
                ("Alias", "NVARCHAR(255) NULL"),
                ("Contact_Person", "NVARCHAR(255) NULL"),
                ("Phone", "NVARCHAR(255) NULL"),
                ("Mobile", "NVARCHAR(255) NULL"),
                ("Credit_Limit", "FLOAT DEFAULT 0"),
                ("Overdue_Bills", "FLOAT DEFAULT 0"),
                ("On_Account_Value", "FLOAT DEFAULT 0"),
                ("Performance", "FLOAT DEFAULT 0"),
                ("This_Qtr_Balance", "FLOAT DEFAULT 0"),
                ("Prev_Qtr_Balance", "FLOAT DEFAULT 0"),
                ("BillwiseOn", "FLOAT DEFAULT 0"),
                ("Sales_Amount", "FLOAT DEFAULT 0"),
                ("Purchase_Amount", "FLOAT DEFAULT 0"),
                ("Sales_Plus_Purchase", "FLOAT DEFAULT 0"),
                ("Receipt_Amount", "FLOAT DEFAULT 0"),
                ("Payment_Amount", "FLOAT DEFAULT 0"),
            ]
            for col_name, col_def in vat_cols_to_add:
                cur.execute(f"""
                    IF NOT EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                        WHERE TABLE_NAME = 'vat_row_ledger_data' AND COLUMN_NAME = ?
                    )
                    BEGIN
                        ALTER TABLE dbo.vat_row_ledger_data ADD [{col_name}] {col_def};
                    END
                """, (col_name,))

            # Clean up row_ledger_data to ensure standard Ledger Data UI remains pristine
            for col_to_drop in ["Sales_Amount", "Purchase_Amount", "Sales_Plus_Purchase", "Sales_Count", "Purchase_Count", "Receipt_Amount", "Payment_Amount"]:
                cur.execute(f"""
                    DECLARE @ConstraintName NVARCHAR(200);
                    SELECT @ConstraintName = d.name
                    FROM sys.default_constraints d
                    JOIN sys.columns c ON d.parent_column_id = c.column_id AND d.parent_object_id = c.object_id
                    WHERE d.parent_object_id = OBJECT_ID('dbo.row_ledger_data') AND c.name = '{col_to_drop}';

                    IF @ConstraintName IS NOT NULL
                    BEGIN
                        EXEC('ALTER TABLE dbo.row_ledger_data DROP CONSTRAINT ' + @ConstraintName);
                    END

                    IF EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                        WHERE TABLE_NAME = 'row_ledger_data' AND COLUMN_NAME = '{col_to_drop}'
                    )
                    BEGIN
                        ALTER TABLE dbo.row_ledger_data DROP COLUMN [{col_to_drop}];
                    END
                """)

            # Drop old 1-to-1 unique constraint from vat_ledger_mapping to allow many-to-many
            cur.execute("""
                IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_vat_ledger_mapping')
                    ALTER TABLE dbo.vat_ledger_mapping DROP CONSTRAINT UQ_vat_ledger_mapping;
                IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_vat_ledger_mapping')
                    DROP INDEX UQ_vat_ledger_mapping ON dbo.vat_ledger_mapping;
            """)

            # Ensure manual_name column exists in vat_ledger_mapping
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = 'vat_ledger_mapping' AND COLUMN_NAME = 'manual_name'
                )
                BEGIN
                    ALTER TABLE dbo.vat_ledger_mapping ADD manual_name NVARCHAR(255) NOT NULL DEFAULT '';
                END
            """)

            conn.commit()
    except Exception as me:
        logger.debug(f"[ensure_vat_tables] column migration notice: {me}")


# ─── VAT COMPANY CONFIGURATION ───────────────────────────────────────────────

def get_active_vat_company(db_name: str) -> str:
    """Return the active VAT company name, or empty string if none configured."""
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    rows = db.execute_query(
        db_name,
        "SELECT setting_value FROM vat_config WHERE setting_key = 'active_vat_company'"
    )
    if rows and rows[0][0]:
        return rows[0][0].strip()
    return ""


def set_active_vat_company(db_name: str, vat_company: str):
    """Set the active VAT company name, saving it to vat_config and vat_companies."""
    vat_company = (vat_company or "").strip()
    if not vat_company:
        return
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    cur = conn.cursor()
    try:
        # Add to vat_companies list if not present
        cur.execute("""
            IF NOT EXISTS (SELECT 1 FROM vat_companies WHERE company_name = ?)
                INSERT INTO vat_companies (company_name) VALUES (?)
        """, (vat_company, vat_company))

        # Set as active in vat_config
        cur.execute("""
            IF EXISTS (SELECT 1 FROM vat_config WHERE setting_key = 'active_vat_company')
                UPDATE vat_config SET setting_value = ?, updated_at = GETDATE() WHERE setting_key = 'active_vat_company'
            ELSE
                INSERT INTO vat_config (setting_key, setting_value) VALUES ('active_vat_company', ?)
        """, (vat_company, vat_company))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_active_vat_company] error: {e}")
        raise


def get_all_vat_companies(db_name: str) -> list[str]:
    """Return list of all configured VAT company names."""
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    rows = db.execute_query(db_name, "SELECT company_name FROM vat_companies ORDER BY company_name")
    return [r[0].strip() for r in rows if r[0]] if rows else []


# ─── DATA ACCESS: INTERNAL LEDGERS ──────────────────────────────────────────

def save_internal_voucher_breakdown(db_name: str, party_records: list[dict]):
    """Save voucher breakdown totals for Internal company into dbo.vat_int_voucher_totals."""
    if not db_name or not party_records:
        return
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE TABLE dbo.vat_int_voucher_totals")
        batch_params = [
            (
                r.get("Name", ""),
                r.get("Sales_Amount", 0.0),
                r.get("Purchase_Amount", 0.0),
                r.get("Sales_Plus_Purchase", 0.0),
                r.get("Receipt_Amount", 0.0),
                r.get("Payment_Amount", 0.0),
            )
            for r in party_records
        ]
        if batch_params:
            cur.executemany("""
                INSERT INTO dbo.vat_int_voucher_totals 
                    (Name, Sales_Amount, Purchase_Amount, Sales_Plus_Purchase, Receipt_Amount, Payment_Amount, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE())
            """, batch_params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_internal_voucher_breakdown] error: {e}")


def load_internal_debtors(db_name: str) -> list[dict]:
    """Load Internal Company ledgers where Group = 'Sundry Debtors' joined with voucher totals."""
    db = get_db_manager()
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        # Verify row_ledger_data exists
        cur.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'row_ledger_data'
        """)
        if cur.fetchone()[0] == 0:
            return []

        # Check if vat_int_voucher_totals exists
        cur.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'vat_int_voucher_totals'
        """)
        has_vouchers = (cur.fetchone()[0] > 0)

        if has_vouchers:
            cur.execute("""
                SELECT 
                    r.*,
                    ISNULL(v.Sales_Amount, 0.0) AS Sales_Amount,
                    ISNULL(v.Purchase_Amount, 0.0) AS Purchase_Amount,
                    ISNULL(v.Sales_Plus_Purchase, 0.0) AS Sales_Plus_Purchase,
                    ISNULL(v.Receipt_Amount, 0.0) AS Receipt_Amount,
                    ISNULL(v.Payment_Amount, 0.0) AS Payment_Amount
                FROM dbo.row_ledger_data r
                LEFT JOIN dbo.vat_int_voucher_totals v ON v.Name = r.Name
                WHERE LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry debtors'
                   OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry debtors'
                ORDER BY r.Name
            """)
        else:
            cur.execute("""
                SELECT 
                    r.*,
                    0.0 AS Sales_Amount,
                    0.0 AS Purchase_Amount,
                    0.0 AS Sales_Plus_Purchase,
                    0.0 AS Receipt_Amount,
                    0.0 AS Payment_Amount
                FROM dbo.row_ledger_data r
                WHERE LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry debtors'
                   OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry debtors'
                ORDER BY r.Name
            """)

        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"[load_internal_debtors] error: {e}")
        return []


def get_internal_debtor_names(db_name: str) -> list[str]:
    """Return list of all internal Sundry Debtor ledger names."""
    debtors = load_internal_debtors(db_name)
    return [d["Name"].strip() for d in debtors if d.get("Name")]


# ─── DATA ACCESS: VAT LEDGERS ────────────────────────────────────────────────

def load_vat_debtors(db_name: str, vat_company: str) -> list[dict]:
    """Load VAT company ledgers where Group = 'Sundry Debtors' from dbo.vat_row_ledger_data (all columns)."""
    if not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT *
            FROM dbo.vat_row_ledger_data
            WHERE vat_company = ? AND (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
            )
            ORDER BY Name
        """, (vat_company,))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"[load_vat_debtors] error: {e}")
        return []


def get_vat_debtor_names(db_name: str, vat_company: str) -> list[str]:
    """Return list of all VAT company Sundry Debtor ledger names."""
    debtors = load_vat_debtors(db_name, vat_company)
    return [d["Name"].strip() for d in debtors if d.get("Name")]


# ─── MAPPING LOGIC (LEDGER & STOCK) ──────────────────────────────────────────

def load_vat_mappings(db_name: str, vat_company: str) -> list[dict]:
    """Load all mapping groups for the given VAT company.
    
    Persists indefinitely across company switches and syncs.
    Algorithm:
    1. Clean up invalid rows where vat_ledger_name is empty/null (VAT ledger = Empty is FORBIDDEN).
    2. Ensure every row has a valid group_id.
    3. Load all active VAT Debtors (V) and Internal Debtors (I).
    4. Auto-match: Any VAT debtor not yet in DB is matched with an identical unassigned
       Internal debtor (is_manual=0), or inserted as an unmapped VAT row (internal_ledger_name='').
    5. Group rows by group_id, supporting 1:1, 1:N, and M:N merged groups.
    6. Sort: Unmapped groups (is_unmapped=True, red) at TOP, followed by mapped groups.
    """
    if not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()

        # 1. Clean up invalid rows where vat_ledger_name is empty/null
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
              AND (vat_ledger_name IS NULL OR LTRIM(RTRIM(vat_ledger_name)) = '')
        """, (vat_company,))

        # 2. Ensure group_id is populated for all existing rows
        cur.execute("""
            UPDATE dbo.vat_ledger_mapping
            SET group_id = id
            WHERE vat_company = ? AND group_id IS NULL
        """, (vat_company,))
        conn.commit()

        # 3. Load active VAT debtors and Internal debtors (with full records for Name and Alias)
        vat_debtors = load_vat_debtors(db_name, vat_company)
        internal_debtors = load_internal_debtors(db_name)

        vat_name_map = {}   # v_name.lower() -> v_actual_name
        vat_alias_map = {}  # v_name.lower() -> v_actual_alias
        for v in vat_debtors:
            v_clean = str(v.get("Name") or "").strip()
            v_alias = str(v.get("Alias") or "").strip()
            if v_clean.lower() in ("none", "nan", "null"):
                v_clean = ""
            if v_alias.lower() in ("none", "nan", "null"):
                v_alias = ""
            if v_clean and v_clean.lower() not in vat_name_map:
                vat_name_map[v_clean.lower()] = v_clean
                vat_alias_map[v_clean.lower()] = v_alias

        int_name_map = {}       # i_name.lower() -> i_actual_name
        int_name_to_alias = {}  # i_name.lower() -> i_actual_alias
        int_alias_to_name = {}  # i_alias.lower() -> i_actual_name
        for i in internal_debtors:
            i_clean = str(i.get("Name") or "").strip()
            i_alias = str(i.get("Alias") or "").strip()
            if i_clean.lower() in ("none", "nan", "null"):
                i_clean = ""
            if i_alias.lower() in ("none", "nan", "null"):
                i_alias = ""
            if i_clean and i_clean.lower() not in int_name_map:
                int_name_map[i_clean.lower()] = i_clean
                int_name_to_alias[i_clean.lower()] = i_alias
            if i_alias and i_alias.lower() not in int_alias_to_name:
                int_alias_to_name[i_alias.lower()] = i_clean

        # 4. Load current DB rows
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, ISNULL(manual_name, ''), is_manual, group_id
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
            ORDER BY group_id, id
        """, (vat_company,))
        db_rows = cur.fetchall()

        # Clean up any orphaned rows if VAT company debtors are loaded but row has nonexistent VAT debtor
        if vat_name_map:
            ids_to_clean = []
            for r in db_rows:
                v_name = (r[1] or "").strip()
                if v_name and v_name.lower() not in vat_name_map:
                    ids_to_clean.append(r[0])
            if ids_to_clean:
                cur.executemany("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", [(i,) for i in ids_to_clean])
                conn.commit()
                cur.execute("""
                    SELECT id, vat_ledger_name, internal_ledger_name, ISNULL(manual_name, ''), is_manual, group_id
                    FROM dbo.vat_ledger_mapping
                    WHERE vat_company = ?
                    ORDER BY group_id, id
                """, (vat_company,))
                db_rows = cur.fetchall()

        mapped_vat_keys = set()
        assigned_int_keys = set()

        for r in db_rows:
            v_name = (r[1] or "").strip()
            i_name = (r[2] or "").strip()
            if v_name:
                mapped_vat_keys.add(v_name.lower())
            if i_name:
                assigned_int_keys.add(i_name.lower())

        # Auto-match existing unmapped non-manual rows using only the two allowed rules:
        # Rule 1: vat_name == internal_name
        # Rule 2: vat_alias == internal_alias
        existing_updates = []
        for r in db_rows:
            rec_id, v_name, i_name, m_name, is_man, gid = r
            v_name = (v_name or "").strip()
            i_name = (i_name or "").strip()
            if not i_name and not is_man:
                v_key = v_name.lower()
                v_alias = vat_alias_map.get(v_key, "")
                matched_int = None
                if v_key in int_name_map and v_key not in assigned_int_keys:
                    matched_int = int_name_map[v_key]
                elif v_alias and v_alias.lower() in int_alias_to_name:
                    candidate = int_alias_to_name[v_alias.lower()]
                    if candidate.lower() not in assigned_int_keys:
                        matched_int = candidate
                if matched_int:
                    existing_updates.append((matched_int, rec_id))
                    assigned_int_keys.add(matched_int.lower())

        if existing_updates:
            cur.executemany("UPDATE dbo.vat_ledger_mapping SET internal_ledger_name = ? WHERE id = ?", existing_updates)
            conn.commit()

        # 5. For any VAT debtor not yet in DB, insert auto-match or unmapped
        new_inserts = []
        for v_key, v_actual in vat_name_map.items():
            if v_key in mapped_vat_keys:
                continue
            v_alias = vat_alias_map.get(v_key, "")
            matched_int = None
            # Only two rules:
            # Rule 1: vat_name == internal_name
            if v_key in int_name_map and v_key not in assigned_int_keys:
                matched_int = int_name_map[v_key]
            # Rule 2: vat_alias == internal_alias
            elif v_alias and v_alias.lower() in int_alias_to_name:
                candidate = int_alias_to_name[v_alias.lower()]
                if candidate.lower() not in assigned_int_keys:
                    matched_int = candidate

            if matched_int:
                new_inserts.append((vat_company, v_actual, matched_int, "", 0))
                assigned_int_keys.add(matched_int.lower())
            else:
                new_inserts.append((vat_company, v_actual, "", "", 0))
            mapped_vat_keys.add(v_key)

        if new_inserts:
            cur.executemany("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual)
                VALUES (?, ?, ?, ?, ?)
            """, new_inserts)
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET group_id = id
                WHERE vat_company = ? AND group_id IS NULL
            """, (vat_company,))
            conn.commit()

        # 6. Re-fetch all rows and group by group_id
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, ISNULL(manual_name, ''), is_manual, group_id
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
            ORDER BY group_id, id
        """, (vat_company,))
        all_rows = cur.fetchall()

        groups_dict = {}
        for r in all_rows:
            rec_id, v_name, i_name, m_name, is_man, gid = r
            gid = gid or rec_id
            v_name = (v_name or "").strip()
            i_name = (i_name or "").strip()
            m_name = (m_name or "").strip()

            if gid not in groups_dict:
                groups_dict[gid] = {
                    "group_id": gid,
                    "vat_ledgers": [],
                    "internal_ledgers": [],
                    "manual_names": [],
                    "is_manual": bool(is_man),
                    "db_ids": [],
                }
            g = groups_dict[gid]
            g["db_ids"].append(rec_id)
            if v_name and v_name not in g["vat_ledgers"]:
                g["vat_ledgers"].append(v_name)
            if i_name and i_name not in g["internal_ledgers"]:
                g["internal_ledgers"].append(i_name)
            if m_name and m_name not in g["manual_names"]:
                g["manual_names"].append(m_name)
            if is_man:
                g["is_manual"] = True

        result = []
        for gid, g in groups_dict.items():
            v_list = g["vat_ledgers"]
            i_list = g["internal_ledgers"]
            m_list = g["manual_names"]
            is_unmapped = (len(i_list) == 0)
            is_merged = (len(v_list) > 1)

            v_aliases = [vat_alias_map.get(v.lower(), "") for v in v_list]
            i_aliases = [int_name_to_alias.get(i.lower(), "") for i in i_list]

            result.append({
                "id": min(g["db_ids"]) if g["db_ids"] else gid,
                "group_id": gid,
                "vat_ledgers": v_list,
                "internal_ledgers": i_list,
                "vat_aliases": v_aliases,
                "internal_aliases": i_aliases,
                "vat_ledger": " | ".join(v_list),
                "internal_ledger": " | ".join(i_list),
                "manual_name": " | ".join(m_list),
                "is_manual": g["is_manual"],
                "is_unmapped": is_unmapped,
                "is_merged": is_merged,
                "db_ids": g["db_ids"],
            })

        # Sort: unmapped at TOP (red), followed by mapped rows
        unmapped_groups = [r for r in result if r["is_unmapped"]]
        mapped_groups = [r for r in result if not r["is_unmapped"]]
        unmapped_groups.sort(key=lambda r: r["vat_ledger"].lower())
        mapped_groups.sort(key=lambda r: r["vat_ledger"].lower())

        return unmapped_groups + mapped_groups

    except Exception as e:
        logger.error(f"[load_vat_mappings] error: {e}", exc_info=True)
        return []


def get_unassigned_internal_debtors(db_name: str, vat_company: str) -> list[dict]:
    """Return list of all internal Sundry Debtor dicts (Name, Alias) not yet assigned in vat_ledger_mapping."""
    if not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT LOWER(LTRIM(RTRIM(internal_ledger_name))) 
            FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? 
              AND internal_ledger_name IS NOT NULL 
              AND LTRIM(RTRIM(internal_ledger_name)) <> ''
        """, (vat_company,))
        assigned_keys = {r[0] for r in cur.fetchall()}
        all_int = load_internal_debtors(db_name)
        unassigned = []
        for i in all_int:
            name = (i.get("Name") or "").strip()
            alias = (i.get("Alias") or "").strip()
            if name.lower() in ("none", "nan", "null"):
                name = ""
            if alias.lower() in ("none", "nan", "null"):
                alias = ""
            if name and name.lower() not in assigned_keys:
                unassigned.append({"Name": name, "Alias": alias})
        return sorted(unassigned, key=lambda d: d["Name"].lower())
    except Exception as e:
        logger.error(f"[get_unassigned_internal_debtors] error: {e}", exc_info=True)
        return []


def assign_internal_ledger_to_group(db_name: str, vat_company: str, group_id: int, internal_ledger: str) -> bool:
    """Assign an internal ledger to a mapping group (supports 1:N and M:N)."""
    if not vat_company or not group_id:
        return False
    internal_ledger = (internal_ledger or "").strip()
    if not internal_ledger:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        # Check if group has an unmapped placeholder row
        cur.execute("""
            SELECT id FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ? 
              AND (internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = '')
        """, (vat_company, group_id))
        unmapped_row = cur.fetchone()
        if unmapped_row:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET internal_ledger_name = ?, is_manual = 1, updated_at = GETDATE()
                WHERE id = ?
            """, (internal_ledger, unmapped_row[0]))
            conn.commit()
            return True

        # Check if internal ledger is already in this group
        cur.execute("""
            SELECT 1 FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
        """, (vat_company, group_id, internal_ledger))
        if cur.fetchone():
            return True

        # Find primary VAT ledger name and manual name for this group
        cur.execute("""
            SELECT TOP 1 vat_ledger_name, manual_name FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        v_row = cur.fetchone()
        v_name = v_row[0] if v_row else ""
        m_name = v_row[1] if v_row else ""
        if not v_name:
            return False

        cur.execute("""
            INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (vat_company, v_name, internal_ledger, m_name, group_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[assign_internal_ledger_to_group] error: {e}", exc_info=True)
        return False


def remove_internal_ledger_from_group(db_name: str, vat_company: str, group_id: int, internal_ledger: str) -> bool:
    """Remove an internal ledger from a mapping group.
    
    If it is the only internal ledger in the group, the VAT row remains in the table with internal_ledger_name='',
    moving it to the TOP in RED as unmapped.
    """
    if not vat_company or not group_id:
        return False
    internal_ledger = (internal_ledger or "").strip()
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        rows = cur.fetchall()
        if not rows:
            return False

        matching = [r for r in rows if r[2] and r[2].strip().lower() == internal_ledger.lower()]
        if not matching:
            return False

        for m in matching:
            rec_id, v_name, _ = m
            v_rows_count = sum(1 for r in rows if r[1] and r[1].strip().lower() == v_name.strip().lower())
            if v_rows_count > 1:
                cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (rec_id,))
                rows = [r for r in rows if r[0] != rec_id]
            else:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET internal_ledger_name = '', is_manual = 1, updated_at = GETDATE()
                    WHERE id = ?
                """, (rec_id,))
                rows = [(r[0], r[1], "") if r[0] == rec_id else r for r in rows]

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[remove_internal_ledger_from_group] error: {e}", exc_info=True)
        return False


def update_group_internal_ledger(db_name: str, vat_company: str, group_id: int, old_name: str, new_name: str) -> bool:
    """Update or replace an internal ledger within a mapping group."""
    if not vat_company or not group_id:
        return False
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not new_name:
        if old_name:
            return remove_internal_ledger_from_group(db_name, vat_company, group_id, old_name)
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        # Resolve alias if typed
        try:
            int_debtors = load_internal_debtors(db_name)
            name_map = {str(d.get("Name") or "").strip().lower(): str(d.get("Name") or "").strip() for d in int_debtors if str(d.get("Name") or "").strip()}
            alias_map = {str(d.get("Alias") or "").strip().lower(): str(d.get("Name") or "").strip() for d in int_debtors if str(d.get("Alias") or "").strip() and str(d.get("Alias") or "").strip().lower() not in ("none", "nan", "null")}
            canon = name_map.get(new_name.lower()) or alias_map.get(new_name.lower()) or new_name
            new_name = canon
        except Exception:
            pass

        if old_name:
            cur.execute("""
                SELECT TOP 1 id FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND group_id = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = ?
            """, (vat_company, group_id, old_name.lower()))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET internal_ledger_name = ?, is_manual = 1, updated_at = GETDATE()
                    WHERE id = ?
                """, (new_name, row[0]))
                conn.commit()
                return True
        return assign_internal_ledger_to_group(db_name, vat_company, group_id, new_name)
    except Exception as e:
        conn.rollback()
        logger.error(f"[update_group_internal_ledger] error: {e}", exc_info=True)
        return False


def update_group_vat_ledger(db_name: str, vat_company: str, group_id: int, old_name: str, new_name: str) -> bool:
    """Update or replace a VAT ledger within a mapping group."""
    if not vat_company or not group_id:
        return False
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        vat_debtors = load_vat_debtors(db_name, vat_company)
        name_map = {str(v.get("Name") or "").strip().lower(): str(v.get("Name") or "").strip() for v in vat_debtors if str(v.get("Name") or "").strip()}
        alias_map = {str(v.get("Alias") or "").strip().lower(): str(v.get("Name") or "").strip() for v in vat_debtors if str(v.get("Alias") or "").strip() and str(v.get("Alias") or "").strip().lower() not in ("none", "nan", "null")}
        canon = name_map.get(new_name.lower()) or alias_map.get(new_name.lower()) or new_name
        new_name = canon

        if old_name:
            cur.execute("""
                SELECT TOP 1 id FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND group_id = ? AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = ?
            """, (vat_company, group_id, old_name.lower()))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET vat_ledger_name = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (new_name, row[0]))
                conn.commit()
                return True
        return False
    except Exception as e:
        conn.rollback()
        logger.error(f"[update_group_vat_ledger] error: {e}", exc_info=True)
        return False


def set_group_internal_ledgers(db_name: str, vat_company: str, group_id: int, internal_ledgers: list[str]) -> bool:
    """Explicitly set the internal ledgers assigned to a group.
    
    Used when editing the Internal Ledger cell in the mapping table.
    - If internal_ledgers is empty: unmaps the group (sets internal_ledger_name='').
    - If non-empty: updates existing rows and inserts/removes rows so that the group's
      internal ledgers exactly match internal_ledgers.
    Guarantees every constituent VAT ledger in the group is preserved.
    """
    if not vat_company or not group_id:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        clean_names = []
        seen = set()
        for n in internal_ledgers:
            c = (n or "").strip()
            if " (" in c and c.endswith(")"):
                c = c[:c.rfind(" (")].strip()
            if c and c.lower() not in seen:
                seen.add(c.lower())
                clean_names.append(c)

        if not clean_names:
            return unmap_vat_group(db_name, vat_company, group_id)

        # Resolve any internal alias to canonical internal ledger name
        try:
            int_debtors = load_internal_debtors(db_name)
            alias_to_name = {str(d.get("Alias", "")).strip().lower(): str(d.get("Name", "")).strip() for d in int_debtors if str(d.get("Alias", "")).strip()}
            name_map = {str(d.get("Name", "")).strip().lower(): str(d.get("Name", "")).strip() for d in int_debtors if str(d.get("Name", "")).strip()}
            resolved = []
            for n in clean_names:
                nl = n.lower()
                if nl in name_map:
                    resolved.append(name_map[nl])
                elif nl in alias_to_name:
                    resolved.append(alias_to_name[nl])
                else:
                    resolved.append(n)
            clean_names = resolved
        except Exception as e:
            logger.warning(f"[set_group_internal_ledgers] alias resolution warning: {e}")

        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, manual_name 
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        rows = cur.fetchall()
        if not rows:
            return False

        all_vats = list(dict.fromkeys(r[1].strip() for r in rows if r[1] and r[1].strip()))
        primary_vat = all_vats[0] if all_vats else ""
        manual_name = rows[0][3].strip() if rows[0][3] else ""

        current_map = {}
        empty_rows = []
        for r in rows:
            rec_id, v_n, i_n, m_n = r
            i_clean = (i_n or "").strip()
            if i_clean:
                current_map[i_clean.lower()] = (rec_id, v_n.strip())
            else:
                empty_rows.append((rec_id, v_n.strip()))

        target_set = {n.lower() for n in clean_names}

        # Handle rows whose internal ledger is no longer in target
        for cur_key, (rec_id, v_n) in list(current_map.items()):
            if cur_key not in target_set:
                v_count = sum(1 for _, v in current_map.values() if v.lower() == v_n.lower()) + \
                          sum(1 for _, v in empty_rows if v.lower() == v_n.lower())
                if v_count > 1:
                    cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (rec_id,))
                else:
                    cur.execute("""
                        UPDATE dbo.vat_ledger_mapping
                        SET internal_ledger_name = '', is_manual = 1, updated_at = GETDATE()
                        WHERE id = ?
                    """, (rec_id,))
                    empty_rows.append((rec_id, v_n))
                del current_map[cur_key]

        # For target names not currently in DB:
        for name in clean_names:
            if name.lower() not in current_map:
                if empty_rows:
                    placeholder_id, placeholder_vat = empty_rows.pop(0)
                    cur.execute("""
                        UPDATE dbo.vat_ledger_mapping
                        SET internal_ledger_name = ?, is_manual = 1, updated_at = GETDATE()
                        WHERE id = ?
                    """, (name, placeholder_id))
                    current_map[name.lower()] = (placeholder_id, placeholder_vat)
                else:
                    cur.execute("""
                        INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id)
                        VALUES (?, ?, ?, ?, 1, ?)
                    """, (vat_company, primary_vat, name, manual_name, group_id))

        # Delete redundant empty placeholder rows ONLY IF that VAT ledger already has a mapped row in the group
        for e_id, e_vat in empty_rows:
            has_mapped = any(v.lower() == e_vat.lower() for _, v in current_map.values())
            if has_mapped:
                cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (e_id,))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_group_internal_ledgers] error: {e}", exc_info=True)
        return False


def set_group_vat_ledgers(db_name: str, vat_company: str, group_id: int, vat_ledgers: list[str]) -> int:
    """Set the VAT ledgers assigned to a group by typing/editing Column 0.
    
    Supports merging multiple VAT ledgers (e.g. typing 'VAT 1 | VAT 2')
    and demerging (removing a VAT ledger from the group).
    Returns the effective group_id, or 0 on failure.
    """
    if not vat_company or not group_id:
        return 0
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return 0
    cur = conn.cursor()
    try:
        # Load all valid active VAT debtors to resolve aliases and canonical names
        vat_debtors = load_vat_debtors(db_name, vat_company)
        name_map = {str(v.get("Name") or "").strip().lower(): str(v.get("Name") or "").strip() for v in vat_debtors if str(v.get("Name") or "").strip()}
        alias_to_name = {str(v.get("Alias") or "").strip().lower(): str(v.get("Name") or "").strip() for v in vat_debtors if str(v.get("Alias") or "").strip() and str(v.get("Alias") or "").strip().lower() not in ("none", "nan", "null")}

        clean_vats = []
        seen = set()
        for v in vat_ledgers:
            c = (v or "").strip()
            # Strip off any parenthesized alias if user typed/pasted 'Name (Alias)'
            if " (" in c and c.endswith(")"):
                c = c[:c.rfind(" (")].strip()
            if not c:
                continue
            cl = c.lower()
            canon = name_map.get(cl) or alias_to_name.get(cl) or c
            if canon.lower() not in seen:
                seen.add(canon.lower())
                clean_vats.append(canon)

        if not clean_vats:
            return group_id  # Cannot leave VAT ledger column empty

        # Query all rows currently belonging to this group
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, manual_name, group_id
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        current_rows = cur.fetchall()
        if not current_rows:
            return 0

        current_vats_dict = {}  # v_name.lower() -> list of row dicts
        for r in current_rows:
            vn = (r[1] or "").strip().lower()
            current_vats_dict.setdefault(vn, []).append(r)

        target_set = {v.lower() for v in clean_vats}

        # 1. Demerge: For any VAT ledger in current group that is no longer in target_set
        for cur_v_lower, r_list in current_vats_dict.items():
            if cur_v_lower not in target_set:
                for r in r_list:
                    # Separate out into its own group
                    cur.execute("""
                        UPDATE dbo.vat_ledger_mapping
                        SET group_id = id, updated_at = GETDATE()
                        WHERE id = ?
                    """, (r[0],))

        # 2. Merge: For any VAT ledger in clean_vats that belongs to another group or table
        for v_name in clean_vats:
            vl = v_name.lower()
            if vl not in current_vats_dict:
                # Check if this VAT ledger already exists in another group
                cur.execute("""
                    SELECT id, group_id FROM dbo.vat_ledger_mapping
                    WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = ?
                """, (vat_company, vl))
                other_rows = cur.fetchall()
                if other_rows:
                    other_gids = list({r[1] for r in other_rows if r[1]})
                    for ogid in other_gids:
                        cur.execute("""
                            UPDATE dbo.vat_ledger_mapping
                            SET group_id = ?, updated_at = GETDATE()
                            WHERE vat_company = ? AND group_id = ?
                        """, (group_id, vat_company, ogid))
                else:
                    # New VAT ledger row into this group
                    cur.execute("""
                        INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id)
                        VALUES (?, ?, '', '', 1, ?)
                    """, (vat_company, v_name, group_id))

        # 3. Clean up duplicate empty placeholder rows in the group
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
              AND (internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = '')
              AND vat_ledger_name IN (
                  SELECT vat_ledger_name FROM dbo.vat_ledger_mapping
                  WHERE vat_company = ? AND group_id = ?
                    AND internal_ledger_name IS NOT NULL AND LTRIM(RTRIM(internal_ledger_name)) <> ''
              )
        """, (vat_company, group_id, vat_company, group_id))

        conn.commit()
        return group_id
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_group_vat_ledgers] error: {e}", exc_info=True)
        return 0


def unmap_vat_group(db_name: str, vat_company: str, group_id: int) -> bool:
    """Unmap all internal ledgers from a VAT mapping group.
    
    Each VAT ledger in the group is retained with internal_ledger_name='', is_manual=1,
    appearing at TOP in RED as unmapped, and protected from auto-mapping overwrite.
    """
    if not vat_company or not group_id:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, vat_ledger_name FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        rows = cur.fetchall()
        if not rows:
            return False

        seen_vats = set()
        to_keep = []
        to_delete = []
        for r in rows:
            v_name = r[1].strip()
            if v_name.lower() not in seen_vats:
                seen_vats.add(v_name.lower())
                to_keep.append(r[0])
            else:
                to_delete.append(r[0])

        for rec_id in to_delete:
            cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (rec_id,))
        for rec_id in to_keep:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET internal_ledger_name = '', is_manual = 1, updated_at = GETDATE()
                WHERE id = ?
            """, (rec_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[unmap_vat_group] error: {e}", exc_info=True)
        return False


def merge_mapping_groups(db_name: str, vat_company: str, group_ids: list[int]) -> int:
    """Merge multiple mapping groups into a single unified M:N group."""
    if not vat_company or not group_ids:
        return 0
    clean_gids = sorted(list({int(g) for g in group_ids}))
    if len(clean_gids) <= 1:
        return clean_gids[0] if clean_gids else 0
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return 0
    cur = conn.cursor()
    try:
        target_gid = clean_gids[0]
        placeholders = ",".join("?" for _ in clean_gids)
        cur.execute(f"""
            UPDATE dbo.vat_ledger_mapping
            SET group_id = ?, updated_at = GETDATE()
            WHERE vat_company = ? AND group_id IN ({placeholders})
        """, [target_gid, vat_company] + clean_gids)

        # Cleanup: For any VAT ledger in the merged group that has both a mapped row
        # and an empty placeholder, delete the redundant empty placeholder
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
              AND (internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = '')
              AND vat_ledger_name IN (
                  SELECT vat_ledger_name FROM dbo.vat_ledger_mapping
                  WHERE vat_company = ? AND group_id = ?
                    AND internal_ledger_name IS NOT NULL AND LTRIM(RTRIM(internal_ledger_name)) <> ''
              )
        """, (vat_company, target_gid, vat_company, target_gid))

        conn.commit()
        return target_gid
    except Exception as e:
        conn.rollback()
        logger.error(f"[merge_mapping_groups] error: {e}", exc_info=True)
        return 0


def demerge_mapping_group(db_name: str, vat_company: str, group_id: int) -> bool:
    """Demerge a merged group back into individual groups for each VAT ledger."""
    if not vat_company or not group_id:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT vat_ledger_name FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        vats = [r[0] for r in cur.fetchall()]
        if len(vats) <= 1:
            return False

        for v in vats[1:]:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET group_id = id, updated_at = GETDATE()
                WHERE vat_company = ? AND group_id = ? AND vat_ledger_name = ?
            """, (vat_company, group_id, v))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[demerge_mapping_group] error: {e}", exc_info=True)
        return False


def set_group_manual_name(db_name: str, vat_company: str, group_id: int, manual_name: str) -> bool:
    """Set the manual name alias for a mapping group."""
    if not vat_company or not group_id:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE dbo.vat_ledger_mapping
            SET manual_name = ?, updated_at = GETDATE()
            WHERE vat_company = ? AND group_id = ?
        """, (manual_name.strip(), vat_company, group_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_group_manual_name] error: {e}", exc_info=True)
        return False


def save_manual_mapping(db_name: str, vat_company: str, record_id: int, vat_ledger: str, internal_ledger: str, manual_name: str = "") -> int:
    """Save or update manual mapping for a record or group."""
    if not vat_company:
        return 0
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return 0
    cur = conn.cursor()
    try:
        vat_ledger = (vat_ledger or "").strip()
        internal_ledger = (internal_ledger or "").strip()
        manual_name = (manual_name or "").strip()

        if record_id and record_id > 0:
            cur.execute("SELECT group_id FROM dbo.vat_ledger_mapping WHERE id = ? OR group_id = ?", (record_id, record_id))
            grow = cur.fetchone()
            gid = grow[0] if grow else record_id

            if manual_name:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET manual_name = ?, updated_at = GETDATE()
                    WHERE vat_company = ? AND group_id = ?
                """, (manual_name, vat_company, gid))

            if internal_ledger:
                assign_internal_ledger_to_group(db_name, vat_company, gid, internal_ledger)

            conn.commit()
            return gid
        else:
            if not vat_ledger:
                return 0
            cur.execute("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, 1)
            """, (vat_company, vat_ledger, internal_ledger, manual_name))
            new_id = cur.fetchone()[0]
            cur.execute("UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE id = ?", (new_id,))
            conn.commit()
            return new_id
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_manual_mapping] error: {e}", exc_info=True)
        return 0


def run_auto_mapping_on_sync(db_name: str, vat_company: str):
    """Run auto-mapping after a VAT Ledger sync."""
    if not vat_company:
        return
    load_vat_mappings(db_name, vat_company)


def load_stock_mappings(db_name: str, company_name: str, imported_vat_items: list[str] = None) -> list[dict]:
    """Load stock mappings for the company.
    
    Includes stock items from both VAT Excel import and Internal stock (dbo.stock_items).
    Exact name matches are automatically paired (i = j = v).
    Unmatched items are generated dynamically at the TOP in RED.
    """
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()

        # 1. Clean up any incomplete dummy rows where either stock item name is empty/null
        cur.execute("""
            DELETE FROM dbo.vat_stock_mapping
            WHERE company_name = ?
              AND (
                  vat_stock_item IS NULL OR LTRIM(RTRIM(vat_stock_item)) = ''
                  OR internal_stock_item IS NULL OR LTRIM(RTRIM(internal_stock_item)) = ''
              )
        """, (company_name or "",))
        conn.commit()

        # 2. Load existing valid mappings from DB
        cur.execute("""
            SELECT id, vat_stock_item, internal_stock_item, ISNULL(manual_name, ''), is_manual
            FROM dbo.vat_stock_mapping
            WHERE company_name = ?
            ORDER BY id
        """, (company_name or "",))
        db_rows = cur.fetchall()

        # Query internal stock items from dbo.stock_items
        cur.execute("""
            SELECT DISTINCT Item_Name FROM dbo.stock_items
            WHERE Item_Name IS NOT NULL AND LTRIM(RTRIM(Item_Name)) <> ''
        """)
        internal_items = [r[0].strip() for r in cur.fetchall() if r[0]]

        imported_vat = [v.strip() for v in (imported_vat_items or []) if v and v.strip()]

        # Build normalized lookup maps: lowercase -> actual name
        vat_item_map = {}
        for v in imported_vat:
            v_clean = (v or "").strip()
            if v_clean and v_clean.lower() not in vat_item_map:
                vat_item_map[v_clean.lower()] = v_clean

        int_item_map = {}
        for i in internal_items:
            i_clean = (i or "").strip()
            if i_clean and i_clean.lower() not in int_item_map:
                int_item_map[i_clean.lower()] = i_clean

        saved_mappings = []
        seen_pairs = set()
        mapped_vat = set()
        mapped_int = set()

        ids_to_delete = []
        for r in db_rows:
            rec_id = r[0]
            v_item = (r[1] or "").strip()
            i_item = (r[2] or "").strip()
            m_name = (r[3] or "").strip()
            is_man = bool(r[4])

            if not v_item or not i_item:
                continue

            pair_key = (v_item.lower(), i_item.lower())
            if pair_key in seen_pairs:
                ids_to_delete.append(rec_id)
                continue
            seen_pairs.add(pair_key)

            v_missing = bool(vat_item_map and v_item.lower() not in vat_item_map)
            i_missing = bool(int_item_map and i_item.lower() not in int_item_map)
            if v_missing or i_missing:
                ids_to_delete.append(rec_id)
                continue

            mapped_vat.add(v_item.lower())
            mapped_int.add(i_item.lower())

            saved_mappings.append({
                "id": rec_id,
                "vat_stock_item": v_item,
                "internal_stock_item": i_item,
                "manual_name": m_name,
                "is_manual": is_man,
                "is_unmapped": False
            })

        if ids_to_delete:
            cur.executemany("DELETE FROM dbo.vat_stock_mapping WHERE id = ?", [(i,) for i in ids_to_delete])
            conn.commit()

        # Auto-match common items (i = j = v)
        common_keys = sorted(set(vat_item_map.keys()) & set(int_item_map.keys()))
        new_auto_inserts = []
        for k in common_keys:
            if k in mapped_vat or k in mapped_int:
                continue
            v_actual = vat_item_map[k]
            i_actual = int_item_map[k]
            new_auto_inserts.append((company_name or "", v_actual, i_actual, "", 0))
            mapped_vat.add(k)
            mapped_int.add(k)

        if new_auto_inserts:
            cur.executemany("""
                INSERT INTO dbo.vat_stock_mapping (company_name, vat_stock_item, internal_stock_item, manual_name, is_manual)
                VALUES (?, ?, ?, ?, ?)
            """, new_auto_inserts)
            conn.commit()

            cur.execute("""
                SELECT id, vat_stock_item, internal_stock_item, ISNULL(manual_name, ''), is_manual
                FROM dbo.vat_stock_mapping
                WHERE company_name = ? AND is_manual = 0
            """, (company_name or "",))
            for r in cur.fetchall():
                pair_key = (r[1].strip().lower(), r[2].strip().lower())
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    saved_mappings.append({
                        "id": r[0],
                        "vat_stock_item": r[1].strip(),
                        "internal_stock_item": r[2].strip(),
                        "manual_name": r[3].strip(),
                        "is_manual": False,
                        "is_unmapped": False
                    })

        # Dynamic unmapped items
        unmapped_records = []
        for k in sorted(vat_item_map.keys()):
            if k not in mapped_vat:
                unmapped_records.append({
                    "id": 0,
                    "vat_stock_item": vat_item_map[k],
                    "internal_stock_item": "",
                    "manual_name": "",
                    "is_manual": False,
                    "is_unmapped": True
                })

        for k in sorted(int_item_map.keys()):
            if k not in mapped_int:
                unmapped_records.append({
                    "id": 0,
                    "vat_stock_item": "",
                    "internal_stock_item": int_item_map[k],
                    "manual_name": "",
                    "is_manual": False,
                    "is_unmapped": True
                })

        unmapped_records.sort(key=lambda r: (r["vat_stock_item"] or r["internal_stock_item"]).lower())
        saved_mappings.sort(key=lambda r: (r["vat_stock_item"] or r["internal_stock_item"]).lower())

        records = unmapped_records + saved_mappings
        return records

    except Exception as e:
        logger.error(f"[load_stock_mappings] error: {e}", exc_info=True)
        return []


def save_stock_mapping(db_name: str, company_name: str, record_id: int, vat_item: str, internal_item: str, manual_name: str = "") -> int:
    """Save or update a stock mapping row by record ID."""
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return 0
    cur = conn.cursor()
    try:
        vat_item = (vat_item or "").strip()
        internal_item = (internal_item or "").strip()
        manual_name = (manual_name or "").strip()

        if not vat_item or not internal_item:
            if record_id and record_id > 0:
                cur.execute("DELETE FROM dbo.vat_stock_mapping WHERE id = ?", (record_id,))
                conn.commit()
            return 0

        is_manual = 1

        if record_id and record_id > 0:
            cur.execute("""
                DELETE FROM dbo.vat_stock_mapping
                WHERE company_name = ? AND id != ?
                  AND (
                      (vat_stock_item = ? AND internal_stock_item = ?)
                      OR (vat_stock_item = ? AND is_manual = 0)
                      OR (internal_stock_item = ? AND is_manual = 0)
                  )
            """, (company_name or "", record_id, vat_item, internal_item, vat_item, internal_item))

            cur.execute("""
                UPDATE dbo.vat_stock_mapping
                SET vat_stock_item = ?, internal_stock_item = ?, manual_name = ?, is_manual = ?, updated_at = GETDATE()
                WHERE id = ?
            """, (vat_item, internal_item, manual_name, is_manual, record_id))
            conn.commit()
            return record_id
        else:
            cur.execute("""
                SELECT id FROM dbo.vat_stock_mapping
                WHERE company_name = ? AND vat_stock_item = ? AND internal_stock_item = ?
            """, (company_name or "", vat_item, internal_item))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE dbo.vat_stock_mapping
                    SET manual_name = ?, is_manual = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (manual_name, is_manual, existing[0]))
                conn.commit()
                return int(existing[0])

            cur.execute("""
                DELETE FROM dbo.vat_stock_mapping
                WHERE company_name = ?
                  AND (
                      (vat_stock_item = ? AND is_manual = 0)
                      OR (internal_stock_item = ? AND is_manual = 0)
                  )
            """, (company_name or "", vat_item, internal_item))

            cur.execute("""
                INSERT INTO dbo.vat_stock_mapping (company_name, vat_stock_item, internal_stock_item, manual_name, is_manual)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?)
            """, (company_name or "", vat_item, internal_item, manual_name, is_manual))
            row = cur.fetchone()
            new_id = int(row[0]) if row and row[0] is not None else 0
            conn.commit()
            return new_id
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_stock_mapping] error: {e}", exc_info=True)
        raise


# ─── VAT CONF LOGIC ──────────────────────────────────────────────────────────

def normalize_yes_no(value: str) -> str:
    """Normalize user input to 'Yes' or 'No'.
    Accepts: Y, Yes, 1, T, True -> 'Yes'
    Accepts: N, No, 0, F, False -> 'No'
    """
    v = (value or "").strip().lower()
    if v in ("y", "yes", "1", "t", "true"):
        return "Yes"
    elif v in ("n", "no", "0", "f", "false"):
        return "No"
    return value.strip()


# Cartoon numbers that must never be assigned to any row (culturally/business reserved)
_EXCLUDED_CNS = frozenset()


def validate_cartoon_number(new_sn: str) -> tuple[bool, str]:
    """Validate cartoon number is a valid positive integer and not reserved.
    Returns (is_valid, error_msg).
    """
    s = (new_sn or "").strip()
    if not s:
        return True, ""
    try:
        val = int(s)
        if val <= 0:
            return False, "Cartoon number must be a positive integer greater than 0."
        if val in _EXCLUDED_CNS:
            return False, f"CN {val} is reserved and cannot be assigned."
        return True, ""
    except ValueError:
        return False, "Please enter a valid numeric cartoon number."


def calculate_need_print(opening: float, closing: float, cash_in: float, cash_out: float) -> str:
    """Return 'Yes' if abs(val) > 100,000 for any of [Opening, Closing, CashInFlow, CashOutFlow, Total Transactions].
    
    100,000 -> 'No'
    100,001 -> 'Yes'
    """
    total_tx = abs(cash_in or 0) + abs(cash_out or 0)
    values = [abs(opening or 0), abs(closing or 0), abs(cash_in or 0), abs(cash_out or 0), total_tx]
    if any(v > 100000.0 for v in values):
        return "Yes"
    return "No"


def load_vat_conf_table_data(db_name: str, vat_company: str, group_type: str) -> list[dict]:
    """Load 10-column data for Vat Conf (Debtor or Creditor).
    
    group_type: 'Debtor' (Sundry Debtors) or 'Creditor' (Sundry Creditors)
    """
    if not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []

    if group_type == "Debtor":
        group_filter = """
            (
                LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry debtors'
                OR LOWER(r.[Group]) LIKE '%debtor%'
                OR LOWER(r.Sub_Group) LIKE '%debtor%'
            )
        """
    else:
        group_filter = """
            (
                LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry creditors'
                OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry creditors'
                OR LOWER(r.[Group]) LIKE '%credit%'
                OR LOWER(r.Sub_Group) LIKE '%credit%'
            )
        """

    try:
        cur = conn.cursor()
        # Join imported VAT ledgers with user-entered conf data
        query = f"""
            SELECT 
                r.Name,
                r.Opening_Balance,
                r.Closing_Balance,
                r.CashInFlow,
                r.CashOutFlow,
                ISNULL(c.did_you_print, 'No') AS did_you_print,
                ISNULL(c.crm, '') AS crm,
                ISNULL(c.get_back, 'No') AS get_back,
                ISNULL(c.expected_opening, '') AS expected_opening,
                ISNULL(c.expected_closing, '') AS expected_closing,
                ISNULL(c.sn, '') AS sn,
                ISNULL(r.Alias, '') AS Alias
            FROM dbo.vat_row_ledger_data r
            LEFT JOIN dbo.vat_conf_data c 
                ON c.vat_company = r.vat_company 
                AND c.group_type = ? 
                AND c.ledger_name = r.Name
            WHERE r.vat_company = ? AND {group_filter}
            ORDER BY r.Name
        """
        cur.execute(query, (group_type, vat_company))
        rows = cur.fetchall()

        # Collect any custom assigned SNs to avoid reusing them
        used_custom_sns = set()
        for r in rows:
            saved_sn = r[10].strip() if len(r) > 10 and r[10] else ""
            if saved_sn.isdigit() and int(saved_sn) > 0 and int(saved_sn) not in _EXCLUDED_CNS:
                used_custom_sns.add(int(saved_sn))

        # Generate default sequential serial numbers, skipping user-assigned custom SNs AND reserved CNs
        cns = []
        cur_num = 1
        for _ in range(len(rows)):
            while cur_num in used_custom_sns or cur_num in _EXCLUDED_CNS:
                cur_num += 1
            cns.append(str(cur_num))
            cur_num += 1

        results = []
        for idx, r in enumerate(rows):
            name = r[0].strip() if r[0] else ""
            if name.lower() in ("none", "nan", "null"):
                name = ""
            op_amt = float(r[1] or 0.0)
            cl_amt = float(r[2] or 0.0)
            c_in = float(r[3] or 0.0)
            c_out = float(r[4] or 0.0)
            did_print = r[5].strip() if r[5] else "No"
            crm_val = r[6].strip() if r[6] else ""
            get_back = r[7].strip() if r[7] else "No"
            exp_op = r[8].strip() if r[8] else ""
            exp_cl = r[9].strip() if r[9] else ""
            saved_sn = r[10].strip() if len(r) > 10 and r[10] else ""
            if saved_sn.isdigit() and (int(saved_sn) in _EXCLUDED_CNS or int(saved_sn) <= 0):
                saved_sn = ""
            alias_val = r[11].strip() if len(r) > 11 and r[11] else ""
            if alias_val.lower() in ("none", "nan", "null"):
                alias_val = ""

            # Use saved SN if user edited it; otherwise use generated cartoon number
            final_sn = saved_sn if saved_sn else (cns[idx] if idx < len(cns) else str(idx + 1))

            need_print = calculate_need_print(op_amt, cl_amt, c_in, c_out)

            results.append({
                "sn": final_sn,
                "name": name,
                "alias": alias_val,
                "opening_amount": op_amt,
                "closing_amount": cl_amt,
                "need_print": need_print,
                "did_you_print": did_print,
                "crm": crm_val,
                "get_back": get_back,
                "expected_opening": exp_op,
                "expected_closing": exp_cl,
            })
        return results

    except Exception as e:
        logger.error(f"[load_vat_conf_table_data] error: {e}")
        return []


def save_vat_conf_field(db_name: str, vat_company: str, group_type: str, ledger_name: str,
                        field_name: str, value: str):
    """Save an editable user field in vat_conf_data.
    
    Allowed fields: sn, did_you_print, crm, get_back, expected_opening, expected_closing.
    """
    allowed_fields = {
        "sn": "sn",
        "did_you_print": "did_you_print",
        "crm": "crm",
        "get_back": "get_back",
        "expected_opening": "expected_opening",
        "expected_closing": "expected_closing",
    }
    col = allowed_fields.get(field_name)
    if not col or not vat_company or not ledger_name:
        return

    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return

    cur = conn.cursor()
    try:
        val_str = (value or "").strip()
        cur.execute(f"""
            IF EXISTS (SELECT 1 FROM dbo.vat_conf_data WHERE vat_company = ? AND group_type = ? AND ledger_name = ?)
                UPDATE dbo.vat_conf_data 
                SET [{col}] = ?, updated_at = GETDATE()
                WHERE vat_company = ? AND group_type = ? AND ledger_name = ?
            ELSE
                INSERT INTO dbo.vat_conf_data (vat_company, group_type, ledger_name, [{col}])
                VALUES (?, ?, ?, ?)
        """, (vat_company, group_type, ledger_name, val_str, vat_company, group_type, ledger_name,
              vat_company, group_type, ledger_name, val_str))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_vat_conf_field] error: {e}")
        raise


def check_amount_match(actual_amount: float, expected_text: str) -> bool:
    """Compare entered expected amount text against actual amount.
    
    Returns True if matches (or if expected is empty), False if mismatch.
    Uses exact decimal precision to 2 decimal places.
    """
    if not expected_text or not expected_text.strip():
        return True  # Blank is not considered an error/mismatch
    try:
        clean_text = expected_text.replace(",", "").strip()
        exp_dec = Decimal(clean_text).quantize(Decimal("0.01"))
        act_dec = Decimal(str(actual_amount)).quantize(Decimal("0.01"))
        return exp_dec == act_dec
    except (InvalidOperation, ValueError, TypeError):
        return False
