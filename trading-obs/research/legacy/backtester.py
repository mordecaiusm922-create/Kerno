"""
Kerno — Backtesting Engine v0.1
Corre sobre datos reales en kerno.db

Estrategia base: spike-follow
  - Detecta spike estadistico en precio
  - Entra en direccion del spike
  - Sale despues de hold_seconds
  - Calcula PnL, win rate, drawdown

Uso:
  python backtester.py
  python backtester.py --symbol ETHUSDT --hold 30 --min-spike 0.02
"""
import sqlite3
import argparse
import json
import os
import math
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "kerno.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_events(symbol, limit=10000):
    conn = get_conn()
    rows = conn.execute("""
        SELECT price, quantity, event_time_ms,
               (ingest_time_ms - event_time_ms) AS latency_ms,
               is_buyer_maker
        FROM market_events
        WHERE symbol = ? AND event_type = 'trade'
        ORDER BY event_time_ms ASC
        LIMIT ?
    """, (symbol.upper(), limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_spikes(events, z_threshold=2.0, min_pct=0.01):
    """
    Detecta spikes estadisticos usando z-score de los movimientos de precio.
    Retorna lista de indices donde hay spike + direccion.
    """
    if len(events) < 10:
        return []

    prices = [e["price"] for e in events]
    diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]

    avg = sum(diffs) / len(diffs)
    variance = sum((d - avg) ** 2 for d in diffs) / len(diffs)
    std = math.sqrt(variance) if variance > 0 else 0

    threshold = avg + z_threshold * std

    spikes = []
    for i in range(1, len(events)):
        diff = prices[i] - prices[i-1]
        abs_diff = abs(diff)
        pct = (abs_diff / prices[i-1]) * 100

        if abs_diff > threshold and pct >= min_pct:
            spikes.append({
                "idx":       i,
                "time_ms":   events[i]["event_time_ms"],
                "price":     prices[i],
                "prev_price": prices[i-1],
                "diff":      diff,
                "pct":       pct,
                "direction": "up" if diff > 0 else "down",
                "latency_ms": events[i]["latency_ms"],
            })

    return spikes


def run_backtest(events, spikes, hold_seconds=30, fee_pct=0.001):
    """
    Simula trades sobre cada spike detectado.
    Estrategia: entra en direccion del spike, sale despues de hold_seconds.
    fee_pct = 0.1% por lado (Binance taker fee).
    """
    if not spikes:
        return [], {}

    prices = [e["price"] for e in events]
    times  = [e["event_time_ms"] for e in events]
    hold_ms = hold_seconds * 1000

    trades = []
    for sp in spikes:
        entry_idx   = sp["idx"]
        entry_price = sp["price"]
        entry_time  = sp["time_ms"]
        direction   = sp["direction"]

        # Busca precio de salida
        exit_idx = None
        for j in range(entry_idx + 1, len(events)):
            if times[j] >= entry_time + hold_ms:
                exit_idx = j
                break

        if exit_idx is None:
            continue  # no hay suficientes datos para cerrar

        exit_price = prices[exit_idx]
        exit_time  = times[exit_idx]

        # PnL segun direccion
        if direction == "up":
            raw_return = (exit_price - entry_price) / entry_price
        else:
            raw_return = (entry_price - exit_price) / entry_price

        # Descontar fees (entrada + salida)
        net_return = raw_return - 2 * fee_pct
        net_pnl_pct = net_return * 100

        trades.append({
            "entry_time_ms":  entry_time,
            "exit_time_ms":   exit_time,
            "entry_price":    entry_price,
            "exit_price":     exit_price,
            "direction":      direction,
            "spike_pct":      sp["pct"],
            "hold_ms":        exit_time - entry_time,
            "net_pnl_pct":    net_pnl_pct,
            "win":            net_pnl_pct > 0,
            "latency_ms":     sp["latency_ms"],
        })

    return trades


def compute_stats(trades):
    if not trades:
        return {}

    n        = len(trades)
    winners  = [t for t in trades if t["win"]]
    losers   = [t for t in trades if not t["win"]]
    pnls     = [t["net_pnl_pct"] for t in trades]

    win_rate    = len(winners) / n * 100
    avg_pnl     = sum(pnls) / n
    total_pnl   = sum(pnls)
    best_trade  = max(pnls)
    worst_trade = min(pnls)

    # Max drawdown (cumulative)
    cum = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    avg_win  = sum(t["net_pnl_pct"] for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t["net_pnl_pct"] for t in losers)  / len(losers)  if losers  else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    avg_hold_s = sum(t["hold_ms"] for t in trades) / n / 1000
    avg_lat    = sum(t["latency_ms"] for t in trades) / n

    return {
        "total_trades":    n,
        "win_rate_pct":    round(win_rate,    2),
        "total_pnl_pct":   round(total_pnl,   4),
        "avg_pnl_pct":     round(avg_pnl,     4),
        "best_trade_pct":  round(best_trade,  4),
        "worst_trade_pct": round(worst_trade, 4),
        "max_drawdown_pct":round(max_dd,      4),
        "profit_factor":   round(profit_factor, 3),
        "avg_hold_sec":    round(avg_hold_s,  1),
        "avg_entry_latency_ms": round(avg_lat, 1),
        "winners":         len(winners),
        "losers":          len(losers),
    }


def save_results(symbol, params, stats, trades):
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT,
            run_time    TEXT,
            params      TEXT,
            stats       TEXT,
            trades      TEXT
        )
    """)
    conn.execute("""
        INSERT INTO backtest_results (symbol, run_time, params, stats, trades)
        VALUES (?, ?, ?, ?, ?)
    """, (
        symbol,
        datetime.now(timezone.utc).isoformat(),
        json.dumps(params),
        json.dumps(stats),
        json.dumps(trades),
    ))
    conn.commit()
    conn.close()


def print_report(symbol, params, stats, trades):
    print("")
    print("=" * 52)
    print(f"  KERNO BACKTEST — {symbol}")
    print("=" * 52)
    print(f"  Events loaded   : {params['events_loaded']}")
    print(f"  Spikes detected : {params['spikes_detected']}")
    print(f"  Hold time       : {params['hold_seconds']}s")
    print(f"  Z-threshold     : {params['z_threshold']}")
    print("-" * 52)
    if not stats:
        print("  No trades ejecutados — insuficientes datos")
        return
    print(f"  Total trades    : {stats['total_trades']}")
    print(f"  Win rate        : {stats['win_rate_pct']}%")
    print(f"  Total PnL       : {stats['total_pnl_pct']:+.4f}%")
    print(f"  Avg PnL/trade   : {stats['avg_pnl_pct']:+.4f}%")
    print(f"  Best trade      : {stats['best_trade_pct']:+.4f}%")
    print(f"  Worst trade     : {stats['worst_trade_pct']:+.4f}%")
    print(f"  Max drawdown    : -{stats['max_drawdown_pct']:.4f}%")
    print(f"  Profit factor   : {stats['profit_factor']}")
    print(f"  Avg hold        : {stats['avg_hold_sec']}s")
    print(f"  Avg entry lat   : {stats['avg_entry_latency_ms']}ms")
    print("-" * 52)

    verdict = ""
    if stats["win_rate_pct"] >= 55 and stats["total_pnl_pct"] > 0:
        verdict = "EDGE DETECTADO - estrategia tiene valor"
    elif stats["total_pnl_pct"] > 0:
        verdict = "PnL positivo - ajustar parametros"
    else:
        verdict = "Sin edge - spike-follow no funciona aqui"
    print(f"  Verdict: {verdict}")
    print("=" * 52)
    print("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kerno Backtester")
    parser.add_argument("--symbol",    default="BTCUSDT")
    parser.add_argument("--hold",      type=int,   default=30,  help="Hold time en segundos")
    parser.add_argument("--z",         type=float, default=2.0, help="Z-score threshold para spikes")
    parser.add_argument("--min-spike", type=float, default=0.01,help="Minimo pct de movimiento")
    parser.add_argument("--limit",     type=int,   default=10000)
    parser.add_argument("--no-save",   action="store_true")
    args = parser.parse_args()

    print(f"Cargando eventos de {args.symbol}...")
    events = load_events(args.symbol, args.limit)
    print(f"  {len(events)} eventos cargados")

    spikes = detect_spikes(events, z_threshold=args.z, min_pct=args.min_spike)
    print(f"  {len(spikes)} spikes detectados")

    trades = run_backtest(events, spikes, hold_seconds=args.hold)
    stats  = compute_stats(trades)

    params = {
        "symbol":          args.symbol,
        "events_loaded":   len(events),
        "spikes_detected": len(spikes),
        "hold_seconds":    args.hold,
        "z_threshold":     args.z,
        "min_spike_pct":   args.min_spike,
    }

    print_report(args.symbol, params, stats, trades)

    if not args.no_save and stats:
        save_results(args.symbol, params, stats, trades)
        print("  Resultados guardados en kerno.db")
