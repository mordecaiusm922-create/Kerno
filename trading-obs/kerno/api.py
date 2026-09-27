"""
Kerno HTTP API (read-only).

Every /v1 endpoint requires an `X-API-Key` header, is rate limited per key and
audit-logged. No endpoint writes market data or signals: GET requests never
change state (the old /events endpoint inserted signals on every page load).

Run: uvicorn kerno.api:app  (or `kerno api`)
"""

# NOTE: no `from __future__ import annotations` here: FastAPI must resolve the
# locally defined `Auth` dependency alias at runtime.

import json
import logging
import math
import time
from importlib import resources
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

from kerno import __version__
from kerno.auth import KeyStore, Principal, RateLimiter, write_audit
from kerno.config import Settings, get_settings
from kerno.db import Database, get_db
from kerno.features import FEATURE_VERSION
from kerno.model import ModelRegistry

logger = logging.getLogger("kerno.api")

MAX_REPLAY_WINDOW_MS = 3_600_000
SCORED = ("CONTINUATION", "ABSORPTION")
_SYMBOL = Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9\-_.]+$")
_EXCHANGE = Query(min_length=1, max_length=16, pattern=r"^[a-z0-9]+$")

STATIC = resources.files("kerno") / "static"


def create_app(settings: Settings | None = None, db: Database | None = None,
               models: ModelRegistry | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or get_db(settings.database_url)
    models = models if models is not None else ModelRegistry.load(settings.models_dir)
    keys = KeyStore(db, settings.default_rate_limit_per_min)
    limiter = RateLimiter()

    app = FastAPI(
        title="Kerno",
        version=__version__,
        docs_url="/docs" if settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_docs else None,
    )
    if settings.auth_disabled:
        logger.warning("KERNO_AUTH_DISABLED=1: API is open to anyone who can reach it. Local development only.")

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET"],
            allow_headers=["X-API-Key"],
        )

    @app.middleware("http")
    async def security_and_audit(request: Request, call_next):
        started = time.monotonic()
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path != "/docs":  # Swagger UI loads its assets from a CDN
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
            try:
                await run_in_threadpool(
                    write_audit, db, getattr(request.state, "key_id", None), request.method, request.url.path,
                    request.url.query, response.status_code, int((time.monotonic() - started) * 1000),
                    request.client.host if request.client else None,
                )
            except Exception:
                logger.exception("audit log write failed")
        return response

    def require_key(request: Request) -> Principal | None:
        if settings.auth_disabled:
            return None
        key = request.headers.get("X-API-Key", "")
        principal = keys.lookup(key) if key else None
        if principal is None:
            raise HTTPException(status_code=401, detail="missing or invalid API key")
        request.state.key_id = principal.key_id
        if not limiter.allow(principal.key_id, principal.rate_limit_per_min):
            raise HTTPException(status_code=429, detail="rate limit exceeded", headers={"Retry-After": "5"})
        return principal

    Auth = Annotated[Principal | None, Depends(require_key)]

    # ── public ───────────────────────────────────────────────────────────────
    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            with db.connect() as c:
                c.scalar("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": db_ok}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/terminal", response_class=HTMLResponse, include_in_schema=False)
    def terminal() -> HTMLResponse:
        return HTMLResponse((STATIC / "terminal.html").read_text(encoding="utf-8"))

    @app.get("/static/{name}", include_in_schema=False)
    def static(name: str) -> FileResponse:
        allowed = {"terminal.js": "text/javascript", "terminal.css": "text/css"}
        if name not in allowed:
            raise HTTPException(status_code=404)
        return FileResponse(str(STATIC / name), media_type=allowed[name])

    # ── data ─────────────────────────────────────────────────────────────────
    @app.get("/v1/trades")
    def trades(
        _: Auth,
        exchange: Annotated[str, _EXCHANGE] = "binance",
        symbol: Annotated[str, _SYMBOL] = "BTCUSDT",
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        before_ms: Annotated[int | None, Query(ge=0)] = None,
    ) -> list[dict[str, Any]]:
        with db.connect() as c:
            return c.fetchall(
                "SELECT exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, "
                "ingest_time_ms - event_time_ms AS latency_ms FROM trades "
                "WHERE exchange = ? AND symbol = ? AND event_time_ms < ? "
                "ORDER BY event_time_ms DESC, exchange_trade_id DESC LIMIT ?",
                (exchange, symbol.upper(), before_ms or 2**62, limit),
            )

    @app.get("/v1/replay")
    def replay(
        _: Auth,
        from_ms: Annotated[int, Query(alias="from", ge=0)],
        to_ms: Annotated[int, Query(alias="to", ge=0)],
        exchange: Annotated[str, _EXCHANGE] = "binance",
        symbol: Annotated[str, _SYMBOL] = "BTCUSDT",
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    ) -> list[dict[str, Any]]:
        if from_ms >= to_ms:
            raise HTTPException(status_code=400, detail="`from` must be before `to`")
        if to_ms - from_ms > MAX_REPLAY_WINDOW_MS:
            raise HTTPException(status_code=400, detail="window too large (max 1 hour); page through it")
        with db.connect() as c:
            return c.fetchall(
                "SELECT exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, ingest_time_ms "
                "FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? AND event_time_ms < ? "
                "ORDER BY event_time_ms, exchange_trade_id LIMIT ?",
                (exchange, symbol.upper(), from_ms, to_ms, limit),
            )

    @app.get("/v1/metrics")
    def metrics(
        _: Auth,
        exchange: Annotated[str, _EXCHANGE] = "binance",
        symbol: Annotated[str, _SYMBOL] = "BTCUSDT",
        minutes: Annotated[int, Query(ge=1, le=240)] = 60,
    ) -> list[dict[str, Any]]:
        since = int(time.time() * 1000) - minutes * 60_000
        with db.connect() as c:
            return c.fetchall(
                "SELECT (event_time_ms / 60000) * 60000 AS bucket_ms, COUNT(*) AS trade_count, "
                "AVG(ingest_time_ms - event_time_ms) AS avg_latency_ms, "
                "MAX(ingest_time_ms - event_time_ms) AS max_latency_ms, "
                "MIN(price) AS price_low, MAX(price) AS price_high, SUM(quantity) AS volume "
                "FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? "
                "GROUP BY bucket_ms ORDER BY bucket_ms DESC",
                (exchange, symbol.upper(), since),
            )

    @app.get("/v1/signals")
    def signals(
        _: Auth,
        exchange: Annotated[str, _EXCHANGE] = "binance",
        symbol: Annotated[str, _SYMBOL] = "BTCUSDT",
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        scored_only: bool = False,
        min_joint: Annotated[float, Query(ge=0.0, le=1.0)] = 0.0,
        include_features: bool = False,
    ) -> list[dict[str, Any]]:
        where = ["exchange = ?", "symbol = ?", "feature_version = ?"]
        params: list[Any] = [exchange, symbol.upper(), FEATURE_VERSION]
        if scored_only:
            where.append("signal IN ('CONTINUATION', 'ABSORPTION')")
        if min_joint > 0:
            where.append("joint_score >= ?")
            params.append(min_joint)
        cols = ("id, exchange, symbol, event_time_ms, price, spike_bps, spike_dir, bucket, signal, predicted_dir, "
                "p_tradeable, p_continuation, joint_score, stage1_model, stage2_model, feature_version, "
                "engine_version, status, price_entry, ret_10s_bps, ret_30s_bps, pnl_10s_bps, pnl_30s_bps, cost_bps")
        if include_features:
            cols += ", features"
        with db.connect() as c:
            rows = c.fetchall(
                f"SELECT {cols} FROM signals WHERE {' AND '.join(where)} ORDER BY event_time_ms DESC LIMIT ?",
                (*params, limit),
            )
        if include_features:
            for r in rows:
                r["features"] = json.loads(r["features"])
        return rows

    @app.get("/v1/performance")
    def performance(
        _: Auth,
        exchange: Annotated[str, _EXCHANGE] = "binance",
        symbol: Annotated[str, _SYMBOL] = "BTCUSDT",
        horizon: Annotated[int, Query()] = 10,
        last_n: Annotated[int, Query(ge=10, le=20000)] = 2000,
    ) -> dict[str, Any]:
        if horizon not in (10, 30):
            raise HTTPException(status_code=400, detail="horizon must be 10 or 30")
        col = f"pnl_{horizon}s_bps"
        with db.connect() as c:
            rows = c.fetchall(
                f"SELECT signal, {col} AS pnl, cost_bps FROM signals "
                "WHERE exchange = ? AND symbol = ? AND feature_version = ? AND status = 'RESOLVED' "
                f"AND signal IN ('CONTINUATION', 'ABSORPTION') AND {col} IS NOT NULL "
                "ORDER BY event_time_ms DESC LIMIT ?",
                (exchange, symbol.upper(), FEATURE_VERSION, last_n),
            )
        groups: dict[str, list[dict]] = {"ALL": rows}
        for s in SCORED:
            groups[s] = [r for r in rows if r["signal"] == s]
        return {
            "exchange": exchange,
            "symbol": symbol.upper(),
            "horizon_s": horizon,
            "feature_version": FEATURE_VERSION,
            "stats": {k: _pnl_stats(v) for k, v in groups.items()},
            "note": ("pnl is net of cost_bps per round trip, entered after the configured entry delay. "
                     "Signals overlap in time, so the t-stat overstates significance."),
        }

    @app.get("/v1/basis")
    def basis(_: Auth, limit: Annotated[int, Query(ge=1, le=2000)] = 200) -> list[dict[str, Any]]:
        with db.connect() as c:
            return c.fetchall("SELECT * FROM basis_log ORDER BY ts_ms DESC LIMIT ?", (limit,))

    @app.get("/v1/models")
    def list_models(_: Auth) -> dict[str, Any]:
        return {"feature_version": FEATURE_VERSION, "models": models.describe()}

    return app


def _pnl_stats(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    pnl = [float(r["pnl"]) for r in rows]
    gross = [p + float(r["cost_bps"] or 0) for p, r in zip(pnl, rows)]
    mean = sum(pnl) / n
    std = math.sqrt(sum((p - mean) ** 2 for p in pnl) / (n - 1)) if n > 1 else 0.0
    return {
        "n": n,
        "hit_rate": round(sum(1 for p in pnl if p > 0) / n, 4),
        "mean_net_bps": round(mean, 4),
        "mean_gross_bps": round(sum(gross) / n, 4),
        "std_bps": round(std, 4),
        "t_stat": round(mean / (std / math.sqrt(n)), 3) if std > 0 else None,
    }


def __getattr__(name: str):
    # `uvicorn kerno.api:app` builds the app lazily so importing this module
    # (tests, CLI) doesn't open database connections.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
