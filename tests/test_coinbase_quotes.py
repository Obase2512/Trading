"""Offline fail-closed Coinbase paper quote and independent exit feed tests."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
import coinbase_quotes as cq
import paper_alerts
from signals import initial_state, entry

NOW = 1_800_000_000
TIMESTAMP = datetime.fromtimestamp(NOW - 15, timezone.utc).isoformat()


def market(product):
    return {"product": product, "bid": 1.0, "ask": 1.01,
            "entry_watch": True, "score": 100, "spread_pct": 0.4,
            "momentum_6h_pct": 3, "turnover_24h_usd": 500000}


class QuoteTests(unittest.TestCase):
    def test_advanced_and_exchange_fresh_timestamps(self):
        self.assertEqual(cq.advanced_quote({
            "best_bid": "1.0", "best_ask": "1.01",
            "trades": [{"time": TIMESTAMP}],
        }, NOW), (1.0, 1.01))
        self.assertEqual(cq.exchange_quote({
            "bid": "1.0", "ask": "1.01", "time": TIMESTAMP,
        }, NOW), (1.0, 1.01))

    def test_stale_source_missing_timestamp_or_crossed_book_refused(self):
        stale = datetime.fromtimestamp(NOW - 2000, timezone.utc).isoformat()
        for data in (
            {"bid": "1", "ask": "1.1", "time": stale},
            {"bid": "1", "ask": "1.1", "time": "invalid"},
            {"bid": "2", "ask": "1", "time": TIMESTAMP},
            {"bid": "0.1", "ask": "2", "time": TIMESTAMP},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                cq.exchange_quote(data, NOW)

    def test_exchange_only_used_when_primary_exit_quote_unavailable(self):
        fake = MagicMock()
        fake.json.return_value = {"bid": "1.20", "ask": "1.21", "time": TIMESTAMP}
        with (patch.object(paper_alerts, "market_quote", side_effect=ValueError("stale")),
              patch("coinbase_quotes.requests.get", return_value=fake) as requester):
            quote, source = paper_alerts.exit_market_quote("BONK-USDC", NOW)
        self.assertEqual(source, "coinbase_exchange")
        self.assertEqual(quote, (1.2, 1.21))
        self.assertEqual(requester.call_args.kwargs["timeout"], 12)

    def test_exchange_fallback_fails_closed_if_not_independently_fresh(self):
        fake = MagicMock()
        fake.json.return_value = {"bid": "1.20", "ask": "1.21",
                                  "time": datetime.fromtimestamp(NOW - 4000, timezone.utc).isoformat()}
        with (patch.object(paper_alerts, "market_quote", side_effect=ValueError("stale")),
              patch("coinbase_quotes.requests.get", return_value=fake),
              self.assertRaises(ValueError)):
            paper_alerts.exit_market_quote("BONK-USDC", NOW)

    def test_failed_exit_quotes_report_unavailability_without_fake_sell(self):
        state = initial_state()
        entry(state, market("BONK-USDC"), NOW - 3600)
        state["realized_pnl_usdc"] = -19.49  # loss cap reached; no new entries
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "paper_state.json"
            path.write_text(json.dumps(state))
            with (patch.object(paper_alerts, "STATE_PATH", path),
                  patch.object(paper_alerts, "exit_market_quote",
                               side_effect=ValueError("stale independent feeds")),
                  patch.object(paper_alerts, "watchlist") as watch,
                  patch.object(paper_alerts, "publish_signal_alerts") as send):
                result, alerts = paper_alerts.scan_once(NOW)
                self.assertEqual(alerts, [])
                self.assertIn("BONK-USDC", result["positions"])
                self.assertEqual(result["monitoring"]["exit_quotes"]["BONK-USDC"]["status"], "unavailable")
                self.assertEqual(result["monitoring"]["exit_quotes"]["BONK-USDC"]["consecutive_failures"], 1)
                self.assertEqual(result["trades"], [])
                watch.assert_not_called()
                send.assert_called_once_with([])
            self.assertEqual(json.loads(path.read_text())["positions"].keys(), result["positions"].keys())

    def test_exit_success_resets_health_and_sells_when_modeled_threshold_met(self):
        state = initial_state()
        entry(state, market("BONK-USDC"), NOW - 3600)
        state["monitoring"] = {"exit_quotes": {"BONK-USDC": {
            "status": "unavailable", "consecutive_failures": 5}}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text(json.dumps(state))
            with (patch.object(paper_alerts, "STATE_PATH", path),
                  patch.object(paper_alerts, "exit_market_quote",
                               return_value=((1.25, 1.26), "coinbase_exchange")),
                  patch.object(paper_alerts, "watchlist", return_value=[]),
                  patch.object(paper_alerts, "publish_signal_alerts") as send):
                result, alerts = paper_alerts.scan_once(NOW)
                self.assertEqual(len(alerts), 1)
                self.assertTrue(alerts[0].startswith("PAPER SELL WATCH BONK-USDC"))
                self.assertEqual(result["positions"], {})
                self.assertNotIn("BONK-USDC", result["monitoring"]["exit_quotes"])
                send.assert_called_once_with(alerts)


if __name__ == "__main__":
    unittest.main()
