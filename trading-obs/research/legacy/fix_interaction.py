import sqlite3
import math

conn = sqlite3.connect("kerno.db")

# Recalcular density_x_spread normalizado
rows = conn.execute("""
    SELECT id, event_density_1m, spread_est
    FROM feature_store
    WHERE event_density_1m IS NOT NULL AND spread_est IS NOT NULL
""").fetchall()

print(f"Recalculando density_x_spread para {len(rows)} filas...")

# Calcular stats para normalizar
vals = [r[1] * r[2] for r in rows if r[1] and r[2]]
mean = sum(vals) / len(vals)
std  = (sum((v-mean)**2 for v in vals) / len(vals))**0.5
print(f"Raw interaction: mean={mean:.6f} std={std:.6f}")

updated = 0
for fid, density, spread in rows:
    raw = (density or 0) * (spread or 0)
    normalized = (raw - mean) / std if std > 0 else 0
    normalized = max(min(normalized, 3.0), -3.0)  # clip at 3 std
    conn.execute("UPDATE feature_store SET density_x_spread=? WHERE id=?",
                 (round(normalized, 6), fid))
    updated += 1
    if updated % 50000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} density_x_spread normalizados")

r = conn.execute("""
    SELECT MIN(density_x_spread), MAX(density_x_spread), AVG(density_x_spread)
    FROM feature_store WHERE density_x_spread IS NOT NULL
""").fetchone()
print(f"Nuevo rango: min={r[0]:.4f} max={r[1]:.4f} avg={r[2]:.4f}")
conn.close()