content = open("api.py", encoding="utf-8").read()

# Agregar funcion de features microstructure antes de _classify
new_funcs = '''
def _spread_features(symbol, current_ms):
    """Roll estimator + flip rate + micro range sin L2 data."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT price FROM market_events "
        "WHERE symbol=? AND event_time_ms >= ? "
        "ORDER BY event_time_ms ASC LIMIT 200",
        (symbol, current_ms - 5000)
    ).fetchall()
    conn.close()
    prices = [r[0] for r in rows]
    if len(prices) < 10:
        return {"roll_spread": 0.0, "flip_rate": 0.0, "micro_range": 0.0}

    # 1 - Roll estimator
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    if len(deltas) >= 2:
        pairs = [(deltas[i], deltas[i-1]) for i in range(1, len(deltas))]
        mean_a = sum(p[0] for p in pairs) / len(pairs)
        mean_b = sum(p[1] for p in pairs) / len(pairs)
        cov = sum((p[0]-mean_a)*(p[1]-mean_b) for p in pairs) / len(pairs)
        roll = round(2 * (-cov)**0.5, 6) if cov < 0 else 0.0
    else:
        roll = 0.0

    # 2 - Flip rate (bid/ask bounce)
    signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in deltas]
    flips = sum(1 for i in range(1, len(signs))
                if signs[i] != 0 and signs[i-1] != 0 and signs[i] != signs[i-1])
    flip_rate = round(flips / max(len(signs)-1, 1), 4)

    # 3 - Micro range 1s
    micro_range = round(max(prices) - min(prices), 6) if prices else 0.0

    return {
        "roll_spread": roll,
        "flip_rate": flip_rate,
        "micro_range": micro_range,
    }

'''

# Insertar antes de _classify
idx = content.find("def _classify(symbol, change_pct):")
if idx == -1:
    print("ERROR: _classify no encontrado")
else:
    content = content[:idx] + new_funcs + content[idx:]
    open("api.py", "w", encoding="utf-8").write(content)
    print("OK: _spread_features agregado")