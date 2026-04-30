import sys
sys.path.insert(0, ".")
import backtester as bt

events = bt.load_events("BTCUSDT", 50000)
spikes = bt.detect_spikes(events, z_threshold=2.0, min_pct=0.01)

def classify(events, idx):
    if idx + 30 >= len(events):
        return None
    entry   = events[idx]["price"]
    after5  = events[idx+5]["price"]
    after30 = events[idx+30]["price"]
    move5   = (after5  - entry) / entry * 100
    move30  = (after30 - entry) / entry * 100
    if abs(move30) < 0.005:
        return "NOISE"
    elif abs(move5) > 0.01 and abs(move30) > abs(move5) * 0.5:
        return "MOMENTUM"
    else:
        return "ABSORPTION"

absorption_spikes = []
noise_spikes      = []

for sp in spikes:
    tipo = classify(events, sp["idx"])
    if tipo == "ABSORPTION":
        rev = dict(sp)
        rev["direction"] = "up" if sp["direction"] == "down" else "down"
        absorption_spikes.append(rev)
    elif tipo == "NOISE":
        noise_spikes.append(sp)

print("=== BACKTEST POR CLASE ===")
print("")

for nombre, clase in [("ABSORPTION (mean reversion)", absorption_spikes), ("NOISE (control)", noise_spikes)]:
    if not clase:
        print(nombre, "-> sin eventos")
        continue
    print(nombre, "->", len(clase), "eventos")
    for hold in [5, 10, 30]:
        trades = bt.run_backtest(events, clase, hold_seconds=hold)
        stats  = bt.compute_stats(trades)
        if stats:
            print("  hold="+str(hold)+"s | WR="+str(stats["win_rate_pct"])+"% | PnL="+str(round(stats["total_pnl_pct"],4))+"% | PF="+str(stats["profit_factor"]))
        else:
            print("  hold="+str(hold)+"s | sin trades")
    print("")
