import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
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

# Interacciones asset-especificas
df["btc_x_latency"] = df["is_btc"] * df["latency_ms"]
df["btc_x_burst"]   = df["is_btc"] * df["burst_1s"]

df = df.dropna()
print(f"Dataset pooled: {len(df)} filas | {df['label'].mean()*100:.1f}% continuation")
print(f"  BTC: {(df['symbol']=='BTCUSDT').sum()} | ETH: {(df['symbol']=='ETHUSDT').sum()}")

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "imbalance_20", "vol_ratio", "dir_burst",
            "latency_ms", "burst_1s",
            "is_btc", "btc_x_latency", "btc_x_burst"]

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
auc   = roc_auc_score(y_test, proba)
brier = brier_score_loss(y_test, proba)
print(f"\nAUC pooled (purged): {auc:.4f}")
print(f"Brier:               {brier:.4f}")

# AUC por activo
for sym in ["BTCUSDT", "ETHUSDT"]:
    mask = test["symbol"] == sym
    if mask.sum() > 50:
        a = roc_auc_score(y_test[mask.values], proba[mask.values])
        print(f"AUC {sym}: {a:.4f}")

# Confidence buckets
print("\n=== CONFIDENCE BUCKETS (pooled) ===")
for lo, hi in [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
    mask = (proba >= lo) & (proba < hi)
    if mask.sum() > 0:
        hit = y_test[mask].mean()
        print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>5} señales | hit rate {hit*100:.1f}%")

# Coeficientes
print("\n=== COEFICIENTES ===")
coefs = sorted(zip(features, model.coef_[0]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    d = "→ continuation" if c > 0 else "→ absorption"
    print(f"  {f:<20} {c:>+7.4f}  {d}")

# Guardar modelo v3
with open("kerno_model_v3.pkl", "wb") as f:
    pickle.dump({"model": model, "scaler": scaler, "features": features}, f)
print("\nOK: kerno_model_v3.pkl guardado")