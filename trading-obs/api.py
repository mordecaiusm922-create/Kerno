from pydantic import BaseModel
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Annotated
from datetime import datetime, timezone
import sqlite3, os, time, threading

DB_PATH = os.getenv("DB_PATH", "kerno.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

app = FastAPI(title="Kerno")

# ── Spike Intelligence Layer ──────────────────────────────
_EDGE_MAP = {
    "BTCUSDT": {
        "SMALL":   ("REV_EDGE",  0.63, 0.37),
        "MEDIUM":  ("REV_EDGE",  0.73, 0.27),
        "EXTREME": ("CONT_EDGE", 0.13, 0.87),
    },
    "ETHUSDT": {
        "LARGE":   ("CONT_EDGE", 0.30, 0.70),
        "EXTREME": ("CONT_EDGE", 0.29, 0.71),
    },
}
_pct_cache    = {}
_streak_cache = {}

def _get_percentiles(symbol):
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

def _classify(symbol, change_pct):
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
        signal, prob_rev, prob_cont = edges[bucket]
    else:
        signal, prob_rev, prob_cont = "NO_EDGE", 0.5, 0.5
    sc = _streak_cache.get(symbol, {"signal": None, "count": 0})
    if sc["signal"] == signal:
        sc["count"] = min(sc["count"] + 1, 10)
    else:
        sc = {"signal": signal, "count": 1}
    _streak_cache[symbol] = sc
    streak_bonus = min((sc["count"] - 1) * 0.04, 0.15)
    base = BASE_CONF.get(bucket, 0.35)
    confidence = round(min(base + streak_bonus, 1.0), 3)
    cls = signal + "_" + bucket if signal != "NO_EDGE" else "NOISE_" + bucket
    zscore = round((m - p.get("mean", 0)) / p.get("std", 1), 3) if p.get("std", 0) > 0 else 0
    return {
        "signal": signal, "classification": cls, "bucket": bucket,
        "prob_reversal": prob_rev, "prob_continuation": prob_cont,
        "confidence": confidence, "zscore": zscore, "regime_n": p.get("n", 0),
    }

# ── Startup ───────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    conn = get_conn()
    conn.execute("""
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
    conn.commit()
    conn.close()
    print("[DB] Kerno inicializado en kerno.db")
    from validator import validator_loop
    t = threading.Thread(target=validator_loop, daemon=True)
    t.start()
    print("[validator] thread iniciado")

# ── Models ────────────────────────────────────────────────
class TradeEvent(BaseModel):
    id:             int
    symbol:         str
    price:          float
    quantity:       float
    event_time_ms:  int
    ingest_time_ms: int
    latency_ms:     int
    is_buyer_maker: bool | None
    trade_id:       int | None
    spike_pct:      float | None = None
    intelligence:   dict | None = None

class Metrics(BaseModel):
    bucket_ms:      int
    symbol:         str
    trade_count:    int
    avg_latency_ms: float | None
    max_latency_ms: float | None
    price_low:      float
    price_high:     float
    volume:         float

# ── Endpoints ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "product": "Kerno", "ts": datetime.now(timezone.utc)}

@app.get("/events", response_model=list[TradeEvent])
def get_events(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit:  Annotated[int, Query(ge=1, le=1000)] = 100,
):
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, symbol, price, quantity,
               event_time_ms, ingest_time_ms,
               (ingest_time_ms - event_time_ms) AS latency_ms,
               is_buyer_maker, trade_id
        FROM market_events
        WHERE symbol = ?
        ORDER BY event_time_ms DESC LIMIT ?
    """, (symbol.upper(), limit)).fetchall()
    conn.close()
    enriched = []
    prev_price = None
    for r in rows:
        d = dict(r)
        if prev_price and prev_price > 0:
            change_pct = (d["price"] - prev_price) / prev_price * 100
            d["spike_pct"] = round(change_pct, 6)
            d["intelligence"] = _classify(d["symbol"], change_pct)
        else:
            d["spike_pct"] = 0.0
            d["intelligence"] = {"signal": "NO_DATA", "confidence": 0.0}
        prev_price = d["price"]
        # Registrar señales con confidence > 0.50 para validacion
        intel = d.get("intelligence", {})
        if intel.get("confidence", 0) >= 0.62 and intel.get("bucket") in ("MEDIUM","LARGE","EXTREME") and intel.get("signal") not in ("NO_DATA", "NO_EDGE"):
            try:
                conn2 = get_conn()
                conn2.execute("""
                    INSERT INTO signal_outcomes
                    (symbol, signal, bucket, confidence, price_entry, event_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (d["symbol"], intel["signal"], intel.get("bucket",""),
                      intel["confidence"], d["price"], d["event_time_ms"]))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
        enriched.append(d)
    return enriched

@app.get("/replay", response_model=list[TradeEvent])
def replay(
    from_ms: Annotated[int, Query(alias="from")],
    to_ms:   Annotated[int, Query(alias="to")],
    symbol:  Annotated[str, Query()] = "BTCUSDT",
    limit:   Annotated[int, Query(ge=1, le=5000)] = 500,
):
    if from_ms >= to_ms:
        raise HTTPException(400, "from debe ser menor que to")
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, symbol, price, quantity,
               event_time_ms, ingest_time_ms,
               (ingest_time_ms - event_time_ms) AS latency_ms,
               is_buyer_maker, trade_id
        FROM market_events
        WHERE symbol=? AND event_time_ms>=? AND event_time_ms<=?
        ORDER BY event_time_ms ASC LIMIT ?
    """, (symbol.upper(), from_ms, to_ms, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/metrics", response_model=list[Metrics])
def get_metrics(
    symbol:  Annotated[str, Query()] = "BTCUSDT",
    minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
):
    since_ms = int((time.time() - minutes * 60) * 1000)
    conn = get_conn()
    rows = conn.execute("""
        SELECT (event_time_ms/60000)*60000 AS bucket_ms, symbol,
               COUNT(*) AS trade_count,
               AVG(ingest_time_ms-event_time_ms) AS avg_latency_ms,
               MAX(ingest_time_ms-event_time_ms) AS max_latency_ms,
               MIN(price) AS price_low, MAX(price) AS price_high,
               SUM(quantity) AS volume
        FROM market_events
        WHERE symbol=? AND event_type='trade' AND event_time_ms>=?
        GROUP BY bucket_ms, symbol ORDER BY bucket_ms DESC
    """, (symbol.upper(), since_ms)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

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
        return {"total": 0, "win_rate_10s": None, "win_rate_30s": None, "validated": 0}
    wins_10   = sum(1 for r in rows if r[1] == "WIN")
    wins_30   = sum(1 for r in rows if r[2] == "WIN")
    validated = sum(1 for r in rows if r[1] != "PENDING")
    return {
        "total": total, "validated": validated,
        "win_rate_10s": round(wins_10/validated*100,1) if validated else None,
        "win_rate_30s": round(wins_30/validated*100,1) if validated else None,
        "avg_confidence": round(sum(r[3] for r in rows)/total, 3),
    }

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    return open("dashboard.html", encoding="utf-8").read()


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
        (r["spike_pct"] or 0), (r["zscore"] or 0), (r["spread_est"] or 0),
        (r["volatility_1m"] or 0), (r["latency_ms"] or 0),
        (r["imbalance_20"] or 0), (r["burst_1s"] or 0),
        (r["vol_ratio"] or 0), (r["dir_burst"] or 0)
    ] for r in rows])
    print(f"[signals] X shape: {X.shape}, rows: {len(rows)}")

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
        # Top 3 drivers por magnitud de contribucion
        feature_names = ["spike_pct","zscore","spread_est","volatility_1m",
                         "latency_ms","imbalance_20","burst_1s","vol_ratio","dir_burst"]
        try:
            base_model = model.calibrated_classifiers_[0].estimator
            coefs = base_model.coef_[0]
            contribs = {f: abs(float(coefs[i]) * float(X_scaled[i][i])) 
                       for i, f in enumerate(feature_names)}
            drivers = sorted(contribs, key=contribs.get, reverse=True)[:3]
        except:
            drivers = ["spike_pct", "vol_ratio", "spread_est"]
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
            "drivers":      drivers,
        })
        if len(out) >= limit:
            break

    out.sort(key=lambda x: x["score"], reverse=True)
    return out
