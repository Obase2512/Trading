"""Conservative paper-only trading rules. Never makes Coinbase orders.

Scoring is heuristic, not a predicted win probability or token safety rating.
Prices, modeled fees, and slippage are not live executable quotes.
"""
import math
from copy import deepcopy
from datetime import datetime, timezone

PAPER_VERSION = 2
STARTING_USDC = 150.0
LEGACY_STARTING_USDC = 50.0
CAPITAL_INCREASE_USDC = 100.0
POSITION_USDC = 50.0
MAX_POSITIONS = 3
MAX_REALIZED_LOSS = 15.0  # Stops NEW paper buys after this cumulative realized loss.
TAKER_FEE = 0.009  # Assumption; do not infer current live trading fee.
SIM_SLIPPAGE = 0.003  # Assumption per side; not a guaranteed execution cost.
COOLDOWN_SECONDS = 6 * 3600
CANDLE_SECONDS = 3600


def fresh_candles(raw, now):
    """Get 24 continuous recently closed 1-hour candles; reject stale data."""
    if not isinstance(raw, dict) or not isinstance(raw.get("candles"), list):
        return []
    candles = []
    for item in raw["candles"]:
        try:
            start = int(item["start"])
            close, volume = float(item["close"]), float(item["volume"])
            if start + CANDLE_SECONDS > now - 60:
                continue
            if not all(map(math.isfinite, (close, volume))) or close <= 0 or volume < 0:
                continue
            candles.append({"start": start, "close": close, "volume": volume})
        except (TypeError, ValueError, KeyError):
            continue
    ordered = [value for _, value in sorted({c["start"]: c for c in candles}.items())]
    window = ordered[-24:]
    if len(window) != 24:
        return []
    if now - (window[-1]["start"] + CANDLE_SECONDS) > 7200:
        return []
    if any(b["start"] - a["start"] != CANDLE_SECONDS for a, b in zip(window, window[1:])):
        return []
    return window


def assess_market(product, candles, bid, ask):
    """Evaluate trend, momentum, volume, and spread. Not a safety certification."""
    try:
        bid, ask = float(bid), float(ask)
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask)):
            return None
        if ask < bid or len(candles) < 24:
            return None
        prices = [float(c["close"]) for c in candles[-24:]]
        if not all(math.isfinite(price) and price > 0 for price in prices):
            return None
        turnover24_usd = sum(float(c["close"]) * float(c["volume"])
                             for c in candles[-24:])
        if not math.isfinite(turnover24_usd):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    spread_pct = (ask - bid) / ask * 100
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    change6h_pct = (prices[-1] / prices[-7] - 1) * 100
    change1h_pct = (prices[-1] / prices[-2] - 1) * 100
    checks = {
        "trend": sma5 >= sma20 * 1.005,
        "momentum_6h": 1 <= change6h_pct <= 15,
        "last_hour_positive": 0 < change1h_pct <= 6,
        "turnover_24h": turnover24_usd >= 100_000,
        "spread": spread_pct <= 0.8,
    }
    return {
        "product": product, "bid": bid, "ask": ask,
        "spread_pct": round(spread_pct, 3),
        "momentum_6h_pct": round(change6h_pct, 2),
        "momentum_1h_pct": round(change1h_pct, 2),
        "turnover_24h_usd": round(turnover24_usd),
        "checks": checks,
        "score": sum(checks.values()) * 20,
        "entry_watch": all(checks.values()),
    }


def initial_state():
    """Version-2 paper portfolio; completely disconnected from the actual account."""
    return {
        "version": PAPER_VERSION,
        "starting_usdc": STARTING_USDC,
        "cash_usdc": STARTING_USDC,
        "positions": {},
        "realized_pnl_usdc": 0.0,
        "trades": [],
        "capital_additions": [],
        "updated_utc": "",
    }


def _valid_number(value, lower=None):
    if type(value) not in (float, int) or not math.isfinite(value):
        return False
    return lower is None or value >= lower


def validate_state(state):
    """Fail closed on corrupted paper state instead of resetting financial history."""
    if not isinstance(state, dict) or state.get("version") != PAPER_VERSION:
        raise ValueError("Unsupported paper state version")
    if abs(float(state.get("starting_usdc", -1)) - STARTING_USDC) > 0.00001:
        raise ValueError("Unexpected paper starting balance")
    if not _valid_number(state.get("cash_usdc"), 0):
        raise ValueError("Invalid paper cash")
    if not _valid_number(state.get("realized_pnl_usdc")):
        raise ValueError("Invalid paper realized profit/loss")
    positions = state.get("positions")
    if not isinstance(positions, dict) or len(positions) > MAX_POSITIONS:
        raise ValueError("Invalid number of open paper positions")
    for product, pos in positions.items():
        if not isinstance(pos, dict) or pos.get("product") != product:
            raise ValueError("Invalid paper position identifier")
        for key in ("units", "entry_cost_usdc", "entry_execution_price", "entry_time"):
            if not _valid_number(pos.get(key), 0):
                raise ValueError("Invalid paper position metric: " + key)
        if pos["units"] == 0 or pos["entry_cost_usdc"] <= 0 or pos["entry_execution_price"] <= 0:
            raise ValueError("Paper position must have positive size")
        if pos["entry_cost_usdc"] > POSITION_USDC + 1e-7:
            raise ValueError("Paper position exceeds per-coin budget")
    if not isinstance(state.get("trades"), list) or not isinstance(state.get("capital_additions"), list):
        raise ValueError("Invalid paper history")
    return state


def migrate_state(state):
    """One-time upgrade from $50/v1 to $150/v2, preserving positions & trades.

    Capital is credited only when version == 1. Reading version 2 cannot add
    a second $100 credit. Existing $10 DOGE trade remains at its original size.
    """
    if state.get("version") == PAPER_VERSION:
        return validate_state(state)
    if state.get("version") != 1:
        raise ValueError("Unknown paper state version; manual review required")
    if abs(float(state.get("starting_usdc", -1)) - LEGACY_STARTING_USDC) > 1e-7:
        raise ValueError("Legacy paper balance is unexpected; refusing automatic migration")
    old_cash = state.get("cash_usdc")
    if not _valid_number(old_cash, 0) or not _valid_number(state.get("realized_pnl_usdc")):
        raise ValueError("Invalid legacy balances")
    old_trades = state.get("trades")
    if not isinstance(old_trades, list):
        raise ValueError("Invalid legacy trade history")
    legacy_position = state.get("position")
    if legacy_position is not None and (
        not isinstance(legacy_position, dict) or not legacy_position.get("product")
    ):
        raise ValueError("Invalid legacy position")
    upgraded = {
        "version": PAPER_VERSION,
        "starting_usdc": STARTING_USDC,
        "cash_usdc": round(old_cash + CAPITAL_INCREASE_USDC, 8),
        "positions": ({legacy_position["product"]: deepcopy(legacy_position)}
                      if legacy_position else {}),
        "realized_pnl_usdc": state["realized_pnl_usdc"],
        "trades": deepcopy(old_trades),
        "capital_additions": [{
            "amount_usdc": CAPITAL_INCREASE_USDC,
            "reason": "One-time paper-only budget increase (50 to 150 USDC)",
        }],
        "updated_utc": state.get("updated_utc", ""),
    }
    return validate_state(upgraded)


def net_exit_value(position, bid):
    execution_price = bid * (1 - SIM_SLIPPAGE)
    return position["units"] * execution_price * (1 - TAKER_FEE)


def entry(state, market, now):
    """Simulate exactly one $50 buy, inclusive of expected taker fees."""
    validate_state(state)
    product = market["product"]
    if (not market["entry_watch"] or product in state["positions"]
            or len(state["positions"]) >= MAX_POSITIONS
            or state["cash_usdc"] + 1e-8 < POSITION_USDC
            or state["realized_pnl_usdc"] <= -MAX_REALIZED_LOSS):
        return None
    for trade in state["trades"]:
        if trade.get("product") == product and now - float(trade.get("exit_time", 0)) < COOLDOWN_SECONDS:
            return None
    ask = float(market["ask"]) * (1 + SIM_SLIPPAGE)
    if not math.isfinite(ask) or ask <= 0:
        return None
    buy_notional = POSITION_USDC / (1 + TAKER_FEE)
    units = buy_notional / ask
    pos = {
        "product": product,
        "units": units,
        "entry_execution_price": ask,
        "entry_bid": market["bid"],
        "entry_cost_usdc": POSITION_USDC,
        "entry_time": now,
        "peak_net_pct": -100.0,
        "entry_fee_usdc": POSITION_USDC - buy_notional,
    }
    state["positions"][product] = pos
    state["cash_usdc"] = round(state["cash_usdc"] - POSITION_USDC, 8)
    return pos


def assess_exit(state, product, bid, now):
    """Monitor/exit one coin independently without affecting other positions."""
    pos = state["positions"].get(product)
    if not pos or not _valid_number(bid, 0) or bid == 0:
        return None
    net_value = net_exit_value(pos, bid)
    pct = (net_value / pos["entry_cost_usdc"] - 1) * 100
    peak = max(float(pos.get("peak_net_pct", -100)), pct)
    pos["peak_net_pct"] = peak
    reason = None
    if pct <= -8:
        reason = "modeled stop-loss (-8% net)"
    elif pct >= 12:
        reason = "modeled take-profit (+12% net)"
    elif peak >= 6 and pct <= peak - 4:
        reason = "modeled trailing exit (4 percentage points from peak)"
    if not reason:
        return {"exit": False, "net_pct": round(pct, 2), "peak_pct": round(peak, 2)}
    pnl = net_value - pos["entry_cost_usdc"]
    state["cash_usdc"] = round(state["cash_usdc"] + net_value, 8)
    state["realized_pnl_usdc"] = round(state["realized_pnl_usdc"] + pnl, 8)
    trade = {
        "product": product, "entry_time": pos["entry_time"],
        "exit_time": now, "entry_cost_usdc": pos["entry_cost_usdc"],
        "exit_proceeds_usdc": round(net_value, 6),
        "pnl_usdc": round(pnl, 6), "pnl_pct": round(pct, 2),
        "reason": reason,
    }
    state["trades"].append(trade)
    state["trades"] = state["trades"][-200:]
    del state["positions"][product]
    return {"exit": True, "trade": trade}


def stamp_state(state, now):
    state["updated_utc"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    return state
