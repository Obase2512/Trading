# Trading Sentinel — Research-only meme coin scanner

This first version monitors new-to-the-scanner **Coinbase spot assets** and recently surfaced Solana/Base DEX token profiles. It **does not place orders**, connect to your funded Coinbase account, or issue validated buy/sell signals.

## Current capabilities

- GitHub Actions scanner scheduled for approximately every 30 minutes (runs can be late or skipped).
- Public Coinbase spot-product catalog comparison against a saved baseline. Appearance in the catalog is **not proof of an official new listing announcement**.
- DEX Screener profile and boost feeds. These are incomplete and may be promotional; discovery does not prove a token is newly launched or pre-Coinbase.
- Basic market-data filters (recent pair, liquidity, volume, transaction counts). **No holder concentration, token-authority, honeypot, rug-pull, or liquidity-lock checks yet.**
- Optional Twilio **research alerts**, limited to two per run. SMS costs and U.S. sender-registration requirements can apply.

**Not yet implemented:** AI-based research commentary, comprehensive token security verification, trade journal, price/exit monitoring, and reliable trade signals. No Coinbase credentials or funds are used. We will add and test these features separately.

## First run

1. Go to **Actions → Trading Sentinel research scan → Run workflow**.
2. Leave **test_sms** unchecked and click **Run workflow**.
3. Open that run and inspect the logs. The first successful run only writes a baseline to `data/state.json`—no market alerts.
4. Subsequent runs may produce candidate alerts. The scheduler runs around minutes 13 and 43 of each hour (UTC), but is not real-time.

If the **Actions** tab is disabled, enable actions for the repository in GitHub settings. GitHub Actions may also require workflow write permission to commit the non-sensitive baseline.

## Optional SMS configuration

When ready, create an SMS-capable Twilio account/number, follow applicable registration requirements, and add these **GitHub Actions repository secrets** in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | Sender phone number, international +1… format |
| `ALERT_TO_NUMBER` | Recipient phone number, international +1… format |

Then use **Run workflow**, checking **test_sms**, to send a single test message. **Do not put phone numbers, credentials, wallet seed phrases, or API keys into public files.**

## Local tests

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py
```

## Next milestones

Add verified security/holder checks, AI risk analysis, Coinbase announcement confirmation, performance tracking for paper trades, and higher-frequency position alerts. **Do not place real trades based only on these research alerts.** With a $50 account, losses and costs can be significant.

References: [Coinbase public products](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products), [DEX Screener APIs](https://docs.dexscreener.com/api/reference), [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
