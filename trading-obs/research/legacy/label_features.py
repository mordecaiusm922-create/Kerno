import sqlite3

conn = sqlite3.connect("kerno.db")

# Verificar columnas reales
cols = [r[1] for r in conn.execute("PRAGMA table_info(feature_store)").fetchall()]
print("Columnas:", cols)

rows = conn.execute("""
    SELECT id, symbol, event_time_ms, price
    FROM feature_store
    ORDER BY event_time_ms ASC
""").fetchall()

print(f"Filas a labelear: {len(rows)}")
updated = 0

for i, (fid, symbol, ts, entry_price) in enumerate(rows):
    p10 = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ?
        ORDER BY event_time_ms ASC LIMIT 1
    """, (symbol, ts + 10000)).fetchone()

    p30 = conn.execute("""
        SELECT price FROM market_events
        WHERE symbol=? AND event_time_ms >= ?
        ORDER BY event_time_ms ASC LIMIT 1
    """, (symbol, ts + 30000)).fetchone()

    if not p10 or not p30:
        continue

    move10 = (p10[0] - entry_price) / entry_price * 100
    move30 = (p30[0] - entry_price) / entry_price * 100

    label10 = 1 if move10 < -0.001 else 0
    label30 = 1 if move30 < -0.001 else 0

    conn.execute("""
        UPDATE feature_store
        SET outcome_10s=?, outcome_30s=?
        WHERE id=?
    """, (str(label10), str(label30), fid))

    updated += 1
    if updated % 10000 == 0:
        conn.commit()
        print(f"  {updated} labels asignados...")

conn.commit()
print(f"OK: {updated} filas labeleadas")

total = conn.execute("SELECT COUNT(*) FROM feature_store WHERE outcome_10s IS NOT NULL").fetchone()[0]
wins = conn.execute("SELECT COUNT(*) FROM feature_store WHERE outcome_10s='1'").fetchone()[0]
print(f"Label distribution: {wins}/{total} = {round(wins/total*100,1)}% reversal")
conn.close()