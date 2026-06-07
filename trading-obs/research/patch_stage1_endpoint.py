X = _np.array([[
        (r["spike_pct"] or 0), (r["zscore"] or 0), (r["spread_est"] or 0),
        (r["volatility_1m"] or 0), (r["latency_ms"] or 0),
        (r["imbalance_20"] or 0), (r["burst_1s"] or 0),
        (r["vol_ratio"] or 0), (r["dir_burst"] or 0)
    ] for r in rows])
    X_scaled = scaler.transform(X)
    scores   = model.predict_proba(X_scaled)[:,1]

    # Stage 1
    s1_model, s1_scaler, s1_features = _load_stage1()
    s1_scores = [0.5] * len(rows)
    if s1_model is not None:
        try:
            conn2 = get_conn()
            s1_rows = conn2.execute(
                "SELECT id, event_density_1m, event_density_5m, density_ratio, "
                "vol_compression, spread_est, spread_z_5m, burstiness_5m, density_x_spread "
                "FROM feature_store WHERE symbol=? AND imbalance_20 IS NOT NULL "
                "ORDER BY event_time_ms DESC LIMIT 200",
                (symbol.upper(),)
            ).fetchall()
            conn2.close()
            id_to_idx = {r["id"]: i for i, r in enumerate(rows)}
            X_s1 = _np.array([[
                float(r["event_density_1m"] or 0),
                float(r["event_density_5m"] or 0),
                float(r["density_ratio"] or 1),
                float(r["vol_compression"] or 1),
                float(r["spread_est"] or 0),
                float(r["spread_z_5m"] or 0),
                float(r["burstiness_5m"] or 1),
                float(r["density_x_spread"] or 0),
            ] for r in s1_rows])
            X_s1_scaled = s1_scaler.transform(X_s1)
            s1_probs = s1_model.predict_proba(X_s1_scaled)[:,1]
            for j, r in enumerate(s1_rows):
                if r["id"] in id_to_idx:
                    s1_scores[id_to_idx[r["id"]]] = float(s1_probs[j])
        except Exception as e:
            print(f"[stage1] error: {e}")

    out = []
    for i, r in enumerate(rows):
        score = float(scores[i])
        p_tradeable = s1_scores[i]
        joint = round(p_tradeable * score, 3)
        if p_tradeable < 0.45:
            sig = "NO_EDGE"
            conf = "LOW"
        else:
            sig = "CONTINUATION" if score >= 0.5 else "ABSORPTION"
            conf = "HIGH" if joint >= 0.6 else ("MEDIUM" if joint >= 0.4 else "LOW")
        if sig == "NO_EDGE" and min_score > 0.3:
            continue
        if sig != "NO_EDGE" and score < min_score:
            continue
        bkt = r["bucket"] or "UNKNOWN"