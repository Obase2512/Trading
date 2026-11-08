"""Independent DEX Screener research feed tests, no internet or wallet."""
import unittest

import solana_launch_feed as feed

NOW = 1800000000.0
TOKEN = "B" * 42
POOL = "A" * 40


def example_pair(age_min=35, token=TOKEN):
    return {
        "chainId": "solana", "pairAddress": POOL,
        "baseToken": {"address": token, "symbol": "DOGE", "name": "Lucky Dog"},
        "pairCreatedAt": int((NOW - 60 * age_min) * 1000),
        "liquidity": {"usd": 35000},
        "volume": {"h24": 24000},
        "txns": {"h24": {"buys": 21, "sells": 15}},
    }


class SecondaryDiscoveryTests(unittest.TestCase):
    def test_recent_pool_is_only_unverified_watch_lead(self):
        lead = feed.parse_pair(TOKEN, example_pair(), NOW)
        self.assertEqual(lead["status"], "RESEARCH_ONLY_UNVERIFIED")
        self.assertFalse(lead["eligible_for_buy_alert"])
        self.assertIn("promoted", lead["source_caveat"].lower())
        self.assertEqual(lead["token_address"], TOKEN)

    def test_mismatched_chain_token_or_stale_pool_refused(self):
        for data in (
            dict(example_pair(), chainId="ethereum"),
            example_pair(age_min=80*60),
            example_pair(token="C"*42),
            dict(example_pair(), pairAddress="../../bad"),
            dict(example_pair(), liquidity={"usd": "NaN"}),
        ):
            with self.subTest(data=data):
                self.assertIsNone(feed.parse_pair(TOKEN, data, NOW))

    def test_profiles_and_pairs_work_but_cannot_enable_trades(self):
        calls = []
        def fetch(path):
            calls.append(path)
            if path == "/token-profiles/latest/v1":
                return [{"chainId": "solana", "tokenAddress": TOKEN},
                        {"chainId": "solana", "tokenAddress": TOKEN},
                        {"chainId": "base", "tokenAddress": "0x" + "a"*40}]
            return [example_pair()]
        result = feed.collect(now=NOW, fetch=fetch, sleep=lambda _: None)
        self.assertEqual(result["profile_tokens_inspected"], 1)
        self.assertEqual(result["successful_pair_lookups"], 1)
        self.assertEqual(len(result["leads"]), 1)
        self.assertFalse(result["trading_eligible"])
        self.assertEqual(len(calls), 2)

    def test_unavailable_pair_lookup_reports_failures_without_fabricating_leads(self):
        def fetch(path):
            if "latest" in path:
                return [{"chainId": "solana", "tokenAddress": TOKEN}]
            raise ValueError("HTTP 429")
        result = feed.collect(now=NOW, fetch=fetch, sleep=lambda _: None)
        self.assertEqual(result["lookup_errors"], 1)
        self.assertEqual(result["leads"], [])


if __name__ == "__main__":
    unittest.main()
