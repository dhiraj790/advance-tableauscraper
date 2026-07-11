"""Tableau Public scraper – production version.

Uses Playwright for everything:
  1. Playwright loads the page, captures bootstrap session
  2. Extracts worksheets from bootstrap response
  3. VizQL commands also go through Playwright's APIRequestContext
     (sharing cookies/session with the browser)
  4. Results exported to CSV files + sample.csv
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


def _parse_bootstrap_body(body: str) -> tuple[dict, dict, list[str]]:
    match = re.search(r"\d+;({.*})\d+;({.*})", body, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not parse bootstrap response body")
    info = json.loads(match.group(1))
    secondary = json.loads(match.group(2))

    ws_names = []
    world = info.get("worldUpdate", {})
    app_pm = world.get("applicationPresModel", {})
    wb_pm = app_pm.get("workbookPresModel", {})
    sheets_info = wb_pm.get("sheetsInfo", [])
    for sheet in sheets_info:
        if sheet.get("isDashboard") is False:
            ws = sheet.get("sheet", "")
            if ws and ws not in ws_names:
                ws_names.append(ws)
    if not ws_names:
        dash_pm = wb_pm.get("dashboardPresModel", {})
        for vid in dash_pm.get("visualIds", []):
            ws = vid.get("worksheet", "")
            if ws and ws not in ws_names:
                ws_names.append(ws)

    return info, secondary, ws_names


def _vizql_via_page(page, url: str, payload_json: str, max_rows: str) -> dict:
    """Make a VizQL command POST via the browser's native fetch API.
    
    Uses FormData + Blob exactly as Tableau's own JavaScript does,
    so cookies, headers, and session are all handled by the browser.
    """
    result = page.evaluate("""
        async ([url, maxRows, visualJson]) => {
            const form = new FormData();
            form.append('maxRows', maxRows);
            const blob = new Blob([visualJson], {type: 'application/octet-stream'});
            form.append('visualIdPresModel', blob, 'blob');
            try {
                const r = await fetch(url, {method: 'POST', body: form});
                return {status: r.status, body: await r.text()};
            } catch (e) {
                return {status: 0, body: e.message || 'fetch failed'};
            }
        }
    """, [url, max_rows, payload_json])
    return result


def _parse_vizql_response(resp: dict) -> pd.DataFrame:
    if resp.get("status") != 200:
        return pd.DataFrame()
    try:
        data = json.loads(resp["body"])
    except (json.JSONDecodeError, KeyError):
        return pd.DataFrame()
    cmd = data.get("vqlCmdResponse", {})
    for result in cmd.get("cmdResultList", []):
        cr = result.get("commandReturn", {})
        sdt = cr.get("summaryDataTable", {})
        if sdt:
            columns = [col.get("fieldCaption", f"col_{i}")
                       for i, col in enumerate(sdt.get("columns", []))]
            rows = sdt.get("data", [])
            if columns and rows:
                return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame()


def _parse_vizql_underlying_response(resp: dict) -> pd.DataFrame:
    if resp.get("status") != 200:
        return pd.DataFrame()
    try:
        data = json.loads(resp["body"])
    except (json.JSONDecodeError, KeyError):
        return pd.DataFrame()
    cmd = data.get("vqlCmdResponse", {})
    for result in cmd.get("cmdResultList", []):
        cr = result.get("commandReturn", {})
        for key in ("underlyingDataTable", "summaryDataTable"):
            sdt = cr.get(key, {})
            if sdt:
                columns = [col.get("fieldCaption", f"col_{i}")
                           for i, col in enumerate(sdt.get("columns", []))]
                rows = sdt.get("data", [])
                if columns and rows:
                    return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame()


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


def detect_address_worksheet(
    worksheets: dict[str, pd.DataFrame],
) -> tuple[str, pd.DataFrame] | None:
    candidates = [
        (name, df) for name, df in worksheets.items() if _is_address_worksheet(df)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: len(pair[1]), reverse=True)
    return candidates[0]


def run(url: str = URL, proxy_server: str | None = None) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        except Exception:
            pass

    if proxy_server is None:
        print("Using default paid proxy...")
        proxy_server = PAID_PROXY
    elif proxy_server == "None":
        proxy_server = None

    worksheets: dict[str, pd.DataFrame] = {}

    clean_url = url.split("?")[0]
    tableau_params = {":embed": "y", ":showVizHome": "no"}
    page_url = clean_url + "?" + urlencode(tableau_params)

    print("Using Playwright for bootstrap + VizQL commands...\n")

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

        bootstrap_body = ""
        session_id = ""
        vizql_root = ""
        host = ""

        def handle_route(route):
            nonlocal bootstrap_body, session_id, vizql_root
            request = route.request
            if not session_id:
                m = re.search(r"/sessions/([^/]+)", request.url)
                if m:
                    session_id = m.group(1)
            if not vizql_root:
                m = re.search(r"(/vizql/.*)/bootstrapSession", request.url)
                if m:
                    vizql_root = m.group(1)
            try:
                response = route.fetch()
                body = response.text()
                if len(body) > len(bootstrap_body):
                    bootstrap_body = body
                route.fulfill(response=response)
            except Exception:
                route.fallback()

        page.route(re.compile(r"bootstrapSession"), handle_route)

        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)

        for _ in range(45):
            if bootstrap_body:
                page.wait_for_timeout(2000)
                break
            page.wait_for_timeout(1000)

        if not bootstrap_body:
            raise RuntimeError("No bootstrapSession response captured")

        uri = urlparse(clean_url)
        host = f"{uri.scheme}://{uri.netloc}"

        if not vizql_root:
            vizql_match = re.search(r"(/vizql/.*)/bootstrapSession", bootstrap_body[:5000])
            if vizql_match:
                vizql_root = vizql_match.group(1)
            else:
                vizql_root = "/vizql/w/_17255232362800/v/sheet11"

        info, _, ws_names = _parse_bootstrap_body(bootstrap_body)
        dashboard_name = info.get("sheetName", "")
        session_id = info.get("sessionId", session_id)
        vizql_root = info.get("vizql_root", vizql_root)

        logger.info("[VERBOSE] bootstrap response: %d bytes", len(bootstrap_body))
        logger.info("[VERBOSE] Dashboard: '%s'", dashboard_name)
        logger.info("[VERBOSE] Session: %s", session_id)
        logger.info("[VERBOSE] VizQL root: %s", vizql_root)
        logger.info("[VERBOSE] Worksheets (%d): %s", len(ws_names), ws_names)

        print(f"Dashboard: {dashboard_name}")
        print(f"VizQL root: {vizql_root}")
        print(f"Session: {session_id}")
        print(f"Worksheets: {ws_names}")

        for ws_name in ws_names:
            try:
                summary_url = f"{host}{vizql_root}/sessions/{session_id}/commands/tabdoc/get-summary-data"
                summary_payload = json.dumps({
                    "worksheet": ws_name,
                    "dashboard": dashboard_name,
                    "flipboardZoneId": 0,
                    "storyPointId": 0,
                })
                logger.info("[VERBOSE] get-summary-data for '%s'", ws_name)
                resp = _vizql_via_page(page, summary_url, summary_payload, str(10000))
                df = _parse_vizql_response(resp)
                if df.empty:
                    under_url = f"{host}{vizql_root}/sessions/{session_id}/commands/tabdoc/get-underlying-data"
                    under_payload = json.dumps({
                        "worksheet": ws_name,
                        "dashboard": dashboard_name,
                        "flipboardZoneId": 0,
                        "storyPointId": 0,
                    })
                    logger.info("[VERBOSE] get-underlying-data for '%s'", ws_name)
                    resp = _vizql_via_page(page, under_url, under_payload, str(10000))
                    df = _parse_vizql_underlying_response(resp)
                if not df.empty:
                    worksheets[ws_name] = df
                    logger.info("Extracted '%s': %d rows x %d cols", ws_name, len(df), len(df.columns))
                else:
                    logger.warning("Worksheet '%s': no data returned", ws_name)
            except Exception as exc:
                logger.warning("Failed to extract '%s': %s", ws_name, exc)

        browser.close()

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
