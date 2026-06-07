import sqlite3, pickle
import pandas as pd
import numpy as np

conn = sqlite3.connect("kerno.db")
df = pd.read_sql("""
    SELECT event_density_1m, event_density_5m, density_ratio,
           volatility_1m, vol_compression, spread_est,
           spread_z_5m, burstiness_5m, density_x_spread,
           stage1_label, event_time_ms
    FROM feature_store
    WHERE stage1_label IS NOT NULL
    ORDER BY event_time_ms ASC
""", conn)
conn.close()

df = df.dropna()
split_time = df.iloc[int(len(df)*0.7)]["event_time_ms"]
test = df[df["event_time_ms"] >= split_time + 60000]

d = pickle.load(open("kerno_stage1.pkl", "rb"))
model, scaler, features = d["model"], d["scaler"], d["features"]

X_test = scaler.transform(test[features].values)
proba = model.predict_proba(X_test)[:,1]

print("Distribucion de probabilidades:")
for lo, hi in [(0,0.3),(0.3,0.5),(0.5,0.7),(0.7,0.9),(0.9,1.0)]:
    mask = (proba >= lo) & (proba < hi)
    print(f"  {lo:.1f}-{hi:.1f}: {mask.sum():>6} ({mask.sum()/len(proba)*100:.1f}%)")

print(f"\nMedia proba: {proba.mean():.4f}")
print(f"Std proba:   {proba.std():.4f}")