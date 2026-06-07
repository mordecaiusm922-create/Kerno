import sys
sys.path.insert(0, ".")
import backtester as bt

events = bt.load_events("BTCUSDT", 50000)
spikes = bt.detect_spikes(events, z_threshold=2.0, min_pct=0.01)

print("=== CLASIFICADOR DE EVENTOS ===")
noise = momentum = absorption = 0

for sp in spikes:
    idx = sp["idx"]
    if idx + 30 >= len(events):
        continue
    entry   = events[idx]["price"]
    after5  = events[idx+5]["price"]
    after30 = events[idx+30]["price"]
    move5   = (after5  - entry) / entry * 100
    move30  = (after30 - entry) / entry * 100
    vol     = sum(e["quantity"] for e in events[idx:idx+5])

    if abs(move30) < 0.005:
        noise += 1
        tipo = "NOISE"
    elif abs(move5) > 0.01 and abs(move30) > abs(move5) * 0.5:
        momentum += 1
        tipo = "MOMENTUM"
    else:
        absorption += 1
        tipo = "ABSORPTION"

    print(f"  {tipo:12s} | spike={sp['pct']:.3f}% | move5={move5:+.4f}% | move30={move30:+.4f}% | vol={vol:.4f}")

total = noise + momentum + absorption
print("")
print(f"NOISE      : {noise}  ({round(noise/total*100,1) if total else 0}%)")
print(f"MOMENTUM   : {momentum}  ({round(momentum/total*100,1) if total else 0}%)")
print(f"ABSORPTION : {absorption}  ({round(absorption/total*100,1) if total else 0}%)")
