import sqlite3
conn = sqlite3.connect('kerno.db')
rows = conn.execute("""
    SELECT spike_pct, COUNT(*) as n
    FROM signal_outcomes so
    JOIN market_events me ON so.price_entry = me.price
    LIMIT 5
""").fetchall()

# Ver distribucion de spike_pct en señales registradas
rows2 = conn.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN ABS(price_entry - price_10s)/price_entry*100 < 0.001 THEN 1 ELSE 0 END) as micro_moves,
        AVG(ABS(price_entry - price_10s)/price_entry*100) as avg_move_pct
    FROM signal_outcomes 
    WHERE price_10s IS NOT NULL
""").fetchone()
print(f"Total validadas: {rows2[0]}")
print(f"Micro-moves (<0.001%): {rows2[1]}")
print(f"Avg move después de señal: {rows2[2]:.6f}%")
conn.close()
