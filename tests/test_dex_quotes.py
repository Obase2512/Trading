"""Offline tests for read-only two-way route validation, no order placement."""
import unittest
from unittest.mock import MagicMock, patch

import requests
import dex_quotes as q

SOL_TOKEN = "B" * 42
BASE_TOKEN = "0x" + "b" * 40


class DexQuoteTests(unittest.TestCase):
    @staticmethod
    def response(payload):
        r = MagicMock()
        r.json.return_value = payload
        return r

    def test_solana_bidirectional_routes_no_wallet_signing(self):
        def requester(url, params, headers, timeout):
            self.assertEqual(url, q.JUPITER)
            self.assertNotIn("taker", params)
            self.assertNotIn("wallet", params)
            if params["inputMint"] == q.SOL_USDC:
                return self.response({
                    "router": "metis", "inAmount": "50000000",
                    "outAmount": "10000000000", "transaction": None,
                })
            return self.response({
                "router": "metis", "inAmount": "10000000000",
                "outAmount": "48250000", "transaction": None,
            })
        delays = []
        x = q.buy_sell_preview("solana", SOL_TOKEN, requester=requester,
                               sleeper=lambda seconds: delays.append(seconds))
        self.assertEqual(x["raw_token_amount"], 10000000000)
        self.assertAlmostEqual(x["quoted_roundtrip_usdc"], 48.25)
        self.assertEqual(delays, [2.1])
        self.assertFalse(x["execution_guaranteed"])
        self.assertEqual(x["verified"], "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT")

    def test_missing_sell_route_does_not_claim_roundtrip(self):
        def requester(url, params, headers, timeout):
            if params["inputMint"] == q.SOL_USDC:
                return self.response({"router": "metis", "inAmount": "50000000",
                                      "outAmount": "10000000000", "transaction": None})
            return self.response({"errorCode": 42, "outAmount": "0"})
        with self.assertRaises(ValueError):
            q.buy_sell_preview("solana", SOL_TOKEN, requester=requester, sleeper=lambda _: None)

    def test_malformed_amounts_or_transaction_rejected(self):
        for bad in ("NaN", "0", "1e20", "-1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    q._atomic(bad)
        with self.assertRaises(ValueError):
            q._solana_quote(q.SOL_USDC, SOL_TOKEN, 50_000_000,
                            requester=lambda *a, **kw: self.response({
                                "router": "metis", "inAmount": "50000000",
                                "outAmount": "123", "transaction": "SIGNED_OR_UNSIGNED_TX"}))

    def test_rug_like_roundtrip_slippage_rejected(self):
        def requester(url, params, headers, timeout):
            if params["inputMint"] == q.SOL_USDC:
                return self.response({"router": "metis", "inAmount": "50000000",
                                      "outAmount": "10000", "transaction": None})
            return self.response({"router": "metis", "inAmount": "10000",
                                  "outAmount": "12000000", "transaction": None})
        with self.assertRaises(ValueError):
            q.buy_sell_preview("solana", SOL_TOKEN, requester=requester, sleeper=lambda _: None)

    def test_base_requires_key_no_0x_calls_if_missing(self):
        with patch.dict("os.environ", {"ZEROX_API_KEY": ""}):
            with self.assertRaises(ValueError):
                q.buy_sell_preview("base", BASE_TOKEN, requester=lambda *a, **kw: None)

    def test_base_0x_v2_read_only_buy_and_sell(self):
        seen = []
        def requester(url, params, headers, timeout):
            self.assertEqual(url, q.ZERO_EX)
            self.assertEqual(params["chainId"], "8453")
            self.assertEqual(headers["0x-version"], "v2")
            seen.append(params.copy())
            buy = params["sellToken"].lower() == q.BASE_USDC.lower()
            return self.response({
                "liquidityAvailable": True,
                "sellAmount": params["sellAmount"],
                "sellToken": params["sellToken"], "buyToken": params["buyToken"],
                "buyAmount": "8000000000000000000" if buy else "47400000",
                "issues": {"simulationIncomplete": False},
            })
        with patch.dict("os.environ", {"ZEROX_API_KEY": "mock-only-key"}):
            result = q.buy_sell_preview("base", BASE_TOKEN, requester=requester)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["sellToken"].lower(), q.BASE_USDC.lower())
        self.assertEqual(seen[1]["sellAmount"], "8000000000000000000")
        self.assertEqual(result["quoted_roundtrip_usdc"], 47.4)
        self.assertFalse(result["execution_guaranteed"])

    def test_base_insufficient_liquidity_and_incomplete_simulation(self):
        for response in (
            {"liquidityAvailable": False},
            {"liquidityAvailable": True, "sellAmount": "50000000",
             "buyAmount": "1000000000", "issues": {"simulationIncomplete": True}},
        ):
            with self.subTest(response=response), patch.dict("os.environ", {"ZEROX_API_KEY": "fake"}):
                with self.assertRaises(ValueError):
                    q._base_quote(q.BASE_USDC, BASE_TOKEN, 50000000,
                                  requester=lambda *a, **kw: self.response(response))

    def test_sell_only_quotes_return_net_not_guaranteed(self):
        def requester(url, params, headers, timeout):
            return self.response({"router": "metis", "inAmount": params["amount"],
                                  "outAmount": "53000000", "transaction": None})
        result = q.indicative_sale("solana", SOL_TOKEN, 10**9, requester=requester)
        self.assertAlmostEqual(result["quoted_net_usdc"], 52.6)
        self.assertFalse(result["execution_guaranteed"])


if __name__ == "__main__":
    unittest.main()
