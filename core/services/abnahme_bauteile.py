"""Bauteile je Raumtyp für die Abnahme vor Ort.

Jeder Raum bekommt die Bauteile, die in ihm tatsächlich zu prüfen sind — eine
Küche hat Unter- und Oberschränke, Arbeitsplatte, Backofen und Kühlschrank, ein
Bad Lavabo, WC und Badewanne, ein Keller nur Boden, Decke, Wände und Türe.

Vorlage ist ein Abnahme-/Übergabeprotokoll aus der Praxis (Turmstrasse 5/7,
Bellach): Küche 22, Bad 25, Wohnzimmer 13, Zimmer 10, Korridor 6, Balkon 7,
Keller 5 Positionen — Wortlaut und Reihenfolge übernommen. Die Räume, die dort
nicht vorkamen (WC, Waschküche/Reduit, Technik, Garage), sind sinngemäss
ergänzt und als solche gekennzeichnet.

Der Raumtyp wird aus dem Raumnamen erkannt (`raumtyp`), nicht aus einer festen
Liste: «Küche Turmstrasse (saniert)», «Büro 1» und «Bad/WC» sind frei benannt.
"""
import re

# Gemeinsame Bauteile (Wortlaut wie im Praxisprotokoll)
_FENSTER = ['Fenster/Fenstersims', 'Jalousie-/Rollläden', 'Gurten/Kurbeln/Motoren']

KUECHE = [
    'Boden', 'Decke', 'Wände', 'Wandplatten', *_FENSTER, 'Leuchten', 'Schalter/Steckdosen',
    'Radiator/Heizkörper', 'Küchenschränke unten', 'Küchenschränke oben',
    'Küchenabdeckung (Arbeitsplatte)', 'Spülbecken', 'Armaturen/Batterie (Wasserhahnen)',
    'Kochherd', 'Dampfabzug/Filter', 'Backofen', 'Kühlschrank/Gefrierfach', 'Geschirrspüler',
    'Kehrichteimer/Grüneimer', 'Fugendichtungen/Kittfugen',
]
BAD = [
    'Boden', 'Decke', 'Wände', 'Wandplatten', *_FENSTER, 'Leuchten', 'Schalter/Steckdosen',
    'Türe', 'Türrahmen', 'Radiator/Heizkörper', 'Lavabo', 'Armaturen/Batterie Lavabo', 'WC/Bidet',
    'Spülkasten', 'Badewanne/Dusche', 'Vorhangstange', 'Brause/Duschenschlauch', 'Spiegelschrank',
    'Zahnglas', 'Seifenschale', 'Handtuchstange', 'Lüftung/Ventilator', 'Badezimmermöbel',
]
WOHNZIMMER = [
    'Boden', 'Decke', 'Wände', *_FENSTER, 'Leuchten', 'Schalter/Steckdosen',
    'Telefondose/Glasfaserdose', 'Türe', 'Türrahmen', 'Radiator/Heizkörper', 'Wandschrank',
]
ZIMMER = [
    'Boden', 'Decke', 'Wände', *_FENSTER, 'Schalter/Steckdosen', 'Türe', 'Türrahmen',
    'Radiator/Heizkörper',
]
KORRIDOR = ['Boden', 'Decke', 'Wände', 'Gegensprechanlage', 'Haustüre', 'Schalter/Steckdosen']
BALKON = [
    'Boden', 'Decke', 'Wände', 'Brüstung', 'Sonnenstoren', 'Gurten/Kurbeln/Motoren',
    'Schalter/Steckdosen',
]
KELLER = ['Boden', 'Decke', 'Wände', 'Türe', 'Türrahmen']

# Sinngemäss ergänzt (nicht im Praxisprotokoll)
WC = [
    'Boden', 'Decke', 'Wände', 'Wandplatten', 'Fenster/Fenstersims', 'Leuchten', 'Schalter/Steckdosen',
    'Türe', 'Türrahmen', 'Radiator/Heizkörper', 'WC/Bidet', 'Spülkasten', 'Lavabo',
    'Lüftung/Ventilator',
]
WASCHKUECHE = [
    'Boden', 'Decke', 'Wände', 'Leuchten', 'Schalter/Steckdosen', 'Türe', 'Türrahmen',
    'Waschmaschine', 'Tumbler/Trockner', 'Waschbecken/Ausguss',
]
TECHNIK = [
    'Boden', 'Wände', 'Türe', 'Heizung/Wärmeerzeuger', 'Boiler/Warmwasserspeicher',
    'Sicherungskasten/Elektroverteilung',
]
GARAGE = ['Boden', 'Decke', 'Wände', 'Garagentor/Antrieb', 'Leuchten', 'Schalter/Steckdosen', 'Türe']
ALLGEMEIN = [
    'Boden', 'Decke', 'Wände', 'Fenster/Fenstersims', 'Türe', 'Türrahmen', 'Leuchten',
    'Schalter/Steckdosen',
]

BAUTEILE = {
    'kueche': KUECHE, 'bad': BAD, 'wc': WC, 'wohnzimmer': WOHNZIMMER, 'zimmer': ZIMMER,
    'korridor': KORRIDOR, 'balkon': BALKON, 'keller': KELLER, 'waschkueche': WASCHKUECHE,
    'technik': TECHNIK, 'garage': GARAGE, 'allgemein': ALLGEMEIN,
}

# Reihenfolge ist Bedeutung: «Waschküche» enthält «küche», «Gäste-WC» ist kein Bad.
_ERKENNUNG = [
    ('waschkueche', r'waschk[üu]e?che|reduit'),
    ('kueche', r'k[üu]e?che|kochnische'),
    ('bad', r'\bbad|dusche'),
    ('wc', r'\bwc\b|toilette'),
    ('technik', r'heizung|technik|haustechnik'),
    ('garage', r'garage|parkplatz|einstellhalle|carport'),
    ('wohnzimmer', r'wohn|stube|salon|essen|esszimmer'),
    ('korridor', r'korridor|eingang|entr[ée]e|flur|diele'),
    ('balkon', r'balkon|terrasse|loggia|sitzplatz'),
    ('keller', r'keller|estrich|abstell|dachboden'),
    ('zimmer', r'zimmer|schlaf|b[üu]e?ro|kinder|arbeit|g[äa]ste'),
]


def raumtyp(name):
    """Der Raumtyp zu einem frei benannten Raum; `allgemein`, wenn keiner passt."""
    n = (name or '').casefold()
    for typ, muster in _ERKENNUNG:
        if re.search(muster, n):
            return typ
    return 'allgemein'


def _schluessel(text):
    return ''.join(ch for ch in (text or '').casefold() if ch.isalpha())


def _erstes_wort(text):
    return next(iter(re.findall(r'[^\W\d_]+', (text or '').casefold())), '')


def _gleich(bauteil, element):
    """Ist das Raumbuch-Element dasselbe Bauteil? Erstes Wort gleich oder das eine
    im anderen enthalten («Wände / Anstrich» ~ «Wände», «Bodenbelag» ~ «Boden»)."""
    a, b = _schluessel(bauteil), _schluessel(element)
    if len(a) < 4 or len(b) < 4:
        return False
    if a in b or b in a:
        return True
    wa, wb = _erstes_wort(bauteil), _erstes_wort(element)
    return len(wa) >= 5 and wa == wb


def bauteile_fuer_raum(name, elemente=()):
    """Die Bauteile eines Raums als Liste von `(Bezeichnung, Raumbuch-Element|None)`.

    Ausgangspunkt ist die Liste des Raumtyps. Hat die Einheit im Raumbuch ein
    passendes Element, ersetzt es den Standardeintrag (der Zeitwert-Bezug bleibt);
    Elemente ohne Entsprechung kommen hinten dazu — ein Raumbuch, das nur den
    Backofen kennt, soll den Raum nicht auf den Backofen verkleinern."""
    restliche = list(elemente)
    ergebnis = []
    for bezeichnung in BAUTEILE[raumtyp(name)]:
        treffer = next((e for e in restliche if _gleich(bezeichnung, e.kategorie)), None)
        if treffer is not None:
            restliche.remove(treffer)
            zusatz = f' – {treffer.bezeichnung}' if treffer.bezeichnung else ''
            ergebnis.append((bezeichnung + zusatz, treffer))
        else:
            ergebnis.append((bezeichnung, None))
    for e in restliche:
        ergebnis.append((e.kategorie + (f' – {e.bezeichnung}' if e.bezeichnung else ''), e))
    return ergebnis
