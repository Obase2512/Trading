"""Offline tests. Zero external services or exchange orders."""
import unittest
from copy import deepcopy
from signals import (
    STARTING_USDC, POSITION_USDC, MAX_POSITIONS, assess_market,
    assess_exit, entry, fresh_candles, initial_state, migrate_state,
    validate_state,
)


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

    def market(self, coin="DOGE-USDC"):
        result = assess_market(coin, self.candles, self.bid, self.ask)
        self.assertTrue(result["entry_watch"])
        return result

    def test_initial_state_has_150_and_no_positions(self):
        state = initial_state()
        self.assertEqual(state["version"], 2)
        self.assertEqual(state["cash_usdc"], 150)
        self.assertEqual(state["positions"], {})
        self.assertEqual(MAX_POSITIONS, 3)

    def test_complete_fresh_candles(self):
        self.assertEqual(len(self.candles), 24)
        self.assertEqual(self.candles[-1]["close"], self.prices[-1])

    def test_stale_or_missing_candles_rejected(self):
        self.assertEqual(fresh_candles(self.raw, self.now + 3 * 3600), [])
        self.assertEqual(fresh_candles({"candles": []}, self.now), [])

    def test_bullish_market_meets_research_filters(self):
        market = self.market()
        self.assertEqual(market["score"], 100)

    def test_bad_spread_no_buy(self):
        result = assess_market("DOGE-USDC", self.candles, self.bid * 0.97, self.ask)
        self.assertFalse(result["entry_watch"])

    def test_three_simultaneous_50_positions_and_fourth_rejected(self):
        state = initial_state()
        for coin in ("DOGE-USDC", "PEPE-USDC", "BONK-USDC"):
            self.assertIsNotNone(entry(state, self.market(coin), self.now))
        self.assertEqual(len(state["positions"]), 3)
        self.assertEqual(state["cash_usdc"], 0)
        self.assertEqual(sum(p["entry_cost_usdc"] for p in state["positions"].values()), 150)
        self.assertIsNone(entry(state, self.market("SHIB-USDC"), self.now))

    def test_duplicate_coin_not_bought_twice(self):
        state = initial_state()
        market = self.market()
        self.assertIsNotNone(entry(state, market, self.now))
        self.assertIsNone(entry(state, market, self.now + 1))
        self.assertEqual(state["cash_usdc"], 100)

    def test_independent_sell_only_one_position(self):
        state = initial_state()
        for coin in ("DOGE-USDC", "PEPE-USDC", "BONK-USDC"):
            entry(state, self.market(coin), self.now)
        result = assess_exit(state, "DOGE-USDC", self.ask * 1.20, self.now + 1800)
        self.assertTrue(result["exit"])
        self.assertEqual(set(state["positions"]), {"PEPE-USDC", "BONK-USDC"})
        self.assertGreater(state["cash_usdc"], POSITION_USDC)
        self.assertEqual(state["trades"][0]["product"], "DOGE-USDC")

    def test_stop_loss_and_trailing_are_independent(self):
        state = initial_state()
        entry(state, self.market("DOGE-USDC"), self.now)
        entry(state, self.market("PEPE-USDC"), self.now)
        self.assertFalse(assess_exit(state, "PEPE-USDC", self.ask * 1.10, self.now + 1800)["exit"])
        self.assertTrue(assess_exit(state, "DOGE-USDC", self.ask * 0.85, self.now + 1800)["exit"])
        self.assertTrue(assess_exit(state, "PEPE-USDC", self.ask * 1.03, self.now + 3600)["exit"])
        self.assertEqual(len(state["trades"]), 2)

    def test_six_hour_same_coin_reentry_cooldown(self):
        state = initial_state()
        market = self.market()
        entry(state, market, self.now)
        assess_exit(state, "DOGE-USDC", self.ask * 1.20, self.now + 1800)
        self.assertIsNone(entry(state, market, self.now + 3600))
        self.assertIsNotNone(entry(state, market, self.now + 8 * 3600))

    def test_realized_loss_cap_stops_new_buys(self):
        state = initial_state()
        state["realized_pnl_usdc"] = -15.0
        self.assertIsNone(entry(state, self.market(), self.now))

    def test_legacy_migration_preserves_10_doge_and_history(self):
        old = {
            "version": 1, "starting_usdc": 50.0, "cash_usdc": 40.0,
            "position": {"product": "DOGE-USDC", "units": 100.0,
                         "entry_cost_usdc": 10.0, "entry_time": 1.0,
                         "entry_execution_price": 0.10, "peak_net_pct": 1.0},
            "realized_pnl_usdc": 0.0,
            "trades": [{"product": "PEPE-USDC", "exit_time": 4.0}],
        }
        new = migrate_state(old)
        self.assertEqual(new["cash_usdc"], 140.0)
        self.assertEqual(new["starting_usdc"], 150.0)
        self.assertEqual(new["positions"]["DOGE-USDC"]["entry_cost_usdc"], 10.0)
        self.assertEqual(new["trades"], old["trades"])
        self.assertEqual(len(new["capital_additions"]), 1)
        self.assertNotIn("positions", old)
        # Reading a version-2 state again must never credit another $100.
        twice = migrate_state(deepcopy(new))
        self.assertEqual(twice["cash_usdc"], 140.0)
        self.assertEqual(len(twice["capital_additions"]), 1)
        # A legacy $10 position occupies one slot but does not get resized.
        self.assertIsNotNone(entry(twice, self.market("PEPE-USDC"), self.now))
        self.assertIsNotNone(entry(twice, self.market("BONK-USDC"), self.now))
        self.assertEqual(twice["cash_usdc"], 40.0)
        self.assertEqual(len(twice["positions"]), 3)

    def test_invalid_old_version_or_malformed_state_fails_closed(self):
        with self.assertRaises(ValueError):
            migrate_state({"version": 0})
        state = initial_state()
        state["cash_usdc"] = -1
        with self.assertRaises(ValueError):
            validate_state(state)


if __name__ == "__main__":
    unittest.main()
