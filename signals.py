"""Deterministic, research-only signal rules. Never sends exchange orders.

Public market candles + bid/ask quotes are imperfect. This is a paper-trading
experiment, not a validated investment strategy or a live stop-loss service.
"""
import math
from datetime import datetime, timezone

STARTING_USDC = 50.0
POSITION_USDC = 10.0
TAKER_FEE = 0.009  # Assumption: verify actual Coinbase tier before any real trading.
SIM_SLIPPAGE = 0.003  # Additional modeled cost per side; real slippage can be higher.
MAX_REALIZED_LOSS = 10.0
CANDLE_SECONDS = 3600


def fresh_candles(raw, now):
    """Get recent *closed* 1h candles, rejecting stale/gapped public data."""
    if not isinstance(raw, dict) or not isinstance(raw.get("candles"), list):
        return []
    candles = []
    for c in raw["candles"]:
        try:
            start = int(c["start"])
            close, volume = float(c["close"]), float(c["volume"])
            if start + CANDLE_SECONDS > now - 60:
                continue  # ignore forming candles
            if not math.isfinite(close) or not math.isfinite(volume) or close <= 0 or volume < 0:
                continue
            candles.append({"start": start, "close": close, "volume": volume})
        except (TypeError, ValueError, KeyError):
            continue
    by_start = {c["start"]: c for c in candles}
    ordered = [by_start[k] for k in sorted(by_start)]
    window = ordered[-24:]
    if len(window) < 24:
        return []
    if now - (window[-1]["start"] + CANDLE_SECONDS) > 7200:
        return []
    if any(b["start"] - a["start"] != CANDLE_SECONDS for a, b in zip(window, window[1:])):
        return []
    return window


def assess_market(product, candles, bid, ask):
    """Score a *watchlist* signal from verified fresh data only."""
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)):
        return None
    if ask < bid or len(candles) < 24:
        return None
    spread_pct = (ask - bid) / ask * 100
    prices = [c["close"] for c in candles[-24:]]
    sma5 = sum(prices[-5:]) / 5
    sma20 = sum(prices[-20:]) / 20
    change6h_pct = (prices[-1] / prices[-7] - 1) * 100
    change1h_pct = (prices[-1] / prices[-2] - 1) * 100
    turnover24_usd = sum(c["close"] * c["volume"] for c in candles[-24:])
    checks = {
        "trend": sma5 >= sma20 * 1.005,
        "momentum_6h": 1 <= change6h_pct <= 15,
        "last_hour_positive": 0 < change1h_pct <= 6,
        "turnover_24h": turnover24_usd >= 100000,
        "spread": spread_pct <= 0.8,
    }
    passed = all(checks.values())
    return {
        "product": product,
        "bid": bid,
        "ask": ask,
        "spread_pct": round(spread_pct, 3),
        "momentum_6h_pct": round(change6h_pct, 2),
        "momentum_1h_pct": round(change1h_pct, 2),
        "turnover_24h_usd": round(turnover24_usd),
        "checks": checks,
        "score": sum(checks.values()) * 20,
        "entry_watch": passed,
    }


def initial_state():
    return {"version": 1, "starting_usdc": STARTING_USDC,
            "cash_usdc": STARTING_USDC, "position": None,
            "realized_pnl_usdc": 0.0, "trades": [],
            "last_alerts": {}, "updated_utc": ""}


def net_exit_value(position, bid):
    execution_price = bid * (1 - SIM_SLIPPAGE)
    return position["units"] * execution_price * (1 - TAKER_FEE)


def entry(state, market, now):
    """Simulate a $10 inclusive-of-fees buy, from paper cash only."""
    if state["position"] or not market["entry_watch"]:
        return None
    if state["realized_pnl_usdc"] <= -MAX_REALIZED_LOSS:
        return None
    if state["cash_usdc"] + 1e-8 < POSITION_USDC:
        return None
    ask = market["ask"] * (1 + SIM_SLIPPAGE)
    buy_notional = POSITION_USDC / (1 + TAKER_FEE)
    units = buy_notional / ask
    position = {
        "product": market["product"], "units": units, "entry_execution_price": ask,
        "entry_bid": market["bid"], "entry_cost_usdc": POSITION_USDC,
        "entry_time": now, "peak_net_pct": -100,
        "entry_fee_usdc": POSITION_USDC - buy_notional,
    }
    state["position"] = position
    state["cash_usdc"] = round(state["cash_usdc"] - POSITION_USDC, 8)
    return position


def assess_exit(state, bid, now):
    """Update paper trailing peak; simulate rule-based exit if triggered."""
    pos = state.get("position")
    if not pos or not isinstance(bid, (int, float)) or not math.isfinite(bid) or bid <= 0:
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
    trade = {"product": pos["product"], "entry_time": pos["entry_time"],
             "exit_time": now, "entry_cost_usdc": pos["entry_cost_usdc"],
             "exit_proceeds_usdc": round(net_value, 6),
             "pnl_usdc": round(pnl, 6), "pnl_pct": round(pct, 2), "reason": reason}
    state["trades"].append(trade)
    state["trades"] = state["trades"][-100:]
    state["position"] = None
    return {"exit": True, "trade": trade}


def stamp_state(state, now):
    state["updated_utc"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    return state
