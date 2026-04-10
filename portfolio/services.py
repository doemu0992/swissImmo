# portfolio/services.py
import requests
import logging
import xml.etree.ElementTree as ET
from .models import Einheit

logger = logging.getLogger(__name__)

# --- 1. GEOADMIN & BFS API LOGIK ---

def get_egid_from_address(strasse, plz, ort):
    """Sucht die EGID via GeoAdmin API (zuverlässig für Adressen)."""
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
    """Übersetzt GWR-Stockwerk-Codes in lesbaren Text (z.B. EG)."""
    if not code: return ""
    code = str(code).strip()
    mapping = {'3100': 'EG', '3200': '1. OG', '3300': 'DG', '3000': 'UG'}
    if code in mapping: return mapping[code]
    if code.startswith('32') and len(code) == 4:
        try: return f"{int(code[2:])}. OG"
        except: pass
    if code.startswith('30') and len(code) == 4:
        try: return f"{int(code[2:])}. UG"
        except: pass
    if code.startswith('33'): return "DG"
    return code

def get_units_from_bfs(egid):
    """Holt Daten via MADD XML-Schnittstelle."""
    if not egid: return []
    units = []
    url = f"https://madd.bfs.admin.ch/eCH-0206?egid={egid}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            found_dwellings = [elem for elem in root.iter() if elem.tag.endswith('dwelling')]

            for dw in found_dwellings:
                ewid, zimmer, flaeche, etage_code, whgnr = "", 0.0, 0.0, "", ""
                for child in dw.iter():
                    tag, val = child.tag, child.text
                    if not val: continue
                    if tag.endswith('dwellingId') or tag.endswith('ewid'): ewid = val
                    elif tag.endswith('noOfHabitableRooms') or tag.endswith('numberOfRooms'):
                        try: zimmer = float(val)
                        except: pass
                    elif tag.endswith('surfaceAreaOfDwelling') or tag.endswith('totalSurface') or tag.endswith('mainUsableArea'):
                        try: flaeche = float(val)
                        except: pass
                    elif tag.endswith('floor'): etage_code = val
                    elif tag.endswith('physicalId') or tag.endswith('adminId'): whgnr = val

                etage_text = translate_floor(etage_code)
                zim_str = f"{zimmer:g}" if zimmer > 0 else "?"
                bezeichnung = f"{zim_str} Zimmer Wohnung"
                if etage_text: bezeichnung += f" ({etage_text})"
                elif etage_code: bezeichnung += f" ({etage_code})"

                units.append({
                    'bezeichnung': bezeichnung,
                    'ewid': ewid if ewid else f"ph-{egid}",
                    'typ': 'whg',
                    'is_meta': False,
                    'zimmer': zimmer,
                    'flaeche': flaeche,
                    'etage': etage_text
                })
        return units
    except Exception as e:
        logger.error(f"Fehler bei GWR XML Abruf: {e}")
        return []

def sync_liegenschaft_with_gwr(liegenschaft):
    """
    Kapselt den gesamten Logik-Ablauf:
    EGID suchen, abspeichern und Einheiten vom Bund importieren.
    """
    result = {'egid_found': False, 'units_created': 0, 'error': None}

    try:
        # 1. EGID über die Adresse finden
        if not liegenschaft.egid:
            found = get_egid_from_address(liegenschaft.strasse, liegenschaft.plz, liegenschaft.ort)
            if found:
                liegenschaft.egid = found
                liegenschaft.save()
                result['egid_found'] = found

        # 2. Einheiten vom Bundesamt (BFS) laden
        if liegenschaft.egid and liegenschaft.einheiten.count() == 0:
            data = get_units_from_bfs(liegenschaft.egid)
            cnt = 0
            for i in data:
                if i.get('is_meta'):
                    if i.get('baujahr'):
                        liegenschaft.baujahr = i['baujahr']
                        liegenschaft.save()
                    continue

                Einheit.objects.create(
                    liegenschaft=liegenschaft,
                    bezeichnung=i['bezeichnung'],
                    ewid=i['ewid'],
                    zimmer=i['zimmer'],
                    etage=i['etage'],
                    flaeche_m2=i['flaeche'],
                    typ='whg'
                )
                cnt += 1
            result['units_created'] = cnt

    except Exception as e:
        result['error'] = str(e)

    return result

# --- 2. PORTFOLIO STATISTIKEN ---

def get_liegenschaft_stats(liegenschaft):
    """
    Berechnet die KPIs einer Liegenschaft (Leerstand, Mieteinnahmen).
    """
    einheiten = liegenschaft.einheiten.all()
    total_einheiten = einheiten.count()
    vermietet = sum(1 for e in einheiten if getattr(e, 'aktiver_vertrag', False))
    leerstand = total_einheiten - vermietet

    soll_miete = sum(float(getattr(e, 'nettomiete_aktuell', 0) or 0) + float(getattr(e, 'nebenkosten_aktuell', 0) or 0) for e in einheiten)
    ist_miete = sum(float(getattr(e, 'nettomiete_aktuell', 0) or 0) + float(getattr(e, 'nebenkosten_aktuell', 0) or 0) for e in einheiten if getattr(e, 'aktiver_vertrag', False))

    return {
        'total': total_einheiten,
        'vermietet': vermietet,
        'leerstand': leerstand,
        'soll_miete': soll_miete,
        'ist_miete': ist_miete
    }