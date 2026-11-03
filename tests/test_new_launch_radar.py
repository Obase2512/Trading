"""All launch-radar tests are offline: no network or real trading credentials."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests
import new_launch_radar as radar

NOW = 1_800_000_000.0


def sample_pool(pool_id="solana_pool_address_00000000000000", minutes_old=45,
                liquidity=180_000, volume=340_000, buys=420, sells=170,
                title="HappyDog / SOL", network="solana"):
    address = ("A" * 40) if network == "solana" else ("0x" + "a" * 40)
    token = ("B" * 42) if network == "solana" else ("0x" + "b" * 40)
    created = datetime.fromtimestamp(NOW - minutes_old * 60, timezone.utc).isoformat()
    return {
        "id": pool_id,
        "attributes": {
            "address": address,
            "pool_created_at": created,
            "name": title,
            "reserve_in_usd": str(liquidity),
            "volume_usd": {"h24": str(volume)},
            "transactions": {"h24": {"buys": buys, "sells": sells}},
            "price_change_percentage": {"h1": "5.3"},
            "fdv_usd": str(1_000_000),
        },
        "relationships": {"base_token": {
            "data": {"id": network + "_" + token}
        }},
    }


class LaunchRadarTests(unittest.TestCase):
    def test_early_pool_research_only_never_trade(self):
        item = radar.parse_pool(sample_pool(), "solana", NOW)
        self.assertIsNotNone(item)
        self.assertTrue(item["meme_theme_hint"])
        self.assertFalse(item["eligible_for_buy_alert"])
        self.assertEqual(item["security_review"], "NOT PERFORMED")
        self.assertTrue(item["url"].startswith("https://www.geckoterminal.com/solana/pools/"))
        self.assertGreater(item["research_priority_score"], 45)

    def test_stale_and_too_new_pools_are_not_shortlisted(self):
        for age in (2, 73 * 60):
            with self.subTest(minutes_old=age):
                self.assertIsNone(radar.parse_pool(sample_pool(minutes_old=age), "solana", NOW))

    def test_low_liquidity_or_buy_sell_activity_rejected(self):
        cases = [
            {"liquidity": 5_000},
            {"volume": 12_000},
            {"buys": 10},
            {"sells": 2},
            {"volume": 20_000_000},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(radar.parse_pool(sample_pool(**kwargs), "solana", NOW))

    def test_token_id_and_pool_addresses_required(self):
        p = sample_pool()
        p["relationships"]["base_token"]["data"]["id"] = "solana_fake"
        self.assertIsNone(radar.parse_pool(p, "solana", NOW))
        p = sample_pool()
        p["attributes"]["address"] = "bad/path?/"
        self.assertIsNone(radar.parse_pool(p, "solana", NOW))

    def test_missing_fields_do_not_promote_anything(self):
        p = sample_pool()
        del p["attributes"]["transactions"]
        self.assertIsNone(radar.parse_pool(p, "solana", NOW))
        p = sample_pool()
        p["attributes"]["reserve_in_usd"] = "NaN"
        self.assertIsNone(radar.parse_pool(p, "solana", NOW))

    def test_repeated_independent_observations_recorded(self):
        p = sample_pool()
        get = lambda network, page: [p] if network == "solana" and page == 1 else []
        first = radar.collect(now=NOW, fetcher=get)
        second = radar.collect(now=NOW + 1800, fetcher=get, prior=first)
        self.assertEqual(len(first["candidates"]), 1)
        self.assertEqual(first["candidates"][0]["observation_count"], 1)
        self.assertEqual(second["candidates"][0]["observation_count"], 2)
        self.assertTrue(second["candidates"][0]["repeat_observed"])
        self.assertEqual(second["candidates"][0]["eligible_for_buy_alert"], False)

    def test_bad_network_does_not_fetch(self):
        with self.assertRaises(ValueError):
            radar.fetch_new_pools("ethereum", 1)
        with self.assertRaises(ValueError):
            radar.fetch_new_pools("solana", 99)

    def test_public_api_fetch_shape_and_timeout(self):
        response = MagicMock()
        response.json.return_value = {"data": [sample_pool()]}
        requester = MagicMock(return_value=response)
        rows = radar.fetch_new_pools("solana", 2, requester=requester)
        self.assertEqual(len(rows), 1)
        self.assertEqual(requester.call_args.kwargs["timeout"], 18)
        self.assertEqual(requester.call_args.kwargs["params"], {"page": 2})

    def test_all_feeds_unavailable_does_not_write_state(self):
        def unavailable(network, page):
            raise requests.RequestException("API not available")
        with self.assertRaises(RuntimeError):
            radar.collect(now=NOW, fetcher=unavailable)

    def test_partial_failure_reports_coverage_limits(self):
        def fetching(network, page):
            if network == "solana":
                raise requests.RequestException("down")
            return [sample_pool(network="base", pool_id="base_id")] if page == 1 else []
        result = radar.collect(now=NOW, fetcher=fetching)
        self.assertGreater(result["successful_pages"], 0)
        self.assertTrue(result["errors"])
        self.assertEqual(len(result["candidates"]), 1)



    def test_watch_lead_surfaces_early_pool_below_strict_trade_filters(self):
        p = sample_pool(minutes_old=3, liquidity=25_000, volume=21_000,
                        buys=12, sells=8)
        self.assertIsNone(radar.parse_pool(p, "solana", NOW))
        lead = radar.parse_watch_lead(p, "solana", NOW)
        self.assertIsNotNone(lead)
        self.assertEqual(lead["status"], "UNVERIFIED_WATCH_ONLY")
        self.assertFalse(lead["eligible_for_buy_alert"])
        result = radar.collect(now=NOW,
                               fetcher=lambda network, page:
                               [p] if network == "solana" and page == 1 else [])
        self.assertEqual(len(result["candidates"]), 0)
        self.assertEqual(len(result["watch_leads"]), 1)
        self.assertTrue(result["coverage_complete"])

    def test_paging_delay_applied_without_slowing_offline_test(self):
        calls = []
        def fetching(network, page):
            calls.append((network, page))
            return []
        delays = []
        x = radar.collect(now=NOW, fetcher=fetching, sleeper=lambda sec: delays.append(sec),
                          page_gap_seconds=2.1)
        self.assertEqual(x["successful_pages"], 6)
        self.assertEqual(len(delays), 5)
        self.assertEqual(calls[0], ("solana", 1))
        self.assertEqual(x["pages_by_network"], {"solana": 3, "base": 3})

    def test_rate_limit_retries_honor_retry_after_bounded(self):
        retry = MagicMock()
        retry.status_code = 429
        retry.headers = {"Retry-After": "3"}
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"data": [sample_pool()]}
        requester = MagicMock(side_effect=[retry, ok])
        delays = []
        x = radar.fetch_new_pools("solana", 1, requester=requester,
                                  sleeper=lambda secs: delays.append(secs))
        self.assertEqual(len(x), 1)
        self.assertEqual(delays, [3.0])
        self.assertEqual(requester.call_count, 2)

    def test_repeated_429_cannot_claim_full_coverage(self):
        no = MagicMock()
        no.status_code = 429
        no.headers = {}
        no.raise_for_status.side_effect = requests.HTTPError("429")
        req = MagicMock(return_value=no)
        with self.assertRaises(requests.HTTPError):
            radar.fetch_new_pools("solana", 1, requester=req,
                                  sleeper=lambda _: None)
        self.assertEqual(req.call_count, 3)

if __name__ == "__main__":
    unittest.main()
