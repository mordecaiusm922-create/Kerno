import sys
sys.path.insert(0, ".")
import backtester as bt

events = bt.load_events("BTCUSDT", 50000)
spikes = bt.detect_spikes(events, z_threshold=2.0, min_pct=0.01)

for sp in spikes:
    sp["direction"] = "up" if sp["direction"] == "down" else "down"

print("=== MEAN REVERSION TEST ===")
print("Eventos :", len(events))
print("Spikes  :", len(spikes))

for hold in [5, 10, 20, 30, 60]:
    trades = bt.run_backtest(events, spikes, hold_seconds=hold)
    stats  = bt.compute_stats(trades)
    if stats:
        print("hold="+str(hold)+"s WR="+str(stats["win_rate_pct"])+"% PnL="+str(stats["total_pnl_pct"])+"% PF="+str(stats["profit_factor"]))
    else:
        print("hold="+str(hold)+"s sin trades")
