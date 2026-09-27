import gzip
import hashlib
import io
import json
import random
import zipfile
from datetime import date, timedelta

import pytest

pytest.importorskip("pyarrow")

from kerno import sources  # noqa: E402
from kerno.dataset import DAY_MS, build_day, day_start_ms  # noqa: E402
from kerno.engine import EngineConfig, SignalEngine, process_range  # noqa: E402
from kerno.ingest import write_trades  # noqa: E402
from kerno.sources import NotPublished, Source, parse_file  # noqa: E402
from kerno.validator import validate_pending  # noqa: E402

D = date(2026, 9, 20)
CFG = EngineConfig(min_history_returns=20)  # synthetic tape is far sparser than real BTC
DAYS = [D - timedelta(days=1), D, D + timedelta(days=1)]


def tape(seed, start_ms, end_ms, step=(800, 4000), start_id=1):
    rng = random.Random(seed)
    ts, price, i, out = start_ms, 60_000.0, start_id, []
    while True:
        ts += rng.randint(*step)
        if ts >= end_ms:
            return out
        move = rng.choice([-1, 0, 0, 1]) * 0.5
        if rng.random() < 0.03:
            move = rng.choice([-1, 1]) * rng.uniform(8, 30)
        price = round(max(1.0, price + move), 2)
        out.append({"id": i, "ts": ts, "price": price, "qty": round(rng.uniform(0.001, 1), 5),
                    "maker": rng.random() < 0.5})
        i += 1


def binance_zip(rows, micro=False, header=False):
    lines = ["id,price,qty,quote_qty,time,is_buyer_maker"] if header else []
    for r in rows:
        t = r["ts"] * 1000 if micro else r["ts"]
        cols = [r["id"], r["price"], r["qty"], round(r["price"] * r["qty"], 8), t, "true" if r["maker"] else "false"]
        if not header:
            cols.append("true")
        lines.append(",".join(map(str, cols)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("trades.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


def bybit_gz(rows):
    lines = ["timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional"]
    for r in rows:
        lines.append(f"{r['ts'] / 1000:.4f},BTCUSDT,{'Sell' if r['maker'] else 'Buy'},{r['qty']},{r['price']},"
                     f"PlusTick,{r['id']:08x}-aaaa,1,1,1")
    return gzip.compress(("\n".join(lines) + "\n").encode())


@pytest.fixture
def served(monkeypatch):
    """Serve synthetic dumps for 3 days x 3 sources through sources._get."""
    files: dict[str, bytes] = {}
    all_rows: dict[str, list] = {}
    for key, seed in (("binance-spot:BTCUSDT", 1), ("binance-um:BTCUSDT", 2), ("bybit:BTCUSDT", 3)):
        src = sources.parse_source(key)
        rows_all = []
        next_id = 1
        for day in DAYS:
            rows = tape(seed * 100 + day.day, day_start_ms(day), day_start_ms(day) + DAY_MS, start_id=next_id)
            next_id += len(rows)
            rows_all += rows
            if src.kind == "binance-spot":
                data = binance_zip(rows, micro=True)  # 2025+ spot format: microseconds, no header
            elif src.kind == "binance-um":
                data = binance_zip(rows, header=True)
            else:
                data = bybit_gz(rows)
            files[src.url(day)] = data
            if src.checksum_url(day):
                files[src.checksum_url(day)] = f"{hashlib.sha256(data).hexdigest()}  x.zip\n".encode()
        all_rows[key] = rows_all

    def fake_get(url, retries=4):
        if url not in files:
            raise NotPublished(url)
        return files[url]

    monkeypatch.setattr(sources, "_get", fake_get)
    return files, all_rows


def test_parsers_normalize_formats(served, tmp_path):
    files, rows = served
    for key in rows:
        src = sources.parse_source(key)
        path, prov = sources.fetch(src, D, tmp_path)
        t = parse_file(src, path)
        expected = [r for r in rows[key] if day_start_ms(D) <= r["ts"] < day_start_ms(D) + DAY_MS]
        assert t.num_rows == len(expected)
        assert t["event_time_ms"].to_pylist() == sorted(t["event_time_ms"].to_pylist())
        first = t.slice(0, 1).to_pylist()[0]
        assert first["event_time_ms"] == expected[0]["ts"]  # µs and float-seconds both land on exact ms
        assert first["side"] == ("sell" if expected[0]["maker"] else "buy")
        assert prov["checksum_verified_by_exchange"] == src.kind.startswith("binance")


def test_checksum_mismatch_is_rejected(served, tmp_path):
    files, _ = served
    src = sources.parse_source("binance-spot:BTCUSDT")
    files[src.checksum_url(D)] = b"0" * 64
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        sources.fetch(src, D, tmp_path)
    assert not list(tmp_path.rglob("*.zip"))  # corrupt download is not kept in the cache


def _canonical(src: Source, rows):
    return [{"exchange": src.exchange, "symbol": src.symbol,
             "exchange_trade_id": str(r["id"]) if src.exchange == "binance" else f"{r['id']:08x}-aaaa",
             "price": r["price"], "quantity": r["qty"], "side": "sell" if r["maker"] else "buy",
             "event_time_ms": r["ts"], "ingest_time_ms": r["ts"], "raw": None} for r in rows]


def test_daily_build_equals_continuous_db_pipeline(served, tmp_path):
    """The offline day equals: all trades in a DB -> continuous engine -> validator, restricted to day D."""
    import pyarrow.parquet as pq

    from kerno.db import Database

    files, rows = served
    src = sources.parse_source("binance-spot:BTCUSDT")
    manifest = build_day([src], D, tmp_path / "out", tmp_path / "cache", cost_bps=10, entry_delay_ms=250, config=CFG)
    assert manifest["failures"] == {}
    got = pq.read_table(tmp_path / "out" / "events" / "exchange=binance" / "symbol=BTCUSDT" / f"date={D}"
                        / "events.parquet").to_pylist()
    assert len(got) > 20

    db = Database(f"sqlite:///{tmp_path / 'ref.db'}")
    db.migrate()
    write_trades(db, _canonical(src, rows[src.key]), store_raw=False)
    process_range(db, SignalEngine("binance", "BTCUSDT", config=CFG), (0, ""), 2**62)
    validate_pending(db, 10, 250)
    start, end = day_start_ms(D), day_start_ms(D) + DAY_MS
    with db.connect() as c:
        ref = c.fetchall("SELECT * FROM signals WHERE event_time_ms >= ? AND event_time_ms < ? ORDER BY event_time_ms",
                         (start, end))
    assert [g["exchange_trade_id"] for g in got] == [r["exchange_trade_id"] for r in ref]
    for g, r in zip(got, ref):
        assert g["status"] == r["status"]
        assert g["ret_10s_bps"] == r["ret_10s_bps"] and g["ret_30s_bps"] == r["ret_30s_bps"]
        feats = json.loads(r["features"])
        assert all(g[f"f_{k}"] == v for k, v in feats.items())


def test_build_is_deterministic_and_complete(served, tmp_path):
    srcs = [sources.parse_source(k) for k in ("binance-spot:BTCUSDT", "binance-um:BTCUSDT", "bybit:BTCUSDT")]
    m1 = build_day(srcs, D, tmp_path / "a", tmp_path / "cache", 10, 250, CFG)
    m2 = build_day(srcs, D, tmp_path / "b", tmp_path / "cache2", 10, 250, CFG)
    h1 = {o["path"]: o["sha256"] for o in m1["outputs"]}
    assert h1 == {o["path"]: o["sha256"] for o in m2["outputs"]}
    assert any(p.startswith("basis/pair=BTCUSDT") for p in h1)
    assert any(p.startswith("summary/") for p in h1)
    assert len([p for p in h1 if p.startswith("events/")]) == 3
    assert {s["source"] for s in m1["sources"]} == {s.key for s in srcs}
    assert all(len(s["sha256"]) == 64 for s in m1["sources"])


def test_day_not_ready_is_reported(served, tmp_path):
    files, _ = served
    src = sources.parse_source("bybit:BTCUSDT")
    del files[src.url(D + timedelta(days=1))]
    m = build_day([src], D, tmp_path / "out", tmp_path / "cache", 10, 250)
    assert "not published" in m["failures"]["bybit:BTCUSDT"]
    assert m["outputs"] == []
