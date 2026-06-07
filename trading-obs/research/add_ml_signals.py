content = open("api.py", encoding="utf-8").read()

patch = """

# Kerno ML Model
import pickle as _pickle
import numpy as _np

_KERNO_MODEL = None
_KERNO_SCALER = None
_KERNO_FEATURES = None

def _load_model():
    global _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES
    if _KERNO_MODEL is None:
        try:
            with open("kerno_model.pkl", "rb") as f:
                data = _pickle.load(f)
            _KERNO_MODEL   = data["model"]
            _KERNO_SCALER  = data["scaler"]
            _KERNO_FEATURES = data["features"]
        except Exception as e:
            print(f"Model not loaded: {e}")
    return _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES

@app.get("/signals")
def get_signals_ml(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit:  Annotated[int, Query(ge=1, le=100)] = 20,
    min_score: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5,
):
    model, scaler, features = _load_model()
    if model is None:
        return {"error": "Model not loaded"}

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, price, event_time_ms, spike_pct, zscore, spread_est, "
        "volatility_1m, latency_ms, imbalance_20, burst_1s, vol_ratio, dir_burst, bucket "
        "FROM feature_store "
        "WHERE symbol=? AND imbalance_20 IS NOT NULL "
        "ORDER BY event_time_ms DESC LIMIT 200",
        (symbol.upper(),)
    ).fetchall()
    conn.close()

    if not rows:
        return []

    X = _np.array([[
        r["spike_pct"] or 0, r["zscore"] or 0, r["spread_est"] or 0,
        r["volatility_1m"] or 0, r["latency_ms"] or 0,
        r["imbalance_20"] or 0, r["burst_1s"] or 0,
        r["vol_ratio"] or 0, r["dir_burst"] or 0
    ] for r in rows])

    X_scaled = scaler.transform(X)
    scores   = model.predict_proba(X_scaled)[:,1]

    out = []
    for i, r in enumerate(rows):
        score = float(scores[i])
        if score < min_score:
            continue
        conf  = "HIGH" if score >= 0.8 else ("MEDIUM" if score >= 0.6 else "LOW")
        bkt   = r["bucket"] or "UNKNOWN"
        sig   = "CONTINUATION" if score >= 0.5 else "ABSORPTION"
        if sig == "CONTINUATION":
            interp = f"{bkt} spike — directional momentum detected. Continuation likely ({score:.0%})."
        else:
            interp = f"{bkt} spike — absorption pattern. Reversal likely ({1-score:.0%})."
        out.append({
            "symbol":        symbol.upper(),
            "price":         r["price"],
            "event_time_ms": r["event_time_ms"],
            "signal":        sig,
            "spike_type":    bkt,
            "score":         round(score, 3),
            "confidence":    conf,
            "interpretation": interp,
            "action":        "FILTER_IN",
        })
        if len(out) >= limit:
            break

    out.sort(key=lambda x: x["score"], reverse=True)
    return out
"""

if "_KERNO_MODEL" in content:
    print("ML endpoint ya existe")
else:
    open("api.py", "w", encoding="utf-8").write(content + patch)
    print("OK: ML /signals agregado")
