import sys, sqlite3, os, math, statistics
sys.path.insert(0, ".")

DB_PATH = os.getenv("DB_PATH", "kerno.db")

def build_candles(symbol="BTCUSDT", interval_seconds=1, limit=50000):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT price, quantity, event_time_ms
        FROM market_events
        WHERE symbol=? AND event_type='trade'
        ORDER BY event_time_ms ASC LIMIT ?
    """, (symbol, limit)).fetchall()
    conn.close()
    candles = {}
    for r in rows:
        b = (r["event_time_ms"] // (interval_seconds*1000)) * (interval_seconds*1000)
        if b not in candles:
            candles[b] = {"open":r["price"],"high":r["price"],"low":r["price"],"close":r["price"],"volume":0,"trades":0,"time_ms":b}
        c = candles[b]
        c["high"]   = max(c["high"], r["price"])
        c["low"]    = min(c["low"],  r["price"])
        c["close"]  = r["price"]
        c["volume"] += r["quantity"]
        c["trades"] += 1
    return [v for k,v in sorted(candles.items())]

def classify_candle(candles, idx, lookahead=10):
    if idx+lookahead >= len(candles): return None
    c     = candles[idx]
    body  = (c["close"]-c["open"])/c["open"]*100
    after = (candles[idx+lookahead]["close"]-c["close"])/c["close"]*100
    if abs(body) < 0.005: return "FLAT"
    if body > 0 and after > 0.003:  return "MOMENTUM_UP"
    if body < 0 and after < -0.003: return "MOMENTUM_DOWN"
    if body > 0 and after < -0.003: return "REVERSAL_DOWN"
    if body < 0 and after > 0.003:  return "REVERSAL_UP"
    return "NOISE"

candles = build_candles(interval_seconds=1)
print("Velas:", len(candles))

counts = {}
wins   = {}
pnls   = {}

for i in range(len(candles)-20):
    tipo = classify_candle(candles, i, lookahead=10)
    if not tipo: continue
    counts[tipo] = counts.get(tipo, 0) + 1

    # Simula trade segun tipo
    entry = candles[i+1]["open"]
    exit_p = candles[i+10]["close"]
    if "UP" in tipo:
        pnl = (exit_p - entry) / entry * 100 - 0.02
    elif "DOWN" in tipo:
        pnl = (entry - exit_p) / entry * 100 - 0.02
    else:
        continue

    if tipo not in pnls: pnls[tipo] = []
    pnls[tipo].append(pnl)
    if tipo not in wins: wins[tipo] = []
    wins[tipo].append(1 if pnl > 0 else 0)

print("")
print("=== CLASIFICADOR DE VELAS ===")
print(f"{'Tipo':<20} {'Count':>6} {'WR%':>7} {'PnL%':>9} {'Avg':>8}")
print("-"*55)
for tipo, count in sorted(counts.items(), key=lambda x: -x[1]):
    if tipo in pnls and pnls[tipo]:
        wr  = round(sum(wins[tipo])/len(wins[tipo])*100, 1)
        pnl = round(sum(pnls[tipo]), 4)
        avg = round(sum(pnls[tipo])/len(pnls[tipo]), 4)
        print(f"  {tipo:<18} {count:>6} {wr:>6}% {pnl:>+9} {avg:>+8}%")
    else:
        print(f"  {tipo:<18} {count:>6}   —       —        —")
