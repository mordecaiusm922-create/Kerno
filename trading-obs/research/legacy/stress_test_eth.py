import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import KFold
from sklearn.utils.class_weight import compute_class_weight

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           latency_z, lat_x_burst, lat_x_vol,
           imbalance_20, burst_1s, vol_ratio, dir_burst,
           micro_label, event_time_ms, symbol
    FROM feature_store
    WHERE symbol='ETHUSDT'
    AND micro_label IN ('CONTINUATION_UP','CONTINUATION_DOWN','ABSORPTION')
    AND ABS(zscore) >= 0.5
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["label"] = np.where(
    df["micro_label"].isin(["CONTINUATION_UP","CONTINUATION_DOWN"]), 1, 0
)
df["is_btc"] = 0.0
df["btc_x_latency"] = 0.0
df["btc_x_burst"] = 0.0
df = df.dropna().reset_index(drop=True)
print(f"ETH dataset: {len(df)} filas | {df['label'].mean()*100:.1f}% continuation")

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "imbalance_20", "vol_ratio", "dir_burst",
            "latency_z", "lat_x_burst", "lat_x_vol", "burst_1s",
            "is_btc", "btc_x_latency", "btc_x_burst"]

X = df[features].values
y = df["label"].values

def run_fold(X_tr, y_tr, X_te, y_te):
    classes = np.unique(y_tr)
    weights = compute_class_weight("balanced", classes=classes, y=y_tr)
    cw = dict(zip(classes, weights))
    scaler = StandardScaler()
    Xtr = scaler.fit_transform(X_tr)
    Xte = scaler.transform(X_te)
    model = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
    model.fit(Xtr, y_tr)
    proba = model.predict_proba(Xte)[:,1]
    auc = roc_auc_score(y_te, proba) if len(np.unique(y_te)) > 1 else 0.5
    return auc, proba, model.coef_[0]

# 1 - Fold stability (5 folds temporales)
print("\n=== FOLD STABILITY (temporal) ===")
fold_size = len(df) // 5
aucs = []
for i in range(5):
    te_start = i * fold_size
    te_end   = te_start + fold_size
    embargo  = 10  # filas de embargo
    tr_idx = list(range(0, max(0, te_start - embargo)))
    te_idx = list(range(te_start, te_end))
    if len(tr_idx) < 50 or len(te_idx) < 10:
        continue
    auc, _, _ = run_fold(X[tr_idx], y[tr_idx], X[te_idx], y[te_idx])
    aucs.append(auc)
    print(f"  Fold {i+1}: AUC={auc:.4f} | N_train={len(tr_idx)} | N_test={len(te_idx)}")

if aucs:
    print(f"  Mean AUC: {np.mean(aucs):.4f} | Std: {np.std(aucs):.4f} | Worst: {min(aucs):.4f}")

# 2 - Ablation ETH
print("\n=== ETH FEATURE ABLATION ===")
split = int(len(df) * 0.7)
base_auc, _, base_coef = run_fold(X[:split], y[:split], X[split:], y[split:])
print(f"  {'FULL MODEL':<22} AUC={base_auc:.4f}  ΔAUC=—")

for i, feat in enumerate(features):
    if feat in ["is_btc", "btc_x_latency", "btc_x_burst"]:
        continue
    remaining = [j for j, f in enumerate(features) if f != feat]
    a, _, _ = run_fold(X[:split, :][:, remaining], y[:split],
                       X[split:, :][:, remaining], y[split:])
    delta = a - base_auc
    flag = " ⚠️ BRITTLE" if delta < -0.05 else ""
    print(f"  {('- '+feat):<22} AUC={a:.4f}  Δ={delta:+.4f}{flag}")

# 3 - Coeficientes estables
print("\n=== COEFICIENTES ETH ===")
_, _, coef = run_fold(X[:split], y[:split], X[split:], y[split:])
core_features = [f for f in features if f not in ["is_btc","btc_x_latency","btc_x_burst"]]
core_idx = [i for i, f in enumerate(features) if f not in ["is_btc","btc_x_latency","btc_x_burst"]]
coefs = sorted(zip(core_features, coef[core_idx]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    d = "→ continuation" if c > 0 else "→ absorption"
    print(f"  {f:<20} {c:>+7.4f}  {d}")