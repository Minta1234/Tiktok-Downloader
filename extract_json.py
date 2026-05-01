import json
import re
import sys
import os

def extract_tiktok_json(input_file, output_file='tiktok_data.json'):
    """
    Extracts TikTok's __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON from a saved HTML file.
    """
    if not os.path.exists(input_file):
        print(f"[-] File not found: {input_file}")
        return

    print(f"[*] Reading: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Locate the JSON metadata blob
    pattern = r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>'
    match = re.search(pattern, content)
    
    if not match:
        # Fallback to SIGI_STATE
        pattern = r'<script id="SIGI_STATE" type="application/json">(.*?)</script>'
        match = re.search(pattern, content)

    if match:
        try:
            data = json.loads(match.group(1))
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"[+] Successfully extracted JSON to: {output_file}")
        except Exception as e:
            print(f"[-] JSON parsing failed: {e}")
    else:
        print("[-] TikTok metadata script tags not found in this file.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_json.py <input_html_file>")
    else:
        extract_tiktok_json(sys.argv[1])
