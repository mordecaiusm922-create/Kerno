import sys, sqlite3, os, math, statistics
sys.path.insert(0, ".")

DB_PATH = os.getenv("DB_PATH", "kerno.db")

def build_candles(symbol, interval_seconds=1, limit=50000):
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

def analyze(symbol, candles):
    if len(candles) < 20:
        print(symbol, "-> pocos datos")
        return {}

    moves = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles if c["open"]>0]
    moves_signed = [(c["close"]-c["open"])/c["open"]*100 for c in candles if c["open"]>0]

    # Spikes: P99
    threshold = sorted(moves)[int(len(moves)*0.99)]

    spike_candles = [(i,c) for i,c in enumerate(candles) if abs(c["close"]-c["open"])/c["open"]*100 >= threshold]

    reversals = []
    continuations = []
    for idx, c in spike_candles:
        if idx+10 >= len(candles): continue
        body  = (c["close"]-c["open"])/c["open"]*100
        after = (candles[idx+10]["close"]-c["close"])/c["close"]*100
        if body > 0 and after < -threshold*0.3: reversals.append(abs(after))
        elif body < 0 and after > threshold*0.3: reversals.append(abs(after))
        elif body > 0 and after > threshold*0.3: continuations.append(abs(after))
        elif body < 0 and after < -threshold*0.3: continuations.append(abs(after))

    flat_pct   = sum(1 for m in moves if m < 0.002) / len(moves) * 100
    spike_pct  = sum(1 for m in moves if m >= threshold) / len(moves) * 100
    rev_rate   = len(reversals)/(len(reversals)+len(continuations))*100 if (reversals or continuations) else 0
    avg_move   = statistics.mean(moves)
    std_move   = statistics.stdev(moves)
    avg_vol    = statistics.mean(c["volume"] for c in candles)

    return {
        "symbol":      symbol,
        "candles":     len(candles),
        "flat_pct":    round(flat_pct, 1),
        "spike_pct":   round(spike_pct, 1),
        "spike_thresh":round(threshold, 4),
        "rev_rate":    round(rev_rate, 1),
        "cont_rate":   round(100-rev_rate, 1),
        "avg_move":    round(avg_move, 5),
        "std_move":    round(std_move, 5),
        "avg_volume":  round(avg_vol, 4),
        "total_spikes":len(spike_candles),
        "reversals":   len(reversals),
        "continuations":len(continuations),
    }

print("Construyendo velas...")
btc = build_candles("BTCUSDT")
eth = build_candles("ETHUSDT")

rb = analyze("BTCUSDT", btc)
re = analyze("ETHUSDT", eth)

print("")
print("=== BTC vs ETH — COMPARACION DE MICROESTRUCTURA ===")
print("")
print(f"{'Metrica':<25} {'BTC':>12} {'ETH':>12} {'diferencia':>12}")
print("-"*62)

metricas = [
    ("Velas 1s",       "candles",       ""),
    ("Flat %",         "flat_pct",      "%"),
    ("Spike threshold","spike_thresh",  "%"),
    ("Spike %",        "spike_pct",     "%"),
    ("Total spikes",   "total_spikes",  ""),
    ("Reversal rate",  "rev_rate",      "%"),
    ("Continuation",   "cont_rate",     "%"),
    ("Avg move/vela",  "avg_move",      "%"),
    ("Std move",       "std_move",      "%"),
    ("Avg volume/s",   "avg_volume",    ""),
]

for nombre, key, unit in metricas:
    bv = rb.get(key, "-")
    ev = re.get(key, "-")
    if isinstance(bv, float) and isinstance(ev, float):
        diff = round(ev - bv, 5)
        print(f"  {nombre:<23} {str(bv)+unit:>12} {str(ev)+unit:>12} {str(diff)+unit:>12}")
    else:
        print(f"  {nombre:<23} {str(bv):>12} {str(ev):>12} {'—':>12}")

print("")
print("=== INSIGHT ===")
if rb.get("rev_rate",0) != re.get("rev_rate",0):
    diff_rev = abs(rb.get("rev_rate",0) - re.get("rev_rate",0))
    leader   = "ETH" if re.get("rev_rate",0) > rb.get("rev_rate",0) else "BTC"
    print(f"  {leader} revierte {diff_rev}% mas frecuente post-spike")
if rb.get("flat_pct",0) != re.get("flat_pct",0):
    more_flat = "BTC" if rb.get("flat_pct",0) > re.get("flat_pct",0) else "ETH"
    print(f"  {more_flat} tiene mas velas planas — menos liquidez o mas eficiente")
if rb.get("avg_move",0) and re.get("avg_move",0):
    ratio = round(re.get("avg_move",0)/rb.get("avg_move",1), 2)
    print(f"  ETH mueve {ratio}x mas que BTC por vela en promedio")
