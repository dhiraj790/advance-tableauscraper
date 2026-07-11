import requests
import json
import re

def main():
    url = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })

    # Step 1: GET initial HTML
    print("GET initial HTML...")
    r = s.get(url)
    
    # Extract version
    version_match = re.search(r"/vizql/(v_[^/]+)/", r.text)
    if not version_match:
        print("No version found!")
        return
    vizql_version = version_match.group(1)
    print(f"vizql_version: {vizql_version}")

    # Step 2: POST startSession/viewing
    start_session_url = f"https://public.tableau.com/vizql/w/_17255232362800/v/sheet11/startSession/viewing?%3AshowVizHome=no&%3Aredirect=auth"
    print(f"POST startSession...")
    r2 = s.post(start_session_url, headers={
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "X-Tsi-Active-Tab": "sheet11"
    }, json={
        "deviceDescriptor": {"deviceType": "desktop", "os": "windows"},
        "clientSize": {"width": 1920, "height": 1080},
    })
    print(f"startSession Status: {r2.status_code}")
    print(f"startSession Cookies: {s.cookies.get_dict()}")
    
    try:
        resp_data = r2.json()
        session_id = resp_data.get("sessionid", "")
        print(f"Got Session ID from startSession JSON: {session_id}")
        
        if session_id:
            # Step 3: POST bootstrapSession
            bootstrap_url = f"https://public.tableau.com/vizql/w/_17255232362800/v/sheet11/bootstrapSession/sessions/{session_id}"
            print(f"\nPOST bootstrapSession...")
            r3 = s.post(bootstrap_url, headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Tsi-Active-Tab": "sheet11",
                "X-Tsi-Session-Id": session_id
            }, data={"sheet_id": "sheet11"})
            print(f"bootstrapSession Status: {r3.status_code}")
            
            if r3.status_code == 200:
                print(f"bootstrapSession Length: {len(r3.text)}")
                if "JSESSIONID" in r3.text:
                    print("JSESSIONID is inside the body!")
                else:
                    print("JSESSIONID not found in body.")
            
    except Exception as e:
        print(f"Error parsing json: {e}")

if __name__ == "__main__":
    main()
