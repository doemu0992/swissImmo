# core/utils/market_data.py
import requests
import re
from decimal import Decimal
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

URL_LIK_HEV = "https://www.hev-schweiz.ch/vermieten/statistiken/landesindex-der-konsumentenpreise"
# BWO-Seite umgezogen -> neue kurze URL (alte /bwo/de/home/... liefert 403)
URL_BWO_REF = "https://www.bwo.admin.ch/de/referenzzinssatz"
URL_BWO_REF_ALT = "https://www.bwo.admin.ch/de/entwicklung-referenzzinssatz-und-durchschnittszinssatz"

# Aktuelle Fallback-Werte (Stand 2026): Referenzzinssatz 1.25 % seit 09.2025,
# LIK Basis Dez 2020 = 100 ~ 107.8. Werden genutzt, wenn kein Internet erreichbar ist.
FALLBACK_REF_ZINS = Decimal('1.25')
FALLBACK_LIK = Decimal('107.8')

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
    found_zins = None
    for url in (URL_BWO_REF, URL_BWO_REF_ALT):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            # Sucht im HTML nach Werten wie "1,25 %" oder "1.50%"
            matches = re.findall(r"(\d[.,]\d{2})\s*%", response.text)
            for m in matches:
                val = clean_decimal(m)
                # Prüft, ob es ein gültiger Zins ist (z.B. Vielfaches von 0.25)
                if val and Decimal('1.00') <= val <= Decimal('3.50') and (val * 100) % 25 == 0:
                    found_zins = val
                    break
            if found_zins:
                break
        except Exception as e:
            errors.append(f"BWO Verbindungsfehler ({url}): {e}")

    if found_zins:
        results['ref_zins'] = found_zins
    else:
        results['ref_zins'] = FALLBACK_REF_ZINS
        if not errors:
            errors.append("BWO: Zins nicht gefunden, nutze Fallback 1.25 %.")

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
                    results['lik'] = FALLBACK_LIK
                    errors.append(f"LIK-Werte für {current_year}/{last_year} waren ungültig.")
            else:
                results['lik'] = FALLBACK_LIK
                errors.append(f"Jahreszeile {current_year}/{last_year} nicht gefunden.")
        else:
            results['lik'] = FALLBACK_LIK
            errors.append("Basis 2020 Tabelle nicht auf HEV gefunden.")

    except Exception as e:
        results['lik'] = FALLBACK_LIK
        errors.append(f"HEV Verbindungsfehler: {e}")

    # Absolutes Sicherheits-Netz
    if 'lik' not in results or results['lik'] is None:
         results['lik'] = FALLBACK_LIK

    return results, errors

def update_verwaltung_rates(organisation=None, *, alle=False):
    """Holt Referenzzinssatz und LIK und schreibt sie in die Verwaltungsdaten.

    `organisation` bestimmt, WESSEN Daten geschrieben werden:

    - **Eine Organisation** — der Weg fuer jeden Aufruf aus der Oberflaeche.
      Ein Knopfdruck darf nur die eigenen Daten aendern. Zwar sind
      Referenzzins und LIK nationale Werte, aber `letztes_update_marktdaten`
      ist es nicht: An diesem Stempel haengt die Frischepruefung, und ein
      fremder Klick duerfte ihn nicht zuruecksetzen.
    - **`alle=True`** — alle Organisationen. Der Weg fuer den taeglichen Lauf
      und `manage.py update_rates`. Vorher schrieb der Aufruf immer nur in die
      ERSTE Verwaltung; alle weiteren blieben auf ihrem alten Zinssatz stehen
      und rechneten Mietzinsanpassungen nach OR 269a gegen einen veralteten
      Stand — ohne dass irgendwo ein Fehler erschienen waere.

    WARUM `alle` UND NICHT EINFACH `None` (18.08.2026): Bis hierher bedeutete
    `None` „alle". Zwei Aufrufer uebergaben aber `aktuelle_organisation()` —
    und der ist None, sobald kein Kontext gesetzt ist. Aus „schreibe in MEINE
    Verwaltung" wurde damit stillschweigend „schreibe in ALLE", inklusive des
    Frischestempels, an dem die Frischepruefung haengt (gemessen: beide
    Verwaltungen landeten auf demselben Wert). Ein vergessener Kontext darf
    nicht die Bedeutung eines Aufrufs umdrehen; „alle" muss man jetzt sagen.
    """
    if organisation is None and not alle:
        raise ValueError(
            'update_verwaltung_rates ohne Organisation: Fuer alle Verwaltungen '
            'ausdruecklich alle=True setzen. Ein leerer Kontext ist kein '
            '„alle" — er ist ein Fehler.')
    try:
        from crm.models import Organisation
    except ImportError:
        return "Systemfehler (Import Fehler crm.models)", []

    # Einmal ins Internet, egal wie viele Verwaltungen versorgt werden.
    data, errors = fetch_market_rates()

    if organisation is not None:
        ziele = [organisation]
    else:
        ziele = list(Organisation.objects.order_by('pk'))
        if not ziele:
            # Erstinbetriebnahme: ohne Verwaltungsdatensatz gaebe es nichts zu
            # schreiben. Das Anlegen bleibt auf genau diesen Fall beschraenkt.
            ziele = [Organisation.objects.create(firma="Meine Verwaltung")]

    ergebnisse = [_rates_schreiben(ziel, data) for ziel in ziele]
    geaendert = [t for t, _ in ergebnisse if t]
    texte = next((m for _, m in ergebnisse if m), [])

    if not texte:
        return "Keine verwertbaren Daten gefunden.", errors
    if geaendert:
        return "Erfolgreich aktualisiert: " + " | ".join(texte), errors
    return "Marktdaten geprüft, sie sind bereits aktuell: " + " | ".join(texte), errors


def _rates_schreiben(verwaltung, data):
    """Schreibt die geholten Werte in EINE Verwaltung. Gibt (geaendert, texte)."""
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
    # Der Zeitstempel hält fest, wann ZULETZT GEPRÜFT wurde — nicht, wann sich
    # zuletzt ein Wert geändert hat. Referenzzins und LIK ändern sich nur ein
    # paar Mal im Jahr; wäre der Stempel an eine Änderung gekoppelt, gälten die
    # Daten dazwischen dauernd als veraltet und jeder Aufruf ginge erneut ins
    # Internet. Genau daran scheiterte die Frischeprüfung in fw_marktdaten_live.
    if msg:
        verwaltung.letztes_update_marktdaten = timezone.now()
        verwaltung.save()
    return updated, msg