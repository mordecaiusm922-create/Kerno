import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.utils.class_weight import compute_class_weight
import pickle

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           imbalance_20, vol_ratio, dir_burst,
           lat_x_burst, burst_1s,
           micro_label, event_time_ms, symbol
    FROM feature_store
    WHERE micro_label IN ('CONTINUATION_UP','CONTINUATION_DOWN','ABSORPTION')
    AND ABS(zscore) >= 0.5
    AND lat_x_burst IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["label"] = np.where(
    df["micro_label"].isin(["CONTINUATION_UP","CONTINUATION_DOWN"]), 1, 0
)
df["is_btc"] = (df["symbol"] == "BTCUSDT").astype(float)
df = df.dropna()

print(f"Dataset: {len(df)} | {df['label'].mean()*100:.1f}% continuation")
print(f"BTC: {(df['symbol']=='BTCUSDT').sum()} | ETH: {(df['symbol']=='ETHUSDT').sum()}")

# Features finales — latency_ms demoted, solo interaccion
features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "imbalance_20", "vol_ratio", "dir_burst",
            "lat_x_burst", "burst_1s", "is_btc"]

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

base = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
base.fit(X_train_s, y_train)

# Calibracion por activo
print("\n=== CALIBRACION POR ACTIVO ===")
results = {}
for sym in ["BTCUSDT", "ETHUSDT"]:
    mask_tr = train["symbol"] == sym
    mask_te = test["symbol"] == sym
    if mask_tr.sum() < 30 or mask_te.sum() < 10:
        continue
    Xtr = scaler.transform(train[mask_tr][features].values)
    ytr = train[mask_tr]["label"].values
    Xte = scaler.transform(test[mask_te][features].values)
    yte = test[mask_te]["label"].values
    cal = CalibratedClassifierCV(base, method="isotonic", cv=3)
    cal.fit(Xtr, ytr)
    proba = cal.predict_proba(Xte)[:,1]
    auc   = roc_auc_score(yte, proba) if len(np.unique(yte)) > 1 else 0.5
    brier = brier_score_loss(yte, proba)
    results[sym] = {"auc": auc, "brier": brier, "cal": cal}
    print(f"{sym}: AUC={auc:.4f} | Brier={brier:.4f} | N={len(yte)}")
    for lo, hi in [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
        mask = (proba >= lo) & (proba < hi)
        if mask.sum() > 0:
            print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>4} signals | hit {yte[mask].mean()*100:.1f}%")

# Coeficientes
print("\n=== COEFICIENTES FINALES ===")
coefs = sorted(zip(features, base.coef_[0]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    d = "→ continuation" if c > 0 else "→ absorption"
    print(f"  {f:<20} {c:>+7.4f}  {d}")

# Guardar modelo final
with open("kerno_model_final.pkl", "wb") as f:
    pickle.dump({"model_btc": results.get("BTCUSDT",{}).get("cal"),
                 "model_eth": results.get("ETHUSDT",{}).get("cal"),
                 "scaler": scaler, "features": features}, f)
print("\nOK: kerno_model_final.pkl guardado")