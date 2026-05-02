import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.utils.class_weight import compute_class_weight

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           latency_ms, imbalance_20, burst_1s, vol_ratio, dir_burst,
           micro_label, event_time_ms
    FROM feature_store
    WHERE micro_label IN ('CONTINUATION_UP','CONTINUATION_DOWN','ABSORPTION')
    AND ABS(zscore) >= 0.5
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["label"] = np.where(df["micro_label"].isin(["CONTINUATION_UP","CONTINUATION_DOWN"]), 1, 0)
df = df.dropna()

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "latency_ms", "imbalance_20", "burst_1s", "vol_ratio", "dir_burst"]

split = int(len(df) * 0.7)
split_time = df.iloc[split]["event_time_ms"]
embargo_ms = 60000

train = df[df["event_time_ms"] <= split_time - embargo_ms]
test  = df[df["event_time_ms"] >= split_time + embargo_ms]

classes = np.unique(train["label"])
weights = compute_class_weight("balanced", classes=classes, y=train["label"].values)
cw = dict(zip(classes, weights))

scaler = StandardScaler()
X_train_s = scaler.fit_transform(train[features].values)
X_test_s  = scaler.transform(test[features].values)
y_train   = train["label"].values
y_test    = test["label"].values

base_model = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
base_model.fit(X_train_s, y_train)

cal_model = CalibratedClassifierCV(base_model, method="isotonic", cv=5)
cal_model.fit(X_train_s, y_train)

proba_raw = base_model.predict_proba(X_test_s)[:,1]
proba_cal = cal_model.predict_proba(X_test_s)[:,1]

print("=== BEFORE CALIBRATION ===")
print(f"AUC:   {roc_auc_score(y_test, proba_raw):.4f}")
print(f"Brier: {brier_score_loss(y_test, proba_raw):.4f}")

print("\n=== AFTER ISOTONIC CALIBRATION ===")
print(f"AUC:   {roc_auc_score(y_test, proba_cal):.4f}")
print(f"Brier: {brier_score_loss(y_test, proba_cal):.4f}")

print("\n=== CALIBRATION CURVE (fraction_of_positives vs mean_predicted) ===")
fraction_pos, mean_pred = calibration_curve(y_test, proba_cal, n_bins=10, strategy="quantile")
print(f"{'Predicted':>12} {'Actual':>10} {'Gap':>8}")
print("-" * 35)
for mp, fp in zip(mean_pred, fraction_pos):
    gap = fp - mp
    flag = " <-- OVERCONFIDENT" if gap < -0.1 else (" <-- UNDERCONFIDENT" if gap > 0.1 else "")
    print(f"{mp:>12.3f} {fp:>10.3f} {gap:>+8.3f}{flag}")

print("\n=== CONFIDENCE BUCKETS (calibrated) ===")
for lo, hi in [(0.3,0.5),(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
    mask = (proba_cal >= lo) & (proba_cal < hi)
    if mask.sum() > 10:
        hit = y_test[mask].mean()
        print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>5} signals | hit rate {hit*100:.1f}%")