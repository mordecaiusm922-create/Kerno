import sqlite3, math

conn = sqlite3.connect("kerno.db")

# Agregar columnas ETH flow features
cols = ["signed_imbalance_1s", "signed_imbalance_5s", "ewma_imbalance",
        "burst_5s", "burst_ratio", "burst_accel",
        "ret_250ms", "ret_1s", "ret_accel",
        "vol_1s", "vol_5s", "vol_ratio_1s_5s",
        "mean_trade_size_1s", "trade_size_cv_5s"]

for col in cols:
    try:
        conn.execute(f"ALTER TABLE feature_store ADD COLUMN {col} REAL")
    except:
        pass
conn.commit()
print("OK: columnas ETH agregadas")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price, volume
    FROM feature_store
    WHERE symbol='ETHUSDT'
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Procesando {len(rows)} filas ETH...")
updated = 0

for i, (fid, symbol, ts, p0, vol0) in enumerate(rows):
    # Ticks ultimos 5s
    pre5 = conn.execute("""
        SELECT price, quantity, event_time_ms FROM market_events
        WHERE symbol='ETHUSDT' AND event_time_ms >= ? AND event_time_ms < ?
        ORDER BY event_time_ms ASC
    """, (ts - 5000, ts)).fetchall()

    # Ticks ultimos 1s
    pre1 = [r for r in pre5 if r[2] >= ts - 1000]

    # Ticks ultimos 250ms
    pre250 = [r for r in pre5 if r[2] >= ts - 250]

    if len(pre5) < 3:
        continue

    prices5 = [r[0] for r in pre5]
    prices1 = [r[0] for r in pre1]
    vols1   = [r[1] for r in pre1]
    vols5   = [r[1] for r in pre5]

    # Signed imbalance
    def signed_imb(prices, vols):
        if len(prices) < 2:
            return 0.0
        signs = [1 if prices[i] > prices[i-1] else (-1 if prices[i] < prices[i-1] else 0)
                 for i in range(1, len(prices))]
        total_vol = sum(vols[1:]) or 1e-10
        return sum(s * v for s, v in zip(signs, vols[1:])) / total_vol

    imb1 = signed_imb(prices1, vols1)
    imb5 = signed_imb(prices5, vols5)

    # EWMA imbalance (decay 0.8)
    if len(prices5) >= 2:
        signs5 = [1 if prices5[i] > prices5[i-1] else (-1 if prices5[i] < prices5[i-1] else 0)
                  for i in range(1, len(prices5))]
        ewma = 0.0
        for s in signs5:
            ewma = 0.8 * ewma + 0.2 * s
    else:
        ewma = 0.0

    # Burst features
    baseline = conn.execute("""
        SELECT COUNT(*) FROM market_events
        WHERE symbol='ETHUSDT' AND event_time_ms >= ? AND event_time_ms < ?
    """, (ts - 60000, ts)).fetchone()[0]
    avg_rate = baseline / 60 if baseline > 0 else 1
    b1 = len(pre1) / avg_rate if avg_rate > 0 else 0
    b5 = len(pre5) / avg_rate / 5 if avg_rate > 0 else 0
    burst_ratio = b1 / b5 if b5 > 0 else 0
    burst_accel = b1 - b5

    # Returns
    ref5  = prices5[0] if prices5 else p0
    ref1  = prices1[0] if prices1 else p0
    ref250 = [r[0] for r in pre5 if r[2] >= ts - 250]
    ref250 = ref250[0] if ref250 else p0

    ret1   = (p0 - ref1)   / ref1   * 100 if ref1 > 0 else 0
    ret250 = (p0 - ref250) / ref250 * 100 if ref250 > 0 else 0
    ret_accel = ret1 - ret250

    # Volatility
    def vol_calc(prices):
        if len(prices) < 3:
            return 0.0
        rets = [(prices[i]-prices[i-1])/prices[i-1]*100
                for i in range(1, len(prices)) if prices[i-1] > 0]
        if not rets:
            return 0.0
        mean = sum(rets)/len(rets)
        return (sum((r-mean)**2 for r in rets)/len(rets))**0.5

    v1 = vol_calc(prices1)
    v5 = vol_calc(prices5)
    vr = v1 / v5 if v5 > 0 else 1.0

    # Trade size
    mean_size = sum(vols1) / len(vols1) if vols1 else 0
    if len(vols5) >= 2:
        mean5 = sum(vols5)/len(vols5)
        std5  = (sum((v-mean5)**2 for v in vols5)/len(vols5))**0.5
        cv5   = std5/mean5 if mean5 > 0 else 0
    else:
        cv5 = 0.0

    conn.execute("""
        UPDATE feature_store
        SET signed_imbalance_1s=?, signed_imbalance_5s=?, ewma_imbalance=?,
            burst_5s=?, burst_ratio=?, burst_accel=?,
            ret_250ms=?, ret_1s=?, ret_accel=?,
            vol_1s=?, vol_5s=?, vol_ratio_1s_5s=?,
            mean_trade_size_1s=?, trade_size_cv_5s=?
        WHERE id=?
    """, (round(imb1,6), round(imb5,6), round(ewma,6),
          round(b5,4), round(burst_ratio,4), round(burst_accel,4),
          round(ret250,8), round(ret1,8), round(ret_accel,8),
          round(v1,8), round(v5,8), round(vr,4),
          round(mean_size,8), round(cv5,4), fid))

    updated += 1
    if updated % 5000 == 0:
        conn.commit()
        print(f"  {updated} procesados...")

conn.commit()
print(f"OK: {updated} filas ETH con flow features")
conn.close()