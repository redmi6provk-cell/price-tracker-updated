"""
Amazon Cart Price Tracker — Standalone Scanner
Runs a scan immediately on start, then every SCAN_INTERVAL_MINUTES (default 15).

Usage:
  python main.py                 # run both Amazon + Myntra (default)
  python main.py --no-amazon     # skip Amazon, run Myntra only
  python main.py --no-myntra     # skip Myntra, run Amazon only
  python main.py --amazon-only   # same as --no-myntra
  python main.py --myntra-only   # same as --no-amazon
"""

import asyncio
import os
import sys
import time
import argparse
import random
from dotenv import load_dotenv

load_dotenv()

from app.amazon_scanner import run_scan
from app.myntra_scanner import myntra_price_check_raw

# ── Parse CLI flags ──────────────────────────────────────────
parser = argparse.ArgumentParser(description="Amazon & Myntra Price Tracker")
parser.add_argument("--no-amazon",   action="store_true", help="Skip Amazon scanner")
parser.add_argument("--no-myntra",   action="store_true", help="Skip Myntra scanner")
parser.add_argument("--amazon-only", action="store_true", help="Run Amazon scanner only")
parser.add_argument("--myntra-only", action="store_true", help="Run Myntra scanner only")
args = parser.parse_args()

RUN_AMAZON = not args.no_amazon and not args.myntra_only
RUN_MYNTRA = not args.no_myntra and not args.amazon_only


async def amazon_loop():
    accounts = [
        {"file": "amazon_cookies.json", "name": "Main Account"}
    ]
    while True:
        for acc in accounts:
            start = time.time()
            print("\n" + "=" * 60)
            print(f"🛒 Starting Amazon Cart Check ({acc['name']})...")
            try:
                amz_result = await run_scan(cookie_filename=acc["file"], account_name=acc["name"])
                if "error" in amz_result:
                    print(f"\n⚠️  Amazon Scan ({acc['name']}) returned error: {amz_result['error']}")
                else:
                    count = len(amz_result.get("decreased_items", []))
                    hits = sum(1 for i in amz_result.get("decreased_items", []) if i.get("hit_desired"))
                    print(f"\n📊 Amazon Summary ({acc['name']}): {count} price drop(s), {hits} target hit(s)")
            except Exception as e:
                print(f"\n💥 Unexpected Amazon error ({acc['name']}): {e}")

        wait_minutes = random.uniform(15, 20)
        wait_seconds = wait_minutes * 60
        print(f"\n⏳ Amazon: Next scan in {int(wait_minutes)}m {int(wait_seconds % 60)}s ...\n")
        await asyncio.sleep(wait_seconds)

async def myntra_loop():
    accounts = ["new_", "old_"]
    while True:
        for account in accounts:
            start = time.time()
            account_name = account.strip('_').upper()
            print("\n" + "=" * 60)
            print(f"🛍️ Starting Myntra Price Check ({account_name} ACCOUNT)...")
            try:
                myn_result = await myntra_price_check_raw(account_prefix=account)
                if "error" in myn_result:
                    print(f"\n⚠️  Myntra Scan ({account_name}) returned error: {myn_result['error']}")
                else:
                    results = myn_result.get("scanned_products", [])
                    scanned_count = len([r for r in results if r.get("pdp_price") is not None])
                    hits = len([r for r in results if r.get("hit_target")])
                    print(f"\n📊 Myntra Summary ({account_name}): Scanned {scanned_count} item(s), {hits} target hit(s)")
            except Exception as e:
                print(f"\n💥 Unexpected Myntra error ({account_name}): {e}")

            wait_minutes = random.uniform(5, 10)
            wait_seconds = wait_minutes * 60
            print(f"\n⏳ Myntra: Next account scan in {int(wait_minutes)}m {int(wait_seconds % 60)}s ...\n")
            await asyncio.sleep(wait_seconds)

async def main():
    print("=" * 60)
    print("🚀 Amazon & Myntra Price Tracker")
    active = []
    if RUN_AMAZON: active.append("Amazon")
    if RUN_MYNTRA: active.append("Myntra")
    print(f"   Active scanners: {', '.join(active) if active else 'None'}")
    print("=" * 60)

    tasks = []
    if RUN_AMAZON:
        tasks.append(amazon_loop())
    if RUN_MYNTRA:
        tasks.append(myntra_loop())

    if not tasks:
        print("⚠️  No scanners selected. Use --amazon-only, --myntra-only, or run without flags for both.")
        return

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
