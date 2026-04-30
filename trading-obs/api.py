"""
Kerno API — FastAPI + SQLite
"""
import os
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db.connection import get_conn, init_db

app = FastAPI(title="Kerno", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── Models ────────────────────────────────────────────────────────────────────
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


class Metrics(BaseModel):
    bucket_ms:      int
    symbol:         str
    trade_count:    int
    avg_latency_ms: float | None
    max_latency_ms: float | None
    price_low:      float
    price_high:     float
    volume:         float


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "product": "Kerno", "ts": datetime.now(timezone.utc)}


@app.get("/events", response_model=list[TradeEvent])
def get_events(
    symbol: Annotated[str, Query()] = "BTCUSDT",
    limit:  Annotated[int, Query(ge=1, le=1000)] = 100,
):
    conn = get_conn()
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
        (symbol.upper(), limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/replay", response_model=list[TradeEvent])
def replay(
    from_ms:  Annotated[int, Query(alias="from")],
    to_ms:    Annotated[int, Query(alias="to")],
    symbol:   Annotated[str, Query()] = "BTCUSDT",
    limit:    Annotated[int, Query(ge=1, le=5000)] = 500,
):
    if from_ms >= to_ms:
        raise HTTPException(400, "'from' debe ser menor que 'to'")

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, symbol, price, quantity,
               event_time_ms, ingest_time_ms,
               (ingest_time_ms - event_time_ms) AS latency_ms,
               is_buyer_maker, trade_id
        FROM market_events
        WHERE symbol        = ?
          AND event_time_ms >= ?
          AND event_time_ms <= ?
        ORDER BY event_time_ms ASC
        LIMIT ?
        """,
        (symbol.upper(), from_ms, to_ms, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/metrics", response_model=list[Metrics])
def get_metrics(
    symbol:  Annotated[str, Query()] = "BTCUSDT",
    minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
):
    since_ms = int((time.time() - minutes * 60) * 1000)

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
            (event_time_ms / 60000) * 60000         AS bucket_ms,
            symbol,
            COUNT(*)                                 AS trade_count,
            AVG(ingest_time_ms - event_time_ms)      AS avg_latency_ms,
            MAX(ingest_time_ms - event_time_ms)      AS max_latency_ms,
            MIN(price)                               AS price_low,
            MAX(price)                               AS price_high,
            SUM(quantity)                            AS volume
        FROM market_events
        WHERE symbol       = ?
          AND event_type   = 'trade'
          AND event_time_ms >= ?
        GROUP BY bucket_ms, symbol
        ORDER BY bucket_ms DESC
        """,
        (symbol.upper(), since_ms),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Serve frontend ────────────────────────────────────────────────────────────
_frontend = os.path.join(os.path.dirname(__file__), "frontend")

if os.path.isdir(_frontend):
    app.mount("/static", StaticFiles(directory=_frontend), name="static")

    @app.get("/", include_in_schema=False)
    def serve_ui():
        return FileResponse(os.path.join(_frontend, "index.html"))


# ── Backtest endpoint ─────────────────────────────────────────────────────────
import sys as _sys
import importlib.util as _ilu

def _load_backtester():
    p = os.path.join(os.path.dirname(__file__), "backtester.py")
    spec = _ilu.spec_from_file_location("backtester", p)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class BacktestResult(BaseModel):
    symbol:            str
    events_loaded:     int
    spikes_detected:   int
    trades_executed:   int
    win_rate_pct:      float | None
    total_pnl_pct:     float | None
    avg_pnl_pct:       float | None
    best_trade_pct:    float | None
    worst_trade_pct:   float | None
    max_drawdown_pct:  float | None
    profit_factor:     float | None
    avg_hold_sec:      float | None
    avg_entry_latency_ms: float | None
    verdict:           str

@app.get("/backtest", response_model=BacktestResult)
def run_backtest_endpoint(
    symbol:    Annotated[str,   Query()] = "BTCUSDT",
    hold:      Annotated[int,   Query(ge=5, le=300)] = 30,
    z:         Annotated[float, Query(ge=1.0, le=5.0)] = 2.0,
    min_spike: Annotated[float, Query(ge=0.001, le=1.0)] = 0.01,
    limit:     Annotated[int,   Query(ge=100, le=50000)] = 10000,
    save:      Annotated[bool,  Query()] = True,
):
    """
    Corre backtest sobre datos historicos en kerno.db.
    Estrategia: spike-follow — entra en direccion del spike, sale despues de hold segundos.
    """
    bt = _load_backtester()
    events = bt.load_events(symbol, limit)
    if len(events) < 20:
        raise HTTPException(400, f"Pocos datos: {len(events)} eventos. Deja el ingestor correr mas tiempo.")

    spikes = bt.detect_spikes(events, z_threshold=z, min_pct=min_spike)
    trades = bt.run_backtest(events, spikes, hold_seconds=hold)
    stats  = bt.compute_stats(trades)

    params = {"symbol": symbol, "events_loaded": len(events),
              "spikes_detected": len(spikes), "hold_seconds": hold,
              "z_threshold": z, "min_spike_pct": min_spike}

    if save and stats:
        bt.save_results(symbol, params, stats, trades)

    if not stats:
        return BacktestResult(
            symbol=symbol, events_loaded=len(events),
            spikes_detected=len(spikes), trades_executed=0,
            win_rate_pct=None, total_pnl_pct=None, avg_pnl_pct=None,
            best_trade_pct=None, worst_trade_pct=None, max_drawdown_pct=None,
            profit_factor=None, avg_hold_sec=None, avg_entry_latency_ms=None,
            verdict="Sin trades — aumenta el tiempo de captura o reduce z-threshold"
        )

    wr  = stats["win_rate_pct"]
    pnl = stats["total_pnl_pct"]
    if wr >= 55 and pnl > 0:
        verdict = "EDGE DETECTADO — estrategia tiene valor estadistico"
    elif pnl > 0:
        verdict = "PnL positivo — ajustar parametros para mejorar win rate"
    elif wr >= 50:
        verdict = "Win rate ok pero fees matan PnL — reducir hold time"
    else:
        verdict = "Sin edge — spike-follow no funciona en este periodo"

    return BacktestResult(
        symbol=symbol,
        events_loaded=len(events),
        spikes_detected=len(spikes),
        trades_executed=stats["total_trades"],
        win_rate_pct=stats["win_rate_pct"],
        total_pnl_pct=stats["total_pnl_pct"],
        avg_pnl_pct=stats["avg_pnl_pct"],
        best_trade_pct=stats["best_trade_pct"],
        worst_trade_pct=stats["worst_trade_pct"],
        max_drawdown_pct=stats["max_drawdown_pct"],
        profit_factor=stats["profit_factor"],
        avg_hold_sec=stats["avg_hold_sec"],
        avg_entry_latency_ms=stats["avg_entry_latency_ms"],
        verdict=verdict,
    )
