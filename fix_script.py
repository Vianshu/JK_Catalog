import os
path = 'src/ui/supp_payment/anil_hisab.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("WHERE key='start_date_locked'", "WHERE [key]='start_date_locked'")
text = text.replace("INSERT INTO anil_settings (key,value)", "INSERT INTO anil_settings ([key],value)")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
