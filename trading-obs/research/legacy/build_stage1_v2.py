import sqlite3, math

conn = sqlite3.connect("kerno.db")
conn.row_factory = sqlite3.Row

print("Cargando datos...")
# Cargar todo de una vez
events = conn.execute("""
    SELECT symbol, event_time_ms, price
    FROM market_events
    ORDER BY event_time_ms ASC
""").fetchall()
print(f"Eventos cargados: {len(events)}")

# Indexar por simbolo
from collections import defaultdict
ev_by_sym = defaultdict(list)
for e in events:
    ev_by_sym[e["symbol"]].append((e["event_time_ms"], e["price"]))

print("Cargando feature_store...")
rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price, spread_est, 
           volatility_1m, vol_ratio_1s_5s
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()
print(f"Feature store: {len(rows)} filas")

updated = 0
tradeable = 0

for row in rows:
    fid = row["id"]
    symbol = row["symbol"]
    ts = row["event_time_ms"]
    p0 = row["price"]
    spread = row["spread_est"] or 0.001
    vol1m = row["volatility_1m"] or 0.001

    evs = ev_by_sym[symbol]

    # Binary search helper
    def count_in_window(start, end):
        lo, hi = 0, len(evs)
        while lo < hi:
            mid = (lo+hi)//2
            if evs[mid][0] < start: lo = mid+1
            else: hi = mid
        s = lo
        while lo < len(evs) and evs[lo][0] < end: lo += 1
        return lo - s

    def prices_in_window(start, end):
        lo, hi = 0, len(evs)
        while lo < hi:
            mid = (lo+hi)//2
            if evs[mid][0] < start: lo = mid+1
            else: hi = mid
        result = []
        while lo < len(evs) and evs[lo][0] < end:
            result.append(evs[lo][1])
            lo += 1
        return result

    d1m = count_in_window(ts-60000, ts)
    d5m = count_in_window(ts-300000, ts)
    density_1m = d1m / 60.0
    density_5m = d5m / 300.0
    density_ratio = density_1m / density_5m if density_5m > 0 else 1.0
    burst5m = density_5m / max(density_1m, 0.001)
    vol_comp = row["vol_ratio_1s_5s"] or 1.0
    spread_z = 0.0
    dx_spread = density_1m * spread

    # Adaptive threshold
    c_min = 0.002
    c_t = max(c_min, 0.5 * vol1m, 0.3 * spread)

    # Future path 30s
    future_prices = prices_in_window(ts, ts+30000)
    if len(future_prices) >= 3 and p0 > 0:
        m_plus  = max((p-p0)/p0*100 for p in future_prices)
        m_minus = min((p-p0)/p0*100 for p in future_prices)
        label = 1 if max(abs(m_plus), abs(m_minus)) >= c_t else 0
    else:
        label = 0

    if label == 1:
        tradeable += 1

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
    if updated % 20000 == 0:
        conn.commit()
        print(f"  {updated}/{len(rows)} — tradeable: {tradeable}")

conn.commit()
print(f"\nOK: {updated} filas procesadas")
print(f"TRADEABLE: {tradeable}/{updated} = {round(tradeable/updated*100,1)}%")
conn.close()