"""Intercept the real Tableau bootstrap with Playwright.

Strategy:
1. Launch headless Chromium via Playwright
2. Navigate to the Tableau viz URL
3. Intercept the bootstrapSession POST response (the real data request)
4. Also read the tsConfigContainer once JS populates it
5. Print what we find
"""
import json
import re
import sys
from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"


def main():
    captured_responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Intercept network requests to find the bootstrapSession call
        def on_response(response):
            url = response.url
            if "bootstrapSession" in url or "get-summary-data" in url or "vizql" in url:
                status = response.status
                content_type = response.headers.get("content-type", "")
                print(f"  [NET] {status} {content_type[:40]} {url[:120]}")
                captured_responses.append({
                    "url": url,
                    "status": status,
                    "content_type": content_type,
                })

        page.on("response", on_response)

        print(f"Navigating to: {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        print(f"Page loaded. Title: {page.title()}")

        # Wait a bit for any late requests
        page.wait_for_timeout(5000)

        # Check if tsConfigContainer got populated by JS
        print("\n--- tsConfigContainer ---")
        ts_config_text = page.evaluate("""
            () => {
                const el = document.getElementById('tsConfigContainer');
                return el ? el.value || el.textContent : null;
            }
        """)
        if ts_config_text and ts_config_text.strip():
            print(f"  Content length: {len(ts_config_text)} chars")
            try:
                config = json.loads(ts_config_text)
                print(f"  Parsed keys: {list(config.keys())[:15]}")
                for key in ["vizql_root", "sessionid", "sheetId", "siteRoot"]:
                    if key in config:
                        print(f"  {key}: {config[key]}")
                with open("output/ts_config_live.json", "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                print("  Saved to output/ts_config_live.json")
            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")
                print(f"  Raw (first 300): {ts_config_text[:300]}")
        else:
            print("  Still empty even after JS execution")

        # Print captured network calls
        print(f"\n--- Captured {len(captured_responses)} vizql responses ---")
        for resp in captured_responses:
            print(f"  {resp['status']} {resp['url'][:150]}")

        # Try to get the bootstrapSession response body
        bootstrap_data = None
        for resp_info in captured_responses:
            if "bootstrapSession" in resp_info["url"]:
                print(f"\n--- Bootstrap response found: {resp_info['url'][:120]} ---")
                # We can't retroactively get the body from the captured info
                # Let's try a different approach - navigate again and capture body
                break

        browser.close()

    # If we found bootstrap calls, we know the real endpoint pattern
    if captured_responses:
        print("\n--- Summary ---")
        print("Real Tableau endpoints discovered:")
        for resp in captured_responses:
            print(f"  {resp['url']}")


if __name__ == "__main__":
    main()
