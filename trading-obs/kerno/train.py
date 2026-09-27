"""
Model training with time-ordered, purged validation.

Dataset: resolved signals of one stream (features were computed by the engine
point-in-time; outcomes by the validator from later trades only).

Labels, for horizon h (10s default):
  stage 1 (tradability): |ret_h_bps| > cost_bps          -> worth trading at all?
  stage 2 (direction):   sign(ret_h_bps) == spike_dir     -> continuation (1) vs absorption (0)
                         trained only on stage-1-positive rows

Split (by time): 60% train | 20% calibration | 20% test, with an embargo
between segments so no label window overlaps the next segment. Probabilities
are calibrated (isotonic) on the calibration segment only; all reported
metrics come from the untouched test segment, plus an expanding-window
walk-forward AUC on train+calibration for stability.

A model is only added to the serving manifest if it beats the gate on the
test segment (AUC > GATE_AUC and, for stage 2, positive mean net PnL).
Requires scikit-learn (`pip install -r requirements-train.txt`).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kerno.db import Database
from kerno.features import FEATURE_VERSION
from kerno.model import LinearModel, save_model

logger = logging.getLogger("kerno.train")

STAGE1_FEATURES = ["density_1m", "density_5m", "density_ratio", "rv_1m_bps", "rv_5m_bps",
                   "vol_ratio_1m_5m", "spread_bps", "density_x_spread", "burst_1s", "abs_spike_bps"]
STAGE2_FEATURES = ["abs_spike_bps", "spike_z", "spike_pctile", "spread_bps", "rv_1m_bps", "vol_ratio_5s_1m",
                   "flow_aligned_2s", "flow_aligned_30s", "burst_1s", "dir_burst"]
MIN_ROWS = 1_000
MIN_CLASS = 50
GATE_AUC = 0.55
EMBARGO_MS = 120_000


def load_dataset(db: Database, exchange: str, symbol: str, horizon: int) -> list[dict[str, Any]]:
    with db.connect() as c:
        rows = c.fetchall(
            f"SELECT event_time_ms, spike_dir, features, ret_{horizon}s_bps AS ret FROM signals "
            "WHERE exchange = ? AND symbol = ? AND feature_version = ? AND status = 'RESOLVED' "
            f"AND ret_{horizon}s_bps IS NOT NULL ORDER BY event_time_ms",
            (exchange, symbol, FEATURE_VERSION),
        )
    for r in rows:
        r["features"] = json.loads(r["features"])
    return rows


def _segments(rows: list[dict[str, Any]]) -> tuple[list, list, list]:
    n = len(rows)
    a, b = rows[int(n * 0.6)]["event_time_ms"], rows[int(n * 0.8)]["event_time_ms"]
    train = [r for r in rows if r["event_time_ms"] < a - EMBARGO_MS]
    calib = [r for r in rows if a + EMBARGO_MS <= r["event_time_ms"] < b - EMBARGO_MS]
    test = [r for r in rows if r["event_time_ms"] >= b + EMBARGO_MS]
    return train, calib, test


def _xy(rows, features, label):
    import numpy as np

    X = np.array([[float(r["features"][f]) for f in features] for r in rows], dtype=float)
    y = np.array([label(r) for r in rows], dtype=int)
    return X, y


def _walk_forward_auc(X, y, times, folds: int = 5) -> list[float]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    aucs = []
    edges = np.linspace(0, len(y), folds + 2, dtype=int)
    for k in range(1, folds + 1):
        start, end = edges[k], edges[k + 1]
        tr = times < times[start] - EMBARGO_MS
        te = np.zeros(len(y), dtype=bool)
        te[start:end] = True
        te &= times >= times[start]
        if tr.sum() < 100 or len(set(y[tr])) < 2 or len(set(y[te])) < 2:
            continue
        sc = StandardScaler().fit(X[tr])
        m = LogisticRegression(C=0.1, class_weight="balanced", max_iter=2000).fit(sc.transform(X[tr]), y[tr])
        aucs.append(float(roc_auc_score(y[te], m.predict_proba(sc.transform(X[te]))[:, 1])))
    return aucs


def train_stage(db: Database, exchange: str, symbol: str, stage: int, models_dir: Path, cost_bps: float,
                horizon: int = 10, force: bool = False) -> dict[str, Any]:
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    full = load_dataset(db, exchange, symbol, horizon)
    rows = full
    if stage == 1:
        features = STAGE1_FEATURES
        label = lambda r: int(abs(r["ret"]) > cost_bps)
    else:
        features = STAGE2_FEATURES
        rows = [r for r in rows if abs(r["ret"]) > cost_bps]
        label = lambda r: int((r["ret"] > 0) == (r["spike_dir"] > 0))

    if len(rows) < MIN_ROWS:
        return {"ok": False, "reason": f"only {len(rows)} usable rows (need {MIN_ROWS}); keep collecting data"}

    train, calib, test = _segments(rows)
    (Xtr, ytr), (Xca, yca), (Xte, yte) = (_xy(s, features, label) for s in (train, calib, test))
    for name, y in (("train", ytr), ("calibration", yca), ("test", yte)):
        if min(int(y.sum()), int(len(y) - y.sum())) < MIN_CLASS:
            return {"ok": False, "reason": f"{name} segment has fewer than {MIN_CLASS} examples of a class"}

    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(C=0.1, class_weight="balanced", max_iter=2000).fit(scaler.transform(Xtr), ytr)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
        clf.predict_proba(scaler.transform(Xca))[:, 1], yca
    )
    p_test = iso.predict(clf.predict_proba(scaler.transform(Xte))[:, 1])

    metrics: dict[str, Any] = {
        "n_train": len(train), "n_calibration": len(calib), "n_test": len(test),
        "base_rate_test": round(float(yte.mean()), 4),
        "test_auc": round(float(roc_auc_score(yte, p_test)), 4),
        "test_brier": round(float(brier_score_loss(yte, p_test)), 5),
        "test_brier_baseline": round(float(brier_score_loss(yte, np.full(len(yte), ytr.mean()))), 5),
    }
    all_rows = train + calib
    Xall, yall = _xy(all_rows, features, label)
    wf = _walk_forward_auc(Xall, yall, np.array([r["event_time_ms"] for r in all_rows]))
    metrics["walk_forward_auc"] = [round(a, 4) for a in wf]
    metrics["walk_forward_auc_mean"] = round(float(np.mean(wf)), 4) if wf else None

    passed = metrics["test_auc"] > GATE_AUC
    if stage == 2:
        # Economics must be measured on *every* event in the test period, not
        # only the ones that later turned out to move more than costs (that
        # filter uses future information).
        metrics["test_auc_note"] = "AUC is conditional on |ret| > cost; PnL below is over all test-period events"
        test_all = [r for r in full if r["event_time_ms"] >= test[0]["event_time_ms"]]
        Xall_te, _ = _xy(test_all, features, lambda r: 0)
        p_all = iso.predict(clf.predict_proba(scaler.transform(Xall_te))[:, 1])
        rets = np.array([r["ret"] for r in test_all])
        spike = np.array([r["spike_dir"] for r in test_all])
        pred_dir = np.where(p_all >= 0.5, spike, -spike)
        pnl = pred_dir * rets - cost_bps
        metrics["test_events"] = len(test_all)
        metrics["test_mean_net_pnl_bps"] = round(float(pnl.mean()), 4)
        metrics["test_hit_rate"] = round(float((pnl > 0).mean()), 4)
        passed = passed and metrics["test_mean_net_pnl_bps"] > 0

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
    safe_symbol = symbol.replace("/", "_")
    model = LinearModel(
        id=f"stage{stage}-{exchange}-{safe_symbol}-{FEATURE_VERSION}-{stamp}",
        stage=stage,
        scope=f"{exchange}:{symbol}",
        features=features,
        mean=[float(x) for x in scaler.mean_],
        scale=[float(x) if x > 0 else 1.0 for x in scaler.scale_],
        coef=[float(x) for x in clf.coef_[0]],
        intercept=float(clf.intercept_[0]),
        feature_version=FEATURE_VERSION,
        calibration={"x": [float(x) for x in iso.X_thresholds_], "y": [float(y) for y in iso.y_thresholds_]},
        threshold=0.5,
        metadata={
            "horizon_s": horizon,
            "cost_bps": cost_bps,
            "trained_from_ms": int(train[0]["event_time_ms"]),
            "trained_to_ms": int(train[-1]["event_time_ms"]),
            "test_from_ms": int(test[0]["event_time_ms"]),
            "test_to_ms": int(test[-1]["event_time_ms"]),
            "metrics": metrics,
            "passed_gate": passed,
        },
    )
    if any(math.isnan(v) for v in model.coef + [model.intercept]):
        return {"ok": False, "reason": "training produced NaN coefficients", "metrics": metrics}

    if passed or force:
        path = save_model(model, models_dir)
        return {"ok": True, "model": model.id, "path": str(path), "passed_gate": passed, "metrics": metrics}
    return {"ok": False, "reason": "did not pass the validation gate; not deployed (use --force to override)",
            "metrics": metrics}
