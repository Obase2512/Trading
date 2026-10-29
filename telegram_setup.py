"""Print Telegram chat IDs without exposing or saving the bot token.

Run: python telegram_setup.py
First press Start and send "hello" to your new Telegram bot.
"""
import getpass

import requests


def main():
    token = getpass.getpass("Paste Telegram bot token (input hidden): ").strip()
    if not token:
        print("No token entered.")
        return
    try:
        response = requests.get(
            "https://api.telegram.org/bot" + token + "/getUpdates",
            params={"limit": 100, "timeout": 0}, timeout=20)
        if response.status_code != 200:
            print("Telegram returned HTTP", response.status_code,
                  "(check token; do not share it).")
            return
        payload = response.json()
        if not payload.get("ok"):
            print("Telegram did not accept the request. Check your bot token.")
            return
    except (requests.RequestException, ValueError):
        print("Could not fetch updates. Check connectivity and token.")
        return
    found = set()
    for update in payload.get("result", []):
        msg = update.get("message") or update.get("edited_message")
        chat = msg.get("chat") if isinstance(msg, dict) else None
        if chat and chat.get("type") == "private" and chat.get("id") is not None:
            found.add(str(chat["id"]))
    if not found:
        print("No private chats found. Open your new bot, press Start,")
        print("send it 'hello', then run this program again.")
    else:
        print("Private chat ID(s):", ", ".join(sorted(found)))
        print("Use your own chat ID as the TELEGRAM_CHAT_ID GitHub secret.")
        print("Your bot token was not printed or saved.")


if __name__ == "__main__":
    main()
