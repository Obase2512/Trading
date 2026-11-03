"""Offline non-trading route-health probes."""
import os
import unittest
from unittest.mock import patch

import dex_quote_health as health


def ok(network, address, amount):
    return {"verified": "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT",
            "execution_guaranteed": False, "quoted_roundtrip_loss_pct": 1.3,
            "gas_buffer_usdc": 0.4, "buy_provider": "read-only",
            "sell_provider": "read-only"}


class QuoteHealthTests(unittest.TestCase):
    def test_solana_ok_base_key_not_configured(self):
        with patch.dict(os.environ, {"ZEROX_API_KEY": ""}):
            result = health.inspect(now=1800000000, quote_fn=ok)
        self.assertEqual(result["status"]["solana"]["status"], "ok")
        self.assertEqual(result["status"]["base"]["status"], "not_configured")

    def test_both_providers_healthy_when_optional_key_exists(self):
        with patch.dict(os.environ, {"ZEROX_API_KEY": "fake-key"}):
            result = health.inspect(now=1800000000, quote_fn=ok)
        self.assertEqual(result["status"]["base"]["status"], "ok")
        self.assertFalse(result["status"]["base"]["execution_guaranteed"])

    def test_missing_or_wrong_quote_never_claimed_healthy(self):
        with patch.dict(os.environ, {"ZEROX_API_KEY": ""}):
            result = health.inspect(
                now=1800000000, quote_fn=lambda *args: {"verified": "unknown"})
        self.assertEqual(result["status"]["solana"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
