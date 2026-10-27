"""Offline tests: no Coinbase account, no network calls, no real trades."""
import unittest
from signals import (STARTING_USDC, assess_market, assess_exit, entry,
                     fresh_candles, initial_state)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.hour = (1900000000 // 3600) * 3600
        self.now = self.hour + 1800
        self.prices = [1.004 ** i for i in range(24)]
        self.raw = {"candles": [
            {"start": str(self.hour - (24 - i) * 3600),
             "close": str(v), "volume": "7000"}
            for i, v in enumerate(self.prices)]}
        self.candles = fresh_candles(self.raw, self.now)
        self.bid = self.prices[-1] * 0.997
        self.ask = self.prices[-1] * 1.001

    def test_complete_fresh_candles(self):
        self.assertEqual(len(self.candles), 24)
        self.assertEqual(self.candles[-1]["close"], self.prices[-1])

    def test_stale_or_missing_candles_rejected(self):
        self.assertEqual(fresh_candles(self.raw, self.now + 3 * 3600), [])
        self.assertEqual(fresh_candles({"candles": []}, self.now), [])

    def test_bullish_market_meets_research_filters(self):
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        self.assertTrue(market["entry_watch"])
        self.assertEqual(market["score"], 100)

    def test_bad_spread_no_buy(self):
        market = assess_market("DOGE-USDC", self.candles, self.bid * 0.97, self.ask)
        self.assertFalse(market["entry_watch"])

    def test_paper_entry_and_profit_exit(self):
        state = initial_state()
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        position = entry(state, market, self.now)
        self.assertIsNotNone(position)
        self.assertAlmostEqual(state["cash_usdc"], 40)
        result = assess_exit(state, self.ask * 1.20, self.now + 1800)
        self.assertTrue(result["exit"])
        self.assertIsNone(state["position"])
        self.assertGreater(state["cash_usdc"], STARTING_USDC)
        self.assertEqual(len(state["trades"]), 1)

    def test_paper_stop_loss(self):
        state = initial_state()
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        entry(state, market, self.now)
        result = assess_exit(state, self.ask * 0.85, self.now + 1800)
        self.assertTrue(result["exit"])
        self.assertLess(state["cash_usdc"], STARTING_USDC)
        self.assertIn("stop-loss", result["trade"]["reason"])

    def test_trailing_exit(self):
        state = initial_state()
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        entry(state, market, self.now)
        r1 = assess_exit(state, self.ask * 1.10, self.now + 1800)
        self.assertFalse(r1["exit"])
        r2 = assess_exit(state, self.ask * 1.03, self.now + 3600)
        self.assertTrue(r2["exit"])
        self.assertIn("trailing", r2["trade"]["reason"])

    def test_loss_limit_blocks_new_entry(self):
        state = initial_state()
        state["realized_pnl_usdc"] = -10
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        self.assertIsNone(entry(state, market, self.now))

    def test_cannot_open_second_position(self):
        state = initial_state()
        market = assess_market("DOGE-USDC", self.candles, self.bid, self.ask)
        self.assertIsNotNone(entry(state, market, self.now))
        self.assertIsNone(entry(state, market, self.now + 3600))
        self.assertAlmostEqual(state["cash_usdc"], 40)


if __name__ == "__main__":
    unittest.main()
