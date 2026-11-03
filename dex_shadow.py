"""Separate DEX shadow simulator using TWO-WAY ROUTED INDICATIVE swap quotes.

This is NOT a real exchange order. A Jupiter/0x indicative quote is not
guaranteed to settle: price changes, native gas, MEV, taxes, account setup,
slippage, transfer restrictions and transaction failures remain unverified.

Existing Coinbase paper positions, account and Telegram remain unchanged.
"""
import json
import logging
import math
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import requests

from dex_security import review
from dex_quotes import buy_sell_preview, indicative_sale

LOG = logging.getLogger("sentinel.dex_shadow")
RADAR = Path("data/new_launch_radar.json")
STATE = Path("data/dex_shadow_state.json")
AUDIT = Path("data/dex_security_reviews.json")
CAPITAL = 150.0
BET = 50.0
MAX_POSITIONS = 3
MAX_CUMULATIVE_LOSS_USDC = 15.0
MIN_SCORE = 70
MAX_TRADE_AGE_H = 24
MAX_HOLD_H = 48
COOLDOWN_SECONDS = 6 * 3600
MAX_COMPLETED_TRADES = 100


def _number(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def initial_state():
    return {
        "version": 2, "strategy": "DEX routed-quote SHADOW, separate comparative $150 scenario",
        "starting_usdc": CAPITAL, "cash_usdc": CAPITAL,
        "positions": {}, "trades": [], "realized_pnl_usdc": 0.0, "updated_utc": "",
        "warnings": [
            "NOT the Coinbase paper balance; do not add two scenarios together.",
            "Two-way indicative quotes are not executable trades or proof of future liquidity.",
            "Native gas budgets are estimates; actual fills, slippage, taxes and failed exits can be worse.",
        ],
    }


def migrate(state):
    """Upgrade previous mark-price ledger without erasing positions or history."""
    if not isinstance(state, dict):
        raise ValueError("Corrupt DEX shadow state")
    if state.get("version") == 1:
        state = deepcopy(state)
        state["version"] = 2
        state["strategy"] = "DEX routed-quote SHADOW, legacy mark positions retained"
        for pos in state.get("positions", {}).values():
            pos["pricing_warning"] = ("Legacy pool-mark position lacks atomic token units. "
                                      "NO fabricated routed sale; manual reconciliation required.")
            pos["execution_model"] = "legacy_pool_mark_unverified"
        state.setdefault("warnings", []).append(
            "Legacy mark-price positions cannot be sold with new route model without atomic units.")
    return validate(state)


def validate(state):
    if not isinstance(state, dict) or state.get("version") != 2:
        raise ValueError("Invalid DEX shadow version")
    if state.get("starting_usdc") != CAPITAL or not isinstance(state.get("positions"), dict):
        raise ValueError("Invalid shadow capital/positions")
    if len(state["positions"]) > MAX_POSITIONS:
        raise ValueError("Too many positions")
    for field in ("cash_usdc", "realized_pnl_usdc"):
        value = state.get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid numeric shadow state")
    if state["cash_usdc"] < 0 or not isinstance(state.get("trades"), list):
        raise ValueError("Invalid DEX shadow cash or history")
    for key, pos in state["positions"].items():
        if not isinstance(pos, dict) or pos.get("pool_key") != key:
            raise ValueError("Invalid position key")
        if _number(pos.get("entry_usdc")) is None or pos["entry_usdc"] > BET:
            raise ValueError("Invalid paper entry cost")
        if _number(pos.get("entry_time")) is None:
            raise ValueError("Invalid paper entry time")
        if pos.get("execution_model") == "routed_indicative_v2":
            raw = pos.get("raw_token_amount")
            if not isinstance(raw, str) or not raw.isdecimal() or int(raw) < 1:
                raise ValueError("Invalid raw token inventory")
        elif pos.get("execution_model") != "legacy_pool_mark_unverified":
            raise ValueError("Position with unknown execution basis")
    return state


def read_state():
    if not STATE.exists():
        return initial_state()
    return migrate(json.loads(STATE.read_text()))


def eligible(candidate):
    """Read-only research heuristic, separate from contract safety check."""
    if not isinstance(candidate, dict):
        return False
    network = candidate.get("network")
    return (
        network in ("solana", "base")
        and candidate.get("pool_key") ==
            f"{network}:{candidate.get('pool_address')}"
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


def run_once(now=None, risk_fn=None, quote_fn=None, sale_fn=None,
             radar_path=None, state_path=None, audit_path=None):
    """Paper bookkeeping; no transaction-building, signing, API orders or Telegram."""
    now = time.time() if now is None else now
    risk_fn = risk_fn or review
    quote_fn = quote_fn or buy_sell_preview
    sale_fn = sale_fn or indicative_sale
    radar_path = radar_path or RADAR
    state_path = state_path or STATE
    audit_path = audit_path or AUDIT
    if not radar_path.exists():
        LOG.warning("Launch radar file absent; no new shadow entries")
        return None
    source = json.loads(radar_path.read_text())
    if source.get("version") != 1 or not isinstance(source.get("candidates"), list):
        raise ValueError("Malformed launch radar file")
    try:
        source_time = datetime.fromisoformat(source["updated_utc"].replace("Z", "+00:00")).timestamp()
        radar_fresh = -120 <= now - source_time <= 7200
    except (KeyError, ValueError, TypeError, OverflowError):
        radar_fresh = False

    state = migrate(json.loads(state_path.read_text())) if state_path.exists() else initial_state()
    events = []
    reviews = []
    exited = set()

    # Existing positions are checked regardless of whether they remain on radar.
    # A missing sell route means NO modeled sell, NOT a fake successful exit.
    for key, pos in list(state["positions"].items()):
        if pos.get("execution_model") != "routed_indicative_v2":
            pos["pricing_warning"] = "Legacy pool-mark position: no atomic token units, no modeled exit"
            continue
        try:
            quote = sale_fn(pos["network"], pos["token_address"], int(pos["raw_token_amount"]))
            if quote.get("verified") != "INDICATIVE_SELL_ROUTE_ONLY":
                raise ValueError("Sell quote not verified as indicative route")
            if not isinstance(quote.get("execution_guaranteed"), bool) or quote["execution_guaranteed"]:
                raise ValueError("Unexpected execution status")
            proceeds = _number(quote.get("quoted_net_usdc"))
            if proceeds is None:
                raise ValueError("Unusable net USDC")
            net_pct = (proceeds / pos["entry_usdc"] - 1) * 100
            pos["peak_net_pct"] = max(float(pos.get("peak_net_pct", -100)), net_pct)
            pos["last_quote_net_usdc"] = proceeds
            pos["last_quote_utc"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
            pos["last_quote_net_pct"] = round(net_pct, 2)
            pos.pop("pricing_warning", None)
            reason = None
            if net_pct <= -12:
                reason = "indicative -12% exit"
            elif net_pct >= 25:
                reason = "indicative +25% exit"
            elif pos["peak_net_pct"] >= 15 and net_pct <= pos["peak_net_pct"] - 10:
                reason = "indicative trailing exit"
            elif now - pos["entry_time"] >= MAX_HOLD_H * 3600:
                reason = "48-hour research holding limit"
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
                    "execution": "READ-ONLY indicative route; NOT an executable sale",
                })
                state["trades"] = state["trades"][-MAX_COMPLETED_TRADES:]
                del state["positions"][key]
                exited.add(key)
                events.append(f"INDICATIVE SHADOW EXIT {key}, net {net_pct:+.2f}% (NOT real sale)")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            pos["pricing_warning"] = ("No verified sell route or incomplete quote; "
                                      "no modeled exit recorded")
            LOG.warning("DEX shadow sale quote failed for %s: %s", key, type(exc).__name__)

    occupied_tokens = {(p["network"], p["token_address"].lower())
                       for p in state["positions"].values()}
    if not radar_fresh:
        LOG.warning("New-launch radar stale/undated. No new DEX shadow positions.")
    candidates = sorted(
        (x for x in source["candidates"] if isinstance(x, dict)) if radar_fresh else [],
        key=lambda x: (-(_number(x.get("research_priority_score")) or 0),
                       x.get("network") != "solana"))[:12]

    for candidate in candidates:
        network = candidate.get("network")
        address = candidate.get("token_address")
        if network not in ("solana", "base") or not isinstance(address, str):
            continue
        evaluated = risk_fn(network, address)
        if not isinstance(evaluated, dict):
            evaluated = {"status": "unknown", "unknown": ["Invalid security report"]}
        review_item = {
            "pool_key": candidate.get("pool_key"), "network": network,
            "token_address": address, "security": evaluated,
            "shadow_entry_eligible": False, "swap_quote": "not requested",
        }
        reviews.append(review_item)
        if evaluated.get("status") != "observed_pass" or not eligible(candidate):
            continue
        key = candidate["pool_key"]
        if (len(state["positions"]) >= MAX_POSITIONS or key in state["positions"]
                or key in exited or (network, address.lower()) in occupied_tokens
                or state["cash_usdc"] < BET
                or state["realized_pnl_usdc"] <= -MAX_CUMULATIVE_LOSS_USDC):
            continue
        if any(t.get("network") == network
               and t.get("token_address", "").lower() == address.lower()
               and 0 <= now - t.get("exit_time", 0) < COOLDOWN_SECONDS for t in state["trades"]):
            continue
        try:
            preview = quote_fn(network, address, BET)
            if (not isinstance(preview, dict) or
                    preview.get("verified") != "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT" or
                    preview.get("execution_guaranteed") is not False or
                    preview.get("token_address") != address or preview.get("network") != network):
                raise ValueError("Two-way read-only quote not confirmed")
            raw_token = preview.get("raw_token_amount")
            if type(raw_token) is not int or raw_token <= 0:
                raise ValueError("Invalid quoted raw amount")
            est = _number(preview.get("quoted_roundtrip_after_gas_buffer_usdc"))
            if est is None or est < 40:
                raise ValueError("Net roundtrip estimation too costly")
            state["positions"][key] = {
                "pool_key": key, "network": network, "pool_address": candidate["pool_address"],
                "token_address": address, "entry_time": now, "entry_usdc": BET,
                "raw_token_amount": str(raw_token),
                "entry_quote_roundtrip_usdc": preview["quoted_roundtrip_usdc"],
                "assumed_gas_buffer_usdc": preview["gas_buffer_usdc"],
                "peak_net_pct": -100, "execution_model": "routed_indicative_v2",
                "execution": "TWO-WAY READ-ONLY INDICATIVE; NO TRANSACTION SUBMITTED",
            }
            state["cash_usdc"] = round(state["cash_usdc"] - BET, 8)
            occupied_tokens.add((network, address.lower()))
            review_item["shadow_entry_eligible"] = True
            review_item["swap_quote"] = {
                "provider_buy": preview["buy_provider"], "provider_sell": preview["sell_provider"],
                "quoted_roundtrip_loss_pct": preview["quoted_roundtrip_loss_pct"],
                "gas_buffer_usdc": preview["gas_buffer_usdc"],
                "execution_guaranteed": False,
            }
            events.append(f"INDICATIVE SHADOW ENTRY {key}: $50 USDC (NOT real buy)")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            review_item["swap_quote"] = "unavailable_or_rejected"
            review_item["quote_error_type"] = type(exc).__name__
            LOG.info("No acceptable two-way route for %s: %s", key, type(exc).__name__)

    state["updated_utc"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    validate(state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(state_path)
    audit_path.write_text(json.dumps({
        "updated_utc": state["updated_utc"], "provider": "GoPlus + Jupiter V2 / 0x read-only",
        "mode": "INDICATIVE QUOTES ONLY", "reviewed": reviews,
        "disclaimer": ("No wallet, signing, actual gas, tax simulation, on-chain confirmation "
                       "or guaranteed buy/sell liquidity. No real orders or Telegram."),
    }, indent=2, sort_keys=True) + "\n")
    for event in events:
        LOG.info("%s", event)
    LOG.info("DEX INDICATIVE SHADOW: %d screened, %d/%d open, $%.2f cash, "
             "%d completed models; no actual orders or Telegram.",
             len(reviews), len(state["positions"]), MAX_POSITIONS,
             state["cash_usdc"], len(state["trades"]))
    return state, reviews, events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_once()
