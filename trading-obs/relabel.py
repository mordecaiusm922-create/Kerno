import sqlite3

conn = sqlite3.connect("kerno.db")

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price, volatility_1m
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Relabeleando {len(rows)} filas...")
updated = 0

for fid, symbol, ts, entry_price, vol in rows:
    p30 = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ?
        ORDER BY event_time_ms ASC LIMIT 1
    """, (symbol, ts + 30000)).fetchone()

    p60 = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ?
        ORDER BY event_time_ms ASC LIMIT 1
    """, (symbol, ts + 60000)).fetchone()

    if not p30 or not p60:
        continue

    ret30 = (p30[0] - entry_price) / entry_price * 100
    ret60 = (p60[0] - entry_price) / entry_price * 100

    # Option B: movimiento normalizado por volatilidad
    k = vol if vol and vol > 0 else 0.001
    label30 = 1 if ret30 < -(k * 0.5) else 0
    label60 = 1 if ret60 < -(k * 0.5) else 0

    conn.execute("""
        UPDATE feature_store
        SET outcome_10s=?, outcome_30s=?
        WHERE id=?
    """, (str(label30), str(label60), fid))

    updated += 1
    if updated % 10000 == 0:
        conn.commit()
        print(f"  {updated} relabeleados...")

conn.commit()
print(f"OK: {updated} filas relabeleadas")

total = conn.execute("SELECT COUNT(*) FROM feature_store WHERE outcome_10s IS NOT NULL").fetchone()[0]
wins  = conn.execute("SELECT COUNT(*) FROM feature_store WHERE outcome_10s='1'").fetchone()[0]
print(f"Nueva distribución: {wins}/{total} = {round(wins/total*100,1)}% reversal")
conn.close()