import sqlite3, os, statistics

DB_PATH = "kerno.db"

EDGE_MAP = {
    "BTCUSDT": {
        "MEDIUM":  ("REVERSAL",      0.66, 0.34),
        "LARGE":   ("CONTINUATION",  0.28, 0.72),
    },
    "ETHUSDT": {
        "SMALL":   ("REVERSAL",      0.61, 0.39),
        "LARGE":   ("CONTINUATION",  0.40, 0.60),
        "EXTREME": ("CONTINUATION",  0.25, 0.75),
    },
}

def get_percentiles(symbol, n=10000):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT price, quantity, event_time_ms
        FROM market_events
        WHERE symbol=? AND event_type='trade'
        ORDER BY event_time_ms DESC LIMIT ?
    """, (symbol, n)).fetchall()
    conn.close()
    candles = {}
    for price, qty, ts in rows:
        b = (ts // 1000) * 1000
        if b not in candles:
            candles[b] = {"open": price, "high": price, "low": price, "close": price}
        c = candles[b]
        c["high"]  = max(c["high"], price)
        c["low"]   = min(c["low"],  price)
        c["close"] = price
    moves = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles.values() if c["open"]>0]
    if len(moves) < 20:
        return None
    s = sorted(moves)
    return {
        "p75": s[int(len(s)*0.75)],
        "p90": s[int(len(s)*0.90)],
        "p99": s[int(len(s)*0.99)],
    }

def classify_event(symbol, price_change_pct, percentiles):
    m = abs(price_change_pct)
    p = percentiles
    if m < p["p75"]:   bucket = "SMALL"
    elif m < p["p90"]: bucket = "MEDIUM"
    elif m < p["p99"]: bucket = "LARGE"
    else:              bucket = "EXTREME"

    edges = EDGE_MAP.get(symbol, {})
    if bucket in edges:
        label, prob_rev, prob_cont = edges[bucket]
        return {
            "bucket":        bucket,
            "classification": f"{bucket}_{label}",
            "prob_reversal":  prob_rev,
            "prob_continuation": prob_cont,
            "signal":        "REV_EDGE" if prob_rev > 0.60 else "CONT_EDGE" if prob_cont > 0.60 else "NO_EDGE",
        }
    return {
        "bucket":        bucket,
        "classification": f"{bucket}_NOISE",
        "prob_reversal":  0.50,
        "prob_continuation": 0.50,
        "signal":        "NO_EDGE",
    }

# Test
for sym in ["BTCUSDT", "ETHUSDT"]:
    pct = get_percentiles(sym)
    if pct:
        result = classify_event(sym, 0.015, pct)
        print(f"{sym}: {result}")
    else:
        print(f"{sym}: pocos datos")
