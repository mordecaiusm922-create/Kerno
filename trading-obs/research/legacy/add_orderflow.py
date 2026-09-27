import sqlite3, math

conn = sqlite3.connect("kerno.db")

# Agregar columnas nuevas
for col in ["imbalance_20", "burst_1s", "vol_ratio", "decay_500ms", "dir_burst"]:
    try:
        conn.execute(f"ALTER TABLE feature_store ADD COLUMN {col} REAL")
        conn.commit()
    except:
        pass
print("OK: columnas agregadas")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Procesando {len(rows)} filas...")
updated = 0

for fid, symbol, ts, p0 in rows:
    # Ticks pre-spike: ultimos 2s
    pre = conn.execute("""
        SELECT price, quantity FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
        ORDER BY event_time_ms ASC
    """, (symbol, ts - 2000, ts)).fetchall()

    # Ticks post-spike: primeros 500ms
    post = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms <= ?
        ORDER BY event_time_ms ASC
    """, (symbol, ts, ts + 500)).fetchall()

    # Ticks 1m para baseline
    baseline = conn.execute("""
        SELECT COUNT(*) FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
    """, (symbol, ts - 60000, ts)).fetchone()[0]

    # Ticks ultimo 1s
    last_1s = conn.execute("""
        SELECT COUNT(*) FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
    """, (symbol, ts - 1000, ts)).fetchone()[0]

    if len(pre) < 3:
        continue

    # Signed imbalance (ponderado por volumen)
    pre_prices = [r[0] for r in pre]
    pre_vols   = [r[1] for r in pre]
    signs = [1 if pre_prices[i] > pre_prices[i-1] else (-1 if pre_prices[i] < pre_prices[i-1] else 0)
             for i in range(1, len(pre_prices))]
    imbalance = sum(s * v for s, v in zip(signs, pre_vols[1:])) / max(sum(pre_vols[1:]), 1e-10)

    # Burstiness
    avg_rate = baseline / 60 if baseline > 0 else 1
    burst = last_1s / avg_rate if avg_rate > 0 else 0

    # Vol ratio
    pre_rets = [abs(pre_prices[i]-pre_prices[i-1])/pre_prices[i-1]*100
                for i in range(1, len(pre_prices)) if pre_prices[i-1] > 0]
    if len(pre_rets) >= 5:
        last5  = pre_rets[-5:]
        vol_5s = (sum((r - sum(last5)/len(last5))**2 for r in last5)/len(last5))**0.5
        vol_1m = (sum((r - sum(pre_rets)/len(pre_rets))**2 for r in pre_rets)/len(pre_rets))**0.5
        vol_ratio = vol_5s / vol_1m if vol_1m > 0 else 1.0
    else:
        vol_ratio = 1.0

    # Post-spike decay 500ms
    post_prices = [r[0] for r in post]
    decay = (post_prices[-1] - p0) / p0 * 100 if len(post_prices) >= 2 and p0 > 0 else 0.0

    # Dir burst
    dir_burst = imbalance * burst

    conn.execute("""
        UPDATE feature_store
        SET imbalance_20=?, burst_1s=?, vol_ratio=?, decay_500ms=?, dir_burst=?
        WHERE id=?
    """, (round(imbalance, 6), round(burst, 4), round(vol_ratio, 4),
          round(decay, 8), round(dir_burst, 6), fid))

    updated += 1
    if updated % 10000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} filas con order flow features")
conn.close()