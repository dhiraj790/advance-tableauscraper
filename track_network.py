import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"

def main():
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
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = context.new_page()

        def on_request(request):
            if "tableau.com" in request.url:
                print(f"-> REQ: {request.method} {request.url[:120]}")

        def on_response(response):
            if "tableau.com" in response.url:
                print(f"<- RES: {response.status} {response.url[:120]}")
                if "set-cookie" in response.headers or "set-cookie" in [h.lower() for h in response.headers.keys()]:
                    for h in response.headers_array():
                        if h["name"].lower() == "set-cookie":
                            print(f"   COOKIE: {h['value'].split('=')[0]}")

        page.on("request", on_request)
        page.on("response", on_response)
        
        print("Loading page...")
        # Use domcontentloaded to avoid hanging on networkidle
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        
        print("Waiting 10 seconds for XHRs to settle...")
        page.wait_for_timeout(10000)
        
        # Check if there is an iframe or something
        raw = page.evaluate("""
            () => {
                const el = document.getElementById('tsConfigContainer');
                return el ? (el.value || el.textContent || '') : 'NOT FOUND';
            }
        """)
        print(f"tsConfigContainer length: {len(raw)}")
        
        browser.close()

if __name__ == "__main__":
    main()
