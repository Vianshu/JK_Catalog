import sqlite3, json

conn = sqlite3.connect(r'C:\Users\HP\Desktop\Testing\HW Divison 082083\catalog.db')
c = conn.cursor()

# CRM pending serials
crm_serials = {'1', '2', '3', '4'}

# Build serial lookup (same as reshuffle_from_crm)
c.execute('SELECT serial_no, group_name, sg_sn, page_no, mg_sn FROM catalog_pages')
all_rows = c.fetchall()

serial_lookup = {}
for sn, g, s, p, m in all_rows:
    serial_lookup[str(sn)] = (g, str(s), p, m)
    try:
        serial_lookup[str(int(sn))] = (g, str(s), p, m)
    except:
        pass

subgroup_pages = {}
matched = 0
unmatched = 0

for serial_no in crm_serials:
    info = serial_lookup.get(str(serial_no))
    if info:
        g, s, p, m = info
        key = (g, s)
        if key not in subgroup_pages:
            subgroup_pages[key] = set()
        subgroup_pages[key].add(p)
        matched += 1
        print(f'  serial {serial_no} → {g}|{s} page {p} ✓')
    else:
        unmatched += 1
        print(f'  serial {serial_no} → NOT FOUND ✗')

print(f'\nMatched: {matched}, Unmatched: {unmatched}')
print(f'Subgroup pages: {subgroup_pages}')

# contiguous ranges
for key, crm_page_nos in subgroup_pages.items():
    sorted_pages = sorted(crm_page_nos)
    contiguous_ranges = []
    if sorted_pages:
        current_range = [sorted_pages[0]]
        for i in range(1, len(sorted_pages)):
            if sorted_pages[i] == sorted_pages[i-1] + 1:
                current_range.append(sorted_pages[i])
            else:
                contiguous_ranges.append(current_range)
                current_range = [sorted_pages[i]]
        contiguous_ranges.append(current_range)
    
    print(f'\nSubgroup {key}:')
    print(f'  CRM pages: {sorted_pages}')
    print(f'  Contiguous ranges: {contiguous_ranges}')
    for rng in contiguous_ranges:
        print(f'  → Would reshuffle pages: {rng}')

# Also show all catalog pages
print(f'\n=== All pages in catalog_pages ({len(all_rows)} total) ===')
for sn, g, s, p, m in sorted(all_rows, key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
    print(f'  serial={sn}, {g}|{s} page {p}')

conn.close()
