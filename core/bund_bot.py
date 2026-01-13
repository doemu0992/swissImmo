import requests
from bs4 import BeautifulSoup
import re

def hol_referenzzinssatz():
    """
    Versucht, den aktuellen Referenzzinssatz von der BWO-Webseite zu lesen.
    Gibt den Zinssatz als float zurück (z.B. 1.25) oder None, wenn es nicht klappt.
    """
    url = "https://www.bwo.admin.ch/bwo/de/home/mietrecht/referenzzinssatz.html"

    try:
        # Wir geben uns als normaler Browser aus (User-Agent), sonst blockiert der Bund manchmal
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=5)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            # Wir suchen nach dem Text "Aktueller Referenzzinssatz"
            # Das BWO ändert die Seite selten, aber die Struktur ist oft:
            # "Der Referenzzinssatz beträgt X.XX Prozent"
            text = soup.get_text()

            # Regex-Suche nach "beträgt X.XX Prozent" oder ähnlichem Muster
            match = re.search(r"Referenzzinssatz.*?(\d+\.\d+).*?Prozent", text, re.IGNORECASE)

            if match:
                return float(match.group(1))

    except Exception as e:
        print(f"Fehler beim Abrufen des Zinssatzes: {e}")
        return None

    return None