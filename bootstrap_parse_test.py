import json
import re
import sys
import io
import pandas as pd
from playwright.sync_api import sync_playwright

from tableauscraper.TableauWorkbook import TableauWorkbook
from tableauscraper import utils

def run():
    url = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"
    bootstrap_body = ""

    print("Bootstrapping via Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        page = context.new_page()

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
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        for _ in range(45):
            page.wait_for_timeout(1000)
            if bootstrap_body:
                page.wait_for_timeout(2000)
                break
        
        browser.close()

    if not bootstrap_body:
        print("Failed to capture bootstrap_body.")
        return

    print(f"Captured bootstrap_body of length {len(bootstrap_body)}")

    match = re.search(r"\d+;({.*})\d+;({.*})", bootstrap_body, re.MULTILINE)
    if not match:
        print("Could not match \d+;{...}\d+;{...} in bootstrap_body.")
        return

    info = json.loads(match.group(1))
    data = json.loads(match.group(2))

    class DummyTS:
        def __init__(self, info, data):
            self.info = info
            self.data = data
            self.logger = None
            if "presModelMap" in self.data["secondaryInfo"]:
                pm = self.data["secondaryInfo"]["presModelMap"]
                self.dataSegments = pm["dataDictionary"]["presModelHolder"]["genDataDictionaryPresModel"]["dataSegments"]
            else:
                self.dataSegments = {}
            self.parameters = utils.getParameterControlInput(self.info)
            self.dashboard = self.info["sheetName"]
            self.filters = utils.getFiltersForAllWorksheet(self.logger, self.data, self.info, self.dashboard)

    from tableauscraper import dashboard
    
    ts = DummyTS(info, data)
    parsedWorksheets = dashboard.getWorksheets(ts, data, info)
    wb = TableauWorkbook(ts, data, info, parsedWorksheets)
    
    ws_names = wb.getWorksheetNames()
    print(f"Worksheets found: {ws_names}")
    for name in ws_names:
        ws = wb.getWorksheet(name)
        df = ws.data
        print(f"  {name}: {len(df)} rows")
        if len(df) > 0:
            print(f"    Columns: {list(df.columns)}")

if __name__ == "__main__":
    run()
