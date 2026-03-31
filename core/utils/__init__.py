import os
import datetime
import requests
import segno
import io
import base64
import logging

# BeautifulSoup wird nicht mehr benötigt, da wir die API nutzen
# from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def get_units_from_bfs(egid):
    """
    NEUE LOGIK (Plan B):
    Da housing-stat.ch eine JavaScript-App ist (kann nicht gescrapt werden)
    und der Detail-Layer der GeoAdmin API gesperrt ist, nutzen wir den Gebäude-Layer.

    Wir holen:
    1. Baujahr (für die Liegenschaft)
    2. Anzahl Wohnungen (um Platzhalter-Einheiten zu erstellen)
    """
    if not egid:
        return []

    # GeoAdmin API - Gebäude Register (Layer ch.bfs.gebaeude_wohnungs_register)
    url = "https://api3.geo.admin.ch/rest/services/api/MapServer/find"
    params = {
        'layer': 'ch.bfs.gebaeude_wohnungs_register',
        'searchText': str(egid),
        'searchField': 'egid',
        'returnGeometry': 'false'
    }

    units = []
    try:
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                attr = data['results'][0]['attributes']

                # Wir holen Infos über das Gebäude
                anzahl_wohnungen = attr.get('ganzwhg', 0)
                baujahr = attr.get('buj', None)

                # Wir packen das Baujahr in den ersten Eintrag (als Meta-Info)
                if baujahr:
                    units.append({
                        'is_meta': True,
                        'baujahr': baujahr,
                        'bezeichnung': 'Meta', 'ewid': 'meta',
                        'zimmer': 0, 'etage': '', 'flaeche': 0, 'typ': 'whg'
                    })

                # Erstellen Platzhalter basierend auf der offiziellen Anzahl.
                if anzahl_wohnungen and anzahl_wohnungen > 0:
                    for i in range(1, int(anzahl_wohnungen) + 1):
                        units.append({
                            'bezeichnung': f"Wohnung {i}",
                            'zimmer': 0.0,
                            'etage': '',
                            'flaeche': 0.0,
                            'ewid': f"ph-{egid}-{i}",
                            'typ': 'whg',
                            'is_meta': False
                        })

                    logger.info(f"GWR Backup: {anzahl_wohnungen} Einheiten-Platzhalter generiert.")
                else:
                    logger.warning(f"GWR: Gebäude gefunden, aber 'ganzwhg' ist 0 oder leer.")

        return units

    except Exception as e:
        logger.error(f"Fehler bei GeoAdmin API Abruf: {e}")
        return []


def get_egid_from_address(strasse, plz, ort):
    """
    Sucht die EGID (Eidg. Gebäude-ID) anhand der Adresse über die GeoAdmin API.
    """
    url = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
    params = {
        'searchText': f"{strasse} {plz} {ort}",
        'type': 'locations',
        'origins': 'address',
        'limit': 1
    }

    try:
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get('results'):
                return data['results'][0]['attrs'].get('egid')
    except Exception as e:
        logger.error(f"Fehler bei EGID Suche: {e}")
        pass

    return None


def generate_swiss_qr_base64(iban, name, strasse, ort, betrag, referenz):
    """
    Erstellt einen Schweizer QR-Code als Base64-String für PDFs.
    """
    qr_data = [
        "SPC", "0200", "1",
        iban.replace(" ", ""),
        "S", name, strasse, ort, "", "", "",  # Gläubiger
        "", "",  # Ultimativer Gläubiger (leer)
        "CHF", str(betrag),
        "", "", "",  # Schuldner (optional, hier leer gelassen)
        "S", referenz,  # Referenztyp (QRR) und Referenznummer
        "Mietzinszahlung", "EPD" # Unstrukturierte Mitteilung + Trailer
    ]

    qr_string = "\r\n".join(qr_data)

    try:
        qr = segno.make(qr_string, error='M')
        buff = io.BytesIO()
        qr.save(buff, kind='png', scale=4)
        return base64.b64encode(buff.getvalue()).decode()
    except Exception as e:
        logger.error(f"Fehler bei QR Generierung: {e}")
        return ""


# ==============================================================================
# --- NEUE HELPER FUNKTIONEN FÜR DIE APP-AUFTEILUNG ---
# ==============================================================================

def get_current_ref_zins():
    try:
        from crm.models import Verwaltung
        v = Verwaltung.objects.first()
        return v.aktueller_referenzzinssatz if v else 1.75
    except: return 1.75

def get_current_lik():
    try:
        from crm.models import Verwaltung
        v = Verwaltung.objects.first()
        return v.aktueller_lik_punkte if v else 107.1
    except: return 107.1

def get_smart_upload_path(instance, filename):
    heute = datetime.date.today().strftime("%Y-%m-%d")
    return os.path.join("uploads", heute, filename)