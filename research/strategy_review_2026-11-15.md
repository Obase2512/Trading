# Trading Sentinel — pause decision and strategy review (2026-11-15)

**Decision: NO LIVE TRADING. NO AUTOMATED PAPER ENTRIES.** No wallet/API order credentials, wallet transfers or real-money trades are authorized. The GitHub scheduled scan trigger is removed. The manual dispatch and pull-request test workflow remain.

## Actual six-trade paper simulation (source: `data/paper_state.json`)

| Symbol | Entry (paper USDC) | Exit (paper USDC) | Net % | Net USDC | Exit type |
|---|---:|---:|---:|---:|---|
| DOGE-USDC | 10 | 9.106757 | -8.93% | -0.893243 | modeled -8% stop |
| FLOKI-USDC | 50 | 45.795040 | -8.41% | -4.204960 | modeled -8% stop |
| PEPE-USDC | 50 | 45.307217 | -9.39% | -4.692783 | modeled -8% stop |
| FLOKI-USDC | 50 | 45.960946 | -8.08% | -4.039054 | modeled -8% stop |
| FARTCOIN-USDC | 50 | 44.342607 | -11.31% | -5.657393 | modeled -8% stop |
| BONK-USDC | 50 | 45.932864 | -8.13% | -4.067136 | modeled -8% stop |

**Net:** 0 wins / 6 losses, -$23.55457043 realized, $126.44542957 remaining from $150 simulated cash, no open Coinbase paper positions. The separate DEX shadow ledger remained at $150 simulated cash, zero completed trades. These are distinct paper scenarios and are not combined.

**Why there is insufficient evidence of profitability:** The entry logic requires a rising 5-hour versus 20-hour mean, 1–15% six-hour upward momentum, last-hour gains, minimum 24-hour turnover and spread below 0.8%. All six trades subsequently hit the modeled stop. The entry conditions were heuristic, not supported by a validated forecasting advantage. Entry/exit costs, adverse movement, stale prices and delayed polling can further degrade fills. A stop rule is not a guaranteed maximum loss; FARTCOIN exited at -11.31% modeled net. These six exits do **not** prove every trading strategy will lose, but they do not support the live use of this one. The original `signals.py` paper model assumes 0.9% taker fee and 0.3% slippage on each side, not venue-verified live fees.

## Simpler alternative backtest — 20-day moving-average trend filter

**Historical source:** Coinbase spot market OHLCV daily candles for BTC-USD, ETH-USD and SOL-USD, requested for 2026-01-01 through 2026-11-14. Every asset returned **318 continuous daily candles**. The pairs are USD, **not** the paper bot's USDC pairs; this is a separate exploratory comparison, not a replay of the six actual trades.

**Fixed illustrative rule, no leverage:** At each day’s open, hold 100% of the simulated $150 in one asset **only if the previous completed day’s close exceeds the mean of the 20 completed daily closes ending on that day**. Otherwise stay 100% in USD cash. The signal is evaluated before that day's open. Sell and buy at the next day's open; all remaining holdings are valued **net of exit costs** at the last day’s close. Costs assume 1.2% each side (0.9% assumed fee plus 0.3% assumed slippage). This uses OHLC market candles, not actual bid/ask execution quotes, order book depth or real fills. Compared to a single buy-and-hold entry/exit using the same cost assumptions and to holding cash with zero return. No parameter optimization, slippage stress test, taxes, spread widening or market impact evaluation. Historical performance does not predict future results.

### Full model period: January 21 – November 14, 2026 (298 trading calendar days)

| Asset | 20-day filter | 20-day filter completed simulated round trips | Buy-and-hold | Stay in cash |
|---|---:|---:|---:|---:|
| BTC-USD | **-23.78%** ($114.32) | 17 | -29.12% ($106.33) | 0% ($150) |
| ETH-USD | **-33.31%** ($100.04) | 17 | -41.21% ($88.19) | 0% ($150) |
| SOL-USD | **-34.53%** ($98.20) | 16 | -45.42% ($81.87) | 0% ($150) |

### Separately evaluated late period: September 1 – November 14, 2026 (75 days)

The filter uses 20-day warm-up history preceding September 1, but assumes a **new $150 cash-only portfolio** at the start of the period. This is a second period comparison, not a claim of out-of-sample validation or a forward live test.

| Asset | 20-day filter | Round trips | Buy-and-hold | Cash |
|---|---:|---:|---:|---:|
| BTC-USD | -14.81% ($127.79) | 4 | -20.32% ($119.52) | 0% |
| ETH-USD | -22.28% ($116.58) | 4 | -30.01% ($104.98) | 0% |
| SOL-USD | -8.78% ($136.84) | 3 | -33.43% ($99.85) | 0% |

**Interpretation:** The simple filter lost less than buy-and-hold in these declining samples but still lost to cash on all tested assets and both periods. It is **not** evidence of a profitable replacement trading strategy. Repeated switching and modeled costs materially matter, especially for $150 capital. Do not select the least-negative asset and treat it as an expected gain.

### Research decision

1. Keep live orders and new entries disabled; do not fund a new wallet or deploy trading capital.
2. Keep all original ledgers intact for future audits, with no portfolio resets or retroactive repricing.
3. Do not resume unattended scheduled scans or pay for an idle always-on monitoring service without a specific evidence-based goal.
4. If revisiting the idea, first specify one rule, one market and risk constraints; use multiple disjoint historical regimes, a realistic spread/fee model, sensitivity testing and a genuinely forward-held test. Until a strategy passes this standard, **stop rather than optimize the infrastructure**.

*This is a research-only retrospective illustration, not individualized financial advice or a trading recommendation.*
