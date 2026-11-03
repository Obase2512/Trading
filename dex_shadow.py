"""Isolated, NON-EXECUTABLE DEX shadow-paper simulator.

This is an independent $150 comparison scenario, NOT an extra cash deposit
and NOT part of the existing Coinbase paper portfolio. Its $50 modeled fills
use public pool mark prices and assumed 2.5% cost EACH SIDE, NOT executable
two-way quotes. No swap routing, wallet signing, Coinbase orders or Telegram.
"""
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from dex_security import review

LOG = logging.getLogger("sentinel.dex_shadow")
RADAR = Path("data/new_launch_radar.json")
STATE = Path("data/dex_shadow_state.json")
AUDIT = Path("data/dex_security_reviews.json")
POOL_URL = "https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}"
CAPITAL = 150.0
BET = 50.0
MAX_POSITIONS = 3
COST_PER_SIDE = 0.025  # Illustrative: DEX LP fees, slippage and network overhead.
MIN_RESERVE = 100_000.0
MIN_SCORE = 70
MAX_TRADE_AGE_H = 24
MAX_HOLD_H = 48
COOLDOWN_SECONDS = 6 * 3600
MAX_COMPLETED_TRADES = 100


def _number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def initial_state():
    return {"version": 1, "strategy": "DEX research SHADOW, separate comparative $150 scenario",
            "starting_usdc": CAPITAL, "cash_usdc": CAPITAL,
            "positions": {}, "trades": [], "realized_pnl_usdc": 0.0, "updated_utc": "",
            "warnings": ["NOT the Coinbase paper balance; do not sum these budgets.",
                         "Public pool marks are not executable bid/ask quotes.",
                         "Failure to sell, price impact, fake volume, and rugs may exceed modeled losses."]}


def validate(state):
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Invalid shadow ledger; manual inspection needed")
    if state.get("starting_usdc") != CAPITAL or not isinstance(state.get("positions"), dict):
        raise ValueError("Incorrect shadow capital or position structure")
    if len(state["positions"]) > MAX_POSITIONS:
        raise ValueError("Too many shadow positions")
    cash = state.get("cash_usdc")
    pnl = state.get("realized_pnl_usdc")
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in (cash, pnl)) or cash < 0:
        raise ValueError("Invalid shadow cash/P&L")
    if not isinstance(state.get("trades"), list):
        raise ValueError("Corrupt shadow history")
    for key, pos in state["positions"].items():
        if not isinstance(pos, dict) or pos.get("pool_key") != key:
            raise ValueError("Corrupt shadow position")
        for field in ("units", "entry_usdc", "entry_price_usd", "entry_time"):
            if _number(pos.get(field)) is None:
                raise ValueError("Corrupt position: " + field)
        if pos["entry_usdc"] > BET:
            raise ValueError("Oversize shadow entry")
    return state


def read_state():
    if not STATE.exists():
        return initial_state()
    return validate(json.loads(STATE.read_text()))


def public_pool(network, address, requester=None):
    if network not in ("solana", "base"):
        raise ValueError("Unknown chain")
    if not isinstance(address, str) or len(address) > 70 or "/" in address or "?" in address:
        raise ValueError("Invalid pool locator")
    requester = requester or requests.get
    response = requester(POOL_URL.format(network=network, pool=address),
                         headers={"Accept": "application/json"}, timeout=15)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ValueError("Pool response missing")
    attrs = body["data"].get("attributes")
    if not isinstance(attrs, dict) or attrs.get("address", "").lower() != address.lower():
        raise ValueError("Wrong pool returned")
    price = _number(attrs.get("base_token_price_usd"))
    liquidity = _number(attrs.get("reserve_in_usd"))
    if price is None or liquidity is None or liquidity < MIN_RESERVE:
        raise ValueError("Invalid pool price or liquidity")
    return {"price": price, "liquidity": liquidity}


def eligible(candidate):
    """Strict paper-only heuristic; provider risk screen checked separately."""
    if not isinstance(candidate, dict):
        return False
    return (
        candidate.get("network") in ("solana", "base")
        and candidate.get("pool_key") == (str(candidate.get("network")) + ":" +
                                         str(candidate.get("pool_address")))
        and candidate.get("meme_theme_hint") is True
        and candidate.get("repeat_observed") is True
        and _number(candidate.get("research_priority_score")) is not None
        and candidate["research_priority_score"] >= MIN_SCORE
        and _number(candidate.get("age_hours")) is not None
        and 0.5 <= candidate["age_hours"] <= MAX_TRADE_AGE_H
        and _number(candidate.get("liquidity_usd")) is not None
        and candidate["liquidity_usd"] >= 150_000
        and _number(candidate.get("volume_24h_usd")) is not None
        and candidate["volume_24h_usd"] >= 300_000
    )


def _model_sale(pos, price):
    return pos["units"] * price * (1 - COST_PER_SIDE)


def run_once(now=None, risk_fn=None, price_fn=None, radar_path=None,
             state_path=None, audit_path=None):
    now = time.time() if now is None else now
    risk_fn = risk_fn or review
    price_fn = price_fn or public_pool
    radar_path = radar_path or RADAR
    state_path = state_path or STATE
    audit_path = audit_path or AUDIT
    if not radar_path.exists():
        LOG.info("New-launch radar not ready; no DEX shadow trades.")
        return None
    source = json.loads(radar_path.read_text())
    if source.get("version") != 1 or not isinstance(source.get("candidates"), list):
        raise ValueError("Invalid new-launch radar input")
    try:
        source_time = datetime.fromisoformat(source["updated_utc"].replace("Z", "+00:00")).timestamp()
        radar_fresh = -120 <= now - source_time <= 7200
    except (KeyError, TypeError, ValueError, OverflowError):
        radar_fresh = False

    state = validate(json.loads(state_path.read_text())) if state_path.exists() else initial_state()
    events = []
    reviews = []
    exited = set()

    # Independent mark-to-market checks, even for pools no longer on the radar.
    for key, pos in list(state["positions"].items()):
        try:
            quote = price_fn(pos["network"], pos["pool_address"])
            proceeds = _model_sale(pos, quote["price"])
            net_pct = (proceeds / pos["entry_usdc"] - 1) * 100
            pos["peak_net_pct"] = max(float(pos.get("peak_net_pct", -100)), net_pct)
            pos["last_mark_usd"] = quote["price"]
            pos["last_mark_time"] = now
            pos["last_modeled_net_pct"] = round(net_pct, 2)
            peak = pos["peak_net_pct"]
            reason = None
            if net_pct <= -12:
                reason = "modeled -12% exit"
            elif net_pct >= 25:
                reason = "modeled +25% exit"
            elif peak >= 15 and net_pct <= peak - 10:
                reason = "modeled 10 point pullback after 15% peak"
            elif now - pos["entry_time"] >= MAX_HOLD_H * 3600:
                reason = "48-hour shadow holding limit"
            if reason:
                pnl = proceeds - pos["entry_usdc"]
                state["cash_usdc"] = round(state["cash_usdc"] + proceeds, 8)
                state["realized_pnl_usdc"] = round(state["realized_pnl_usdc"] + pnl, 8)
                state["trades"].append({
                    "pool_key": key, "token_address": pos["token_address"],
                    "network": pos["network"], "entry_time": pos["entry_time"],
                    "exit_time": now, "entry_usdc": pos["entry_usdc"],
                    "exit_usdc": round(proceeds, 6), "pnl_usdc": round(pnl, 6),
                    "pnl_pct": round(net_pct, 2), "reason": reason,
                    "execution": "UNVERIFIED modeled pool mark, not tradable fill",
                })
                state["trades"] = state["trades"][-MAX_COMPLETED_TRADES:]
                del state["positions"][key]
                exited.add(key)
                events.append(f"SHADOW EXIT {key}, modeled {net_pct:+.2f}% (not a real sell)")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            pos["pricing_warning"] = "Pool quote/liquidity missing; cannot claim a sale"
            LOG.warning("DEX shadow cannot mark %s: %s", key, type(exc).__name__)

    # Separate account used to test DEX heuristics vs existing Coinbase system.
    occupied_tokens = {(p["network"], p["token_address"].lower())
                       for p in state["positions"].values()}
    if not radar_fresh:
        LOG.warning("Radar is stale or undated. No NEW shadow entry; continuing open-position marks.")
    candidates = sorted((x for x in source["candidates"] if isinstance(x, dict))
                        if radar_fresh else [],
                        key=lambda x: (x.get("network") != "solana",
                                       -_number(x.get("research_priority_score"))
                                       if _number(x.get("research_priority_score")) else 0))

    for candidate in candidates[:12]:
        network = candidate.get("network")
        address = candidate.get("token_address")
        if not isinstance(network, str) or not isinstance(address, str):
            continue
        evaluation = risk_fn(network, address)
        if not isinstance(evaluation, dict):
            evaluation = {"status": "unknown", "unknown": ["invalid risk response"]}
        review_item = {
            "pool_key": candidate.get("pool_key"), "network": network,
            "token_address": address, "priority": candidate.get("research_priority_score"),
            "security": evaluation, "shadow_entry_eligible": False,
        }
        reviews.append(review_item)
        if evaluation.get("status") != "observed_pass" or not eligible(candidate):
            continue
        key = candidate["pool_key"]
        if (len(state["positions"]) >= MAX_POSITIONS
                or key in state["positions"] or key in exited
                or (network, address.lower()) in occupied_tokens
                or state["cash_usdc"] < BET):
            continue
        if state["realized_pnl_usdc"] <= -15:
            continue
        if any(t.get("network") == network and
               t.get("token_address", "").lower() == address.lower() and
               0 <= now - t.get("exit_time", 0) < COOLDOWN_SECONDS for t in state["trades"]):
            continue
        try:
            quote = price_fn(network, candidate["pool_address"])
            if quote["liquidity"] < 150_000:
                continue
            cost = BET
            units = (cost * (1 - COST_PER_SIDE)) / quote["price"]
            state["positions"][key] = {
                "pool_key": key, "network": network, "pool_address": candidate["pool_address"],
                "token_address": address, "entry_time": now, "entry_usdc": cost,
                "entry_price_usd": quote["price"], "units": units,
                "peak_net_pct": -100, "assumed_cost_each_side_pct": 2.5,
                "execution": "NOT executable quote; public pool mark model only",
            }
            state["cash_usdc"] = round(state["cash_usdc"] - cost, 8)
            occupied_tokens.add((network, address.lower()))
            review_item["shadow_entry_eligible"] = True
            events.append(f"SHADOW ENTRY {key}: modeled $50 (not a real buy)")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            review_item["pricing_error"] = type(exc).__name__
            LOG.warning("Skipped DEX shadow price for %s: %s", key, type(exc).__name__)

    state["updated_utc"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    validate(state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    audit_path.write_text(json.dumps({
        "updated_utc": state["updated_utc"],
        "provider": "GoPlus read-only", "mode": "PRELIMINARY ONLY",
        "reviewed": reviews,
        "disclaimer": ("Observed_pass is NOT proof of token safety or sellability. "
                       "Shadow results use public marks, NOT real swap quotes. "
                       "NEVER place actual trades on this evidence alone."),
    }, indent=2, sort_keys=True) + "\n")
    for event in events:
        LOG.info("%s", event)
    LOG.info("DEX SHADOW ONLY: %d screened leads, %d open / %d max, %.2f paper cash, "
             "%d simulated exits; NO Telegram, NO real orders.",
             len(reviews), len(state["positions"]), MAX_POSITIONS,
             state["cash_usdc"], len(state["trades"]))
    return state, reviews, events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_once()
