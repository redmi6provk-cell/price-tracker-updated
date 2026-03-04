import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def send_telegram_alert(message: str) -> bool:
    """Send a message to the configured Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Token/Chat ID not configured. Skipping.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    print("[Telegram] ✅ Alert sent successfully")
                    return True
                else:
                    body = await resp.text()
                    print(f"[Telegram] ❌ Failed ({resp.status}): {body}")
                    return False
    except Exception as e:
        print(f"[Telegram] ❌ Exception: {e}")
        return False
