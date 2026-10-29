"""End-to-end isolated scans: multiple simulated buys/independent sell alerts."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_alerts
from signals import initial_state


def market(product):
    return {"product": product, "bid": 1.0, "ask": 1.01,
            "entry_watch": True, "score": 100, "spread_pct": 0.5,
            "momentum_6h_pct": 4.0, "momentum_1h_pct": 1.0,
            "turnover_24h_usd": 1000000}


class IntegrationTests(unittest.TestCase):
    def test_multiple_qualifying_coins_generate_separate_buy_alerts(self):
        symbols = ["DOGE-USDC", "PEPE-USDC", "BONK-USDC", "SHIB-USDC"]
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(paper_alerts, "STATE_PATH", Path(directory)/"paper.json"),
                  patch.object(paper_alerts, "watchlist", return_value=symbols),
                  patch.object(paper_alerts, "market_quote", return_value=(1.0, 1.01)),
                  patch.object(paper_alerts, "public_candles", return_value=[]),
                  patch.object(paper_alerts, "assess_market", side_effect=lambda p, *_: market(p)),
                  patch.object(paper_alerts, "publish_signal_alerts") as send):
                state, alerts = paper_alerts.scan_once(1900000000)
                self.assertEqual(len(alerts), 3)
                self.assertTrue(all(a.startswith("PAPER BUY WATCH ") for a in alerts))
                self.assertEqual(len(state["positions"]), 3)
                self.assertEqual(state["cash_usdc"], 0)
                send.assert_called_once_with(alerts)
                self.assertEqual(json.loads((Path(directory)/"paper.json").read_text())["version"], 2)
                # Second run has no new position/alert and no duplicate buy.
                state2, alerts2 = paper_alerts.scan_once(1900001800)
                self.assertEqual(alerts2, [])
                self.assertEqual(len(state2["positions"]), 3)

    def test_two_independent_simulated_sell_alerts_on_same_scan(self):
        state = initial_state()
        from signals import entry
        for coin in ("DOGE-USDC", "PEPE-USDC", "BONK-USDC"):
            entry(state, market(coin), 1900000000)
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory)/"paper.json"
            state_file.write_text(json.dumps(state))
            prices = {"DOGE-USDC": (1.2, 1.21), "PEPE-USDC": (0.8, 0.81),
                      "BONK-USDC": (1.03, 1.04)}
            with (patch.object(paper_alerts, "STATE_PATH", state_file),
                  patch.object(paper_alerts, "market_quote", side_effect=lambda p, _: prices[p]),
                  patch.object(paper_alerts, "watchlist", return_value=[]),
                  patch.object(paper_alerts, "publish_signal_alerts") as send):
                state2, alerts = paper_alerts.scan_once(1900001800)
                self.assertEqual(sum("PAPER SELL WATCH" in a for a in alerts), 2)
                self.assertEqual(set(state2["positions"]), {"BONK-USDC"})
                self.assertEqual(len(state2["trades"]), 2)
                send.assert_called_once_with(alerts)

    def test_watchlist_filters_unlisted_coinbase_products(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)/"state.json"
            d.write_text(json.dumps({"coinbase": {"DOGE": "DOGE-USDC", "PEPE": "PEPE-USD"}}))
            with (patch.object(paper_alerts, "DISCOVERY_PATH", d),
                  patch.dict(os.environ, {"PAPER_WATCHLIST": "DOGE-USDC,PEPE-USDC"})):
                self.assertEqual(paper_alerts.watchlist(), ["DOGE-USDC"])


if __name__ == "__main__":
    unittest.main()
