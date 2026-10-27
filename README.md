# Trading Sentinel — Read-only meme coin discovery

Research-only scanner for **newly detected Coinbase spot assets** and recently surfaced **Solana / Base DEX token profiles**.

- Runs approximately every 30 minutes through GitHub Actions (scheduled jobs can be delayed or skipped).
- Logs market-data changes and can optionally send research alerts using Twilio.
- Uses public Coinbase and DEX Screener APIs; **does not require a Coinbase API key**.
- Does **not** buy or sell coins, predict profit, monitor your live position, or automatically recommend purchases.
- DEX Screener profiles/boosts are an **incomplete, sometimes promoted discovery feed**, not a comprehensive list of launches. Tokens are not verified or assumed to be available on Coinbase.
- Market filters do **not** verify holder concentration, contract privileges, token sale restrictions, or scam safety.

## Starting the workflow

1. Open **Actions > Trading Sentinel research scan > Run workflow**.
2. The first successful scan **builds a baseline** in \`data/state.json\`, without sending market alerts.
3. Subsequent runs report newly detected assets and research candidates. Check Actions logs.
4. Scheduled runs occur at roughly 13 and 43 minutes past each hour (UTC), subject to GitHub Actions delays.

### Optional SMS alerts

Twilio requires an SMS-capable number and, for many U.S. application-generated messages, A2P registration and charges.

In **Settings > Secrets and variables > Actions**, add these GitHub Actions secrets (never commit real values):

| Secret | Purpose |
|---|---|
| \`TWILIO_ACCOUNT_SID\` | Twilio account SID |
| \`TWILIO_AUTH_TOKEN\` | Twilio auth token |
| \`TWILIO_FROM_NUMBER\` | Twilio sending number in E.164, e.g. +1… |
| \`ALERT_TO_NUMBER\` | Your phone number in E.164 |
| \`OPENAI_API_KEY\` | Optional, enables brief AI-generated caution notes |

From **Run workflow**, select \`test_sms\` to send a single connectivity text after setting the secrets.

### Test locally

\`\`\`bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py
\`\`\`

No trading credentials, seed phrases, wallet keys or funds are required. Do not place them in this public repository.

### What comes next

Before suggesting live entries, improve token-security checks, watchlist persistence, fee-adjusted paper trading, official Coinbase announcement correlation, and ongoing position/exit monitoring. A 30-minute GitHub Action is **not an appropriate real-time stop-loss**.

Docs: [Coinbase public products](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products) · [DEX Screener API](https://docs.dexscreener.com/api/reference) · [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
