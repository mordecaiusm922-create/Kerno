"""
Point-in-time microstructure features.

Single source of truth for feature definitions: the live engine, historical
replay and model training all call `compute_features`, so there is no
train/serve skew. Every window only contains trades that were processed
before the event trade (same exchange+symbol, ordered by event time then
exchange_trade_id), so nothing here can see the future.

Bump FEATURE_VERSION whenever a definition changes. Signals and models are
keyed by it; a model trained on one version is never applied to another.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

FEATURE_VERSION = "fv2"
MAX_WINDOW_MS = 300_000  # longest lookback used by any feature
TAIL_RETURNS = 500  # trailing non-zero tick returns used for spike percentiles


@dataclass(slots=True)
class Tick:
    ts: int
    price: float
    qty: float
    side: int  # +1 aggressive buy, -1 aggressive sell
    ret_bps: float  # tick return vs previous trade, 0 for the first


@dataclass
class Window:
    """Rolling state for one (exchange, symbol) stream."""

    ticks: deque[Tick] = field(default_factory=deque)
    abs_returns: deque[float] = field(default_factory=lambda: deque(maxlen=TAIL_RETURNS))

    @property
    def last_price(self) -> float | None:
        return self.ticks[-1].price if self.ticks else None

    def span_ms(self) -> int:
        return self.ticks[-1].ts - self.ticks[0].ts if len(self.ticks) > 1 else 0

    def push(self, tick: Tick) -> None:
        self.ticks.append(tick)
        if tick.ret_bps != 0.0:
            self.abs_returns.append(abs(tick.ret_bps))
        horizon = tick.ts - MAX_WINDOW_MS
        while self.ticks and self.ticks[0].ts < horizon:
            self.ticks.popleft()

    def since(self, ts_from: int) -> list[Tick]:
        """Ticks with ts >= ts_from (scans from the newest end)."""
        out: list[Tick] = []
        for t in reversed(self.ticks):
            if t.ts < ts_from:
                break
            out.append(t)
        out.reverse()
        return out


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(int(len(sorted_vals) * q), len(sorted_vals) - 1)]


def bucket_for(abs_bps: float, sorted_tail: list[float]) -> str:
    if abs_bps < percentile(sorted_tail, 0.75):
        return "SMALL"
    if abs_bps < percentile(sorted_tail, 0.90):
        return "MEDIUM"
    if abs_bps < percentile(sorted_tail, 0.99):
        return "LARGE"
    return "EXTREME"


def _rv(ticks: list[Tick]) -> float:
    """Realized volatility (bps) = sqrt(sum of squared tick returns)."""
    return math.sqrt(sum(t.ret_bps * t.ret_bps for t in ticks))


def _roll_spread_bps(ticks: list[Tick], price: float) -> float:
    """Roll (1984) effective spread from serial covariance of price changes."""
    if len(ticks) < 4 or price <= 0:
        return 0.0
    d = [ticks[i].price - ticks[i - 1].price for i in range(1, len(ticks))]
    a, b = d[1:], d[:-1]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
    return 2.0 * math.sqrt(-cov) / price * 1e4 if cov < 0 else 0.0


def _imbalance(ticks: list[Tick]) -> float:
    total = sum(t.qty for t in ticks)
    if total <= 0:
        return 0.0
    return sum(t.side * t.qty for t in ticks) / total


def compute_features(window: Window, event: Tick, sorted_tail: list[float]) -> dict[str, float]:
    """
    Features for `event` using only `window` (trades before the event) plus the
    event trade's own price change. `sorted_tail` is the sorted trailing
    |tick return| distribution, excluding the event.
    """
    t = event.ts
    last_2s = window.since(t - 2_000)
    last_5s = window.since(t - 5_000)
    last_30s = window.since(t - 30_000)
    last_1m = window.since(t - 60_000)
    last_5m = window.since(t - 300_000)
    n_1s = sum(1 for x in last_2s if x.ts >= t - 1_000)

    abs_spike = abs(event.ret_bps)
    spike_dir = 1.0 if event.ret_bps > 0 else -1.0
    mean = sum(sorted_tail) / len(sorted_tail) if sorted_tail else 0.0
    var = sum((x - mean) ** 2 for x in sorted_tail) / len(sorted_tail) if sorted_tail else 0.0
    std = math.sqrt(var)
    rank = sum(1 for x in sorted_tail if x <= abs_spike) / len(sorted_tail) if sorted_tail else 0.0

    density_1m = len(last_1m) / 60.0
    density_5m = len(last_5m) / 300.0
    rv_5s, rv_1m, rv_5m = _rv(last_5s), _rv(last_1m), _rv(last_5m)
    spread = _roll_spread_bps(last_5s, event.price)
    imb_2s = _imbalance(last_2s)
    imb_30s = _imbalance(last_30s)
    burst_1s = n_1s / density_1m if density_1m > 0 else 0.0

    return {
        "spike_bps": event.ret_bps,
        "abs_spike_bps": abs_spike,
        "spike_z": (abs_spike - mean) / std if std > 0 else 0.0,
        "spike_pctile": rank,
        "spread_bps": spread,
        "rv_5s_bps": rv_5s,
        "rv_1m_bps": rv_1m,
        "rv_5m_bps": rv_5m,
        "vol_ratio_5s_1m": rv_5s / rv_1m if rv_1m > 0 else 0.0,
        "vol_ratio_1m_5m": rv_1m / rv_5m if rv_5m > 0 else 0.0,
        "flow_imbalance_2s": imb_2s,
        "flow_imbalance_30s": imb_30s,
        "flow_aligned_2s": imb_2s * spike_dir,
        "flow_aligned_30s": imb_30s * spike_dir,
        "burst_1s": burst_1s,
        "dir_burst": imb_2s * spike_dir * burst_1s,
        "density_1m": density_1m,
        "density_5m": density_5m,
        "density_ratio": density_1m / density_5m if density_5m > 0 else 0.0,
        "density_x_spread": density_1m * spread,
    }


FEATURE_NAMES: tuple[str, ...] = tuple(
    compute_features(Window(), Tick(0, 1.0, 0.0, 1, 1.0), [1.0]).keys()
)
