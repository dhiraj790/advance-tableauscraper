"""Debug: test in-browser fetch with both versioned and non-versioned vizql_root,
and check if the page is in an iframe."""
import json
import re
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"


def main():
    bootstrap_body = ""
    vizql_version = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        def on_response(response):
            nonlocal bootstrap_body, vizql_version
            if not vizql_version:
                m = re.search(r"/vizql/(v_[^/]+)/", response.url)
                if m:
                    vizql_version = m.group(1)

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
                page.wait_for_timeout(3000)
                break

        # Get config
        raw = page.evaluate("""
            () => {
                const el = document.getElementById('tsConfigContainer');
                return el ? (el.value || el.textContent || '') : '';
            }
        """)
        ts_config = json.loads(raw) if raw and raw.strip() else {}

        vizql_root = ts_config.get("vizql_root", "")
        session_id = ts_config.get("sessionid", "")

        print(f"vizql_root from config: {vizql_root}")
        print(f"session_id: {session_id}")
        print(f"vizql_version from network: {vizql_version}")

        # Check cookies
        cookies = context.cookies()
        print(f"\nCookies ({len(cookies)}):")
        for c in cookies:
            print(f"  {c['name']} = {c['value'][:50]}... domain={c.get('domain', '?')}")

        # Check frames
        frames = page.frames
        print(f"\nFrames ({len(frames)}):")
        for frame in frames:
            print(f"  {frame.name or '(main)'}: {frame.url[:100]}")

        # Parse bootstrap for dashboard name
        dashboard_name = ""
        match = re.search(r"\d+;({.*})\d+;({.*})", bootstrap_body, re.MULTILINE)
        if match:
            info = json.loads(match.group(1))
            dashboard_name = info.get("sheetName", "")
        print(f"\nDashboard name: {dashboard_name}")

        # Try both versioned and non-versioned
        host = "https://public.tableau.com"
        roots_to_try = [
            ("non-versioned", vizql_root),
        ]
        if vizql_version:
            versioned = vizql_root.replace("/vizql/", f"/vizql/{vizql_version}/", 1)
            roots_to_try.append(("versioned", versioned))

        ws_name = "100m"

        for label, root in roots_to_try:
            api_url = f"{host}{root}/sessions/{session_id}/commands/tabdoc/get-summary-data"
            print(f"\n--- {label} ---")
            print(f"URL: {api_url}")

            result = page.evaluate("""
                async ([apiUrl, wsName, dashName]) => {
                    try {
                        const formData = new FormData();
                        formData.append('maxRows', '200');
                        formData.append('visualIdPresModel', JSON.stringify({
                            worksheet: wsName,
                            dashboard: dashName,
                            flipboardZoneId: 0,
                            storyPointId: 0,
                        }));

                        const response = await fetch(apiUrl, {
                            method: 'POST',
                            body: formData,
                            credentials: 'include',
                        });

                        return {
                            status: response.status,
                            statusText: response.statusText,
                            headers: Object.fromEntries(response.headers.entries()),
                            bodyLength: 0,
                            bodyPreview: '',
                            ok: response.ok,
                        };
                    } catch (e) {
                        return { error: e.message };
                    }
                }
            """, [api_url, ws_name, dashboard_name])

            print(f"  Result: {json.dumps(result, indent=2)}")

            if result.get("ok"):
                # Actually get the data
                result2 = page.evaluate("""
                    async ([apiUrl, wsName, dashName]) => {
                        const formData = new FormData();
                        formData.append('maxRows', '200');
                        formData.append('visualIdPresModel', JSON.stringify({
                            worksheet: wsName,
                            dashboard: dashName,
                            flipboardZoneId: 0,
                            storyPointId: 0,
                        }));
                        const response = await fetch(apiUrl, {
                            method: 'POST',
                            body: formData,
                            credentials: 'include',
                        });
                        return await response.json();
                    }
                """, [api_url, ws_name, dashboard_name])
                print(f"  Data keys: {list(result2.keys())[:10]}")

        # Also try via the iframe if there is one
        if len(frames) > 1:
            print("\n\n--- Trying from iframe context ---")
            iframe = frames[1]
            for label, root in roots_to_try:
                api_url = f"{host}{root}/sessions/{session_id}/commands/tabdoc/get-summary-data"
                print(f"\n{label}: {api_url}")
                try:
                    result = iframe.evaluate("""
                        async ([apiUrl, wsName, dashName]) => {
                            try {
                                const formData = new FormData();
                                formData.append('maxRows', '200');
                                formData.append('visualIdPresModel', JSON.stringify({
                                    worksheet: wsName,
                                    dashboard: dashName,
                                    flipboardZoneId: 0,
                                    storyPointId: 0,
                                }));
                                const response = await fetch(apiUrl, {
                                    method: 'POST',
                                    body: formData,
                                    credentials: 'include',
                                });
                                return { status: response.status, ok: response.ok };
                            } catch (e) {
                                return { error: e.message };
                            }
                        }
                    """, [api_url, ws_name, dashboard_name])
                    print(f"  Result: {result}")
                except Exception as e:
                    print(f"  Error: {e}")

        browser.close()


if __name__ == "__main__":
    main()
