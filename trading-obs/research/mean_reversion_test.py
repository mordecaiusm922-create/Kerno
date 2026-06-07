import sys
sys.path.insert(0, '.')
import backtester as bt

events = bt.load_events('BTCUSDT', 50000)
spikes = bt.detect_spikes(events, z_threshold=2.0, min_pct=0.01)

# Mean reversion: entra CONTRA el spike
for sp in spikes:
    sp['direction'] = 'up' if sp['direction'] == 'down' else 'down'

print("=== MEAN REVERSION TEST ===")
print(f"Eventos : {len(events)}")
print(f"Spikes  : {len(spikes)}")

for hold in [5, 10, 20, 30, 60]:
    trades = bt.run_backtest(events, spikes, hold_seconds=hold)
    stats  = bt.compute_stats(trades)
    if stats:
        print(f"hold={hold:3d}s | WR={stats['win_rate_pct']:5.1f}% | PnL={stats['total_pnl_pct']:+.4f}% | DD={stats['max_drawdown_pct']:.4f}% | PF={stats['profit_factor']}")
    else:
        print(f"hold={hold:3d}s | sin trades")
