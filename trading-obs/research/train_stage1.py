import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.utils.class_weight import compute_class_weight
import pickle

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT event_density_1m, event_density_5m, density_ratio,
           volatility_1m, vol_compression, spread_est,
           spread_z_5m, burstiness_5m, density_x_spread,
           stage1_label, event_time_ms, symbol
    FROM feature_store
    WHERE stage1_label IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df = df.dropna()
print(f"Dataset: {len(df)} | TRADEABLE: {df['stage1_label'].mean()*100:.1f}%")

features = ["event_density_1m", "event_density_5m", "density_ratio",
            "vol_compression", "spread_est",
            "spread_z_5m", "burstiness_5m", "density_x_spread"]

X = df[features].values
y = df["stage1_label"].values

split = int(len(df) * 0.7)
split_time = df.iloc[split]["event_time_ms"]
embargo_ms = 60000

train = df[df["event_time_ms"] <= split_time - embargo_ms]
test  = df[df["event_time_ms"] >= split_time + embargo_ms]
print(f"Train: {len(train)} | Test: {len(test)}")

X_train = train[features].values
y_train = train["label"].values if "label" in train else train["stage1_label"].values
X_test  = test[features].values
y_test  = test["stage1_label"].values

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
prauc = average_precision_score(y_test, proba)
print(f"\nROC-AUC: {auc:.4f}")
print(f"PR-AUC:  {prauc:.4f}")

print("\n=== PRECISION-RECALL BUCKETS ===")
for thr in [0.3, 0.4, 0.5, 0.6, 0.7]:
    mask = proba >= thr
    if mask.sum() > 0:
        prec = y_test[mask].mean()
        rec  = mask[y_test==1].mean()
        print(f"  thr={thr}: {mask.sum():>5} signals | precision={prec:.3f} | recall={rec:.3f}")

print("\n=== COEFICIENTES ===")
coefs = sorted(zip(features, model.coef_[0]), key=lambda x: -abs(x[1]))
for f, c in coefs:
    d = "→ tradeable" if c > 0 else "→ neutral"
    print(f"  {f:<25} {c:>+7.4f}  {d}")

with open("kerno_stage1.pkl", "wb") as f:
    pickle.dump({"model": model, "scaler": scaler, "features": features}, f)
print("\nOK: kerno_stage1.pkl guardado")