"""Raum-/Ausstattungskatalog (Vorlagen) und Standard-Lebensdauern.

- RAUM_KATALOG: pro Raumtyp die typischen Ausstattungselemente, damit die
  Erfassung schnell geht (Standardliste laden, dann je Element anpassen —
  Marke/Modell/Neuwert/Einbaudatum ergänzen).
- STANDARD_LEBENSDAUER: gängige Nutzungsdauern (Jahre) je Kategorie, angelehnt
  an die paritätische Lebensdauertabelle (Mieterverband/HEV). Bewusst als
  Startwerte gedacht — in der App editierbar, offizielle Version dort pflegen.

Konsistenz: Jeder Innenraum enthält denselben Satz gemeinsamer Bauteile
(Wände, Decke, Fenster/Fensterbank/Storen, Tür, Beleuchtung, Lichtschalter,
Steckdosen) plus die raumspezifischen Elemente — so ist der Katalog überall
gleich aufgebaut und vollständig.
"""

# Gemeinsame Bauteile für Innenräume (überall gleich → konsistente Erfassung).
# (Kategorie, Standard-Lebensdauer-Jahre)
_ALLGEMEIN_ELEKTRO = [
    ('Beleuchtung', 15), ('Lichtschalter', 25), ('Steckdosen', 25),
]
_INNEN_BASIS = [
    ('Wände / Anstrich', 8), ('Decke / Anstrich', 8),
    ('Fenster', 30), ('Fensterbank', 30), ('Storen / Rollladen', 25),
    ('Zimmertür', 30),
] + _ALLGEMEIN_ELEKTRO

# Raumtyp -> Liste von (Kategorie, Standard-Lebensdauer-Jahre)
RAUM_KATALOG = {
    'Küche': [
        ('Küchenkombination / Korpus', 25), ('Arbeitsplatte', 20),
        ('Kochherd / Glaskeramik', 15), ('Backofen', 15), ('Mikrowelle', 12),
        ('Dampfabzug / Ventilator', 15), ('Geschirrspüler', 12),
        ('Kühlschrank / Gefrierteil', 15), ('Spüle / Becken', 25),
        ('Küchenarmatur', 20), ('Spritzschutz / Wandabschluss', 20),
        ('Wände / Anstrich', 8), ('Decke / Anstrich', 8), ('Bodenbelag', 20),
        ('Fenster', 30), ('Fensterbank', 30), ('Storen / Rollladen', 25),
        ('Küchentür', 30),
    ] + _ALLGEMEIN_ELEKTRO,
    'Bad / WC': [
        ('Badewanne', 35), ('Dusche / Duschwanne', 30), ('Duschabtrennung / Duschwand', 20),
        ('Lavabo / Waschbecken', 35), ('WC / Spülkasten', 35),
        ('Armaturen', 20), ('Spiegelschrank', 15), ('Badmöbel / Unterschrank', 20),
        ('Wandplatten', 30), ('Bodenplatten', 30), ('Silikonfugen', 5),
        ('Ventilator / Entlüftung', 15), ('Accessoires / Handtuchhalter', 15),
        ('Decke / Anstrich', 8), ('Fenster', 30), ('Badezimmertür', 30),
    ] + _ALLGEMEIN_ELEKTRO,
    'Wohnzimmer': [
        ('Bodenbelag / Parkett', 25), ('Teppich', 10),
        ('Heizkörper / Radiator', 30), ('Balkontür', 30),
    ] + _INNEN_BASIS,
    'Zimmer': [
        ('Bodenbelag / Parkett', 25), ('Teppich', 10),
        ('Einbauschrank', 25), ('Heizkörper / Radiator', 30),
    ] + _INNEN_BASIS,
    'Korridor / Entrée': [
        ('Bodenbelag', 20), ('Einbauschrank / Garderobe', 25),
        ('Wohnungseingangstür', 30), ('Gegensprechanlage / Video', 20),
        ('Sicherungskasten / Elektroverteilung', 30),
        ('Wände / Anstrich', 8), ('Decke / Anstrich', 8),
    ] + _ALLGEMEIN_ELEKTRO,
    'Reduit / Waschküche': [
        ('Waschmaschine', 15), ('Tumbler / Trockner', 15),
        ('Waschbecken / Ausguss', 25), ('Regale / Tablare', 20),
        ('Wände / Anstrich', 8), ('Bodenbelag', 20), ('Tür', 30),
    ] + _ALLGEMEIN_ELEKTRO,
    'Keller / Estrich': [
        ('Kellerabteil / Lattenverschlag', 30), ('Regale / Tablare', 20),
        ('Wände', 8), ('Bodenbelag', 20), ('Kellertür', 30),
        ('Beleuchtung', 15), ('Lichtschalter', 25),
    ],
    'Balkon / Terrasse': [
        ('Bodenbelag / Plattenbelag', 20), ('Geländer / Brüstung', 40),
        ('Storen / Markise', 20), ('Sichtschutz / Trennwand', 20),
        ('Sonnenschutz-Motor', 15), ('Aussenbeleuchtung', 15),
        ('Steckdose (aussen)', 25), ('Wasseranschluss (aussen)', 25),
    ],
    'Heizung / Technik': [
        ('Heizung / Wärmeerzeuger', 30), ('Heizkörper / Radiatoren', 30),
        ('Bodenheizung-Verteiler', 30), ('Boiler / Warmwasserspeicher', 20),
        ('Lüftungsanlage', 20), ('Rauchmelder', 10),
        ('Wasserzähler / Zähler', 15), ('Sicherungskasten', 30),
    ],
}

RAUMTYPEN = list(RAUM_KATALOG.keys())

# Kategorie -> Jahre (aggregiert aus dem Katalog, für die Lebensdauertabelle)
STANDARD_LEBENSDAUER = {}
for _elemente in RAUM_KATALOG.values():
    for _kat, _jahre in _elemente:
        if _jahre and _kat not in STANDARD_LEBENSDAUER:
            STANDARD_LEBENSDAUER[_kat] = _jahre


def seed_lebensdauer():
    """Legt fehlende Standard-Lebensdauern an (idempotent). Gibt Anzahl neu zurück."""
    from portfolio.models import Lebensdauer
    n = 0
    for kat, jahre in STANDARD_LEBENSDAUER.items():
        _, created = Lebensdauer.objects.get_or_create(
            kategorie=kat, defaults={'jahre': jahre, 'bemerkung': 'Standardwert (anpassbar)'})
        if created:
            n += 1
    return n
