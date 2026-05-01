import re

api_path = "api.py"
content = open(api_path, encoding="utf-8").read()

new_code = '''
# ── Spike Intelligence Layer ─────────────────────────────
import sqlite3 as _sqlite3, os as _os

_EDGE_MAP = {
    "BTCUSDT": {
        "MEDIUM":  ("REVERSAL",     0.66, 0.34),
        "LARGE":   ("CONTINUATION", 0.28, 0.72),
    },
    "ETHUSDT": {
        "SMALL":   ("REVERSAL",     0.61, 0.39),
        "LARGE":   ("CONTINUATION", 0.40, 0.60),
        "EXTREME": ("CONTINUATION", 0.25, 0.75),
    },
}
_pct_cache = {}

def _get_percentiles(symbol):
    conn = _sqlite3.connect("kerno.db")
    rows = conn.execute("""
        SELECT price, event_time_ms FROM market_events
        WHERE symbol=? AND event_type=\'trade\'
        ORDER BY event_time_ms DESC LIMIT 10000
    """, (symbol,)).fetchall()
    conn.close()
    candles = {}
    for price, ts in rows:
        b = (ts // 1000) * 1000
        if b not in candles:
            candles[b] = {"open": price, "close": price}
        candles[b]["close"] = price
    moves = [abs(c["close"]-c["open"])/c["open"]*100 for c in candles.values() if c["open"]>0]
    if len(moves) < 20:
        return None
    s = sorted(moves)
    return {"p75": s[int(len(s)*0.75)], "p90": s[int(len(s)*0.90)], "p99": s[int(len(s)*0.99)]}

def _classify(symbol, change_pct):
    global _pct_cache
    if symbol not in _pct_cache:
        _pct_cache[symbol] = _get_percentiles(symbol)
    p = _pct_cache.get(symbol)
    if not p:
        return {"signal": "NO_DATA", "classification": "UNKNOWN", "prob_reversal": 0.5, "prob_continuation": 0.5}
    m = abs(change_pct)
    if m < p["p75"]:   bucket = "SMALL"
    elif m < p["p90"]: bucket = "MEDIUM"
    elif m < p["p99"]: bucket = "LARGE"
    else:              bucket = "EXTREME"
    edges = _EDGE_MAP.get(symbol, {})
    if bucket in edges:
        label, prob_rev, prob_cont = edges[bucket]
        signal = "REV_EDGE" if prob_rev > 0.60 else "CONT_EDGE" if prob_cont > 0.60 else "NO_EDGE"
        return {"bucket": bucket, "classification": f"{bucket}_{label}", "prob_reversal": prob_rev, "prob_continuation": prob_cont, "signal": signal}
    return {"bucket": bucket, "classification": f"{bucket}_NOISE", "prob_reversal": 0.5, "prob_continuation": 0.5, "signal": "NO_EDGE"}
'''

# Insertar despues de los imports
insert_after = "app = FastAPI("
idx = content.find(insert_after)
if idx == -1:
    insert_after = "from fastapi"
    idx = content.find(insert_after)

end_of_line = content.find("\\n", idx) + 1
content = content[:end_of_line] + new_code + content[end_of_line:]

# Parchear el endpoint /events para agregar clasificacion
old_return = "return rows"
new_return = """
    # Enriquecer con Spike Intelligence
    enriched = []
    prev_price = None
    for row in rows:
        d = dict(row)
        if prev_price and prev_price > 0:
            change_pct = (d["price"] - prev_price) / prev_price * 100
            d["spike_pct"] = round(change_pct, 6)
            d["intelligence"] = _classify(d["symbol"], change_pct)
        else:
            d["spike_pct"] = 0.0
            d["intelligence"] = {"signal": "NO_DATA"}
        prev_price = d["price"]
        enriched.append(d)
    return enriched"""

if old_return in content:
    content = content.replace(old_return, new_return, 1)
    print("OK: /events enriquecido con Spike Intelligence")
else:
    print("WARN: no encontre 'return rows' — revisa api.py manualmente")

open(api_path, "w", encoding="utf-8").write(content)
print("api.py actualizado — uvicorn se recarga solo")
