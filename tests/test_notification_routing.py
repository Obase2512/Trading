"""Offline tests: market discovery never notifies; only paper BUY/SELL can."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scanner
from paper_alerts import publish_signal_alerts


class NotificationRoutingTests(unittest.TestCase):
    @patch("scanner.send_telegram")
    @patch("scanner.dex_profiles", return_value={})
    @patch("scanner.coinbase", return_value={"DOGE": "DOGE-USDC", "NEW": "NEW-USDC"})
    def test_discovery_does_not_send_telegram(self, _coinbase, _dex, telegram):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"initialized": True,
                                         "coinbase": {"DOGE": "DOGE-USDC"},
                                         "seen": {}}))
            with patch("scanner.state_file", state), patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_CHAT_ID": "123"}, clear=True):
                scanner.run()
        telegram.assert_not_called()

    @patch("paper_alerts.send_telegram")
    def test_only_qualifying_buy_and_sell_sent(self, telegram):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token",
                                     "TELEGRAM_CHAT_ID": "123"}, clear=True):
            publish_signal_alerts([
                "New Coinbase spot symbol detected: NEW",
                "Unverified DEX watchlist: MEME",
                "PAPER BUY WATCH DOGE-USDC: test signal",
                "PAPER HOLD DOGE-USDC: no exit yet",
                "PAPER SELL WATCH DOGE-USDC: test signal",
                "Routine scan completed",
            ])
        self.assertEqual(telegram.call_count, 2)
        self.assertEqual(telegram.call_args_list[0].args[0],
                         "PAPER BUY WATCH DOGE-USDC: test signal")
        self.assertEqual(telegram.call_args_list[1].args[0],
                         "PAPER SELL WATCH DOGE-USDC: test signal")

    @patch("paper_alerts.send_telegram")
    def test_no_signal_means_no_message(self, telegram):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token",
                                     "TELEGRAM_CHAT_ID": "123"}, clear=True):
            publish_signal_alerts([])
        telegram.assert_not_called()

    @patch("paper_alerts.send_telegram")
    def test_missing_credentials_suppresses_messages(self, telegram):
        with patch.dict(os.environ, {}, clear=True):
            publish_signal_alerts(["PAPER BUY WATCH DOGE-USDC: test"])
        telegram.assert_not_called()


if __name__ == "__main__":
    unittest.main()
