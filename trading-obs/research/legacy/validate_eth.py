import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.utils.class_weight import compute_class_weight
import pickle

conn = sqlite3.connect("kerno.db")

# Cargar modelo BTC para comparar coeficientes
try:
    with open("kerno_model.pkl", "rb") as f:
        btc_data = pickle.load(f)
    btc_coef = btc_data.get("coef", None)
    print("Modelo BTC cargado")
except:
    btc_coef = None
    print("kerno_model.pkl no encontrado - solo ETH")

df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           latency_ms, imbalance_20, burst_1s, vol_ratio, dir_burst,
           micro_label, event_time_ms
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
df = df.dropna()
print(f"ETH dataset: {len(df)} filas | {df['label'].mean()*100:.1f}% continuation")

if len(df) < 100:
    print("INSUFICIENTE DATA ETH — necesitas mas eventos")
    exit()

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "latency_ms", "imbalance_20", "burst_1s", "vol_ratio", "dir_burst"]

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
print(f"\nETH AUC (purged): {auc:.4f}")
print(f"ETH Brier:        {brier:.4f}")

# Confidence buckets
print("\n=== ETH CONFIDENCE BUCKETS ===")
for lo, hi in [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,1.0)]:
    mask = (proba >= lo) & (proba < hi)
    if mask.sum() > 0:
        hit = y_test[mask].mean()
        print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>5} señales | hit rate {hit*100:.1f}%")

# Tabla de signos BTC vs ETH
print("\n=== SIGN STABILITY BTC vs ETH ===")
print(f"{'feature':<20} {'ETH':>8}  {'BTC':>8}  {'stable?'}")
print("-" * 55)
btc_coefs = btc_coef if btc_coef is not None else [None]*len(features)
for f, ec, bc in zip(features, model.coef_[0], btc_coefs):
    es = "+" if ec > 0 else "-"
    if bc is not None:
        bs = "+" if bc > 0 else "-"
        stable = "✅" if es == bs else "❌ FLIP"
    else:
        bs = "?"
        stable = "?"
    print(f"  {f:<20} {ec:>+7.4f}  {str(bc) if bc else '?':>8}  {stable}")