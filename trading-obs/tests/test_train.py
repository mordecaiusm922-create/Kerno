import json
import random

import pytest

from kerno.engine import insert_signals
from kerno.features import FEATURE_NAMES
from kerno.model import ModelRegistry
from kerno.train import train_stage


def _synthetic_signals(db, n=4000, seed=1):
    """Resolved signals where flow alignment genuinely predicts continuation."""
    rng = random.Random(seed)
    recs, outcomes = [], []
    for i in range(n):
        feats = {f: rng.gauss(0, 1) for f in FEATURE_NAMES}
        spike_dir = rng.choice([-1, 1])
        cont = rng.random() < (0.8 if feats["flow_aligned_2s"] > 0 else 0.2)
        move = rng.uniform(25, 60) if rng.random() < 0.8 else rng.uniform(0, 5)
        ret = move * (spike_dir if cont else -spike_dir)
        recs.append({"exchange": "binance", "symbol": "BTCUSDT", "exchange_trade_id": str(i),
                     "event_time_ms": 1_700_000_000_000 + i * 5_000, "price": 100.0, "spike_bps": 2.0 * spike_dir,
                     "spike_dir": spike_dir, "bucket": "LARGE", "features": json.dumps(feats), "p_tradeable": None,
                     "p_continuation": None, "joint_score": None, "signal": "UNSCORED", "predicted_dir": None,
                     "stage1_model": None, "stage2_model": None, "feature_version": "fv2", "engine_version": "t"})
        outcomes.append((ret, str(i)))
    with db.connect() as c:
        insert_signals(c, recs)
        c.executemany("UPDATE signals SET status = 'RESOLVED', ret_10s_bps = ? WHERE exchange_trade_id = ?", outcomes)


def test_train_gate_and_deploy(db, tmp_path):
    pytest.importorskip("sklearn")
    _synthetic_signals(db)
    res = train_stage(db, "binance", "BTCUSDT", 2, tmp_path, cost_bps=10)
    assert res["ok"] and res["passed_gate"], res
    m = res["metrics"]
    assert m["test_auc"] > 0.7 and m["test_mean_net_pnl_bps"] > 0
    assert len(m["walk_forward_auc"]) >= 3
    reg = ModelRegistry.load(tmp_path)
    assert reg.get(2, "binance", "BTCUSDT").id == res["model"]


def test_train_refuses_noise(db, tmp_path):
    pytest.importorskip("sklearn")
    _synthetic_signals(db, seed=2)
    # stage 1 on pure-noise features cannot beat the gate -> not deployed
    res = train_stage(db, "binance", "BTCUSDT", 1, tmp_path, cost_bps=10)
    assert not res["ok"] and "gate" in res["reason"]
    assert ModelRegistry.load(tmp_path).models == []


def test_train_needs_data(db, tmp_path):
    res = train_stage(db, "binance", "BTCUSDT", 2, tmp_path, cost_bps=10)
    assert not res["ok"] and "rows" in res["reason"]
