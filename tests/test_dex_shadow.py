"""DEX shadow: independent read-only routed-quote paper tests, offline."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import requests
import dex_shadow as dex

NOW = 1_800_000_000.0
SOL = "B" * 42


def candidate(pool="A"*40, token=SOL, network="solana"):
    return {"pool_key": network + ":" + pool, "pool_address": pool,
            "token_address": token, "network": network, "meme_theme_hint": True,
            "repeat_observed": True, "research_priority_score": 90,
            "age_hours": 1.5, "liquidity_usd": 300_000,
            "volume_24h_usd": 750_000}


def write_source(folder, items, updated=NOW):
    path = folder / "radar.json"
    path.write_text(json.dumps({
        "version": 1, "updated_utc": datetime.fromtimestamp(updated, timezone.utc).isoformat(),
        "candidates": items,
    }))
    return path


def always_pass(*args):
    return {"status": "observed_pass", "flagged": [], "unknown": []}


def good_buy(network, token, amount):
    return {"network": network, "token_address": token,
            "verified": "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT",
            "execution_guaranteed": False, "raw_token_amount": 2_000_000_000,
            "quoted_roundtrip_usdc": 48.0,
            "quoted_roundtrip_after_gas_buffer_usdc": 47.2,
            "quoted_roundtrip_loss_pct": 4.0,
            "gas_buffer_usdc": 0.4,
            "buy_provider": "mock-Jupiter", "sell_provider": "mock-Jupiter"}


def good_sale(network, token, raw_amount):
    return {"network": network, "token_address": token,
            "verified": "INDICATIVE_SELL_ROUTE_ONLY", "execution_guaranteed": False,
            "quoted_net_usdc": 65.0}


class ShadowTests(unittest.TestCase):
    def run_case(self, folder, risk=always_pass, quote=good_buy, sale=good_sale, now=NOW):
        return dex.run_once(now=now, risk_fn=risk, quote_fn=quote, sale_fn=sale,
                            radar_path=folder/"radar.json", state_path=folder/"shadow.json",
                            audit_path=folder/"audit.json")

    def test_three_independent_50_positions_and_no_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_source(folder, [candidate(pool=str(i)*40, token=str(i+1)*42)
                                  for i in range(4)])
            state, reviews, events = self.run_case(folder)
            self.assertEqual(state["version"], 2)
            self.assertEqual(state["cash_usdc"], 0)
            self.assertEqual(len(state["positions"]), 3)
            self.assertEqual(len(events), 3)
            self.assertTrue(all(p["execution_model"] == "routed_indicative_v2"
                                for p in state["positions"].values()))
            self.assertEqual(len(reviews), 4)
            self.assertEqual(json.loads((folder/"audit.json").read_text())["mode"],
                             "INDICATIVE QUOTES ONLY")
            next_state, _, events2 = self.run_case(folder, now=NOW + 300,
                                                    risk=lambda *_: {"status": "unknown"})
            self.assertEqual(len(next_state["positions"]), 0)
            self.assertEqual(len(next_state["trades"]), 3)
            self.assertEqual(len(events2), 3)  # separate indicative exits

    def test_unknown_risk_no_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()])
            state, _, events = self.run_case(d, risk=lambda *_: {"status": "unknown"})
            self.assertEqual(events, [])
            self.assertEqual(state["cash_usdc"], 150)

    def test_no_usable_two_way_quote_never_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()])
            def unavailable(*_):
                raise requests.RequestException("no routes")
            state, reviews, events = self.run_case(d, quote=unavailable)
            self.assertEqual(state["positions"], {})
            self.assertEqual(state["cash_usdc"], 150)
            self.assertEqual(events, [])
            self.assertEqual(reviews[0]["swap_quote"], "unavailable_or_rejected")

    def test_unavailable_sell_route_never_records_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()])
            self.run_case(d)
            def no_sell(*_):
                raise requests.RequestException("no sell route")
            state, _, events = self.run_case(d, sale=no_sell, now=NOW + 1800)
            self.assertEqual(len(state["positions"]), 1)
            self.assertEqual(len(state["trades"]), 0)
            self.assertEqual(events, [])
            self.assertIn("no modeled exit",
                          list(state["positions"].values())[0]["pricing_warning"])

    def test_quoted_exit_net_proceeds_used_for_realized_paper_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()])
            self.run_case(d)
            state, _, events = self.run_case(d, sale=good_sale, now=NOW + 1800)
            self.assertEqual(len(state["trades"]), 1)
            self.assertEqual(state["cash_usdc"], 165)
            self.assertEqual(state["trades"][0]["pnl_usdc"], 15)
            self.assertIn("NOT an executable sale", state["trades"][0]["execution"])
            self.assertEqual(len(events), 1)

    def test_stale_radar_refuses_new_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()], updated=NOW-20000)
            state, _, _ = self.run_case(d)
            self.assertEqual(state["positions"], {})
            self.assertEqual(state["cash_usdc"], 150)

    def test_legacy_v1_preserved_not_fabricated_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [])
            old = {
                "version": 1, "starting_usdc": 150, "cash_usdc": 100,
                "positions": {"solana:legacy": {
                    "pool_key": "solana:legacy", "network": "solana",
                    "pool_address": "A"*40, "token_address": SOL,
                    "units": 100.0, "entry_price_usd": 1.0,
                    "entry_usdc": 50, "entry_time": 123456.0,
                }},
                "trades": [], "realized_pnl_usdc": 0.0,
            }
            (d/"shadow.json").write_text(json.dumps(old))
            state, _, events = self.run_case(d)
            self.assertEqual(state["version"], 2)
            self.assertEqual(state["cash_usdc"], 100)
            self.assertEqual(len(state["positions"]), 1)
            self.assertEqual(state["trades"], [])
            self.assertEqual(events, [])
            self.assertIn("Legacy", state["positions"]["solana:legacy"]["pricing_warning"])

    def test_invalid_provider_claims_cannot_invent_approved_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_source(d, [candidate()])
            def bogus(network, token, amount):
                response = good_buy(network, token, amount)
                response["execution_guaranteed"] = True
                return response
            state, _, _ = self.run_case(d, quote=bogus)
            self.assertEqual(state["positions"], {})


if __name__ == "__main__":
    unittest.main()
