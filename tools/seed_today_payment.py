"""
seed_today_payment.py
─────────────────────────────────────────────────────────────────────────────
Standalone script to add / update data in the Today Payment tab.

Run from the project root directory:
    python tools/seed_today_payment.py

The script connects directly to SQL Server (same instance as the main app),
finds the correct company database for the specified company folder, creates
the tables if they don't exist, then inserts the data you define below.

SETUP
─────
1. Edit the COMPANY_PATH variable to point to your company data folder.
2. Edit the data arrays below (PAYMENTS, DL, etc.) with your current values.
3. Run the script.  It will wipe and re-insert the data for each section.
4. Open the app → Supp. Payment → Today Payment to see the changes live.
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import os

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.logic.db_manager import get_db_manager, build_logical_name

# ==============================================================================
# CONFIGURE THESE
# ==============================================================================

# Path to your company's data folder
COMPANY_PATH = r"C:\Users\HP\Desktop\testt\HW Divison 082083"

# ─── PAYMENTS ────────────────────────────────────────────────────────────────
# Columns: date, particulars, payment, col4, col5
PAYMENTS = [
    ("",           "Macha Bank",                              "",          "macha",  "from jnk"),
    ("",           "Macha Bank",                              "",          "macha",  "from brt"),
    ("",           "Macha Bank",                              "",          "macha",  "from btm"),
    ("",           "Macha Bank",                              "",          "macha",  "from ngt"),
    ("2026-08-10", "Car Loan Emi",                            "50000",     "",       ""),
    ("2026-09-10", "Home Loan Suman Mam",                     "0",         "",       ""),
    ("2026-08-16", "Interest-Macha Bank-QTR End",             "0",         "",       ""),
    ("2026-08-16", "PWCL- Every 3 Month interest",            "0",         "",       ""),
    ("2026-09-14", "PWCL- Every 3 Month",                     "0",         "",       ""),
    ("2026-08-10", "NEW LOAN 1013",                           "500000",    "",       ""),
    ("2026-08-16", "NEW LOAN 1013 interest",                  "0",         "",       ""),
    ("",           "Rajkumar ji",                             "",          "",       ""),
    ("fri",        "Chandrodaya, Brt",                        "",          "",       ""),
    ("mon/tue",    "Chandrodaya, KTM",                        "650000",    "",       ""),
    ("",           "ANIL SIR",                                "",          "",       ""),
    ("2026-08-07", "Kishan Pipe Product",                     "150000",    "",       ""),
    ("fri",        "Dhiraj trading",                          "",          "",       ""),
    ("thu",        "Priti valve & Fitting Ind, P. Ltd",       "40000",     "",       ""),
    ("sun",        "Tejas Tiwari Group Pvt.Ltd, Ktm",         "",          "",       ""),
    ("wed",        "Aarna International Pvt.Ltd, Kathmandu",  "45000",     "",       ""),
    ("fri",        "Sujita Paints Industries,Brt",            "",          "",       ""),
    ("wed",        "Jeen Mata Impex Pvt. Ltd.",               "",          "",       ""),
    ("",           "Jitu sir (machha credit card)",           "",          "",       ""),
    ("",           "Papa",                                    "",          "",       ""),
    ("",           "vat",                                     "",          "",       ""),
    ("",           "Brijwashi Products , Aligarh India",      "241281.99", "M11548", "rtgs"),
]

# ─── PURCHASE TODAY ──────────────────────────────────────────────────────────
PURCHASE_TODAY = [
    ("2026-08-07", "surendra joshi", "305395", "", "cash brt"),
]

# ─── PURCHASE UPCOMING ───────────────────────────────────────────────────────
PURCHASE_UPCOMING = [
    ("", "jaipur",                           "800000", "", ""),
    ("", "Sri Maruti Mangal, Ktm",           "460000", "", "chq"),
    ("", "Lotus ,Ktm",                       "500000", "", ""),
    ("", "New Famous Tar Jali Udhyog ,Brj",  "176200", "", ""),
]

# ─── ACCOUNTS ────────────────────────────────────────────────────────────────
# Columns: account_name, remain_cash, bank_cash
ACCOUNTS = [
    ("laxmi Bank",        "3653.76",    "3653.76"),
    ("macha (dl settle)", "-732210.42", "1008184.58"),
    ("Cash",              "505395",     "505395"),
    ("btm",               "430000",     "430000"),
    ("jnk",               "0",          "50000"),
    ("Ngt",               "0",          "25000"),
]

# ─── LIMITS & LC ─────────────────────────────────────────────────────────────
# Columns: limit_type, amount, col3
LIMITS = [
    ("Remain Demand Loan Limit", "", ""),
    ("Remain LC Limit",          "", ""),
    ("Used LC",                  "", ""),
]

# ─── DEMAND LOANS (DL) ───────────────────────────────────────────────────────
# Columns: dl_no, amount, expiry_date, days_left (leave "" - app auto-calculates), gap
DL = [
    ("DL-995",  "700000", "2026-08-25", "", "17"),
    ("DL-997",  "700000", "2026-09-01", "", "7"),
    ("DL-1001", "700000", "2026-09-07", "", "6"),
    ("DL-1003", "700000", "2026-09-11", "", "4"),
    ("DL-1009", "700000", "2026-09-18", "", "7"),
    ("DL-1016", "700000", "2026-09-28", "", "10"),
    ("DL-1024", "700000", "2026-10-01", "", "3"),
    ("DL-1029", "700000", "2026-10-06", "", "5"),
    ("DL-1036", "700000", "2026-10-12", "", "6"),
    ("DL-1043", "700000", "2026-10-21", "", "9"),
    ("DL-1048", "700000", "2026-10-29", "", "8"),
    ("DL-1052", "700000", "2026-11-04", "", "6"),
    ("DL-1057", "700000", "2026-11-10", "", "6"),
    ("DL-1062", "700000", "2026-11-17", "", "7"),
    ("DL-1071", "700000", "2026-11-26", "", "9"),
    ("DL-10",   "700000", "2026-12-02", "", "6"),
]

# ==============================================================================
# END OF CONFIG
# ==============================================================================


def main():
    company_name = os.path.basename(os.path.normpath(COMPANY_PATH))
    db_name = build_logical_name(company_name, company_path=COMPANY_PATH)

    print(f"Company:  {company_name}")
    print(f"Database: {db_name}")
    print()

    db = get_db_manager()

    tables = {
        "tp_payments":     "CREATE TABLE tp_payments     (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))",
        "tp_pur_today":    "CREATE TABLE tp_pur_today    (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))",
        "tp_pur_upcoming": "CREATE TABLE tp_pur_upcoming (sn INT IDENTITY, date NVARCHAR(50), particulars NVARCHAR(MAX), payment NVARCHAR(100), col4 NVARCHAR(100), col5 NVARCHAR(200))",
        "tp_accounts":     "CREATE TABLE tp_accounts     (sn INT IDENTITY, account_name NVARCHAR(200), remain_cash NVARCHAR(100), bank_cash NVARCHAR(100))",
        "tp_limits":       "CREATE TABLE tp_limits       (sn INT IDENTITY, limit_type NVARCHAR(200), amount NVARCHAR(100), col3 NVARCHAR(100))",
        "tp_dl":           "CREATE TABLE tp_dl           (sn INT IDENTITY, dl_no NVARCHAR(100), amount NVARCHAR(100), expiry_date NVARCHAR(50), days_left NVARCHAR(20), gap NVARCHAR(20))",
    }

    print("Ensuring tables...")
    for table, ddl in tables.items():
        ok = db.ensure_table(db_name, table, ddl)
        print(f"  {'[OK]' if ok else '[FAIL]'} {table}")

    print()
    conn = db.get_connection(db_name)
    if not conn:
        print("ERROR: Could not connect. Is the app running or SQL Server available?")
        sys.exit(1)

    cur = conn.cursor()

    sections = [
        ("tp_payments",     "(date, particulars, payment, col4, col5)",  PAYMENTS),
        ("tp_pur_today",    "(date, particulars, payment, col4, col5)",  PURCHASE_TODAY),
        ("tp_pur_upcoming", "(date, particulars, payment, col4, col5)",  PURCHASE_UPCOMING),
        ("tp_accounts",     "(account_name, remain_cash, bank_cash)",    ACCOUNTS),
        ("tp_limits",       "(limit_type, amount, col3)",                LIMITS),
        ("tp_dl",           "(dl_no, amount, expiry_date, days_left, gap)", DL),
    ]

    try:
        for table, cols, data in sections:
            ncols = len(data[0]) if data else 0
            placeholders = ", ".join(["?"] * ncols)
            cur.execute(f"DELETE FROM {table}")
            if data:
                cur.executemany(
                    f"INSERT INTO {table} {cols} VALUES ({placeholders})", data
                )
            print(f"  Seeded {len(data):>3} row(s)  ->  {table}")

        conn.commit()
        print()
        print("All data seeded successfully!")
        print("Open the app and navigate to Supp. Payment -> Today Payment to verify.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        raise


if __name__ == "__main__":
    main()
