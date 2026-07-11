import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        def on_response(response):
            # Print URL and Set-Cookie header if present
            headers = response.headers
            if "set-cookie" in headers or "set-cookie" in [h.lower() for h in headers.keys()]:
                # In playwright, headers is a dict, and multiple headers might be joined by newline, or use headers_array
                for h in response.headers_array():
                    if h["name"].lower() == "set-cookie":
                        val = h["value"]
                        # Mask the long value for readability, just show the cookie name
                        cookie_name = val.split("=")[0]
                        print(f"[{response.status}] {response.url[:80]}... SETS COOKIE: {cookie_name}")
                        if "JSESSIONID" in cookie_name:
                            print(f"   => GOT JSESSIONID: {val}")

        page.on("response", on_response)
        
        print("Loading page to intercept Set-Cookie headers...")
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        
        browser.close()

if __name__ == "__main__":
    main()
