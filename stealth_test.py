"""Test if headless mode is triggering bot detection."""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"

def main():
    ts_config = {}
    with sync_playwright() as p:
        # Try headless=False first (if supported) or just stick to headless=True with more realistic args
        try:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
        except Exception as e:
            print(f"Launch failed: {e}")
            return

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        
        # Add a script to hide webdriver
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = context.new_page()

        print("Loading page with stealth...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        page.wait_for_timeout(10000)

        # Get tsConfigContainer
        raw = page.evaluate("""
            () => {
                const el = document.getElementById('tsConfigContainer');
                return el ? (el.value || el.textContent || '') : '';
            }
        """)
        if raw and raw.strip():
            ts_config = json.loads(raw)
            print(f"vizql_root: {ts_config.get('vizql_root')}")
            print(f"sessionid: {ts_config.get('sessionid')}")

        browser_cookies = context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in browser_cookies}
        print(f"Cookies: {list(cookies_dict.keys())}")

        browser.close()

if __name__ == "__main__":
    main()
