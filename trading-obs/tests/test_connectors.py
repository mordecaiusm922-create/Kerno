import json

from kerno.connectors import build_connector, canonical_symbol
from kerno.connectors.coinbase import parse_iso_to_ms


def test_binance_combined_and_raw_frames():
    c = build_connector("binance", ["btcusdt", "ETHUSDT"])
    assert c.url().endswith("streams=btcusdt@trade/ethusdt@trade")
    payload = {"e": "trade", "s": "BTCUSDT", "t": 12345, "p": "65000.10", "q": "0.002", "T": 1700000000123, "m": True}
    for frame in (json.dumps({"stream": "btcusdt@trade", "data": payload}), json.dumps(payload)):
        [t] = c.parse_message(frame)
        assert t["exchange_trade_id"] == "12345" and t["side"] == "sell" and t["price"] == 65000.10
        assert json.loads(t["raw"]) == payload


def test_bybit_perp_suffix_and_per_trade_raw():
    c = build_connector("bybit", ["BTCUSDT"])
    msg = {"topic": "publicTrade.BTCUSDT", "data": [
        {"s": "BTCUSDT", "i": "a", "p": "65000", "v": "0.1", "S": "Buy", "T": 1},
        {"s": "BTCUSDT", "i": "b", "p": "65001", "v": "0.2", "S": "Sell", "T": 2},
    ]}
    trades = c.parse_message(json.dumps(msg))
    assert [t["symbol"] for t in trades] == ["BTCUSDT-PERP"] * 2
    assert [t["side"] for t in trades] == ["buy", "sell"]
    # raw is the single trade, not the whole batch (the old code stored the batch N times)
    assert json.loads(trades[1]["raw"])["i"] == "b"
    assert canonical_symbol("bybit", "btcusdt") == "BTCUSDT-PERP"


def test_okx_and_errors():
    c = build_connector("okx", ["BTC-USDT"])
    assert c.parse_message("pong") == []
    assert c.parse_message(json.dumps({"event": "error", "code": "1", "msg": "x"})) == []
    msg = {"arg": {"channel": "trades"}, "data": [
        {"instId": "BTC-USDT", "tradeId": "9", "px": "1", "sz": "2", "side": "buy", "ts": "3"}]}
    [t] = c.parse_message(json.dumps(msg))
    assert t["event_time_ms"] == 3 and t["quantity"] == 2.0


def test_coinbase_timestamps_and_bad_payloads():
    assert parse_iso_to_ms("2023-02-09T20:19:35.39625135Z") == 1675973975396
    assert parse_iso_to_ms("2023-02-09T20:19:35Z") == 1675973975000
    c = build_connector("coinbase", ["BTC-USD"])
    good = {"product_id": "BTC-USD", "trade_id": "1", "price": "10", "size": "1", "side": "BUY",
            "time": "2023-02-09T20:19:35.1Z"}
    bad = {"product_id": "BTC-USD", "trade_id": "2", "price": "-1", "size": "1", "side": "BUY",
           "time": "2023-02-09T20:19:35.1Z"}
    msg = {"channel": "market_trades", "events": [{"trades": [good, bad, {"garbage": 1}]}]}
    assert [t["exchange_trade_id"] for t in c.parse_message(json.dumps(msg))] == ["1"]
    assert c.parse_message("not json") == []
    assert c.parse_message(b"\xff") == []
