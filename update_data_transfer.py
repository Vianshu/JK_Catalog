import re

with open('src/logic/data_transfer.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix MISSING_TABLE_PKS
text = re.sub(
    r'"payment_sheet_data":\s*"id"',
    '"payment_sheet_data": None',
    text
)

# Fix SUPP_PAYMENT_TABLES
pattern = r'(SUPP_PAYMENT_TABLES\s*=\s*\[)([\s\S]*?)(\])'
replacement = r'''\1
    "payment_sheet_data",
    "supplier_records",
    "supplier_accounts",
    "anil_ledger",
    "anil_settings",
    "tp_sections",
    "tp_section_cols",
    "tp_section_data",
    "bonus_data",
    "team_list_data",
    "ins_human",
    "ins_vehicle",
    "ins_stock"
\3'''
text = re.sub(pattern, replacement, text)

with open('src/logic/data_transfer.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Regex update applied.')
