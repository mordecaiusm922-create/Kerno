import sqlite3, math, time

conn = sqlite3.connect("kerno.db")

# Limpiar feature_store para empezar limpio
conn.execute("DELETE FROM feature_store")
conn.commit()

# Traer todos los eventos ordenados
rows = conn.execute("""
    SELECT id, symbol, price, quantity, event_time_ms, ingest_time_ms
    FROM market_events
    WHERE symbol IN ('BTCUSDT','ETHUSDT')
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Total eventos: {len(rows)}")

def compute_spread_features(prices):
    if len(prices) < 10:
        return 0.0, 0.0, 0.0
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    # Roll estimator
    if len(deltas) >= 2:
        pairs = list(zip(deltas[1:], deltas[:-1]))
        ma = sum(p[0] for p in pairs)/len(pairs)
        mb = sum(p[1] for p in pairs)/len(pairs)
        cov = sum((p[0]-ma)*(p[1]-mb) for p in pairs)/len(pairs)
        roll = round(2*math.sqrt(-cov), 8) if cov < 0 else 0.0
    else:
        roll = 0.0
    # Flip rate
    signs = [1 if d>0 else (-1 if d<0 else 0) for d in deltas]
    flips = sum(1 for i in range(1,len(signs))
                if signs[i]!=0 and signs[i-1]!=0 and signs[i]!=signs[i-1])
    flip_rate = round(flips/max(len(signs)-1,1), 4)
    # Micro range
    micro = round(max(prices)-min(prices), 6)
    return roll, flip_rate, micro

# Procesar por ventanas
inserted = 0
WINDOW = 100  # ultimos 100 ticks para features

for i in range(WINDOW, len(rows), 10):  # cada 10 eventos
    row = rows[i]
    rid, symbol, price, qty, ts, ingest = row

    # Ventana de precios anteriores
    window_prices = [rows[j][2] for j in range(i-WINDOW, i)]

    # Spike pct
    prev_price = rows[i-1][2]
    spike_pct = abs(price-prev_price)/prev_price*100 if prev_price > 0 else 0

    # Percentile rank en ventana
    sorted_moves = sorted([abs(window_prices[k]-window_prices[k-1])/window_prices[k-1]*100
                           for k in range(1,len(window_prices)) if window_prices[k-1]>0])
    if sorted_moves:
        spike_pct_rank = sum(1 for m in sorted_moves if m <= spike_pct)/len(sorted_moves)
        mean = sum(sorted_moves)/len(sorted_moves)
        std = (sum((m-mean)**2 for m in sorted_moves)/len(sorted_moves))**0.5
        zscore = round((spike_pct-mean)/std, 3) if std > 0 else 0
    else:
        spike_pct_rank, zscore = 0.0, 0.0

    # Volatility 1m — std de moves en ventana
    volatility = round(std if sorted_moves else 0.0, 8)

    # Trade rate 1m
    t_start = ts - 60000
    trade_rate = sum(1 for r in rows[max(0,i-200):i] if r[4] >= t_start)

    # Spread features
    roll, flip_rate, micro = compute_spread_features(window_prices)

    # Hour of day normalizado 0-1
    hour = (ts // 3600000) % 24
    time_of_day = round(hour / 24, 4)

    # Latency
    latency = ingest - ts

    # Bucket simple
    if spike_pct < sorted_moves[int(len(sorted_moves)*0.75)] if sorted_moves else True:
        bucket = "SMALL"
    elif spike_pct < sorted_moves[int(len(sorted_moves)*0.90)] if sorted_moves else True:
        bucket = "MEDIUM"
    elif spike_pct < sorted_moves[int(len(sorted_moves)*0.99)] if sorted_moves else True:
        bucket = "LARGE"
    else:
        bucket = "EXTREME"

    conn.execute("""
        INSERT INTO feature_store
        (symbol, event_time_ms, price, spike_pct, zscore, bucket,
         signal, confidence, volume, spread_est, volatility_1m,
         trade_rate_1m, hour_of_day, latency_ms)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (symbol, ts, price, round(spike_pct,8), zscore, bucket,
          "PENDING", 0.0, qty, roll, volatility,
          trade_rate, time_of_day, latency))

    inserted += 1
    if inserted % 5000 == 0:
        conn.commit()
        print(f"  {inserted} filas insertadas...")

conn.commit()
print(f"OK: feature_store llenada con {inserted} filas")
conn.close()