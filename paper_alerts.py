"""Market-data-only meme coin WATCH signals and simulated trade bookkeeping.

Never uses Coinbase credentials, checks real holdings, or places real orders.
Coin discovery != permission to trade. DEX-only tokens never enter this engine.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from scanner import get
from telegram_alerts import send_telegram
from signals import (MAX_POSITIONS, POSITION_USDC, initial_state,
                     migrate_state, validate_state, fresh_candles,
                     assess_market, entry, assess_exit, stamp_state)

LOG = logging.getLogger("sentinel.paper")
STATE_PATH = Path("data/paper_state.json")
DISCOVERY_PATH = Path("data/state.json")
CB_MARKET = "https://api.coinbase.com/api/v3/brokerage/market/products"

# Explicitly reviewed symbols only. A new listing must appear in this universe
# before the scanner may even evaluate its market indicators; this is not a
# complete list of meme coins. Check product status and data availability.
DEFAULT_WATCHLIST = ("DOGE-USDC,PEPE-USDC,BONK-USDC,SHIB-USDC,FLOKI-USDC,"
                     "WIF-USDC,TURBO-USDC,MOG-USDC,BRETT-USDC,PENGU-USDC,"
                     "POPCAT-USDC,FARTCOIN-USDC")


def watchlist():
    requested = os.getenv("PAPER_WATCHLIST", DEFAULT_WATCHLIST)
    result = []
    for item in requested.upper().split(","):
        product = item.strip()
        if re.fullmatch(r"[A-Z0-9]{2,20}-USDC", product) and product not in result:
            result.append(product)
    if not DISCOVERY_PATH.exists():
        LOG.info("Coinbase snapshot absent locally; quotes must verify eligibility.")
        return result[:20]
    try:
        discoveries = json.loads(DISCOVERY_PATH.read_text())
        available = set(discoveries.get("coinbase", {}).values())
        return [p for p in result if p in available][:20]
    except (OSError, json.JSONDecodeError, AttributeError):
        LOG.warning("Coinbase discovery catalog unreadable; skip new entries")
        return []


def market_quote(product, now):
    ticker = get(f"{CB_MARKET}/{product}/ticker", {"limit": 1})
    if not isinstance(ticker, dict):
        raise ValueError("Unexpected Coinbase ticker")
    trades = ticker.get("trades")
    if not isinstance(trades, list) or not trades or not isinstance(trades[0], dict):
        raise ValueError("Missing market trade timestamp")
    from datetime import datetime
    ts = datetime.fromisoformat(trades[0]["time"].replace("Z", "+00:00")).timestamp()
    if not (-60 <= now - ts <= 900):
        raise ValueError("Stale public ticker")
    bid, ask = float(ticker["best_bid"]), float(ticker["best_ask"])
    if not (0 < bid <= ask):
        raise ValueError("Invalid bid/ask")
    return bid, ask


def public_candles(product, now):
    result = get(f"{CB_MARKET}/{product}/candles",
                 {"start": str(int(now - 48 * 3600)), "end": str(int(now)),
                  "granularity": "ONE_HOUR", "limit": 48})
    return fresh_candles(result, now)


def optional_ai_explanation(market):
    """Optional qualitative description. Never authorizes a simulated/live buy."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "AI commentary not configured."
    evidence = {k: market[k] for k in
                ("product", "score", "checks", "spread_pct", "momentum_6h_pct",
                 "momentum_1h_pct", "turnover_24h_usd")}
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "gpt-4.1-mini", "max_output_tokens": 100,
                  "instructions": ("Summarize the supplied price/volume checks in one short, "
                                   "cautious sentence. Never recommend real trading. "
                                   "Contract, holder, liquidity-lock risk NOT reviewed."),
                  "input": json.dumps(evidence)}, timeout=25)
        response.raise_for_status()
        words = " ".join(c.get("text", "") for i in response.json().get("output", [])
                         for c in i.get("content", []) if c.get("type") == "output_text")
        return words[:160] or "AI commentary unavailable."
    except (requests.RequestException, ValueError, KeyError):
        return "AI commentary unavailable."


def load_state():
    if not STATE_PATH.exists():
        return initial_state()
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read paper state; refusing to reset") from exc
    return migrate_state(state)


def save_state(state):
    validate_state(state)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    tmp.replace(STATE_PATH)


def publish_signal_alerts(alerts):
    """Telegram only for simulated buy/sell events; silent otherwise."""
    for msg in alerts:
        if not (msg.startswith("PAPER BUY WATCH ") or msg.startswith("PAPER SELL WATCH ")):
            LOG.info("Research-only event suppressed from Telegram")
            continue
        LOG.info("PAPER TRADING SIGNAL: %s", msg)
        if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
            LOG.info("Telegram unconfigured; signal available in GitHub logs")
            continue
        try:
            send_telegram(msg)
            LOG.info("Paper signal sent to Telegram")
        except (RuntimeError, ValueError) as exc:
            LOG.error("Telegram delivery failed: %s", exc)


def scan_once(now=None):
    """Process independent exits first, then best new candidates up to 3 slots."""
    now = time.time() if now is None else now
    state = load_state()
    alerts = []
    exited_this_scan = set()

    # Each simulated holding is tracked independently, even when no longer in
    # the approved watchlist (so it doesn't silently stop being monitored).
    for product in list(state["positions"]):
        try:
            bid, _ = market_quote(product, now)
            decision = assess_exit(state, product, bid, now)
            if decision and decision["exit"]:
                trade = decision["trade"]
                exited_this_scan.add(product)
                alerts.append(
                    f"PAPER SELL WATCH {product}: {trade['reason']}; "
                    f"simulated net P&L {trade['pnl_pct']:+.2f}% / "
                    f"{trade['pnl_usdc']:+.2f} USDC. NO REAL ORDER. "
                    "30-minute polling cannot guarantee stop execution.")
            elif decision:
                LOG.info("PAPER HOLD %s: modeled net %+.2f%%", product,
                         decision["net_pct"])
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOG.warning("SKIP exit evaluation %s: %s", product, exc)

    slots = MAX_POSITIONS - len(state["positions"])
    if slots > 0:
        candidates = []
        for product in watchlist():
            if product in state["positions"] or product in exited_this_scan:
                continue
            try:
                bid, ask = market_quote(product, now)
                metrics = assess_market(product, public_candles(product, now), bid, ask)
                if not metrics:
                    LOG.info("SKIP %s: insufficient fresh market data", product)
                    continue
                LOG.info("WATCH %s score %s/100 6h %+.2f%% spread %.3f%%",
                         product, metrics["score"], metrics["momentum_6h_pct"],
                         metrics["spread_pct"])
                if metrics["entry_watch"]:
                    candidates.append(metrics)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                LOG.warning("SKIP %s: market data unavailable: %s", product, exc)
        candidates.sort(key=lambda m: (-m["score"], m["spread_pct"],
                                       -m["turnover_24h_usd"], m["product"]))
        for best in candidates:
            if len(state["positions"]) >= MAX_POSITIONS:
                break
            pos = entry(state, best, now)
            if pos:
                alerts.append(
                    f"PAPER BUY WATCH {best['product']}: {best['score']}/100 "
                    f"filter score, 6h {best['momentum_6h_pct']:+.2f}%, "
                    f"spread {best['spread_pct']:.3f}%. "
                    f"Simulated {pos['entry_cost_usdc']:.0f} USDC entry, "
                    f"{len(state['positions'])}/{MAX_POSITIONS} slots open. "
                    f"{optional_ai_explanation(best)} "
                    "NOT A REAL BUY RECOMMENDATION; no real order.")

    stamp_state(state, now)
    save_state(state)  # Commit later by GitHub Actions; no manual real trade.
    publish_signal_alerts(alerts)
    LOG.info("PAPER summary: cash %.2f USDC, %d/%d open, realized P&L %+.2f, "
             "%d alerts. NO REAL ORDERS.", state["cash_usdc"],
             len(state["positions"]), MAX_POSITIONS,
             state["realized_pnl_usdc"], len(alerts))
    return state, alerts


def run():
    return scan_once()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
