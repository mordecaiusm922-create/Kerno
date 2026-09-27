"""
Daily open dataset built from free public dumps. No servers, no database.

For each source and UTC day D:

  1. download D-1, D and D+1 (checksums verified; cached on disk)
  2. warm the engine on the last WARMUP_MS of D-1 (state then equals a continuous run)
  3. run the engine over D -> events with point-in-time features
  4. resolve each event's outcome from later trades (D and the start of D+1),
     with exactly the validator's rules (`validator.resolve_with`)
  5. write Parquet + a provenance manifest (source SHA-256s, output SHA-256s,
     code/feature/engine versions, parameters)

Outputs, under --out:

  events/exchange=<ex>/symbol=<sym>/date=<D>/events.parquet   one row per event, features as columns
  summary/date=<D>/summary.parquet                             one row per stream: counts and headline stats
  basis/pair=<SYM>/date=<D>/basis_1m.parquet                   Binance spot vs USDT-M perp, 1-minute closes
  manifest/date=<D>.json                                       provenance

Raw trades are *not* republished: they remain available from the exchanges.
Only derived data is published (see docs/dataset.md for why).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from kerno import __version__
from kerno.engine import ENGINE_VERSION, WARMUP_MS, EngineConfig, SignalEngine
from kerno.features import FEATURE_NAMES, FEATURE_VERSION
from kerno.sources import NotPublished, Source, fetch, parse_file
from kerno.validator import HORIZONS_MS, MAX_GAP_MS, resolve_with

logger = logging.getLogger("kerno.dataset")

DAY_MS = 86_400_000
LOOKAHEAD_MS = max(HORIZONS_MS) + MAX_GAP_MS + 10_000
BASIS_STALE_MS = 60_000


def day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(source: Source, day: date, cache_dir: Path, provenance: list[dict]):
    path, prov = fetch(source, day, cache_dir)
    table = parse_file(source, path)
    provenance.append({"source": source.key, "day": day.isoformat(), "rows": len(table), **prov})
    return table


def _series_lookup(times, prices):
    """Same semantics as validator.series_lookup, on numpy arrays."""
    import numpy as np

    def lookup(ts: int) -> float | None:
        i = int(np.searchsorted(times, ts, side="left"))
        if i == len(times) or int(times[i]) - ts > MAX_GAP_MS:
            return None
        return float(prices[i])

    return lookup


def process_source(source: Source, day: date, cache_dir: Path, cost_bps: float, entry_delay_ms: int,
                   config: EngineConfig, provenance: list[dict]) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.compute as pc

    start, end = day_start_ms(day), day_start_ms(day) + DAY_MS
    cur = _load(source, day, cache_dir, provenance)
    nxt = _load(source, day + timedelta(days=1), cache_dir, provenance)  # NotPublished -> day not ready
    try:
        prev = _load(source, day - timedelta(days=1), cache_dir, provenance)
    except NotPublished:
        prev = None
        logger.warning("%s %s: no previous day published; first minutes are not warmed", source.key, day)

    in_day = pc.and_(pc.greater_equal(cur["event_time_ms"], start), pc.less(cur["event_time_ms"], end))
    outside = len(cur) - (pc.sum(in_day).as_py() or 0)
    if outside:
        logger.warning("%s %s: %d trades outside the UTC day ignored", source.key, day, outside)
    cur = cur.filter(in_day)

    engine = SignalEngine(source.exchange, source.symbol, config=config)
    if prev is not None:
        warm = prev.filter(pc.greater_equal(prev["event_time_ms"], start - WARMUP_MS))
        for batch in warm.to_batches(max_chunksize=100_000):
            for t in batch.to_pylist():
                engine.warm(t)
        del prev, warm

    events: list[dict[str, Any]] = []
    for batch in cur.to_batches(max_chunksize=100_000):
        for t in batch.to_pylist():
            rec = engine.on_trade(t)
            if rec:
                events.append(rec)

    head = nxt.filter(pc.less(nxt["event_time_ms"], end + LOOKAHEAD_MS))
    series = pa.concat_tables([cur.select(["event_time_ms", "price"]), head.select(["event_time_ms", "price"])])
    times = series["event_time_ms"].to_numpy()
    prices = series["price"].to_numpy()
    lookup = _series_lookup(times, prices)
    for ev in events:
        ev.update(resolve_with(lookup, ev["event_time_ms"], None, cost_bps, entry_delay_ms))

    return {"source": source, "events": events, "n_trades": len(cur),
            "times": cur["event_time_ms"].to_numpy(), "prices": cur["price"].to_numpy(),
            "volume": float(pc.sum(cur["quantity"]).as_py() or 0.0)}


EVENT_COLUMNS = ("exchange", "symbol", "exchange_trade_id", "event_time_ms", "price", "spike_bps", "spike_dir",
                 "bucket", "status", "price_entry", "price_10s", "price_30s", "ret_10s_bps", "ret_30s_bps",
                 "feature_version", "engine_version")


def _events_table(events: list[dict[str, Any]]):
    import pyarrow as pa

    cols: dict[str, list] = {c: [] for c in EVENT_COLUMNS}
    feats: dict[str, list] = {f: [] for f in FEATURE_NAMES}
    for ev in events:
        for c in EVENT_COLUMNS:
            cols[c].append(ev.get(c))
        fv = json.loads(ev["features"])
        for f in FEATURE_NAMES:
            feats[f].append(fv[f])
    schema = pa.schema(
        [("exchange", pa.string()), ("symbol", pa.string()), ("exchange_trade_id", pa.string()),
         ("event_time_ms", pa.int64()), ("price", pa.float64()), ("spike_bps", pa.float64()),
         ("spike_dir", pa.int8()), ("bucket", pa.string()), ("status", pa.string()),
         ("price_entry", pa.float64()), ("price_10s", pa.float64()), ("price_30s", pa.float64()),
         ("ret_10s_bps", pa.float64()), ("ret_30s_bps", pa.float64()),
         ("feature_version", pa.string()), ("engine_version", pa.string())]
        + [(f"f_{f}", pa.float64()) for f in FEATURE_NAMES]
    )
    data = {**cols, **{f"f_{f}": v for f, v in feats.items()}}
    return pa.table(data, schema=schema)


def _summary_row(day: date, res: dict[str, Any], cost_bps: float) -> dict[str, Any]:
    s: Source = res["source"]
    ev = res["events"]
    resolved = [e for e in ev if e.get("status") == "RESOLVED"]
    moved = [e for e in resolved if e["ret_10s_bps"] != 0]
    cont = [e for e in moved if (e["ret_10s_bps"] > 0) == (e["spike_dir"] > 0)]
    return {
        "date": day.isoformat(),
        "exchange": s.exchange,
        "symbol": s.symbol,
        "n_trades": res["n_trades"],
        "volume": res["volume"],
        "n_events": len(ev),
        "n_resolved": len(resolved),
        "n_medium": sum(1 for e in ev if e["bucket"] == "MEDIUM"),
        "n_large": sum(1 for e in ev if e["bucket"] == "LARGE"),
        "n_extreme": sum(1 for e in ev if e["bucket"] == "EXTREME"),
        # share of events whose 10s move continued the spike direction (moves of exactly 0 excluded)
        "continuation_rate_10s": round(len(cont) / len(moved), 6) if moved else None,
        "mean_abs_ret_10s_bps": round(sum(abs(e["ret_10s_bps"]) for e in resolved) / len(resolved), 6) if resolved else None,
        "share_abs_ret_10s_gt_cost": round(sum(1 for e in resolved if abs(e["ret_10s_bps"]) > cost_bps) / len(resolved), 6)
        if resolved else None,
        "cost_bps": cost_bps,
        "feature_version": FEATURE_VERSION,
    }


def _basis_table(day: date, spot: dict[str, Any], perp: dict[str, Any]):
    import numpy as np
    import pyarrow as pa

    start = day_start_ms(day)
    closes = start + 60_000 * np.arange(1, 1441, dtype=np.int64)
    rows: dict[str, list] = {k: [] for k in ("minute_start_ms", "spot_price", "spot_ts_ms", "perp_price",
                                             "perp_ts_ms", "basis_bps")}
    si = np.searchsorted(spot["times"], closes, side="left") - 1
    pi = np.searchsorted(perp["times"], closes, side="left") - 1
    for k, close in enumerate(closes):
        if si[k] < 0 or pi[k] < 0:
            continue
        st, pt = int(spot["times"][si[k]]), int(perp["times"][pi[k]])
        if close - st > BASIS_STALE_MS or close - pt > BASIS_STALE_MS:
            continue
        sp, pp = float(spot["prices"][si[k]]), float(perp["prices"][pi[k]])
        rows["minute_start_ms"].append(int(close) - 60_000)
        rows["spot_price"].append(sp)
        rows["spot_ts_ms"].append(st)
        rows["perp_price"].append(pp)
        rows["perp_ts_ms"].append(pt)
        rows["basis_bps"].append(round((pp - sp) / sp * 1e4, 6))
    return pa.table(rows)


def _write(table, path: Path, outputs: list[dict], root: Path) -> None:
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    outputs.append({"path": path.relative_to(root).as_posix(), "rows": table.num_rows, "sha256": _sha256(path)})


def build_day(sources: list[Source], day: date, out_dir: Path, cache_dir: Path, cost_bps: float,
              entry_delay_ms: int, config: EngineConfig | None = None) -> dict[str, Any]:
    import pyarrow as pa

    config = config or EngineConfig()
    t0 = time.time()
    provenance: list[dict] = []
    outputs: list[dict] = []
    results: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for s in sources:
        try:
            res = process_source(s, day, cache_dir, cost_bps, entry_delay_ms, config, provenance)
        except NotPublished as exc:
            failures[s.key] = f"not published yet: {exc}"
            logger.warning("%s %s: %s", s.key, day, failures[s.key])
            continue
        except Exception as exc:
            failures[s.key] = f"{type(exc).__name__}: {exc}"
            logger.exception("%s %s failed", s.key, day)
            continue
        results[s.key] = res
        _write(_events_table(res["events"]),
               out_dir / "events" / f"exchange={s.exchange}" / f"symbol={s.symbol}" / f"date={day}" / "events.parquet",
               outputs, out_dir)
        logger.info("%s %s: %d trades -> %d events", s.key, day, res["n_trades"], len(res["events"]))

    if results:
        summary = [_summary_row(day, r, cost_bps) for r in results.values()]
        _write(pa.Table.from_pylist(summary), out_dir / "summary" / f"date={day}" / "summary.parquet", outputs, out_dir)
    for res in results.values():
        s = res["source"]
        perp = results.get(f"binance-um:{s.native}")
        if s.kind == "binance-spot" and perp:
            _write(_basis_table(day, res, perp),
                   out_dir / "basis" / f"pair={s.native}" / f"date={day}" / "basis_1m.parquet", outputs, out_dir)

    manifest = {
        "date": day.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": {"kerno_version": __version__, "git_sha": os.getenv("GITHUB_SHA"),
                 "feature_version": FEATURE_VERSION, "engine_version": ENGINE_VERSION},
        "parameters": {"cost_bps": cost_bps, "entry_delay_ms": entry_delay_ms, "engine": asdict(config),
                       "horizons_ms": list(HORIZONS_MS), "max_gap_ms": MAX_GAP_MS, "warmup_ms": WARMUP_MS},
        "sources": provenance,
        "outputs": outputs,
        "failures": failures,
        "seconds": round(time.time() - t0, 1),
    }
    mpath = out_dir / "manifest" / f"date={day}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def prune_cache(cache_dir: Path, keep_from: date) -> None:
    """Delete cached dumps older than `keep_from` (a backfill otherwise fills the disk)."""
    for f in cache_dir.rglob("*"):
        if not f.is_file():
            continue
        stem = f.name.split(".")[0]
        try:
            d = date.fromisoformat(stem[-10:])
        except ValueError:
            continue
        if d < keep_from:
            f.unlink()


def build_range(sources: list[Source], start: date, end: date, out_dir: Path, cache_dir: Path, cost_bps: float,
                entry_delay_ms: int, keep_cache: bool = False) -> list[dict[str, Any]]:
    manifests = []
    day = start
    while day <= end:
        manifests.append(build_day(sources, day, out_dir, cache_dir, cost_bps, entry_delay_ms))
        if not keep_cache:
            prune_cache(cache_dir, day)  # the next day still needs `day` as its warm-up
        day += timedelta(days=1)
    return manifests


def publish(out_dir: Path, repo_id: str, token: str | None = None) -> str:
    """Upload the dataset folder (and card) to a Hugging Face dataset repo."""
    from huggingface_hub import HfApi

    api = HfApi(token=token or os.getenv("HF_TOKEN"))
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    card = out_dir / "README.md"
    if not card.exists():
        from importlib import resources

        card.write_text((resources.files("kerno") / "dataset_card.md").read_text(encoding="utf-8"), encoding="utf-8")
    commit = api.upload_folder(
        folder_path=str(out_dir), repo_id=repo_id, repo_type="dataset",
        commit_message=f"kerno dataset update ({datetime.now(UTC).date()})",
        allow_patterns=["README.md", "events/**", "summary/**", "basis/**", "manifest/**"],
    )
    return str(commit)
