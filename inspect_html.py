"""Inspect the actual HTML response from the Tableau URL to understand the bootstrap."""
import requests
import re
import json

url = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

print("1) Fetching the viz page...")
r = requests.get(url, headers=headers, timeout=30)
print(f"   Status: {r.status_code}")
print(f"   Content-Type: {r.headers.get('Content-Type', 'unknown')}")
print(f"   Body length: {len(r.text)} chars")

# Save full HTML for inspection
with open("output/page_dump.html", "w", encoding="utf-8") as f:
    f.write(r.text)
print("   Saved full HTML to output/page_dump.html")

# Look for the Tableau bootstrap JSON embedded in the page
html = r.text

# Check if the page is a redirect / auth wall
if "redirect" in html.lower()[:500] or r.status_code != 200:
    print(f"\n   WARNING: Page might be a redirect or auth wall.")
    print(f"   First 500 chars: {html[:500]}")

# Look for tsConfigContainer (the standard Tableau bootstrap pattern)
print("\n2) Looking for tsConfigContainer...")
match = re.search(r'id="tsConfigContainer"[^>]*>(.*?)</textarea>', html, re.DOTALL)
if match:
    config_text = match.group(1).strip()
    print(f"   Found tsConfigContainer ({len(config_text)} chars)")
    try:
        config = json.loads(config_text)
        print(f"   Parsed JSON keys: {list(config.keys())[:20]}")
        # Look for session info
        for key in ["vizql_root", "sessionid", "sheetId", "showParams", "siteRoot"]:
            if key in config:
                print(f"   {key}: {config[key]}")
        # Save it
        with open("output/ts_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("   Saved to output/ts_config.json")
    except json.JSONDecodeError as e:
        print(f"   JSON parse failed: {e}")
        print(f"   First 200 chars: {config_text[:200]}")
else:
    print("   tsConfigContainer NOT found")

# Look for any embedded JSON blobs
print("\n3) Scanning for tableau-specific patterns in HTML...")
patterns = {
    "vizql_root": r'"vizql_root"\s*:\s*"([^"]+)"',
    "sessionid": r'"sessionid"\s*:\s*"([^"]+)"',
    "sheetId": r'"sheetId"\s*:\s*"([^"]+)"',
    "model": r'"model"\s*:\s*\{',
    "worldUpdate": r'"worldUpdate"',
    "presModel": r'"presModel"',
    "dataDictionary": r'"dataDictionary"',
    "dataSegments": r'"dataSegments"',
}
for name, pattern in patterns.items():
    m = re.search(pattern, html)
    if m:
        print(f"   FOUND: {name} at pos {m.start()}")
        if m.lastindex:
            print(f"          value = {m.group(1)[:100]}")
    else:
        print(f"   not found: {name}")

# Look for secondary data URL or API calls in scripts
print("\n4) Looking for script tags with data URLs...")
script_matches = re.findall(r'<script[^>]*src=["\']([^"\']*)["\']', html)
for s in script_matches[:10]:
    print(f"   script: {s}")

# Check for the tableau bootstrapSession URL pattern
print("\n5) Searching for bootstrapSession or sessions URL patterns...")
bs_matches = re.findall(r'(https?://[^\s"\'<>]+(?:bootstrapSession|sessions|vizql)[^\s"\'<>]*)', html)
for m in bs_matches[:10]:
    print(f"   URL: {m}")

# Check for secondary data loading via a different endpoint
print("\n6) Looking for sheet data in <script> inline blocks...")
inline_scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print(f"   Found {len(inline_scripts)} inline script blocks")
for i, script in enumerate(inline_scripts):
    if len(script.strip()) > 50:
        snippet = script.strip()[:200].replace('\n', ' ')
        print(f"   [{i}] ({len(script)} chars) {snippet}...")
