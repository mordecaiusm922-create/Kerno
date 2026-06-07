import sqlite3, sys
sys.path.insert(0, '.')

conn = sqlite3.connect('kerno.db')
conn.row_factory = sqlite3.Row

# Simular un insert
try:
    conn.execute("""
        INSERT INTO signal_outcomes
        (symbol, signal, bucket, confidence, price_entry, event_time_ms)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("BTCUSDT", "REV_EDGE", "MEDIUM", 0.73, 78500.0, 1777652538994))
    conn.commit()
    print("INSERT OK")
    print("Filas:", conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0])
except Exception as e:
    print("ERROR:", e)
conn.close()
