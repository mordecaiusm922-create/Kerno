"""
Immutable Parquet archive of raw trades.

The hot database only needs recent trades (the engine looks back 5 minutes,
the validator 35 seconds). Everything older is written to one Parquet file per
exchange/symbol/UTC day:

    <archive_dir>/exchange=binance/symbol=BTCUSDT/date=2026-05-14/trades.parquet

and, if KERNO_S3_BUCKET is set, uploaded to S3-compatible object storage
(Supabase Storage, Cloudflare R2, AWS S3). Each file is verified (row count and
SHA-256) and recorded in `archive_manifest` *before* anything is deleted from
the database. Trades are only deleted with --delete.

This replaces the old cleaner.py, which silently deleted everything older than
two hours.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kerno.config import Settings
from kerno.db import Database

logger = logging.getLogger("kerno.archive")

DAY_MS = 86_400_000
COLUMNS = ("exchange", "symbol", "exchange_trade_id", "price", "quantity", "side", "event_time_ms", "ingest_time_ms")


def _schema():
    import pyarrow as pa

    return pa.schema([
        ("exchange", pa.string()), ("symbol", pa.string()), ("exchange_trade_id", pa.string()),
        ("price", pa.float64()), ("quantity", pa.float64()), ("side", pa.string()),
        ("event_time_ms", pa.int64()), ("ingest_time_ms", pa.int64()),
    ])


def _day_str(day_start_ms: int) -> str:
    return datetime.fromtimestamp(day_start_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_day(db: Database, exchange: str, symbol: str, start: int, path: Path) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = _schema()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    n = 0
    with db.connect() as c, pq.ParquetWriter(tmp, schema, compression="zstd") as writer:
        buf: dict[str, list[Any]] = {k: [] for k in COLUMNS}
        rows = c.iter_rows(
            f"SELECT {', '.join(COLUMNS)} FROM trades WHERE exchange = ? AND symbol = ? "
            "AND event_time_ms >= ? AND event_time_ms < ? ORDER BY event_time_ms, exchange_trade_id",
            (exchange, symbol, start, start + DAY_MS),
        )
        for row in rows:
            for k in COLUMNS:
                buf[k].append(row[k])
            n += 1
            if len(buf["price"]) >= 200_000:
                writer.write_table(pa.table(buf, schema=schema))
                buf = {k: [] for k in COLUMNS}
        if buf["price"]:
            writer.write_table(pa.table(buf, schema=schema))
    written = pq.ParquetFile(tmp).metadata.num_rows
    if written != n:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"parquet verification failed for {path}: wrote {written}, expected {n}")
    tmp.replace(path)
    return n


def _upload(settings: Settings, path: Path, key: str) -> str:
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region or None,
    )
    s3.upload_file(str(path), settings.s3_bucket, key)
    head = s3.head_object(Bucket=settings.s3_bucket, Key=key)
    if int(head["ContentLength"]) != path.stat().st_size:
        raise RuntimeError(f"upload size mismatch for s3://{settings.s3_bucket}/{key}")
    return f"s3://{settings.s3_bucket}/{key}"


def archive(db: Database, settings: Settings, before_days: int = 7, delete: bool = False) -> list[dict[str, Any]]:
    if delete and before_days < 1:
        raise ValueError("refusing to delete trades younger than 1 day")
    today = int(time.time() * 1000) // DAY_MS * DAY_MS
    cutoff = today - before_days * DAY_MS
    done: list[dict[str, Any]] = []

    with db.connect() as c:
        streams = c.fetchall(
            "SELECT exchange, symbol, MIN(event_time_ms) AS first_ms FROM trades "
            "WHERE event_time_ms < ? GROUP BY exchange, symbol",
            (cutoff,),
        )

    for s in streams:
        exchange, symbol = s["exchange"], s["symbol"]
        day = int(s["first_ms"]) // DAY_MS * DAY_MS
        while day < cutoff:
            ds = _day_str(day)
            with db.connect() as c:
                count = int(c.scalar(
                    "SELECT COUNT(*) FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? AND event_time_ms < ?",
                    (exchange, symbol, day, day + DAY_MS),
                ))
                prior = c.fetchone(
                    "SELECT rows, uri FROM archive_manifest WHERE exchange = ? AND symbol = ? AND day = ?",
                    (exchange, symbol, ds),
                )
            if count == 0:
                day += DAY_MS
                continue

            rel = Path(f"exchange={exchange}") / f"symbol={symbol}" / f"date={ds}" / "trades.parquet"
            if prior is None or int(prior["rows"]) != count:
                path = settings.archive_dir / rel
                n = _write_day(db, exchange, symbol, day, path)
                digest = _sha256(path)
                uri = _upload(settings, path, rel.as_posix()) if settings.s3_bucket else str(path)
                with db.connect() as c:
                    c.execute(
                        "INSERT INTO archive_manifest (exchange, symbol, day, rows, sha256, uri, created_at_ms) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (exchange, symbol, day) DO UPDATE SET "
                        "rows = excluded.rows, sha256 = excluded.sha256, uri = excluded.uri, "
                        "created_at_ms = excluded.created_at_ms",
                        (exchange, symbol, ds, n, digest, uri, int(time.time() * 1000)),
                    )
                logger.info("archived %s %s %s: %d trades -> %s", exchange, symbol, ds, n, uri)
                done.append({"exchange": exchange, "symbol": symbol, "day": ds, "rows": n, "uri": uri})
                archived_rows = n
            else:
                archived_rows = int(prior["rows"])

            if delete:
                if archived_rows != count:
                    raise RuntimeError(f"{exchange} {symbol} {ds}: archive has {archived_rows} rows, db {count}; not deleting")
                with db.connect() as c:
                    deleted = c.execute(
                        "DELETE FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? AND event_time_ms < ?",
                        (exchange, symbol, day, day + DAY_MS),
                    )
                logger.info("deleted %d archived trades %s %s %s from hot storage", deleted, exchange, symbol, ds)
            day += DAY_MS
    return done

