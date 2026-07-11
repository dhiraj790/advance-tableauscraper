"""Diagnostic: inspect the bootstrap data to find where the actual data is stored."""
import json
import re
import sys
import os
from pathlib import Path
from urllib.parse import urlparse

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright
from tableauscraper import TableauScraper as TS
from tableauscraper import dashboard
from tableauscraper import utils as ts_utils

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"
OUTPUT = Path("output")
OUTPUT.mkdir(exist_ok=True)


def get_bootstrap():
    """Load page via Playwright and capture bootstrap."""
    bootstrap_body = ""
    ts_config = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        ).new_page()

        def on_response(response):
            nonlocal bootstrap_body
            if "bootstrapSession" in response.url and response.status == 200:
                try:
                    body = response.text()
                    if len(body) > len(bootstrap_body):
                        bootstrap_body = body
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        for _ in range(30):
            page.wait_for_timeout(1000)
            if bootstrap_body:
                page.wait_for_timeout(2000)
                break

        raw = page.evaluate("""
            () => {
                const el = document.getElementById('tsConfigContainer');
                return el ? (el.value || el.textContent || '') : '';
            }
        """)
        if raw and raw.strip():
            ts_config = json.loads(raw)

        browser.close()

    return ts_config, bootstrap_body


def main():
    print("Fetching bootstrap data via Playwright...\n")
    ts_config, bootstrap_body = get_bootstrap()

    print(f"tsConfig keys: {list(ts_config.keys())}")
    print(f"Bootstrap body length: {len(bootstrap_body)}")

    # Parse the bootstrap
    match = re.search(r"\d+;({.*})\d+;({.*})", bootstrap_body, re.MULTILINE)
    if not match:
        print("ERROR: Could not parse bootstrap body")
        print(f"First 500 chars: {bootstrap_body[:500]}")
        return

    info = json.loads(match.group(1))
    data = json.loads(match.group(2))

    # Save full JSON for analysis
    with open(OUTPUT / "bootstrap_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    with open(OUTPUT / "bootstrap_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\ninfo keys: {list(info.keys())}")
    print(f"data keys: {list(data.keys())}")

    # Inspect worksheets in the info
    print(f"\nsheetName: {info.get('sheetName')}")
    print(f"publishedSheetsInfo:")
    for sheet in info.get("publishedSheetsInfo", []):
        print(f"  - {sheet}")

    # Look at the workbookPresModel / presModelMap
    secondary = data.get("secondaryInfo", {})
    print(f"\nsecondaryInfo keys: {list(secondary.keys())}")

    if "presModelMap" in secondary:
        pmm = secondary["presModelMap"]
        print(f"\npresModelMap keys: {list(pmm.keys())}")

        # Check dataDictionary
        if "dataDictionary" in pmm:
            dd = pmm["dataDictionary"]
            print(f"\ndataDictionary keys: {list(dd.keys())}")
            dd_pm = dd.get("presModelHolder", {}).get("genDataDictionaryPresModel", {})
            print(f"genDataDictionaryPresModel keys: {list(dd_pm.keys())}")
            segments = dd_pm.get("dataSegments", {})
            print(f"dataSegments count: {len(segments)}")
            for seg_key in list(segments.keys())[:3]:
                seg = segments[seg_key]
                print(f"\n  segment '{seg_key}' keys: {list(seg.keys()) if isinstance(seg, dict) else type(seg)}")
                if isinstance(seg, dict):
                    for col_key in list(seg.keys())[:5]:
                        col = seg[col_key]
                        if isinstance(col, dict):
                            print(f"    {col_key}: keys={list(col.keys())[:5]}")
                            data_type = col.get("dataType")
                            values = col.get("dataValues", [])
                            print(f"      dataType={data_type}, #values={len(values)}")
                            if values:
                                print(f"      first 3 values: {values[:3]}")

        # Check vizDataModel
        if "vizDataModel" in pmm:
            vdm = pmm["vizDataModel"]
            print(f"\nvizDataModel keys: {list(vdm.keys())}")

    # Now try with tableauscraper to see worksheets
    print("\n\n--- Using tableauscraper to list worksheets ---")
    scraper = TS()
    uri = urlparse(URL)
    scraper.host = f"{uri.scheme}://{uri.netloc}"
    scraper.tableauData = ts_config
    scraper.info = info
    scraper.data = data
    scraper.dashboard = info.get("sheetName", "")

    if "presModelMap" in secondary:
        pres = secondary["presModelMap"]
        scraper.dataSegments = (
            pres.get("dataDictionary", {})
            .get("presModelHolder", {})
            .get("genDataDictionaryPresModel", {})
            .get("dataSegments", {})
        )

    wb = dashboard.getWorksheets(scraper, scraper.data, scraper.info)
    names = wb.getWorksheetNames()
    print(f"Worksheet names: {names}")

    for name in names:
        try:
            ws = wb.getWorksheet(name)
            df = ws.data
            print(f"\n  '{name}': {df.shape}")
            if not df.empty:
                print(f"    Columns: {list(df.columns)}")
                print(f"    First row: {dict(df.iloc[0])}")
        except Exception as e:
            print(f"\n  '{name}': ERROR - {e}")

    # Also try looking at the data model directly
    print("\n\n--- Inspecting data model for map data ---")
    if "presModelMap" in secondary:
        pmm = secondary["presModelMap"]
        for key in pmm:
            print(f"\npresModelMap['{key}'] type={type(pmm[key]).__name__}")
            if isinstance(pmm[key], dict):
                sub_keys = list(pmm[key].keys())[:5]
                print(f"  sub-keys: {sub_keys}")


if __name__ == "__main__":
    main()
