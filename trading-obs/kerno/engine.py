"""
Signal engine.

`SignalEngine.on_trade()` is a pure, deterministic function of the ordered
trade sequence of one (exchange, symbol) stream: same trades in -> same
signals out. Live processing and historical replay use the exact same code.

The worker (`run_engine`) reads trades from the database in
(event_time_ms, exchange_trade_id) order behind a small watermark, feeds them
to the engine, and writes signals + its cursor in the same transaction, so a
crash never double-writes or skips.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from kerno.db import Conn, Database
from kerno.features import FEATURE_VERSION, MAX_WINDOW_MS, Tick, Window, bucket_for, compute_features
from kerno.model import ModelRegistry

logger = logging.getLogger("kerno.engine")

ENGINE_VERSION = "engine-3"

# Replaying this much history before a start point reproduces a continuous run
# exactly: the first MAX_WINDOW_MS rebuilds the window, the second replays event
# detection so the cooldown state is also exact.
WARMUP_MS = 2 * MAX_WINDOW_MS


@dataclass(frozen=True)
class EngineConfig:
    min_spike_bps: float = 1.0  # ignore tick moves smaller than this
    min_pctile: float = 0.75  # event must be >= this percentile of trailing |returns|
    min_history_returns: int = 100  # warm-up: non-zero returns needed first
    min_history_ms: int = 60_000  # warm-up: window span needed first
    cooldown_ms: int = 1_000  # at most one event per stream per cooldown


def _side(side: str) -> int:
    return 1 if side == "buy" else -1


class SignalEngine:
    def __init__(self, exchange: str, symbol: str, models: ModelRegistry | None = None,
                 config: EngineConfig | None = None):
        self.exchange = exchange
        self.symbol = symbol
        self.models = models or ModelRegistry()
        self.config = config or EngineConfig()
        self.window = Window()
        self._last_event_ts: int | None = None

    def warm(self, trade: dict[str, Any]) -> None:
        """Feed a historical trade without emitting (restores state; see WARMUP_MS)."""
        self._advance(trade, emit=False)

    def on_trade(self, trade: dict[str, Any]) -> dict[str, Any] | None:
        return self._advance(trade, emit=True)

    def _advance(self, trade: dict[str, Any], emit: bool) -> dict[str, Any] | None:
        price = float(trade["price"])
        prev = self.window.last_price
        ret_bps = (price - prev) / prev * 1e4 if prev else 0.0
        tick = Tick(int(trade["event_time_ms"]), price, float(trade["quantity"]), _side(trade["side"]), ret_bps)

        record = None
        if self._is_candidate(tick):
            tail = self.window.sorted_tail()
            abs_bps = abs(ret_bps)
            pct_rank = sum(1 for x in tail if x <= abs_bps) / len(tail)
            if pct_rank >= self.config.min_pctile:
                # detection also runs while warming, so cooldown state is exact
                if emit:
                    record = self._build(trade, tick, tail)
                self._last_event_ts = tick.ts
        self.window.push(tick)
        return record

    def _is_candidate(self, tick: Tick) -> bool:
        c = self.config
        if abs(tick.ret_bps) < c.min_spike_bps:
            return False
        if len(self.window.abs_returns) < c.min_history_returns or self.window.span_ms() < c.min_history_ms:
            return False
        if self._last_event_ts is not None and tick.ts - self._last_event_ts < c.cooldown_ms:
            return False
        return True

    def _build(self, trade: dict[str, Any], tick: Tick, tail: list[float]) -> dict[str, Any]:
        feats = compute_features(self.window, tick, tail)
        spike_dir = 1 if tick.ret_bps > 0 else -1

        s1 = self.models.get(1, self.exchange, self.symbol)
        s2 = self.models.get(2, self.exchange, self.symbol)
        p_t = s1.predict(feats) if s1 else None
        p_c = s2.predict(feats) if s2 else None

        predicted_dir = None
        joint = None
        if p_c is None:
            signal = "UNSCORED"
        else:
            continuation = p_c >= 0.5
            predicted_dir = spike_dir if continuation else -spike_dir
            p_dir = p_c if continuation else 1.0 - p_c
            joint = p_dir * p_t if p_t is not None else None
            if p_t is not None and p_t < s1.threshold:
                signal = "NO_EDGE"
            else:
                signal = "CONTINUATION" if continuation else "ABSORPTION"

        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "exchange_trade_id": str(trade["exchange_trade_id"]),
            "event_time_ms": tick.ts,
            "price": tick.price,
            "spike_bps": round(tick.ret_bps, 6),
            "spike_dir": spike_dir,
            "bucket": bucket_for(abs(tick.ret_bps), tail),
            "features": json.dumps({k: round(v, 8) for k, v in feats.items()}, sort_keys=True),
            "p_tradeable": None if p_t is None else round(p_t, 6),
            "p_continuation": None if p_c is None else round(p_c, 6),
            "joint_score": None if joint is None else round(joint, 6),
            "signal": signal,
            "predicted_dir": predicted_dir,
            "stage1_model": s1.id if s1 else None,
            "stage2_model": s2.id if s2 else None,
            "feature_version": FEATURE_VERSION,
            "engine_version": ENGINE_VERSION,
        }


# ── persistence ──────────────────────────────────────────────────────────────

SIGNAL_COLUMNS = (
    "exchange", "symbol", "exchange_trade_id", "event_time_ms", "price", "spike_bps", "spike_dir",
    "bucket", "features", "p_tradeable", "p_continuation", "joint_score", "signal", "predicted_dir",
    "stage1_model", "stage2_model", "feature_version", "engine_version", "created_at_ms",
)
INSERT_SIGNAL_SQL = (
    f"INSERT INTO signals ({', '.join(SIGNAL_COLUMNS)}) VALUES ({', '.join('?' * len(SIGNAL_COLUMNS))}) "
    "ON CONFLICT DO NOTHING"
)

TRADE_BATCH_SQL = """
    SELECT exchange_trade_id, price, quantity, side, event_time_ms
    FROM trades
    WHERE exchange = ? AND symbol = ?
      AND (event_time_ms, exchange_trade_id) > (?, ?)
      AND event_time_ms <= ?
    ORDER BY event_time_ms, exchange_trade_id
    LIMIT ?
"""


def insert_signals(c: Conn, records: Iterable[dict[str, Any]]) -> None:
    now = int(time.time() * 1000)
    c.executemany(INSERT_SIGNAL_SQL, ([r.get(k, now) if k == "created_at_ms" else r[k] for k in SIGNAL_COLUMNS]
                                      for r in records))


def process_range(db: Database, engine: SignalEngine, start: tuple[int, str], end_ms: int,
                  batch: int = 5_000, save_cursor: bool = False) -> tuple[int, tuple[int, str]]:
    """Run `engine` over trades in (start, end_ms], writing signals. Returns (n_signals, last cursor)."""
    cursor = start
    total = 0
    while True:
        with db.connect() as c:
            rows = c.fetchall(TRADE_BATCH_SQL, (engine.exchange, engine.symbol, cursor[0], cursor[1], end_ms, batch))
            if not rows:
                return total, cursor
            records = [r for r in (engine.on_trade(t) for t in rows) if r]
            insert_signals(c, records)
            cursor = (int(rows[-1]["event_time_ms"]), str(rows[-1]["exchange_trade_id"]))
            if save_cursor:
                _save_cursor(c, engine, cursor)
        total += len(records)
        if len(rows) < batch:
            return total, cursor


def _load_cursor(c: Conn, exchange: str, symbol: str) -> tuple[int, str] | None:
    row = c.fetchone(
        "SELECT last_event_time_ms, last_exchange_trade_id FROM engine_state "
        "WHERE exchange = ? AND symbol = ? AND feature_version = ?",
        (exchange, symbol, FEATURE_VERSION),
    )
    return (int(row["last_event_time_ms"]), str(row["last_exchange_trade_id"])) if row else None


def _save_cursor(c: Conn, engine: SignalEngine, cursor: tuple[int, str]) -> None:
    c.execute(
        "INSERT INTO engine_state (exchange, symbol, feature_version, last_event_time_ms, "
        "last_exchange_trade_id, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (exchange, symbol, feature_version) DO UPDATE SET "
        "last_event_time_ms = excluded.last_event_time_ms, "
        "last_exchange_trade_id = excluded.last_exchange_trade_id, updated_at_ms = excluded.updated_at_ms",
        (engine.exchange, engine.symbol, FEATURE_VERSION, cursor[0], cursor[1], int(time.time() * 1000)),
    )


def warm_engine(db: Database, engine: SignalEngine, cursor: tuple[int, str]) -> None:
    """Replay the WARMUP_MS of trades up to and including `cursor` so state matches a continuous run."""
    with db.connect() as c:
        rows = c.fetchall(
            "SELECT exchange_trade_id, price, quantity, side, event_time_ms FROM trades "
            "WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? "
            "AND (event_time_ms, exchange_trade_id) <= (?, ?) "
            "ORDER BY event_time_ms, exchange_trade_id",
            (engine.exchange, engine.symbol, cursor[0] - WARMUP_MS, cursor[0], cursor[1]),
        )
    for r in rows:
        engine.warm(r)


def run_engine(db: Database, streams: list[tuple[str, str]], models: ModelRegistry,
               stop: threading.Event, watermark_ms: int = 3_000, poll_s: float = 1.0,
               start_lookback_ms: int = 3_600_000) -> None:
    """Live worker loop over several (exchange, symbol) streams."""
    engines: dict[tuple[str, str], tuple[SignalEngine, tuple[int, str]]] = {}
    for exchange, symbol in streams:
        engine = SignalEngine(exchange, symbol, models)
        with db.connect() as c:
            cursor = _load_cursor(c, exchange, symbol)
            if cursor is None:
                first = c.scalar(
                    "SELECT MIN(event_time_ms) FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ?",
                    (exchange, symbol, int(time.time() * 1000) - start_lookback_ms),
                )
                cursor = (int(first) - 1, "") if first is not None else (int(time.time() * 1000), "")
        warm_engine(db, engine, cursor)
        engines[(exchange, symbol)] = (engine, cursor)
        logger.info("engine %s:%s starting after %s", exchange, symbol, cursor)

    while not stop.is_set():
        horizon = int(time.time() * 1000) - watermark_ms
        for key, (engine, cursor) in list(engines.items()):
            try:
                n, cursor = process_range(db, engine, cursor, horizon, save_cursor=True)
                engines[key] = (engine, cursor)
                if n:
                    logger.info("engine %s:%s +%d signals", *key, n)
            except Exception:
                logger.exception("engine %s:%s batch failed; will retry", *key)
        stop.wait(poll_s)
