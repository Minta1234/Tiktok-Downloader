import requests
import json
import re
import sys

def test_tiktok_api(tiktok_url):
    """
    Tests the TikWM API for extracting TikTok Photo Mode / Video metadata.
    """
    print(f"[*] Testing TikWM API for: {tiktok_url}")
    api_url = f"https://www.tikwm.com/api/?url={tiktok_url}"
    
    try:
        resp = requests.get(api_url, timeout=15)
        print(f"[+] API Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                item_data = data.get("data", {})
                images = item_data.get("images", [])
                print(f"[!] Success: Found {len(images)} images")
                for i, img in enumerate(images):
                    print(f"    - Image {i+1}: {img}")
                return item_data
            else:
                print(f"[-] API Error: {data.get('msg')}")
        else:
            print(f"[-] HTTP Error: {resp.status_code}")
    except Exception as e:
        print(f"[-] Request failed: {e}")
    return None

if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "PASTE_TIKTOK_URL_HERE"
    if target_url == "PASTE_TIKTOK_URL_HERE":
        print("Usage: python debug_tiktok.py <tiktok_url>")
    else:
        test_tiktok_api(target_url)
