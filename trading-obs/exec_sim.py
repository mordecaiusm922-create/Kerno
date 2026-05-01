import sys, sqlite3, os
sys.path.insert(0, ".")
import backtester as bt

DB_PATH = "kerno.db"
FEE = 0.001
SLIPPAGE = 0.0005
LOOKAHEAD = 10

def build_candles(symbol, interval_seconds=1, limit=50000):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT price, quantity, event_time_ms
        FROM market_events WHERE symbol=? AND event_type='trade'
        ORDER BY event_time_ms ASC LIMIT ?
    """, (symbol, limit)).fetchall()
    conn.close()
    candles = {}
    for r in rows:
        b = (r["event_time_ms"] // (interval_seconds*1000)) * (interval_seconds*1000)
        if b not in candles:
            candles[b] = {"open":r["price"],"high":r["price"],"low":r["price"],"close":r["price"],"volume":0,"time_ms":b}
        c = candles[b]
        c["high"]   = max(c["high"], r["price"])
        c["low"]    = min(c["low"],  r["price"])
        c["close"]  = r["price"]
        c["volume"] += r["quantity"]
    return [v for k,v in sorted(candles.items())]

def percentile(data, p):
    s = sorted(data)
    return s[min(int(len(s)*p/100), len(s)-1)]

def simulate(symbol, candles):
    moves = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles if c["open"]>0]
    if len(moves) < 50: return

    p75 = percentile(moves, 75)
    p90 = percentile(moves, 90)
    p99 = percentile(moves, 99)

    edge_map = {
        "BTCUSDT": {"MEDIUM": ("REV", 0.66), "LARGE": ("CONT", 0.72)},
        "ETHUSDT": {"SMALL":  ("REV", 0.61), "LARGE": ("CONT", 0.60), "EXTREME": ("CONT", 0.75)},
    }
    edges = edge_map.get(symbol, {})

    trades = []
    for i, c in enumerate(candles):
        if i+LOOKAHEAD >= len(candles) or c["open"] <= 0: continue
        body  = (c["close"]-c["open"])/c["open"]*100
        move  = abs(body)

        if move < p75:    bucket = "SMALL"
        elif move < p90:  bucket = "MEDIUM"
        elif move < p99:  bucket = "LARGE"
        else:             bucket = "EXTREME"

        if bucket not in edges: continue
        direction, prob = edges[bucket]
        if prob < 0.60: continue

        entry_dir = ("long" if body > 0 else "short") if direction == "CONT" else ("short" if body > 0 else "long")
        entry = c["close"] * (1 + SLIPPAGE if entry_dir == "long" else 1 - SLIPPAGE)
        exit_p = candles[i+LOOKAHEAD]["close"] * (1 - SLIPPAGE if entry_dir == "long" else 1 + SLIPPAGE)

        raw = (exit_p-entry)/entry*100 if entry_dir == "long" else (entry-exit_p)/entry*100
        net = raw - 2*FEE*100
        trades.append({"bucket":bucket, "net":net, "win":net>0})

    if not trades:
        print(f"\n{symbol}: sin trades"); return

    wins  = sum(1 for t in trades if t["win"])
    total = sum(t["net"] for t in trades)
    wr    = round(wins/len(trades)*100, 1)
    avg   = round(total/len(trades), 4)

    cum, peak, dd = 0, 0, 0
    for t in trades:
        cum += t["net"]
        peak = max(peak, cum)
        dd   = max(dd, peak-cum)

    print(f"\n=== EXECUTION SIMULATOR — {symbol} ===")
    print(f"Fee: {FEE*100}% | Slippage: {SLIPPAGE*100}% cada lado")
    print(f"Trades   : {len(trades)}")
    print(f"Win rate : {wr}%")
    print(f"Total PnL: {round(total,4)}%")
    print(f"Avg/trade: {avg}%")
    print(f"Max DD   : -{round(dd,4)}%")
    print("")
    if total > 0 and wr > 50:
        print("VEREDICTO: SOBREVIVE COSTOS — edge real potencial")
    elif total > 0:
        print("VEREDICTO: PnL positivo — win rate bajo, ajustar")
    else:
        print("VEREDICTO: NO sobrevive costos — fees matan el edge")

btc = build_candles("BTCUSDT")
eth = build_candles("ETHUSDT")
print(f"BTC: {len(btc)} velas | ETH: {len(eth)} velas")
simulate("BTCUSDT", btc)
simulate("ETHUSDT", eth)
