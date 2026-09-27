"""
Outcome resolution for signals.

For each PENDING signal the validator looks only at trades strictly after the
signal trade:

  entry  = first trade at or after event + ENTRY_DELAY_MS   (you can't trade the print you reacted to)
  exit_h = first trade at or after event + h,  h in {10s, 30s}

  ret_h_bps = (exit_h - entry) / entry * 1e4                (market move)
  pnl_h_bps = predicted_dir * ret_h_bps - cost_bps          (what the signal would have earned)

A signal is only resolved once the stream has data past the 30s horizon
(data watermark, not wall clock), so a feed outage can't produce fake
outcomes. If the exit trade is more than MAX_GAP_MS late the signal is marked
NO_DATA instead of being scored against a stale price.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from kerno.db import Conn, Database

logger = logging.getLogger("kerno.validator")

HORIZONS_MS = (10_000, 30_000)
MAX_GAP_MS = 5_000

_FIRST_AFTER = (
    "SELECT price, event_time_ms FROM trades "
    "WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? "
    "ORDER BY event_time_ms, exchange_trade_id LIMIT 1"
)


def _first_after(c: Conn, exchange: str, symbol: str, ts: int) -> dict[str, Any] | None:
    row = c.fetchone(_FIRST_AFTER, (exchange, symbol, ts))
    if row is None or int(row["event_time_ms"]) - ts > MAX_GAP_MS:
        return None
    return row


def resolve_signal(c: Conn, sig: dict[str, Any], cost_bps: float, entry_delay_ms: int) -> dict[str, Any]:
    ex, sym, t0 = sig["exchange"], sig["symbol"], int(sig["event_time_ms"])
    entry = _first_after(c, ex, sym, t0 + entry_delay_ms)
    exits = [_first_after(c, ex, sym, t0 + h) for h in HORIZONS_MS]
    if entry is None or any(e is None for e in exits):
        return {"status": "NO_DATA"}

    p0 = float(entry["price"])
    out: dict[str, Any] = {"status": "RESOLVED", "price_entry": p0, "cost_bps": cost_bps}
    direction = sig.get("predicted_dir")
    for h, e in zip(HORIZONS_MS, exits):
        tag = f"{h // 1000}s"
        ret = (float(e["price"]) - p0) / p0 * 1e4
        out[f"price_{tag}"] = float(e["price"])
        out[f"ret_{tag}_bps"] = round(ret, 6)
        out[f"pnl_{tag}_bps"] = round(direction * ret - cost_bps, 6) if direction else None
    return out


def validate_pending(db: Database, cost_bps: float, entry_delay_ms: int, batch: int = 1_000) -> int:
    """Resolve every signal whose 30s horizon is covered by ingested data. Returns count resolved."""
    resolved = 0
    with db.connect() as c:
        streams = c.fetchall("SELECT DISTINCT exchange, symbol FROM signals WHERE status = 'PENDING'")
        watermarks = {}
        for s in streams:
            wm = c.scalar("SELECT MAX(event_time_ms) FROM trades WHERE exchange = ? AND symbol = ?",
                          (s["exchange"], s["symbol"]))
            if wm is not None:
                watermarks[(s["exchange"], s["symbol"])] = int(wm)
    for (exchange, symbol), wm in watermarks.items():
        # the exit trade may arrive up to MAX_GAP_MS after the horizon
        cutoff = wm - max(HORIZONS_MS) - MAX_GAP_MS
        while True:
            with db.connect() as c:
                pending = c.fetchall(
                    "SELECT id, exchange, symbol, event_time_ms, predicted_dir FROM signals "
                    "WHERE status = 'PENDING' AND exchange = ? AND symbol = ? AND event_time_ms <= ? "
                    "ORDER BY event_time_ms LIMIT ?",
                    (exchange, symbol, cutoff, batch),
                )
                now = int(time.time() * 1000)
                for sig in pending:
                    res = resolve_signal(c, sig, cost_bps, entry_delay_ms)
                    cols = sorted(res)
                    c.execute(
                        f"UPDATE signals SET {', '.join(f'{k} = ?' for k in cols)}, resolved_at_ms = ? WHERE id = ?",
                        [res[k] for k in cols] + [now, sig["id"]],
                    )
            resolved += len(pending)
            if len(pending) < batch:
                break
    return resolved


def run_validator(db: Database, cost_bps: float, entry_delay_ms: int, stop: threading.Event,
                  poll_s: float = 5.0) -> None:
    while not stop.is_set():
        try:
            n = validate_pending(db, cost_bps, entry_delay_ms)
            if n:
                logger.info("validator resolved %d signals", n)
        except Exception:
            logger.exception("validator pass failed; will retry")
        stop.wait(poll_s)
