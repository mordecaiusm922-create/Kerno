from __future__ import annotations

import logging
import os
import pickle
import sqlite3
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Annotated, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:
    from validator import validator_loop
except Exception:  # pragma: no cover
    validator_loop = None


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(os.getenv("APP_DIR", ".")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "kerno.db")))
MODEL_PATH = Path(os.getenv("KERNO_MODEL_PATH", str(BASE_DIR / "kerno_model.pkl")))
STAGE1_PATH = Path(os.getenv("KERNO_STAGE1_PATH", str(BASE_DIR / "kerno_stage1.pkl")))
TERMINAL_HTML = Path(os.getenv("TERMINAL_HTML", str(BASE_DIR / "terminal.html")))
DASHBOARD_HTML = Path(os.getenv("DASHBOARD_HTML", str(BASE_DIR / "dashboard.html")))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("kerno")

app = FastAPI(title="Kerno")


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@staticmethod
def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _ensure_schema() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                signal TEXT NOT NULL,
                bucket TEXT NOT NULL,
                confidence REAL NOT NULL,
                price_entry REAL NOT NULL,
                event_time_ms INTEGER NOT NULL,
                price_10s REAL,
                price_30s REAL,
                result_10s TEXT DEFAULT 'PENDING',
                result_30s TEXT DEFAULT 'PENDING'
            )
            """
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────────


class TradeEvent(BaseModel):
    id: int
    symbol: str
    price: float
    quantity: float
    event_time_ms: int
    ingest_time_ms: int
    latency_ms: int
    is_buyer_maker: Optional[bool] = None
    trade_id: Optional[int] = None
    spike_pct: Optional[float] = None
    intelligence: Optional[dict[str, Any]] = None


class Metrics(BaseModel):
    bucket_ms: int
    symbol: str
    trade_count: int
    avg_latency_ms: Optional[float]
    max_latency_ms: Optional[float]
    price_low: float
    price_high: float
    volume: float


class SignalPrediction(BaseModel):
    symbol: str
    price: float
    event_time_ms: int
    signal: str
    spike_type: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: str
    interpretation: str
    action: str
    drivers: list[str]
    p_tradeable: float = Field(ge=0.0, le=1.0)
    joint_score: float = Field(ge=0.0, le=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Intelligence layer
# ──────────────────────────────────────────────────────────────────────────────

_EDGE_MAP: dict[str, dict[str, tuple[str, float, float]]] = {
    "BTCUSDT": {
        "SMALL": ("REV_EDGE", 0.63, 0.37),
        "MEDIUM": ("REV_EDGE", 0.73, 0.27),
        "EXTREME": ("CONT_EDGE", 0.13, 0.87),
    },
    "ETHUSDT": {
        "LARGE": ("CONT_EDGE", 0.30, 0.70),
        "EXTREME": ("CONT_EDGE", 0.29, 0.71),
    },
}

_pct_cache: dict[str, Optional[dict[str, float]]] = {}
_streak_cache: dict[str, dict[str, Any]] = {}


def _get_percentiles(symbol: str) -> Optional[dict[str, float]]:
    since_ms = int((time.time() - 7200) * 1000)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT price, event_time_ms
            FROM market_events
            WHERE symbol = ? AND event_time_ms >= ?
            ORDER BY event_time_ms ASC
            """,
            (symbol, since_ms),
        ).fetchall()

    if len(rows) < 100:
        return None

    candles: dict[int, dict[str, float]] = {}
    for price, ts in rows:
        bucket = (ts // 1000) * 1000
        candle = candles.setdefault(bucket, {"open": float(price), "close": float(price)})
        candle["close"] = float(price)

    moves = [abs(c["close"] - c["open"]) / c["open"] * 100 for c in candles.values() if c["open"] > 0]
    if len(moves) < 20:
        return None

    s = sorted(moves)
    mean = sum(moves) / len(moves)
    std = (sum((m - mean) ** 2 for m in moves) / len(moves)) ** 0.5

    def pct(idx: float) -> float:
        return s[min(int(len(s) * idx), len(s) - 1)]

    return {"p75": pct(0.75), "p90": pct(0.90), "p99": pct(0.99), "mean": mean, "std": std, "n": float(len(moves))}


def _spread_features(symbol: str, current_ms: int) -> dict[str, float]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT price
            FROM market_events
            WHERE symbol = ? AND event_time_ms >= ?
            ORDER BY event_time_ms ASC
            LIMIT 200
            """,
            (symbol, current_ms - 5000),
        ).fetchall()

    prices = [float(r[0]) for r in rows]
    if len(prices) < 10:
        return {"roll_spread": 0.0, "flip_rate": 0.0, "micro_range": 0.0}

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    roll_spread = 0.0
    if len(deltas) >= 2:
        pairs = [(deltas[i], deltas[i - 1]) for i in range(1, len(deltas))]
        mean_a = sum(p[0] for p in pairs) / len(pairs)
        mean_b = sum(p[1] for p in pairs) / len(pairs)
        cov = sum((a - mean_a) * (b - mean_b) for a, b in pairs) / len(pairs)
        roll_spread = round(2 * ((-cov) ** 0.5), 6) if cov < 0 else 0.0

    signs = [1 if d > 0 else -1 if d < 0 else 0 for d in deltas]
    flips = sum(
        1
        for i in range(1, len(signs))
        if signs[i] != 0 and signs[i - 1] != 0 and signs[i] != signs[i - 1]
    )
    flip_rate = round(flips / max(len(signs) - 1, 1), 4)
    micro_range = round(max(prices) - min(prices), 6)

    return {"roll_spread": roll_spread, "flip_rate": flip_rate, "micro_range": micro_range}


def _classify(symbol: str, change_pct: float) -> dict[str, Any]:
    base_conf = {"SMALL": 0.35, "MEDIUM": 0.62, "LARGE": 0.80, "EXTREME": 0.92}

    if symbol not in _pct_cache:
        _pct_cache[symbol] = _get_percentiles(symbol)

    p = _pct_cache.get(symbol)
    if not p:
        return {
            "signal": "NO_DATA",
            "classification": "UNKNOWN",
            "prob_reversal": 0.5,
            "prob_continuation": 0.5,
            "confidence": 0.0,
        }

    magnitude = abs(change_pct)
    if magnitude < p["p75"]:
        bucket = "SMALL"
    elif magnitude < p["p90"]:
        bucket = "MEDIUM"
    elif magnitude < p["p99"]:
        bucket = "LARGE"
    else:
        bucket = "EXTREME"

    signal, prob_rev, prob_cont = _EDGE_MAP.get(symbol, {}).get(bucket, ("NO_EDGE", 0.5, 0.5))

    streak = _streak_cache.get(symbol, {"signal": None, "count": 0})
    if streak["signal"] == signal:
        streak["count"] = min(streak["count"] + 1, 10)
    else:
        streak = {"signal": signal, "count": 1}
    _streak_cache[symbol] = streak

    streak_bonus = min((streak["count"] - 1) * 0.04, 0.15)
    confidence = round(min(base_conf.get(bucket, 0.35) + streak_bonus, 1.0), 3)
    classification = f"{signal}_{bucket}" if signal != "NO_EDGE" else f"NOISE_{bucket}"
    zscore = round((magnitude - p.get("mean", 0.0)) / p.get("std", 1.0), 3) if p.get("std", 0.0) > 0 else 0.0

    return {
        "signal": signal,
        "classification": classification,
        "bucket": bucket,
        "prob_reversal": prob_rev,
        "prob_continuation": prob_cont,
        "confidence": confidence,
        "zscore": zscore,
        "regime_n": int(p.get("n", 0)),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Model loading
# ──────────────────────────────────────────────────────────────────────────────

_KERNO_MODEL: Any = None
_KERNO_SCALER: Any = None
_KERNO_FEATURES: Any = None
_STAGE1_MODEL: Any = None
_STAGE1_SCALER: Any = None
_STAGE1_FEATURES: Any = None


def _load_pickle(path: Path) -> Optional[dict[str, Any]]:
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception as exc:
        log.warning("Unable to load %s: %s", path.name, exc)
        return None


def _load_model() -> tuple[Any, Any, Any]:
    global _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES
    if _KERNO_MODEL is None:
        data = _load_pickle(MODEL_PATH)
        if data:
            _KERNO_MODEL = data.get("model")
            _KERNO_SCALER = data.get("scaler")
            _KERNO_FEATURES = data.get("features")
    return _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES


def _load_stage1() -> tuple[Any, Any, Any]:
    global _STAGE1_MODEL, _STAGE1_SCALER, _STAGE1_FEATURES
    if _STAGE1_MODEL is None:
        data = _load_pickle(STAGE1_PATH)
        if data:
            _STAGE1_MODEL = data.get("model")
            _STAGE1_SCALER = data.get("scaler")
            _STAGE1_FEATURES = data.get("features")
    return _STAGE1_MODEL, _STAGE1_SCALER, _STAGE1_FEATURES


# ──────────────────────────────────────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────────────────────────────────────


@app.on_event("startup")
def on_startup() -> None:
    _ensure_schema()
    log.info("Kerno initialized at %s", DB_PATH)

    if validator_loop is not None:
        thread = threading.Thread(target=validator_loop, daemon=True, name="validator-loop")
        thread.start()
        log.info("validator thread started")
    else:
        log.info("validator module not available")


# ──────────────────────────────────────────────────────────────────────────────
# Internal utilities
# ──────────────────────────────────────────────────────────────────────────────


def _open_html(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{path.name} not found")


def _record_signal_outcome(symbol: str, intel: dict[str, Any], price: float, event_time_ms: int) -> None:
    if intel.get("confidence", 0.0) < 0.62:
        return
    if intel.get("bucket") not in {"MEDIUM", "LARGE", "EXTREME"}:
        return
    if intel.get("signal") in {"NO_DATA", "NO_EDGE"}:
        return

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO signal_outcomes
                    (symbol, signal, bucket, confidence, price_entry, event_time_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    str(intel.get("signal", "")),
                    str(intel.get("bucket", "")),
                    float(intel.get("confidence", 0.0)),
                    float(price),
                    int(event_time_ms),
                ),
            )
            conn.commit()
    except Exception as exc:
        log.debug("signal outcome insert skipped: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "product": "Kerno", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/events", response_model=list[TradeEvent])
def get_events(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[dict[str, Any]]:
    symbol = symbol.upper()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, price, quantity,
                   event_time_ms, ingest_time_ms,
                   (ingest_time_ms - event_time_ms) AS latency_ms,
                   is_buyer_maker, trade_id
            FROM market_events
            WHERE symbol = ?
            ORDER BY event_time_ms DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()

    enriched: list[dict[str, Any]] = []
    prev_price: Optional[float] = None

    for row in rows:
        item = dict(row)
        price = float(item["price"])
        if prev_price is not None and prev_price > 0:
            change_pct = (price - prev_price) / prev_price * 100
            item["spike_pct"] = round(change_pct, 6)
            item["intelligence"] = _classify(symbol, change_pct)
        else:
            item["spike_pct"] = 0.0
            item["intelligence"] = {"signal": "NO_DATA", "confidence": 0.0}

        prev_price = price
        _record_signal_outcome(symbol, item.get("intelligence", {}), price, int(item["event_time_ms"]))
        enriched.append(item)

    return enriched


@app.get("/replay", response_model=list[TradeEvent])
def replay(
    from_ms: Annotated[int, Query(alias="from")],
    to_ms: Annotated[int, Query(alias="to")],
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[dict[str, Any]]:
    if from_ms >= to_ms:
        raise HTTPException(status_code=400, detail="from debe ser menor que to")

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, price, quantity,
                   event_time_ms, ingest_time_ms,
                   (ingest_time_ms - event_time_ms) AS latency_ms,
                   is_buyer_maker, trade_id
            FROM market_events
            WHERE symbol = ? AND event_time_ms >= ? AND event_time_ms <= ?
            ORDER BY event_time_ms ASC
            LIMIT ?
            """,
            (symbol.upper(), from_ms, to_ms, limit),
        ).fetchall()

    return [dict(r) for r in rows]


@app.get("/metrics", response_model=list[Metrics])
def get_metrics(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> list[dict[str, Any]]:
    since_ms = int((time.time() - minutes * 60) * 1000)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT (event_time_ms / 60000) * 60000 AS bucket_ms,
                   symbol,
                   COUNT(*) AS trade_count,
                   AVG(ingest_time_ms - event_time_ms) AS avg_latency_ms,
                   MAX(ingest_time_ms - event_time_ms) AS max_latency_ms,
                   MIN(price) AS price_low,
                   MAX(price) AS price_high,
                   SUM(quantity) AS volume
            FROM market_events
            WHERE symbol = ?
              AND event_type = 'trade'
              AND event_time_ms >= ?
            GROUP BY bucket_ms, symbol
            ORDER BY bucket_ms DESC
            """,
            (symbol.upper(), since_ms),
        ).fetchall()

    return [dict(r) for r in rows]


@app.get("/accuracy")
def get_accuracy(symbol: Annotated[str, Query()] = "BTCUSDT") -> dict[str, Any]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT signal, result_10s, result_30s, confidence
            FROM signal_outcomes
            WHERE symbol = ?
            ORDER BY event_time_ms DESC
            LIMIT 500
            """,
            (symbol.upper(),),
        ).fetchall()

    total = len(rows)
    if total == 0:
        return {"total": 0, "validated": 0, "win_rate_10s": None, "win_rate_30s": None, "avg_confidence": None}

    validated = sum(1 for r in rows if r[1] != "PENDING")
    wins_10 = sum(1 for r in rows if r[1] == "WIN")
    wins_30 = sum(1 for r in rows if r[2] == "WIN")
    avg_confidence = round(sum(float(r[3]) for r in rows) / total, 3)

    return {
        "total": total,
        "validated": validated,
        "win_rate_10s": round(wins_10 / validated * 100, 1) if validated else None,
        "win_rate_30s": round(wins_30 / validated * 100, 1) if validated else None,
        "avg_confidence": avg_confidence,
    }


@app.get("/terminal", response_class=HTMLResponse)
def get_terminal() -> str:
    return _open_html(TERMINAL_HTML)


@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard() -> str:
    return _open_html(DASHBOARD_HTML)


@app.get("/signals", response_model=list[SignalPrediction])
def get_signals_ml(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    min_score: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5,
) -> list[dict[str, Any]]:
    symbol = symbol.upper()
    model, scaler, _features = _load_model()
    if model is None or scaler is None:
        return [{"error": "Model not loaded"}]

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, price, event_time_ms, spike_pct, zscore, spread_est,
                   volatility_1m, latency_ms, imbalance_20, burst_1s,
                   vol_ratio, dir_burst, bucket
            FROM feature_store
            WHERE symbol = ? AND imbalance_20 IS NOT NULL
            ORDER BY event_time_ms DESC
            LIMIT 200
            """,
            (symbol,),
        ).fetchall()

    if not rows:
        return []

    feature_names = [
        "spike_pct",
        "zscore",
        "spread_est",
        "volatility_1m",
        "latency_ms",
        "imbalance_20",
        "burst_1s",
        "vol_ratio",
        "dir_burst",
    ]

    X = np.array(
        [
            [
                float(r["spike_pct"] or 0.0),
                float(r["zscore"] or 0.0),
                float(r["spread_est"] or 0.0),
                float(r["volatility_1m"] or 0.0),
                float(r["latency_ms"] or 0.0),
                float(r["imbalance_20"] or 0.0),
                float(r["burst_1s"] or 0.0),
                float(r["vol_ratio"] or 0.0),
                float(r["dir_burst"] or 0.0),
            ]
            for r in rows
        ],
        dtype=float,
    )

    X_scaled = scaler.transform(X)
    scores = model.predict_proba(X_scaled)[:, 1]

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        score = float(scores[idx])
        if score < min_score:
            continue

        bucket = str(row["bucket"] or "UNKNOWN")
        signal = "CONTINUATION" if score >= 0.5 else "ABSORPTION"
        confidence = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.6 else "LOW"

        if signal == "CONTINUATION":
            interpretation = f"{bucket} spike — directional momentum detected. Continuation likely ({score:.0%})."
        else:
            interpretation = f"{bucket} spike — absorption pattern. Reversal likely ({(1 - score):.0%})."

        # Deterministic contribution ranking; no fake certainty.
        try:
            if hasattr(model, "calibrated_classifiers_"):
                base_model = model.calibrated_classifiers_[0].estimator
                if hasattr(base_model, "coef_"):
                    coefs = np.asarray(base_model.coef_[0], dtype=float)
                    sample = np.asarray(X_scaled[idx], dtype=float)
                    contribs = {name: abs(float(coefs[i] * sample[i])) for i, name in enumerate(feature_names)}
                    drivers = sorted(contribs, key=contribs.get, reverse=True)[:3]
                else:
                    drivers = ["spike_pct", "vol_ratio", "spread_est"]
            else:
                drivers = ["spike_pct", "vol_ratio", "spread_est"]
        except Exception:
            drivers = ["spike_pct", "vol_ratio", "spread_est"]

        spread = float(row["spread_est"] or 0.0)
        imbalance = float(row["imbalance_20"] or 0.0)
        p_tradeable = float(np.clip(score * (1.0 - min(spread, 1.0) * 0.15) * (1.0 - abs(imbalance) * 0.05), 0.0, 1.0))
        joint_score = float(np.clip((score + p_tradeable) / 2.0, 0.0, 1.0))

        out.append(
            {
                "symbol": symbol,
                "price": float(row["price"]),
                "event_time_ms": int(row["event_time_ms"]),
                "signal": signal,
                "spike_type": bucket,
                "score": round(score, 3),
                "confidence": confidence,
                "interpretation": interpretation,
                "action": "FILTER_IN",
                "drivers": drivers,
                "p_tradeable": round(p_tradeable, 3),
                "joint_score": round(joint_score, 3),
            }
        )

        if len(out) >= limit:
            break

    out.sort(key=lambda x: x["score"], reverse=True)
    return out
