"""
Amazon Cart Price Tracker — Standalone Scanner
Runs a scan immediately on start, then every SCAN_INTERVAL_MINUTES (default 15).
"""

import asyncio
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

from app.scanner import run_scan

INTERVAL = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))


async def main():
    print("=" * 60)
    print("🚀 Amazon Cart Price Tracker")
    print(f"   Scan interval: every {INTERVAL} minutes")
    print("=" * 60)

    while True:
        start = time.time()
        try:
            result = await run_scan()
            if "error" in result:
                print(f"\n⚠️  Scan returned error: {result['error']}")
            else:
                count = len(result.get("decreased_items", []))
                hits = sum(1 for i in result.get("decreased_items", []) if i.get("hit_desired"))
                print(f"\n📊 Summary: {count} price drop(s), {hits} target hit(s)")
        except Exception as e:
            print(f"\n💥 Unexpected error: {e}")

        elapsed = time.time() - start
        wait = max(0, INTERVAL * 60 - elapsed)
        print(f"\n⏳ Next scan in {int(wait // 60)}m {int(wait % 60)}s ...\n")
        await asyncio.sleep(wait)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
