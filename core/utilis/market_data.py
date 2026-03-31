import requests
import re
from decimal import Decimal
from django.utils import timezone

# Offizielle Quellen
URL_BWO_REF = "https://www.bwo.admin.ch/bwo/de/home/mietrecht/referenzzinssatz.html"
URL_BFS_LIK = "https://www.bfs.admin.ch/bfs/de/home/statistiken/preise/landesindex-konsumentenpreise.html"

def fetch_market_rates():
    """
    Holt den aktuellen Referenzzinssatz und LIK von den Admin.ch Webseiten.
    Gibt ein Dict zurück: {'ref_zins': Decimal(...), 'lik': Decimal(...)}
    """
    results = {}
    errors = []

    # 1. Referenzzinssatz holen (BWO)
    try:
        response = requests.get(URL_BWO_REF, timeout=10)
        if response.status_code == 200:
            # Suche nach Muster wie "Aktueller Referenzzinssatz: 1.75 %" oder ähnlichem
            # Wir suchen nach einer Zahl gefolgt von "%" im Kontext von "Referenzzinssatz"
            content = response.text

            # Regex Erklärung: Suche nach "Referenzzinssatz" ... gefolgt von Zahl (X.XX)
            # Das ist etwas "Heuristik", funktioniert aber meistens gut bei den Bundes-Seiten
            match = re.search(r"Referenzzinssatz.*?(\d+\.\d{2})\s*%", content, re.IGNORECASE | re.DOTALL)

            if match:
                results['ref_zins'] = Decimal(match.group(1))
            else:
                # Fallback: Suche einfach nach der prominentesten Prozentzahl im Titel
                errors.append("BWO: Konnte Zinssatz nicht im Text finden.")
        else:
            errors.append(f"BWO Seite nicht erreichbar (Status {response.status_code})")
    except Exception as e:
        errors.append(f"BWO Fehler: {str(e)}")

    # 2. LIK Punkte holen (BFS)
    try:
        response = requests.get(URL_BFS_LIK, timeout=10)
        if response.status_code == 200:
            content = response.text
            # Suche nach "Stand [Monat] [Jahr]: 107.1 Punkte"
            # Wir suchen nach einer Zahl im Format XXX.X vor dem Wort "Punkte"
            match = re.search(r"(\d{3}\.\d)\s*Punkte", content)

            if match:
                results['lik'] = Decimal(match.group(1))
            else:
                errors.append("BFS: Konnte LIK Punkte nicht finden.")
        else:
            errors.append(f"BFS Seite nicht erreichbar (Status {response.status_code})")
    except Exception as e:
        errors.append(f"BFS Fehler: {str(e)}")

    return results, errors

def update_verwaltung_rates():
    """
    Führt das Update auf dem Verwaltung-Objekt aus.
    """
    from crm.models import Verwaltung

    data, errors = fetch_market_rates()
    verwaltung = Verwaltung.objects.first()

    if not verwaltung:
        return "Keine Verwaltung angelegt.", errors

    updated_fields = []
    if 'ref_zins' in data:
        verwaltung.aktueller_referenzzinssatz = data['ref_zins']
        updated_fields.append(f"Ref.Zins: {data['ref_zins']}%")

    if 'lik' in data:
        verwaltung.aktueller_lik_punkte = data['lik']
        updated_fields.append(f"LIK: {data['lik']} Punkte")

    if updated_fields:
        verwaltung.letztes_update_marktdaten = timezone.now()
        verwaltung.save()
        return f"Erfolg: {', '.join(updated_fields)}", errors

    return "Keine neuen Daten gefunden.", errors