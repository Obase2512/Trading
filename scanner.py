import json, os, time, logging
from pathlib import Path
import requests
from telegram_alerts import send_telegram

logging.basicConfig(level=logging.INFO)
state_file = Path("data/state.json")

def get(url, params=None):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def coinbase():
    found = {}
    for offset in range(0, 5000, 250):
        data = get("https://api.coinbase.com/api/v3/brokerage/market/products", {"limit":250,"offset":offset,"product_type":"SPOT"})
        products = data.get("products")
        if not isinstance(products, list):
            raise ValueError("Unexpected Coinbase response")
        for p in products:
            if not isinstance(p, dict):
                continue
            base = p.get("base_currency_id")
            if (base and p.get("quote_currency_id") in ("USDC", "USD")
                and p.get("product_type") in ("SPOT",None)
                and str(p.get("status", "online")).lower() == "online"
                and not any(p.get(x) for x in ("trading_disabled","view_only","is_disabled"))):
                found[base] = p.get("product_id")
        if len(products) < 250:
            break
    return found

def dex_profiles():
    out = {}
    for endpoint in ("token-profiles/latest/v1", "token-boosts/latest/v1"):
        rows = get("https://api.dexscreener.com/" + endpoint)
        if not isinstance(rows, list):
            raise ValueError("Unexpected DEX Screener response")
        for t in rows:
            chain, address = t.get("chainId"), t.get("tokenAddress")
            if chain in ("base","solana") and address:
                out[chain+":"+address] = (chain,address)
    return out

def candidate(chain, address, pairs):
    pairs = [p for p in pairs if p.get("chainId") == chain and
        (p.get("baseToken") or {}).get("address") == address]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
    created = p.get("pairCreatedAt")
    if not isinstance(created,(int,float)):
        return None
    age = (time.time()*1000 - created)/3600000
    liq = float((p.get("liquidity") or {}).get("usd") or 0)
    vol = float((p.get("volume") or {}).get("h24") or 0)
    tx = (p.get("txns") or {}).get("h24") or {}
    if not (0 <= age <= 72 and liq >= 100000 and vol >= 200000
            and int(tx.get("buys") or 0) >= 20 and int(tx.get("sells") or 0) >= 20):
        return None
    return {"symbol":(p.get("baseToken") or {}).get("symbol","?"),
        "chain":chain,"address":address,"age_h":round(age,1),"liquidity":round(liq),
        "volume_24h":round(vol),"url":p.get("url","")}

def run():
    if os.getenv("TEST_TELEGRAM") == "true":
        send_telegram("Trading Sentinel Telegram test successful. Research and paper alerts only; no real orders.")
        logging.info("Telegram delivery test succeeded.")
        return
    prior = json.loads(state_file.read_text()) if state_file.exists() else {"initialized":False,"coinbase":{},"seen":{}}
    listings = coinbase()
    profiles = dex_profiles()
    initialized = prior.get("initialized",False)
    seen = {k:v for k,v in prior.get("seen",{}).items() if isinstance(v,(int,float)) and v > time.time()-30*86400}
    alerts = []
    if initialized:
        for coin in sorted(set(listings)-set(prior.get("coinbase",{})))[:2]:
            alerts.append("New Coinbase spot symbol detected: "+coin+" ("+str(listings[coin])+
                "). Confirm official announcement. Research only.")
    looked = 0
    for key,(chain,address) in profiles.items():
        if key in seen:
            continue
        if not initialized:
            seen[key] = time.time()
            continue
        if looked >= 20:
            break
        looked += 1
        try:
            pairs = get("https://api.dexscreener.com/token-pairs/v1/"+chain+"/"+address)
            item = candidate(chain,address,pairs if isinstance(pairs,list) else [])
            seen[key] = time.time()
            if item and len(alerts)<2:
                alerts.append("Unverified DEX watchlist: "+str(item["symbol"])+" on "+chain+
                    " liq $"+str(item["liquidity"])+" 24h volume $"+str(item["volume_24h"])+
                    ". Token: "+address+". Contract and holders not checked. NOT A BUY SIGNAL.")
        except (requests.RequestException, ValueError, TypeError) as ex:
            logging.warning("DEX lookup skipped: %s",ex)
    # Discovery results remain in GitHub logs and never generate Telegram messages.
    # Telegram is reserved for actual paper buy/sell signals in paper_alerts.py.
    for alert in alerts:
        logging.info("DISCOVERY ONLY (no phone notification): %s", alert)
    state_file.parent.mkdir(parents=True,exist_ok=True)
    state_file.write_text(json.dumps({"initialized":True,"coinbase":listings,
        "seen":seen,"updated":time.time()},indent=2)+"\n")
    logging.info("Done: %d Coinbase assets, %d DEX profiles. No orders.",len(listings),len(profiles))

if __name__ == "__main__":
    run()
