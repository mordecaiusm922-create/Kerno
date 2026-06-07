import sqlite3

conn = sqlite3.connect("kerno.db")

# Agregar columna para label microestructural
try:
    conn.execute("ALTER TABLE feature_store ADD COLUMN micro_label TEXT")
    conn.commit()
    print("OK: columna micro_label agregada")
except:
    print("micro_label ya existe")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Labeleando {len(rows)} filas con path-dependent logic...")

# Costo round-trip estimado: fees 0.04% + slippage 0.01%
C = 0.01

updated = 0
dist = {"CONTINUATION_UP": 0, "CONTINUATION_DOWN": 0, "ABSORPTION": 0, "NOISE": 0}

for fid, symbol, ts, p0 in rows:
    # Path futuro 60s
    future = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms <= ?
        ORDER BY event_time_ms ASC LIMIT 200
    """, (symbol, ts, ts + 60000)).fetchall()

    if len(future) < 5:
        continue

    prices = [r[0] for r in future]
    returns = [(p - p0) / p0 * 100 for p in prices]

    M_plus  = max(returns)
    M_minus = min(returns)

    if M_plus > C and M_minus > -(C / 2):
        label = "CONTINUATION_UP"
    elif M_minus < -C and M_plus < (C / 2):
        label = "CONTINUATION_DOWN"
    elif abs(M_plus) < C and abs(M_minus) < C:
        label = "NOISE"
    else:
        label = "ABSORPTION"

    dist[label] = dist.get(label, 0) + 1

    conn.execute("UPDATE feature_store SET micro_label=? WHERE id=?", (label, fid))

    updated += 1
    if updated % 10000 == 0:
        conn.commit()
        print(f"  {updated} labeleados...")

conn.commit()
print(f"\nOK: {updated} filas con label microestructural")
print("\nDistribucion:")
for k, v in dist.items():
    print(f"  {k:<20} {v:>6}  ({round(v/updated*100,1)}%)")
conn.close()