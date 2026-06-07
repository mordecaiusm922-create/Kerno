content = open("api.py", encoding="utf-8").read()

old = '    cls = signal + "_" + bucket if signal != "NO_EDGE" else "NOISE_" + bucket\n    return {\n        "signal": signal, "classification": cls, "bucket": bucket,\n        "prob_reversal": prob_rev, "prob_continuation": prob_cont,\n        "confidence": confidence,\n    }'

new = '    cls = signal + "_" + bucket if signal != "NO_EDGE" else "NOISE_" + bucket\n    zscore = round((m - p.get("mean", 0)) / p.get("std", 1), 3) if p.get("std", 0) > 0 else 0\n    return {\n        "signal": signal, "classification": cls, "bucket": bucket,\n        "prob_reversal": prob_rev, "prob_continuation": prob_cont,\n        "confidence": confidence, "zscore": zscore, "regime_n": p.get("n", 0),\n    }'

if old in content:
    content = content.replace(old, new, 1)
    open("api.py", "w", encoding="utf-8").write(content)
    print("OK: zscore y regime_n agregados")
else:
    print("NOT FOUND - buscando texto actual...")
    idx = content.find('cls = signal + "_" + bucket')
    print(repr(content[idx:idx+200]))