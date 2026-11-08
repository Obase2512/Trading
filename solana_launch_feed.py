"""Independent secondary Solana launch research source: DEX Screener token profiles.

DEX Screener profiles can be promoted/paid and DO NOT enumerate every launch.
Pair creation timestamps are POOL dates, not token mint dates. This feed never
creates simulated entries, security clearance, Telegram alerts or real trades.
"""
import json
import logging
import os
from pathlib import Path
import math
import re
import time
from datetime import datetime, timezone

import requests

LOG = logging.getLogger("sentinel.solana_secondary")
BASE = "https://api.dexscreener.com"
STATE_PATH = Path(os.getenv("SENTINEL_STATE_DIR", "data")) / "solana_secondary.json"
MAX_LOOKUPS = 8
MAX_WATCH = 12
MAX_PAIR_AGE_HOURS = 72
SOL_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _float(v):
    try:
        val = float(v)
        if math.isfinite(val) and val >= 0:
            return val
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _get(path, requester=None):
    requester = requester or requests.get
    try:
        resp = requester(BASE + path, timeout=12,
                         headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        raise ValueError("DEX Screener request unavailable") from None
    if not isinstance(data, list):
        raise ValueError("Unexpected DEX Screener data")
    return data


def parse_pair(token, pair, now):
    if (not isinstance(pair, dict) or pair.get("chainId") != "solana" or
            not isinstance(token, str) or not SOL_ADDRESS.fullmatch(token)):
        return None
    bt = pair.get("baseToken")
    if not isinstance(bt, dict) or bt.get("address") != token:
        return None
    pair_address = pair.get("pairAddress")
    if not isinstance(pair_address, str) or not SOL_ADDRESS.fullmatch(pair_address):
        return None
    created = _float(pair.get("pairCreatedAt"))
    if created is None:
        return None
    age_h = (now - created / 1000) / 3600
    if not 0 <= age_h <= MAX_PAIR_AGE_HOURS:
        return None
    liquidity = _float((pair.get("liquidity") or {}).get("usd"))
    volume = _float((pair.get("volume") or {}).get("h24"))
    tx = (pair.get("txns") or {}).get("h24")
    if not isinstance(tx, dict):
        return None
    buys = _float(tx.get("buys"))
    sells = _float(tx.get("sells"))
    if any(v is None for v in (liquidity, volume, buys, sells)):
        return None
    if liquidity < 15_000 or volume < 8_000 or buys < 5 or sells < 5:
        return None
    name = str(bt.get("name") or bt.get("symbol") or "Unknown")[:100]
    return {
        "network": "solana", "pool_key": "solana:" + pair_address,
        "pool_address": pair_address, "token_address": token,
        "pool_name": name, "pool_age_hours": round(age_h, 2),
        "liquidity_usd": round(liquidity), "volume_24h_usd": round(volume),
        "buys_24h": int(buys), "sells_24h": int(sells),
        "source": "DEX Screener latest token profiles + token-pairs API",
        "source_caveat": ("Profiles may be promoted; pool age is not token age. "
                         "No independent contract review or future sell quote."),
        "eligible_for_buy_alert": False, "status": "RESEARCH_ONLY_UNVERIFIED",
        "url": "https://dexscreener.com/solana/" + pair_address,
    }


def collect(now=None, fetch=None, sleep=None):
    now = time.time() if now is None else now
    fetch = fetch or _get
    sleep = sleep or time.sleep
    profiles = fetch("/token-profiles/latest/v1")
    if not isinstance(profiles, list):
        raise ValueError("Token profile feed shape invalid")
    unique = []
    seen = set()
    for item in profiles:
        if not isinstance(item, dict) or item.get("chainId") != "solana":
            continue
        address = item.get("tokenAddress")
        if not isinstance(address, str) or not SOL_ADDRESS.fullmatch(address) or address in seen:
            continue
        seen.add(address)
        unique.append(address)
        if len(unique) == MAX_LOOKUPS:
            break

    leads = {}
    errors = 0
    successful = 0
    for i, token in enumerate(unique):
        if i:
            sleep(0.25)  # polite pacing even on public endpoints
        try:
            pairs = fetch(f"/token-pairs/v1/solana/{token}")
            successful += 1
        except (ValueError, TypeError, requests.RequestException):
            errors += 1
            continue
        if not isinstance(pairs, list):
            errors += 1
            continue
        for pair in pairs:
            lead = parse_pair(token, pair, now)
            if lead:
                leads[lead["pool_key"]] = lead
    return {
        "source": "DEX Screener recently profiled Solana tokens; incomplete/promoted feed",
        "updated_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "profile_tokens_inspected": len(unique),
        "successful_pair_lookups": successful,
        "lookup_errors": errors,
        "leads": sorted(leads.values(),
                        key=lambda x: (-x["liquidity_usd"], -x["volume_24h_usd"],
                                       x["pool_key"]))[:MAX_WATCH],
        "trading_eligible": False,
    }



def run():
    """Persist independent secondary lead list, even if GeckoTerminal is down."""
    try:
        result = collect()
    except (ValueError, TypeError, requests.RequestException) as exc:
        LOG.warning("Secondary Solana discovery unavailable (%s): prior state retained",
                    type(exc).__name__)
        return None
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temp.replace(STATE_PATH)
    LOG.info("SECONDARY SOLANA: %d unverified profile-linked leads, %d pair lookup errors. "
             "No buy signals or real orders.", len(result["leads"]), result["lookup_errors"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
