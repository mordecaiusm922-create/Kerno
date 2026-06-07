import sys, sqlite3, os
sys.path.insert(0, ".")

DB_PATH = os.getenv("DB_PATH", "kerno.db")

def build_candles(symbol="BTCUSDT", interval_seconds=1, limit=50000):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT price, quantity, event_time_ms
        FROM market_events
        WHERE symbol = ? AND event_type = 'trade'
        ORDER BY event_time_ms ASC
        LIMIT ?
    """, (symbol, limit)).fetchall()
    conn.close()

    candles = {}
    for r in rows:
        bucket = (r["event_time_ms"] // (interval_seconds * 1000)) * (interval_seconds * 1000)
        if bucket not in candles:
            candles[bucket] = {"open":r["price"],"high":r["price"],"low":r["price"],"close":r["price"],"volume":0,"trades":0}
        c = candles[bucket]
        c["high"]   = max(c["high"], r["price"])
        c["low"]    = min(c["low"],  r["price"])
        c["close"]  = r["price"]
        c["volume"] += r["quantity"]
        c["trades"] += 1

    result = [{"time_ms":k,"open":v["open"],"high":v["high"],"low":v["low"],"close":v["close"],"volume":v["volume"],"trades":v["trades"]} for k,v in sorted(candles.items())]
    return result

candles = build_candles(interval_seconds=1)
moves   = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles if c["open"]>0]
moves.sort(reverse=True)

print("Velas de 1s generadas:", len(candles))
print("")
print("Top 10 movimientos por vela:")
for i,m in enumerate(moves[:10]):
    print("  "+str(i+1)+". "+str(round(m,4))+"% ($"+str(round(m/100*77000,2))+")")

import statistics
print("")
print("Media  :", round(statistics.mean(moves),4), "%")
print("Stdev  :", round(statistics.stdev(moves),4), "%")
print("P95    :", round(sorted(moves)[int(len(moves)*0.95)],4), "%")
print("P99    :", round(sorted(moves)[int(len(moves)*0.99)],4), "%")
