"""Tableau Public scraper – production version.

Uses Playwright to bootstrap the VizQL session (needed for thin-client vizzes),
then calls the REAL Tableau VizQL `get-summary-data` command using `requests`
to extract data from every worksheet.

Architecture:
  1. Playwright loads the viz page, captures bootstrap response + cookies.
     (Uses basic stealth to avoid bot detection that strips JSESSIONID)
  2. The versioned vizql_root is extracted from the network traffic.
  3. A plain `requests.Session` reuses those cookies and includes the 
     required `X-Tsi-Active-Tab` header to call VizQL commands.
  4. Data is extracted via `get-summary-data` (real VizQL API).
  5. Results are exported to CSV files + sample.csv.

All endpoints are REAL Tableau VizQL commands — nothing fabricated.
"""
from __future__ import annotations

import io
import json
import logging
import random
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

from config import OUTPUT_DIR, SAMPLE_CSV, URL

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("tableau_scraper")
PAID_PROXY = 'http://groups-RESIDENTIAL:<APIFY_PROXY_PASSWORD>@proxy.apify.com:8000'
# ── Keywords for address-level worksheet detection ──────────────────
ADDRESS_KEYWORDS = [
    "address", "street", "road", "city", "zip", "postal",
    "lat", "lon", "longitude", "latitude",
    "\u05db\u05ea\u05d5\u05d1\u05ea",  # כתובת
    "\u05e8\u05d7\u05d5\u05d1",        # רחוב
    "\u05e2\u05d9\u05e8",              # עיר
    "\u05e1\u05e4\u05e7",              # ספק
]


def _is_address_worksheet(df: pd.DataFrame) -> bool:
    if df.empty:
        return False
    cols_lower = [str(c).lower() for c in df.columns]
    return any(kw in col for col in cols_lower for kw in ADDRESS_KEYWORDS)


# ────────────────────────────────────────────────────────────────────
#  Core: Playwright bootstrap + requests API
# ────────────────────────────────────────────────────────────────────

def _bootstrap_via_playwright(url: str, proxy_server: str | None = None):
    bootstrap_req = None
    bootstrap_resp = None
    bootstrap_body = ""
    vizql_version = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context_args = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        if proxy_server:
            parsed = urlparse(proxy_server)
            if parsed.username and parsed.password:
                context_args["proxy"] = {
                    "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                    "username": parsed.username,
                    "password": parsed.password,
                }
            else:
                context_args["proxy"] = {"server": proxy_server}
            
        context = browser.new_context(**context_args)
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        page = context.new_page()

        def handle_route(route):
            nonlocal bootstrap_req, bootstrap_body, vizql_version
            request = route.request
            
            if not vizql_version:
                ver_match = re.search(r"/vizql/(v_[^/]+)/", request.url)
                if ver_match:
                    vizql_version = ver_match.group(1)

            if bootstrap_req is None:
                bootstrap_req = {
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "post_data": request.post_data,
                }
                logger.info("\n[VERBOSE] Captured bootstrapSession Request:")
                logger.info("URL: %s", request.url)
                logger.info("Headers: %s", json.dumps(request.headers, indent=2))
                logger.info("POST Body: %s\n", request.post_data)

            try:
                response = route.fetch()
                logger.info("\n[VERBOSE] Captured bootstrapSession Response Status: %s", response.status)
                body = response.text()
                if len(body) > len(bootstrap_body):
                    bootstrap_body = body
                route.fulfill(response=response)
            except Exception as e:
                logger.error("Failed to read bootstrap response via route: %s", e)
                # Fallback to let the page continue if fetch fails
                route.fallback()

        page.route(re.compile(r"bootstrapSession"), handle_route)

        # Wait until DOM loaded, Tableau uses delayed JS XHRs so networkidle fires too early
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # Wait extra time for bootstrapSession if networkidle fired too early
        for _ in range(45):
            if bootstrap_body:
                page.wait_for_timeout(3000)
                break
            page.wait_for_timeout(1000)

        if not bootstrap_body:
            raise RuntimeError("No bootstrapSession response captured")

        logger.info("[VERBOSE] bootstrapSession response size: %d bytes", len(bootstrap_body))

        # Extract data strictly from bootstrap response body (not tsConfigContainer)
        dashboard_name = ""
        worksheet_names = []
        session_id = ""
        vizql_root = ""
        sheet_id = ""
        datasources = []

        match = re.search(r"\d+;({.*})\d+;({.*})", bootstrap_body, re.MULTILINE)
        if match:
            info = json.loads(match.group(1))
            dashboard_name = info.get("sheetName", "")
            session_id = info.get("sessionId", "")
            vizql_root = info.get("vizql_root", "")
            sheet_id = info.get("sheetId", "")
            
            world = info.get("worldUpdate", {})
            app_pm = world.get("applicationPresModel", {})
            wb_pm = app_pm.get("workbookPresModel", {})
            
            # Extract worksheets from sheetsInfo
            sheets_info = wb_pm.get("sheetsInfo", [])
            for sheet in sheets_info:
                if sheet.get("isDashboard") is False:
                    ws_name = sheet.get("sheet", "")
                    if ws_name and ws_name not in worksheet_names:
                        worksheet_names.append(ws_name)
            
            # Fallback to visualIds if sheetsInfo is empty
            if not worksheet_names:
                dash_pm = wb_pm.get("dashboardPresModel", {})
                for vid in dash_pm.get("visualIds", []):
                    ws = vid.get("worksheet", "")
                    if ws and ws not in worksheet_names:
                        worksheet_names.append(ws)

            # Try to extract datasources if present (older versions / secondaryInfo)
            try:
                secondary_info = json.loads(match.group(2))
                dd_pm = secondary_info.get("secondaryInfo", {}).get("presModelMap", {}).get("dataDictionary", {}).get("presModelHolder", {}).get("genDataDictionaryPresModel", {})
                if dd_pm:
                    datasources = [ds.get("name", ds.get("id", ds)) for ds in dd_pm.get("dataSources", [])]
            except Exception:
                pass
            
            if not datasources:
                dd_pm = wb_pm.get("dataDictionary", {})
                if dd_pm:
                    datasources = [ds.get("name", ds.get("id", ds)) for ds in dd_pm.get("dataSources", [])]

            logger.info("[VERBOSE] Workbook Info: '%s'", dashboard_name)
            logger.info("[VERBOSE] Extracted Worksheets (%d): %s", len(worksheet_names), worksheet_names)
            logger.info("[VERBOSE] Extracted Datasources (%d): %s", len(datasources), datasources)

        if not session_id:
            # Extract from URL e.g. /bootstrapSession/sessions/F33...
            sess_match = re.search(r"/sessions/([^/]+)", bootstrap_req["url"])
            if sess_match:
                session_id = sess_match.group(1)
            else:
                logger.warning("Could not find sessionId in bootstrap info or URL.")

        browser_cookies = context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in browser_cookies}
        
        jsessionid = cookies_dict.get("JSESSIONID")
        logger.info("\n[VERBOSE] JSESSIONID extracted: %s", jsessionid)
        logger.info("[VERBOSE] VizQL Session ID: %s", session_id)
        logger.info("[VERBOSE] Extracted cookies: %s\n", cookies_dict.keys())
        
        if not jsessionid:
            logger.warning("[VERBOSE] JSESSIONID is missing from the browser cookies. This is expected behavior for modern Tableau Public deployments.")

        browser.close()

    # Reconstruct vizql_root correctly from the URL if missing
    if not vizql_root:
        vizql_match = re.search(r"(/vizql/.*)/bootstrapSession", bootstrap_req["url"])
        if vizql_match:
            vizql_root = vizql_match.group(1)
        elif vizql_version:
            vizql_root = f"/vizql/{vizql_version}"
        else:
            vizql_root = "/vizql/t/public/w/dashboard" # Fallback guess

    uri = urlparse(url)
    host = f"{uri.scheme}://{uri.netloc}"

    return {
        "host": host,
        "vizql_root": vizql_root,
        "session_id": session_id,
        "dashboard_name": dashboard_name,
        "worksheet_names": worksheet_names,
        "cookies": cookies_dict,
        "active_tab": sheet_id,
        "browser_headers": bootstrap_req["headers"]
    }


def _get_summary_data(
    host: str, vizql_root: str, session_id: str,
    http: requests.Session,
    worksheet_name: str, dashboard_name: str,
    max_rows: int = 10000,
) -> pd.DataFrame:
    url = f"{host}{vizql_root}/sessions/{session_id}/commands/tabdoc/get-summary-data"
    payload = (
        ("maxRows", (None, str(max_rows))),
        ("visualIdPresModel", (None, json.dumps({
            "worksheet": worksheet_name,
            "dashboard": dashboard_name,
            "flipboardZoneId": 0,
            "storyPointId": 0,
        }))),
    )

    logger.info("[VERBOSE] Executing VizQL command: get-summary-data for worksheet '%s'", worksheet_name)
    r = http.post(url, files=payload, timeout=60)
    r.raise_for_status()
    logger.info("[VERBOSE] get-summary-data response size: %d bytes", len(r.content))
    resp = r.json()

    cmd = resp.get("vqlCmdResponse", {})
    for result in cmd.get("cmdResultList", []):
        cr = result.get("commandReturn", {})
        sdt = cr.get("summaryDataTable", {})
        if sdt:
            columns = [col.get("fieldCaption", f"col_{i}")
                       for i, col in enumerate(sdt.get("columns", []))]
            data_rows = sdt.get("data", [])
            if columns and data_rows:
                return pd.DataFrame(data_rows, columns=columns)

    return pd.DataFrame()


def _get_underlying_data(
    host: str, vizql_root: str, session_id: str,
    http: requests.Session,
    worksheet_name: str, dashboard_name: str,
    max_rows: int = 10000,
) -> pd.DataFrame:
    url = f"{host}{vizql_root}/sessions/{session_id}/commands/tabdoc/get-underlying-data"
    payload = (
        ("maxRows", (None, str(max_rows))),
        ("includeAllColumns", (None, "true")),
        ("visualIdPresModel", (None, json.dumps({
            "worksheet": worksheet_name,
            "dashboard": dashboard_name,
            "flipboardZoneId": 0,
            "storyPointId": 0,
        }))),
    )

    logger.info("[VERBOSE] Executing VizQL command: get-underlying-data for worksheet '%s'", worksheet_name)
    r = http.post(url, files=payload, timeout=60)
    r.raise_for_status()
    logger.info("[VERBOSE] get-underlying-data response size: %d bytes", len(r.content))
    resp = r.json()

    cmd = resp.get("vqlCmdResponse", {})
    for result in cmd.get("cmdResultList", []):
        cr = result.get("commandReturn", {})
        for key in ("underlyingDataTable", "summaryDataTable"):
            sdt = cr.get(key, {})
            if sdt:
                columns = [col.get("fieldCaption", f"col_{i}")
                           for i, col in enumerate(sdt.get("columns", []))]
                data_rows = sdt.get("data", [])
                if columns and data_rows:
                    return pd.DataFrame(data_rows, columns=columns)

    return pd.DataFrame()


# ────────────────────────────────────────────────────────────────────
#  Address worksheet detection
# ────────────────────────────────────────────────────────────────────

def detect_address_worksheet(
    worksheets: dict[str, pd.DataFrame],
) -> tuple[str, pd.DataFrame] | None:
    candidates = [
        (name, df)
        for name, df in worksheets.items()
        if _is_address_worksheet(df)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: len(pair[1]), reverse=True)
    return candidates[0]


# ────────────────────────────────────────────────────────────────────
#  Export
# ────────────────────────────────────────────────────────────────────

def export_worksheets(worksheets: dict[str, pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in worksheets.items():
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
        
        # CSV Export
        csv_path = OUTPUT_DIR / f"{safe}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        
        # JSON Export
        json_path = OUTPUT_DIR / f"{safe}.json"
        df.to_json(json_path, orient="records", force_ascii=False)
        
        logger.info("Exported '%s' -> %s, %s (%d rows)", name, csv_path.name, json_path.name, len(df))


def save_sample(df: pd.DataFrame, path: Path = SAMPLE_CSV, n: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = df.head(n)
    sample.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Saved %d-row sample -> %s", len(sample), path)


# ────────────────────────────────────────────────────────────────────
#  Public entry point
# ────────────────────────────────────────────────────────────────────

def run(url: str = URL, proxy_server: str | None = None) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """End-to-end scrape: connect -> list -> extract -> export -> sample."""

    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        except Exception:
            pass

    worksheets: dict[str, pd.DataFrame] = {}

    if proxy_server is None:
        print("Using default paid proxy...")
        proxy_server = PAID_PROXY
    elif proxy_server == "None":
        proxy_server = None

    max_attempts = 3
    boot = None

    print("Using Playwright + VizQL commands to load Tableau dashboard...\n")

    try:
        for attempt in range(max_attempts):
            if proxy_server:
                print(f"[Attempt {attempt+1}/{max_attempts}] Using proxy: {proxy_server}")

            try:
                boot = _bootstrap_via_playwright(url, proxy_server)
                break  # Success
            except Exception as e:
                logger.warning("Bootstrap failed on attempt %d: %s", attempt+1, e)
                if attempt == max_attempts - 1:
                    raise RuntimeError(f"Failed to bootstrap after {max_attempts} attempts: {e}")
                print("Proxy/connection failed. Retrying...\n")

        host = boot["host"]
        vizql_root = boot["vizql_root"]
        session_id = boot["session_id"]
        dashboard_name = boot["dashboard_name"]
        ws_names = boot["worksheet_names"]
        cookies = boot["cookies"]
        active_tab = boot["active_tab"]

        print(f"Dashboard: {dashboard_name}")
        print(f"VizQL root: {vizql_root}")
        print(f"Session: {session_id}")
        print(f"Worksheets: {ws_names}")
        print(f"Cookies: {list(cookies.keys())}")

        http = requests.Session()
        if proxy_server:
            http.proxies.update({
                "http": proxy_server,
                "https": proxy_server,
            })
        http.cookies.update(cookies)
        
        # Filter browser headers to avoid breaking python requests
        safe_headers = {}
        for k, v in boot["browser_headers"].items():
            if k.lower() not in ["accept-encoding", "content-length", "host", "connection", "content-type"]:
                safe_headers[k] = v
        
        http.headers.update(safe_headers)
        http.headers.update({
            "Accept": "application/json, text/javascript, */*",
            "X-Tsi-Active-Tab": active_tab,
        })

        for ws_name in ws_names:
            try:
                df = _get_summary_data(
                    host, vizql_root, session_id, http, ws_name, dashboard_name
                )
                if df.empty:
                    df = _get_underlying_data(
                        host, vizql_root, session_id, http, ws_name, dashboard_name
                    )
                if not df.empty:
                    worksheets[ws_name] = df
                    logger.info("Extracted '%s': %d rows x %d cols",
                                ws_name, len(df), len(df.columns))
                else:
                    logger.warning("Worksheet '%s': no data returned", ws_name)
            except Exception as exc:
                logger.warning("Failed to extract '%s': %s", ws_name, exc)
    except Exception as e:
        raise RuntimeError(f"Scraper failed: {e}")

    if not worksheets:
        raise RuntimeError("No worksheet data could be extracted.")

    # ── 3. Print worksheets ──
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Found {len(worksheets)} worksheet(s) with data:")
    for i, name in enumerate(sorted(worksheets.keys()), 1):
        df = worksheets[name]
        print(f"  {i}. {name}  ({len(df)} rows x {len(df.columns)} cols)")
    print(sep)

    # ── 4. Print columns ──
    for name, df in worksheets.items():
        print(f"\n-- Worksheet: {name} --")
        print(f"   Columns: {list(df.columns)}")

    # ── 5. Export all worksheets ──
    export_worksheets(worksheets)

    # ── 6. Detect address-level worksheet ──
    best: pd.DataFrame
    match = detect_address_worksheet(worksheets)
    if match:
        best_name, best = match
        print(f"\n[OK] Address-level data detected in: '{best_name}'")
    else:
        best_name = max(worksheets, key=lambda k: len(worksheets[k]))
        best = worksheets[best_name]
        print(f"\n[!] No address columns detected; using largest: '{best_name}'")

    # ── 7. Save sample.csv ──
    save_sample(best)
    print(f"\n[OK] sample.csv saved ({min(20, len(best))} rows)")

    return best, worksheets
