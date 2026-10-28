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
            Debit_Totals FLOAT DEFAULT 0,
            Credit_Totals FLOAT DEFAULT 0,
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
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns 
                    WHERE object_id = OBJECT_ID('dbo.vat_ledger_mapping') 
                      AND name = 'serial_no'
                )
                BEGIN
                    ALTER TABLE dbo.vat_ledger_mapping ADD serial_no INT NULL;
                END
            """)
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns 
                    WHERE object_id = OBJECT_ID('dbo.vat_ledger_mapping') 
                      AND name = 'classification'
                )
                BEGIN
                    ALTER TABLE dbo.vat_ledger_mapping ADD classification NVARCHAR(50) NOT NULL DEFAULT '';
                END
            """)
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns 
                    WHERE object_id = OBJECT_ID('dbo.vat_ledger_mapping') 
                      AND name = 'narration'
                )
                BEGIN
                    ALTER TABLE dbo.vat_ledger_mapping ADD narration NVARCHAR(MAX) NOT NULL DEFAULT '';
                END
            """)
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping 
                SET group_id = id 
                WHERE group_id IS NULL;
            """)

            # Backfill serial_no for existing rows (strictly append-only, preserving existing positive serial numbers)
            cur.execute("""
                IF EXISTS (
                    SELECT 1 FROM dbo.vat_ledger_mapping 
                    WHERE (serial_no IS NULL OR serial_no < 0)
                      AND vat_ledger_name IS NOT NULL 
                      AND LTRIM(RTRIM(vat_ledger_name)) <> ''
                )
                BEGIN
                    UPDATE dbo.vat_ledger_mapping 
                    SET serial_no = 0 
                    WHERE LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none';

                    WITH Unnumbered AS (
                        SELECT vat_company, vat_ledger_name,
                               ROW_NUMBER() OVER (PARTITION BY vat_company ORDER BY MIN(id)) AS rn
                        FROM dbo.vat_ledger_mapping
                        WHERE vat_ledger_name IS NOT NULL 
                          AND LTRIM(RTRIM(vat_ledger_name)) <> '' 
                          AND LOWER(LTRIM(RTRIM(vat_ledger_name))) <> 'none'
                          AND (serial_no IS NULL OR serial_no <= 0)
                        GROUP BY vat_company, vat_ledger_name
                    ),
                    MaxSN AS (
                        SELECT vat_company, ISNULL(MAX(serial_no), 0) AS max_sn
                        FROM dbo.vat_ledger_mapping
                        WHERE serial_no > 0
                        GROUP BY vat_company
                    )
                    UPDATE m
                    SET m.serial_no = ISNULL(mx.max_sn, 0) + u.rn
                    FROM dbo.vat_ledger_mapping m
                    JOIN Unnumbered u ON m.vat_company = u.vat_company AND m.vat_ledger_name = u.vat_ledger_name
                    LEFT JOIN MaxSN mx ON m.vat_company = mx.vat_company
                    WHERE m.serial_no IS NULL OR m.serial_no <= 0;
                END
            """)
            # Clean up duplicate unmapped rows where the same VAT debtor is already mapped elsewhere
            cur.execute("""
                WITH Dupes AS (
                    SELECT id, vat_company, vat_ledger_name, internal_ledger_name,
                           ROW_NUMBER() OVER (
                               PARTITION BY vat_company, LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', ''))
                               ORDER BY 
                                   CASE WHEN internal_ledger_name IS NOT NULL AND LTRIM(RTRIM(internal_ledger_name)) <> '' THEN 0 ELSE 1 END,
                                   CASE WHEN is_manual = 1 THEN 0 ELSE 1 END,
                                   id ASC
                           ) AS rn
                    FROM dbo.vat_ledger_mapping
                    WHERE vat_ledger_name IS NOT NULL AND LTRIM(RTRIM(vat_ledger_name)) <> ''
                      AND LOWER(LTRIM(RTRIM(vat_ledger_name))) <> 'none'
                )
                DELETE FROM dbo.vat_ledger_mapping
                WHERE id IN (
                    SELECT d.id FROM Dupes d
                    WHERE d.rn > 1 
                      AND (d.internal_ledger_name IS NULL OR LTRIM(RTRIM(d.internal_ledger_name)) = '')
                );
            """)
            # Clean up identical duplicate mapping rows within same group
            cur.execute("""
                WITH ExactDupes AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY vat_company, group_id,
                                            LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')),
                                            LOWER(REPLACE(LTRIM(RTRIM(internal_ledger_name)), ' ', ''))
                               ORDER BY id ASC
                           ) AS rn
                    FROM dbo.vat_ledger_mapping
                )
                DELETE FROM dbo.vat_ledger_mapping
                WHERE id IN (SELECT id FROM ExactDupes WHERE rn > 1);
            """)
            conn.commit()
    except Exception as e:
        logger.debug(f"[ensure_vat_tables] mapping migration note: {e}")

    # 4b. VAT Unassigned Internal Classification (Cash Sales, Old Party)
    db.ensure_table(db_name, "vat_unassigned_classification", """
        CREATE TABLE vat_unassigned_classification (
            vat_company NVARCHAR(255) NOT NULL,
            internal_ledger_name NVARCHAR(255) NOT NULL,
            classification NVARCHAR(50) NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT GETDATE(),
            PRIMARY KEY (vat_company, internal_ledger_name)
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

    # 8. VAT Sub Group CRM Mapping (Debtor Sub Group -> CRM Name)
    db.ensure_table(db_name, "vat_subgroup_crm_mapping", """
        CREATE TABLE vat_subgroup_crm_mapping (
            id INT IDENTITY PRIMARY KEY,
            vat_company NVARCHAR(255) NOT NULL,
            sub_group NVARCHAR(255) NOT NULL,
            crm_name NVARCHAR(255) NOT NULL,
            updated_at DATETIME DEFAULT GETDATE(),
            CONSTRAINT UQ_vat_subgroup_crm UNIQUE (vat_company, sub_group)
        )
    """)

    # Migration guard: add missing columns if upgrading existing tables
    try:
        conn = db.get_connection(db_name)
        if conn:
            cur = conn.cursor()
            cur.execute("""
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_NAME = 'vat_subgroup_crm_mapping'
                )
                BEGIN
                    CREATE TABLE dbo.vat_subgroup_crm_mapping (
                        id INT IDENTITY PRIMARY KEY,
                        vat_company NVARCHAR(255) NOT NULL,
                        sub_group NVARCHAR(255) NOT NULL,
                        crm_name NVARCHAR(255) NOT NULL,
                        updated_at DATETIME DEFAULT GETDATE(),
                        CONSTRAINT UQ_vat_subgroup_crm UNIQUE (vat_company, sub_group)
                    );
                END
            """)

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
                ("CashInFlow", "FLOAT DEFAULT 0"),
                ("CashOutFlow", "FLOAT DEFAULT 0"),
                ("Performance", "FLOAT DEFAULT 0"),
                ("This_Qtr_Balance", "FLOAT DEFAULT 0"),
                ("Prev_Qtr_Balance", "FLOAT DEFAULT 0"),
                ("BillwiseOn", "FLOAT DEFAULT 0"),
                ("Debit_Totals", "FLOAT DEFAULT 0"),
                ("Credit_Totals", "FLOAT DEFAULT 0"),
            ]
            # Safe: col_name and col_def are sourced from hardcoded vat_cols_to_add list above
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

            for col_name in ["Debit_Totals", "Credit_Totals"]:
                cur.execute(f"""
                    IF EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'row_ledger_data'
                    )
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                            WHERE TABLE_NAME = 'row_ledger_data' AND COLUMN_NAME = '{col_name}'
                        )
                        BEGIN
                            ALTER TABLE dbo.row_ledger_data ADD [{col_name}] FLOAT DEFAULT 0;
                        END
                    END
                """)

            # Clean up obsolete commercial columns to keep ledger tables clean
            for col_to_drop in ["Sales_Amount", "Purchase_Amount", "Sales_Plus_Purchase", "Sales_Count", "Purchase_Count", "Receipt_Amount", "Payment_Amount"]:
                for tbl in ["row_ledger_data", "vat_row_ledger_data"]:
                    cur.execute(f"""
                        DECLARE @ConstraintName NVARCHAR(200);
                        SELECT @ConstraintName = d.name
                        FROM sys.default_constraints d
                        JOIN sys.columns c ON d.parent_column_id = c.column_id AND d.parent_object_id = c.object_id
                        WHERE d.parent_object_id = OBJECT_ID('dbo.{tbl}') AND c.name = '{col_to_drop}';

                        IF @ConstraintName IS NOT NULL
                        BEGIN
                            EXEC('ALTER TABLE dbo.{tbl} DROP CONSTRAINT ' + @ConstraintName);
                        END

                        IF EXISTS (
                            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS 
                            WHERE TABLE_NAME = '{tbl}' AND COLUMN_NAME = '{col_to_drop}'
                        )
                        BEGIN
                            ALTER TABLE dbo.{tbl} DROP COLUMN [{col_to_drop}];
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
    """Backwards-compatibility stub (voucher breakdown replaced with native Debit/Credit totals)."""
    pass


def load_internal_debtors(db_name: str) -> list[dict]:
    """Load Internal Company ledgers where Group = 'Sundry Debtors' directly from dbo.row_ledger_data."""
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

        cur.execute("""
            SELECT *
            FROM dbo.row_ledger_data
            WHERE (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY Name
        """)

        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
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
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY Name
        """, (vat_company,))
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[load_vat_debtors] error: {e}")
        return []


def get_vat_debtor_names(db_name: str, vat_company: str) -> list[str]:
    """Return list of all VAT company Sundry Debtor ledger names (excluding reserved None)."""
    debtors = load_vat_debtors(db_name, vat_company)
    return [d["Name"].strip() for d in debtors if d.get("Name") and d["Name"].strip().lower() not in ("none", "nan", "null")]


def _load_debtor_names_and_aliases(cur, table_name: str, vat_company: str = None) -> list[dict]:
    """Fast targeted fetch of only Name and Alias for debtors to avoid heavy SELECT * transfers."""
    if table_name not in ("row_ledger_data", "vat_row_ledger_data"):
        raise ValueError(f"Unauthorized table name: {table_name}")
    if vat_company:
        cur.execute(f"""
            SELECT DISTINCT LTRIM(RTRIM(Name)) AS Name, LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias
            FROM dbo.[{table_name}]
            WHERE vat_company = ? AND (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY Name
        """, (vat_company,))
    else:
        cur.execute(f"""
            SELECT DISTINCT LTRIM(RTRIM(Name)) AS Name, LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias
            FROM dbo.[{table_name}]
            WHERE (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY Name
        """)
    return [{"Name": r[0] or "", "Alias": r[1] or ""} for r in cur.fetchall()]


# ─── MAPPING LOGIC (LEDGER & STOCK) ──────────────────────────────────────────

def cleanup_invalid_mappings(db_name: str, vat_company: str) -> None:
    """Clean up invalid rows and ensure group_id is populated for stored mappings."""
    if not vat_company:
        return
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
              AND (
                  vat_ledger_name IS NULL OR LTRIM(RTRIM(vat_ledger_name)) = ''
                  OR vat_ledger_name IN (
                      SELECT Name FROM dbo.vat_row_ledger_data
                      WHERE vat_company = ?
                        AND (
                            LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) IN ('othere account', 'other account', 'othere accounts', 'other accounts')
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%other%account%'
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%othere%account%'
                        )
                  )
                  OR internal_ledger_name IN (
                      SELECT Name FROM dbo.row_ledger_data
                      WHERE (
                            LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) IN ('othere account', 'other account', 'othere accounts', 'other accounts')
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%other%account%'
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%othere%account%'
                      )
                  )
              )
        """, (vat_company, vat_company))

        cur.execute("""
            UPDATE dbo.vat_ledger_mapping
            SET group_id = id
            WHERE vat_company = ? AND group_id IS NULL
        """, (vat_company,))
        deduplicate_internal_ledgers_across_groups(cur, vat_company)
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[cleanup_invalid_mappings] error: {e}", exc_info=True)


def load_pending_cheques_by_party(db_name: str) -> dict[str, float]:
    """Load total pending cheque amounts per internal debtor from cheques table.
    
    A cheque is pending if clear_date is NULL or empty/whitespace.
    Maps canonical debtor names, aliases, and GUIDs to aggregate pending amounts.
    """
    if not db_name:
        return {}
    db = get_db_manager()
    conn = db.get_connection(db_name)
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        # 1. Build debtor name/alias/guid lookup map
        cur.execute("""
            SELECT LTRIM(RTRIM(Name)) AS Name, 
                   LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias,
                   LTRIM(RTRIM(ISNULL(GUID, ''))) AS GUID
            FROM dbo.row_ledger_data
            WHERE (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
        """)
        guid_to_canon = {}
        alias_to_canon = {}
        for r in cur.fetchall():
            nm = (r[0] or "").strip()
            al = (r[1] or "").strip()
            gd = (r[2] or "").strip().lower()
            if nm:
                canon = " ".join(nm.split()).lower()
                if gd:
                    guid_to_canon[gd] = canon
                if al:
                    alias_to_canon[" ".join(al.split()).lower()] = canon
                alias_to_canon[canon] = canon

        # 2. Check if cheques table exists
        cur.execute("""
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_NAME = 'cheques'
        """)
        if not cur.fetchone():
            return {}

        # 3. Fetch pending cheques (where clear_date is NULL or blank)
        cur.execute("""
            SELECT party, party_guid, amount, clear_date 
            FROM dbo.cheques 
            WHERE clear_date IS NULL OR LTRIM(RTRIM(clear_date)) = ''
        """)
        rows = cur.fetchall()
        pending_map = {}
        for r in rows:
            p_name = (r[0] or "").strip()
            p_guid = (r[1] or "").strip().lower()
            amt_raw = r[2]
            if not amt_raw:
                continue
            try:
                amt = float(str(amt_raw).replace(",", "").strip())
            except (ValueError, TypeError):
                continue
            if amt == 0.0:
                continue

            canon = None
            if p_guid and p_guid in guid_to_canon:
                canon = guid_to_canon[p_guid]
            elif p_name:
                p_norm = " ".join(p_name.split()).lower()
                canon = alias_to_canon.get(p_norm, p_norm)

            if canon:
                pending_map[canon] = pending_map.get(canon, 0.0) + amt

        return pending_map
    except Exception as e:
        logger.warning(f"[load_pending_cheques_by_party] Failed: {e}")
        return {}


def load_vat_mappings(db_name: str, vat_company: str) -> list[dict]:
    """Load all mapping groups for the given VAT company.
    
    Persists indefinitely across company switches and syncs.
    Fast, read-only: does NOT rematch or mutate data on every read.
    Returns groups with constituent VAT ledgers, internal ledgers, serial numbers,
    closing balances (without decimals), classifications, and unmapped status.
    Unmatched (1 x 0) groups appear at the TOP, followed by matched groups,
    and default None VAT (Serial 0) at the end.
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

        # 0. Load pending cheques by debtor from cheques table
        pending_cheques_map = load_pending_cheques_by_party(db_name)

        # 1. Load closing balances and aliases for VAT debtors (fast lookup)
        cur.execute("""
            SELECT LTRIM(RTRIM(Name)) AS Name, 
                   LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias,
                   ISNULL(Closing_Balance, 0) AS Closing_Balance
            FROM dbo.vat_row_ledger_data
            WHERE vat_company = ? AND (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY Name
        """, (vat_company,))
        vat_info = {}
        for r in cur.fetchall():
            nm = (r[0] or "").strip()
            if nm:
                k = " ".join(nm.split()).lower()
                vat_info[k] = {
                    "Name": nm,
                    "Alias": (r[1] or "").strip(),
                    "Closing": float(r[2] or 0.0)
                }

        # 4. Load closing balances, aliases, and GUID for Internal debtors (fast lookup)
        cur.execute("""
            SELECT LTRIM(RTRIM(Name)) AS Name, 
                   LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias,
                   ISNULL(Closing_Balance, 0) AS Closing_Balance,
                   LTRIM(RTRIM(ISNULL(GUID, ''))) AS GUID
            FROM dbo.row_ledger_data
            WHERE (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(Sub_Group, '')) NOT LIKE '%othere%account%'
        """)
        int_info = {}
        for r in cur.fetchall():
            nm = (r[0] or "").strip()
            if nm:
                k = " ".join(nm.split()).lower()
                int_info[k] = {
                    "Name": nm,
                    "Alias": (r[1] or "").strip(),
                    "Closing": float(r[2] or 0.0),
                    "GUID": (r[3] or "").strip().lower() if len(r) > 3 else ""
                }

        # Clean up any duplicate unmapped rows for this company before reading
        try:
            cur.execute("""
                WITH Dupes AS (
                    SELECT id, vat_company, vat_ledger_name, internal_ledger_name,
                           ROW_NUMBER() OVER (
                               PARTITION BY vat_company, LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', ''))
                               ORDER BY 
                                   CASE WHEN internal_ledger_name IS NOT NULL AND LTRIM(RTRIM(internal_ledger_name)) <> '' THEN 0 ELSE 1 END,
                                   CASE WHEN is_manual = 1 THEN 0 ELSE 1 END,
                                   id ASC
                           ) AS rn
                    FROM dbo.vat_ledger_mapping
                    WHERE vat_company = ?
                      AND vat_ledger_name IS NOT NULL AND LTRIM(RTRIM(vat_ledger_name)) <> ''
                      AND LOWER(LTRIM(RTRIM(vat_ledger_name))) <> 'none'
                )
                DELETE FROM dbo.vat_ledger_mapping
                WHERE id IN (
                    SELECT d.id FROM Dupes d
                    WHERE d.rn > 1 
                      AND (d.internal_ledger_name IS NULL OR LTRIM(RTRIM(d.internal_ledger_name)) = '')
                );
            """, (vat_company,))
            conn.commit()
        except Exception:
            pass

        try:
            deduplicate_internal_ledgers_across_groups(cur, vat_company)
            conn.commit()
        except Exception:
            pass

        # 4.5 Ensure any VAT debtors from vat_row_ledger_data are persisted in dbo.vat_ledger_mapping with stable serial numbers
        cur.execute("""
            SELECT DISTINCT LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', ''))
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND vat_ledger_name IS NOT NULL AND LTRIM(RTRIM(vat_ledger_name)) <> ''
        """, (vat_company,))
        existing_vat_keys = {r[0] for r in cur.fetchall() if r[0]}

        cur.execute("SELECT ISNULL(MAX(serial_no), 0) FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND serial_no > 0", (vat_company,))
        max_sn_val = cur.fetchone()[0] or 0

        inserted_any = False
        for vk, v_data in sorted(vat_info.items(), key=lambda x: x[1]["Name"]):
            raw_vname = v_data["Name"]
            if raw_vname.lower() in ("none", "nan", "null"):
                continue
            vk_norm = raw_vname.replace(" ", "").lower()
            if vk_norm not in existing_vat_keys:
                max_sn_val += 1
                cur.execute("""
                    INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, serial_no, classification)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, '', '', 0, ?, '')
                """, (vat_company, raw_vname, max_sn_val))
                new_row_id = cur.fetchone()[0]
                cur.execute("UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE id = ?", (new_row_id,))
                existing_vat_keys.add(vk_norm)
                inserted_any = True

        if inserted_any:
            conn.commit()

        # 5. Fetch all stored mapping rows
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, ISNULL(manual_name, ''), 
                   is_manual, group_id, serial_no, ISNULL(classification, ''), ISNULL(narration, '')
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
              AND vat_ledger_name IS NOT NULL AND LTRIM(RTRIM(vat_ledger_name)) <> ''
            ORDER BY ISNULL(group_id, id), id
        """, (vat_company,))
        rows = cur.fetchall()

        groups_dict = {}
        for r in rows:
            rec_id, v_name, i_name, m_name, is_man, gid, sn, cls, narr = r
            gid = gid or rec_id
            v_name = (v_name or "").strip()
            i_name = (i_name or "").strip()
            m_name = (m_name or "").strip()
            cls = (cls or "").strip()
            narr = (narr or "").strip()
            sn = int(sn) if sn is not None else 0

            if gid not in groups_dict:
                groups_dict[gid] = {
                    "group_id": gid,
                    "serial_no": sn,
                    "vat_items": [],
                    "internal_items": [],
                    "vat_ledgers": [],
                    "internal_ledgers": [],
                    "vat_aliases": [],
                    "internal_aliases": [],
                    "manual_names": [],
                    "classification": cls,
                    "narration": narr,
                    "pending_chq": 0.0,
                    "is_manual": bool(is_man),
                    "db_ids": [],
                }
            g = groups_dict[gid]
            g["db_ids"].append(rec_id)
            if sn and (not g["serial_no"] or g["serial_no"] == 0):
                g["serial_no"] = sn
            if cls and not g["classification"]:
                g["classification"] = cls
            if narr and not g.get("narration"):
                g["narration"] = narr

            # VAT ledger item
            if v_name:
                vk = " ".join(v_name.split()).lower()
                v_meta = vat_info.get(vk, {})
                v_alias = v_meta.get("Alias", "")
                v_closing = v_meta.get("Closing", 0.0)
                if not any(" ".join(vi["name"].split()).lower() == vk for vi in g["vat_items"]):
                    g["vat_items"].append({
                        "id": rec_id,
                        "name": v_name,
                        "alias": v_alias,
                        "closing": v_closing,
                        "serial_no": sn,
                        "classification": cls,
                    })
                    g["vat_ledgers"].append(v_name)
                    g["vat_aliases"].append(v_alias)

            # Internal ledger item
            if i_name:
                ik = " ".join(i_name.split()).lower()
                i_meta = int_info.get(ik, {})
                i_alias = i_meta.get("Alias", "")
                i_closing = i_meta.get("Closing", 0.0)
                i_guid = i_meta.get("GUID", "")

                # Look up pending cheque for this internal ledger
                i_chq = 0.0
                if i_guid and i_guid in pending_cheques_map:
                    i_chq = pending_cheques_map[i_guid]
                elif ik in pending_cheques_map:
                    i_chq = pending_cheques_map[ik]
                elif i_alias:
                    ak = " ".join(i_alias.split()).lower()
                    if ak in pending_cheques_map:
                        i_chq = pending_cheques_map[ak]

                if not any(" ".join(ii["name"].split()).lower() == ik for ii in g["internal_items"]):
                    g["internal_items"].append({
                        "id": rec_id,
                        "name": i_name,
                        "alias": i_alias,
                        "closing": i_closing,
                        "guid": i_guid,
                        "pending_chq": i_chq,
                    })
                    g["internal_ledgers"].append(i_name)
                    g["internal_aliases"].append(i_alias)
                    g["pending_chq"] = sum(float(ii.get("pending_chq", 0.0) or 0.0) for ii in g["internal_items"])

            if m_name and m_name not in g["manual_names"]:
                g["manual_names"].append(m_name)
            if is_man:
                g["is_manual"] = True

        # Deduplication safeguard:
        # 1) If a VAT debtor is already mapped in a group with internal ledgers,
        #    discard any duplicate unmapped singleton groups for that same VAT debtor.
        # 2) Discard duplicate unmapped groups that share the exact same VAT debtors.
        mapped_ledger_keys = set()
        for g in groups_dict.values():
            if g["internal_items"]:
                for v in g["vat_ledgers"]:
                    mapped_ledger_keys.add(" ".join(v.split()).lower())

        deduped_groups = []
        seen_unmapped_keys = set()
        for gid, g in groups_dict.items():
            if not g["internal_items"]:
                all_already_mapped = all(" ".join(v.split()).lower() in mapped_ledger_keys for v in g["vat_ledgers"]) if g["vat_ledgers"] else False
                if all_already_mapped:
                    continue
                if g["vat_ledgers"]:
                    group_key = tuple(sorted(" ".join(v.split()).lower() for v in g["vat_ledgers"]))
                    if group_key in seen_unmapped_keys:
                        continue
                    seen_unmapped_keys.add(group_key)
            deduped_groups.append(g)

        result = []
        for g in deduped_groups:
            gid = g["group_id"]
            v_list = g["vat_ledgers"]
            i_list = g["internal_ledgers"]
            m_list = g["manual_names"]
            is_unmapped = (len(i_list) == 0)
            is_merged = (len(v_list) > 1)
            # A group is strictly None VAT only if it explicitly represents the reserved 'None' VAT ledger
            is_none_vat = any(v["name"].strip().lower() == "none" for v in g["vat_items"]) or (not g["vat_items"] and str(g.get("vat_ledger", "")).strip().lower() == "none")

            result.append({
                "id": min(g["db_ids"]) if g["db_ids"] else gid,
                "group_id": gid,
                "serial_no": g["serial_no"],
                "vat_items": g["vat_items"],
                "internal_items": g["internal_items"],
                "vat_ledgers": v_list,
                "internal_ledgers": i_list,
                "vat_aliases": g["vat_aliases"],
                "internal_aliases": g["internal_aliases"],
                "vat_ledger": " | ".join(v_list),
                "internal_ledger": " | ".join(i_list),
                "manual_name": " | ".join(m_list),
                "is_manual": g["is_manual"],
                "is_unmapped": is_unmapped,
                "is_merged": is_merged,
                "is_none_vat": is_none_vat,
                "classification": g["classification"],
                "narration": g.get("narration", ""),
                "pending_chq": g.get("pending_chq", 0.0),
                "db_ids": g["db_ids"],
            })

        def _is_cash_sales_group(g):
            ints = [str(x).strip().lower() for x in g.get("internal_ledgers", [])]
            cls = str(g.get("classification", "")).strip().lower()
            return "cash sales" in ints or cls == "cash sales"

        def _is_old_party_group(g):
            ints = [str(x).strip().lower() for x in g.get("internal_ledgers", [])]
            cls = str(g.get("classification", "")).strip().lower()
            return "old party" in ints or cls == "old party"

        none_vat_groups = [r for r in result if r["is_none_vat"]]
        rem_groups = [r for r in result if not r["is_none_vat"]]

        cash_sales_groups = [r for r in rem_groups if _is_cash_sales_group(r)]
        old_party_groups = [r for r in rem_groups if not _is_cash_sales_group(r) and _is_old_party_group(r)]

        # 1. Not assigned mappings (no internal ledger assigned, not Cash Sales / Old Party)
        not_assigned_groups = [
            r for r in rem_groups
            if not _is_cash_sales_group(r) and not _is_old_party_group(r)
            and (r["is_unmapped"] or not r.get("internal_items"))
        ]

        # 2. Normal mappings (mapped to real internal debtors)
        normal_groups = [
            r for r in rem_groups
            if not _is_cash_sales_group(r) and not _is_old_party_group(r)
            and not (r["is_unmapped"] or not r.get("internal_items"))
        ]

        not_assigned_groups.sort(key=lambda r: (r["serial_no"] or 999999, r["vat_ledger"].lower()))
        normal_groups.sort(key=lambda r: (r["serial_no"] or 999999, r["vat_ledger"].lower()))
        cash_sales_groups.sort(key=lambda r: (r["serial_no"] or 999999, r["vat_ledger"].lower()))
        old_party_groups.sort(key=lambda r: (r["serial_no"] or 999999, r["vat_ledger"].lower()))
        none_vat_groups.sort(key=lambda r: (r["serial_no"] or 0, r["vat_ledger"].lower()))

        cur.close()
        return not_assigned_groups + normal_groups + cash_sales_groups + old_party_groups + none_vat_groups

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[load_vat_mappings] error: {e}", exc_info=True)
        return []


def get_unassigned_internal_debtors(db_name: str, vat_company: str) -> list[dict]:
    """Return list of all internal Sundry Debtor dicts (Name, Alias, Classification) not yet assigned in vat_ledger_mapping."""
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
            SELECT DISTINCT 
                LTRIM(RTRIM(r.Name)) AS Name, 
                LTRIM(RTRIM(ISNULL(r.Alias, ''))) AS Alias,
                LTRIM(RTRIM(ISNULL(c.classification, ''))) AS Classification
            FROM dbo.row_ledger_data r
            LEFT JOIN dbo.vat_unassigned_classification c 
                ON c.vat_company = ? AND LOWER(LTRIM(RTRIM(c.internal_ledger_name))) = LOWER(LTRIM(RTRIM(r.Name)))
            WHERE (
                LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry debtors'
                OR LOWER(r.[Group]) LIKE '%debtor%'
                OR LOWER(r.Sub_Group) LIKE '%debtor%'
            )
            AND LOWER(LTRIM(RTRIM(ISNULL(r.Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
            AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%other%account%'
            AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%othere%account%'
            AND LOWER(LTRIM(RTRIM(r.Name))) NOT IN (
                SELECT DISTINCT LOWER(LTRIM(RTRIM(internal_ledger_name))) 
                FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? 
                  AND internal_ledger_name IS NOT NULL 
                  AND LTRIM(RTRIM(internal_ledger_name)) <> ''
            )
            ORDER BY LTRIM(RTRIM(r.Name))
        """, (vat_company, vat_company))
        rows = cur.fetchall()
        unassigned = []
        for r in rows:
            name = (r[0] or "").strip()
            alias = (r[1] or "").strip()
            cls = (r[2] or "").strip()
            if name.lower() in ("none", "nan", "null"):
                name = ""
            if alias.lower() in ("none", "nan", "null"):
                alias = ""
            if name:
                unassigned.append({"Name": name, "Alias": alias, "Classification": cls})
        cur.close()
        conn.commit()
        return unassigned
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[get_unassigned_internal_debtors] error: {e}", exc_info=True)
        return []


def _remove_internal_ledger_from_other_groups(cur, vat_company: str, target_group_id: int, internal_ledger: str):
    """Ensure internal_ledger exists ONLY in target_group_id across the company.
    
    If it was present in any other group, safely removes it:
    - If the other group has other rows for that VAT ledger, deletes the row.
    - If this was the only row for that VAT ledger in the other group, sets internal_ledger_name = ''
      so the VAT ledger remains in the table as unmapped.
    Does NOT affect placeholder values ('Cash Sales', 'Old Party').
    """
    if not internal_ledger or internal_ledger.lower() in ("cash sales", "old party"):
        return
    cur.execute("""
        SELECT id, group_id, vat_ledger_name
        FROM dbo.vat_ledger_mapping
        WHERE vat_company = ? AND group_id <> ? 
          AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
    """, (vat_company, target_group_id, internal_ledger))
    other_rows = cur.fetchall()
    for row_id, o_gid, o_vname in other_rows:
        cur.execute("""
            SELECT COUNT(*) FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ? 
              AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = LOWER(?)
              AND id <> ?
        """, (vat_company, o_gid, o_vname, row_id))
        has_other = cur.fetchone()[0] > 0
        if has_other:
            cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (row_id,))
        else:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET internal_ledger_name = '', classification = '', is_manual = 1, updated_at = GETDATE()
                WHERE id = ?
            """, (row_id,))


def deduplicate_internal_ledgers_across_groups(cur, vat_company: str):
    """Enforce global uniqueness: each internal ledger belongs to at most one group.
    
    Excludes 'Cash Sales' and 'Old Party'.
    Keeps the assignment in the latest/highest-ID group and clears/removes from others.
    """
    if not vat_company:
        return
    try:
        cur.execute("""
            SELECT LOWER(LTRIM(RTRIM(internal_ledger_name)))
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? 
              AND internal_ledger_name IS NOT NULL 
              AND LTRIM(RTRIM(internal_ledger_name)) <> ''
              AND LOWER(LTRIM(RTRIM(internal_ledger_name))) NOT IN ('cash sales', 'old party')
            GROUP BY LOWER(LTRIM(RTRIM(internal_ledger_name)))
            HAVING COUNT(DISTINCT group_id) > 1
        """, (vat_company,))
        dupe_names = [r[0] for r in cur.fetchall() if r[0]]
        for dupe in dupe_names:
            cur.execute("""
                SELECT TOP 1 group_id 
                FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = ?
                ORDER BY ISNULL(updated_at, '1900-01-01') DESC, id DESC
            """, (vat_company, dupe))
            res = cur.fetchone()
            if res and res[0]:
                keep_gid = res[0]
                _remove_internal_ledger_from_other_groups(cur, vat_company, keep_gid, dupe)
    except Exception as e:
        logger.warning(f"[deduplicate_internal_ledgers_across_groups] {e}")


def assign_internal_ledger_to_group(db_name: str, vat_company: str, group_id: int, internal_ledger: str, target_vat_name: str = None) -> bool:
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
        # Validate that internal_ledger exists in internal debtors (Name or Alias)
        int_debtors = _load_debtor_names_and_aliases(cur, "row_ledger_data")
        name_map = {}
        alias_map = {}
        for d in int_debtors:
            nm = (d.get("Name") or "").strip()
            al = (d.get("Alias") or "").strip()
            if nm and nm.lower() not in ("none", "nan", "null"):
                name_map[" ".join(nm.split()).lower()] = nm
            if al and al.lower() not in ("none", "nan", "null"):
                alias_map[" ".join(al.split()).lower()] = nm

        clean_val = " ".join(internal_ledger.split()).lower()
        if clean_val in ("cash sales", "old party"):
            canon = "Cash Sales" if clean_val == "cash sales" else "Old Party"
        else:
            canon = name_map.get(clean_val) or alias_map.get(clean_val)
            if not canon and '(' in internal_ledger and ')' in internal_ledger:
                before = " ".join(internal_ledger[:internal_ledger.rfind('(')].strip().split()).lower()
                inside = " ".join(internal_ledger[internal_ledger.rfind('(')+1:internal_ledger.rfind(')')].strip().split()).lower()
                canon = name_map.get(before) or alias_map.get(before) or name_map.get(inside) or alias_map.get(inside)
            if not canon and '[' in internal_ledger and ']' in internal_ledger:
                before = " ".join(internal_ledger[:internal_ledger.rfind('[')].strip().split()).lower()
                inside = " ".join(internal_ledger[internal_ledger.rfind('[')+1:internal_ledger.rfind(']')].strip().split()).lower()
                canon = name_map.get(before) or alias_map.get(before) or name_map.get(inside) or alias_map.get(inside)
            if not canon:
                logger.warning(f"[assign_internal_ledger_to_group] Rejected: '{internal_ledger}' is not in internal debtors list")
                return False
        internal_ledger = canon

        if internal_ledger in ("Cash Sales", "Old Party"):
            # Guard: Reserved 'None' VAT group cannot be mapped to Cash Sales or Old Party
            cur.execute("""
                SELECT 1 FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? AND (group_id = ? OR id = ?)
                  AND (serial_no = 0 OR LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none')
            """, (vat_company, group_id, group_id))
            if cur.fetchone() or (target_vat_name and target_vat_name.strip().lower() == "none"):
                logger.warning(f"[assign_internal_ledger_to_group] 'None' VAT cannot be mapped to '{internal_ledger}'")
                return False

            # Assign Cash Sales or Old Party to the group
            cur.execute("""
                SELECT id, vat_ledger_name, internal_ledger_name 
                FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? AND group_id = ?
            """, (vat_company, group_id))
            g_rows = cur.fetchall()
            if not g_rows:
                return False

            # Choose target row (matching target_vat_name if specified, or first placeholder/unmapped, or first row)
            target_id = None
            if target_vat_name:
                for rid, v_n, _ in g_rows:
                    if v_n and v_n.strip().lower() == target_vat_name.strip().lower():
                        target_id = rid
                        break
            if not target_id:
                for rid, _, iname in g_rows:
                    if not iname or iname.strip().lower() in ("", "cash sales", "old party"):
                        target_id = rid
                        break
            if not target_id:
                target_id = g_rows[0][0]

            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET internal_ledger_name = ?, classification = ?, is_manual = 1, updated_at = GETDATE()
                WHERE id = ?
            """, (internal_ledger, internal_ledger, target_id))

            # For any other rows in this group, clear internal_ledger_name while preserving VAT ledgers!
            other_ids = [r[0] for r in g_rows if r[0] != target_id]
            for oid in other_ids:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET internal_ledger_name = '', classification = '', is_manual = 1, updated_at = GETDATE()
                    WHERE id = ?
                """, (oid,))

            cur.execute("""
                DELETE FROM dbo.vat_unassigned_classification
                WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
            """, (vat_company, internal_ledger))

            logger.info(f"User changed mapping in assign_internal_ledger_to_group: group {group_id} -> '{internal_ledger}'")
            conn.commit()
            return True

        # Check if group has an unmapped placeholder row
        cur.execute("""
            SELECT id FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ? 
              AND (internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = ''
                   OR LOWER(LTRIM(RTRIM(internal_ledger_name))) IN ('cash sales', 'old party'))
        """, (vat_company, group_id))
        placeholder_rows = cur.fetchall()
        if placeholder_rows:
            primary_id = placeholder_rows[0][0]
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET internal_ledger_name = ?, classification = '', is_manual = 1, updated_at = GETDATE()
                WHERE id = ?
            """, (internal_ledger, primary_id))
            if len(placeholder_rows) > 1:
                cur.execute("""
                    SELECT vat_ledger_name FROM dbo.vat_ledger_mapping WHERE id = ?
                """, (primary_id,))
                p_vrow = cur.fetchone()
                p_vname = p_vrow[0].strip().lower() if p_vrow and p_vrow[0] else ""
                for x_row in placeholder_rows[1:]:
                    cur.execute("""
                        SELECT vat_ledger_name FROM dbo.vat_ledger_mapping WHERE id = ?
                    """, (x_row[0],))
                    x_vrow = cur.fetchone()
                    x_vname = x_vrow[0].strip().lower() if x_vrow and x_vrow[0] else ""
                    if x_vname == p_vname:
                        cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (x_row[0],))
            cur.execute("""
                DELETE FROM dbo.vat_unassigned_classification
                WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
            """, (vat_company, internal_ledger))
            _remove_internal_ledger_from_other_groups(cur, vat_company, group_id, internal_ledger)
            logger.info(f"User changed mapping in assign_internal_ledger_to_group: group {group_id} -> '{internal_ledger}'")
            conn.commit()
            return True

        # Check if internal ledger is already in this group
        cur.execute("""
            SELECT 1 FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
        """, (vat_company, group_id, internal_ledger))
        if cur.fetchone():
            return True

        # Find primary VAT ledger name, manual name, and serial_no for this group
        cur.execute("""
            SELECT TOP 1 vat_ledger_name, manual_name, serial_no FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND group_id = ?
        """, (vat_company, group_id))
        v_row = cur.fetchone()
        v_name = v_row[0] if v_row else ""
        m_name = v_row[1] if v_row else ""
        sn = v_row[2] if v_row else None

        if not v_name and target_vat_name:
            v_name = target_vat_name
            cur.execute("SELECT ISNULL(MAX(serial_no), 0) + 1 FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND serial_no > 0", (vat_company,))
            sn = cur.fetchone()[0] or 1

        if not v_name:
            return False

        cur.execute("""
            INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id, serial_no, classification)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, 1, ?, ?, '')
        """, (vat_company, v_name, internal_ledger, m_name, group_id, sn))
        new_row_id = cur.fetchone()[0]

        effective_gid = new_row_id if group_id >= 900000 else group_id
        # If group_id was virtual, resolve it to new_row_id
        if group_id >= 900000:
            cur.execute("UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE id = ?", (new_row_id,))

        cur.execute("""
            DELETE FROM dbo.vat_unassigned_classification
            WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
        """, (vat_company, internal_ledger))
        if internal_ledger.lower() not in ("cash sales", "old party"):
            _remove_internal_ledger_from_other_groups(cur, vat_company, effective_gid, internal_ledger)
        logger.info(f"User changed mapping in assign_internal_ledger_to_group: group {effective_gid} -> '{internal_ledger}'")
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
                    SET internal_ledger_name = '', classification = '', is_manual = 1, updated_at = GETDATE()
                    WHERE id = ?
                """, (rec_id,))
        # If no internal ledgers remain in the group, demerge distinct VAT ledgers
        has_internal = any((r[2] or "").strip() for r in rows)
        if not has_internal and len(rows) > 1:
            for r in rows:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET group_id = ?, manual_name = '', updated_at = GETDATE()
                    WHERE id = ?
                """, (r[0], r[0]))

        logger.info(f"User changed mapping in remove_internal_ledger_from_group")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[remove_internal_ledger_from_group] error: {e}", exc_info=True)
        return False


def update_group_internal_ledger(db_name: str, vat_company: str, group_id: int, old_name: str, new_name: str) -> bool:
    """Update or replace an internal ledger within a mapping group.
    
    Strictly validates that new_name exists in internal debtors list (name or alias).
    Rejects invalid names not in the list.
    """
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
        # Validate that new_name exists in internal debtors (Name or Alias)
        int_debtors = _load_debtor_names_and_aliases(cur, "row_ledger_data")
        name_map = {}
        alias_map = {}
        for d in int_debtors:
            nm = (d.get("Name") or "").strip()
            al = (d.get("Alias") or "").strip()
            if nm and nm.lower() not in ("none", "nan", "null"):
                name_map[" ".join(nm.split()).lower()] = nm
            if al and al.lower() not in ("none", "nan", "null"):
                alias_map[" ".join(al.split()).lower()] = nm

        clean_new = " ".join(new_name.split()).lower()
        if clean_new in ("cash sales", "old party"):
            canon = "Cash Sales" if clean_new == "cash sales" else "Old Party"
        else:
            canon = name_map.get(clean_new) or alias_map.get(clean_new)
            if not canon:
                logger.warning(f"[update_group_internal_ledger] Rejected: '{new_name}' is not in internal debtors list")
                return False
        new_name = canon

        if new_name in ("Cash Sales", "Old Party"):
            cur.execute("""
                SELECT 1 FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? AND (group_id = ? OR id = ?)
                  AND (serial_no = 0 OR LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none')
            """, (vat_company, group_id, group_id))
            if cur.fetchone():
                logger.warning(f"[update_group_internal_ledger] 'None' VAT cannot be mapped to '{new_name}'")
                return False

        if old_name:
            cur.execute("""
                SELECT TOP 1 id FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND group_id = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = ?
            """, (vat_company, group_id, old_name.lower()))
            row = cur.fetchone()
            if row:
                cls_val = new_name if new_name in ("Cash Sales", "Old Party") else ''
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET internal_ledger_name = ?, classification = ?, is_manual = 1, updated_at = GETDATE()
                    WHERE id = ?
                """, (new_name, cls_val, row[0]))
                if new_name.lower() not in ("cash sales", "old party"):
                    _remove_internal_ledger_from_other_groups(cur, vat_company, group_id, new_name)
                logger.info(f"User changed mapping in update_group_internal_ledger: group {group_id} '{old_name}' -> '{new_name}'")
                conn.commit()
                return True
        return assign_internal_ledger_to_group(db_name, vat_company, group_id, new_name)
    except Exception as e:
        conn.rollback()
        logger.error(f"[update_group_internal_ledger] error: {e}", exc_info=True)
        return False


def update_group_vat_ledger(db_name: str, vat_company: str, group_id: int, old_name: str, new_name: str) -> bool:
    """Update or replace a VAT ledger within a mapping group.
    
    Strictly validates that new_name exists in VAT debtors list (name or alias).
    Rejects invalid names not in the list.
    """
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
        vat_debtors = _load_debtor_names_and_aliases(cur, "vat_row_ledger_data", vat_company=vat_company)
        name_map = {}
        alias_map = {}
        for d in vat_debtors:
            nm = (d.get("Name") or "").strip()
            al = (d.get("Alias") or "").strip()
            if nm and nm.lower() not in ("none", "nan", "null"):
                name_map[" ".join(nm.split()).lower()] = nm
            if al and al.lower() not in ("none", "nan", "null"):
                alias_map[" ".join(al.split()).lower()] = nm

        clean_new = " ".join(new_name.split()).lower()
        canon = name_map.get(clean_new) or alias_map.get(clean_new)
        if not canon:
            logger.warning(f"[update_group_vat_ledger] Rejected: '{new_name}' is not in VAT debtors list")
            return False
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
                logger.info(f"User changed mapping in update_group_vat_ledger: group {group_id} '{old_name}' -> '{new_name}'")
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

        # Get existing serial_no for group so newly inserted rows maintain stable serial numbers
        cur.execute("SELECT TOP 1 serial_no FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND group_id = ? AND serial_no IS NOT NULL", (vat_company, group_id))
        sn_res = cur.fetchone()
        group_sn = sn_res[0] if sn_res and sn_res[0] is not None else None

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
                        INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id, serial_no)
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                    """, (vat_company, primary_vat, name, manual_name, group_id, group_sn))
                if name.lower() not in ("cash sales", "old party"):
                    _remove_internal_ledger_from_other_groups(cur, vat_company, group_id, name)

        # Delete redundant empty placeholder rows ONLY IF that VAT ledger already has a mapped row in the group
        for e_id, e_vat in empty_rows:
            has_mapped = any(v.lower() == e_vat.lower() for _, v in current_map.values())
            if has_mapped:
                cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (e_id,))

        logger.info(f"User changed mapping in set_group_internal_ledgers")
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
                r_ids = [r[0] for r in r_list]
                if group_id in r_ids:
                    # The removed ledger owns group_id: target_set ledgers need a new group_id
                    cur.execute("""
                        SELECT id FROM dbo.vat_ledger_mapping
                        WHERE vat_company = ? AND group_id = ?
                          AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) <> ?
                    """, (vat_company, group_id, cur_v_lower.replace(" ", "")))
                    other_rows = cur.fetchall()
                    if other_rows:
                        new_other_gid = min(r[0] for r in other_rows)
                        for o_id in [r[0] for r in other_rows]:
                            cur.execute("""
                                UPDATE dbo.vat_ledger_mapping
                                SET group_id = ?, updated_at = GETDATE()
                                WHERE id = ?
                            """, (new_other_gid, o_id))
                else:
                    new_gid = min(r_ids)
                    for r_id in r_ids:
                        cur.execute("""
                            UPDATE dbo.vat_ledger_mapping
                            SET group_id = ?, updated_at = GETDATE()
                            WHERE id = ?
                        """, (new_gid, r_id))

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
                            SET group_id = ?, is_manual = 1, updated_at = GETDATE()
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

        logger.info(f"User changed mapping in set_group_vat_ledgers")
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
                SET internal_ledger_name = '', classification = '', manual_name = '', is_manual = 1, group_id = ?, updated_at = GETDATE()
                WHERE id = ?
            """, (rec_id, rec_id))
        logger.info(f"User changed mapping in unmap_vat_group (demerged {len(to_keep)} VAT ledger(s))")
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
        # Exclude reserved 'None' group from merging
        placeholders = ",".join("?" for _ in clean_gids)
        cur.execute(f"""
            SELECT DISTINCT group_id FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id IN ({placeholders})
              AND (serial_no = 0 OR LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none')
        """, [vat_company] + clean_gids)
        none_gids = {r[0] for r in cur.fetchall()}
        if none_gids:
            clean_gids = [g for g in clean_gids if g not in none_gids]
            if len(clean_gids) <= 1:
                return clean_gids[0] if clean_gids else 0

        target_gid = clean_gids[0]
        placeholders = ",".join("?" for _ in clean_gids)
        cur.execute(f"""
            UPDATE dbo.vat_ledger_mapping
            SET group_id = ?, is_manual = 1, updated_at = GETDATE()
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

        logger.info(f"User changed mapping in merge_mapping_groups")
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
            SELECT id, vat_ledger_name FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
            ORDER BY id
        """, (vat_company, group_id))
        all_rows = cur.fetchall()
        if not all_rows:
            return False

        # Group rows by normalized vat_ledger_name
        vat_to_rows = {}
        for r_id, v_name in all_rows:
            vk = " ".join((v_name or "").split()).lower()
            vat_to_rows.setdefault(vk, []).append((r_id, v_name))

        if len(vat_to_rows) <= 1:
            return False

        # Each distinct VAT ledger gets its own group_id (the min id among its rows)
        for vk, r_list in vat_to_rows.items():
            min_id = min(r[0] for r in r_list)
            for r_id, _ in r_list:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET group_id = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (min_id, r_id))

        logger.info(f"User changed mapping in demerge_mapping_group for group {group_id} -> separated {len(vat_to_rows)} VAT ledgers")
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
        logger.info(f"User changed mapping in set_group_manual_name")
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

            logger.info(f"User changed mapping in save_manual_mapping")
            conn.commit()
            return gid
        else:
            if not vat_ledger:
                return 0
            cur.execute("""
                SELECT ISNULL(MAX(serial_no), 0) + 1 FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND serial_no > 0
            """, (vat_company,))
            next_sn = cur.fetchone()[0] or 1

            cur.execute("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, serial_no)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, 1, ?)
            """, (vat_company, vat_ledger, internal_ledger, manual_name, next_sn))
            new_id = cur.fetchone()[0]
            cur.execute("UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE id = ?", (new_id,))
            logger.info(f"User changed mapping in save_manual_mapping")
            conn.commit()
            return new_id
    except Exception as e:
        conn.rollback()
        logger.error(f"[save_manual_mapping] error: {e}", exc_info=True)
        return 0


def merge_vat_ledger_into_group(db_name: str, vat_company: str, target_group_id: int, vat_ledger_name: str, target_vat_name: str = None) -> bool:
    """Take vat_ledger_name and place it into target_group_id.
    
    Retains its original serial number and shifts any existing internal mappings with it.
    Guards strictly against merging the reserved 'None' VAT ledger.
    """
    if not vat_company or not target_group_id:
        return False
    vat_ledger_name = (vat_ledger_name or "").strip()
    if vat_ledger_name.startswith("↳ "):
        vat_ledger_name = vat_ledger_name[2:].strip()
    if not vat_ledger_name:
        return False
    if vat_ledger_name.lower() == "none":
        logger.warning("[merge_vat_ledger_into_group] 'None' VAT ledger cannot be merged")
        return False
    if target_vat_name and target_vat_name.strip().lower() == "none":
        logger.warning("[merge_vat_ledger_into_group] Cannot merge into reserved 'None' VAT group")
        return False

    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        # Guard: Target group must not be the reserved 'None' group
        cur.execute("""
            SELECT 1 FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND (group_id = ? OR id = ?)
              AND (serial_no = 0 OR LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none')
        """, (vat_company, target_group_id, target_group_id))
        if cur.fetchone():
            logger.warning(f"[merge_vat_ledger_into_group] Cannot merge into reserved 'None' group {target_group_id}")
            return False

        # Resolve real target group ID in DB (handles virtual group IDs >= 900000)
        cur.execute("""
            SELECT TOP 1 id, group_id FROM dbo.vat_ledger_mapping 
            WHERE vat_company = ? AND (group_id = ? OR id = ?)
        """, (vat_company, target_group_id, target_group_id))
        target_row = cur.fetchone()
        if target_row:
            real_target_gid = target_row[1] or target_row[0]
        else:
            if target_vat_name:
                cur.execute("""
                    SELECT id, group_id FROM dbo.vat_ledger_mapping
                    WHERE vat_company = ? AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) = LOWER(REPLACE(?, ' ', ''))
                """, (vat_company, target_vat_name))
                existing_t = cur.fetchone()
                if existing_t:
                    real_target_gid = existing_t[1] or existing_t[0]
                else:
                    cur.execute("SELECT ISNULL(MAX(serial_no), 0) + 1 FROM dbo.vat_ledger_mapping WHERE vat_company = ? AND serial_no > 0", (vat_company,))
                    t_sn = cur.fetchone()[0] or 1
                    cur.execute("""
                        INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, serial_no, classification)
                        OUTPUT INSERTED.id
                        VALUES (?, ?, '', '', 1, ?, '')
                    """, (vat_company, target_vat_name, t_sn))
                    new_t_id = cur.fetchone()[0]
                    cur.execute("UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE id = ?", (new_t_id,))
                    real_target_gid = new_t_id
            else:
                real_target_gid = target_group_id

        # Resolve canonical VAT debtor name if alias or combo was passed
        cur.execute("""
            SELECT DISTINCT LTRIM(RTRIM(Name)) AS Name, LTRIM(RTRIM(ISNULL(Alias, ''))) AS Alias
            FROM dbo.vat_row_ledger_data
            WHERE vat_company = ? AND (
                LOWER(LTRIM(RTRIM([Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(Sub_Group))) = 'sundry debtors'
                OR LOWER([Group]) LIKE '%debtor%'
                OR LOWER(Sub_Group) LIKE '%debtor%'
            )
        """, (vat_company,))
        for vn, va in cur.fetchall():
            if not vn:
                continue
            vn_clean = " ".join(vn.split()).lower()
            va_clean = " ".join(va.split()).lower() if va else ""
            in_clean = " ".join(vat_ledger_name.split()).lower()
            if in_clean in (vn_clean, va_clean, f"{vn_clean} ({va_clean})", f"{vn_clean} [{va_clean}]"):
                vat_ledger_name = vn
                break
            if '(' in vat_ledger_name and ')' in vat_ledger_name:
                before = " ".join(vat_ledger_name[:vat_ledger_name.rfind('(')].strip().split()).lower()
                inside = " ".join(vat_ledger_name[vat_ledger_name.rfind('(')+1:vat_ledger_name.rfind(')')].strip().split()).lower()
                if before in (vn_clean, va_clean) or inside in (vn_clean, va_clean):
                    vat_ledger_name = vn
                    break

        # Check if vat_ledger_name already exists in dbo.vat_ledger_mapping
        cur.execute("""
            SELECT id, group_id, serial_no FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) = LOWER(REPLACE(?, ' ', ''))
        """, (vat_company, vat_ledger_name))
        existing_rows = cur.fetchall()

        if existing_rows:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET group_id = ?, is_manual = 1, updated_at = GETDATE()
                WHERE vat_company = ? AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) = LOWER(REPLACE(?, ' ', ''))
            """, (real_target_gid, vat_company, vat_ledger_name))
        else:
            cur.execute("""
                SELECT ISNULL(MAX(serial_no), 0) + 1 FROM dbo.vat_ledger_mapping
                WHERE vat_company = ? AND serial_no > 0
            """, (vat_company,))
            next_sn = cur.fetchone()[0] or 1

            cur.execute("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, group_id, serial_no, classification)
                VALUES (?, ?, '', '', 1, ?, ?, '')
            """, (vat_company, vat_ledger_name, real_target_gid, next_sn))

        # Cleanup redundant empty placeholders
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ? AND group_id = ?
              AND (internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = '')
              AND vat_ledger_name IN (
                  SELECT vat_ledger_name FROM dbo.vat_ledger_mapping
                  WHERE vat_company = ? AND group_id = ?
                    AND internal_ledger_name IS NOT NULL AND LTRIM(RTRIM(internal_ledger_name)) <> ''
              )
        """, (vat_company, real_target_gid, vat_company, real_target_gid))

        logger.info(f"User merged VAT ledger '{vat_ledger_name}' into group {target_group_id}")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[merge_vat_ledger_into_group] error: {e}", exc_info=True)
        return False


def remove_vat_ledger_from_group(db_name: str, vat_company: str, group_id: int, vat_ledger_name: str) -> bool:
    """Remove a single VAT ledger from a merged group, returning it to its own group (original serial position).
    
    Any internal mappings with the same VAT ledger name are shifted together with it.
    """
    if not vat_company or not group_id:
        return False
    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return False
    vat_ledger_name = (vat_ledger_name or "").strip()
    if vat_ledger_name.startswith("↳ "):
        vat_ledger_name = vat_ledger_name[2:].strip()
    if not vat_ledger_name:
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
            ORDER BY id
        """, (vat_company, group_id))
        all_rows = cur.fetchall()
        if not all_rows:
            return False

        norm_target = " ".join(vat_ledger_name.split()).lower()
        target_ids = [r[0] for r in all_rows if " ".join((r[1] or "").split()).lower() == norm_target]
        remaining_rows = [r for r in all_rows if " ".join((r[1] or "").split()).lower() != norm_target]

        if not target_ids or not remaining_rows:
            return False

        # If the target ledger owns the current group_id (group_id in target_ids):
        # Target ledger keeps group_id, while remaining ledgers in the group move to their own new group_id
        if group_id in target_ids:
            new_remaining_gid = min(r[0] for r in remaining_rows)
            for r_id, _ in remaining_rows:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET group_id = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (new_remaining_gid, r_id))
            logger.info(f"User removed anchor VAT ledger '{vat_ledger_name}' from group {group_id} -> remaining moved to new group {new_remaining_gid}")
        else:
            # The target ledger does NOT own group_id: move the target ledger to its own min(id)
            new_target_gid = min(target_ids)
            for t_id in target_ids:
                cur.execute("""
                    UPDATE dbo.vat_ledger_mapping
                    SET group_id = ?, updated_at = GETDATE()
                    WHERE id = ?
                """, (new_target_gid, t_id))
            logger.info(f"User removed VAT ledger '{vat_ledger_name}' from group {group_id} -> new group {new_target_gid}")

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[remove_vat_ledger_from_group] error: {e}", exc_info=True)
        return False


def set_mapping_classification(db_name: str, vat_company: str, group_id: int, vat_ledger_name: str, classification: str) -> bool:
    """Classify an unmatched VAT ledger as 'Cash Sales', 'Old Party', or ''."""
    if not vat_company:
        return False
    vat_ledger_name = (vat_ledger_name or "").strip()
    if vat_ledger_name.startswith("↳ "):
        vat_ledger_name = vat_ledger_name[2:].strip()
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cls = classification.strip()
        if cls in ("Cash Sales", "Old Party"):
            if vat_ledger_name.lower() == "none":
                return False
            cur.execute("""
                SELECT 1 FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? AND group_id = ? 
                  AND (serial_no = 0 OR LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none')
            """, (vat_company, group_id))
            if cur.fetchone():
                return False

            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET classification = ?,
                    internal_ledger_name = CASE 
                        WHEN internal_ledger_name IS NULL OR LTRIM(RTRIM(internal_ledger_name)) = '' 
                             OR LOWER(LTRIM(RTRIM(internal_ledger_name))) IN ('cash sales', 'old party') 
                        THEN ? 
                        ELSE internal_ledger_name 
                    END,
                    updated_at = GETDATE()
                WHERE vat_company = ? AND group_id = ? AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) = LOWER(REPLACE(?, ' ', ''))
            """, (cls, cls, vat_company, group_id, vat_ledger_name))
        else:
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET classification = ?,
                    internal_ledger_name = CASE 
                        WHEN LOWER(LTRIM(RTRIM(internal_ledger_name))) IN ('cash sales', 'old party') 
                        THEN '' 
                        ELSE internal_ledger_name 
                    END,
                    updated_at = GETDATE()
                WHERE vat_company = ? AND group_id = ? AND LOWER(REPLACE(LTRIM(RTRIM(vat_ledger_name)), ' ', '')) = LOWER(REPLACE(?, ' ', ''))
            """, (cls, vat_company, group_id, vat_ledger_name))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_mapping_classification] error: {e}", exc_info=True)
        return False


def save_mapping_narration(db_name: str, vat_company: str, group_id: int, narration: str) -> bool:
    """Save user-entered narration text for a VAT mapping group."""
    if not db_name or not vat_company or not group_id:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE dbo.vat_ledger_mapping
            SET narration = ?, updated_at = GETDATE()
            WHERE vat_company = ? AND (group_id = ? OR id = ?)
        """, (narration.strip(), vat_company, group_id, group_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[save_mapping_narration] error: {e}", exc_info=True)
        return False


def set_unassigned_classification(db_name: str, vat_company: str, internal_ledger_name: str, classification: str) -> bool:
    """Classify an unassigned internal ledger as 'Cash Sales', 'Old Party', or ''."""
    if not vat_company or not internal_ledger_name:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cls = classification.strip()
        if not cls:
            cur.execute("""
                DELETE FROM dbo.vat_unassigned_classification
                WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
            """, (vat_company, internal_ledger_name.strip()))
        else:
            cur.execute("""
                IF EXISTS (
                    SELECT 1 FROM dbo.vat_unassigned_classification 
                    WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
                )
                    UPDATE dbo.vat_unassigned_classification 
                    SET classification = ?, updated_at = GETDATE()
                    WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = LOWER(?)
                ELSE
                    INSERT INTO dbo.vat_unassigned_classification (vat_company, internal_ledger_name, classification)
                    VALUES (?, ?, ?)
            """, (vat_company, internal_ledger_name.strip(), cls, vat_company, internal_ledger_name.strip(), vat_company, internal_ledger_name.strip(), cls))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[set_unassigned_classification] error: {e}", exc_info=True)
        return False


def run_auto_mapping_on_sync(db_name: str, vat_company: str):
    """Run auto-mapping after a sync operation.
    
    Strictly matches by Ledger Name (Name-only, no Alias).
    If matched, clears any prior 'Cash Sales' or 'Old Party' classification.
    Inserts newly discovered VAT debtors with a fixed sequential serial_no.
    Does NOT overwrite manual mappings or existing groups.
    """
    if not vat_company:
        return
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return
    try:
        cur = conn.cursor()

        # 1. Clean up invalid rows where vat_ledger_name is empty/null or belongs to excluded 'Other/Othere Account' subgroup
        cur.execute("""
            DELETE FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
              AND (
                  vat_ledger_name IS NULL OR LTRIM(RTRIM(vat_ledger_name)) = ''
                  OR vat_ledger_name IN (
                      SELECT Name FROM dbo.vat_row_ledger_data
                      WHERE vat_company = ?
                        AND (
                            LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) IN ('othere account', 'other account', 'othere accounts', 'other accounts')
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%other%account%'
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%othere%account%'
                        )
                  )
                  OR internal_ledger_name IN (
                      SELECT Name FROM dbo.row_ledger_data
                      WHERE (
                            LOWER(LTRIM(RTRIM(ISNULL(Sub_Group, '')))) IN ('othere account', 'other account', 'othere accounts', 'other accounts')
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%other%account%'
                            OR LOWER(ISNULL(Sub_Group, '')) LIKE '%othere%account%'
                      )
                  )
              )
        """, (vat_company, vat_company))

        # 2. Ensure group_id is populated
        cur.execute("""
            UPDATE dbo.vat_ledger_mapping
            SET group_id = id
            WHERE vat_company = ? AND group_id IS NULL
        """, (vat_company,))

        # 3. Ensure 'None' VAT ledger exists with serial_no = 0
        cur.execute("""
            IF NOT EXISTS (
                SELECT 1 FROM dbo.vat_ledger_mapping 
                WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none'
            )
            BEGIN
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, serial_no, classification)
                VALUES (?, 'None', '', '', 1, 0, '');
                UPDATE dbo.vat_ledger_mapping SET group_id = id WHERE group_id IS NULL AND vat_company = ? AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none';
            END
            ELSE
            BEGIN
                UPDATE dbo.vat_ledger_mapping SET serial_no = 0 WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(vat_ledger_name))) = 'none';
            END
        """, (vat_company, vat_company, vat_company, vat_company))
        conn.commit()

        # 4. Load all VAT debtors (names + aliases) and Internal debtors (names + aliases)
        vat_debtors = _load_debtor_names_and_aliases(cur, "vat_row_ledger_data", vat_company)
        int_debtors = _load_debtor_names_and_aliases(cur, "row_ledger_data")

        vat_dict = {}
        vat_alias_map = {}
        for v in vat_debtors:
            nm = (v.get("Name") or "").strip()
            al = (v.get("Alias") or "").strip()
            if nm and nm.lower() not in ("none", "nan", "null"):
                k = " ".join(nm.split()).lower()
                vat_dict[k] = nm
                if al and al.lower() not in ("none", "nan", "null"):
                    vat_alias_map[k] = " ".join(al.split()).lower()

        int_dict = {}
        for i in int_debtors:
            nm = (i.get("Name") or "").strip()
            al = (i.get("Alias") or "").strip()
            if nm and nm.lower() not in ("none", "nan", "null"):
                k_nm = " ".join(nm.split()).lower()
                int_dict[k_nm] = nm
            if al and al.lower() not in ("none", "nan", "null"):
                k_al = " ".join(al.split()).lower()
                if k_al not in int_dict:
                    int_dict[k_al] = nm

        # 5. Fetch existing DB rows
        cur.execute("""
            SELECT id, vat_ledger_name, internal_ledger_name, group_id, serial_no, classification
            FROM dbo.vat_ledger_mapping
            WHERE vat_company = ?
            ORDER BY id
        """, (vat_company,))
        existing_rows = cur.fetchall()

        existing_vats = {}
        assigned_ints = set()
        max_serial = 0

        for r in existing_rows:
            r_id, v_n, i_n, g_id, sn, cls = r
            v_clean = (v_n or "").strip()
            i_clean = (i_n or "").strip()
            vk = " ".join(v_clean.split()).lower()
            ik = " ".join(i_clean.split()).lower()
            if sn and sn > max_serial:
                max_serial = sn
            if vk and vk != "none":
                existing_vats.setdefault(vk, []).append((r_id, g_id, i_clean, sn, cls))
            if ik and ik not in ("cash sales", "old party"):
                assigned_ints.add(ik)

        # 6. Check existing unmapped VAT rows (1 x 0) or placeholder ('Cash Sales', 'Old Party'):
        # If matching internal ledger exists in int_dict (from active Tally/Excel sync),
        # automatically map to the real internal ledger and remove 'Cash Sales' / 'Old Party'.
        for vk, r_list in list(existing_vats.items()):
            eligible_rows = [
                row_item for row_item in r_list 
                if not row_item[2] or row_item[2].lower() in ("cash sales", "old party")
            ]
            if eligible_rows and len(eligible_rows) == len(r_list):
                r_id, g_id, old_int, sn, cls = eligible_rows[0]
                
                # Check match against int_dict (by VAT name or VAT alias)
                va = vat_alias_map.get(vk, "")
                matched_int = None
                if vk in int_dict and vk not in assigned_ints:
                    matched_int = int_dict[vk]
                elif va and va in int_dict and va not in assigned_ints:
                    matched_int = int_dict[va]

                if matched_int:
                    cur.execute("""
                        UPDATE dbo.vat_ledger_mapping
                        SET internal_ledger_name = ?, classification = '', is_manual = 0, updated_at = GETDATE()
                        WHERE id = ?
                    """, (matched_int, r_id))
                    assigned_ints.add(" ".join(matched_int.split()).lower())
                    if len(eligible_rows) > 1:
                        for extra_r in eligible_rows[1:]:
                            cur.execute("DELETE FROM dbo.vat_ledger_mapping WHERE id = ?", (extra_r[0],))
                    cur.execute("""
                        DELETE FROM dbo.vat_unassigned_classification
                        WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = ?
                    """, (vat_company, " ".join(matched_int.split()).lower()))

        # 7. Add new VAT debtors that don't exist yet in vat_ledger_mapping
        new_vat_rows = []
        for vk, v_name in vat_dict.items():
            if vk not in existing_vats:
                max_serial += 1
                sn = max_serial
                va = vat_alias_map.get(vk, "")
                matched_int = None
                if vk in int_dict and vk not in assigned_ints:
                    matched_int = int_dict[vk]
                elif va and va in int_dict and va not in assigned_ints:
                    matched_int = int_dict[va]

                if matched_int:
                    new_vat_rows.append((vat_company, v_name, matched_int, "", 0, sn, ""))
                    assigned_ints.add(" ".join(matched_int.split()).lower())
                    cur.execute("""
                        DELETE FROM dbo.vat_unassigned_classification
                        WHERE vat_company = ? AND LOWER(LTRIM(RTRIM(internal_ledger_name))) = ?
                    """, (vat_company, " ".join(matched_int.split()).lower()))
                elif vk in int_dict and vk in assigned_ints:
                    matched_int = int_dict[vk]
                    new_vat_rows.append((vat_company, v_name, matched_int, "", 0, sn, ""))
                else:
                    new_vat_rows.append((vat_company, v_name, "", "", 0, sn, ""))

        if new_vat_rows:
            cur.executemany("""
                INSERT INTO dbo.vat_ledger_mapping (vat_company, vat_ledger_name, internal_ledger_name, manual_name, is_manual, serial_no, classification)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, new_vat_rows)
            cur.execute("""
                UPDATE dbo.vat_ledger_mapping
                SET group_id = id
                WHERE vat_company = ? AND group_id IS NULL
            """, (vat_company,))

        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[run_auto_mapping_on_sync] error: {e}", exc_info=True)


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
        conn.commit()
        cur.close()
        return records

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
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


def clear_stock_mappings(db_name: str, company_name: str = None) -> bool:
    """Cleanly clear VAT stock mapping records from dbo.vat_stock_mapping."""
    if not db_name:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if company_name:
            cur.execute("DELETE FROM dbo.vat_stock_mapping WHERE company_name = ?", (company_name,))
        else:
            cur.execute("TRUNCATE TABLE dbo.vat_stock_mapping")
        conn.commit()
        logger.info(f"[clear_stock_mappings] Cleanly cleared vat_stock_mapping for company='{company_name}' in db='{db_name}'")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[clear_stock_mappings] error: {e}", exc_info=True)
        return False


# ─── VAT CONF LOGIC ──────────────────────────────────────────────────────────

def normalize_yes_no(value: str) -> str:
    """Normalize user input to 'Yes', 'No', 'No Need', or 'N/A'."""
    v = (value or "").strip().lower()
    if v in ("y", "yes", "1", "t", "true"):
        return "Yes"
    elif v in ("n", "no", "0", "f", "false"):
        return "No"
    elif v in ("no need", "noneed", "nn"):
        return "No Need"
    elif v in ("n/a", "na"):
        return "N/A"
    return value.strip()


def get_unique_vat_debtor_subgroups(db_name: str, vat_company: str) -> list[str]:
    """Return sorted unique Sub_Group names for Debtor ledgers in vat_row_ledger_data."""
    if not db_name or not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        group_filter = """
            (
                LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry debtors'
                OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry debtors'
                OR LOWER(r.[Group]) LIKE '%debtor%'
                OR LOWER(r.Sub_Group) LIKE '%debtor%'
            )
        """
        query = f"""
            SELECT DISTINCT LTRIM(RTRIM(r.Sub_Group)) AS sub_group
            FROM dbo.vat_row_ledger_data r
            WHERE r.vat_company = ? AND {group_filter}
              AND r.Sub_Group IS NOT NULL
              AND LTRIM(RTRIM(r.Sub_Group)) != ''
              AND LOWER(LTRIM(RTRIM(r.Sub_Group))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
              AND LOWER(r.Sub_Group) NOT LIKE '%other%account%'
              AND LOWER(r.Sub_Group) NOT LIKE '%othere%account%'
            ORDER BY 1
        """
        cur.execute(query, (vat_company,))
        rows = cur.fetchall()
        subgroups = [r[0].strip() for r in rows if r[0] and r[0].strip()]
        cur.close()
        return subgroups
    except Exception as e:
        logger.error(f"[get_unique_vat_debtor_subgroups] error: {e}")
        return []


def get_unique_vat_creditor_subgroups(db_name: str, vat_company: str) -> list[str]:
    """Return sorted unique Sub_Group names for Creditor ledgers in vat_row_ledger_data."""
    if not db_name or not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []
    cur = conn.cursor()
    try:
        group_filter = """
            (
                LOWER(LTRIM(RTRIM(r.[Group]))) = 'sundry creditors'
                OR LOWER(LTRIM(RTRIM(r.Sub_Group))) = 'sundry creditors'
                OR LOWER(r.[Group]) LIKE '%creditor%'
                OR LOWER(r.Sub_Group) LIKE '%creditor%'
            )
        """
        query = f"""
            SELECT DISTINCT LTRIM(RTRIM(ISNULL(NULLIF(LTRIM(RTRIM(r.Sub_Group)), ''), ISNULL(r.[Group], '')))) AS sub_group
            FROM dbo.vat_row_ledger_data r
            WHERE r.vat_company = ? AND {group_filter}
              AND (
                  (r.Sub_Group IS NOT NULL AND LTRIM(RTRIM(r.Sub_Group)) != '')
                  OR (r.[Group] IS NOT NULL AND LTRIM(RTRIM(r.[Group])) != '')
              )
              AND LOWER(LTRIM(RTRIM(ISNULL(r.Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
              AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%other%account%'
              AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY 1
        """
        cur.execute(query, (vat_company,))
        rows = cur.fetchall()
        return [r[0].strip() for r in rows if r[0] and r[0].strip()]
    except Exception as e:
        logger.error(f"[get_unique_vat_creditor_subgroups] error: {e}")
        return []
    finally:
        try:
            cur.close()
        except Exception:
            pass


def load_vat_subgroup_crm_mappings(db_name: str, vat_company: str) -> dict[str, str]:
    """Load dict of {sub_group: crm_name} from dbo.vat_subgroup_crm_mapping."""
    if not db_name or not vat_company:
        return {}
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        query = """
            SELECT LTRIM(RTRIM(sub_group)), LTRIM(RTRIM(crm_name))
            FROM dbo.vat_subgroup_crm_mapping
            WHERE vat_company = ?
        """
        cur.execute(query, (vat_company,))
        rows = cur.fetchall()
        mappings = {}
        for r in rows:
            sg = (r[0] or "").strip()
            crm = (r[1] or "").strip()
            if sg:
                mappings[sg] = crm
        cur.close()
        return mappings
    except Exception as e:
        logger.error(f"[load_vat_subgroup_crm_mappings] error: {e}")
        return {}


def save_vat_subgroup_crm_mappings(db_name: str, vat_company: str, mappings: dict[str, str]) -> bool:
    """Save or update subgroup -> crm mappings in dbo.vat_subgroup_crm_mapping.
    Also cascades the mapped CRM to vat_conf_data for all existing debtor ledgers in each sub group.
    """
    if not db_name or not vat_company:
        return False
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return False
    cur = conn.cursor()
    try:
        for sub_group, crm_name in mappings.items():
            sg = (sub_group or "").strip()
            crm = (crm_name or "").strip()
            if not sg:
                continue
            upsert_query = """
                IF EXISTS (SELECT 1 FROM dbo.vat_subgroup_crm_mapping WHERE vat_company = ? AND sub_group = ?)
                    UPDATE dbo.vat_subgroup_crm_mapping
                    SET crm_name = ?, updated_at = GETDATE()
                    WHERE vat_company = ? AND sub_group = ?
                ELSE
                    INSERT INTO dbo.vat_subgroup_crm_mapping (vat_company, sub_group, crm_name, updated_at)
                    VALUES (?, ?, ?, GETDATE())
            """
            cur.execute(upsert_query, (vat_company, sg, crm, vat_company, sg, vat_company, sg, crm))

            # Cascade updated mapping to vat_conf_data for ledgers in this sub group
            cascade_query = """
                UPDATE c
                SET c.crm = ?, c.updated_at = GETDATE()
                FROM dbo.vat_conf_data c
                INNER JOIN dbo.vat_row_ledger_data r 
                    ON r.vat_company = c.vat_company AND r.Name = c.ledger_name
                WHERE c.vat_company = ? 
                  AND LOWER(LTRIM(RTRIM(c.group_type))) = 'debtor'
                  AND LOWER(LTRIM(RTRIM(r.Sub_Group))) = ?
            """
            cur.execute(cascade_query, (crm, vat_company, sg.lower()))

        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[save_vat_subgroup_crm_mappings] error: {e}")
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass


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


def calculate_need_print(opening: float = 0.0, closing: float = 0.0,
                         cash_in: float = 0.0, cash_out: float = 0.0,
                         debit_totals: float = 0.0, credit_totals: float = 0.0) -> str:
    """Return 'Yes' if abs(val) > 100,000 for any of [Opening, Closing, CashInFlow, CashOutFlow, Debit_Totals, Credit_Totals].
    
    100,000 -> 'No'
    100,001 -> 'Yes'
    """
    values = [
        abs(opening or 0),
        abs(closing or 0),
        abs(cash_in or 0),
        abs(cash_out or 0),
        abs(debit_totals or 0),
        abs(credit_totals or 0)
    ]
    if any(v > 100000.0 for v in values):
        return "Yes"
    return "No"


def load_vat_conf_table_data(db_name: str, vat_company: str, group_type: str = "debtor",
                             company_path: str = None) -> list[dict]:
    """Load row ledger data joined with vat_conf_data for Debtor or Creditor Vat Conf table.
    
    group_type: 'Debtor' (Sundry Debtors) or 'Creditor' (Sundry Creditors)
    """
    if not vat_company:
        return []
    db = get_db_manager()
    ensure_vat_tables(db, db_name)
    conn = db.get_connection(db_name)
    if not conn:
        return []

    group_type_norm = str(group_type or "debtor").strip().lower()
    if group_type_norm == "debtor":
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
                OR LOWER(r.[Group]) LIKE '%creditor%'
                OR LOWER(r.Sub_Group) LIKE '%creditor%'
            )
        """

    try:
        cur = conn.cursor()
        subgroup_crm_map = load_vat_subgroup_crm_mappings(db_name, vat_company) if group_type_norm == "debtor" else {}
        norm_sg_map = {str(k).strip().lower(): str(v).strip() for k, v in subgroup_crm_map.items() if k}

        # Join imported VAT ledgers with user-entered conf data
        query = f"""
            SELECT 
                r.Name,
                r.Opening_Balance,
                r.Closing_Balance,
                r.CashInFlow,
                r.CashOutFlow,
                ISNULL(c.did_you_print, '') AS did_you_print,
                ISNULL(c.crm, '') AS crm,
                ISNULL(c.get_back, '') AS get_back,
                ISNULL(c.expected_opening, '') AS expected_opening,
                ISNULL(c.expected_closing, '') AS expected_closing,
                ISNULL(c.sn, '') AS sn,
                ISNULL(r.Alias, '') AS Alias,
                ISNULL(r.[Pan_No.], '') AS pan_no,
                ISNULL(NULLIF(LTRIM(RTRIM(r.Sub_Group)), ''), ISNULL(r.[Group], '')) AS sub_group,
                ISNULL(r.Debit_Totals, 0.0) AS debit_totals,
                ISNULL(r.Credit_Totals, 0.0) AS credit_totals
            FROM dbo.vat_row_ledger_data r
            LEFT JOIN dbo.vat_conf_data c 
                ON c.vat_company = r.vat_company 
                AND LOWER(LTRIM(RTRIM(c.group_type))) = ? 
                AND c.ledger_name = r.Name
            WHERE r.vat_company = ? AND {group_filter}
              AND LOWER(LTRIM(RTRIM(ISNULL(r.Sub_Group, '')))) NOT IN ('othere account', 'other account', 'othere accounts', 'other accounts')
              AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%other%account%'
              AND LOWER(ISNULL(r.Sub_Group, '')) NOT LIKE '%othere%account%'
            ORDER BY r.Name
        """
        cur.execute(query, (group_type_norm, vat_company))
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
            op_raw = r[1]
            cl_raw = r[2]
            op_amt = None if (op_raw is None or (isinstance(op_raw, float) and op_raw != op_raw)) else (0.0 if abs(float(op_raw)) < 1e-9 else float(op_raw))
            cl_amt = None if (cl_raw is None or (isinstance(cl_raw, float) and cl_raw != cl_raw)) else (0.0 if abs(float(cl_raw)) < 1e-9 else float(cl_raw))
            c_in = 0.0 if (r[3] is None or (isinstance(r[3], float) and r[3] != r[3])) else (0.0 if abs(float(r[3])) < 1e-9 else float(r[3]))
            c_out = 0.0 if (r[4] is None or (isinstance(r[4], float) and r[4] != r[4])) else (0.0 if abs(float(r[4])) < 1e-9 else float(r[4]))
            deb_tot = 0.0 if (len(r) <= 14 or r[14] is None or (isinstance(r[14], float) and r[14] != r[14])) else (0.0 if abs(float(r[14])) < 1e-9 else float(r[14]))
            cred_tot = 0.0 if (len(r) <= 15 or r[15] is None or (isinstance(r[15], float) and r[15] != r[15])) else (0.0 if abs(float(r[15])) < 1e-9 else float(r[15]))

            exp_op = r[8].strip() if r[8] else ""
            exp_cl = r[9].strip() if r[9] else ""
            saved_sn = r[10].strip() if len(r) > 10 and r[10] else ""
            if saved_sn.isdigit() and (int(saved_sn) in _EXCLUDED_CNS or int(saved_sn) <= 0):
                saved_sn = ""
            alias_val = r[11].strip() if len(r) > 11 and r[11] else ""
            if alias_val.lower() in ("none", "nan", "null"):
                alias_val = ""

            pan_no = r[12].strip() if len(r) > 12 and r[12] else ""
            if pan_no.lower() in ("none", "nan", "null"):
                pan_no = ""

            sub_group = r[13].strip() if len(r) > 13 and r[13] else ""
            if sub_group.lower() in ("none", "nan", "null"):
                sub_group = ""

            # Use saved SN if user edited it; otherwise use generated cartoon number
            final_sn = saved_sn if saved_sn else (cns[idx] if idx < len(cns) else str(idx + 1))

            need_print = calculate_need_print(
                opening=op_amt or 0.0,
                closing=cl_amt or 0.0,
                cash_in=c_in,
                cash_out=c_out,
                debit_totals=deb_tot,
                credit_totals=cred_tot
            )

            # Dynamic Did You Print: saved edit > ("No Need" if need_print == "No" else "")
            saved_did_print = r[5].strip() if r[5] else ""
            if saved_did_print:
                did_print = saved_did_print
            else:
                did_print = "No Need" if need_print == "No" else ""

            # Dynamic Get Back: saved edit > ("N/A" if did_print == "No Need" else "")
            saved_get_back = r[7].strip() if r[7] else ""
            if saved_get_back:
                get_back = saved_get_back
            else:
                get_back = "N/A" if did_print == "No Need" else ""

            # Dynamic CRM: manual user edit in vat_conf_data > Sub Group mapped CRM > ""
            saved_crm = r[6].strip() if r[6] else ""
            clean_sg = sub_group.strip().lower()
            mapped_crm = norm_sg_map.get(clean_sg, "")
            if saved_crm:
                crm_val = saved_crm
            else:
                crm_val = mapped_crm

            results.append({
                "sn": final_sn,
                "name": name,
                "pan_no": pan_no,
                "alias": alias_val,
                "opening_amount": op_amt,
                "closing_amount": cl_amt,
                "cash_in": c_in,
                "cash_out": c_out,
                "debit_totals": deb_tot,
                "credit_totals": cred_tot,
                "need_print": need_print,
                "need_confirmation": need_print,
                "did_you_print": did_print,
                "sub_group": sub_group,
                "crm": crm_val,
                "get_back": get_back,
                "expected_opening": exp_op,
                "expected_closing": exp_cl,
            })
        cur.close()
        return results

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
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
    # Safe: col is strictly checked against allowed_fields whitelist dictionary and escaped with [{col}]
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
    finally:
        try:
            cur.close()
        except Exception:
            pass


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
