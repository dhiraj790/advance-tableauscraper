import json
from tableauscraper import TableauScraper

url = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"

def main():
    ts = TableauScraper()
    ts.loads(url)
    
    print(f"vizql_root: {ts.vizql_root}")
    print(f"session_id: {ts.session_id}")
    print(f"Cookies: {list(ts.session.cookies.keys())}")
    
    wb = ts.getWorkbook()
    ws_names = wb.getWorksheetNames()
    print(f"Worksheets: {ws_names}")
    
    # Try calling get-summary-data using ts.session
    host = "https://public.tableau.com"
    for ws_name in ws_names:
        print(f"\n--- {ws_name} ---")
        api_url = f"{host}{ts.vizql_root}/sessions/{ts.session_id}/commands/tabdoc/get-summary-data"
        payload = (
            ("maxRows", (None, "10000")),
            ("visualIdPresModel", (None, json.dumps({
                "worksheet": ws_name,
                "dashboard": ts.dashboard,
                "flipboardZoneId": 0,
                "storyPointId": 0,
            }))),
        )
        
        try:
            r = ts.session.post(api_url, files=payload, timeout=30)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                resp = r.json()
                cmd = resp.get("vqlCmdResponse", {})
                for result in cmd.get("cmdResultList", []):
                    cr = result.get("commandReturn", {})
                    sdt = cr.get("summaryDataTable", {})
                    if sdt:
                        cols = [c.get("fieldCaption") for c in sdt.get("columns", [])]
                        rows = sdt.get("data", [])
                        print(f"  Extracted {len(rows)} rows, columns: {cols}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
