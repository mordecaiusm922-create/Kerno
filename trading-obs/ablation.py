import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           trade_rate_1m, hour_of_day, latency_ms,
           micro_label, event_time_ms
    FROM feature_store
    WHERE micro_label IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

# Binario: CONTINUATION_UP vs resto
df["label"] = (df["micro_label"] == "CONTINUATION_UP").astype(int)
df = df.dropna()
print(f"Dataset: {len(df)} filas | {df['label'].mean()*100:.1f}% positive")

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "trade_rate_1m", "hour_of_day", "latency_ms"]

# Purged walk-forward — embargo de 60s entre train y test
df = df.reset_index(drop=True)
split = int(len(df) * 0.7)
embargo_ms = 60000
split_time = df.loc[split, "event_time_ms"]

train = df[df["event_time_ms"] <= split_time - embargo_ms]
test  = df[df["event_time_ms"] >= split_time + embargo_ms]
print(f"Train: {len(train)} | Test: {len(test)} | Embargo: 60s")

def run_model(X_tr, y_tr, X_te, y_te, label="full"):
    scaler = StandardScaler()
    Xtr = scaler.fit_transform(X_tr)
    Xte = scaler.transform(X_te)
    model = LogisticRegression(max_iter=1000, C=0.1, penalty="l1", solver="liblinear")
    model.fit(Xtr, y_tr)
    proba = model.predict_proba(Xte)[:,1]
    auc   = roc_auc_score(y_te, proba)
    brier = brier_score_loss(y_te, proba)
    return auc, brier, model.coef_[0]

X_train = train[features].values
y_train = train["label"].values
X_test  = test[features].values
y_test  = test["label"].values

print("\n=== ABLATION TABLE ===")
print(f"{'Model':<25} {'AUC':>7} {'Brier':>7} {'ΔAUC':>7}")
print("-" * 50)

base_auc, base_brier, base_coef = run_model(X_train, y_train, X_test, y_test)
print(f"{'FULL MODEL':<25} {base_auc:>7.4f} {base_brier:>7.4f} {'—':>7}")

for i, feat in enumerate(features):
    remaining = [f for f in features if f != feat]
    Xi_train = train[remaining].values
    Xi_test  = test[remaining].values
    auc, brier, _ = run_model(Xi_train, y_train, Xi_test, y_test)
    delta = auc - base_auc
    flag = " ⚠️  LEAKAGE?" if delta < -0.05 else ""
    print(f"{'- '+feat:<25} {auc:>7.4f} {brier:>7.4f} {delta:>+7.4f}{flag}")

print("\n=== COEFICIENTES (modelo completo) ===")
coefs = sorted(zip(features, base_coef), key=lambda x: -abs(x[1]))
for f, c in coefs:
    bar = "█" * int(abs(c) * 10)
    direction = "→ continuation" if c > 0 else "→ no continuation"
    print(f"  {f:<20} {c:>+7.4f}  {bar} {direction}")