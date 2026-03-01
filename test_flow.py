import sqlite3, datetime
conn = sqlite3.connect(r'C:\Users\HP\Desktop\Testing\NGT Branch 208283\final_data.db')
cursor = conn.cursor()
now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
cursor.execute("UPDATE catalog SET [Lenth] = ?, [Update_date] = ? WHERE [Product Name] = 'CI. केप'", ('2:3|2', now))
print('Rows updated:', cursor.rowcount)
conn.commit()
conn.close()
