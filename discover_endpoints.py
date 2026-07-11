"""Inspect the real network flow for the Tableau thin-client viz.

The tsConfigContainer is empty on this page, meaning the viz uses
the newer "thin client" architecture.  PreBootstrap.min.js fetches
the bootstrap config via a secondary request.

This script discovers the REAL endpoints by:
1. Checking what tableauscraper.loads() actually does internally
2. Trying the documented Tableau Public API patterns
3. Looking at the vizql version embedded in the page
"""
import json
import re
import requests
import sys

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BASE_URL = "https://public.tableau.com"
VIEW_URL = f"{BASE_URL}/views/_17255232362800/sheet11"

session = requests.Session()
session.headers.update(HEADERS)


def step1_get_page():
    """Fetch the main viz page and extract the vizql version."""
    print("=" * 60)
    print("STEP 1: Fetch viz page and extract vizql version")
    print("=" * 60)
    r = session.get(f"{VIEW_URL}?:showVizHome=no", timeout=30)
    print(f"  Status: {r.status_code}")

    # Extract vizql version from the PreBootstrap script URL
    m = re.search(r'/vizql/(v_[^/]+)/', r.text)
    if m:
        version = m.group(1)
        print(f"  VizQL version: {version}")
        return version, r.text
    print("  ERROR: Could not find vizql version")
    return None, r.text


def step2_try_bootstrapSession(vizql_version):
    """Try the real Tableau bootstrapSession endpoint.
    
    In newer Tableau, the bootstrap is fetched via POST to:
      /vizql/<version>/bootstrapSession/sessions/<session_id>
    
    But first we need to get the session. The session comes from
    the initial page load (set-cookie or embedded in HTML).
    """
    print("\n" + "=" * 60)
    print("STEP 2: Check session cookies")
    print("=" * 60)
    cookies = dict(session.cookies)
    print(f"  Cookies: {list(cookies.keys())}")
    for k, v in cookies.items():
        print(f"    {k} = {v[:80]}{'...' if len(v) > 80 else ''}")


def step3_try_public_api():
    """Try the Tableau Public REST API to get workbook info.
    
    The Tableau Public API has a documented endpoint:
      GET /api/v1/viz/<workbook_id>
    or we can try the profile-based API.
    """
    print("\n" + "=" * 60)
    print("STEP 3: Try Tableau Public REST API")
    print("=" * 60)

    # Pattern: get workbook metadata from the public API
    # The workbook path is: _17255232362800
    workbook_id = "_17255232362800"

    # Try fetching the viz info
    api_url = f"{BASE_URL}/api/v1/viz/{workbook_id}"
    print(f"  Trying: {api_url}")
    try:
        r = session.get(api_url, timeout=15)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  Content-Type: {r.headers.get('Content-Type')}")
            print(f"  Body (first 500): {r.text[:500]}")
    except Exception as e:
        print(f"  Error: {e}")


def step4_try_embed_url():
    """Try the :embed=y URL which sometimes returns more data."""
    print("\n" + "=" * 60)
    print("STEP 4: Try embed URL format")
    print("=" * 60)

    embed_url = f"{VIEW_URL}?:embed=y&:showVizHome=no"
    print(f"  URL: {embed_url}")
    r = session.get(embed_url, timeout=30)
    print(f"  Status: {r.status_code}")
    print(f"  Body length: {len(r.text)}")

    # Check if tsConfigContainer has content now
    m = re.search(r'id="tsConfigContainer"[^>]*>(.*?)</textarea>', r.text, re.DOTALL)
    if m:
        config_text = m.group(1).strip()
        print(f"  tsConfigContainer: {len(config_text)} chars")
        if config_text:
            try:
                config = json.loads(config_text)
                print(f"  Keys: {list(config.keys())[:20]}")
                with open("output/ts_config_embed.json", "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                print(f"  Saved to output/ts_config_embed.json")
                return config
            except json.JSONDecodeError as e:
                print(f"  JSON error: {e}")
                print(f"  Raw: {config_text[:300]}")
    else:
        print("  tsConfigContainer not found")
    return None


def step5_try_format_csv():
    """Try the :format=csv download URL (works on some public vizzes)."""
    print("\n" + "=" * 60)
    print("STEP 5: Try direct CSV download (:format=csv)")
    print("=" * 60)

    csv_url = f"{VIEW_URL}?:format=csv"
    print(f"  URL: {csv_url}")
    r = session.get(csv_url, timeout=30)
    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('Content-Type')}")
    print(f"  Body length: {len(r.text)}")
    if r.status_code == 200 and "text/csv" in r.headers.get("Content-Type", ""):
        print(f"  First 500 chars: {r.text[:500]}")
        with open("output/direct_download.csv", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("  Saved to output/direct_download.csv")
        return True
    else:
        print(f"  Response (first 300): {r.text[:300]}")
    return False


def step6_try_render_view():
    """Try the Tableau render API for exporting data."""
    print("\n" + "=" * 60)
    print("STEP 6: Try render view endpoints")
    print("=" * 60)

    # Try getting the viz as JSON
    for fmt in ["json", "csv"]:
        url = f"{VIEW_URL}.{fmt}"
        print(f"  Trying: {url}")
        try:
            r = session.get(url, timeout=15)
            print(f"    Status: {r.status_code}, Type: {r.headers.get('Content-Type', '?')}")
            if r.status_code == 200:
                print(f"    Body (first 300): {r.text[:300]}")
        except Exception as e:
            print(f"    Error: {e}")


if __name__ == "__main__":
    version, html = step1_get_page()
    if version:
        step2_try_bootstrapSession(version)
    step3_try_public_api()
    config = step4_try_embed_url()
    step5_try_format_csv()
    step6_try_render_view()
