import pandas as pd
import sys
import datetime

excel_path = r'C:\Users\HP\Desktop\Supp. Bank account recod.xlsx'
out_path = r'C:\Users\HP\Desktop\project\backup code\populate_supp_payment.sql'

try:
    xl = pd.ExcelFile(excel_path)
    df_record = xl.parse('Record')
    df_anil = xl.parse('Anil Dai Hisab')
    df_team = xl.parse('Team-List')
    df_bonus = xl.parse("Bonus detail's")
    df_tp = xl.parse('today payment', header=None)
except Exception as e:
    print(f"Error reading excel: {e}")
    sys.exit(1)

def safe_str(val):
    if pd.isna(val) or str(val).strip() == 'nan':
        return ''
    if isinstance(val, datetime.datetime):
        return val.strftime('%Y-%m-%d')
    return str(val).strip().replace(chr(39), chr(39)+chr(39))

sql_statements = [
    "-- USE [YOUR_DATABASE_NAME];",
    "GO",
    "",
    "PRINT 'Clearing existing supplier payment tables...'",
    "DELETE FROM supplier_accounts;",
    "DELETE FROM supplier_records;",
    "DELETE FROM anil_ledger;",
    "DELETE FROM team_list_data;",
    "DELETE FROM bonus_data;",
    "DELETE FROM tp_sections;",
    "DELETE FROM tp_section_data;",
    "",
    "PRINT 'Populating Supplier Records and Accounts...'"
]

# -----------------
# 1. Record Sheet (39 cards, sequential normal numbering 1 to 39)
# -----------------
sql_statements.append("SET IDENTITY_INSERT supplier_records ON;")

sn_indices = df_record[df_record['S.N.'].notna()].index.tolist()

for i, start_idx in enumerate(sn_indices):
    end_idx = sn_indices[i+1] if i + 1 < len(sn_indices) else len(df_record)
    block = df_record.iloc[start_idx:end_idx].reset_index(drop=True)
    supplier_name = safe_str(block.loc[0, 'A/C of'])
    if not supplier_name: 
        continue
        
    seq_id = i + 1
    
    sql_statements.append(f"INSERT INTO supplier_records (id, name, sort_order) VALUES ({seq_id}, N'{supplier_name}', {seq_id});")
    sql_statements.append(f"DECLARE @Supp{seq_id} INT = {seq_id};")


    
    accounts = [
        {'type': 'Company Account', 'label_col': df_record.columns[2], 'val_col': df_record.columns[3]},
        {'type': 'Personal Account', 'label_col': df_record.columns[5], 'val_col': df_record.columns[6]},
    ]
    
    if len(df_record.columns) > 9:
        accounts.append({'type': 'Other Account 1', 'label_col': df_record.columns[8], 'val_col': df_record.columns[9]})
        
    acc_index = 0
    for acc in accounts:
        l_col = acc['label_col']
        v_col = acc['val_col']
        if not l_col or not v_col or l_col not in block.columns or v_col not in block.columns:
            continue
            
        acc_data = {}
        for row_i in range(min(6, len(block))):
            lbl = safe_str(block.loc[row_i, l_col])
            val = safe_str(block.loc[row_i, v_col])
            if val:
                acc_data[lbl] = val
                
        if not acc_data:
            continue
            
        naam = acc_data.get('नाम', '')
        thegana = acc_data.get('ठेगाना', '')
        baik = acc_data.get('बैक', '')
        khata = acc_data.get('खाता न.', '')
        rakam = acc_data.get('रकम', '')
        jamma = acc_data.get('जम्मा गर्ने', '')
        
        sql = (f"INSERT INTO supplier_accounts (supplier_id, acc_index, acc_type, naam, thegana, baik, khata, rakam, jamma) "
               f"VALUES (@Supp{seq_id}, {acc_index}, N'{acc['type']}', N'{naam}', N'{thegana}', N'{baik}', N'{khata}', N'{rakam}', N'{jamma}');")
        sql_statements.append(sql)
        acc_index += 1
    sql_statements.append('')

sql_statements.append("SET IDENTITY_INSERT supplier_records OFF;")
sql_statements.append('')

# -----------------
# 2. Anil Dai Hisab
# -----------------
sql_statements.append("PRINT 'Populating Anil Ledger...'")
for i, row in df_anil.iterrows():
    sd = safe_str(row.iloc[0])
    ed = safe_str(row.iloc[1])
    dy = safe_str(row.iloc[2])
    pa = safe_str(row.iloc[3])
    dr = safe_str(row.iloc[4])
    cr = safe_str(row.iloc[5])
    rm = safe_str(row.iloc[6]) if len(row) > 6 else ''
    if not (pa or dr or cr):
        continue
    sql_statements.append(f"INSERT INTO anil_ledger (sort_order, start_date, end_date, days, particular, dr, cr, remarks) "
                          f"VALUES ({i}, N'{sd}', N'{ed}', N'{dy}', N'{pa}', N'{dr}', N'{cr}', N'{rm}');")
sql_statements.append('')

# -----------------
# 3. Team-List
# -----------------
sql_statements.append("PRINT 'Populating Team List...'")
for r_idx in range(len(df_team)):
    for c_idx in range(len(df_team.columns)):
        val = safe_str(df_team.iloc[r_idx, c_idx])
        if val:
            sql_statements.append(f"INSERT INTO team_list_data (row_idx, col_idx, cell_text) VALUES ({r_idx}, {c_idx}, N'{val}');")
sql_statements.append('')

# -----------------
# 4. Bonus details
# -----------------
sql_statements.append("PRINT 'Populating Bonus Data...'")
for r_idx in range(len(df_bonus)):
    for c_idx in range(len(df_bonus.columns)):
        val = safe_str(df_bonus.iloc[r_idx, c_idx])
        if val:
            sql_statements.append(f"INSERT INTO bonus_data (row_idx, col_idx, cell_text) VALUES ({r_idx}, {c_idx}, N'{val}');")
sql_statements.append('')

# -----------------
# 5. Today Payment
# -----------------
sql_statements.append("PRINT 'Populating Today Payment...'")

# Seed core sections
_CORE = [
    ("Payments",            "#1565C0", 0),
    ("Demand Loans (DL)",   "#2E7D32", 1),
    ("Purchase (Today)",    "#00695C", 2),
    ("Account Table",       "#E65100", 3),
    ("Purchase (Upcoming)", "#4527A0", 4),
    ("Limits & LC",         "#B71C1C", 5),
]
for name, color, order in _CORE:
    sql_statements.append(f"INSERT INTO tp_sections (sort_order, name, header_color, is_core) VALUES ({order}, N'{name}', N'{color}', 1);")

def insert_tp(name, row_idx, col_idx, val):
    if val:
        sql_statements.append(f"INSERT INTO tp_section_data (section_id, row_idx, col_idx, cell_text) SELECT id, {row_idx}, {col_idx}, N'{val}' FROM tp_sections WHERE name=N'{name}';")

# Parse 6 tables
# Payments
mode = 1 # 1: Payments, 3: Purch Today, 5: Purch Upc
r_idx = 0
for i in range(1, len(df_tp)):
    c1 = safe_str(df_tp.iloc[i, 1]).strip()
    if c1 == 'Today': mode = 3; r_idx = 0; continue
    elif c1 == 'UPCOMING': mode = 5; r_idx = 0; continue
    
    row_vals = [safe_str(df_tp.iloc[i, c]) for c in range(1, 6)]
    if any(row_vals):
        table_name = "Payments" if mode == 1 else "Purchase (Today)" if mode == 3 else "Purchase (Upcoming)"
        for c_idx, val in enumerate(row_vals):
            insert_tp(table_name, r_idx, c_idx, val)
        r_idx += 1

# Account Table
r_idx = 0
for i in range(1, len(df_tp)):
    c7 = safe_str(df_tp.iloc[i, 7]).strip()
    if 'Limit' in c7 or 'Used' in c7: break
    
    row_vals = [safe_str(df_tp.iloc[i, c]) for c in range(7, 10)]
    if any(row_vals):
        for c_idx, val in enumerate(row_vals):
            insert_tp("Account Table", r_idx, c_idx, val)
        r_idx += 1

# Limits & LC
r_idx = 0
i = 1
while i < len(df_tp):
    c7 = safe_str(df_tp.iloc[i, 7]).strip()
    if c7 in ['Remain Demand Loan Limit', 'Remain LC Limit', 'Used LC']:
        limit_type = c7
        limit_val = safe_str(df_tp.iloc[i+1, 7]).strip()
        insert_tp("Limits & LC", r_idx, 0, limit_type)
        insert_tp("Limits & LC", r_idx, 1, limit_val)
        r_idx += 1
        i += 2 # Skip the value row
    else:
        i += 1

# Demand Loans (DL)
r_idx = 0
for i in range(1, len(df_tp)):
    row_vals = [safe_str(df_tp.iloc[i, c]) for c in range(11, 18)]
    if any(row_vals):
        for c_idx, val in enumerate(row_vals):
            insert_tp("Demand Loans (DL)", r_idx, c_idx, val)
        r_idx += 1

sql_statements.append('')
sql_statements.append("GO")

with open(out_path, 'w', encoding='utf-8-sig') as f:
    f.write('\n'.join(sql_statements))

print("Done")
