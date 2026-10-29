"""Offline tests proving scanner routes messages to Telegram correctly."""
import os
import unittest
from unittest.mock import patch

from scanner import notify


class NotificationRoutingTests(unittest.TestCase):
    @patch("scanner.send_telegram")
    @patch("scanner.send_twilio")
    def test_telegram_only(self, twilio, telegram):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token",
                                     "TELEGRAM_CHAT_ID": "123"}, clear=True):
            notify("PAPER BUY WATCH (test)")
        telegram.assert_called_once_with("PAPER BUY WATCH (test)")
        twilio.assert_not_called()

    @patch("scanner.send_telegram")
    @patch("scanner.send_twilio")
    def test_unconfigured_provider_logs_only(self, twilio, telegram):
        with patch.dict(os.environ, {}, clear=True):
            notify("NO OP")
        telegram.assert_not_called()
        twilio.assert_not_called()

    @patch("scanner.send_telegram")
    def test_partial_telegram_credentials_fail_closed(self, telegram):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=True):
            with self.assertRaises(ValueError):
                notify("PAPER BUY WATCH")
        telegram.assert_called_once()


if __name__ == "__main__":
    unittest.main()
