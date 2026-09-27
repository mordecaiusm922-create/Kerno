"""
Free public historical trade dumps, one file per instrument per UTC day.

  binance-spot  https://data.binance.vision/data/spot/daily/trades/<SYM>/<SYM>-trades-<DAY>.zip
  binance-um    https://data.binance.vision/data/futures/um/daily/trades/<SYM>/<SYM>-trades-<DAY>.zip
  bybit         https://public.bybit.com/trading/<SYM>/<SYM><DAY>.csv.gz

Binance publishes a `.CHECKSUM` (SHA-256) next to every file; it is verified
before parsing. Bybit publishes none, so the SHA-256 of what was downloaded is
recorded instead. Either way every output can be traced to exact source bytes.

Files are parsed with pyarrow into the canonical trade columns, sorted by
(event_time_ms, exchange_trade_id): the same order the engine uses everywhere.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import logging
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("kerno.sources")

BINANCE_BASE = "https://data.binance.vision/data"
BYBIT_BASE = "https://public.bybit.com/trading"
USER_AGENT = "kerno-dataset/1.0 (+https://github.com/mordecaiusm922-create/Kerno)"
COLUMNS = ("exchange_trade_id", "price", "quantity", "side", "event_time_ms")


class NotPublished(Exception):
    """The file for that day does not exist (yet)."""


@dataclass(frozen=True)
class Source:
    kind: str  # binance-spot | binance-um | bybit
    native: str  # e.g. BTCUSDT

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.native}"

    @property
    def exchange(self) -> str:
        return "bybit" if self.kind == "bybit" else "binance"

    @property
    def symbol(self) -> str:
        """Canonical symbol, collision-safe across spot and perpetuals (docs/connectors.md, Finding #2)."""
        return self.native if self.kind == "binance-spot" else f"{self.native}-PERP"

    def url(self, day: date) -> str:
        d = day.isoformat()
        if self.kind == "binance-spot":
            return f"{BINANCE_BASE}/spot/daily/trades/{self.native}/{self.native}-trades-{d}.zip"
        if self.kind == "binance-um":
            return f"{BINANCE_BASE}/futures/um/daily/trades/{self.native}/{self.native}-trades-{d}.zip"
        return f"{BYBIT_BASE}/{self.native}/{self.native}{d}.csv.gz"

    def checksum_url(self, day: date) -> str | None:
        return self.url(day) + ".CHECKSUM" if self.kind.startswith("binance") else None


def parse_source(spec: str) -> Source:
    kind, _, native = spec.partition(":")
    if kind not in ("binance-spot", "binance-um", "bybit") or not native:
        raise ValueError(f"bad source {spec!r}; expected binance-spot:SYM, binance-um:SYM or bybit:SYM")
    return Source(kind, native.upper())


# ── download ────────────────────────────────────────────────────────────────


def _get(url: str, retries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotPublished(url) from None
            if exc.code in (403, 451):
                raise RuntimeError(f"{url}: HTTP {exc.code} (geo-blocked from this network?)") from None
            err: Exception = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            err = exc
        wait = 2 ** (attempt + 1)
        logger.warning("download failed (%s), retrying in %ss: %s", err, wait, url)
        time.sleep(wait)
    raise RuntimeError(f"download failed after {retries} attempts: {url}")


def fetch(source: Source, day: date, cache_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Download (or reuse from cache) one day's file; verify its checksum. Returns (path, provenance)."""
    url = source.url(day)
    path = cache_dir / source.kind / source.native / url.rsplit("/", 1)[1]
    if not path.exists():
        data = _get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    verified = False
    if (curl := source.checksum_url(day)) is not None:
        expected = _get(curl).decode().split()[0].strip().lower()
        if expected != digest:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"checksum mismatch for {url}: exchange says {expected}, got {digest}")
        verified = True
    return path, {"url": url, "sha256": digest, "checksum_verified_by_exchange": verified,
                  "bytes": path.stat().st_size}


# ── parsing ─────────────────────────────────────────────────────────────────


def _open_text(path: Path) -> io.BufferedIOBase:
    if path.suffix == ".zip":
        zf = zipfile.ZipFile(path)
        return zf.open(zf.namelist()[0])
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def parse_file(source: Source, path: Path):
    """Parse a dump into a pyarrow Table with COLUMNS, sorted by (event_time_ms, exchange_trade_id)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as pacsv

    with _open_text(path) as f:
        raw = f.read()
    if source.kind.startswith("binance"):
        has_header = raw[:1].isalpha()
        names = ["id", "price", "qty", "quote_qty", "time", "is_buyer_maker", "is_best_match"]
        opts = pacsv.ReadOptions(skip_rows=1 if has_header else 0, column_names=names[:_ncols(raw, has_header)])
        conv = pacsv.ConvertOptions(column_types={"id": pa.int64(), "price": pa.float64(), "qty": pa.float64(),
                                                  "time": pa.int64(), "is_buyer_maker": pa.bool_()})
        t = pacsv.read_csv(io.BytesIO(raw), read_options=opts, convert_options=conv)
        ts = t["time"]
        if len(t) and pc.max(ts).as_py() > 10**14:  # spot files switched to microseconds in 2025
            ts = pc.divide(ts, 1000)
        out = pa.table({
            "exchange_trade_id": pc.cast(t["id"], pa.string()),
            "price": t["price"],
            "quantity": t["qty"],
            # buyer is maker -> the aggressor sold
            "side": pc.if_else(t["is_buyer_maker"], "sell", "buy"),
            "event_time_ms": pc.cast(ts, pa.int64()),
        })
    else:
        t = pacsv.read_csv(io.BytesIO(raw), convert_options=pacsv.ConvertOptions(
            column_types={"timestamp": pa.float64(), "price": pa.float64(), "size": pa.float64()}))
        # seconds with sub-ms decimals -> floor to ms (epsilon guards 0.9999... float artefacts)
        ms = pc.floor(pc.add(pc.multiply(t["timestamp"], 1000.0), 1e-6))
        out = pa.table({
            "exchange_trade_id": pc.cast(t["trdMatchID"], pa.string()),
            "price": t["price"],
            "quantity": t["size"],
            "side": pc.utf8_lower(t["side"]),
            "event_time_ms": pc.cast(ms, pa.int64()),
        })
    bad = pc.sum(pc.invert(pc.and_(pc.greater(out["price"], 0), pc.greater_equal(out["quantity"], 0)))).as_py() or 0
    if bad:
        logger.warning("%s: dropping %d rows with invalid price/quantity", path.name, bad)
        out = out.filter(pc.and_(pc.greater(out["price"], 0), pc.greater_equal(out["quantity"], 0)))
    return out.sort_by([("event_time_ms", "ascending"), ("exchange_trade_id", "ascending")])


def _ncols(raw: bytes, has_header: bool) -> int:
    lines = raw.split(b"\n", 2)
    sample = lines[1] if has_header and len(lines) > 1 else lines[0]
    return sample.count(b",") + 1
