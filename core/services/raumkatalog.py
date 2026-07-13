"""Raum-/Ausstattungskatalog (Vorlagen) und Standard-Lebensdauern.

- RAUM_KATALOG: pro Raumtyp die typischen Ausstattungselemente, damit die
  Erfassung schnell geht (Standardliste laden, dann anpassen).
- STANDARD_LEBENSDAUER: gängige Nutzungsdauern (Jahre) je Kategorie, angelehnt
  an die paritätische Lebensdauertabelle (Mieterverband/HEV). Bewusst als
  Startwerte gedacht — in der App editierbar, offizielle Version dort pflegen.
"""

# Raumtyp -> Liste von (Kategorie, Standard-Lebensdauer-Jahre|None)
RAUM_KATALOG = {
    'Küche': [
        ('Küchenkombination', 25), ('Kochherd / Glaskeramik', 15), ('Backofen', 15),
        ('Dampfabzug', 15), ('Geschirrspüler', 12), ('Kühlschrank', 15),
        ('Spüle / Armatur', 20), ('Arbeitsplatte', 20), ('Wände', 8),
        ('Bodenbelag', 20), ('Beleuchtung', 15), ('Lichtschalter', 25),
        ('Steckdosen', 25), ('Fensterbank', 30), ('Storen / Rollladen', 25),
    ],
    'Bad / WC': [
        ('Badewanne', 35), ('Dusche / Duschwand', 20), ('Lavabo', 35), ('WC', 35),
        ('Armaturen', 20), ('Spiegelschrank', 15), ('Wandplatten', 30),
        ('Bodenplatten', 30), ('Ventilator / Entlüftung', 15), ('Beleuchtung', 15),
        ('Lichtschalter', 25), ('Steckdosen', 25),
    ],
    'Zimmer': [
        ('Wände / Anstrich', 8), ('Bodenbelag / Parkett', 25), ('Teppich', 10),
        ('Decke', 8), ('Fenster', 30), ('Fensterbank', 30), ('Storen / Rollladen', 25),
        ('Beleuchtung', 15), ('Lichtschalter', 25), ('Steckdosen', 25), ('Zimmertür', 30),
    ],
    'Wohnzimmer': [
        ('Wände / Anstrich', 8), ('Bodenbelag / Parkett', 25), ('Decke', 8),
        ('Fenster', 30), ('Fensterbank', 30), ('Storen / Rollladen', 25),
        ('Beleuchtung', 15), ('Lichtschalter', 25), ('Steckdosen', 25),
    ],
    'Korridor / Entrée': [
        ('Wände / Anstrich', 8), ('Bodenbelag', 20), ('Einbauschrank', 25),
        ('Wohnungstür', 30), ('Beleuchtung', 15), ('Lichtschalter', 25),
        ('Steckdosen', 25), ('Gegensprechanlage', 20),
    ],
    'Reduit / Keller': [
        ('Waschmaschine', 15), ('Tumbler', 15), ('Regale', 20), ('Beleuchtung', 15),
        ('Wände', 8), ('Bodenbelag', 20),
    ],
    'Balkon / Terrasse': [
        ('Bodenbelag', 20), ('Geländer', 40), ('Storen / Markise', 20),
        ('Beleuchtung', 15), ('Steckdose (aussen)', 25),
    ],
    'Allgemein': [
        ('Heizung / Radiatoren', 30), ('Boiler', 20), ('Rauchmelder', 10),
        ('Zähler', 15),
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
