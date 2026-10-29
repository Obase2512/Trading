# Trading Sentinel — Meme Coin Research + Paper Buy/Sell Alerts

A **research-only** monitoring experiment using public Coinbase and DEX Screener market data. It does **not** buy or sell crypto, connect to your Coinbase account, or risk your real $50.73 balance.

## What this version does

The scheduled GitHub Actions workflow runs *approximately* every 30 minutes (GitHub cron jobs can be late or skipped):

1. `scanner.py`: checks Coinbase's public spot catalog for newly detected exchange symbols and DEX Screener's **incomplete/promotional** token profile feeds. These are **unverified discovery alerts**, not buy signals.
2. `paper_alerts.py`: screens the watchlist `DOGE-USDC,PEPE-USDC,BONK-USDC` against public Coinbase quotes and the last 24 *closed* hourly candles.
3. `signals.py`: produces a hypothetical **PAPER BUY WATCH** when all five basic conditions pass: upward short-term moving-average trend; 6h price change of +1% to +15%; positive 1h momentum (up to +6%); at least $100,000 estimated 24h turnover; quoted bid/ask spread no more than 0.8%.
4. With a simulated position open, later scans issue a **PAPER SELL WATCH** after a modeled net +12% take-profit, -8% stop-loss, or trailing decline of 4 percentage points from a +6% gain.
5. Notifications go through **Telegram** when its bot token and chat ID are configured. Twilio SMS is an optional alternative; if both are configured, both receive alerts. Without a provider, alerts appear only in GitHub Actions logs. Optionally set an OpenAI API key for **descriptive commentary** when a paper entry occurs; LLM text does not authorize trades.

**Crucial**: These threshold rules have **not been validated for predictive performance**. A 100/100 filter score is not a 100% success probability or an assessment of token contract safety. The algorithm does not check whale concentration, freeze/mint authority, liquidity locks, honeypot restrictions or rugs. The selected watchlist includes only Coinbase exchange-traded assets: DEX-only discoveries remain informational until further screening is developed.

## Paper account (not linked to Coinbase)

- Initial simulated balance: **50 USDC** in `data/paper_state.json`.
- Maximum simulated purchase: **10 USDC**, fees included.
- One position at a time, no leverage.
- Approximate market-entry/exit fees: **0.90% taker each side** (update if your actual tier changes).
- Extra assumed slippage: **0.30% per side**; actual execution can be worse.
- Stop new simulated entries at **10 USDC cumulative realized losses**.
- Price-exit checks run **only when the workflow executes**, so a sharp crash can pass through a stop between checks. **This is NOT a reliable real-time stop-loss**.
- GitHub commits paper-trade state to this **public repository**. It contains *hypothetical* orders only; never add account details or real positions here.

## Test the upgraded workflow

1. Run `git pull origin main` on your Mac, making sure you have no uncommitted changes before pulling.
2. In your active virtual environment run:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python paper_alerts.py
```

3. From [GitHub Actions](https://github.com/Obase2512/Trading/actions), select **Trading Sentinel — discovery and paper alerts**, click **Run workflow**, and keep `test_sms` unchecked.
4. Open the latest workflow run. It should show both *Research discovery* and *Paper buy/sell watch* steps and then save `data/state.json` and `data/paper_state.json`.
5. To inspect your *hypothetical* portfolio, open `data/paper_state.json` in GitHub after the run. It starts with 50 USDC and may open a simulated position only when all conditions pass. If no signal passes, that is expected.

## Telegram alerts (recommended)

Telegram bot messages use the Bot API and don't incur Twilio SMS charges.

1. In Telegram, open the official [@BotFather](https://t.me/BotFather) bot, send \`/newbot\`, choose a name and unique username ending with \`bot\`.
2. Open the **new bot**, press **Start**, and send **hello**. Telegram bots cannot initiate chats before you do.
3. Run \`git pull origin main\` on your Mac, then in the Python virtual environment run \`python telegram_setup.py\`. The script privately prompts for the BotFather token (no echo or local storage), reads your bot's incoming messages, and displays your private numeric chat ID. If no chat ID is found, send your new bot another message and rerun the script.
4. In your repository's **Settings → Secrets and variables → Actions**, choose **New repository secret** and save two secrets:
   - \`TELEGRAM_BOT_TOKEN\`: token provided by BotFather (keep it secret).
   - \`TELEGRAM_CHAT_ID\`: numeric private chat ID printed by the script.
5. Go to [GitHub Actions](https://github.com/Obase2512/Trading/actions), select **Trading Sentinel — discovery and paper alerts**, click **Run workflow**, and check **test_telegram** (leave \`test_sms\` unchecked). A successful run sends **one Telegram test message** and does not execute scanning or trades.
6. Leave Telegram notifications enabled on your phone. Subsequent scheduled runs will send **research and paper buy/sell alerts if a qualifying event is detected**. No event means no message.

**Never paste the bot token into a chat, commit it in a public GitHub file, or share screenshots containing it.** The setup script does not store it. The bot has no trading credentials or permissions.

If the Telegram test fails, verify both GitHub secrets, that you pressed **Start** in your bot, and the Actions run logs. The code deliberately suppresses Telegram tokens from API error messages.

## Optional SMS and AI explanation

Add the following to **Settings → Secrets and variables → Actions → New repository secret** (never paste secrets into the public repo):

| Secret | Function |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio credential |
| `TWILIO_FROM_NUMBER` | Twilio SMS sender in +countrycode format |
| `ALERT_TO_NUMBER` | Your destination phone number in +countrycode format |
| `OPENAI_API_KEY` | Optional AI commentary; API usage billed separately |

To test Twilio SMS after secrets are set, trigger a manual run with `test_sms` checked. Telegram has its own `test_telegram` checkbox. Twilio U.S. A2P registration or other sender rules and charges may apply. If the text service fails, read GitHub logs; alerts are not automatically resent.

To edit the paper watchlist, change `PAPER_WATCHLIST` in `.github/workflows/scan.yml`. Do not add a DEX-only pair; this feature uses Coinbase spot market data.

## Next development goals

1. Strengthen contract/holder/security risk checks before suggesting *any real trade*.
2. Record and assess dozens of hypothetical trades, including alternative outcomes, total fees and missed signals.
3. Improve monitoring reliability, state storage, and SMS delivery; consider a continuously running service for time-sensitive exits.
4. Only if warranted, consider *manually approved* live trades with strict limits. Never deploy real trading API credentials into this project during testing.

Sources: [Coinbase public market-data API](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles), [DEX Screener API](https://docs.dexscreener.com/api/reference), [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
