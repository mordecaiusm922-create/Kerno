import sqlite3
conn = sqlite3.connect('kerno.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tablas:", tables)
if 'signal_outcomes' in tables:
    print("Filas:", conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0])
else:
    print("TABLA NO EXISTE")
