"""
kerno <command>

  init-db                     apply schema migrations to DATABASE_URL
  ingest                      stream trades from exchanges into the database
  engine | validate | basis   run one background worker
  run-all                     ingest + engine + validator + basis in one process
  api                         serve the HTTP API
  replay                      (re)compute signals over stored history
  train                       train + validate a model from resolved signals
  archive                     export old trades to Parquet (optionally delete them)
  migrate-sqlite PATH         copy a legacy local kerno.db into DATABASE_URL
  dataset build|publish       daily open dataset from free public dumps (no server needed)
  keys create|list|revoke     manage API keys
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from kerno.config import get_settings, parse_streams
from kerno.connectors import canonical_symbol
from kerno.db import get_db

logger = logging.getLogger("kerno")


def _stream_pairs(streams: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(ex, canonical_symbol(ex, s)) for ex, syms in streams.items() for s in syms]


def _install_stop(stop_async: asyncio.Event | None, stop_thread: threading.Event) -> None:
    def handler(*_):
        stop_thread.set()
        if stop_async is not None:
            loop.call_soon_threadsafe(stop_async.set)

    loop = asyncio.get_event_loop() if stop_async is not None else None
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # not main thread / unsupported on this platform
            pass


def _run_threads(targets: list[tuple[str, callable]], stop: threading.Event) -> list[threading.Thread]:
    threads = [threading.Thread(target=fn, name=name, daemon=True) for name, fn in targets]
    for t in threads:
        t.start()
    return threads


def cmd_run(args, settings, workers: set[str]) -> None:
    from kerno.basis import run_basis
    from kerno.engine import run_engine
    from kerno.ingest import run_ingest
    from kerno.model import ModelRegistry
    from kerno.validator import run_validator

    db = get_db(settings.database_url)
    streams = parse_streams(args.streams) if getattr(args, "streams", None) else settings.streams
    stop = threading.Event()
    targets = []
    if "engine" in workers:
        models = ModelRegistry.load(settings.models_dir)
        targets.append(("engine", lambda: run_engine(db, _stream_pairs(streams), models, stop)))
    if "validate" in workers:
        targets.append(("validator", lambda: run_validator(db, settings.cost_bps, settings.entry_delay_ms, stop)))
    if "basis" in workers:
        targets.append(("basis", lambda: run_basis(db, stop)))

    if "ingest" in workers:
        async def main():
            astop = asyncio.Event()
            _install_stop(astop, stop)
            threads = _run_threads(targets, stop)
            await run_ingest(db, streams, astop, store_raw=settings.store_raw)
            stop.set()
            for t in threads:
                t.join(timeout=10)

        asyncio.run(main())
    else:
        _install_stop(None, stop)
        threads = _run_threads(targets, stop)
        while not stop.is_set():
            stop.wait(1)
        for t in threads:
            t.join(timeout=10)


def cmd_replay(args, settings) -> None:
    from kerno.engine import SignalEngine, process_range, warm_engine
    from kerno.model import ModelRegistry

    db = get_db(settings.database_url)
    models = ModelRegistry.load(settings.models_dir) if args.score else None
    engine = SignalEngine(args.exchange, args.symbol, models)
    with db.connect() as c:
        first = c.scalar("SELECT MIN(event_time_ms) FROM trades WHERE exchange = ? AND symbol = ?",
                         (args.exchange, args.symbol))
    if first is None:
        sys.exit(f"no trades for {args.exchange}:{args.symbol}")
    start = max(int(first), args.from_ms or 0)
    warm_engine(db, engine, (start - 1, "￿"))
    engine._last_event_ts = None
    n, cursor = process_range(db, engine, (start - 1, "￿"), args.to_ms or 2**62)
    print(json.dumps({"signals_written": n, "last_cursor": list(cursor)}))


DEFAULT_DATASET_SOURCES = "binance-spot:BTCUSDT,binance-um:BTCUSDT,binance-spot:ETHUSDT,binance-um:ETHUSDT,bybit:BTCUSDT"


def cmd_dataset(args, settings) -> None:
    from datetime import UTC, date, datetime, timedelta

    from kerno.dataset import build_range, publish
    from kerno.sources import parse_source

    if args.dataset_cmd == "publish":
        print(json.dumps({"commit": publish(args.out, args.repo)}))
        return
    if args.date:
        start = end = date.fromisoformat(args.date)
    elif args.start:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else start
    else:
        start = end = datetime.now(UTC).date() - timedelta(days=2)
    if (end - start).days + 1 > args.max_days:
        sys.exit(f"range of {(end - start).days + 1} days exceeds --max-days {args.max_days}")
    sources = [parse_source(s) for s in args.sources.split(",") if s.strip()]
    manifests = build_range(sources, start, end, args.out, args.cache, settings.cost_bps, settings.entry_delay_ms)
    report = [{"date": m["date"], "outputs": len(m["outputs"]), "failures": m["failures"], "seconds": m["seconds"]}
              for m in manifests]
    print(json.dumps(report, indent=2))
    if any(m["failures"] for m in manifests):
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    p = argparse.ArgumentParser(prog="kerno", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    for name in ("ingest", "run-all"):
        sp = sub.add_parser(name)
        sp.add_argument("--streams", help="e.g. 'binance:BTCUSDT,ETHUSDT;bybit:BTCUSDT' (default: KERNO_STREAMS)")
    for name in ("engine", "validate", "basis"):
        sp = sub.add_parser(name)
        sp.add_argument("--streams")
        if name == "validate":
            sp.add_argument("--once", action="store_true", help="resolve what is resolvable now, then exit")
    sp = sub.add_parser("api")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp = sub.add_parser("replay")
    sp.add_argument("--exchange", required=True)
    sp.add_argument("--symbol", required=True, help="canonical symbol as stored, e.g. BTCUSDT-PERP for bybit")
    sp.add_argument("--from-ms", type=int)
    sp.add_argument("--to-ms", type=int)
    sp.add_argument("--score", action="store_true", help="also score with the deployed models")
    sp = sub.add_parser("train")
    sp.add_argument("--exchange", required=True)
    sp.add_argument("--symbol", required=True)
    sp.add_argument("--stage", choices=["1", "2", "all"], default="all")
    sp.add_argument("--horizon", type=int, choices=[10, 30], default=10)
    sp.add_argument("--force", action="store_true", help="deploy even if the validation gate fails")
    sp = sub.add_parser("archive")
    sp.add_argument("--before-days", type=int, default=7)
    sp.add_argument("--delete", action="store_true", help="delete trades from the database after verified archive")
    sp = sub.add_parser("migrate-sqlite")
    sp.add_argument("path", type=Path)
    sp.add_argument("--since-days", type=float)
    sp.add_argument("--with-raw", action="store_true")
    sp = sub.add_parser("dataset", help="build/publish the daily open dataset from public dumps")
    ds = sp.add_subparsers(dest="dataset_cmd", required=True)
    db_ = ds.add_parser("build")
    db_.add_argument("--date", help="UTC day YYYY-MM-DD (default: two days ago)")
    db_.add_argument("--start")
    db_.add_argument("--end")
    db_.add_argument("--sources", default=DEFAULT_DATASET_SOURCES,
                     help=f"comma-separated kind:SYMBOL (default {DEFAULT_DATASET_SOURCES})")
    db_.add_argument("--out", type=Path, default=Path("dataset"))
    db_.add_argument("--cache", type=Path, default=Path(".dump-cache"))
    db_.add_argument("--max-days", type=int, default=31)
    dp = ds.add_parser("publish")
    dp.add_argument("--out", type=Path, default=Path("dataset"))
    dp.add_argument("--repo", required=True, help="Hugging Face dataset repo id, e.g. user/kerno-microstructure")
    sp = sub.add_parser("keys")
    ks = sp.add_subparsers(dest="keys_cmd", required=True)
    kc = ks.add_parser("create")
    kc.add_argument("name")
    kc.add_argument("--rate", type=int, help="requests per minute")
    ks.add_parser("list")
    kr = ks.add_parser("revoke")
    kr.add_argument("id", type=int)

    args = p.parse_args(argv)

    if args.cmd == "init-db":
        applied = get_db(settings.database_url).migrate()
        print(f"migrations applied: {applied or 'none (up to date)'}")
    elif args.cmd == "ingest":
        cmd_run(args, settings, {"ingest"})
    elif args.cmd == "run-all":
        cmd_run(args, settings, {"ingest", "engine", "validate", "basis"})
    elif args.cmd == "validate" and args.once:
        from kerno.validator import validate_pending

        n = validate_pending(get_db(settings.database_url), settings.cost_bps, settings.entry_delay_ms)
        print(json.dumps({"resolved": n}))
    elif args.cmd in ("engine", "validate", "basis"):
        cmd_run(args, settings, {args.cmd})
    elif args.cmd == "api":
        import uvicorn

        from kerno.api import create_app

        # Proxy headers (client IP, https) are only trusted from FORWARDED_ALLOW_IPS
        # (uvicorn reads it from the environment; default 127.0.0.1). Behind a
        # platform load balancer, set it to that proxy's address range.
        uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=True)
    elif args.cmd == "replay":
        cmd_replay(args, settings)
    elif args.cmd == "train":
        from kerno.train import train_stage

        db = get_db(settings.database_url)
        stages = [1, 2] if args.stage == "all" else [int(args.stage)]
        for st in stages:
            res = train_stage(db, args.exchange, args.symbol, st, settings.models_dir, settings.cost_bps,
                              horizon=args.horizon, force=args.force)
            print(json.dumps({"stage": st, **res}, indent=2))
    elif args.cmd == "archive":
        from kerno.archive import archive

        done = archive(get_db(settings.database_url), settings, args.before_days, args.delete)
        print(json.dumps(done, indent=2))
    elif args.cmd == "migrate-sqlite":
        from kerno.migrate_sqlite import migrate

        t0 = time.time()
        report = migrate(args.path, get_db(settings.database_url), args.since_days, args.with_raw)
        print(json.dumps({**report, "seconds": round(time.time() - t0, 1)}, indent=2))
    elif args.cmd == "dataset":
        cmd_dataset(args, settings)
    elif args.cmd == "keys":
        from kerno.auth import create_key, list_keys, revoke_key

        db = get_db(settings.database_url)
        if args.keys_cmd == "create":
            key = create_key(db, args.name, args.rate)
            print("API key (shown once, store it in a password manager):")
            print(key)
        elif args.keys_cmd == "list":
            for k in list_keys(db):
                print(json.dumps(k))
        else:
            print("revoked" if revoke_key(db, args.id) else "no active key with that id")


if __name__ == "__main__":
    main()
