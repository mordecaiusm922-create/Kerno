import sqlite3
conn = sqlite3.connect('kerno.db')
conn.execute("DELETE FROM signal_outcomes")
conn.commit()
print("OK: signal_outcomes limpia -", conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0], "filas")
conn.close()
