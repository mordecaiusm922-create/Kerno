content = open("api.py", encoding="utf-8").read()

old = '''        out.append({
            "symbol":        symbol.upper(),
            "price":         r["price"],
            "event_time_ms": r["event_time_ms"],
            "signal":        sig,
            "spike_type":    bkt,
            "score":         round(score'''

new = '''        # Top 3 drivers por magnitud de contribucion
        feature_names = ["spike_pct","zscore","spread_est","volatility_1m",
                         "latency_ms","imbalance_20","burst_1s","vol_ratio","dir_burst"]
        try:
            base_model = model.calibrated_classifiers_[0].estimator
            coefs = base_model.coef_[0]
            contribs = {f: abs(float(coefs[i]) * float(X_scaled[i][i])) 
                       for i, f in enumerate(feature_names)}
            drivers = sorted(contribs, key=contribs.get, reverse=True)[:3]
        except:
            drivers = ["spike_pct", "vol_ratio", "spread_est"]
        out.append({
            "symbol":        symbol.upper(),
            "price":         r["price"],
            "event_time_ms": r["event_time_ms"],
            "signal":        sig,
            "spike_type":    bkt,
            "score":         round(score'''

if old in content:
    content = content.replace(old, new, 1)
    # Agregar drivers al dict de respuesta
    content = content.replace(
        '"action":        "FILTER_IN" if score >= 0.65 else "MONITOR"',
        '"action":        "FILTER_IN" if score >= 0.65 else "MONITOR",\n            "drivers": drivers',
        1
    )
    open("api.py", "w", encoding="utf-8").write(content)
    print("OK: drivers agregados")
else:
    print("NOT FOUND - buscando texto...")
    idx = content.find('"symbol":        symbol.upper()')
    print(repr(content[idx-100:idx+200]))