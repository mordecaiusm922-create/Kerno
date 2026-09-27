import sqlite3, math, time

conn = sqlite3.connect("kerno.db")

# Agregar columnas Stage 1
cols = ["event_density_1m", "event_density_5m", "density_ratio",
        "vol_compression", "spread_z_5m", "burstiness_5m",
        "density_x_spread", "stage1_label"]

for col in cols:
    try:
        conn.execute(f"ALTER TABLE feature_store ADD COLUMN {col} REAL")
    except:
        pass
conn.commit()
print("OK: columnas Stage 1 agregadas")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price, spread_est, 
           volatility_1m, burst_1s, vol_ratio_1s_5s
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Procesando {len(rows)} filas...")
updated = 0

for i, (fid, symbol, ts, p0, spread, vol1m, burst1, volratio) in enumerate(rows):
    if p0 is None:
        continue

    # Event density
    d1m = conn.execute("""
        SELECT COUNT(*) FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
    """, (symbol, ts-60000, ts)).fetchone()[0]

    d5m = conn.execute("""
        SELECT COUNT(*) FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
    """, (symbol, ts-300000, ts)).fetchone()[0]

    density_1m = d1m / 60.0
    density_5m = d5m / 300.0
    density_ratio = density_1m / density_5m if density_5m > 0 else 1.0

    # Vol compression
    vol_comp = (volratio or 1.0)

    # Spread z-score 5m
    spreads = conn.execute("""
        SELECT spread_est FROM feature_store
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms < ?
        AND spread_est IS NOT NULL
    """, (symbol, ts-300000, ts)).fetchall()
    if len(spreads) >= 5:
        sp_vals = [r[0] for r in spreads]
        sp_mean = sum(sp_vals)/len(sp_vals)
        sp_std  = (sum((s-sp_mean)**2 for s in sp_vals)/len(sp_vals))**0.5
        spread_z = (spread-sp_mean)/sp_std if sp_std > 0 and spread else 0.0
    else:
        spread_z = 0.0

    # Burstiness 5m
    burst5m = density_5m / max(density_1m, 0.001)

    # Interaction
    dx_spread = density_1m * (spread or 0)

    # Stage 1 label — adaptive threshold
    vol = vol1m or 0.001
    sp  = spread or 0.001
    c_min = 0.002
    c_t = max(c_min, 0.5 * vol, 0.3 * sp)

    # Get future path 30s
    future = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ? AND event_time_ms <= ?
        ORDER BY event_time_ms ASC LIMIT 100
    """, (symbol, ts, ts+30000)).fetchall()

    if len(future) >= 3:
        prices = [r[0] for r in future]
        m_plus  = max((p-p0)/p0*100 for p in prices)
        m_minus = min((p-p0)/p0*100 for p in prices)
        label = 1 if max(abs(m_plus), abs(m_minus)) >= c_t else 0
    else:
        label = 0

    conn.execute("""
        UPDATE feature_store
        SET event_density_1m=?, event_density_5m=?, density_ratio=?,
            vol_compression=?, spread_z_5m=?, burstiness_5m=?,
            density_x_spread=?, stage1_label=?
        WHERE id=?
    """, (round(density_1m,4), round(density_5m,4), round(density_ratio,4),
          round(vol_comp,4), round(spread_z,4), round(burst5m,4),
          round(dx_spread,6), label, fid))

    updated += 1
    if updated % 10000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} filas con Stage 1 features")

# Distribution
total = conn.execute("SELECT COUNT(*) FROM feature_store WHERE stage1_label IS NOT NULL").fetchone()[0]
tradeable = conn.execute("SELECT COUNT(*) FROM feature_store WHERE stage1_label=1").fetchone()[0]
print(f"TRADEABLE: {tradeable}/{total} = {round(tradeable/total*100,1)}%")
conn.close()