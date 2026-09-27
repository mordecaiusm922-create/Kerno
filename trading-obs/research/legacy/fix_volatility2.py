import sqlite3, math

conn = sqlite3.connect("kerno.db")

rows = conn.execute("""
    SELECT id, volatility_1m, price FROM feature_store
    WHERE volatility_1m IS NOT NULL AND price > 0
""").fetchall()

print(f"Aplicando log-transform a {len(rows)} filas...")
updated = 0

for fid, vol, price in rows:
    # Primero desnormalizar (multiplicar por precio / 100)
    vol_abs = vol * price / 100 if vol <= 1.0 else vol
    # Log transform normalizado
    vol_log = math.log1p(vol_abs) / math.log1p(price * 0.01) if price > 0 else 0
    vol_log = min(max(vol_log, 0), 3.0)  # cap at 3 std
    conn.execute("UPDATE feature_store SET volatility_1m=? WHERE id=?",
                 (round(vol_log, 6), fid))
    updated += 1
    if updated % 50000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} filas con log-transform")

r = conn.execute("""
    SELECT MIN(volatility_1m), MAX(volatility_1m), AVG(volatility_1m),
           SUM(CASE WHEN volatility_1m > 0.9 THEN 1 ELSE 0 END) as high
    FROM feature_store WHERE volatility_1m IS NOT NULL
""").fetchone()
print(f"Rango: min={r[0]:.4f} max={r[1]:.4f} avg={r[2]:.4f} high={r[3]}")
conn.close()