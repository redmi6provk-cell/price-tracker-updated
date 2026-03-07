import asyncio
import os
import json
import re
import sys
from typing import Callable, Any
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from app.notifications import send_telegram_alert

load_dotenv()

# ─── Browser config from .env ──────────────────────────────
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").strip().lower() == "true"
BROWSER_CLOSE    = os.getenv("BROWSER_CLOSE",    "false").strip().lower() == "true"


async def run_with_playwright(task_callback: Callable, close_browser: bool | None = None) -> Any:
    """Launch Playwright browser. close_browser defaults to BROWSER_CLOSE from .env."""
    should_close = BROWSER_CLOSE if close_browser is None else close_browser
    headless     = BROWSER_HEADLESS
    mode_label   = "headless" if headless else "headful"
    print(f"[Playwright] Launching Chromium ({mode_label}, incognito)...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless,
        channel="chromium",
        args=[
            "--incognito",
            "--disable-http2",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--lang=en-IN,en",
        ]
    )
    # Realistic user-agent so Myntra treats us like a normal Chrome user
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-IN",
        viewport={"width": 1366, "height": 768},
    )
    # Remove the 'webdriver' property that bots check for
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = await context.new_page()

    # Intercept and block unnecessary resources to prevent timeouts
    async def block_resources(route):
        request = route.request
        # Block heavy media and tracking domains
        if request.resource_type in ["image", "media", "font"]:
            await route.abort()
        elif "google-analytics.com" in request.url or "googletagmanager.com" in request.url:
            await route.abort()
        elif "criteo.com" in request.url or "adsystem" in request.url or "doubleclick.net" in request.url:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", block_resources)

    print("[Playwright] Browser ready (incognito + adblocker)")

    try:
        result = await task_callback(context, page)
        print("[Playwright] Task callback completed")
        return result
    except Exception as e:
        print(f"[Playwright] Error in task callback: {e}")
        raise
    finally:
        if should_close:
            await browser.close()
            await pw.stop()
            print("[Playwright] Browser closed")
        else:
            print("[Playwright] Browser left open for debugging")


# =====================================================
# 🔹 PLAYWRIGHT LOOP (WINDOWS SAFE)
# =====================================================

def get_playwright_loop():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


# =====================================================
# 🔹 COMMON PLAYWRIGHT HANDLER
# =====================================================

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
        # expirationDate -> expires
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





# =====================================================
# 🔹 MYNTRA : PRODUCT PRICE SCAN
# =====================================================

async def myntra_price_check_raw(account_prefix: str = "") -> dict:
    data_dir = os.path.dirname(os.path.dirname(__file__))
    cookies_path = os.path.join(data_dir, "data", f"{account_prefix}myntra_cookies.json")
    products_path = os.path.join(data_dir, "data", f"{account_prefix}myntra_products.json")

    print(f"[Myntra] Step 0: Cookies path = {cookies_path}")

    if not os.path.exists(cookies_path):
        print("[Myntra] ERROR: myntra_cookies.json not found")
        return {"error": "myntra_cookies.json not found"}

    # Load cookies
    try:
        with open(cookies_path, "r") as f:
            raw_cookies = json.load(f)

        cookies = sanitize_cookies(raw_cookies)
        print(f"[Myntra] Step 0: Loaded {len(cookies)} cookies")
    except Exception as e:
        print(f"[Myntra] ERROR reading cookies: {e}")
        return {"error": f"Error reading cookies: {e}"}

    # Load products from flat JSON array
    products = []
    try:
        if os.path.exists(products_path):
            with open(products_path, "r") as f:
                products = json.load(f)
            if not isinstance(products, list):
                products = []
            
            # Ensure every product has an id
            import uuid
            for p in products:
                if "id" not in p:
                    p["id"] = str(uuid.uuid4())
                # *** FRESH START: reset lowest_notified_price every run ***
                # This ensures every app restart sends notifications for all current hits,
                # regardless of what was previously saved. "new start means new."
                p["lowest_notified_price"] = None
                
    except Exception as e:
        print(f"[Myntra] ERROR reading products: {e}")
        return {"error": f"Error reading products: {e}"}

    print(f"[Myntra] Step 0: Found {len(products)} tracked products")

    if not products:
        print("[Myntra] No products to scan")
        return {"message": "No Myntra products tracked"}

    async def myntra_flow(context, page):
        # 1️⃣ Open Myntra
        print("[Myntra] Step 1: Opening https://www.myntra.com/ ...")
        await page.goto("https://www.myntra.com/", wait_until="domcontentloaded")
        print("[Myntra] Step 1: ✅ Myntra loaded")

        # 2️⃣ Load cookies
        print("[Myntra] Step 2: Adding cookies to context...")
        await context.add_cookies(cookies)
        print("[Myntra] Step 2: ✅ Cookies added")

        # 3️⃣ Reload
        print("[Myntra] Step 3: Reloading page...")
        await page.reload(wait_until="domcontentloaded")
        print("[Myntra] Step 3: ✅ Page reloaded")

        results = []
        from datetime import datetime
        scan_time = datetime.utcnow().isoformat()

        def _parse_price(text):
            """Clean price text and return float or None."""
            if not text:
                return None
            clean = text.replace("\u20b9", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
            m = re.search(r"[\d]+\.?\d*", clean)
            if m:
                try:
                    return float(m.group())
                except:
                    pass
            return None

        # 4️⃣ Scan each product
        for i, product in enumerate(products):
            # Random delay between products to avoid rate limiting / bot detection
            if i > 0:
                import random as _random
                wait_s = _random.randint(8, 15)
                print(f"  [Myntra] Waiting {wait_s}s before next product...")
                await page.wait_for_timeout(wait_s * 1000)

            url = product.get("url")
            if not url:
                print(f"[Myntra] Product {i+1} — skipped (no URL)")
                continue

            print(f"\n[Myntra] Product {i+1}/{len(products)} — Opening {url}")
            try:
                # Fire the request and don't strictly wait for perfect completion
                # "commit" means we received headers, but Myntra sometimes hangs even there
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000, referer="https://www.myntra.com/")
                except Exception as e:
                    # If it times out, the HTML might still be loaded enough to parse prices
                    print(f"  [Myntra] ⚠️ Load timeout ({str(e).splitlines()[0]}), attempting to scrape anyway...")
                
                # Give the JS an extra moment to render prices in the DOM
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  [Myntra] ⚠️ Failed to load {url} (Error: {e}) - Skipping product")
                product["scan_status"] = "failed"
                product["last_scanned_at"] = scan_time
                results.append({
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "url": url,
                    "target_price": None,
                    "pdp_price": None,
                    "mrp": None,
                    "best_price": None,
                    "image": product.get("image"),
                    "drop_amount": None,
                    "drop_pct": None,
                    "hit_target": False,
                    "scan_status": "failed",
                })
                continue

            # \u2500 Extract PDP Price (selling price) \u2500\u2500\u2500\u2500\u2500
            pdp_price = None
            pdp_el = await page.query_selector(".pdp-price strong")
            if pdp_el:
                pdp_text = await pdp_el.inner_text()
                pdp_price = _parse_price(pdp_text)
                print(f"  [PDP] Price: {pdp_price} (raw: '{pdp_text}')")
            else:
                print("  [PDP] Price element not found")

            # \u2500 Extract MRP \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
            mrp = None
            mrp_el = await page.query_selector(".pdp-mrp s")
            if mrp_el:
                mrp_text = await mrp_el.inner_text()
                mrp = _parse_price(mrp_text)
                print(f"  [MRP] Price: {mrp} (raw: '{mrp_text}')")
            else:
                print("  [MRP]  element not found")

            # ─ Extract Best Price ────────────
            best_price = None
            
            # Find all offer titles and exclusively look for the "Best Price:" one
            offer_titles = await page.query_selector_all(".pdp-offers-offerTitle b")
            for title_el in offer_titles:
                title_text = await title_el.inner_text()
                # Strict check for "Best Price"
                if "Best Price" in title_text:
                    best_price = _parse_price(title_text)
                    print(f"  [Best] Price: {best_price} (raw: '{title_text}')")
                    break
                    
            if best_price is None:
                print("  [Best] Price element not found (or 'Best Price:' text missing)")

            # ─ Compare best_price with target (desired_price) ─
            raw_target = product.get("desired_price")
            try:
                target_price = float(raw_target) if raw_target is not None else None
            except:
                target_price = None
                
            hit_target = False
            drop_amount = None
            drop_pct = None
            compare_price = best_price if best_price is not None else pdp_price

            # Check if this should trigger an immediate alert
            trigger_immediate_alert = False

            lowest_notified = product.get("lowest_notified_price")
            if lowest_notified is not None:
                try:
                    lowest_notified = float(lowest_notified)
                except:
                    lowest_notified = None

            if compare_price is not None and target_price is not None and target_price > 0:
                drop_amount = round(target_price - compare_price, 2)
                drop_pct = round((drop_amount / target_price) * 100, 1)
                
                # It's at or below our desired price
                if compare_price <= target_price:
                    hit_target = True
                    
                    # Logic for immediate alert
                    if lowest_notified is None or compare_price < lowest_notified:
                        trigger_immediate_alert = True
                        product["lowest_notified_price"] = compare_price
                        print(f"  [Alert] 🔔 NEW target hit! {compare_price} vs target {target_price}")
                    else:
                        print(f"  [Alert] ℹ️ Already hit and notified at {lowest_notified}. No new alert.")
                        
                else:
                    # Price went back above target, reset the flag so they can be alerted again if it drops again
                    if lowest_notified is not None:
                        product["lowest_notified_price"] = None
                        print(f"  [Reset] price {compare_price} is above target {target_price}, resetting tracker.")

                status = "[HIT]" if hit_target else "[above]"
                print(f"  [Compare] Best {compare_price} vs Target {target_price} | diff {drop_amount} ({drop_pct}%) | {status}")

            # ─ Update product in DB ───────────
            product["pdp_price"] = pdp_price
            product["best_price"] = best_price
            product["mrp"] = mrp
            product["last_scanned_price"] = compare_price # The final calculated price used for comparison
            product["scan_status"] = "scanned" if compare_price is not None else "failed"
            product["last_scanned_at"] = scan_time

            if compare_price is not None:
                if "prices" not in product:
                    product["prices"] = []
                product["prices"].append({
                    "price": compare_price,
                    "timestamp": scan_time,
                })

            results.append({
                "id": product.get("id"),
                "name": product.get("name"),
                "url": url,
                "target_price": target_price,
                "pdp_price": pdp_price,
                "mrp": mrp,
                "best_price": best_price,
                "image": product.get("image"),
                "drop_amount": drop_amount,
                "drop_pct": drop_pct,
                "hit_target": hit_target,
                "trigger_immediate": trigger_immediate_alert,
                "scan_status": product["scan_status"],
            })

        # Save product updates (prices, scan_status, lowest_notified_price) back to file
        try:
            with open(products_path, "w") as f:
                json.dump(products, f, indent=4)
            print("[Myntra] ✅ Updated myntra_products.json with latest scan data")
        except Exception as e:
            print(f"[Myntra] ⚠️ Failed to save myntra_products.json: {e}")

        # 1. SEND IMMEDIATE ALERTS
        new_hits = [r for r in results if r.get("trigger_immediate")]
        if new_hits:
            print(f"[Myntra] Sending immediate Telegram alert for {len(new_hits)} NEW target hit(s)...")
            lines = ["🛍️ <b>Myntra Price Alert — New Lowest Price!</b>\n"]
            for r in new_hits:
                bp = r["best_price"] if r["best_price"] is not None else r["pdp_price"]
                lines.append(
                    f'🟢 <a href="{r["url"]}">{r["name"]}</a>\n'
                    f'   🔥 Price: ₹{bp}\n'
                    f'   🎯 Target: ₹{r["target_price"]} | Drop: ₹{r["drop_amount"]} ({r["drop_pct"]}%)\n'
                )
            await send_telegram_alert("\n\n".join(lines), platform=f"{account_prefix.upper()}MYNTRA")
        else:
            print("[Myntra] No NEW immediate alerts triggered — skipping instant alert")

        # 2. CHECK & SEND TWICE DAILY DIGEST (12:01 AM and 7:00 AM)
        # Digests only fire within a time window — not at any time just because state is stale
        from datetime import datetime, time as datetime_time
        import pytz
        
        tz = pytz.timezone('Asia/Kolkata')
        now_dt = datetime.now(tz)
        today_str = now_dt.strftime("%Y-%m-%d")
        now_time = now_dt.time()
        
        digest_state_path = os.path.join(data_dir, "data", f"{account_prefix}myntra_digest_state.json")
        digest_state = {"last_1201am": None, "last_0700am": None}
        
        try:
            if os.path.exists(digest_state_path):
                with open(digest_state_path, "r") as f:
                    digest_state = json.load(f)
        except Exception as e:
            print(f"[Myntra] Could not read digest state (will create new): {e}")

        all_hits = [r for r in results if r.get("hit_target")]
        
        send_digest = False
        digest_title = ""

        # Midnight window: 00:01 AM – 02:00 AM only
        in_midnight_window = datetime_time(0, 1) <= now_time <= datetime_time(2, 0)
        # Morning window: 07:00 AM – 09:00 AM only
        in_morning_window = datetime_time(7, 0) <= now_time <= datetime_time(9, 0)
        
        if in_midnight_window and digest_state.get("last_1201am") != today_str:
            send_digest = True
            digest_title = "Midnight (12:01 AM) Digest"
            digest_state["last_1201am"] = today_str
        elif in_morning_window and digest_state.get("last_0700am") != today_str:
            send_digest = True
            digest_title = "Morning (7:00 AM) Digest"
            digest_state["last_0700am"] = today_str
        else:
            print(f"[Myntra] Digest check: not in a digest window, skipping (current IST time: {now_time.strftime('%H:%M')})")

        if send_digest and all_hits:
            print(f"[Myntra] Sending {digest_title} for {len(all_hits)} active targets...")
            lines = [f"📅 <b>Myntra Price Tracker — {digest_title}</b>\n"]
            lines.append(f"<i>Active Deals Below Desired Price:</i>\n")
            for r in all_hits:
                bp = r["best_price"] if r["best_price"] is not None else r["pdp_price"]
                lines.append(
                    f'✅ <a href="{r["url"]}">{r["name"]}</a>\n'
                    f'   Price: ₹{bp} (Target: ₹{r["target_price"]})'
                )
            await send_telegram_alert("\n\n".join(lines), platform=f"{account_prefix.upper()}MYNTRA")
            
            # Save state
            try:
                with open(digest_state_path, "w") as f:
                    json.dump(digest_state, f, indent=4)
            except Exception as e:
                print(f"[Myntra] ⚠️ Failed to save digest state: {e}")

        print(f"\n[Myntra] Done — scanned {len(results)} products, {len(all_hits)} total hit target")
        return {"scanned_products": results}

    return await run_with_playwright(myntra_flow)


def myntra_price_check(account_prefix: str = "") -> dict:
    print(f"[Myntra] === Starting myntra_price_check ({account_prefix}) ===")
    loop = get_playwright_loop()
    try:
        result = loop.run_until_complete(myntra_price_check_raw(account_prefix))
        print(f"[Myntra] === Result keys: {list(result.keys())} ===")
    except Exception as e:
        print(f"[Myntra] === EXCEPTION: {e} ===")
        result = {"error": str(e)}
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
    return result