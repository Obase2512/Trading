"""Fail-closed preliminary DEX token checks via read-only GoPlus endpoints.

An "observed_pass" means *only* the limited fields we checked did not reveal
listed hazards. It is NOT a finding of safety, sellability, authentic liquidity,
or future profit. No keys, transaction signing or trades are used here.
"""
import logging
import math
import os
import re

import requests

LOG = logging.getLogger("sentinel.dex_security")
API = "https://api.gopluslabs.io/api/v1"
NETWORKS = {"solana", "base"}
MAX_HOLDER_SHARE = 0.20
MAX_TOP10_SHARE = 0.50


def _flag(value):
    """Return bool or None for unknown; never treat missing as safe."""
    if isinstance(value, dict):
        value = value.get("status")
    if value in ("1", 1, True):
        return True
    if value in ("0", 0, False):
        return False
    return None


def _fraction(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and 0 <= out <= 1 else None


def _valid_token(network, address):
    if network == "base":
        return isinstance(address, str) and bool(re.fullmatch(r"0[xX][0-9a-fA-F]{40}", address))
    if network == "solana":
        return isinstance(address, str) and bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address))
    return False


def fetch_goplus(network, address, requester=None):
    """Get one token security report. Optional provider key is never logged."""
    if not _valid_token(network, address):
        raise ValueError("Invalid token address/network")
    url = (f"{API}/solana/token_security" if network == "solana"
           else f"{API}/token_security/8453")
    headers = {"Accept": "application/json"}
    key = os.getenv("GOPLUS_ACCESS_TOKEN", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    requester = requester or requests.get
    response = requester(url, params={"contract_addresses": address.lower() if network == "base" else address},
                         headers=headers, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("code")) != "1":
        raise ValueError("Security provider response not successful")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Security provider result missing")
    info = result.get(address)
    if not isinstance(info, dict):
        info = result.get(address.lower())
    if not isinstance(info, dict):
        # Do not accept an unrelated token report just because it has data.
        raise ValueError("Provider did not return exact token address")
    return info


def evaluate(network, address, data):
    """Assess only explicitly available risk indicators; unknown => no paper buy."""
    if not _valid_token(network, address):
        raise ValueError("Invalid token address/network")
    flagged = []
    unknown = []
    if not isinstance(data, dict):
        return {"status": "unknown", "flagged": [], "unknown": ["provider data missing"],
                "source": "GoPlus read-only"}
    if network == "base":
        for field in ("is_honeypot", "cannot_sell_all", "cannot_buy", "is_mintable",
                      "is_proxy", "is_blacklisted", "hidden_owner",
                      "owner_change_balance", "transfer_pausable", "can_take_back_ownership"):
            v = _flag(data.get(field))
            if v is True:
                flagged.append(field)
            elif v is None:
                unknown.append(field)
        for field in ("is_open_source", "is_in_dex"):
            v = _flag(data.get(field))
            if v is False:
                flagged.append(field + " false")
            elif v is None:
                unknown.append(field)
        for field in ("buy_tax", "sell_tax"):
            val = _fraction(data.get(field))
            if val is None:
                unknown.append(field)
            elif val > 0.03:
                flagged.append(field + " >3%")
    else:
        for field in ("mintable", "freezable", "non_transferable", "closable",
                      "balance_mutable_authority"):
            v = _flag(data.get(field))
            if v is True:
                flagged.append(field)
            elif v is None:
                unknown.append(field)
        # Additional risks flagged whenever reported; unknown is not clearance.
        for field in ("transfer_fee_upgradable", "transfer_hook_upgradable"):
            v = _flag(data.get(field))
            if v is True:
                flagged.append(field)
            elif v is None:
                unknown.append(field)
        default = str(data.get("default_account_state", ""))
        if default in ("2", "0"):
            flagged.append("default_account_state uninitialized/frozen")
        elif default != "1":
            unknown.append("default_account_state")
        for field in ("transfer_hook",):
            obj = data.get(field)
            if isinstance(obj, dict) and obj.get("address"):
                flagged.append("transfer_hook present")
            elif obj not in (None, {}, ""):
                unknown.append(field)
        transfer_fee = data.get("transfer_fee")
        if isinstance(transfer_fee, dict):
            current = transfer_fee.get("current_fee_rate") or {}
            rate = _fraction(
                float(current.get("fee_rate")) / 10000
                if isinstance(current, dict) and current.get("fee_rate") is not None
                else None)
            if rate is None:
                unknown.append("transfer_fee")
            elif rate > 0.03:
                flagged.append("transfer_fee >3%")

    holders = data.get("holders")
    shares = []
    if not isinstance(holders, list) or not holders:
        unknown.append("holder concentration")
    else:
        for holder in holders[:10]:
            if not isinstance(holder, dict):
                unknown.append("holder concentration")
                break
            share = _fraction(holder.get("percent"))
            if share is None:
                unknown.append("holder concentration")
                break
            shares.append(share)
        if shares:
            if max(shares) > MAX_HOLDER_SHARE:
                flagged.append("single holder >20%")
            if sum(shares) > MAX_TOP10_SHARE:
                flagged.append("top holders >50%")

    status = "blocked" if flagged else "unknown" if unknown else "observed_pass"
    return {
        "status": status,
        "flagged": sorted(set(flagged)),
        "unknown": sorted(set(unknown)),
        "source": "GoPlus read-only",
        "disclaimer": ("Preliminary signals only; liquidity locks, fake-volume, "
                       "owner linkage and executable two-way swap quotes NOT verified."),
    }


def review(network, address, requester=None):
    """Network/provider errors do not become 'approved' tokens."""
    try:
        report = fetch_goplus(network, address, requester=requester)
        return evaluate(network, address, report)
    except (requests.RequestException, ValueError, TypeError, OverflowError) as exc:
        LOG.warning("Security check unavailable for %s token (no clearance): %s", network, type(exc).__name__)
        return {"status": "unknown", "flagged": [], "unknown": ["security API unavailable"],
                "source": "GoPlus read-only", "disclaimer": "NOT cleared; no real or paper buy"}
