"""Read-only DEX quote-provider connectivity probe, independent of meme picks.

Tests two-way $50 USDC routes on known-liquid reference tokens only.
No trading signals, wallet access, transaction creation/signing or Telegram.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from dex_quotes import buy_sell_preview

LOG = logging.getLogger("sentinel.quote_probe")
PATH = Path(os.getenv("SENTINEL_STATE_DIR", "data")) / "dex_quote_health.json"
# Wrapped SOL (Solana) and WETH (Base) are *reference* assets only.
REFERENCE_TOKENS = {
    "solana": "So11111111111111111111111111111111111111112",
    "base": "0x4200000000000000000000000000000000000006",
}


def inspect(now=None, quote_fn=None):
    now = time.time() if now is None else now
    quote_fn = quote_fn or buy_sell_preview
    result = {
        "updated_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "mode": "READ_ONLY_ROUTE_HEALTH_CHECK",
        "amount_usdc": 50,
        "status": {},
        "note": ("Reference-token round trip is a routing health test ONLY; "
                 "does not certify a new meme token is safe, routable or sellable."),
    }
    for network, token in REFERENCE_TOKENS.items():
        if network == "base" and not os.getenv("ZEROX_API_KEY", "").strip():
            result["status"][network] = {
                "status": "not_configured", "reason": "ZEROX_API_KEY absent"
            }
            continue
        try:
            quote = quote_fn(network, token, 50)
            if (quote.get("verified") != "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT"
                    or quote.get("execution_guaranteed") is not False):
                raise ValueError("Provider did not return read-only 2-way quote")
            result["status"][network] = {
                "status": "ok",
                "provider_buy": quote.get("buy_provider", "unknown"),
                "provider_sell": quote.get("sell_provider", "unknown"),
                "quoted_roundtrip_loss_pct": quote["quoted_roundtrip_loss_pct"],
                "estimated_gas_buffer_usdc_each_side": quote["gas_buffer_usdc"],
                "execution_guaranteed": False,
            }
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as exc:
            LOG.warning("Read-only quote health unavailable for %s (%s)",
                        network, type(exc).__name__)
            result["status"][network] = {
                "status": "unavailable", "error_type": type(exc).__name__,
                "execution_guaranteed": False,
            }
    return result


def run():
    result = inspect()
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    tmp.replace(PATH)
    for network, status in result["status"].items():
        LOG.info("QUOTE ROUTE HEALTH %s: %s (research-only, no transaction)",
                 network, status["status"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
