"""Offline provider parser tests; missing risk information never grants approval."""
import unittest
from unittest.mock import MagicMock
import requests

from dex_security import evaluate, fetch_goplus, review

SOL = "B" * 42
BASE = "0x" + "b" * 40
HOLDERS = [{"percent": "0.035"} for _ in range(10)]


def base_data():
    value = {k: "0" for k in (
        "is_honeypot", "cannot_sell_all", "cannot_buy",
        "is_mintable", "is_proxy", "is_blacklisted", "hidden_owner",
        "owner_change_balance", "transfer_pausable", "can_take_back_ownership")}
    value.update({"is_open_source": "1", "is_in_dex": "1",
                  "buy_tax": "0.01", "sell_tax": "0.01", "holders": HOLDERS})
    return value


def sol_data():
    value = {k: {"status": "0"} for k in (
        "mintable", "freezable", "non_transferable", "closable",
        "balance_mutable_authority", "transfer_fee_upgradable",
        "transfer_hook_upgradable")}
    value.update({"default_account_state": "1", "holders": HOLDERS})
    return value


class SecurityTests(unittest.TestCase):
    def test_known_base_signals_get_preliminary_not_safety_approval(self):
        r = evaluate("base", BASE, base_data())
        self.assertEqual(r["status"], "observed_pass")
        self.assertIn("NOT verified", r["disclaimer"])

    def test_honeypot_sell_tax_and_whale_block_base(self):
        for adjustment in (
            {"is_honeypot": "1"},
            {"sell_tax": "0.9"},
            {"holders": [{"percent": "0.6"}]},
        ):
            case = base_data()
            case.update(adjustment)
            self.assertEqual(evaluate("base", BASE, case)["status"], "blocked")

    def test_unknown_fields_fail_closed_base(self):
        self.assertEqual(evaluate("base", BASE, {})["status"], "unknown")
        case = base_data()
        del case["cannot_sell_all"]
        self.assertEqual(evaluate("base", BASE, case)["status"], "unknown")

    def test_preliminary_solana_observation(self):
        self.assertEqual(evaluate("solana", SOL, sol_data())["status"], "observed_pass")
        case = sol_data()
        case["freezable"] = {"status": "1"}
        self.assertEqual(evaluate("solana", SOL, case)["status"], "blocked")

    def test_solana_unknown_mint_is_not_passed(self):
        case = sol_data()
        case["mintable"] = None
        self.assertEqual(evaluate("solana", SOL, case)["status"], "unknown")

    def test_look_up_requires_exact_address_not_any_report(self):
        fake = MagicMock()
        fake.json.return_value = {"code": 1, "result": {"unrelated": base_data()}}
        with self.assertRaises(ValueError):
            fetch_goplus("base", BASE, requester=lambda *a, **kw: fake)

    def test_failure_status_and_http_error_never_approve(self):
        def broken(*a, **kw):
            raise requests.RequestException("unavailable")
        result = review("solana", SOL, requester=broken)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["flagged"], [])

    def test_malformed_addresses_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate("solana", "wrong/bad", {})
        with self.assertRaises(ValueError):
            evaluate("base", "0x123", {})


if __name__ == "__main__":
    unittest.main()
