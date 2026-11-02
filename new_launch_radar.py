"""Research-only early-launch radar for Solana and Base DEX pools.

IMPORTANT: Newly created pools are not necessarily newly minted tokens or meme
coins. Liquidity, turnover and social names can be manipulated. No automated
buy/sell alerts, no paper position, and no actual Coinbase/DEX orders result
from this feed. Candidates must pass independent contract/holder/security checks
and a separate trade-model validation before any trading feature is considered.
"""
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

LOG = logging.getLogger("sentinel.launch_radar")
BASE_URL = "https://api.geckoterminal.com/api/v2"
STATE_PATH = Path("data/new_launch_radar.json")
NETWORKS = ("solana", "base")
PAGES_PER_NETWORK = 3
MAX_SEEN = 700
MAX_CANDIDATES = 20
MAX_POOL_AGE_HOURS = 72
MIN_POOL_AGE_MINUTES = 5

# Descriptive tag only; meme labeling is heuristic and is NEVER a safety check.
MEME_TERMS = (
    "doge", "dog", "shib", "inu", "pepe", "frog", "cat", "kitty",
    "meme", "bonk", "floki", "wojak", "chad", "moon", "capy",
    "hamster", "pengu", "pudgy", "troll", "fart", "goat", "rat",
    "pup", "wif", "pnut", "musk", "elon", "kek", "poop",
)
UNTRUSTED_QUOTES = {
    "so11111111111111111111111111111111111111112",
    "epjfwdd5aufqssqem2qn1xzybapc8g4weg gkzwytdt1v".replace(" ", ""),
    "0x4200000000000000000000000000000000000006",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
}


def _finite(value, default=None):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return default
    return number if math.isfinite(number) else default


def _created_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def _address(pool, network):
    attrs = pool.get("attributes") or {}
    address = attrs.get("address")
    if not isinstance(address, str) or not re.fullmatch(r"[A-Za-z0-9]{20,70}", address):
        return None
    return address


def _base_token_address(pool, network):
    token = (((pool.get("relationships") or {}).get("base_token") or {})
             .get("data") or {})
    token_id = token.get("id")
    if not isinstance(token_id, str) or not token_id.startswith(network + "_"):
        return None
    value = token_id[len(network) + 1:]
    if not re.fullmatch(r"[A-Za-z0-9]{20,70}", value):
        return None
    return value


def parse_pool(pool, network, now):
    """Parse one GeckoTerminal pool; reject incomplete or implausible observations."""
    if network not in NETWORKS or not isinstance(pool, dict):
        return None
    attrs = pool.get("attributes")
    if not isinstance(attrs, dict):
        return None
    address = _address(pool, network)
    token = _base_token_address(pool, network)
    if not address or not token or token.lower() in UNTRUSTED_QUOTES:
        return None
    created = _created_timestamp(attrs.get("pool_created_at"))
    if created is None:
        return None
    age_minutes = (now - created) / 60.0
    if not (MIN_POOL_AGE_MINUTES <= age_minutes <= MAX_POOL_AGE_HOURS * 60):
        return None
    liquidity = _finite(attrs.get("reserve_in_usd"))
    volumes = attrs.get("volume_usd") or {}
    tx = (attrs.get("transactions") or {}).get("h24") or {}
    if not isinstance(volumes, dict) or not isinstance(tx, dict):
        return None
    volume = _finite(volumes.get("h24"))
    buys = _finite(tx.get("buys"))
    sells = _finite(tx.get("sells"))
    if (liquidity is None or volume is None or buys is None or sells is None
            or liquidity < 0 or volume < 0 or buys < 0 or sells < 0):
        return None

    # Conservative research shortlist gate, NOT a test for fake volume or rugs.
    if liquidity < 75_000 or volume < 150_000 or buys < 60 or sells < 30:
        return None
    volume_to_liquidity = volume / liquidity
    if volume_to_liquidity < 0.35 or volume_to_liquidity > 30:
        return None

    name = attrs.get("name")
    name = name[:100] if isinstance(name, str) else "Unknown token"
    hint = any(term in name.lower() for term in MEME_TERMS)
    # No unsupported inference that this IS a meme coin.
    pct = attrs.get("price_change_percentage") or {}
    one_hour_pct = _finite(pct.get("h1")) if isinstance(pct, dict) else None
    fdv = _finite(attrs.get("fdv_usd"))
    if fdv is not None and fdv < 0:
        fdv = None

    score = 0
    score += 15 if liquidity >= 250_000 else 10 if liquidity >= 125_000 else 5
    score += 15 if volume >= 750_000 else 10 if volume >= 350_000 else 5
    score += 15 if buys >= 500 and sells >= 200 else 10 if buys >= 200 and sells >= 80 else 5
    score += 10 if age_minutes >= 30 else 5
    score += 10 if buys / max(sells, 1) >= 1.2 else 5
    score += 10 if 0.5 <= volume_to_liquidity <= 8 else 5
    score += 10 if one_hour_pct is not None and 0 < one_hour_pct <= 30 else 0
    score += 10 if fdv is not None and fdv <= 30 * liquidity else 0
    score += 5 if hint else 0

    # Scores describe observable research activity, NOT safety or future returns.
    if score < 45:
        return None
    if not hint and score < 70:
        return None

    return {
        "pool_key": network + ":" + address,
        "network": network,
        "pool_address": address,
        "token_address": token,
        "pool_name": name,
        "age_hours": round(age_minutes / 60, 2),
        "liquidity_usd": round(liquidity),
        "volume_24h_usd": round(volume),
        "buys_24h": int(buys),
        "sells_24h": int(sells),
        "volume_liquidity_ratio": round(volume_to_liquidity, 2),
        "one_hour_change_pct": round(one_hour_pct, 2) if one_hour_pct is not None else None,
        "fdv_usd": round(fdv) if fdv is not None else None,
        "meme_theme_hint": hint,
        "research_priority_score": score,
        "security_review": "NOT PERFORMED",
        "eligible_for_buy_alert": False,
        "url": f"https://www.geckoterminal.com/{network}/pools/{address}",
    }


def fetch_new_pools(network, page, requester=None):
    """Official public GeckoTerminal API, paginated; no paid boosts feed."""
    if network not in NETWORKS or not (1 <= page <= PAGES_PER_NETWORK):
        raise ValueError("Invalid network or page")
    requester = requester or requests.get
    response = requester(
        f"{BASE_URL}/networks/{network}/new_pools",
        params={"page": page},
        headers={"Accept": "application/json"},
        timeout=18,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("Unexpected new-pools API response")
    return body["data"]


def collect(now=None, fetcher=None, prior=None):
    """Collect independent public pool observations with bounded state."""
    now = time.time() if now is None else now
    fetcher = fetcher or fetch_new_pools
    prior = prior or {}
    prior_seen = prior.get("seen", {})
    if not isinstance(prior_seen, dict):
        prior_seen = {}
    seen = {}
    for key, entry in prior_seen.items():
        if (isinstance(key, str) and isinstance(entry, dict)
                and _finite(entry.get("last_seen"), -1) >= now - 4 * 86400):
            seen[key] = {
                "first_seen": _finite(entry.get("first_seen"), now),
                "last_seen": _finite(entry.get("last_seen"), now),
                "observations": min(100, max(1, int(_finite(entry.get("observations"), 1)))),
            }
    records = {}
    errors = []
    inspected = 0
    successful_pages = 0

    for network in NETWORKS:
        for page in range(1, PAGES_PER_NETWORK + 1):
            try:
                pools = fetcher(network, page)
                if not isinstance(pools, list):
                    raise ValueError("Pool result is not a list")
                successful_pages += 1
            except (requests.RequestException, ValueError, TypeError) as exc:
                LOG.warning("New-pool fetch failed (%s page %d): %s", network, page, exc)
                errors.append(f"{network}: page {page} unavailable")
                break
            for pool in pools:
                inspected += 1
                if not isinstance(pool, dict):
                    continue
                key = pool.get("id")
                # GeckoTerminal pool IDs are stable provider IDs.
                if isinstance(key, str) and len(key) <= 140:
                    item = seen.get(key, {"first_seen": now, "last_seen": now,
                                          "observations": 0})
                    if item.get("last_seen", 0) < now - 60:
                        item["observations"] += 1
                    elif item["observations"] == 0:
                        item["observations"] = 1
                    item["last_seen"] = now
                    seen[key] = item
                result = parse_pool(pool, network, now)
                if not result:
                    continue
                existing = seen.get(key, {}) if isinstance(key, str) else {}
                result["observation_count"] = existing.get("observations", 1)
                result["repeat_observed"] = result["observation_count"] >= 2
                # Do not merge pools using ticker; same names can be impersonations.
                records[result["pool_key"]] = result

    if successful_pages == 0:
        raise RuntimeError("New-launch feeds unavailable; keeping prior radar file")

    top = sorted(records.values(), key=lambda x: (
        -x["research_priority_score"],
        -int(x["repeat_observed"]),
        -x["liquidity_usd"],
        x["pool_key"],
    ))[:MAX_CANDIDATES]

    # Keep recent pool IDs only; do not grow Git history without bounds.
    recent = sorted(seen.items(), key=lambda x: x[1]["last_seen"], reverse=True)
    seen = dict(recent[:MAX_SEEN])
    return {
        "version": 1,
        "updated_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "source": "GeckoTerminal new_pools public API (Solana and Base)",
        "coverage": "Recent paginated pools only; not comprehensive; newly created pools are not necessarily new tokens",
        "scanned_pool_rows": inspected,
        "successful_pages": successful_pages,
        "errors": errors,
        "candidates": top,
        "seen": seen,
        "disclaimer": ("Unverified research leads; no contract, holder, mint, freeze, "
                       "liquidity-lock, wash-trading or honeypot checks. NOT BUY SIGNALS."),
    }


def run():
    try:
        prior = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        LOG.warning("Radar state unreadable; not reusing prior observation history")
        prior = {}
    try:
        result = collect(prior=prior)
    except RuntimeError as exc:
        LOG.warning("%s", exc)
        return None

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    tmp.replace(STATE_PATH)

    LOG.info("NEW LAUNCH RESEARCH: scanned %d pool rows; %d candidates, %d page errors. "
             "No Telegram notifications or trade orders.",
             result["scanned_pool_rows"], len(result["candidates"]), len(result["errors"]))
    for item in result["candidates"][:8]:
        LOG.info("RESEARCH ONLY %s / %s: priority %d/100, age %.2fh, liquidity $%d, "
                 "24h volume $%d, %d buys/%d sells, repeat=%s. "
                 "UNVERIFIED, NOT A BUY SIGNAL. %s",
                 item["pool_name"], item["network"],
                 item["research_priority_score"], item["age_hours"],
                 item["liquidity_usd"], item["volume_24h_usd"],
                 item["buys_24h"], item["sells_24h"],
                 item["repeat_observed"], item["url"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
