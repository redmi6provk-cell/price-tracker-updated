import asyncio
import os
import json
import re
import sys
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from app.notifications import send_telegram_alert

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
COOKIES_PATH = os.path.join(DATA_DIR, "amazon_cookies.json")
PRODUCTS_PATH = os.path.join(DATA_DIR, "amazon_products.json")

# ─── Browser config from .env ──────────────────────────────
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").strip().lower() == "true"
BROWSER_CLOSE    = os.getenv("BROWSER_CLOSE",    "false").strip().lower() == "true"


# ─── Cookie Helpers ───────────────────────────────────────

def sanitize_cookies(raw_cookies: list) -> list:
    """Convert browser-extension exported cookies to Playwright format."""
    cleaned = []
    for c in raw_cookies:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
        }
        if "expirationDate" in c:
            cookie["expires"] = c["expirationDate"]
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("secure"):
            cookie["secure"] = True
        if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
            cookie["sameSite"] = c["sameSite"]
        cleaned.append(cookie)
    return cleaned


# ─── HTML Parser ──────────────────────────────────────────

def parse_cart_alert_html(html: str) -> list[dict]:
    """Parse Amazon cart alert HTML and extract products with decreased prices."""
    soup = BeautifulSoup(html, "html.parser")
    decreased_items = []

    for li in soup.find_all("li"):
        hidden = li.find("input", {"name": "imb-type", "value": "priceDecrease"})
        if not hidden:
            continue

        link_elem = li.find("a", href=True)
        name_elem = li.find("span", class_="sc-product-title")
        if not link_elem or not name_elem:
            continue

        product_name = name_elem.get_text(strip=True)
        product_link = "https://www.amazon.in" + link_elem["href"]

        span_text = li.get_text()
        # Debug: print raw text for price extraction
        print(f"  [DEBUG] Raw text: {repr(span_text[:300])}")
        price_match = re.search(
            r"has decreased from\D*([\d,]+\.?\d*)\s*to\D*([\d,]+\.?\d*)",
            span_text,
        )
        if price_match:
            old_price = price_match.group(1)
            new_price = price_match.group(2)
        else:
            # Fallback: try to find any two price-like numbers near "decreased"
            fallback = re.findall(r"[\d,]+\.?\d+", span_text)
            print(f"  [DEBUG] Primary regex failed. Fallback numbers found: {fallback}")
            if len(fallback) >= 2:
                old_price = fallback[-2]
                new_price = fallback[-1]
            else:
                old_price = "?"
                new_price = "?"

        decreased_items.append({
            "name": product_name,
            "link": product_link,
            "old_price": old_price,
            "new_price": new_price,
        })
        print(f"  📉 {product_name}: ₹{old_price} → ₹{new_price}")

    return decreased_items


# ─── Desired Price Comparison ─────────────────────────────

def compare_with_desired_prices(decreased_items: list[dict]) -> list[dict]:
    """Match decreased items with amazon_products.json and compute drop vs desired."""
    if not os.path.exists(PRODUCTS_PATH):
        print("[Compare] amazon_products.json not found, skipping comparison")
        return decreased_items

    try:
        with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
            tracked_products = json.load(f)
    except Exception as e:
        print(f"[Compare] Error reading amazon_products.json: {e}")
        return decreased_items

    if not isinstance(tracked_products, list):
        print("[Compare] amazon_products.json is not a list, skipping")
        return decreased_items

    for item in decreased_items:
        cart_name = item["name"].lower().strip()
        matched = None
        for prod in tracked_products:
            prod_name = (prod.get("name") or "").lower().strip()
            if not prod_name:
                continue
            if prod_name in cart_name or cart_name in prod_name:
                matched = prod
                break

        if matched:
            desired = matched.get("desired_price")
            mrp = matched.get("mrp")
            try:
                new_price_f = float(item["new_price"].replace(",", ""))
                old_price_f = float(item["old_price"].replace(",", ""))
            except (ValueError, AttributeError):
                continue

            drop_amount = round(old_price_f - new_price_f, 2)
            drop_pct = round((drop_amount / old_price_f) * 100, 1) if old_price_f > 0 else 0

            item["desired_price"] = desired if desired and desired != "" else None
            item["mrp"] = mrp
            item["drop_amount"] = drop_amount
            item["drop_pct"] = drop_pct
            item["hit_desired"] = (
                new_price_f <= float(desired) if desired and desired != "" else False
            )
            status = "✅ HIT" if item["hit_desired"] else "❌ above"
            print(f"  🎯 {item['name']}: drop ₹{drop_amount} ({drop_pct}%) | desired: ₹{desired} | {status}")
        else:
            item["desired_price"] = None
            item["mrp"] = None
            item["drop_amount"] = None
            item["drop_pct"] = None
            item["hit_desired"] = False

    return decreased_items


# ─── Main Scanner ─────────────────────────────────────────

async def run_scan(cookie_filename="amazon_cookies.json", account_name="AMAZON") -> dict:
    """Full scan: open Amazon cart, extract alerts, compare, notify Telegram."""
    print("\n" + "=" * 60)
    print("🔍 AMAZON CART SCAN STARTED")
    print("=" * 60)

    # Load cookies
    cookies_path = os.path.join(DATA_DIR, cookie_filename)
    if not os.path.exists(cookies_path):
        print(f"❌ {cookie_filename} not found")
        return {"error": f"{cookie_filename} not found"}

    try:
        with open(cookies_path, "r") as f:
            raw_cookies = json.load(f)
        cookies = sanitize_cookies(raw_cookies)
        print(f"✅ Loaded {len(cookies)} cookies")
    except Exception as e:
        print(f"❌ Error reading cookies: {e}")
        return {"error": str(e)}

    # Launch browser (controlled by .env BROWSER_HEADLESS)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=BROWSER_HEADLESS,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context()
    page = await context.new_page()
    mode_label = "headless" if BROWSER_HEADLESS else "headful"
    print(f"✅ Browser launched ({mode_label})")

    try:
        # 1. Open Amazon
        await page.goto("https://www.amazon.in/", wait_until="domcontentloaded")
        print("✅ Amazon loaded")

        # 2. Inject cookies
        await context.add_cookies(cookies)
        await page.reload(wait_until="domcontentloaded")
        print("✅ Cookies applied & page reloaded")

        # 3. Check greeting
        greeting_elem = await page.query_selector("span#nav-link-accountList-nav-line-1")
        if not greeting_elem:
            print("❌ Not logged in — cookies may be expired")
            return {"error": "Invalid cookies or not logged in"}

        greeting = (await greeting_elem.inner_text()).strip()
        print(f"✅ Logged in as: {greeting}")

        # 4. Open cart
        await page.goto("https://www.amazon.in/cart", wait_until="domcontentloaded")
        print("✅ Cart page loaded")

        # 5. Extract cart alert
        cart_alert_elem = await page.query_selector("#sc-important-message-alert")
        if not cart_alert_elem:
            print("ℹ️  No cart alerts found — no price changes")
            return {"greeting": greeting, "decreased_items": []}

        cart_alert_html = await cart_alert_elem.inner_html()
        print(f"✅ Cart alert found ({len(cart_alert_html)} chars)")



        # 6. Parse price decreases
        print("\n📋 Parsing price decreases...")
        decreased_items = parse_cart_alert_html(cart_alert_html)
        print(f"Found {len(decreased_items)} decreased item(s)")

        if not decreased_items:
            print("ℹ️  No price decreases found")
            return {"greeting": greeting, "decreased_items": []}



        # 7. Compare with desired prices — only care about desired-price hits
        print("\n📊 Comparing with desired prices...")
        decreased_items = compare_with_desired_prices(decreased_items)

        hits     = [item for item in decreased_items if item.get("hit_desired")]
        non_hits = [item for item in decreased_items if not item.get("hit_desired")
                    and item.get("drop_amount") is not None]

        # Log non-hits to console only (no Telegram)
        for item in non_hits:
            desired_str = f'₹{item["desired_price"]}' if item["desired_price"] else "N/A"
            print(f'  🎯 {item["name"][:60]}: drop ₹{item["drop_amount"]} ({item["drop_pct"]}%) | desired: {desired_str} | ❌ above')

        # 8. Send Telegram alert ONLY for desired-price hits
        if hits:
            alert_lines = [f"🎯 <b>Amazon ({account_name.upper()}) — Target Price Hit!</b>\n"]
            for item in hits:
                desired_str = f'₹{item["desired_price"]}' if item["desired_price"] else "N/A"
                alert_lines.append(
                    f'✅ <a href="{item["link"]}">{item["name"]}</a>\n'
                    f'   ₹{item["old_price"]} → ₹{item["new_price"]} | Target: {desired_str}'
                )
                print(f'  ✅ TARGET HIT: {item["name"][:60]}: ₹{item["new_price"]} ≤ desired {desired_str}')
            await send_telegram_alert("\n\n".join(alert_lines), platform="AMAZON")
        else:
            print("  ℹ️  No items hit desired price — no Telegram alert sent")

        drop_count = len(decreased_items)
        hit_count  = len(hits)
        if BROWSER_CLOSE:
            await browser.close()
            await pw.stop()
            print("\n✅ SCAN COMPLETE — browser closed")
        else:
            print("\n✅ SCAN COMPLETE — browser left open")
        return {"greeting": greeting, "decreased_items": decreased_items}

    except Exception as e:
        print(f"❌ SCAN FAILED: {e}")
        return {"error": str(e)}
