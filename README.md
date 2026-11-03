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

## DEX security review + separate shadow portfolio

The new DEX research pipeline, run after `new_launch_radar.py`, is:

- `dex_security.py`: fetches **read-only GoPlus** token reports for Solana and Base, verifies exact chain/token address and checks available mint/freeze/transfer/honeypot/admin-control/tax/holder-concentration signals. Responses are classified **blocked**, **unknown**, or **observed_pass**. **Unknown is never accepted as a pass.** This is not an audit or security guarantee. No liquidity-lock, wash-trading, connected-wallet or executable swap validation is done.
- `dex_shadow.py`: reviews up to 12 current new-launch candidates; it can simulate a `$50` shadow entry **only** if security fields return observed_pass, the launch was observed across multiple scans, pool age/volume/liquidity meet higher thresholds, and a public pool USD price can be retrieved. Missing, stale or incomplete information results in **no entry**.
- An **independent comparative $150 DEX shadow scenario** records up to three distinct $50 positions. This is *not* a second funding source, *not* the existing Coinbase paper ledger, and *not* the real Coinbase balance. **Do not add the two paper scenario budgets together**. The existing Coinbase positions and $50 simulated entry policy are unchanged.
- The shadow model uses public **GeckoTerminal pool-mark prices** and an illustrative **2.5% cost on each side**; no executable on-chain quotes or simulated transaction receipts are obtained. It uses modeled profit/loss/time exits, but if a sale quote is unavailable, it records **no fake sale**. Even a profitable modeled result can be impossible to realize, especially if pool liquidity disappears.
- Shadow results and risk findings live in [data/dex_shadow_state.json](https://github.com/Obase2512/Trading/blob/main/data/dex_shadow_state.json) and [data/dex_security_reviews.json](https://github.com/Obase2512/Trading/blob/main/data/dex_security_reviews.json), plus GitHub workflow logs.
- **No Telegram alerts from the DEX shadow model, no live orders, and no funds/wallet access.** Telegram remains reserved for qualifying existing Coinbase-paper buy/sell events. This DEX evaluation is a *benchmark and engineering experiment*, not a launch-ready trading engine.

The GoPlus endpoint may rate-limit or return partial reports. You can optionally set `GOPLUS_ACCESS_TOKEN` as a GitHub Actions repository **secret**, but the pipeline still runs in restricted, fail-closed research mode without it. Never store wallet seed phrases, signing keys or trading credentials in this repository.

**Next required milestone:** incorporate *real bidirectional Solana Jupiter / Base routing quotes and sell-simulation* without sending signed orders; test pool/holder concentration, liquidity withdrawal, creator clusters, transaction landing, execution costs, and reliable sub-minute monitoring. **Only then should any real-money pilot be considered**, after reviewing trustworthy completed paper-trade outcomes and an explicit separate live-trading authorization.

## New-launch radar: Solana and Base (research-only)

**Focus:** catch candidate newly created DEX trading pools *before* most tokens would reach centralized exchanges.

- Public source: [GeckoTerminal new-pools API](https://api.geckoterminal.com/docs/index.html), paginated for **Solana** and **Base** on each scheduled scan. DEX Screener's existing profile/boost discovery remains available, but is not treated as a complete source of newly launched tokens.
- Source coverage is incomplete: the first three pages per network are scanned each run; newly created pools may disappear from these pages quickly, and a new pool may contain an old token. This is **not exhaustive tracking of every newly minted meme coin**.
- The scanner filters for pool age **5 minutes to 72 hours**, at least **$75,000 measured liquidity**, **$150,000 recent 24-hour volume**, and at least **60 buys / 30 sells**. It rejects very extreme 24-hour volume-to-liquidity ratios.
- A *research-priority* score considers liquidity, trading activity, age, turnover, price changes and a simple meme-theme **name hint**. It is **not a confidence score, profit forecast or verified meme classification**. Token symbols and names can be copied by scammers.
- Candidates appear in the GitHub Actions step **Research newly launched DEX pools** and in [data/new_launch_radar.json](https://github.com/Obase2512/Trading/blob/main/data/new_launch_radar.json). The JSON includes token and pool addresses (do not rely on symbols alone), age, measured volume, liquidity, buying/selling transactions and provider links.
- No candidate is automatically promoted to a Coinbase paper-trade watchlist, and **no Telegram message is sent merely because a new pool qualifies for research**. Your Telegram-only-on-paper-BUY/SELL preference remains unchanged.
- Most important: this radar **does not yet check mint/freeze authority, LP locks, holder/creator concentration, wash-trading, contract traps, honeypots or real exit liquidity**. No DEX buy/sell simulator is active. Before using radar findings as buy signals, build a chain-specific risk verification stage, verified pool-pricing/execution simulation, separate paper position ledger and tested exits.

**Watchlist nuance:** early launches on a DEX cannot automatically be bought on Coinbase. Our currently active $50 simulated trades are still **Coinbase USDC pairs**; the $150 paper budget and three-position cap are unchanged.

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
