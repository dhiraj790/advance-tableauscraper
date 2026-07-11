"""Debug script – see what tableauscraper receives from the URL."""
import sys
import traceback
from tableauscraper import TableauScraper as TS

url = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"
print(f"Testing URL: {url}\n")

ts = TS()
try:
    ts.loads(url)
    wb = ts.getWorkbook()
    names = wb.getWorksheetNames()
    print(f"Worksheets: {names}")
    for name in names:
        ws = wb.getWorksheet(name)
        print(f"\n{name}: {ws.data.shape}")
        print(ws.data.head(5))
except Exception as exc:
    print(f"Error: {exc}")
    traceback.print_exc()

    # Try alternative URL formats
    print("\n--- Trying alternative URL formats ---\n")
    alt_urls = [
        "https://public.tableau.com/views/_17255232362800/sheet11",
        "https://public.tableau.com/views/_17255232362800/1",
    ]
    for alt in alt_urls:
        print(f"Trying: {alt}")
        try:
            ts2 = TS()
            ts2.loads(alt)
            wb2 = ts2.getWorkbook()
            names2 = wb2.getWorksheetNames()
            print(f"  ✔ Worksheets: {names2}")
            for name in names2:
                ws = wb2.getWorksheet(name)
                print(f"    {name}: {ws.data.shape}")
                print(ws.data.head(3))
            break
        except Exception as e2:
            print(f"  ✘ {e2}")
