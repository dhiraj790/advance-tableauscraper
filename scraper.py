"""Tableau Public scraper – production version.

Hybrid approach:
  1. Playwright loads the page, intercepts bootstrapSession requests
  2. ABORTs the browser's bootstrap (so session is not activated by browser)
  3. Extracts session ID from the intercepted request URL
  4. Extracts cookies from the Playwright context
  5. Closes the browser
  6. Uses requests.Session with extracted cookies to bootstrap the session
  7. Then POSTs VizQL commands (get-summary-data / get-underlying-data)
     to extract data from every worksheet
  8. Results are exported to CSV files + sample.csv

This ensures the bootstrap and VizQL commands come from the same client
(requests.Session), while still getting the pre-bootstrap session ID
from the Playwright browser context.
"""
from __future__ import annotations

import io
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlencode

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

from config import OUTPUT_DIR, SAMPLE_CSV, URL

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("tableau_scraper")
PAID_PROXY = 'http://groups-RESIDENTIAL:<APIFY_PROXY_PASSWORD>@proxy.apify.com:8000'
ADDRESS_KEYWORDS = [
    "address", "street", "road", "city", "zip", "postal",
    "lat", "lon", "longitude", "latitude",
    "\u05db\u05ea\u05d5\u05d1\u05ea",
    "\u05e8\u05d7\u05d5\u05d1",
    "\u05e2\u05d9\u05e8",
    "\u05e1\u05e4\u05e7",
]


def _is_address_worksheet(df: pd.DataFrame) -> bool:
    if df.empty:
        return False
    cols_lower = [str(c).lower() for c in df.columns]
    return any(kw in col for col in cols_lower for kw in ADDRESS_KEYWORDS)


def _parse_bootstrap_response(body: str) -> tuple[dict, dict]:
    match = re.search(r"\d+;({.*})\d+;({.*})", body, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not parse bootstrap response body")
    return json.loads(match.group(1)), json.loads(match.group(2))


def _extract_worksheets(info: dict) -> list[str]:
    names = []
    world = info.get("worldUpdate", {})
    app_pm = world.get("applicationPresModel", {})
    wb_pm = app_pm.get("workbookPresModel", {})
    sheets_info = wb_pm.get("sheetsInfo", [])
    for sheet in sheets_info:
        if sheet.get("isDashboard") is False:
            ws = sheet.get("sheet", "")
            if ws and ws not in names:
                names.append(ws)
    if not names:
        dash_pm = wb_pm.get("dashboardPresModel", {})
        for vid in dash_pm.get("visualIds", []):
            ws = vid.get("worksheet", "")
            if ws and ws not in names:
                names.append(ws)
    return names


def _bootstrap_via_playwright(url: str, proxy_server: str | None = None):
    clean_url = url.split("?")[0]
    tableau_params = {":embed": "y", ":showVizHome": "no"}
    page_url = clean_url + "?" + urlencode(tableau_params)
    uri = urlparse(clean_url)
    host = f"{uri.scheme}://{uri.netloc}"

    bootstrap_url = None
    cookies_dict = {}

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

        def handle_bootstrap(route):
            nonlocal bootstrap_url
            if bootstrap_url is None:
                bootstrap_url = route.request.url
                logger.info("[VERBOSE] Intercepted bootstrap URL: %s", bootstrap_url)
            # ABORT the browser's bootstrap — we'll do it ourselves
            route.abort()

        page.route(re.compile(r"bootstrapSession"), handle_bootstrap)

        logger.info("Loading page via Playwright (blocking browser bootstrap)...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)

        for _ in range(45):
            if bootstrap_url:
                break
            page.wait_for_timeout(1000)

        if not bootstrap_url:
            raise RuntimeError("No bootstrapSession request intercepted")

        context_cookies = context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in context_cookies}
        logger.info("[VERBOSE] Cookies from Playwright: %s", list(cookies_dict.keys()))

        browser.close()

    logger.info("[VERBOSE] Bootstrap URL: %s", bootstrap_url)

    # Extract session ID, vizql_root from the bootstrap URL
    sess_match = re.search(r"/bootstrapSession/sessions/([^/]+)", bootstrap_url)
    if not sess_match:
        raise RuntimeError(f"Could not extract session ID from bootstrap URL: {bootstrap_url}")
    pre_session_id = sess_match.group(1)

    vizql_match = re.search(r"(/vizql/.*)/bootstrapSession", bootstrap_url)
    if not vizql_match:
        raise RuntimeError(f"Could not extract vizql_root from bootstrap URL: {bootstrap_url}")
    vizql_root = vizql_match.group(1)

    logger.info("[VERBOSE] Pre-bootstrap session ID: %s", pre_session_id)
    logger.info("[VERBOSE] vizql_root: %s", vizql_root)

    # Now bootstrap from our own requests.Session
    http = requests.Session()
    if proxy_server:
        http.proxies.update({"http": proxy_server, "https": proxy_server})

    http.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/javascript, application/json, */*",
    })

    # Set cookies with proper domain so requests sends them
    for name, value in cookies_dict.items():
        http.cookies.set(name, value, domain=".public.tableau.com", path="/")

    # Extract sheet_id from the bootstrap URL if possible
    sheet_id_match = re.search(r"/v/([^/]+)", vizql_root)
    sheet_id = sheet_id_match.group(1) if sheet_id_match else ""

    bs_url = f"{host}{vizql_root}/bootstrapSession/sessions/{pre_session_id}"
    bs_payload = {
        "sheet_id": sheet_id,
        "clientDimension": json.dumps({"w": 1920, "h": 1080}),
    }

    logger.info("Bootstrapping session from requests session...")
    bs_resp = http.post(
        bs_url, data=bs_payload,
        headers={
            "Accept": "text/javascript",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": host,
            "Referer": page_url,
            "X-Tsi-Active-Tab": sheet_id,
        },
        timeout=30,
    )
    if bs_resp.status_code != 200:
        logger.warning("Bootstrap POST returned %d: %s", bs_resp.status_code, bs_resp.text[:500])
    bs_resp.raise_for_status()
    logger.info("[VERBOSE] Bootstrap response: %d bytes", len(bs_resp.content))

    info, _ = _parse_bootstrap_response(bs_resp.text)
    dashboard_name = info.get("sheetName", "")
    session_id = info.get("sessionId", pre_session_id)
    ws_names = _extract_worksheets(info)
    sheet_id_from_info = info.get("sheetId", sheet_id)

    logger.info("[VERBOSE] Workbook Info: '%s'", dashboard_name)
    logger.info("[VERBOSE] Worksheets (%d): %s", len(ws_names), ws_names)

    return {
        "host": host,
        "vizql_root": vizql_root,
        "session_id": session_id,
        "dashboard_name": dashboard_name,
        "worksheet_names": ws_names,
        "cookies": dict(http.cookies),
        "active_tab": sheet_id_from_info,
        "http": http,
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


def export_worksheets(worksheets: dict[str, pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in worksheets.items():
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
        csv_path = OUTPUT_DIR / f"{safe}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        json_path = OUTPUT_DIR / f"{safe}.json"
        df.to_json(json_path, orient="records", force_ascii=False)
        logger.info("Exported '%s' -> %s, %s (%d rows)", name, csv_path.name, json_path.name, len(df))


def save_sample(df: pd.DataFrame, path: Path = SAMPLE_CSV, n: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = df.head(n)
    sample.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Saved %d-row sample -> %s", len(sample), path)


def run(url: str = URL, proxy_server: str | None = None) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
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

    print("Using Playwright + requests hybrid approach...\n")

    try:
        boot = _bootstrap_via_playwright(url, proxy_server)

        host = boot["host"]
        vizql_root = boot["vizql_root"]
        session_id = boot["session_id"]
        dashboard_name = boot["dashboard_name"]
        ws_names = boot["worksheet_names"]
        http = boot["http"]
        active_tab = boot["active_tab"]

        print(f"Dashboard: {dashboard_name}")
        print(f"VizQL root: {vizql_root}")
        print(f"Session: {session_id}")
        print(f"Worksheets: {ws_names}")

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

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Found {len(worksheets)} worksheet(s) with data:")
    for i, name in enumerate(sorted(worksheets.keys()), 1):
        df = worksheets[name]
        print(f"  {i}. {name}  ({len(df)} rows x {len(df.columns)} cols)")
    print(sep)

    for name, df in worksheets.items():
        print(f"\n-- Worksheet: {name} --")
        print(f"   Columns: {list(df.columns)}")

    export_worksheets(worksheets)

    best: pd.DataFrame
    match = detect_address_worksheet(worksheets)
    if match:
        best_name, best = match
        print(f"\n[OK] Address-level data detected in: '{best_name}'")
    else:
        best_name = max(worksheets, key=lambda k: len(worksheets[k]))
        best = worksheets[best_name]
        print(f"\n[!] No address columns detected; using largest: '{best_name}'")

    save_sample(best)
    print(f"\n[OK] sample.csv saved ({min(20, len(best))} rows)")

    return best, worksheets
