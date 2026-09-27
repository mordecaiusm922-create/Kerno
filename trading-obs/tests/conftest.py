import os
import random

import pytest

from kerno.db import Database

PG_URL = os.getenv("KERNO_TEST_POSTGRES_URL")
TABLES = ["trades", "symbol_registry", "basis_log", "signals", "engine_state", "api_keys",
          "api_audit_log", "archive_manifest", "schema_migrations"]
BACKENDS = ["sqlite"] + (["postgres"] if PG_URL else [])


def _fresh(backend: str, tmp_path) -> Database:
    if backend == "sqlite":
        db = Database(f"sqlite:///{tmp_path / 'kerno.db'}")
    else:
        db = Database(PG_URL)
        with db.connect() as c:
            for t in TABLES:
                c.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    db.migrate()
    return db


@pytest.fixture(params=BACKENDS)
def db(request, tmp_path):
    database = _fresh(request.param, tmp_path)
    yield database
    database.close()


def make_trades(n=3000, start_ms=1_700_000_000_000, seed=7, exchange="binance", symbol="BTCUSDT",
                jump_every=40):
    """Synthetic tape: small random walk with periodic jumps, ~100ms apart."""
    rng = random.Random(seed)
    price = 50_000.0
    ts = start_ms
    out = []
    for i in range(n):
        ts += rng.randint(20, 180)
        step = rng.choice([-1, 0, 0, 0, 1]) * 0.5
        if i % jump_every == 0 and i > 0:
            step = rng.choice([-1, 1]) * rng.uniform(10, 40)
        price = max(1.0, price + step)
        side = "buy" if (step > 0 or (step == 0 and rng.random() < 0.5)) else "sell"
        out.append({
            "exchange": exchange, "symbol": symbol, "exchange_trade_id": str(100000 + i),
            "price": round(price, 2), "quantity": round(rng.uniform(0.001, 0.5), 5), "side": side,
            "event_time_ms": ts, "ingest_time_ms": ts + rng.randint(5, 50), "raw": None,
        })
    return out
