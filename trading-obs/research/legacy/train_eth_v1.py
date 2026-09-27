import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.utils.class_weight import compute_class_weight

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, signed_imbalance_1s, signed_imbalance_5s,
           ewma_imbalance, burst_1s, burst_5s, burst_ratio,
           burst_accel, ret_250ms, ret_1s, ret_accel,
           vol_1s, vol_5s, vol_ratio_1s_5s,
           mean_trade_size_1s, trade_size_cv_5s,
           micro_label, event_time_ms
    FROM feature_store
    WHERE symbol='ETHUSDT'
    AND micro_label IN ('CONTINUATION_UP','CONTINUATION_DOWN','ABSORPTION')
    AND signed_imbalance_1s IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["label"] = np.where(
    df["micro_label"].isin(["CONTINUATION_UP","CONTINUATION_DOWN"]), 1, 0
)
df = df.dropna()
print(f"ETH flow dataset: {len(df)} filas | {df['label'].mean()*100:.1f}% continuation")

features = ["spike_pct", "signed_imbalance_1s", "signed_imbalance_5s",
            "ewma_imbalance", "burst_1s", "burst_5s", "burst_ratio",
            "burst_accel", "ret_250ms", "ret_1s", "ret_accel",
            "vol_1s", "vol_5s", "vol_ratio_1s_5s",
            "mean_trade_size_1s", "trade_size_cv_5s"]

split = int(len(df) * 0.7)
split_time = df.iloc[split]["event_time_ms"]
embargo_ms = 60000
train = df[df["event_time_ms"] <= split_time - embargo_ms]
test  = df[df["event_time_ms"] >= split_time + embargo_ms]
print(f"Train: {len(train)} | Test: {len(test)}")

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

model = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
model.fit(X_train_s, y_train)

proba = model.predict_proba(X_test_s)[:,1]
auc   = roc_auc_score(y_test, proba) if len(np.unique(y_test)) > 1 else 0.5
brier = brier_score_loss(y_test, proba)
print(f"\nETH flow AUC (purged): {auc:.4f}")
print(f"Brier:                 {brier:.4f}")

print("\n=== CONFIDENCE BUCKETS ===")
for lo, hi in [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
    mask = (proba >= lo) & (proba < hi)
    if mask.sum() > 0:
        hit = y_test[mask].mean()
        print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>4} signals | hit {hit*100:.1f}%")

print("\n=== COEFICIENTES ETH FLOW ===")
coefs = sorted(zip(features, model.coef_[0]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    d = "→ continuation" if c > 0 else "→ absorption"
    print(f"  {f:<25} {c:>+7.4f}  {d}")