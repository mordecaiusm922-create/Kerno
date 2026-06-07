import sqlite3
conn = sqlite3.connect('kerno.db')

# Ultimas señales con spike real
rows = conn.execute("""
    SELECT price, event_time_ms,
           LAG(price) OVER (ORDER BY event_time_ms) as prev_price,
           ABS(price - LAG(price) OVER (ORDER BY event_time_ms)) / 
           LAG(price) OVER (ORDER BY event_time_ms) * 100 as move_pct
    FROM market_events
    WHERE symbol='BTCUSDT'
    ORDER BY event_time_ms DESC
    LIMIT 500
""").fetchall()

real_moves = [(r[0], r[1], r[3]) for r in rows if r[3] and r[3] > 0.001]
print(f"Movimientos reales (>0.001%) en ultimos 500 eventos: {len(real_moves)}")
if real_moves:
    import datetime
    last = real_moves[0]
    ts = datetime.datetime.fromtimestamp(last[1]/1000).strftime('%H:%M:%S')
    print(f"Ultimo move real: {last[2]:.4f}% a las {ts}")
    print(f"Precio: {last[0]}")

conn.close()
