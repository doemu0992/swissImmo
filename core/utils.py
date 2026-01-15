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
                # 'ganzwhg' = Anzahl Wohnungen total
                # 'buj' = Baujahr
                anzahl_wohnungen = attr.get('ganzwhg', 0)
                baujahr = attr.get('buj', None)

                # Wir packen das Baujahr in den ersten Eintrag (als Meta-Info)
                # Damit kann admin.py das Baujahr auslesen, ohne eine Einheit zu erstellen
                if baujahr:
                    units.append({
                        'is_meta': True,
                        'baujahr': baujahr,
                        # Dummy-Werte, damit alter Code nicht abstürzt, falls er das liest
                        'bezeichnung': 'Meta', 'ewid': 'meta',
                        'zimmer': 0, 'etage': '', 'flaeche': 0, 'typ': 'whg'
                    })

                # Da wir keine Details (Zimmer/Fläche pro Whg) mehr kriegen,
                # erstellen wir Platzhalter basierend auf der offiziellen Anzahl.
                if anzahl_wohnungen and anzahl_wohnungen > 0:
                    for i in range(1, int(anzahl_wohnungen) + 1):
                        units.append({
                            'bezeichnung': f"Wohnung {i}", # Platzhalter-Name
                            'zimmer': 0.0,      # Unbekannt -> Muss manuell ergänzt werden
                            'etage': '',        # Unbekannt
                            'flaeche': 0.0,     # Unbekannt
                            'ewid': f"ph-{egid}-{i}",  # Einzigartige Platzhalter-ID
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
                # Das erste (beste) Ergebnis zurückgeben
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