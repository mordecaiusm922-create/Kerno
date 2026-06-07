import sys, sqlite3, os, math
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

def percentile(data, p):
    s = sorted(data)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s)-1)]

def spike_intelligence(symbol, candles, lookahead=10):
    moves = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles if c["open"]>0 and c["close"]>0]
    if len(moves) < 50:
        print(symbol, "-> pocos datos"); return

    p50  = percentile(moves, 50)
    p75  = percentile(moves, 75)
    p90  = percentile(moves, 90)
    p99  = percentile(moves, 99)

    buckets = {
        "SMALL  (p50-p75)":  (p50,  p75),
        "MEDIUM (p75-p90)":  (p75,  p90),
        "LARGE  (p90-p99)":  (p90,  p99),
        "EXTREME(p99+)":     (p99,  999),
    }

    print(f"\n=== SPIKE INTELLIGENCE LAYER — {symbol} ===")
    print(f"Percentiles: p50={p50:.5f}% p75={p75:.5f}% p90={p90:.5f}% p99={p99:.5f}%")
    print("")
    print(f"{'Bucket':<24} {'N':>5} {'Rev%':>7} {'Cont%':>7} {'Avg_after':>10} {'Edge':>10}")
    print("-"*65)

    for bucket_name, (lo, hi) in buckets.items():
        spike_idxs = [
            i for i,c in enumerate(candles)
            if c["open"]>0 and lo <= abs(c["close"]-c["open"])/c["open"]*100 < hi
            and i+lookahead < len(candles)
        ]

        reversals = []
        continuations = []
        afters = []

        for idx in spike_idxs:
            body  = (candles[idx]["close"] - candles[idx]["open"]) / candles[idx]["open"] * 100
            after = (candles[idx+lookahead]["close"] - candles[idx]["close"]) / candles[idx]["close"] * 100
            afters.append(after)

            if body > 0 and after < -p50*0.5:  reversals.append(after)
            elif body < 0 and after > p50*0.5:  reversals.append(after)
            elif body > 0 and after > p50*0.5:  continuations.append(after)
            elif body < 0 and after < -p50*0.5: continuations.append(after)

        n = len(spike_idxs)
        if n == 0:
            print(f"  {bucket_name:<22} {'0':>5}")
            continue

        total_dir = len(reversals) + len(continuations)
        rev_pct  = round(len(reversals)/total_dir*100, 1) if total_dir else 0
        cont_pct = round(len(continuations)/total_dir*100, 1) if total_dir else 0
        avg_after = round(sum(afters)/len(afters), 5) if afters else 0

        # Edge: diferencia significativa de rev vs cont
        if total_dir >= 5:
            edge = "REV_EDGE" if rev_pct > 60 else "CONT_EDGE" if cont_pct > 60 else "NO_EDGE"
        else:
            edge = "INSUF"

        print(f"  {bucket_name:<22} {n:>5} {rev_pct:>6}% {cont_pct:>6}% {avg_after:>+10.5f}% {edge:>10}")

        # Output JSON del spike intelligence
        if edge != "NO_EDGE" and edge != "INSUF":
            prob_rev  = round(rev_pct/100, 2)
            prob_cont = round(cont_pct/100, 2)
            print(f"    -> JSON: {{\"asset\":\"{symbol}\",\"bucket\":\"{bucket_name.strip()}\",\"prob_reversal\":{prob_rev},\"prob_continuation\":{prob_cont}}}")

    print("")

btc = build_candles("BTCUSDT")
eth = build_candles("ETHUSDT")
spike_intelligence("BTCUSDT", btc)
spike_intelligence("ETHUSDT", eth)
