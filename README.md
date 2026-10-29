# Trading Sentinel — 3-Coin Paper Trading + Telegram Alerts

**Paper trading only. No Coinbase API keys, no exchange orders, no DEX purchases.**
This app screens curated Coinbase exchange-listed meme-coin symbols using public candles and quotes. It uses deterministic price/volume rules, with optional AI commentary, not a validated predictive AI trading strategy.

## Portfolio (Version 2)

| Setting | Value |
|---|---|
| Target paper budget | **150 USDC** |
| Maximum simultaneously open paper positions | **3 different coins** |
| New paper entry amount | **50 USDC per coin**, fees included |
| Simulated taker fee | **0.9% each side**, assumed |
| Additional simulated slippage | **0.3% each side**, assumed |
| Cumulative realized loss threshold | **-15 USDC stops new paper buys** |
| Re-buy same coin after a paper exit | **6-hour cooldown** |
| Actual Coinbase buys and sells | **DISABLED** |

### Preserving the earlier $50 test

The earlier paper account was Version 1 with a 50 USDC starting balance and possibly an outstanding 10 USDC simulated DOGE position. On its **first successful Version 2 scan**, the bot:
1. Credits **100 USDC only to paper cash**, yielding a 150 USDC paper starting budget.
2. Migrates the earlier single paper position without selling or resizing it.
3. Preserves historical paper trades and realized P&L.
4. Records the credit in a capital-additions ledger, and increases the version number to prevent the $100 from being added again.

**Example:** $40 paper cash and an old $10 DOGE position become $140 paper cash and the same $10 position. Two additional $50 paper positions may open, leaving $40 cash. Once the older $10 position closes, a new $50 position can occupy its slot *if cash and market criteria permit*. The paper cash is entirely separate from your Coinbase wallet; funding Coinbase does not fund this simulation.

## Research universe

The default curated set is DOGE, PEPE, BONK, SHIB, FLOKI, WIF, TURBO, MOG, BRETT, PENGU, POPCAT and FARTCOIN, **only where a currently identified eligible Coinbase spot USDC trading pair exists**. Unsupported and stale tickers are skipped.

The catalog discovery step tracks changes in Coinbase Exchange assets and a partial/promoted DEX Screener feed. A brand-new token discovered on a DEX is **not automatically eligible** for simulated Coinbase trading. Likewise, a newly listed exchange meme token must be included in the curated symbol set (configurable via the PAPER_WATCHLIST environment variable) before buy rules are evaluated. This is **not** an exhaustive discovery system for all meme coin launches.

A candidate must pass all five entry filters: upward short-term moving-average trend; six-hour momentum from +1% to +15%; positive one-hour momentum no greater than +6%; at least $100,000 estimated turnover in the last 24 hours; and quoted spread at most 0.8%. A perfect filter score is **not** a probability of profit or token safety certification.

## Independent paper SELL WATCH conditions

Each open paper position is tracked independently; it may generate a SELL WATCH on a modeled **+12% net profit**, **-8% net loss**, or a **4-percentage-point decline after a +6% gain**. These thresholds include assumed fees and slippage. GitHub Actions runs approximately every 30 minutes but can be delayed, so these are **not guaranteed stop-losses**.

## Telegram alerts

Existing Telegram secrets (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) work unchanged. One paper BUY WATCH alert is produced for each newly simulated position; one SELL WATCH alert for each simulated exit. Multiple buy/sell messages can be sent in the same run. There are **no Telegram messages** for discovery-only coins, scans without qualifying events, or ordinary hold updates.

A manually selected test_telegram workflow option sends only one connectivity message, not a buy or sell signal.

## Run and verify

1. Open [Trading Sentinel Actions](https://github.com/Obase2512/Trading/actions/workflows/scan.yml).
2. Choose **Run workflow**, branch **main**, leave **test_telegram unchecked**.
3. After the first successful run, inspect [data/paper_state.json](https://github.com/Obase2512/Trading/blob/main/data/paper_state.json) to confirm **version 2**, starting balance **150**, and the **positions** mapping. The one-time paper credit happens on this run, not at code commit time.
4. Subsequent checks are scheduled at roughly minutes 13 and 43 UTC; GitHub can delay them.
5. Local check: git pull origin main; python -m unittest discover -s tests -v

**Risk:** The engine does not audit token contracts, insider/holder concentration, liquidity locks, or honeypots. Fee/slippage assumptions are not a price guarantee. Monitor paper results over many trades before ever contemplating live trading. Never publish Coinbase keys, wallet secrets, or Telegram tokens in this public repository.
