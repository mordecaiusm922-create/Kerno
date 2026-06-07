import re

content = open('api.py', encoding='utf-8').read()

# 1) Agregar imports necesarios al inicio
old_imports = 'from fastapi.responses import HTMLResponse'
new_imports = '''from fastapi.responses import HTMLResponse
import threading, time'''
content = content.replace(old_imports, new_imports, 1)

# 2) Agregar _streak_cache junto a _pct_cache
content = content.replace(
    '_pct_cache = {}',
    '_pct_cache  = {}\n_streak_cache = {}  # {symbol: {"signal": str, "count": int}}'
, 1)

# 3) Reemplazar _classify completo con version confidence
old_classify = 'def _classify(symbol, change_pct):'
idx = content.find(old_classify)
# encontrar fin de funcion (proximo def al mismo nivel)
end_idx = content.find('\ndef ', idx + 10)
old_func = content[idx:end_idx]

new_func = '''def _classify(symbol, change_pct):
    global _pct_cache, _streak_cache
    BASE_CONF = {"SMALL": 0.35, "MEDIUM": 0.62, "LARGE": 0.80, "EXTREME": 0.92}
    if symbol not in _pct_cache:
        _pct_cache[symbol] = _get_percentiles(symbol)
    p = _pct_cache.get(symbol)
    if not p:
        return {"signal": "NO_DATA", "classification": "UNKNOWN",
                "prob_reversal": 0.5, "prob_continuation": 0.5, "confidence": 0.0}
    m = abs(change_pct)
    if   m < p["p75"]:  bucket = "SMALL"
    elif m < p["p90"]:  bucket = "MEDIUM"
    elif m < p["p99"]:  bucket = "LARGE"
    else:               bucket = "EXTREME"
    edges = _EDGE_MAP.get(symbol, {})
    if bucket in edges:
        label, prob_rev, prob_cont = edges[bucket]
        signal = label
    else:
        label, prob_rev, prob_cont = "NO_EDGE", 0.5, 0.5
        signal = "NO_EDGE"
    # Streak tracking
    sc = _streak_cache.get(symbol, {"signal": None, "count": 0})
    if sc["signal"] == signal:
        sc["count"] = min(sc["count"] + 1, 10)
    else:
        sc = {"signal": signal, "count": 1}
    _streak_cache[symbol] = sc
    streak_bonus = min((sc["count"] - 1) * 0.04, 0.15)
    base = BASE_CONF.get(bucket, 0.35)
    confidence = round(min(base + streak_bonus, 1.0), 3)
    return {
        "signal": signal,
        "classification": label + "_" + bucket if signal != "NO_EDGE" else "NOISE_" + bucket,
        "bucket": bucket,
        "prob_reversal": prob_rev,
        "prob_continuation": prob_cont,
        "confidence": confidence,
    }

'''

content = content[:idx] + new_func + content[end_idx+1:]

# 4) Crear tabla signal_outcomes en startup
old_startup = '[DB] Kerno inicializado'
idx2 = content.find(old_startup)
line_end = content.find('\n', idx2)
insert = '''
    # Signal outcomes table
    conn2 = get_conn()
    conn2.execute("""
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, signal TEXT, bucket TEXT,
            confidence REAL, price_entry REAL,
            event_time_ms INTEGER,
            price_10s REAL, price_30s REAL,
            result_10s TEXT DEFAULT 'PENDING',
            result_30s TEXT DEFAULT 'PENDING'
        )
    """)
    conn2.commit()
    conn2.close()'''
content = content[:line_end] + insert + content[line_end:]

# 5) Agregar endpoints /signals y /accuracy antes del /dashboard
old_dash = '@app.get("/dashboard"'
new_endpoints = '''
@app.get("/signals")
def get_signals(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    min_confidence: Annotated[float, Query()] = 0.60,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.id, e.symbol, e.price, e.quantity,
               e.event_time_ms, e.ingest_time_ms,
               (e.ingest_time_ms - e.event_time_ms) AS latency_ms,
               e.is_buyer_maker, e.trade_id
        FROM market_events e
        WHERE e.symbol = ?
        ORDER BY e.event_time_ms DESC LIMIT 500
    """, (symbol.upper(),)).fetchall()
    conn.close()
    results = []
    prev_price = None
    for r in rows:
        d = dict(r)
        if prev_price and prev_price > 0:
            change_pct = (d["price"] - prev_price) / prev_price * 100
            intel = _classify(d["symbol"], change_pct)
            d["spike_pct"] = round(change_pct, 6)
            d["intelligence"] = intel
        else:
            d["spike_pct"] = 0.0
            d["intelligence"] = {"signal": "NO_DATA", "confidence": 0.0}
        prev_price = d["price"]
        if d["intelligence"].get("confidence", 0) >= min_confidence and \
           d["intelligence"].get("signal") not in ("NO_DATA", "NO_EDGE"):
            results.append(d)
        if len(results) >= limit:
            break
    return results

@app.get("/accuracy")
def get_accuracy(symbol: Annotated[str, Query()] = "BTCUSDT"):
    conn = get_conn()
    rows = conn.execute("""
        SELECT signal, result_10s, result_30s, confidence
        FROM signal_outcomes WHERE symbol=?
        ORDER BY event_time_ms DESC LIMIT 500
    """, (symbol.upper(),)).fetchall()
    conn.close()
    total = len(rows)
    if total == 0:
        return {"total": 0, "win_rate_10s": None, "win_rate_30s": None}
    wins_10 = sum(1 for r in rows if r[1] == "WIN")
    wins_30 = sum(1 for r in rows if r[2] == "WIN")
    validated = sum(1 for r in rows if r[1] != "PENDING")
    return {
        "total": total,
        "validated": validated,
        "win_rate_10s": round(wins_10 / validated * 100, 1) if validated else None,
        "win_rate_30s": round(wins_30 / validated * 100, 1) if validated else None,
        "avg_confidence": round(sum(r[3] for r in rows) / total, 3),
    }

''' + old_dash
content = content.replace(old_dash, new_endpoints, 1)

open('api.py', 'w', encoding='utf-8').write(content)
print('OK: api.py parcheado — confidence + /signals + /accuracy')
