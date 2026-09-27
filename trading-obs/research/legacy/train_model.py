import sqlite3
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
import numpy as np

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT spike_pct, zscore, spread_est, volatility_1m,
           trade_rate_1m, hour_of_day, latency_ms,
           outcome_10s, outcome_30s, bucket, symbol
    FROM feature_store
    WHERE outcome_10s IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df["outcome_10s"] = df["outcome_10s"].astype(int)
df = df.dropna()
print(f"Dataset: {len(df)} filas | {df['outcome_10s'].mean()*100:.1f}% reversal")

features = ["spike_pct", "zscore", "spread_est", "volatility_1m",
            "trade_rate_1m", "hour_of_day", "latency_ms"]

X = df[features].values
y = df["outcome_10s"].values

# Walk-forward split — no random
split = int(len(df) * 0.7)
X_train, X_test = X[:split], X[split:]
y_train, y_test = y[:split], y[split:]

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s  = scaler.transform(X_test)

model = LogisticRegression(max_iter=1000)
model.fit(X_train_s, y_train)

proba_test = model.predict_proba(X_test_s)[:,1]

auc   = roc_auc_score(y_test, proba_test)
brier = brier_score_loss(y_test, proba_test)
print(f"\nAUC:   {auc:.4f}  (0.5=random, 1.0=perfecto)")
print(f"Brier: {brier:.4f} (menor es mejor, 0.25=random)")

# Calibracion
cal = CalibratedClassifierCV(model, method="isotonic", cv=5)
proba_cal = cal.predict_proba(X_test_s)[:,1]

# Threshold alto — solo señales fuertes
for thr in [0.55, 0.60, 0.65]:
    mask = proba_cal > thr
    if mask.sum() > 0:
        wr = y_test[mask].mean()
        print(f"Threshold {thr}: {mask.sum()} señales | win rate {wr*100:.1f}%")

# Coeficientes
print("\n=== COEFICIENTES ===")
coefs = sorted(zip(features, model.coef_[0]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    direction = "→ mas reversal" if c > 0 else "→ menos reversal"
    print(f"  {f:<20} {c:+.4f}  {direction}")