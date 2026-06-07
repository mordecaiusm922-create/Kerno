import sqlite3, time
conn = sqlite3.connect("kerno.db")
r = conn.execute("SELECT strftime('%s','now') * 1000").fetchone()
print("SQLite now ms:", r[0])
print("Python now ms:", int(time.time()*1000))
conn.close()