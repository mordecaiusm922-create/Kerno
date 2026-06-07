import sqlite3

conn = sqlite3.connect("kerno.db")

rows = conn.execute("""
    SELECT id, volatility_1m, price FROM feature_store
    WHERE volatility_1m IS NOT NULL AND price > 0
""").fetchall()

print(f"Normalizando {len(rows)} filas...")
updated = 0

for fid, vol, price in rows:
    vol_pct = (vol / price) * 100 if price > 0 else 0
    vol_pct = min(vol_pct, 1.0)
    conn.execute("UPDATE feature_store SET volatility_1m=? WHERE id=?",
                 (round(vol_pct, 8), fid))
    updated += 1
    if updated % 50000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} volatility_1m normalizados")

r = conn.execute("""
    SELECT MIN(volatility_1m), MAX(volatility_1m), AVG(volatility_1m)
    FROM feature_store WHERE volatility_1m IS NOT NULL
""").fetchone()
print(f"Nuevo rango: min={r[0]:.8f} max={r[1]:.8f} avg={r[2]:.8f}")
conn.close()