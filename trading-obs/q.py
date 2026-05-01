import sqlite3
conn = sqlite3.connect('kerno.db')
rows = conn.execute("""
    SELECT price, event_time_ms FROM market_events
    WHERE symbol='BTCUSDT'
    ORDER BY event_time_ms DESC LIMIT 20
""").fetchall()
conn.close()
prices = [r[0] for r in rows]
times  = [r[1] for r in rows]
import datetime
for i in range(1, len(prices)):
    move = abs(prices[i-1] - prices[i]) / prices[i] * 100
    ts   = datetime.datetime.fromtimestamp(times[i-1]/1000).strftime('%H:%M:%S')
    print(f"{ts}  {prices[i-1]:.2f}  move={move:.6f}%")
