import sqlite3

conn = sqlite3.connect("kerno.db")

# Normalizar spread_est como % del precio
rows = conn.execute("""
    SELECT id, spread_est, price FROM feature_store
    WHERE spread_est IS NOT NULL AND price > 0
""").fetchall()

print(f"Normalizando {len(rows)} filas...")
updated = 0

for fid, spread, price in rows:
    spread_pct = (spread / price) * 100 if price > 0 else 0
    spread_pct = min(spread_pct, 1.0)  # cap at 1%
    conn.execute("UPDATE feature_store SET spread_est=? WHERE id=?",
                 (round(spread_pct, 6), fid))
    updated += 1
    if updated % 50000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} spread_est normalizados como % precio")

# Verificar
rows2 = conn.execute("""
    SELECT MIN(spread_est), MAX(spread_est), AVG(spread_est)
    FROM feature_store WHERE spread_est IS NOT NULL
""").fetchone()
print(f"Nuevo rango: min={rows2[0]:.6f} max={rows2[1]:.6f} avg={rows2[2]:.6f}")
conn.close()