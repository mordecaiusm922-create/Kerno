"""
fix_api.py — reemplaza api.py con la version limpia de Kerno
Ejecutar desde: C:\Users\usuario\Downloads\trading-obs\trading-obs
"""
import os

API_CONTENT = '''"""
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
        raise HTTPException(400, "\'from\' debe ser menor que \'to\'")

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
        WHERE symbol        = ?
          AND event_type    = \'trade\'
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
'''

target = os.path.join(os.path.dirname(__file__), "api.py")

with open(target, "w", encoding="utf-8") as f:
    f.write(API_CONTENT)

print(f"✓ api.py reemplazado correctamente en: {target}")
print("  Uvicorn se recargará solo. Abre: http://localhost:8000/")
