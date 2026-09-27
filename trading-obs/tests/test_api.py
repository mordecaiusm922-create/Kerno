import hashlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from kerno.api import create_app
from kerno.auth import create_key, revoke_key
from kerno.config import Settings
from kerno.engine import SignalEngine, process_range
from kerno.ingest import write_trades
from kerno.model import ModelRegistry
from kerno.validator import validate_pending
from tests.conftest import TABLES, make_trades

ENDPOINTS = [
    "/v1/trades", "/v1/metrics", "/v1/signals", "/v1/signals?include_features=true&scored_only=true",
    "/v1/performance", "/v1/performance?horizon=30", "/v1/basis", "/v1/models",
    "/v1/replay?from=1700000000000&to=1700000600000",
]


@pytest.fixture
def client(db):
    trades = make_trades(3000)
    write_trades(db, trades, store_raw=False)
    process_range(db, SignalEngine("binance", "BTCUSDT"), (0, ""), 2**62)
    validate_pending(db, 10, 250)
    settings = replace(Settings(), database_url=db.url, auth_disabled=False, default_rate_limit_per_min=1000)
    app = create_app(settings, db=db, models=ModelRegistry())
    key = create_key(db, "test")
    return TestClient(app), key, db


def snapshot(db):
    out = {}
    with db.connect() as c:
        for t in TABLES:
            if t == "api_audit_log":
                continue
            rows = c.fetchall(f"SELECT * FROM {t} ORDER BY 1")
            out[t] = hashlib.sha256(repr(rows).encode()).hexdigest()
    return out


def test_requires_api_key(client):
    tc, key, _ = client
    for path in ENDPOINTS:
        assert tc.get(path).status_code == 401
        assert tc.get(path, headers={"X-API-Key": "kerno_wrong"}).status_code == 401
    assert tc.get("/health").json()["database"] is True


def test_get_requests_never_write(client):
    """Regression for the old /events endpoint, which inserted signals on every page load."""
    tc, key, db = client
    before = snapshot(db)
    for _ in range(3):
        for path in ENDPOINTS:
            assert tc.get(path, headers={"X-API-Key": key}).status_code == 200, path
    assert snapshot(db) == before
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM api_audit_log") == 3 * len(ENDPOINTS)


def test_performance_is_net_of_costs(client):
    tc, key, db = client
    with db.connect() as c:
        c.execute("UPDATE signals SET signal = 'CONTINUATION', predicted_dir = spike_dir, "
                  "pnl_10s_bps = spike_dir * ret_10s_bps - cost_bps WHERE status = 'RESOLVED'")
    stats = tc.get("/v1/performance", headers={"X-API-Key": key}).json()["stats"]["ALL"]
    assert stats["n"] > 0
    assert round(stats["mean_gross_bps"] - stats["mean_net_bps"], 6) == 10.0


def test_validation_and_limits(client):
    tc, key, _ = client
    h = {"X-API-Key": key}
    assert tc.get("/v1/replay?from=0&to=7200000", headers=h).status_code == 400
    assert tc.get("/v1/replay?from=10&to=5", headers=h).status_code == 400
    assert tc.get("/v1/trades?limit=100000", headers=h).status_code == 422
    assert tc.get("/v1/trades?symbol=BTC'--", headers=h).status_code == 422
    assert tc.get("/v1/performance?horizon=7", headers=h).status_code == 400
    assert tc.get("/static/../api.py").status_code == 404


def test_rate_limit_and_revocation(db):
    settings = replace(Settings(), database_url=db.url, default_rate_limit_per_min=5)
    tc = TestClient(create_app(settings, db=db, models=ModelRegistry()))
    key = create_key(db, "limited")
    codes = [tc.get("/v1/models", headers={"X-API-Key": key}).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[-1] == 429
    key2 = create_key(db, "revoked")
    with db.connect() as c:
        kid = c.scalar("SELECT id FROM api_keys WHERE name = 'revoked'")
    assert revoke_key(db, kid)
    tc2 = TestClient(create_app(settings, db=db, models=ModelRegistry()))
    assert tc2.get("/v1/models", headers={"X-API-Key": key2}).status_code == 401


def test_security_headers_and_terminal(client):
    tc, _, _ = client
    r = tc.get("/terminal")
    assert r.status_code == 200
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "<script>" not in r.text  # no inline script, CSP can stay strict
    js = tc.get("/static/terminal.js").text
    assert ".innerHTML" not in js and "insertAdjacentHTML" not in js


def test_keys_are_stored_hashed(db):
    key = create_key(db, "x")
    with db.connect() as c:
        row = c.fetchone("SELECT * FROM api_keys WHERE name = 'x'")
    assert key not in repr(row) and row["key_hash"] == hashlib.sha256(key.encode()).hexdigest()
