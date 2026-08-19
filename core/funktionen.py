"""Funktionsfreigabe — die eine Stelle, an der entschieden wird, was eine
Verwaltung darf.

WARUM DIESES MODUL SCHON JETZT EXISTIERT

Die Vorgabe für Phase 3 lautet: Funktionsfreigabe über ein zentrales
Berechtigungssystem, nie über verstreute `if`-Abfragen im Code. Phase 4a baut
aber bereits Funktionen, die später abostufenabhängig sein werden — Fälle,
Läufe, Portale. Ohne diese Naht entstünden dabei genau die verstreuten
Abfragen, die Phase 3 danach wieder einsammeln müsste.

Deshalb steht hier ab sofort die Naht, und nur die Naht. Die Stufe einer
Verwaltung ist bis Phase 3 **fest hinterlegt** (siehe `stufe_von`). Wenn Phase 3
echte Abodaten bringt, ändert sich ausschliesslich diese eine Funktion — kein
Aufrufer.

WARUM EIN UNBEKANNTER SCHLÜSSEL EINEN FEHLER WIRFT

Ein Tippfehler in `hat_funktion(org, 'faelle_erweitert')` würde bei einer
Rückgabe von `False` stillschweigend eine Funktion sperren, die eigentlich frei
sein sollte. Das fällt niemandem auf — die Schaltfläche ist einfach weg. Ein
`UnbekannteFunktion` fällt sofort auf, und zwar im Test. Der Katalog unten ist
deshalb Pflicht, nicht Dokumentation.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class UnbekannteFunktion(KeyError):
    """Ein Funktionsschlüssel, der nicht im Katalog steht."""


# ---------------------------------------------------------------------------
# Katalog: jeder Schlüssel, den es gibt, mit Klartext.
# Erweitern heisst hier eintragen — sonst wirft `hat_funktion`.
# ---------------------------------------------------------------------------
FUNKTIONEN = {
    # Grundlage, in jeder Stufe enthalten
    'akten':                'Akten lesen und bearbeiten',
    'dokumente':            'Dokumentenablage je Akte',
    'monatslauf':           'Sollstellung, Bankabgleich, Mahnlauf',

    # ab Stufe «aufbau»
    'faelle':               'Fallmaschine: Vorgänge mit Schritten und Fristen',
    'fristenwaechter':      'Prüfung von Terminen und Fristen gegen das Regelwerk',
    'zulauf':               'Posteingang mit Zuordnungsvorschlag',

    # ab Stufe «verwaltung»
    'nebenkostenlauf':      'Nebenkostenabrechnung als geführter Lauf',
    'vor_ort':              'Vor-Ort-Modus für Abnahme und Besichtigung',
    'eigentuemerportal':    'Portalzugang für die Eigentümerschaft',
    'mieterportal':         'Portalzugang für die Mieterschaft',

    # ab Stufe «portfolio»
    'mandatsrentabilitaet': 'Honorarertrag gegen erfassten Aufwand',
    'schnittstellen':       'Buchhaltungsexport, Portale, Kalender',
}

# Zubuchbare Module. Stehen bewusst getrennt: Sie hängen nicht an der Stufe,
# sondern werden einzeln gebucht (Vorgabe Phase 3).
MODULE = {
    'signatur':             'Digitale Unterschrift',
    'belegerkennung':       'OCR- und KI-Dokumentenerkennung',
    'reporting_erweitert':  'Eigene Auswertungen und Exportvorlagen',
}

# ---------------------------------------------------------------------------
# Stufen. Jede Stufe enthält alles aus der vorherigen.
# ---------------------------------------------------------------------------
_AUFBAUEND = (
    ('basis',       ('akten', 'dokumente', 'monatslauf')),
    ('aufbau',      ('faelle', 'fristenwaechter', 'zulauf')),
    ('verwaltung',  ('nebenkostenlauf', 'vor_ort',
                     'eigentuemerportal', 'mieterportal')),
    ('portfolio',   ('mandatsrentabilitaet', 'schnittstellen')),
)

STUFEN = {}
_bisher = ()
for _name, _neu in _AUFBAUEND:
    _bisher = _bisher + _neu
    STUFEN[_name] = frozenset(_bisher)
del _name, _neu, _bisher

STUFEN_REIHENFOLGE = tuple(name for name, _ in _AUFBAUEND)

# Mengengrenzen je Stufe. `None` heisst unbegrenzt.
GRENZEN = {
    'basis':      {'einheiten': 60,  'nutzer': 1},
    'aufbau':     {'einheiten': 120, 'nutzer': 3},
    'verwaltung': {'einheiten': 250, 'nutzer': 5},
    'portfolio':  {'einheiten': 800, 'nutzer': 15},
}

#: Welche Mengengrenzen es überhaupt gibt — abgeleitet, nicht zweitgeschrieben,
#: damit die Liste nicht neben `GRENZEN` herlaufen kann.
GRENZ_ARTEN = frozenset().union(*(werte.keys() for werte in GRENZEN.values()))

#: Bis Phase 3 gilt diese Stufe für jede Verwaltung. Über die Einstellungen
#: übersteuerbar, damit die Sperrpfade überhaupt testbar sind.
VORGABE_STUFE = 'verwaltung'


def stufe_von(organisation):
    """Die Abostufe einer Verwaltung.

    **Bis Phase 3 fest hinterlegt.** Genau diese Funktion wird dort durch den
    Zugriff auf die echten Abodaten ersetzt; alles andere in diesem Modul und
    alle Aufrufer bleiben unverändert.
    """
    if organisation is None:
        return None
    stufe = getattr(settings, 'SWISSIMMO_VORGABE_STUFE', VORGABE_STUFE)
    if stufe not in STUFEN:
        # Ohne diese Prüfung käme weiter unten ein nacktes `KeyError('premium')`
        # heraus — ohne Hinweis, woher der Wert stammt. Ab Phase 3 liefert diese
        # Funktion echte Abodaten; eine umbenannte oder abgelaufene Stufe ist
        # dann ein realistischer Fall und darf nicht als Rätsel ankommen.
        raise ImproperlyConfigured(
            f'{stufe!r} ist keine bekannte Abostufe. '
            f'Bekannt: {sorted(STUFEN)}.')
    return stufe


def hat_funktion(organisation, schluessel):
    """Darf diese Verwaltung die genannte Funktion nutzen?

    Wirft `UnbekannteFunktion`, wenn der Schlüssel weder im Funktionskatalog
    noch bei den Modulen steht — ein Tippfehler soll auffallen und nicht
    stillschweigend sperren.

    Ohne Organisation (anonym, oder Kontext noch nicht gesetzt) ist die Antwort
    `False`. Das ist die sichere Richtung: im Zweifel nicht freigeben.
    """
    if schluessel in MODULE:
        return _hat_modul(organisation, schluessel)
    if schluessel not in FUNKTIONEN:
        raise UnbekannteFunktion(
            f'{schluessel!r} steht weder in FUNKTIONEN noch in MODULE. '
            f'Neue Funktionen gehören in den Katalog in core/funktionen.py.')
    stufe = stufe_von(organisation)
    if stufe is None:
        return False
    return schluessel in STUFEN[stufe]


def _hat_modul(organisation, schluessel):
    """Zubuchbares Modul. Bis Phase 3 sind alle Module aktiv."""
    if organisation is None:
        return False
    return True


def grenze(organisation, was):
    """Mengengrenze der Stufe, oder `None` für unbegrenzt.

    `was` ist 'einheiten' oder 'nutzer'.

    Die Prüfung des Schlüssels steht **vor** der Prüfung der Organisation —
    aus demselben Grund wie in `hat_funktion`: Ohne Organisation gäbe ein
    Tippfehler sonst schweigend 0 zurück, und 0 sieht aus wie eine echte
    Grenze. Gesperrt wäre dann alles, und niemand wüsste warum.
    """
    if was not in GRENZ_ARTEN:
        raise UnbekannteFunktion(
            f'{was!r} ist keine bekannte Mengengrenze. '
            f'Bekannt: {sorted(GRENZ_ARTEN)}')
    stufe = stufe_von(organisation)
    if stufe is None:
        return 0
    return GRENZEN[stufe][was]
