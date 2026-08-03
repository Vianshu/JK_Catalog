import sqlite3
conn = sqlite3.connect('C:/Users/HP/Desktop/testt/HW Divison 082083.db')
c = conn.cursor()
c.execute("SELECT item_name FROM stock_items WHERE item_name LIKE '%super%stick%'")
print(c.fetchall())
