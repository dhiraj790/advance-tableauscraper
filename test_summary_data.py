"""Try to get underlying/summary data via the VizQL commands API.

The viz is server-rendered (tiles), so the bootstrap doesn't contain 
inline data. We need to use the session to call get-summary-data or 
get-underlying-data commands.
"""
import json
import re
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"


def main():
    ts_config = {}
    cookies_dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # Wait for the page to fully load including bootstrap
        bootstrap_captured = False

        def on_response(response):
            nonlocal bootstrap_captured
            if "bootstrapSession" in response.url and response.status == 200:
                bootstrap_captured = True

        page.on("response", on_response)

        print("Loading page...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        for _ in range(30):
            page.wait_for_timeout(1000)
            if bootstrap_captured:
                page.wait_for_timeout(3000)
                break

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

        # Get cookies from the browser context
        browser_cookies = context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in browser_cookies}
        print(f"Cookies: {list(cookies_dict.keys())}")

        browser.close()

    if not ts_config:
        print("ERROR: no tsConfig")
        return

    vizql_root = ts_config["vizql_root"]
    session_id = ts_config["sessionid"]
    host = "https://public.tableau.com"

    # Create a requests session with the browser cookies
    s = requests.Session()
    s.cookies.update(cookies_dict)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*",
        "X-Tsi-Active-Tab": ts_config.get("sheetId", ""),
    })

    # List of worksheets to try
    worksheets = [
        # Hebrew names from the dashboard
        "\u05d1\u05d7\u05d9\u05e8\u05ea \u05db\u05ea\u05d5\u05d1\u05ea",  # בחירת כתובת
        "\u05de\u05e4\u05ea \u05db\u05ea\u05d5\u05d1\u05ea",             # מפת כתובת
        "100m", "200m", "300m", "500m", "1000m", "1500m",
    ]
    dashboard_name = ts_config.get("sheetId", "sheet11")
    
    # Read the sheetName from the config
    sheet_name = "\u05d7\u05d9\u05e4\u05d5\u05e9 \u05dc\u05e4\u05d9 \u05db\u05ea\u05d5\u05d1\u05ea"  # חיפוש לפי כתובת

    print(f"\nDashboard: {sheet_name}")
    print(f"\nTrying get-summary-data for each worksheet...\n")

    for ws_name in worksheets:
        print(f"--- Worksheet: {ws_name} ---")

        # Try get-summary-data
        summary_url = f"{host}{vizql_root}/sessions/{session_id}/commands/tabdoc/get-summary-data"
        payload = (
            ("maxRows", (None, "200")),
            ("visualIdPresModel", (None, json.dumps({
                "worksheet": ws_name,
                "dashboard": sheet_name,
                "flipboardZoneId": 0,
                "storyPointId": 0,
            }))),
        )

        try:
            r = s.post(summary_url, files=payload, timeout=30)
            print(f"  Status: {r.status_code}")
            print(f"  Content-Type: {r.headers.get('Content-Type', '?')}")

            if r.status_code == 200:
                try:
                    resp_json = r.json()
                    # Look for data in the response
                    if "vqlCmdResponse" in resp_json:
                        cmd = resp_json["vqlCmdResponse"]
                        print(f"  vqlCmdResponse keys: {list(cmd.keys())[:10]}")
                        layout_status = cmd.get("layoutStatus")
                        print(f"  layoutStatus: {layout_status}")
                        
                        if "cmdResultList" in cmd:
                            for i, result in enumerate(cmd["cmdResultList"]):
                                print(f"  cmdResult[{i}] keys: {list(result.keys())[:10]}")
                                if "commandReturn" in result:
                                    cr = result["commandReturn"]
                                    print(f"    commandReturn keys: {list(cr.keys())[:10]}")
                                    if "summaryDataTable" in cr:
                                        sdt = cr["summaryDataTable"]
                                        print(f"    summaryDataTable keys: {list(sdt.keys())[:10]}")
                                        cols = sdt.get("columns", [])
                                        print(f"    columns ({len(cols)}): {[c.get('fieldCaption', '?') for c in cols[:10]]}")
                                        if "data" in sdt:
                                            data_rows = sdt["data"]
                                            print(f"    data rows: {len(data_rows)}")
                                            if data_rows:
                                                print(f"    first row: {data_rows[0][:5] if len(data_rows[0]) > 5 else data_rows[0]}")
                    else:
                        # Check for error messages
                        keys = list(resp_json.keys())[:10]
                        print(f"  Response keys: {keys}")
                        
                except json.JSONDecodeError:
                    print(f"  Not JSON. First 200 chars: {r.text[:200]}")
            else:
                print(f"  Error response: {r.text[:200]}")

        except Exception as e:
            print(f"  Error: {e}")

        print()


if __name__ == "__main__":
    main()
