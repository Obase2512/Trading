"""Read-only Coinbase USDC best bid/ask with independent timestamp checks.

For paper EXITS only, an official Coinbase Exchange ticker can be used when
the Advanced Trade public ticker is stale. Exchange ticker has its own trade
timestamp; never invent a price when both feeds are stale or unavailable.
This is NOT a real stop order, guaranteed exit, or executable quote.
"""
import math
import re
from datetime import datetime, timezone

import requests

EXCHANGE_TICKER = "https://api.exchange.coinbase.com/products/{product}/ticker"
MAX_AGE_SECONDS = 900
MAX_SPREAD_PCT = 3.0


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing source price timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid source timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Source timestamp lacks timezone")
    return result.timestamp()


def _quote(bid_value, ask_value, source_time, now):
    bid, ask = float(bid_value), float(ask_value)
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask)):
        raise ValueError("Invalid bid/ask")
    if bid > ask:
        raise ValueError("Crossed bid/ask")
    if (ask - bid) / ask * 100 > MAX_SPREAD_PCT:
        raise ValueError("Excessive spread; cannot safely paper-mark")
    if not (-60 <= now - source_time <= MAX_AGE_SECONDS):
        raise ValueError("Stale public ticker")
    return bid, ask


def advanced_quote(data, now):
    if not isinstance(data, dict):
        raise ValueError("Unexpected Advanced ticker")
    trades = data.get("trades")
    if not isinstance(trades, list) or not trades or not isinstance(trades[0], dict):
        raise ValueError("Missing Advanced trade timestamp")
    return _quote(data["best_bid"], data["best_ask"], _timestamp(trades[0]["time"]), now)


def exchange_quote(data, now):
    if not isinstance(data, dict):
        raise ValueError("Unexpected Exchange ticker")
    return _quote(data["bid"], data["ask"], _timestamp(data["time"]), now)


def exchange_exit_quote(product, now, requester=None):
    if not isinstance(product, str) or not re.fullmatch(r"[A-Z0-9]{2,20}-USDC", product):
        raise ValueError("Invalid Coinbase pair")
    requester = requester or requests.get
    try:
        response = requester(
            EXCHANGE_TICKER.format(product=product),
            headers={"Accept": "application/json", "User-Agent": "TradingSentinelPaper/1.0"},
            timeout=12,
        )
        response.raise_for_status()
        return exchange_quote(response.json(), now)
    except requests.RequestException:
        # Error messages can contain provider details; avoid leaking them to logs.
        raise ValueError("Exchange exit data unavailable") from None
