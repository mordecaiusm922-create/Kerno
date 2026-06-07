content = open("api.py", encoding="utf-8").read()

idx = content.find("def _get_percentiles(symbol):")
end = content.find("\ndef ", idx + 10)

new_func = """def _get_percentiles(symbol):
    import time as _time
    since_ms = int((_time.time() - 7200) * 1000)
    conn = get_conn()
    rows = conn.execute(
        "SELECT price, event_time_ms FROM market_events "
        "WHERE symbol=? AND event_time_ms >= ? "
        "ORDER BY event_time_ms ASC",
        (symbol, since_ms)
    ).fetchall()
    conn.close()
    if len(rows) < 100:
        return None
    candles = {}
    for price, ts in rows:
        b = (ts // 1000) * 1000
        if b not in candles:
            candles[b] = {"open": price, "close": price}
        candles[b]["close"] = price
    moves = [abs(c["close"]-c["open"])/c["open"]*100
             for c in candles.values() if c["open"] > 0]
    if len(moves) < 20:
        return None
    s = sorted(moves)
    mean = sum(moves) / len(moves)
    std = (sum((m - mean)**2 for m in moves) / len(moves))**0.5
    return {
        "p75": s[int(len(s)*0.75)],
        "p90": s[int(len(s)*0.90)],
        "p99": s[int(len(s)*0.99)],
        "mean": mean, "std": std, "n": len(moves)
    }
"""

if idx == -1:
    print("ERROR: funcion no encontrada")
else:
    content = content[:idx] + new_func + content[end:]
    open("api.py", "w", encoding="utf-8").write(content)
    print("OK: percentiles rolling 2h activos")