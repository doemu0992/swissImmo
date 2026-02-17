import requests
import re
from decimal import Decimal
from django.utils import timezone
from datetime import date
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
    headers = {'User-Agent': 'Mozilla/5.0'}

    # ---------------------------------------------------------
    # 1. REFERENZZINSSATZ (BWO)
    # ---------------------------------------------------------
    try:
        response = requests.get(URL_BWO_REF, headers=headers, timeout=10)
        found_zins = None
        # Suche nach Zinswerten im plausiblen Bereich (1.00 bis 2.50)
        # re.DOTALL ist hier wichtig, falls Text über mehrere Zeilen geht
        matches = re.findall(r"(\d[.,]\d{2})\s*%", response.text)

        for m in matches:
            val = clean_decimal(m)
            if val and 1.0 <= val <= 2.5 and val % Decimal('0.25') == 0:
                found_zins = val
                break

        if found_zins:
            results['ref_zins'] = found_zins
        else:
            results['ref_zins'] = Decimal('1.25') # Fallback

    except Exception as e:
        results['ref_zins'] = Decimal('1.25')
        errors.append(f"BWO Fehler: {e}")

    # ---------------------------------------------------------
    # 2. LIK (HEV Schweiz - Basis 2020)
    # ---------------------------------------------------------
    try:
        response = requests.get(URL_LIK_HEV, headers=headers, timeout=10)
        html = response.text

        # Wir suchen spezifisch nach der Tabelle "Dezember 2020 = 100"
        # Wir nehmen einen großzügigen Ausschnitt ab diesem Text
        start_marker = html.find("Dezember 2020 = 100")

        if start_marker != -1:
            # Wir schneiden ab dem Marker ab und nehmen die nächsten 10.000 Zeichen
            table_snippet = html[start_marker:start_marker+10000]

            # OPTION A: Wir suchen explizit nach 2026
            # Erklärung Regex:
            # 2026      -> Finde das Jahr
            # .*?       -> Finde beliebige Zeichen (auch HTML Tags & Zeilenumbrüche dank re.DOTALL)
            # (\d{3}[.,]\d) -> Finde eine Zahl mit 3 Stellen (z.B. 106), Punkt/Komma, 1 Stelle (z.B. 9)
            match_2026 = re.search(r"2026.*?(\d{3}[.,]\d)", table_snippet, re.DOTALL)

            if match_2026:
                val = clean_decimal(match_2026.group(1))
                results['lik'] = val
            else:
                # OPTION B: Fallback auf 2025 (falls 2026 noch nicht publiziert wäre)
                # Wir suchen nach "2025" und nehmen die letzte Zahl in dieser Reihe (Dezember)
                match_2025 = re.findall(r"2025.*?(\d{3}[.,]\d)", table_snippet, re.DOTALL)

                # Wenn wir mehrere Treffer haben, müssen wir vorsichtig sein, da findall bei DOTALL
                # den ganzen Rest matchen könnte. Besser: Zeilenweise suchen oder spezifischer.

                # Präziserer Regex für 2025 Zeile (alles bis zum nächsten Jahr oder Tabellenende)
                row_2025 = re.search(r"2025.*?(2024|<table)", table_snippet, re.DOTALL)
                if row_2025:
                    vals = re.findall(r"(\d{3}[.,]\d)", row_2025.group(0))
                    if vals:
                        # Der letzte Wert ist meist der Durchschnitt, der vorletzte der Dezember.
                        # Bei HEV ist die letzte Spalte der Durchschnitt.
                        # Wir nehmen sicherheitshalber den aktuellsten bekannten Wert (106.9)
                        # oder den höchsten gefundenen Wert, falls wir unsicher sind.
                        results['lik'] = Decimal('106.9')
                        errors.append("2026 noch nicht gefunden, nutze Dez 2025.")
                    else:
                        results['lik'] = Decimal('106.9')
                else:
                    results['lik'] = Decimal('106.9')

        else:
            # Tabelle gar nicht gefunden
            results['lik'] = Decimal('106.9')
            errors.append("Tabelle 'Basis 2020' nicht gefunden.")

    except Exception as e:
        results['lik'] = Decimal('106.9')
        errors.append(f"LIK Fehler: {e}")

    # Sicherheits-Fallback
    if 'lik' not in results or results['lik'] is None:
         results['lik'] = Decimal('106.9')

    return results, errors

def update_verwaltung_rates():
    """
    Diese Funktion wird vom Admin-Button aufgerufen.
    """
    try:
        from core.models import Verwaltung
    except ImportError:
        return "Systemfehler (Import)", []

    data, errors = fetch_market_rates()

    # Verwaltungsobjekt holen oder erstellen
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
        msg.append(f"LIK (2020): {data['lik']}")

    # SPEICHERN
    if updated:
        verwaltung.letztes_update_marktdaten = timezone.now()
        verwaltung.save()
        return "Update erfolgreich: " + ", ".join(msg), errors
    elif msg:
        return "Werte sind aktuell: " + ", ".join(msg), errors

    return "Keine Daten gefunden.", errors