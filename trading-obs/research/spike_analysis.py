import sys
sys.path.insert(0, ".")
import backtester as bt

events = bt.load_events("BTCUSDT", 50000)
spikes = bt.detect_spikes(events, z_threshold=2.0, min_pct=0.01)

print("Spikes detectados:", len(spikes))
seguidos = revertidos = neutros = 0

for sp in spikes:
    idx = sp["idx"]
    if idx + 10 >= len(events):
        continue
    entry  = events[idx]["price"]
    after  = events[min(idx+5, len(events)-1)]["price"]
    move   = (after - entry) / entry * 100
    direct = sp["direction"]
    if direct == "up":
        if move > 0.005:    seguidos += 1
        elif move < -0.005: revertidos += 1
        else:               neutros += 1
    else:
        if move < -0.005:   seguidos += 1
        elif move > 0.005:  revertidos += 1
        else:               neutros += 1

total = seguidos + revertidos + neutros
print("Continuan :", seguidos,   str(round(seguidos/total*100,1) if total else 0)+"%")
print("Revierten :", revertidos, str(round(revertidos/total*100,1) if total else 0)+"%")
print("Neutros   :", neutros,    str(round(neutros/total*100,1) if total else 0)+"%")
