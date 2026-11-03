"""Two-way indicative DEX route checks; read-only, NO transaction execution.

Solana: Jupiter Swap V2 GET /order WITHOUT taker (quote only).
Base: 0x Swap V2 AllowanceHolder GET /price (read-only; API key required).

A two-way quote is NOT proof that an actual transaction would settle.
Network fees, account creation, MEV, slippage, and token transfer restrictions
can make realized proceeds much worse. Never signs or submits transactions.
"""
import logging
import math
import os
import re
import time

import requests

LOG = logging.getLogger("sentinel.dex_quotes")
USDC_RAW = 1_000_000  # Solana USDC and Base native USDC: six decimals.
SOL_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
JUPITER = "https://api.jup.ag/swap/v2/order"
ZERO_EX = "https://api.0x.org/swap/allowance-holder/price"
SLIPPAGE_BPS = 100
MAX_ROUND_TRIP_LOSS = 0.15
# Conservative *assumptions*, NOT actual gas estimates; neither source here
# proves token account creation cost, priority fees, RPC landing, or gas USD.
GAS_BUFFER_USDC = {"solana": 0.40, "base": 1.00}


def _atomic(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Invalid raw token amount")
    s = str(value)
    if not re.fullmatch(r"[0-9]{1,80}", s):
        raise ValueError("Invalid raw amount format")
    raw = int(s)
    if raw < 1:
        raise ValueError("Zero amount")
    return raw


def _validate(network, token):
    if network == "solana":
        if not isinstance(token, str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", token):
            raise ValueError("Bad Solana mint")
        if token == SOL_USDC:
            raise ValueError("Cannot swap USDC for itself")
    elif network == "base":
        if not isinstance(token, str) or not re.fullmatch(r"0[xX][0-9a-fA-F]{40}", token):
            raise ValueError("Bad Base token address")
        if token.lower() == BASE_USDC.lower():
            raise ValueError("Cannot swap USDC for itself")
    else:
        raise ValueError("Unsupported chain")


def _http_get(url, params, headers, requester=None):
    requester = requester or requests.get
    response = requester(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected routing API payload")
    return data


def _solana_quote(input_mint, output_mint, amount, requester=None):
    headers = {"Accept": "application/json"}
    api_key = os.getenv("JUPITER_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    data = _http_get(JUPITER, {
        "inputMint": input_mint, "outputMint": output_mint,
        "amount": str(amount),
    }, headers, requester)
    if data.get("errorCode") or data.get("error"):
        raise ValueError("Jupiter route unavailable")
    if data.get("transaction") not in (None, ""):
        raise ValueError("Jupiter unexpectedly returned transaction; quote-only required")
    if data.get("inputMint", input_mint) != input_mint or data.get("outputMint", output_mint) != output_mint:
        raise ValueError("Jupiter response mint mismatch")
    if _atomic(data.get("inAmount")) != amount:
        raise ValueError("Jupiter input mismatch")
    if not isinstance(data.get("router"), str) or not data["router"].strip():
        raise ValueError("Missing Jupiter router")
    out = _atomic(data.get("outAmount"))
    fee_bps = data.get("feeBps")
    if fee_bps is not None:
        try:
            fee_bps = float(fee_bps)
        except (ValueError, TypeError):
            raise ValueError("Bad Jupiter fee")
        if not math.isfinite(fee_bps) or fee_bps < 0 or fee_bps > 500:
            raise ValueError("Excessive Jupiter fee")
    return {"raw_out": out, "provider": "Jupiter Swap V2 indicative", "router": data["router"],
            "provider_fee_bps": fee_bps}


def _base_quote(input_token, output_token, amount, requester=None):
    key = os.getenv("ZEROX_API_KEY", "").strip()
    if not key:
        raise ValueError("ZEROX_API_KEY missing; Base read-only route unavailable")
    data = _http_get(ZERO_EX, {
        "chainId": "8453", "sellToken": input_token, "buyToken": output_token,
        "sellAmount": str(amount), "slippageBps": str(SLIPPAGE_BPS),
    }, {"0x-api-key": key, "0x-version": "v2", "Accept": "application/json"}, requester)
    if data.get("liquidityAvailable") is not True:
        raise ValueError("0x no liquidity")
    if data.get("sellToken", input_token).lower() != input_token.lower():
        raise ValueError("0x sell token mismatch")
    if data.get("buyToken", output_token).lower() != output_token.lower():
        raise ValueError("0x buy token mismatch")
    if _atomic(data.get("sellAmount")) != amount:
        raise ValueError("0x input mismatch")
    issues = data.get("issues", {})
    if isinstance(issues, dict) and issues.get("simulationIncomplete") is True:
        raise ValueError("0x simulation incomplete")
    out = _atomic(data.get("buyAmount"))
    return {"raw_out": out, "provider": "0x Swap V2 indicative", "router": "0x"}


def indicative_swap(network, sell_token, buy_token, raw_sell_amount, requester=None):
    """Get indicative output for exact raw input; no wallet or transaction."""
    amount = _atomic(raw_sell_amount)
    if network == "solana":
        return _solana_quote(sell_token, buy_token, amount, requester=requester)
    if network == "base":
        return _base_quote(sell_token, buy_token, amount, requester=requester)
    raise ValueError("Unsupported network")


def buy_sell_preview(network, token, amount_usdc=50, requester=None, sleeper=None):
    """Quote $50 USDC->token then token->USDC immediately.

    This measures route availability and immediate round-trip friction only.
    It does NOT establish that a sale will remain possible in the future.
    """
    _validate(network, token)
    if type(amount_usdc) not in (int, float) or not math.isfinite(amount_usdc) or not (0 < amount_usdc <= 50):
        raise ValueError("Invalid simulated spend amount")
    raw_usdc = round(amount_usdc * USDC_RAW)
    usdc = SOL_USDC if network == "solana" else BASE_USDC
    first = indicative_swap(network, usdc, token, raw_usdc, requester)
    if network == "solana":
        (sleeper or time.sleep)(2.1)  # Jupiter keyless limit: 0.5 req/s.
    second = indicative_swap(network, token, usdc, first["raw_out"], requester)
    raw_back = second["raw_out"]
    roundtrip_cash = raw_back / USDC_RAW
    costs = amount_usdc - roundtrip_cash
    if (roundtrip_cash <= 0 or roundtrip_cash > amount_usdc * 1.1
            or costs / amount_usdc > MAX_ROUND_TRIP_LOSS):
        raise ValueError("Round-trip price impact too high/suspicious")
    return {
        "network": network, "token_address": token,
        "raw_buy_usdc": raw_usdc, "raw_token_amount": first["raw_out"],
        "raw_sell_usdc_preview": raw_back,
        "buy_provider": first["provider"], "sell_provider": second["provider"],
        "buy_router": first["router"], "sell_router": second["router"],
        "quoted_roundtrip_usdc": round(roundtrip_cash, 6),
        "quoted_roundtrip_loss_pct": round(100 * costs / amount_usdc, 2),
        "gas_buffer_usdc": GAS_BUFFER_USDC[network],
        "quoted_roundtrip_after_gas_buffer_usdc": round(
            max(0, roundtrip_cash - 2 * GAS_BUFFER_USDC[network]), 6),
        "verified": "READ_ONLY_TWO_WAY_INDICATIVE_AT_THIS_INSTANT",
        "execution_guaranteed": False,
        "disclaimer": ("Quote valid only at request instant. Native gas, account creation, "
                       "allowances, price movement, MEV, tax/transfer restrictions, tx "
                       "failure and future sell availability NOT verified."),
    }


def indicative_sale(network, token, raw_token_amount, requester=None):
    """Read-only current route for selling a held raw token amount back to USDC."""
    _validate(network, token)
    usdc = SOL_USDC if network == "solana" else BASE_USDC
    quote = indicative_swap(network, token, usdc, raw_token_amount, requester)
    return {
        "network": network, "token_address": token, "raw_usdc": quote["raw_out"],
        "quoted_usdc": round(quote["raw_out"] / USDC_RAW, 6),
        "gas_buffer_usdc": GAS_BUFFER_USDC[network],
        "quoted_net_usdc": round(max(0, quote["raw_out"] / USDC_RAW - GAS_BUFFER_USDC[network]), 6),
        "provider": quote["provider"], "verified": "INDICATIVE_SELL_ROUTE_ONLY",
        "execution_guaranteed": False,
    }
