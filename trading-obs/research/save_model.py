import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.utils.class_weight import compute_class_weight
import pickle

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

X = df[features].values
y = df["label"].values

classes = np.unique(y)
weights = compute_class_weight("balanced", classes=classes, y=y)
cw = dict(zip(classes, weights))

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

base = LogisticRegression(max_iter=1000, C=0.1, solver="lbfgs", class_weight=cw)
base.fit(X_scaled, y)

cal = CalibratedClassifierCV(base, method="isotonic", cv=5)
cal.fit(X_scaled, y)

with open("kerno_model.pkl", "wb") as f:
    pickle.dump({"model": cal, "scaler": scaler, "features": features}, f)

print("OK: modelo guardado en kerno_model.pkl")
print(f"Entrenado con {len(df)} filas")
