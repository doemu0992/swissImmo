import requests

def debug_lik_source():
    print("--- DIAGNOSE START ---")
    url = "https://www.mietrecht.ch/landesindex/ubersicht"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    print(f"1. Verbinde zu: {url} ...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"2. HTTP Status: {response.status_code}")
        
        if response.status_code != 200:
            print("   ❌ FEHLER: Seite blockiert (Status nicht 200).")
            return

        html = response.text
        print(f"3. Seite geladen: {len(html)} Zeichen.")

        if "Dezember" in html:
            print("   ✅ Wort 'Dezember' gefunden.")
        else:
            print("   ❌ Wort 'Dezember' NICHT gefunden.")

        if "2025" in html:
            print("   ✅ Jahr '2025' gefunden.")
        else:
            print("   ❌ Jahr '2025' NICHT gefunden.")

        if "106.9" in html or "106,9" in html:
            print("   ✅ Zahl '106.9' gefunden!")
        else:
            print("   ❌ Zahl '106.9' NICHT gefunden.")

    except Exception as e:
        print(f"   ❌ CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    debug_lik_source()
