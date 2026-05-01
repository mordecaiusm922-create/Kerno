import sqlite3
conn = sqlite3.connect('kerno.db')

rows = conn.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN ABS(price_entry - price_10s)/price_entry*100 < 0.001 THEN 1 ELSE 0 END) as micro_moves,
        AVG(ABS(price_entry - price_10s)/price_entry*100) as avg_move_pct,
        AVG(price_10s - price_entry) as avg_raw_move
    FROM signal_outcomes 
    WHERE price_10s IS NOT NULL
""").fetchone()
print(f"Total validadas: {rows[0]}")
print(f"Micro-moves (<0.001%): {rows[1]}")
print(f"Avg move despues de senal: {rows[2]:.8f}%")
print(f"Avg move raw: {rows[3]:.6f}")

# Ver las primeras 5 señales con sus resultados
print("\n=== MUESTRA ===")
sample = conn.execute("""
    SELECT signal, bucket, confidence, price_entry, price_10s, result_10s
    FROM signal_outcomes LIMIT 10
""").fetchall()
for r in sample:
    move = ((r[4]-r[3])/r[3]*100) if r[4] else 0
    print(f"  {r[0]:<12} {r[1]:<8} conf={r[2]:.3f} entry={r[3]:.2f} p10s={r[4]} move={move:.6f}% -> {r[5]}")
conn.close()
