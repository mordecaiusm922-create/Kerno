import threading

from kerno.basis import sample_basis
from kerno.engine import SignalEngine, process_range, run_engine
from kerno.ingest import write_trades
from kerno.model import ModelRegistry
from kerno.validator import resolve_signal, validate_pending
from tests.conftest import make_trades


def count(db, table):
    with db.connect() as c:
        return c.scalar(f"SELECT COUNT(*) FROM {table}")


def _in_memory(trades):
    engine = SignalEngine("binance", "BTCUSDT")
    return [r for r in (engine.on_trade(t) for t in trades) if r]


def test_ingest_is_idempotent(db):
    trades = make_trades(500)
    write_trades(db, trades, store_raw=False)
    write_trades(db, trades, store_raw=False)  # reconnect duplicates
    assert count(db, "trades") == 500


def test_db_replay_matches_in_memory_engine(db):
    trades = make_trades(3000)
    write_trades(db, trades, store_raw=False)
    n, cursor = process_range(db, SignalEngine("binance", "BTCUSDT"), (0, ""), 2**62, batch=700)
    mem = _in_memory(trades)
    assert n == len(mem) == count(db, "signals")
    assert cursor == (trades[-1]["event_time_ms"], trades[-1]["exchange_trade_id"])
    # replaying again writes nothing new
    process_range(db, SignalEngine("binance", "BTCUSDT"), (0, ""), 2**62)
    assert count(db, "signals") == n


def test_engine_worker_resumes_from_cursor(db, monkeypatch):
    import time as real_time

    trades = make_trades(3000)
    fake_now = (trades[-1]["event_time_ms"] + 10_000) / 1000
    monkeypatch.setattr("kerno.engine.time.time", lambda: fake_now)

    def run_worker(**kwargs):
        stop = threading.Event()
        t = threading.Thread(target=run_engine, args=(db, [("binance", "BTCUSDT")], ModelRegistry(), stop),
                             kwargs={"poll_s": 0.05, **kwargs})
        t.start()
        real_time.sleep(0.5)
        stop.set()
        t.join()

    write_trades(db, trades[:1500], store_raw=False)
    run_worker(start_lookback_ms=10**12)
    write_trades(db, trades[1500:], store_raw=False)
    run_worker()  # restart: resumes from the saved cursor

    with db.connect() as c:
        rows = c.fetchall("SELECT exchange_trade_id FROM signals ORDER BY event_time_ms")
    ids = [r["exchange_trade_id"] for r in rows]
    mem_ids = [r["exchange_trade_id"] for r in _in_memory(trades)]
    # a restart reproduces the continuous run exactly (see engine.WARMUP_MS)
    assert ids == mem_ids


def _signal(ts, direction=1):
    return {"id": 1, "exchange": "binance", "symbol": "BTCUSDT", "event_time_ms": ts, "predicted_dir": direction}


def _tape(db, points):
    write_trades(db, [{"exchange": "binance", "symbol": "BTCUSDT", "exchange_trade_id": str(i), "price": p,
                       "quantity": 1.0, "side": "buy", "event_time_ms": ts, "ingest_time_ms": ts, "raw": None}
                      for i, (ts, p) in enumerate(points)], store_raw=False)


def test_validator_uses_entry_delay_costs_and_future_only(db):
    t0 = 1_000_000
    _tape(db, [(t0, 100.0), (t0 + 100, 999.0), (t0 + 300, 100.0), (t0 + 10_000, 101.0), (t0 + 30_000, 99.0)])
    with db.connect() as c:
        res = resolve_signal(c, _signal(t0, 1), cost_bps=10, entry_delay_ms=250)
    assert res["status"] == "RESOLVED"
    assert res["price_entry"] == 100.0  # the 999 print at +100ms is inside the entry delay
    assert round(res["ret_10s_bps"], 6) == 100.0 and round(res["pnl_10s_bps"], 6) == 90.0
    assert round(res["pnl_30s_bps"], 6) == -110.0
    with db.connect() as c:
        short = resolve_signal(c, _signal(t0, -1), cost_bps=10, entry_delay_ms=250)
    assert round(short["pnl_10s_bps"], 6) == -110.0


def test_validator_gaps_and_watermark(db):
    t0 = 1_000_000
    _tape(db, [(t0, 100.0), (t0 + 300, 100.0), (t0 + 20_000, 101.0), (t0 + 40_000, 99.0)])
    with db.connect() as c:
        assert resolve_signal(c, _signal(t0), 10, 250)["status"] == "NO_DATA"  # nothing near +10s
    trades = make_trades(3000)
    write_trades(db, trades, store_raw=False)
    process_range(db, SignalEngine("binance", "BTCUSDT"), (0, ""), 2**62)
    validate_pending(db, cost_bps=10, entry_delay_ms=250)
    with db.connect() as c:
        rows = c.fetchall("SELECT status, event_time_ms FROM signals")
    last = trades[-1]["event_time_ms"]
    for r in rows:
        if r["event_time_ms"] > last - 35_000:
            assert r["status"] == "PENDING"  # horizon not covered by data yet
    assert any(r["status"] == "RESOLVED" for r in rows)


def test_basis_sampler(db):
    now = 2_000_000_000_000
    write_trades(db, [
        {"exchange": "binance", "symbol": "BTCUSDT", "exchange_trade_id": "1", "price": 100.0, "quantity": 1,
         "side": "buy", "event_time_ms": now - 1000, "ingest_time_ms": now, "raw": None},
        {"exchange": "bybit", "symbol": "BTCUSDT-PERP", "exchange_trade_id": "1", "price": 99.9, "quantity": 1,
         "side": "buy", "event_time_ms": now - 500, "ingest_time_ms": now, "raw": None},
    ], store_raw=False)
    row = sample_basis(db, now)
    assert round(row["basis_pct"], 6) == -0.1 and row["okx_price"] is None
    assert sample_basis(db, now + 120_000) is None  # stale legs are not sampled
