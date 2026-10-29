import os
import unittest
from unittest.mock import patch, MagicMock

from telegram_alerts import send_telegram


class TelegramDeliveryTests(unittest.TestCase):
    def test_missing_credentials_never_sends(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("telegram_alerts.requests.post") as call:
                with self.assertRaises(ValueError):
                    send_telegram("TEST")
                call.assert_not_called()

    def test_successful_message(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True}
        with patch("telegram_alerts.requests.post", return_value=response) as call:
            self.assertTrue(send_telegram("PAPER BUY WATCH", token="secret", chat_id="12345"))
            self.assertEqual(call.call_args.kwargs["data"]["chat_id"], "12345")
            self.assertEqual(call.call_args.kwargs["data"]["text"], "PAPER BUY WATCH")

    def test_api_error_does_not_leak_token(self):
        response = MagicMock(status_code=403)
        with patch("telegram_alerts.requests.post", return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                send_telegram("TEST", token="private-token", chat_id="123")
        self.assertNotIn("private-token", str(caught.exception))

    def test_network_failure_does_not_leak_token(self):
        import requests
        with patch("telegram_alerts.requests.post",
                   side_effect=requests.RequestException("https://api.telegram.org/botprivate-token")):
            with self.assertRaises(RuntimeError) as caught:
                send_telegram("TEST", token="private-token", chat_id="123")
        self.assertNotIn("private-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
