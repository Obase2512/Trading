# Trading Sentinel — 3-Coin Paper Trading + Telegram Alerts

**Paper trading only. No Coinbase API keys, no exchange orders, no DEX purchases.**
This app screens curated Coinbase exchange-listed meme-coin symbols using public candles and quotes. It uses deterministic price/volume rules, with optional AI commentary, not a validated predictive AI trading strategy.

## Reliability upgrade — monitoring ownership and early Solana coverage

### Coinbase paper exit monitoring (active after the next GitHub workflow run)

- Existing Coinbase paper positions are checked with the Advanced Trade public ticker. If its **independently timestamped** trade quote is stale/unavailable, a *separate Coinbase Exchange REST ticker* is tried **for exits only**. Every price must have a fresh timestamp and valid bid/ask; stale or excessively wide quotes **never create fictitious stop-loss fills**. This does not guarantee real execution.
- Exit health is recorded in `data/paper_state.json` at `monitoring.exit_quotes.<SYMBOL>`, including independent price source and count of consecutive missing quotes. Missing data is logged clearly; Telegram remains **paper BUY/SELL events only**, never monitoring chatter.
- The existing paper cumulative realized-loss limit of **-$15** still blocks new entries; it does **not** delete or automatically sell old paper positions. The logic now avoids scanning new candidates when entries are blocked.

### Second Solana discovery source (active after next workflow run)

- In addition to GeckoTerminal, `solana_launch_feed.py` reads **recent DEX Screener token profiles**, then verifies their Solana pair address, pool creation time, liquidity, volume, and buy/sell activity through the token-pairs endpoint.
- Results are stored separately at [data/solana_secondary.json](https://github.com/Obase2512/Trading/blob/main/data/solana_secondary.json), and copied into the radar snapshot only while the source is fresh.
- **DEX Screener profiles may be paid/promoted and are NOT exhaustive new mint listings.** This is a second unverified *research-only* source, NOT a meme-coin safety ranking, trading opportunity, or permission to enter. No auto-buy or Telegram signals result from these discoveries.
- If one feed is unavailable, its failure should not erase the independently persisted other feed.

### Always-on worker prepared; NOT DEPLOYED or ACTIVE by default

A long-running, single-writer alternative to GitHub's delayed schedules is now available: `sentinel_worker.py`.
It targets **60-second** checks for existing Coinbase paper positions, **3-minute** launch/DEX shadow scans, and **5-minute** provider-health checks. Cadences are application targets, not guarantees. This is **paper-only**.

**Important: do not start the worker while GitHub Actions continues writing portfolio state.**
A persistent hosting account (for example [Railway persistent services](https://docs.railway.com/services))
and a persistent filesystem volume are required. Hosting can cost money. No new exchange account, wallet or Coinbase API key is required.

Recommended single-writer handoff if you choose persistent hosting:

1. Keep the GitHub schedule as-is until ready for the handoff; note the latest completed `data/paper_state.json` and `data/dex_shadow_state.json`. This repository's main branch must contain the final, up-to-date ledgers before worker deployment.
2. Set GitHub repository **Settings → Secrets and variables → Actions → Variables**: `SENTINEL_WORKER_ACTIVE=true`. This stops **the data-writing and Telegram steps** on subsequent GitHub scheduled/manual workflows (pull-request unit tests remain enabled).
3. In Railway (or similar), deploy **one persistent worker service** from the latest `main` commit. In its service Settings set **Start Command** to `python sentinel_worker.py`. Attach a persistent volume mounted to **`/data`** and configure `SENTINEL_STATE_DIR=/data`. Make sure the source branch contains the latest GitHub state at this handoff; do not deploy from an old checkout.
4. Set worker service variables `SENTINEL_WORKER_ENABLED=true` and `SENTINEL_GITHUB_WRITER_DISABLED=true` **only after** step 2. If you want Telegram paper BUY/SELL alerts, copy the existing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as **service secrets**, never in the public repo. Optional research API secrets: `JUPITER_API_KEY`, `ZEROX_API_KEY`, `GOPLUS_ACCESS_TOKEN`.
5. Inspect worker service logs and the volume file **`/data/worker_heartbeat.json`**. The worker fails closed without the owner-handoff flags or mounted volume, and refuses concurrent workers on the same volume. Persistent mode saves state **on that volume**, not to the GitHub JSON files.
6. To switch back to GitHub, first stop the worker, **copy the latest saved paper/DEX ledgers from the persistent volume back to the repository**, and only then set `SENTINEL_WORKER_ACTIVE=false`. Otherwise state would rewind and alerts/trades could duplicate.

This arrangement **has not been deployed to any cloud account**. It will NOT speed up the running GitHub schedule until a persistent host is provisioned and explicitly switched over. Never run two monitoring writers or multiple worker replicas. Neither setup is suitable for guaranteed stop-loss execution, and no real-money trade execution exists.

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
- `dex_shadow.py`: reviews up to 12 current new-launch candidates; it can simulate a **$50 indicative** entry only if risk checks return `observed_pass`, a recent pool was observed across multiple scans, strict activity thresholds pass, **and independently routed $50 buy and immediate sell quotes are both available**. Missing or adverse routes block new entries.
- An **independent comparative $150 DEX shadow scenario** records up to three distinct $50 positions. This is *not* a second funding source, *not* the existing Coinbase paper ledger, and *not* the real Coinbase balance. **Do not add the two paper scenario budgets together**. The existing Coinbase positions and $50 simulated entry policy are unchanged.
- `dex_quotes.py` uses **Jupiter Swap V2 GET `/order` with no wallet/taker on Solana**, and **0x AllowanceHolder V2 GET `/price` on Base** to obtain read-only *indicative*, bidirectional route prices. It models native gas with a separately labeled estimate ($0.40 per Solana swap, $1 per Base swap). These amounts are NOT guaranteed gas, execution quotes, or swap-tax estimates. Subsequent sell events require a fresh token→USDC indicative route; if no usable sell route exists, **no successful simulated sale is recorded**. Historical mark-only DEX positions, if any, are preserved but *cannot* be magically converted to routed sales without their raw token units.
- Shadow results and risk findings live in [data/dex_shadow_state.json](https://github.com/Obase2512/Trading/blob/main/data/dex_shadow_state.json) and [data/dex_security_reviews.json](https://github.com/Obase2512/Trading/blob/main/data/dex_security_reviews.json), plus GitHub workflow logs.
- **No Telegram alerts from the DEX shadow model, no live orders, and no funds/wallet access.** Telegram remains reserved for qualifying existing Coinbase-paper buy/sell events. This DEX evaluation is a *benchmark and engineering experiment*, not a launch-ready trading engine.

The GoPlus endpoint may rate-limit or return partial reports. You can optionally set `GOPLUS_ACCESS_TOKEN` as a GitHub Actions repository **secret**, but the pipeline still runs in restricted, fail-closed research mode without it. Never store wallet seed phrases, signing keys or trading credentials in this repository.

**Live read-only quote provider checks:** The scheduled workflow now independently exercises a **$50 USDC → wrapped SOL → USDC** indicative path (Solana, Jupiter), and a **$50 USDC → WETH → USDC** indicative path (Base, 0x only when its API key exists). It stores route status, provider names and an *estimated* immediate round-trip cost in [data/dex_quote_health.json](https://github.com/Obase2512/Trading/blob/main/data/dex_quote_health.json). These known-liquid reference assets are NOT new-meme-coin recommendations. A provider passing this connectivity check does **not** mean any specific new token is tradeable, safe, or sellable. Failure never triggers a trade or fabricated fill.

**Route quote setup:** Jupiter's quote-only V2 endpoint supports limited requests without an API key. An optional `JUPITER_API_KEY` GitHub Actions secret improves rate limits. **Base requires a `ZEROX_API_KEY` GitHub Actions secret** from the 0x developer dashboard; without it Base quote checks are unavailable and Base shadow trades will not open. These are *read-only provider API keys*, not wallet seed phrases or trading permissions. The new code NEVER invokes Jupiter `/execute`, 0x `/quote`, signs transactions, or sends orders.

**Next required milestone:** verify real gas/network fees and quote-vs-execution slippage under controlled non-live simulations; deepen contract/holder/creator-cluster screening, check liquidity withdrawal and improve reliable minute-level monitoring. An indicative two-way route *today* does NOT prove the token can be sold *later*. Before live trading, review meaningful paper performance and obtain a separate explicit live-trading authorization.

## New-launch radar: Solana and Base (research-only)

**Focus:** catch candidate newly created DEX trading pools *before* most tokens would reach centralized exchanges.

- Public source: [GeckoTerminal new-pools API](https://api.geckoterminal.com/docs/index.html), paginated for **Solana** and **Base** on each scheduled scan. DEX Screener's existing profile/boost discovery remains available, but is not treated as a complete source of newly launched tokens.
- Source coverage is incomplete: the first three pages per network are scanned each run; requests are **paced**, and transient HTTP 429/5xx failures use **bounded retries** and `Retry-After` when available. The radar reports `coverage_complete`, `pages_by_network`, and errors; a partial scan is not portrayed as exhaustive. New pools can disappear from the feed between runs or contain old tokens. This does **not** detect every meme launch, especially pre-pool bonding-curve activity.
- The scanner now maintains **two clearly separated tiers**: broader `watch_leads` for new pools with at least **$20,000 measured liquidity**, **$10,000 24h volume**, and **5 buys / 5 sells** (research ONLY, not eligible for buys); and the original stricter `candidates` tier, requiring **5 minutes–72 hours**, at least **$75,000 liquidity**, **$150,000 volume**, **60 buys / 30 sells** and liquidity/volume checks. These are not security guarantees.
- A *research-priority* score considers liquidity, trading activity, age, turnover, price changes and a simple meme-theme **name hint**. It is **not a confidence score, profit forecast or verified meme classification**. Token symbols and names can be copied by scammers.
- Candidates appear in the GitHub Actions step **Research newly launched DEX pools** and in [data/new_launch_radar.json](https://github.com/Obase2512/Trading/blob/main/data/new_launch_radar.json). The JSON includes token and pool addresses (do not rely on symbols alone), age, measured volume, liquidity, buying/selling transactions and provider links.
- No candidate is automatically promoted to a Coinbase paper-trade watchlist, and **no Telegram message is sent merely because a new pool qualifies for research**. Your Telegram-only-on-paper-BUY/SELL preference remains unchanged.
- The radar *by itself* does not certify meme classification or verify security. GoPlus preliminary checks and optional quote-based shadow simulation run separately, but still cannot prove liquidity locks, honest volume, token ownership distribution, future exit availability, or successful real settlement. **No DEX trading is enabled.**

**Watchlist nuance:** early launches on a DEX cannot automatically be bought on Coinbase. Our currently active $50 simulated trades are still **Coinbase USDC pairs**; the $150 paper budget and three-position cap are unchanged.

## Research universe

The default curated set is DOGE, PEPE, BONK, SHIB, FLOKI, WIF, TURBO, MOG, BRETT, PENGU, POPCAT and FARTCOIN, **only where a currently identified eligible Coinbase spot USDC trading pair exists**. Unsupported and stale tickers are skipped.

The catalog discovery step tracks changes in Coinbase Exchange assets and a partial/promoted DEX Screener feed. A brand-new token discovered on a DEX is **not automatically eligible** for simulated Coinbase trading. Likewise, a newly listed exchange meme token must be included in the curated symbol set (configurable via the PAPER_WATCHLIST environment variable) before buy rules are evaluated. This is **not** an exhaustive discovery system for all meme coin launches.

A candidate must pass all five entry filters: upward short-term moving-average trend; six-hour momentum from +1% to +15%; positive one-hour momentum no greater than +6%; at least $100,000 estimated turnover in the last 24 hours; and quoted spread at most 0.8%. A perfect filter score is **not** a probability of profit or token safety certification.

## Independent paper SELL WATCH conditions

Each *Coinbase* paper position is tracked independently; it may generate a SELL WATCH on a modeled **+12% net profit**, **-8% net loss**, or a **4-percentage-point decline after a +6% gain**. These thresholds include assumed fees and slippage. GitHub Actions runs approximately every 30 minutes but can be delayed, so these are **not guaranteed stop-losses**.

## Telegram alerts

Existing Telegram secrets (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) work unchanged. One paper BUY WATCH alert is produced for each newly simulated position; one SELL WATCH alert for each simulated exit. Multiple buy/sell messages can be sent in the same run. There are **no Telegram messages** for discovery-only coins, scans without qualifying events, or ordinary hold updates.

A manually selected test_telegram workflow option sends only one connectivity message, not a buy or sell signal.

## Run and verify

1. Open [Trading Sentinel Actions](https://github.com/Obase2512/Trading/actions/workflows/scan.yml).
2. Choose **Run workflow**, branch **main**, leave **test_telegram unchecked**.
3. After the first successful run, inspect [data/paper_state.json](https://github.com/Obase2512/Trading/blob/main/data/paper_state.json) to confirm **version 2**, starting balance **150**, and the **positions** mapping. The one-time paper credit happens on this run, not at code commit time.
4. Subsequent scans target roughly **every 10 minutes** (minutes 7, 17, 27, 37, 47, 57 UTC), but **GitHub Actions can delay or skip scheduled jobs**. This is NOT suitable for real-time protective exits.
5. Local check: git pull origin main; python -m unittest discover -s tests -v

**Risk:** The engine does not audit token contracts, insider/holder concentration, liquidity locks, or honeypots. Fee/slippage assumptions are not a price guarantee. Monitor paper results over many trades before ever contemplating live trading. Never publish Coinbase keys, wallet secrets, or Telegram tokens in this public repository.
