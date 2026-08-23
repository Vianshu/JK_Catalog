
import re

content = open('src/ui/godown_list.py', encoding='utf-8').read()
content_norm = content.replace('\r\n', '\n')

lines = content_norm.split('\n')
# Find the duplicate 'else:' block starting around line 481
# The new 'if data:' block at line 453 ends with 'return' at line 480
# The duplicate 'else:' starts at line 481 and ends at line 527

# Find the line numbers (0-indexed)
# Look for the second 'data = self._alias_lookup.get(text.lower())' which is the duplicate
search = '                else:\n                    data = self._alias_lookup.get(text.lower())'
idx = content_norm.find(search)
if idx < 0:
    print("NOT FOUND as expected string")
    # Print around line 481
    for i, l in enumerate(lines[477:530], start=478):
        print(f'{i+1}: {repr(l)}')
else:
    # Find the end of this block - it ends with 'self.save_data_to_db()'
    # followed by an empty line
    end_marker = '                        self.save_data_to_db()\n\n            # Column 1'
    end_idx = content_norm.find(end_marker, idx)
    if end_idx < 0:
        print("END NOT FOUND")
        print(repr(content_norm[idx:idx+200]))
    else:
        # Replace the duplicate else block with the simple no-match else
        replacement = '''                else:
                    unit_val = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
                    pno_val  = self.table.item(row, 5).text() if self.table.item(row, 5) else ""
                    self.set_item_locked(row, 2, unit_val, should_lock=False)
                    self.set_item_locked(row, 5, pno_val,  should_lock=False)
                    if not self.table.item(row, 1): self.set_item_locked(row, 1, "", should_lock=False)
                    from PyQt6.QtCore import QTimer
                    def _move_and_edit_else(r=row):
                        self._nav_set_current(r, 1)
                        if self.table.item(r, 1):
                            self.table.editItem(self.table.item(r, 1))
                    QTimer.singleShot(0, _move_and_edit_else)
                    self.save_data_to_db()

            # Column 1'''
        old_block = content_norm[idx:end_idx + len(end_marker)]
        content_new = content_norm.replace(old_block, replacement, 1)
        open('src/ui/godown_list.py', 'w', encoding='utf-8').write(content_new)
        print('DONE')
