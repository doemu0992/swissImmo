import requests
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

def get_egid_from_address(strasse, plz, ort):
    """
    Sucht die EGID via GeoAdmin API (zuverlässig für Adressen).
    """
    url = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
    params = {
        'searchText': f"{strasse} {plz} {ort}",
        'type': 'locations',
        'origins': 'address',
        'limit': 1
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                attrs = data['results'][0].get('attrs', {})
                # FeatureID bereinigen (123456_0 -> 123456)
                raw_id = attrs.get('featureId', '') or attrs.get('num', '') or attrs.get('egid', '')
                if raw_id:
                    egid = str(raw_id).split('_')[0]
                    if egid.isdigit() and int(egid) > 1000:
                        return egid
        return None
    except Exception as e:
        logger.error(f"Fehler bei EGID Suche: {e}")
        return None


def translate_floor(code):
    """
    Übersetzt GWR-Stockwerk-Codes (z.B. 3100) in lesbaren Text (z.B. EG).
    """
    if not code: return ""
    code = str(code).strip()

    # Bekannte Codes
    mapping = {
        '3100': 'EG',
        '3200': '1. OG',
        '3300': 'DG',
        '3000': 'UG'
    }

    if code in mapping:
        return mapping[code]

    # Logik für Obergeschosse (32xx) -> 3201 = 1. OG
    if code.startswith('32') and len(code) == 4:
        try:
            num = int(code[2:])
            return f"{num}. OG"
        except: pass

    # Logik für Untergeschosse (30xx) -> 3001 = 1. UG
    if code.startswith('30') and len(code) == 4:
        try:
            num = int(code[2:])
            return f"{num}. UG"
        except: pass

    # Logik für Dachgeschosse
    if code.startswith('33'):
         return "DG"

    return code # Fallback


def get_units_from_bfs(egid):
    """
    Holt Daten via MADD XML-Schnittstelle.
    Nutzt korrekte Tags für Zimmer/Fläche und formatiert die Bezeichnung neu.
    """
    if not egid:
        return []

    units = []
    url = f"https://madd.bfs.admin.ch/eCH-0206?egid={egid}"

    logger.info(f"GWR: Rufe XML Details ab für EGID {egid}...")

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            root = ET.fromstring(response.content)

            # Alle 'dwelling' (Wohnung) Elemente suchen
            found_dwellings = []
            for elem in root.iter():
                if elem.tag.endswith('dwelling'):
                    found_dwellings.append(elem)

            if found_dwellings:
                logger.info(f"GWR: {len(found_dwellings)} Wohnungen im XML gefunden.")

                for dw in found_dwellings:
                    # Variablen resetten
                    ewid = ""
                    zimmer = 0.0
                    flaeche = 0.0
                    etage_code = ""
                    whgnr = ""

                    # Kind-Elemente durchsuchen
                    for child in dw.iter():
                        tag = child.tag
                        val = child.text

                        if not val: continue

                        # 1. EWID
                        if tag.endswith('dwellingId') or tag.endswith('ewid'):
                            ewid = val

                        # 2. ZIMMER
                        elif tag.endswith('noOfHabitableRooms') or tag.endswith('numberOfRooms'):
                            try: zimmer = float(val)
                            except: pass

                        # 3. FLÄCHE
                        elif tag.endswith('surfaceAreaOfDwelling') or \
                             tag.endswith('totalSurface') or \
                             tag.endswith('mainUsableArea'):
                            try: flaeche = float(val)
                            except: pass

                        # 4. STOCKWERK
                        elif tag.endswith('floor'):
                            etage_code = val

                        # 5. Admin Nummer
                        elif tag.endswith('physicalId') or tag.endswith('adminId'):
                            whgnr = val

                    # Daten aufbereiten
                    etage_text = translate_floor(etage_code)

                    # --- NEUE FORMEL FÜR BEZEICHNUNG ---
                    # Format: "4.5 Zimmer Wohnung (1. OG)"

                    # Zimmer formatieren (aus 4.0 wird "4", aus 3.5 bleibt "3.5")
                    if zimmer > 0:
                        zim_str = f"{zimmer:g}" # :g entfernt unnötige Nullen
                    else:
                        zim_str = "?"

                    bezeichnung = f"{zim_str} Zimmer Wohnung"

                    if etage_text:
                        bezeichnung += f" ({etage_text})"
                    elif etage_code:
                        bezeichnung += f" ({etage_code})"

                    units.append({
                        'bezeichnung': bezeichnung,
                        'ewid': ewid if ewid else f"ph-{egid}",
                        'typ': 'whg',
                        'is_meta': False,
                        'zimmer': zimmer,
                        'flaeche': flaeche,
                        'etage': etage_text
                    })
            else:
                logger.warning("GWR: XML geladen, aber keine <dwelling> Tags erkannt.")
        else:
            logger.error(f"GWR MADD Fehler: Status {response.status_code}")

        return units

    except Exception as e:
        logger.error(f"Fehler bei GWR XML Abruf: {e}")
        return []