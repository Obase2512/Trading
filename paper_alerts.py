"""Read-only Coinbase watchlist and simulated buy/sell alerts.

This module NEVER uses Coinbase account credentials or submits an order.
Its trades are entirely hypothetical, using public bid/ask and hourly candles.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from scanner import get, notify
from signals import (initial_state, fresh_candles, assess_market,
                     entry, assess_exit, stamp_state)

LOG = logging.getLogger("sentinel.paper")
STATE_PATH = Path("data/paper_state.json")
CB_MARKET = "https://api.coinbase.com/api/v3/brokerage/market/products"
DEFAULT_WATCHLIST = "DOGE-USDC,PEPE-USDC,BONK-USDC"


def watchlist():
    requested = os.getenv("PAPER_WATCHLIST", DEFAULT_WATCHLIST)
    result = []
    for item in requested.upper().split(","):
        product = item.strip()
        if re.fullmatch(r"[A-Z0-9]{2,20}-USDC", product) and product not in result:
            result.append(product)
    return result[:12]


def market_quote(product, now):
    ticker = get(f"{CB_MARKET}/{product}/ticker", {"limit": 1})
    if not isinstance(ticker, dict):
        raise ValueError("Unexpected Coinbase ticker")
    trades = ticker.get("trades")
    if not isinstance(trades, list) or not trades or not isinstance(trades[0], dict):
        raise ValueError("Missing market trade timestamp")
    # A stale exchange quote must not initiate or close even a paper position.
    from datetime import datetime, timezone
    ts = datetime.fromisoformat(trades[0]["time"].replace("Z", "+00:00")).timestamp()
    if not (-60 <= now - ts <= 900):
        raise ValueError("Stale public ticker")
    bid, ask = float(ticker["best_bid"]), float(ticker["best_ask"])
    if not (0 < bid <= ask):
        raise ValueError("Invalid bid/ask")
    return bid, ask


def public_candles(product, now):
    start = int(now - 48 * 3600)
    result = get(f"{CB_MARKET}/{product}/candles",
                 {"start": str(start), "end": str(int(now)),
                  "granularity": "ONE_HOUR", "limit": 48})
    return fresh_candles(result, now)


def optional_ai_explanation(market):
    """AI can explain checked metrics; AI text NEVER authorizes paper/live buys."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "AI explanation not configured."
    evidence = {k: market[k] for k in
                ("product", "score", "checks", "spread_pct", "momentum_6h_pct",
                 "momentum_1h_pct", "turnover_24h_usd")}
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "gpt-4.1-mini", "max_output_tokens": 100,
                  "instructions": ("Summarize the supplied quantitative market checks in one "
                                   "short cautious sentence. Do not recommend a real trade "
                                   "or claim token safety. State that holder/contract risk "
                                   "has not been verified."),
                  "input": json.dumps(evidence)}, timeout=25)
        response.raise_for_status()
        data = response.json()
        words = " ".join(part.get("text", "") for out in data.get("output", [])
                         for part in out.get("content", [])
                         if part.get("type") == "output_text")
        return words[:180] or "AI explanation unavailable."
    except (requests.RequestException, ValueError, KeyError):
        return "AI explanation unavailable."


def load_state():
    if not STATE_PATH.exists():
        return initial_state()
    data = json.loads(STATE_PATH.read_text())
    # Fail closed if the persisted state is invalid; NEVER reset it silently.
    if (data.get("version") != 1 or not isinstance(data.get("cash_usdc"), (float, int))
        or not isinstance(data.get("trades"), list) or "position" not in data):
        raise ValueError("Invalid paper state; inspect before continuing")
    return data


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    temp.replace(STATE_PATH)


def run():
    now = time.time()
    state = load_state()
    alerts = []
    holding = state.get("position")
    if holding:
        product = holding["product"]
        try:
            bid, _ = market_quote(product, now)
            decision = assess_exit(state, bid, now)
            if decision and decision.get("exit"):
                trade = decision["trade"]
                alerts.append(
                    f"PAPER SELL WATCH {product}: {trade['reason']}; net simulated "
                    f"P&L {trade['pnl_pct']:+.2f}% / {trade['pnl_usdc']:+.2f} USDC. "
                    "NO REAL ORDER. 30-minute checks are not protective stop-losses.")
            elif decision:
                LOG.info("PAPER HOLD %s: modeled net %+.2f%%", product, decision["net_pct"])
        except (requests.RequestException, TypeError, ValueError, KeyError) as exc:
            LOG.warning("Cannot monitor paper position: %s; no exit simulated", exc)
    else:
        candidates = []
        for product in watchlist():
            try:
                bid, ask = market_quote(product, now)
                candles = public_candles(product, now)
                metrics = assess_market(product, candles, bid, ask)
                if metrics is None:
                    LOG.info("SKIP %s: inadequate fresh market data", product)
                    continue
                LOG.info("WATCH %s score %s/100 6h %+.2f%% spread %.3f%%",
                         product, metrics["score"], metrics["momentum_6h_pct"],
                         metrics["spread_pct"])
                if metrics["entry_watch"]:
                    candidates.append(metrics)
            except (requests.RequestException, TypeError, ValueError, KeyError) as exc:
                LOG.warning("SKIP %s: market data unavailable: %s", product, exc)
        if candidates:
            best = sorted(candidates, key=lambda m: (-m["score"],
                          m["spread_pct"], -m["turnover_24h_usd"]))[0]
            position = entry(state, best, now)
            if position:
                alerts.append(
                    f"PAPER BUY WATCH {best['product']}: score {best['score']}/100, "
                    f"6h {best['momentum_6h_pct']:+.2f}%, spread {best['spread_pct']:.3f}%. "
                    f"Simulated $10 entry; {optional_ai_explanation(best)} "
                    "Token safety NOT established. NO REAL ORDER.")
    stamp_state(state, now)
    save_state(state)  # Persist before notification attempt, preventing repeat entries.
    for msg in alerts:
        try:
            notify(msg)
        except requests.RequestException as exc:
            LOG.error("SMS failure (state saved; inspect logs): %s", exc)
    LOG.info("Paper cash %.2f USDC; open %s; total realized P&L %+.2f USDC. "
             "No actual orders.", state["cash_usdc"],
             state["position"]["product"] if state["position"] else "none",
             state["realized_pnl_usdc"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
