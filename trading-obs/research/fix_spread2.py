import sqlite3, math

conn = sqlite3.connect("kerno.db")
conn.row_factory = sqlite3.Row

print("Cargando eventos...")
events = conn.execute("""
    SELECT symbol, event_time_ms, price
    FROM market_events
    ORDER BY event_time_ms ASC
""").fetchall()

from collections import defaultdict
ev_by_sym = defaultdict(list)
for e in events:
    ev_by_sym[e["symbol"]].append((e["event_time_ms"], e["price"]))
print(f"Eventos cargados: {sum(len(v) for v in ev_by_sym.values())}")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Recalculando spread_est para {len(rows)} filas...")
updated = 0

for row in rows:
    fid = row["id"]
    symbol = row["symbol"]
    ts = row["event_time_ms"]
    p0 = row["price"]

    evs = ev_by_sym[symbol]
    # Binary search para ventana 5s
    lo, hi = 0, len(evs)
    while lo < hi:
        mid = (lo+hi)//2
        if evs[mid][0] < ts-5000: lo = mid+1
        else: hi = mid
    pre_prices = []
    idx = lo
    while idx < len(evs) and evs[idx][0] < ts:
        pre_prices.append(evs[idx][1])
        idx += 1

    if len(pre_prices) >= 4:
        deltas = [pre_prices[i]-pre_prices[i-1] for i in range(1, len(pre_prices))]
        if len(deltas) >= 2:
            pairs = list(zip(deltas[1:], deltas[:-1]))
            ma = sum(p[0] for p in pairs)/len(pairs)
            mb = sum(p[1] for p in pairs)/len(pairs)
            cov = sum((p[0]-ma)*(p[1]-mb) for p in pairs)/len(pairs)
            if cov < 0 and p0 > 0:
                roll = 2 * math.sqrt(-cov)
                spread_pct = roll / p0 * 100
            else:
                spread_pct = 0.0
        else:
            spread_pct = 0.0
    else:
        spread_pct = 0.0

    conn.execute("UPDATE feature_store SET spread_est=? WHERE id=?",
                 (round(spread_pct, 8), fid))
    updated += 1
    if updated % 20000 == 0:
        conn.commit()
        print(f"  {updated}/{len(rows)}")

conn.commit()
print(f"OK: {updated} spread_est recalculados")

r = conn.execute("""
    SELECT MIN(spread_est), MAX(spread_est), AVG(spread_est),
           SUM(CASE WHEN spread_est = 0 THEN 1 ELSE 0 END) as zeros
    FROM feature_store WHERE spread_est IS NOT NULL
""").fetchone()
print(f"min={r[0]:.6f} max={r[1]:.6f} avg={r[2]:.6f} zeros={r[3]}")
conn.close()