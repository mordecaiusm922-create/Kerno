import sqlite3, datetime

conn = sqlite3.connect('kerno.db')

# Buscar ventanas con spikes reales en el historico
rows = conn.execute("""
    SELECT price, event_time_ms FROM market_events
    WHERE symbol='BTCUSDT'
    ORDER BY event_time_ms ASC
""").fetchall()

spikes = []
for i in range(1, len(rows)):
    p0, t0 = rows[i-1]
    p1, t1 = rows[i]
    if p0 > 0:
        move = abs(p1 - p0) / p0 * 100
        if move >= 0.005:  # solo moves reales
            spikes.append((t0, p0, p1, move))

print(f"Spikes reales (>= 0.005%) en historico: {len(spikes)}")
if spikes:
    wins, losses = 0, 0
    for t0, p0, p1, move in spikes[:200]:
        # Simular costo de ejecucion: spread estimado 0.001% + fee 0.04% Binance taker
        cost = p0 * (0.00001 + 0.0004)
        # Si es REV_EDGE: apostamos a que baja
        # Buscamos precio 10s despues
        target_ms = t0 + 10000
        future = conn.execute("""
            SELECT price FROM market_events
            WHERE symbol='BTCUSDT' AND event_time_ms >= ?
            ORDER BY event_time_ms ASC LIMIT 1
        """, (target_ms,)).fetchone()
        if future:
            pf = future[0]
            raw_move = p1 - pf  # queremos que baje (REV)
            net = raw_move - cost
            if net > 0:
                wins += 1
            else:
                losses += 1

    total = wins + losses
    print(f"Execution-aware WIN rate (10s, REV): {wins}/{total} = {round(wins/total*100,1) if total else 0}%")
    print(f"Spread+fee estimado por trade: ~0.041%")

    ts = datetime.datetime.fromtimestamp(spikes[0][0]/1000).strftime('%H:%M:%S')
    ts2 = datetime.datetime.fromtimestamp(spikes[-1][0]/1000).strftime('%H:%M:%S')
    print(f"Rango analizado: {ts} → {ts2}")

conn.close()
