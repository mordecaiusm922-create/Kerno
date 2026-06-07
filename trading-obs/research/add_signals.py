content = open("api.py", encoding="utf-8").read()

endpoint = """

# signals endpoint
@app.get("/signals")
def get_signals(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit:  Annotated[int, Query(ge=1, le=100)] = 10,
    min_confidence: Annotated[float, Query(ge=0.0, le=1.0)] = 0.7,
):
    conn = get_conn()
    rows = conn.execute(
        "SELECT price, event_time_ms, spike_pct, zscore, bucket, signal, confidence "
        "FROM feature_store "
        "WHERE symbol=? AND confidence>=? AND signal NOT IN ('NO_DATA','PENDING') "
        "ORDER BY event_time_ms DESC LIMIT ?",
        (symbol.upper(), min_confidence, limit)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        score = r["confidence"]
        conf_label = "HIGH" if score >= 0.8 else ("MEDIUM" if score >= 0.6 else "LOW")
        sig = r["signal"]
        bkt = r["bucket"]
        if "CONT" in sig:
            interp = f"{bkt} spike with directional momentum. Continuation likely ({score:.0%})."
        elif "REV" in sig:
            interp = f"{bkt} spike with absorption pattern. Reversal likely ({score:.0%})."
        else:
            interp = f"{bkt} spike detected. Insufficient confidence."
        out.append({
            "symbol": symbol.upper(),
            "price": r["price"],
            "event_time_ms": r["event_time_ms"],
            "signal": sig,
            "spike_type": bkt,
            "score": round(score, 3),
            "confidence": conf_label,
            "interpretation": interp,
            "action": "FILTER_IN" if score >= min_confidence else "FILTER_OUT",
        })
    return out
"""

if "/signals" in content:
    print("Endpoint ya existe")
else:
    open("api.py", "w", encoding="utf-8").write(content + endpoint)
    print("OK: /signals agregado")
