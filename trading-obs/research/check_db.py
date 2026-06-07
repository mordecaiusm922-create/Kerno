import sqlite3
conn = sqlite3.connect('kerno.db')
rows = conn.execute("""
    SELECT id, symbol, price, quantity, event_time_ms, ingest_time_ms,
           (ingest_time_ms - event_time_ms) AS latency_ms, is_buyer_maker, trade_id
    FROM market_events WHERE symbol='BTCUSDT'
    ORDER BY event_time_ms DESC LIMIT 3
""").fetchall()
for r in rows:
    print(r)
