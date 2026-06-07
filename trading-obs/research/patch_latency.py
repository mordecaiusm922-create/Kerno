import sqlite3

conn = sqlite3.connect("kerno.db")

try:
    conn.execute("ALTER TABLE feature_store ADD COLUMN latency_z REAL")
    conn.execute("ALTER TABLE feature_store ADD COLUMN lat_x_burst REAL")
    conn.execute("ALTER TABLE feature_store ADD COLUMN lat_x_vol REAL")
    conn.commit()
    print("OK: columnas agregadas")
except:
    print("columnas ya existen")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, latency_ms, burst_1s, vol_ratio
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Procesando {len(rows)} filas...")
WINDOW = 50
updated = 0

for i, (fid, symbol, ts, lat, burst, vol) in enumerate(rows):
    if lat is None or burst is None or vol is None:
        continue
    window = [rows[j][3] for j in range(max(0, i-WINDOW), i)
              if rows[j][1] == symbol and rows[j][3] is not None]
    if len(window) < 10:
        lat_z = 0.0
    else:
        mean = sum(window) / len(window)
        std  = (sum((w-mean)**2 for w in window) / len(window))**0.5
        lat_z = round((lat - mean) / std, 4) if std > 0 else 0.0

    lat_burst = round(lat_z * burst, 4)
    lat_vol   = round(lat_z * vol, 4)

    conn.execute("""
        UPDATE feature_store
        SET latency_z=?, lat_x_burst=?, lat_x_vol=?
        WHERE id=?
    """, (lat_z, lat_burst, lat_vol, fid))

    updated += 1
    if updated % 20000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} filas con latency normalizada")
conn.close()