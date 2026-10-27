"""Kantons-Erkennung + Schlichtungsbehörden-Register für die amtlichen Formulare.

Die Formularstruktur ist bundesrechtlich (OR/VMWG) überall gleich — pro Kanton
unterscheidet sich der Schlichtungsbehörden-Block (Seite 2) und der Kantonsname.

Primär wird das Kantons-Feld der Liegenschaft verwendet; fehlt es, greift eine
grobe PLZ-Heuristik. Ist der Kanton nicht exakt hinterlegt, wird ein generischer
(klar als solcher gekennzeichneter) Block verwendet — es werden KEINE Adressen
geraten."""

KANTON_NAMEN = {
    'AG': 'Aargau', 'AI': 'Appenzell Innerrhoden', 'AR': 'Appenzell Ausserrhoden',
    'BE': 'Bern', 'BL': 'Basel-Landschaft', 'BS': 'Basel-Stadt', 'FR': 'Freiburg',
    'GE': 'Genf', 'GL': 'Glarus', 'GR': 'Graubünden', 'JU': 'Jura', 'LU': 'Luzern',
    'NE': 'Neuenburg', 'NW': 'Nidwalden', 'OW': 'Obwalden', 'SG': 'St. Gallen',
    'SH': 'Schaffhausen', 'SO': 'Solothurn', 'SZ': 'Schwyz', 'TG': 'Thurgau',
    'TI': 'Tessin', 'UR': 'Uri', 'VD': 'Waadt', 'VS': 'Wallis', 'ZG': 'Zug',
    'ZH': 'Zürich',
}

# Grobe PLZ→Kanton-Heuristik (nur Fallback, wenn Liegenschaft.kanton leer ist).
#
# DIE BEREICHE ÜBERLAPPEN, UND DAS IST DER PUNKT (Befund G, 26.10.2026)
#
# Bis zu dieser Fassung gewann der erste passende Bereich: 1201 Genève wurde
# Waadt, 8200 Schaffhausen Zürich, 3920 Zermatt Bern — und mit ihnen Kantons-
# formular, Schlichtungsbehörde und Formularpflicht. Die Postleitzahlen folgen
# den Postkreisen, nicht den Kantonsgrenzen; eine Tabelle grober Bereiche kann
# das nicht auflösen. Die Bereiche bleiben, wie sie sind — sie zu «verbessern»
# hiesse, Grenzen zu raten. Liegt eine PLZ in Bereichen MEHRERER Kantone, gibt
# die Heuristik KEINEN Kanton zurück, und die Oberfläche fragt nach.
_PLZ_RANGES = [
    (1000, 1299, 'VD'), (1300, 1399, 'VD'), (1400, 1499, 'VD'),
    (1200, 1299, 'GE'), (1500, 1599, 'FR'), (1600, 1699, 'FR'),
    (1700, 1799, 'FR'), (1800, 1899, 'VD'), (1900, 1999, 'VS'),
    (2000, 2099, 'NE'), (2300, 2399, 'NE'), (2500, 2599, 'BE'),
    (2800, 2899, 'JU'), (2900, 2999, 'JU'),
    (3000, 3999, 'BE'), (3900, 3999, 'VS'),
    (4000, 4099, 'BS'), (4100, 4199, 'BL'), (4200, 4299, 'BL'),
    (4300, 4499, 'AG'), (4500, 4699, 'SO'), (4800, 4899, 'AG'),
    (5000, 5999, 'AG'),
    (6000, 6099, 'LU'), (6100, 6299, 'LU'), (6300, 6399, 'ZG'),
    (6400, 6499, 'SZ'), (6460, 6499, 'UR'), (6500, 6999, 'TI'),
    (6600, 6699, 'TI'), (6370, 6399, 'NW'), (6050, 6099, 'OW'),
    (7000, 7999, 'GR'),
    (8000, 8099, 'ZH'), (8100, 8499, 'ZH'), (8200, 8299, 'SH'),
    (8500, 8599, 'TG'), (8600, 8999, 'ZH'), (8700, 8999, 'ZH'),
    (9000, 9099, 'SG'), (9100, 9199, 'AR'), (9050, 9059, 'AI'),
    (9200, 9499, 'SG'), (9500, 9599, 'SG'), (8750, 8999, 'GL'),
]


def plz_kantone(plz):
    """Alle Kantone, in deren Bereich die PLZ fällt (sortiert) — leer, wenn keiner."""
    try:
        p = int(str(plz).strip()[:4])
    except (ValueError, TypeError):
        return []
    return sorted({kt for lo, hi, kt in _PLZ_RANGES if lo <= p <= hi})


def plz_to_kanton(plz):
    """Der Kanton zur PLZ, wenn die Heuristik ihn EINDEUTIG kennt — sonst None.

    None heisst «nicht bestimmbar»: kein Bereich oder mehrere Kantone. Wer
    wissen will, welche in Frage kommen, fragt `plz_kantone`."""
    kandidaten = plz_kantone(plz)
    return kandidaten[0] if len(kandidaten) == 1 else None


def kanton_fuer_liegenschaft(lg):
    """Kanton-Code (2 Zeichen) oder None. Priorität: Feld an der Liegenschaft,
    sonst die PLZ — aber nur, wenn sie eindeutig ist."""
    if lg is None:
        return None
    kt = (getattr(lg, 'kanton', '') or '').strip().upper()
    if kt in KANTON_NAMEN:
        return kt
    return plz_to_kanton(getattr(lg, 'plz', ''))


def formular_kanton(lg):
    """Der Kanton für ein AMTLICHES Formular — nur aus dem Feld, nie aus der PLZ.

    Ein Formular des falschen Kantons nennt die falsche Schlichtungsbehörde
    und ist kein genehmigtes Formular; die Mitteilung wäre nichtig. Darum
    genügt hier auch eine eindeutige PLZ nicht: Sie ist eine Vermutung, und
    für diese eine Angabe verlangt der Bestand Gewissheit. None = nicht erfasst.
    """
    if lg is None:
        return None
    kt = (getattr(lg, 'kanton', '') or '').strip().upper()
    return kt if kt in KANTON_NAMEN else None


# ------------------------------------------------------------------
# Schlichtungsbehörden-Register (exakt hinterlegte Kantone).
# Wert = Liste von (Amtei/Bezeichnung, Adresse, Telefon).
# Für Kantone mit mehreren Bezirken (z.B. SO) → Funktion plz -> Liste.
# ------------------------------------------------------------------
_SO_ALLE = [
    ("Amtei Solothurn-Lebern", "Schlichtungsbehörde für Miete und Pacht Solothurn-Lebern, Rötistrasse 4, 4501 Solothurn", "Tel. 032 627 75 27"),
    ("Amtei Bucheggberg-Wasseramt", "Schlichtungsbehörde für Miete und Pacht Bucheggberg-Wasseramt, Rötistrasse 4, 4501 Solothurn", "Tel. 032 627 75 27"),
    ("Amtei Thal-Gäu", "Schlichtungsbehörde für Miete und Pacht Thal-Gäu, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 062 311 91 61"),
    ("Amtei Olten-Gösgen", "Schlichtungsbehörde für Miete und Pacht Olten-Gösgen, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 062 311 86 44"),
    ("Amtei Dorneck-Thierstein", "Schlichtungsbehörde für Miete und Pacht Dorneck-Thierstein, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 061 785 77 20"),
]

# Kanton Bern: Schlichtungsbehörden in Miet- und Pachtsachen bei den vier
# Regionalgerichten. Der Vermieter reicht bei der für den Ort der gelegenen Sache
# zuständigen regionalen Schlichtungsbehörde ein (Art. 200 ZPO i.V.m. kant. EG ZPO).
_BE_ALLE = [
    ("Region Bern-Mittelland", "Schlichtungsbehörde Miete/Pacht, Regionalgericht Bern-Mittelland, Amthaus, Hodlerstrasse 7, 3011 Bern", "Tel. 031 635 47 47"),
    ("Region Emmental-Oberaargau", "Schlichtungsbehörde Miete/Pacht, Regionalgericht Emmental-Oberaargau, Dunantstrasse 1, 3400 Burgdorf", "Tel. 034 420 33 11"),
    ("Region Oberland", "Schlichtungsbehörde Miete/Pacht, Regionalgericht Oberland, Scheibenstrasse 11, 3600 Thun", "Tel. 033 225 97 00"),
    ("Region Berner Jura-Seeland", "Schlichtungsbehörde Miete/Pacht, Regionalgericht Berner Jura-Seeland, Spitalstrasse 14, 2502 Biel/Bienne", "Tel. 032 346 12 00"),
]

# Kanton Zürich: Mietschlichtungsbehörden je Bezirk. Nur die grossen, gut
# dokumentierten Behörden sind exakt hinterlegt; für nicht abgedeckte PLZ fällt
# der Block ehrlich auf den generischen Hinweis zurück (keine geratene Adresse).
_ZH_BEHOERDEN = {
    'zuerich': ("Bezirk Zürich", "Schlichtungsbehörde in Mietsachen des Bezirkes Zürich, Badenerstrasse 90, Postfach, 8004 Zürich", "Tel. 044 248 016 0"),
    'winterthur': ("Bezirk Winterthur", "Schlichtungsbehörde in Mietsachen des Bezirkes Winterthur, Hermann-Götz-Strasse 24, 8400 Winterthur", "Tel. 052 268 12 00"),
}


def _zh_resolver(plz):
    """Zuständige Zürcher Bezirks-Schlichtungsbehörde nach PLZ; None wenn nicht
    exakt abgedeckt (→ generischer Fallback)."""
    try:
        p = int(str(plz).strip()[:4])
    except (ValueError, TypeError):
        return None
    if 8000 <= p <= 8099:
        return [_ZH_BEHOERDEN['zuerich']]
    if 8400 <= p <= 8419:
        return [_ZH_BEHOERDEN['winterthur']]
    return None


SCHLICHTUNG_REGISTER = {
    'SO': _SO_ALLE,   # Kanton exakt hinterlegt (aus amtlichem Formular)
    'BE': _BE_ALLE,   # 4 regionale Schlichtungsbehörden (Ort der gelegenen Sache)
    'ZH': _zh_resolver,  # PLZ-Resolver je Bezirk (grosse Bezirke exakt)
    # Weitere Kantone werden hier ergänzt, sobald die exakten Adressen vorliegen.
}


def schlichtung_block(lg):
    """Gibt (kanton_code, kanton_name, [(bezeichnung, adresse, telefon), …], exakt: bool) zurück.
    exakt=False → generischer Platzhalter, Adresse muss noch verifiziert/ergänzt werden."""
    kt = kanton_fuer_liegenschaft(lg)
    name = KANTON_NAMEN.get(kt, '')
    eintrag = SCHLICHTUNG_REGISTER.get(kt)
    if eintrag:
        behoerden = eintrag(getattr(lg, 'plz', '')) if callable(eintrag) else eintrag
        if behoerden:   # Resolver kann None liefern (PLZ nicht abgedeckt) → Fallback
            return kt, name, behoerden, True
    # Generischer Fallback (nichts erfunden)
    ort = getattr(lg, 'ort', '') if lg else ''
    generisch = [(
        f"Schlichtungsbehörde für Miete und Pacht des Kantons {name or kt or '—'}",
        f"am Ort der gelegenen Sache ({ort})" if ort else "am Ort der gelegenen Sache",
        "(Adresse im amtlichen Verzeichnis des Kantons prüfen)",
    )]
    return kt, name, generisch, False
