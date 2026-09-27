import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.utils.class_weight import compute_class_weight
import pickle

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           latency_ms, imbalance_20, burst_1s, vol_ratio, dir_burst,
           micro_label, event_time_ms, symbol
    FROM feature_store
    WHERE micro_label IN ('CONTINUATION_UP','CONTINUATION_DOWN','ABSORPTION')
    AND ABS(zscore) >= 0.5
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["label"] = np.where(
    df["micro_label"].isin(["CONTINUATION_UP","CONTINUATION_DOWN"]), 1, 0
)
df["is_btc"] = (df["symbol"] == "BTCUSDT").astype(float)
df["btc_x_latency"] = df["is_btc"] * df["latency_ms"]
df["btc_x_burst"]   = df["is_btc"] * df["burst_1s"]
df = df.dropna()

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "imbalance_20", "vol_ratio", "dir_burst",
            "latency_ms", "burst_1s",
            "is_btc", "btc_x_latency", "btc_x_burst"]

split = int(len(df) * 0.7)
split_time = df.iloc[split]["event_time_ms"]
embargo_ms = 60000
train = df[df["event_time_ms"] <= split_time - embargo_ms]
test  = df[df["event_time_ms"] >= split_time + embargo_ms]

X_train = train[features].values
y_train = train["label"].values
X_test  = test[features].values
y_test  = test["label"].values

classes = np.unique(y_train)
weights = compute_class_weight("balanced", classes=classes, y=y_train)
cw = dict(zip(classes, weights))

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s  = scaler.transform(X_test)

base_model = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
base_model.fit(X_train_s, y_train)

# Calibracion isotonica por activo
print("=== CALIBRACION POR ACTIVO ===")
for sym in ["BTCUSDT", "ETHUSDT"]:
    mask_tr = train["symbol"] == sym
    mask_te = test["symbol"] == sym
    if mask_tr.sum() < 50 or mask_te.sum() < 50:
        print(f"{sym}: insuficiente data")
        continue
    Xtr = scaler.transform(train[mask_tr][features].values)
    ytr = train[mask_tr]["label"].values
    Xte = scaler.transform(test[mask_te][features].values)
    yte = test[mask_te]["label"].values

    cal = CalibratedClassifierCV(base_model, method="isotonic", cv=3)
    cal.fit(Xtr, ytr)
    proba = cal.predict_proba(Xte)[:,1]
    auc   = roc_auc_score(yte, proba)
    brier = brier_score_loss(yte, proba)
    print(f"\n{sym} — AUC: {auc:.4f} | Brier: {brier:.4f} | N test: {len(yte)}")

    # Calibration curve
    fraction_pos, mean_pred = calibration_curve(yte, proba, n_bins=5)
    print(f"  Calibration curve (mean_pred → fraction_pos):")
    for mp, fp in zip(mean_pred, fraction_pos):
        bar = "█" * int(fp * 20)
        print(f"    {mp:.3f} → {fp:.3f}  {bar}")

    # Confidence buckets
    for lo, hi in [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
        mask = (proba >= lo) & (proba < hi)
        if mask.sum() > 0:
            hit = yte[mask].mean()
            print(f"  bucket {lo:.1f}-{hi:.1f}: {mask.sum():>4} signals | hit {hit*100:.1f}%")

# Regime slicing
print("\n=== REGIME SLICING ===")
proba_all = base_model.predict_proba(X_test_s)[:,1]
test_copy = test.copy()
test_copy["proba"] = proba_all
test_copy["y"] = y_test

# Por vol_ratio terciles
print("\nVol ratio terciles:")
terciles = np.percentile(test_copy["vol_ratio"], [33, 66])
for label, mask in [
    ("low_vol",  test_copy["vol_ratio"] <= terciles[0]),
    ("mid_vol",  (test_copy["vol_ratio"] > terciles[0]) & (test_copy["vol_ratio"] <= terciles[1])),
    ("high_vol", test_copy["vol_ratio"] > terciles[1]),
]:
    sub = test_copy[mask]
    if len(sub) > 30:
        a = roc_auc_score(sub["y"], sub["proba"])
        top = sub[sub["proba"] >= 0.8]
        hr = top["y"].mean() if len(top) > 0 else 0
        print(f"  {label:<12} N={len(sub):>4} AUC={a:.4f} top_bucket_hr={hr*100:.1f}% (n={len(top)})")

# Por spread_est terciles
print("\nSpread est terciles:")
sp_terciles = np.percentile(test_copy["spread_est"], [33, 66])
for label, mask in [
    ("low_spread",  test_copy["spread_est"] <= sp_terciles[0]),
    ("mid_spread",  (test_copy["spread_est"] > sp_terciles[0]) & (test_copy["spread_est"] <= sp_terciles[1])),
    ("high_spread", test_copy["spread_est"] > sp_terciles[1]),
]:
    sub = test_copy[mask]
    if len(sub) > 30:
        a = roc_auc_score(sub["y"], sub["proba"])
        top = sub[sub["proba"] >= 0.8]
        hr = top["y"].mean() if len(top) > 0 else 0
        print(f"  {label:<12} N={len(sub):>4} AUC={a:.4f} top_bucket_hr={hr*100:.1f}% (n={len(top)})")