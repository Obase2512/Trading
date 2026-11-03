"""Test DEX shadow trades without touching Coinbase paper state or Telegram."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import requests
import dex_shadow as dex

NOW = 1800000000.0
SOL = "B" * 42


def candidate(pool="A"*40, token=SOL, network="solana"):
    return {"pool_key": network + ":" + pool, "pool_address": pool,
            "token_address": token, "network": network, "meme_theme_hint": True,
            "repeat_observed": True, "research_priority_score": 90,
            "age_hours": 1.5, "liquidity_usd": 300_000,
            "volume_24h_usd": 750_000}


def write_source(directory, items):
    path = directory / "radar.json"
    path.write_text(json.dumps({
        "version": 1, "updated_utc": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
        "candidates": items,
    }))
    return path


def always_pass(*args):
    return {"status": "observed_pass", "flagged": [], "unknown": []}


def basic_quote(*args):
    return {"price": 1.0, "liquidity": 300_000}


class ShadowTests(unittest.TestCase):
    def run_case(self, folder, risk=always_pass, price=basic_quote, now=NOW):
        return dex.run_once(now=now, risk_fn=risk, price_fn=price,
                            radar_path=folder/"radar.json",
                            state_path=folder/"shadow.json",
                            audit_path=folder/"audit.json")

    def test_opens_three_50_shadow_positions_fourth_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_source(folder, [candidate(pool=str(i)*40, token=str(i+1)*42) for i in range(4)])
            state, reviews, events = self.run_case(folder)
            self.assertEqual(state["cash_usdc"], 0)
            self.assertEqual(len(state["positions"]), 3)
            self.assertEqual(len(events), 3)
            self.assertEqual(len(reviews), 4)
            self.assertFalse(any("REAL" in x for x in events))
            self.assertIn("NOT the Coinbase", state["warnings"][0])
            second, _, events2 = self.run_case(folder, now=NOW+1000)
            self.assertEqual(len(second["positions"]), 3)
            self.assertEqual(events2, [])
            self.assertEqual(json.loads((folder/"audit.json").read_text())["mode"], "PRELIMINARY ONLY")

    def test_unverified_security_never_opens_paper_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_source(folder, [candidate()])
            state, _, _ = self.run_case(folder, risk=lambda *_: {"status": "unknown"})
            self.assertEqual(state["positions"], {})
            self.assertEqual(state["cash_usdc"], 150)

    def test_unconfirmed_repeat_or_weak_candidate_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            c = candidate()
            c["repeat_observed"] = False
            write_source(folder, [c])
            state, _, _ = self.run_case(folder)
            self.assertEqual(len(state["positions"]), 0)

    def test_shadow_exit_has_cost_and_does_not_pretend_actual_sale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_source(folder, [candidate()])
            state, _, _ = self.run_case(folder)
            self.assertEqual(state["cash_usdc"], 100)
            def rising(*_):
                return {"price": 1.5, "liquidity": 320_000}
            state2, _, events = self.run_case(folder, now=NOW + 1800, price=rising)
            self.assertEqual(state2["cash_usdc"] > 150, True)
            self.assertEqual(len(state2["trades"]), 1)
            self.assertEqual(state2["trades"][0]["execution"], "UNVERIFIED modeled pool mark, not tradable fill")
            self.assertEqual(len(state2["positions"]), 0)
            self.assertEqual(len(events), 1)

    def test_unavailable_sell_price_never_records_fake_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_source(folder, [candidate()])
            self.run_case(folder)
            def bad(*_):
                raise requests.RequestException("missing liquidity")
            state, _, events = self.run_case(folder, price=bad, now=NOW + 1800)
            self.assertEqual(len(state["positions"]), 1)
            self.assertEqual(len(state["trades"]), 0)
            self.assertIn("cannot claim a sale",
                          list(state["positions"].values())[0]["pricing_warning"])
            self.assertEqual(events, [])

    def test_public_pool_rejects_mismatched_address(self):
        from unittest.mock import MagicMock
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"attributes": {"address": "not-the-requested-pool",
                                    "base_token_price_usd": "1", "reserve_in_usd": "300000"}}}
        with self.assertRaises(ValueError):
            dex.public_pool("solana", "A"*40, requester=lambda *a, **k: mock_response)


if __name__ == "__main__":
    unittest.main()
