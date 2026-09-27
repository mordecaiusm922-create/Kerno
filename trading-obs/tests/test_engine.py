import json

from kerno.engine import SignalEngine
from kerno.features import FEATURE_NAMES
from kerno.model import LinearModel, ModelRegistry
from tests.conftest import make_trades


def run(trades, models=None):
    e = SignalEngine("binance", "BTCUSDT", models)
    return [r for r in (e.on_trade(t) for t in trades) if r]


def test_deterministic():
    trades = make_trades()
    assert run(trades) == run(trades)
    assert len(run(trades)) > 10


def test_no_look_ahead():
    """Signals emitted on a prefix of the tape are identical when more data follows."""
    trades = make_trades(4000)
    full = run(trades)
    cut = trades[2500]["event_time_ms"]
    prefix = run(trades[:2500])
    assert prefix == [s for s in full if s["event_time_ms"] < cut]


def test_features_ignore_future_trades():
    trades = make_trades(3000)
    base = run(trades)
    target = base[len(base) // 2]
    # tamper with every trade after the event: features of the event must not change
    tampered = [dict(t) for t in trades]
    for t in tampered:
        if t["event_time_ms"] > target["event_time_ms"]:
            t["price"] *= 1.5
            t["side"] = "sell"
    again = {s["exchange_trade_id"]: s for s in run(tampered)}
    assert again[target["exchange_trade_id"]]["features"] == target["features"]


def test_spike_direction_and_fields():
    for s in run(make_trades()):
        assert s["spike_dir"] == (1 if s["spike_bps"] > 0 else -1)
        assert abs(s["spike_bps"]) >= 1.0
        assert set(json.loads(s["features"])) == set(FEATURE_NAMES)
        assert s["signal"] == "UNSCORED" and s["predicted_dir"] is None


def _model(stage, coef_sign=1.0):
    feats = ["abs_spike_bps", "burst_1s"]
    return LinearModel(id=f"s{stage}", stage=stage, scope="*", features=feats, mean=[0, 0], scale=[1, 1],
                       coef=[coef_sign, 0.0], intercept=0.0, feature_version="fv3")


def test_scoring_and_joint_score():
    reg = ModelRegistry([_model(1), _model(2)])
    sigs = run(make_trades(), reg)
    assert sigs and all(s["signal"] == "CONTINUATION" for s in sigs)
    for s in sigs:
        assert s["predicted_dir"] == s["spike_dir"]
        assert abs(s["joint_score"] - s["p_tradeable"] * s["p_continuation"]) < 1e-5
    reg = ModelRegistry([_model(2, -1.0)])
    for s in run(make_trades(), reg):
        assert s["signal"] == "ABSORPTION" and s["predicted_dir"] == -s["spike_dir"]
        assert s["p_tradeable"] is None and s["joint_score"] is None


def test_warm_start_matches_continuous_run():
    """Processing from any point after a WARMUP_MS warm-up equals one continuous run."""
    from kerno.engine import WARMUP_MS

    trades = make_trades(8000, jump_every=15)
    full = run(trades)
    for cut_idx in (3000, 5000, 6500):
        cut = trades[cut_idx]["event_time_ms"]
        e = SignalEngine("binance", "BTCUSDT")
        for t in trades[:cut_idx]:
            if t["event_time_ms"] >= cut - WARMUP_MS:
                e.warm(t)
        resumed = [r for r in (e.on_trade(t) for t in trades[cut_idx:]) if r]
        assert resumed == [s for s in full if s["event_time_ms"] >= cut]
        assert resumed


def test_state_is_time_bounded():
    trades = make_trades(3000)
    e = SignalEngine("binance", "BTCUSDT")
    for t in trades:
        e.on_trade(t)
    oldest = trades[-1]["event_time_ms"] - 300_000
    assert all(ts >= oldest for ts, _ in e.window.abs_returns)
    assert all(t.ts >= oldest for t in e.window.ticks)
