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

    # 4. VAT Ledger Mapping (VAT Ledger -> Internal Ledger -> Manual Name)
    db.ensure_table(db_name, "vat_ledger_mapping", """
        CREATE TABLE vat_ledger_mapping (
            id INT IDENTITY PRIMARY KEY,
            vat_company NVARCHAR(255) NOT NULL,
            vat_ledger_name NVARCHAR(255) NOT NULL DEFAULT '',
            internal_ledger_name NVARCHAR(255) NOT NULL DEFAULT '',
            manual_name NVARCHAR(255) NOT NULL DEFAULT '',
            is_manual BIT NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT GETDATE(),
            updated_at DATETIME DEFAULT GETDATE()
        )
    """)

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
        for r in party_records:
            cur.execute("""
                INSERT INTO dbo.vat_int_voucher_totals 
                    (Name, Sales_Amount, Purchase_Amount, Sales_Plus_Purchase, Receipt_Amount, Payment_Amount, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE())
            """, (
                r.get("Name", ""),
                r.get("Sales_Amount", 0.0),
                r.get("Purchase_Amount", 0.0),
                r.get("Sales_Plus_Purchase", 0.0),
                r.get("Receipt_Amount", 0.0),
                r.get("Payment_Amount", 0.0)
            ))
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
                WHERE r.[Group] = 'Sundry Debtors'
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
                WHERE r.[Group] = 'Sundry Debtors'
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
            WHERE vat_company = ? AND [Group] = 'Sundry Debtors'
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
    """Load all mapping rows for the given VAT company.
    
    Persists indefinitely across company switches and syncs.
    Includes ledgers from both VAT company and Internal company:
    - Saved mappings from dbo.vat_ledger_mapping (including any manual many-to-many associations).
    - Any unmapped VAT debtors are added.
    - Any unmapped Internal debtors are added.
    Unmatched rows (where vat_ledger or internal_ledger is empty) are sorted at the TOP,
    followed by matched rows.
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
        
        # 1. Load existing saved mappings from DB
        cur.execute("""
            SELECT m.id, m.vat_ledger_name, m.internal_ledger_name, ISNULL(m.manual_name, ''), m.is_manual
            FROM dbo.vat_ledger_mapping m
            WHERE m.vat_company = ?
        """, (vat_company,))
        db_rows = cur.fetchall()

        # 2. Get distinct VAT and Internal debtor lists
        vat_debtor_names = get_vat_debtor_names(db_name, vat_company)
        internal_debtor_names = get_internal_debtor_names(db_name)

        # Build records list from existing DB mappings
        records = []
        covered_vat = set()
        covered_int = set()

        for r in db_rows:
            rec_id = r[0]
            v_name = (r[1] or "").strip()
            i_name = (r[2] or "").strip()
            m_name = (r[3] or "").strip()
            is_man = bool(r[4])

            if v_name:
                covered_vat.add(v_name)
            if i_name:
                covered_int.add(i_name)

            records.append({
                "id": rec_id,
                "vat_ledger": v_name,
                "internal_ledger": i_name,
                "manual_name": m_name,
                "is_manual": is_man,
                "is_unmapped": not (v_name and i_name)
            })

        # 3. For any unmapped VAT debtor: check exact match or add as unmapped row
        unmapped_vat = [v for v in vat_debtor_names if v not in covered_vat]
        unmapped_int = [i for i in internal_debtor_names if i not in covered_int]
        unmapped_int_set = set(unmapped_int)

        new_inserts = []
        for v in unmapped_vat:
            if v in unmapped_int_set:
                # Exact name match found!
                new_inserts.append((vat_company, v, v, "", 0))
                covered_vat.add(v)
                covered_int.add(v)
                unmapped_int_set.remove(v)
            else:
                new_inserts.append((vat_company, v, "", "", 0))
                covered_vat.add(v)

        for i in unmapped_int_set:
            new_inserts.append((vat_company, "", i, "", 0))
            covered_int.add(i)

        if new_inserts:
            for ins in new_inserts:
                cur.execute("""
                    INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?, ?)
                """, ins)
                row = cur.fetchone()
                new_id = int(row[0]) if row and row[0] is not None else 0
                records.append({
                    "id": new_id,
                    "vat_ledger": ins[1],
                    "internal_ledger": ins[2],
                    "manual_name": ins[3],
                    "is_manual": bool(ins[4]),
                    "is_unmapped": not (ins[1] and ins[2])
                })
            conn.commit()

        # Sort: unmapped at TOP (0), mapped below (1); then by name
        def _sort_key(item):
            unmapped_flag = 0 if item["is_unmapped"] else 1
            primary_name = (item["vat_ledger"] or item["internal_ledger"] or "").lower()
            return (unmapped_flag, primary_name)

        records.sort(key=_sort_key)
        return records
    except Exception as e:
        logger.error(f"[load_vat_mappings] error: {e}", exc_info=True)
        return []


def save_manual_mapping(db_name: str, vat_company: str, record_id: int, vat_ledger: str, internal_ledger: str, manual_name: str = "") -> int:
    """Save or update a mapping row by its record ID.
    
    If record_id exists, updates the row.
    If record_id is 0 or None, inserts a new row and returns the new ID.
    """
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
        is_manual = 1 if (vat_ledger and internal_ledger) else 0

        if record_id and record_id > 0:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET vat_ledger_name = ?, internal_ledger_name = ?, manual_name = ?, is_manual = ?, updated_at = GETDATE()
                WHERE id = ?
            """, (vat_ledger, internal_ledger, manual_name, is_manual, record_id))
            conn.commit()
            return record_id
        else:
            cur.execute("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?)
            """, (vat_company, vat_ledger, internal_ledger, manual_name, is_manual))
            row = cur.fetchone()
            new_id = int(row[0]) if row and row[0] is not None else 0
            conn.commit()
            return new_id
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_manual_mapping] error: {e}", exc_info=True)
        raise


def run_auto_mapping_on_sync(db_name: str, vat_company: str):
    """Run auto-mapping after a VAT Ledger sync.
    
    Ensures all VAT debtors and Internal debtors are represented in dbo.vat_ledger_mapping.
    Exact name matches are automatically paired; others remain unmapped (blank) at the top.
    Never overwrites existing mappings or deletes historical data.
    """
    if not vat_company:
        return
    load_vat_mappings(db_name, vat_company)


def load_stock_mappings(db_name: str, company_name: str, imported_vat_items: list[str] = None) -> list[dict]:
    """Load stock mappings for the company.
    
    Includes stock items from both VAT Excel import and Internal stock (dbo.stock_items).
    Unmatched rows (where vat_stock_item or internal_stock_item is empty) are sorted at the TOP.
    """
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, vat_stock_item, internal_stock_item, ISNULL(manual_name, ''), is_manual
            FROM dbo.vat_stock_mapping
            WHERE company_name = ?
        """, (company_name or "",))
        db_rows = cur.fetchall()

        # Query internal stock items from dbo.stock_items
        cur.execute("""
            SELECT DISTINCT Item_Name FROM dbo.stock_items
            WHERE Item_Name IS NOT NULL AND LTRIM(RTRIM(Item_Name)) <> ''
        """)
        internal_items = [r[0].strip() for r in cur.fetchall() if r[0]]

        imported_vat = [v.strip() for v in (imported_vat_items or []) if v and v.strip()]

        records = []
        covered_vat = set()
        covered_int = set()

        for r in db_rows:
            rec_id = r[0]
            v_item = (r[1] or "").strip()
            i_item = (r[2] or "").strip()
            m_name = (r[3] or "").strip()
            is_man = bool(r[4])

            if v_item:
                covered_vat.add(v_item)
            if i_item:
                covered_int.add(i_item)

            records.append({
                "id": rec_id,
                "vat_stock_item": v_item,
                "internal_stock_item": i_item,
                "manual_name": m_name,
                "is_manual": is_man,
                "is_unmapped": not (v_item and i_item)
            })

        unmapped_vat = [v for v in imported_vat if v not in covered_vat]
        unmapped_int = [i for i in internal_items if i not in covered_int]
        unmapped_int_set = set(unmapped_int)

        new_inserts = []
        for v in unmapped_vat:
            if v in unmapped_int_set:
                new_inserts.append((company_name, v, v, "", 0))
                covered_vat.add(v)
                covered_int.add(v)
                unmapped_int_set.remove(v)
            else:
                new_inserts.append((company_name, v, "", "", 0))
                covered_vat.add(v)

        for i in unmapped_int_set:
            new_inserts.append((company_name, "", i, "", 0))
            covered_int.add(i)

        if new_inserts:
            for ins in new_inserts:
                cur.execute("""
                    INSERT INTO dbo.vat_stock_mapping (company_name, vat_stock_item, internal_stock_item, manual_name, is_manual)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?, ?)
                """, ins)
                row = cur.fetchone()
                new_id = int(row[0]) if row and row[0] is not None else 0
                records.append({
                    "id": new_id,
                    "vat_stock_item": ins[1],
                    "internal_stock_item": ins[2],
                    "manual_name": ins[3],
                    "is_manual": bool(ins[4]),
                    "is_unmapped": not (ins[1] and ins[2])
                })
            conn.commit()

        def _sort_key(item):
            unmapped_flag = 0 if item["is_unmapped"] else 1
            primary_name = (item["vat_stock_item"] or item["internal_stock_item"] or "").lower()
            return (unmapped_flag, primary_name)

        records.sort(key=_sort_key)
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
        is_manual = 1 if (vat_item and internal_item) else 0

        if record_id and record_id > 0:
            cur.execute("""
                UPDATE dbo.vat_stock_mapping
                SET vat_stock_item = ?, internal_stock_item = ?, manual_name = ?, is_manual = ?, updated_at = GETDATE()
                WHERE id = ?
            """, (vat_item, internal_item, manual_name, is_manual, record_id))
            conn.commit()
            return record_id
        else:
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


def validate_cartoon_number(new_sn: str) -> tuple[bool, str]:
    """Validate cartoon number is a valid positive integer.
    Returns (is_valid, error_msg).
    """
    s = (new_sn or "").strip()
    if not s:
        return True, ""
    try:
        int(s)
        return True, ""
    except ValueError:
        return False, "Please enter a valid numeric cartoon number."


def calculate_need_print(opening: float, closing: float, cash_in: float, cash_out: float) -> str:
    """Return 'Yes' if abs(val) > 100,000 for any of [Opening, Closing, CashInFlow, CashOutFlow, Total Transactions].
    
    100,000 -> 'No'
    100,001 -> 'Yes'
    """
    total_tx = abs(cash_in) + abs(cash_out)
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

    target_group = "Sundry Debtors" if group_type == "Debtor" else "Sundry Creditors"

    try:
        cur = conn.cursor()
        # Join imported VAT ledgers with user-entered conf data
        query = """
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
                ISNULL(c.sn, '') AS sn
            FROM dbo.vat_row_ledger_data r
            LEFT JOIN dbo.vat_conf_data c 
                ON c.vat_company = r.vat_company 
                AND c.group_type = ? 
                AND c.ledger_name = r.Name
            WHERE r.vat_company = ? AND r.[Group] = ?
            ORDER BY r.Name
        """
        cur.execute(query, (group_type, vat_company, target_group))
        rows = cur.fetchall()

        # Collect any custom assigned SNs to avoid reusing them
        used_custom_sns = set()
        for r in rows:
            saved_sn = r[10].strip() if len(r) > 10 and r[10] else ""
            if saved_sn.isdigit():
                used_custom_sns.add(int(saved_sn))

        # Generate default sequential serial numbers, skipping user-assigned custom SNs
        cns = []
        cur_num = 1
        for _ in range(len(rows)):
            while cur_num in used_custom_sns:
                cur_num += 1
            cns.append(str(cur_num))
            cur_num += 1

        results = []
        for idx, r in enumerate(rows):
            name = r[0].strip() if r[0] else ""
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

            # Use saved SN if user edited it; otherwise use generated cartoon number
            final_sn = saved_sn if saved_sn else (cns[idx] if idx < len(cns) else str(idx + 1))

            need_print = calculate_need_print(op_amt, cl_amt, c_in, c_out)

            results.append({
                "sn": final_sn,
                "name": name,
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
