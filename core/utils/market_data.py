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

# Richtwerte (Stand 2026). Sie werden NIE in eine bestehende Verwaltung
# geschrieben: Ein fehlgeschlagener Abruf darf den Satz, den jemand eingetragen
# oder zuletzt erfolgreich geholt hat, nicht durch einen geratenen ersetzen.
# Alle Anpassungen nach Art. 269a OR rechnen gegen diesen Satz — ein stiller
# Rückfall auf 1.25 % (Stresstest 30.09.2026: manuell gesetzte 1.00 % sprangen
# zurück auf 1.25 %) macht jede Mietzinsanpassung falsch, ohne dass ein Fehler
# erscheint. Nur das Anlegen einer leeren Verwaltung darf sie als Startwert nutzen.
FALLBACK_REF_ZINS = Decimal('1.25')
FALLBACK_LIK = Decimal('107.8')

#: Der Referenzzinssatz bewegt sich in Schritten von 0.25 Prozentpunkten
#: (Art. 12a VMWG). Gültig sind damit auch 0.00 bis 1.00 — die Untergrenze
#: 1.00 der früheren Prüfung hätte 0.75 % und 0.50 % nie erkannt.
REF_ZINS_MIN = Decimal('0.00')
REF_ZINS_MAX = Decimal('5.00')
_REF_SCHRITT = Decimal('0.25')

def clean_decimal(value_str):
    if not value_str: return None
    clean = re.sub(r'[^\d.,]', '', value_str)
    clean = clean.replace(',', '.').strip()
    try:
        return Decimal(clean)
    except:
        return None

def _ist_gueltiger_ref_zins(val):
    return (val is not None and REF_ZINS_MIN <= val <= REF_ZINS_MAX
            and val % _REF_SCHRITT == 0)


def ref_zins_aus_html(html):
    """Liest den Referenzzinssatz aus der BWO-Seite — oder None.

    Zwei Stufen, weil die Seite viele Prozentwerte enthält (Beispiele,
    Verlaufstabelle): Zuerst nur, was unmittelbar hinter dem Stichwort
    «Referenzzinssatz» steht; erst dann jeder gültige Wert der Seite.
    Keine Treffer heisst None, nicht «Standardwert».
    """
    muster = r"(\d[.,]\d{2})\s*%"
    for m in re.finditer(r"referenzzins", html, re.IGNORECASE):
        for w in re.findall(muster, html[m.end():m.end() + 300]):
            val = clean_decimal(w)
            if _ist_gueltiger_ref_zins(val):
                return val
    for w in re.findall(muster, html):
        val = clean_decimal(w)
        if _ist_gueltiger_ref_zins(val) and val > 0:
            return val
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
            found_zins = ref_zins_aus_html(response.text)
            if found_zins is not None:
                break
        except Exception as e:
            errors.append(f"BWO Verbindungsfehler ({url}): {e}")

    # KEIN Fallback-Wert in `results`: Was nicht gefunden wurde, fehlt — und der
    # Aufrufer schreibt es dann nicht (siehe `_rates_schreiben`).
    if found_zins is not None:
        results['ref_zins'] = found_zins
    else:
        errors.append("BWO: Referenzzinssatz konnte nicht gelesen werden — der "
                      "gespeicherte Satz bleibt unverändert. Bitte prüfen.")

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
                    errors.append(f"LIK-Werte für {current_year}/{last_year} waren ungültig.")
            else:
                errors.append(f"Jahreszeile {current_year}/{last_year} nicht gefunden.")
        else:
            errors.append("Basis 2020 Tabelle nicht auf HEV gefunden.")

    except Exception as e:
        errors.append(f"HEV Verbindungsfehler: {e}")

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
        # Nichts gelesen → nichts geschrieben, und das laut: kein «aktualisiert».
        return ("Marktdaten NICHT aktualisiert: keine verwertbaren Daten gefunden. "
                "Die gespeicherten Werte bleiben unverändert — bitte prüfen."), errors
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