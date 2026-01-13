import requests
import segno
import io
import base64

def get_units_from_bfs(egid):
    """
    Holt Wohnungsdaten direkt vom offiziellen BFS GWR Layer.
    """
    # Wir nutzen den Feature-Service, der stabiler für EGID-Abfragen ist
    url = "https://api3.geo.admin.ch/rest/services/api/MapServer/find"
    params = {
        'layer': 'ch.bfs.gebaeude_wohnungs_register-wohnungen',
        'searchText': str(egid),
        'searchField': 'egid',
        'returnGeometry': 'false',
        'sr': '2056'
    }

    units = []
    try:
        # Timeout erhöht auf 10 Sekunden, da GWR manchmal langsam ist
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])

            for item in results:
                attr = item.get('attributes', {})
                # BFS Bezeichnungen:
                # wanzj = Zimmeranzahl, wstwk = Stockwerk, warea = Fläche
                units.append({
                    'bezeichnung': f"Whg {attr.get('wewid', 'Neu')} - {attr.get('wanzj', '?')} Zi",
                    'zimmer': attr.get('wanzj') or 0,
                    'etage': attr.get('wstwk') or 0,
                    'flaeche': attr.get('warea') or 0
                })
        return units
    except Exception as e:
        print(f"Fehler beim GWR-Abruf: {e}")
        return []

# --- QR Code & EGID-Suche bleiben gleich ---
def generate_swiss_qr_base64(iban, name, strasse, ort, betrag, referenz):
    qr_data = ["SPC", "0200", "1", iban.replace(" ", ""), "S", name, strasse, ort, "", "", "", "", "CHF", str(betrag), "", "S", referenz, "Mietzinszahlung", "EPD"]
    qr_string = "\r\n".join(qr_data)
    qr = segno.make(qr_string, error='M')
    buff = io.BytesIO()
    qr.save(buff, kind='png', scale=4)
    return base64.b64encode(buff.getvalue()).decode()

def get_egid_from_address(strasse, plz, ort):
    url = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
    params = {'searchText': f"{strasse} {plz} {ort}", 'type': 'locations', 'origins': 'address', 'limit': 1}
    try:
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get('results'):
                return data['results'][0]['attrs'].get('egid')
    except: pass
    return None