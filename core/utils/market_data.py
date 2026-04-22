# core/utils/market_data.py
import requests
import re
from decimal import Decimal
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

URL_LIK_HEV = "https://www.hev-schweiz.ch/vermieten/statistiken/landesindex-der-konsumentenpreise"
URL_BWO_REF = "https://www.bwo.admin.ch/bwo/de/home/mietrecht/referenzzinssatz.html"

def clean_decimal(value_str):
    if not value_str: return None
    clean = re.sub(r'[^\d.,]', '', value_str)
    clean = clean.replace(',', '.').strip()
    try:
        return Decimal(clean)
    except:
        return None

def fetch_market_rates():
    results = {}
    errors = []

    # Ein unauffälliger Browser-Header, damit uns die Schweizer Server nicht blocken
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # ---------------------------------------------------------
    # 1. REFERENZZINSSATZ (BWO)
    # ---------------------------------------------------------
    try:
        response = requests.get(URL_BWO_REF, headers=headers, timeout=10)
        found_zins = None

        # Sucht im HTML nach Werten wie "1,25 %" oder "1.50%"
        matches = re.findall(r"(\d[.,]\d{2})\s*%", response.text)

        for m in matches:
            val = clean_decimal(m)
            # Prüft, ob es ein gültiger Zins ist (z.B. Vielfaches von 0.25)
            if val and Decimal('1.00') <= val <= Decimal('3.50') and (val * 100) % 25 == 0:
                found_zins = val
                break

        if found_zins:
            results['ref_zins'] = found_zins
        else:
            results['ref_zins'] = Decimal('1.75') # Fallback
            errors.append("BWO: Zins nicht gefunden, nutze Fallback.")

    except Exception as e:
        results['ref_zins'] = Decimal('1.75')
        errors.append(f"BWO Verbindungsfehler: {e}")

    # ---------------------------------------------------------
    # 2. LIK (HEV Schweiz - Basis 2020)
    # ---------------------------------------------------------
    try:
        response = requests.get(URL_LIK_HEV, headers=headers, timeout=10)
        html = response.text

        # Wir suchen den Tabellen-Block für "Dezember 2020 = 100"
        start_marker = html.find("2020 = 100")

        if start_marker != -1:
            # Wir nehmen den HTML-Code nach dem Marker (wo die aktuellen Jahre stehen)
            table_snippet = html[start_marker:start_marker+5000]

            # FIX: Zuerst als Zahl (int) berechnen, dann in Text (str) umwandeln!
            year_int = timezone.now().year
            current_year = str(year_int)          # z.B. "2026"
            next_year = str(year_int + 1)         # z.B. "2027"
            last_year = str(year_int - 1)         # z.B. "2025"

            # Wir suchen gezielt die Zeile des aktuellen oder letzten Jahres
            row_match = re.search(fr"{current_year}.*?(?:</tr>|<br>|{next_year})", table_snippet, re.IGNORECASE | re.DOTALL)

            if not row_match:
                # Falls das aktuelle Jahr noch nicht publiziert ist, nehmen wir das Vorjahr
                row_match = re.search(fr"{last_year}.*?(?:</tr>|<br>|{current_year})", table_snippet, re.IGNORECASE | re.DOTALL)

            if row_match:
                row_html = row_match.group(0)
                # Wir suchen in dieser Zeile nach ALLEN Zahlen im Format 1XX.X
                vals = re.findall(r"(1\d{2}[.,]\d)", row_html)

                valid_liks = []
                for v in vals:
                    d_val = clean_decimal(v)
                    # WICHTIG: Wir filtern die "100.0" aus (das ist nur der Basiswert!)
                    # Ein realistischer LIK für 2025/2026 liegt zwischen 104.0 und 120.0
                    if d_val and Decimal('104.0') < d_val < Decimal('120.0'):
                        valid_liks.append(d_val)

                if valid_liks:
                    # Wir nehmen den aktuellsten/letzten Wert in dieser Jahres-Reihe
                    results['lik'] = valid_liks[-1]
                else:
                    results['lik'] = Decimal('107.8')
                    errors.append(f"LIK-Werte für {current_year}/{last_year} waren ungültig.")
            else:
                results['lik'] = Decimal('107.8')
                errors.append(f"Jahreszeile {current_year}/{last_year} nicht gefunden.")
        else:
            results['lik'] = Decimal('107.8')
            errors.append("Basis 2020 Tabelle nicht auf HEV gefunden.")

    except Exception as e:
        results['lik'] = Decimal('107.8')
        errors.append(f"HEV Verbindungsfehler: {e}")

    # Absolutes Sicherheits-Netz
    if 'lik' not in results or results['lik'] is None:
         results['lik'] = Decimal('107.8')

    return results, errors

def update_verwaltung_rates():
    """
    Diese Funktion wird vom Dashboard-Button aufgerufen.
    Sie speichert die neuen Werte direkt in die Datenbank.
    """
    try:
        from crm.models import Verwaltung
    except ImportError:
        return "Systemfehler (Import Fehler crm.models)", []

    data, errors = fetch_market_rates()

    # Verwaltungsobjekt holen oder anlegen
    verwaltung = Verwaltung.objects.first()
    if not verwaltung:
        verwaltung = Verwaltung.objects.create(firma="Meine Verwaltung")

    updated = False
    msg = []

    # ZINS UPDATE
    if 'ref_zins' in data and data['ref_zins']:
        if verwaltung.aktueller_referenzzinssatz != data['ref_zins']:
            verwaltung.aktueller_referenzzinssatz = data['ref_zins']
            updated = True
        msg.append(f"Zins: {data['ref_zins']}%")

    # LIK UPDATE
    if 'lik' in data and data['lik']:
        if verwaltung.aktueller_lik_punkte != data['lik']:
            verwaltung.aktueller_lik_punkte = data['lik']
            updated = True
        msg.append(f"LIK (Basis 2020): {data['lik']}")

    # SPEICHERN
    if updated:
        verwaltung.letztes_update_marktdaten = timezone.now()
        verwaltung.save()
        return "Erfolgreich aktualisiert: " + " | ".join(msg), errors
    elif msg:
        return "Marktdaten geprüft, sie sind bereits aktuell: " + " | ".join(msg), errors

    return "Keine verwertbaren Daten gefunden.", errors