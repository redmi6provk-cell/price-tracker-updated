import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# We expect a comma-separated list of "TOKEN:CHAT_ID" pairs for each scanner
# Example: "824458..:1140.. , 123456..:9876.."
AMAZON_TELEGRAM_BOTS = os.getenv("AMAZON_TELEGRAM_BOTS", "")
MYNTRA_TELEGRAM_BOTS = os.getenv("MYNTRA_TELEGRAM_BOTS", "")

# Fallback for backward compatibility if the new vars aren't set
OLD_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OLD_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FALLBACK_BOT = f"{OLD_TELEGRAM_BOT_TOKEN}:{OLD_TELEGRAM_CHAT_ID}" if OLD_TELEGRAM_BOT_TOKEN and OLD_TELEGRAM_CHAT_ID else ""

def get_bots_for_platform(platform: str) -> list:
    """Returns a list of tuples: (bot_token, chat_id)"""
    env_var_name = f"{platform.upper()}_TELEGRAM_BOTS"
    bot_string = os.getenv(env_var_name, "")
    
    if not bot_string:
        bot_string = FALLBACK_BOT
    
    bots = []
    if bot_string:
        # Each pair is "BOT_TOKEN:CHAT_ID"
        # Bot tokens themselves contain a colon (e.g. "12345:ABCxyz")
        # so we must split on the LAST colon to separate chat_id from token
        for pair in bot_string.split(","):
            pair = pair.strip()
            if ":" in pair:
                parts = pair.rsplit(":", 1)  # split on last ":" to get token vs chat_id
                if len(parts) == 2:
                    bots.append((parts[0].strip(), parts[1].strip()))
    return bots


async def send_telegram_alert(message: str, platform: str = "AMAZON") -> bool:
    """Send a message to all configured Telegram bots for the specified platform."""
    bots = get_bots_for_platform(platform)
    
    if not bots:
        print(f"[Telegram] Token/Chat ID not configured for {platform}. Skipping.")
        return False

    success = True
    async with aiohttp.ClientSession() as session:
        for token, chat_id in bots:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        print(f"[Telegram] ✅ Alert sent successfully for {platform} (Bot: ...{token[-4:]})")
                    else:
                        body = await resp.text()
                        print(f"[Telegram] ❌ Failed ({resp.status}) for {platform}: {body}")
                        success = False
            except Exception as e:
                print(f"[Telegram] ❌ Exception for {platform}: {e}")
                success = False
                
    return success
