import os, re

files = ['src/logic/catalog_logic.py', 'src/ui/supp_payment.py', 'src/ui/cheque_list.py', 'src/ui/godown_list.py']
for f in files:
    if not os.path.exists(f): continue
    content = open(f, encoding='utf-8').read()
    
    print(f"\n--- Checking {f} for f-string DB queries (SQL injection/errors) ---")
    matches = re.finditer(r'\.execute(?:_query)?\(\s*(?:f\"[^\"]*\"|f\'[^\']*\')', content)
    for m in matches:
        start = max(0, m.start() - 20)
        end = min(len(content), m.end() + 20)
        print(f'Match: {content[start:end]}')

    print(f"\n--- Checking {f} for unclosed connections or missing commits ---")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'get_connection(' in line or '_get_conn(' in line:
            # check the next few lines for commit/close (very rough)
            found_commit = False
            for j in range(i, min(i+15, len(lines))):
                if 'commit()' in lines[j] or 'rollback()' in lines[j]:
                    found_commit = True
            if 'INSERT ' in content[max(0, i-50):min(len(content), i+200)] and not found_commit:
                print(f"Possible missing commit near line {i+1}: {line.strip()}")
