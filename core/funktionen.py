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
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _


class UnbekannteFunktion(KeyError):
    """Ein Funktionsschlüssel, der nicht im Katalog steht."""


class FunktionGesperrt(PermissionError):
    """Die Funktion ist im Abonnement dieser Verwaltung nicht freigeschaltet.

    Wird von Diensten geworfen, die auch ohne Oberfläche laufen (Versand,
    Hintergrundläufe). Die Oberfläche fängt sie in `abo.middleware` und zeigt
    die Sperrseite mit dem Weg zum Upgrade statt einer 403 ohne Erklärung.
    """

    def __init__(self, schluessel):
        self.schluessel = schluessel
        super().__init__(f'Funktion {schluessel!r} ist nicht freigeschaltet.')


class GrenzeErreicht(Exception):
    """Eine Mengengrenze verhindert das Anlegen eines NEUEN Datensatzes.

    Bestehende Datensätze bleiben davon unberührt: Die Grenze begrenzt das
    Anlegen, nie das Lesen (docs/PHASE-3-ENTITLEMENTS.md §2 B).
    """

    def __init__(self, was, grenze):
        self.was = was
        self.grenze = grenze
        super().__init__(f'Grenze für {was!r} erreicht: {grenze}.')


# ---------------------------------------------------------------------------
# Katalog: jeder Schlüssel, den es gibt, mit Klartext.
# Erweitern heisst hier eintragen — sonst wirft `hat_funktion`.
# ---------------------------------------------------------------------------
FUNKTIONEN = {
    # ab Stufe «start», also in jeder Stufe. Was eine Verwaltung gesetzlich
    # oder betrieblich zwingend braucht, steht hier (docs/MARKT.md §5).
    'akten':                _('Akten lesen und bearbeiten'),
    'dokumente':            _('Dokumentenablage je Akte'),
    'monatslauf':           _('Sollstellung, Bankabgleich, Mahnlauf'),
    'fristenwaechter':      _('Prüfung von Terminen und Fristen gegen das Regelwerk'),
    'nebenkostenlauf':      _('Nebenkostenabrechnung als geführter Lauf'),
    'vor_ort':              _('Vor-Ort-Modus für Abnahme und Besichtigung'),
    'mieterportal':         _('Portalzugang für die Mieterschaft'),
    # Auskunft und Datenübergabe gehören in jede Stufe (DSG: Auskunftsrecht;
    # MARKT.md §7: «Alle Daten lesbar und exportierbar»). Der Schlüssel steht im
    # Katalog, damit die Sperrtabelle ihn kennt, nicht damit er sperrt.
    'datenexport':          _('Datenexport (Buchungsjournal, Mandatspaket, Auskunft)'),

    # ab Stufe «team»
    'faelle':               _('Fallmaschine: Vorgänge mit Schritten und Fristen'),
    'zulauf':               _('Posteingang mit Zuordnungsvorschlag'),
    'eigentuemerportal':    _('Portalzugang für die Eigentümerschaft'),
    # Zuschnitt der drei folgenden ist VORLÄUFIG: Sie liegen in «team», weil
    # das die Stufe ist, die heute jede Verwaltung hat. Wohin sie gehören, ist
    # eine Entscheidung des Betreibers (Bericht, Fachpunkt 1).
    'betreibung':           _('Betreibung: Rechtsöffnung, Forderungen, Kosten'),
    'datenimport':          _('Datenimport (Stammdaten und Salden aus anderen Programmen)'),
    'stweg':                _('Stockwerkeigentum: Versammlung, Beschlüsse, Fonds, Abrechnung'),

    # ab Stufe «professional»
    'mandatsrentabilitaet': _('Honorarertrag gegen erfassten Aufwand'),
    'schnittstellen':       _('Buchhaltungsexport, Portale, Kalender'),
}

# Zubuchbare Module. Stehen bewusst getrennt: Sie hängen nicht an der Stufe,
# sondern werden einzeln gebucht (Vorgabe Phase 3).
MODULE = {
    'signatur':             _('Digitale Unterschrift'),
    'belegerkennung':       _('OCR- und KI-Dokumentenerkennung'),
    'reporting_erweitert':  _('Eigene Auswertungen und Exportvorlagen'),
}

# ---------------------------------------------------------------------------
# Stufen. Jede Stufe enthält alles aus der vorherigen.
#
# Die Codes sind die Marktnamen aus docs/MARKT.md (Entscheid D7 in
# docs/PLAN-V7.md). Bis 29.09.2026 hiessen sie basis/aufbau/verwaltung/
# portfolio. Die Umstellung war verhaltensneutral: «team» enthält genau die
# zehn Schlüssel der früheren «verwaltung», «professional» genau die der
# früheren «portfolio» (docs/AUFTRAG-ABOSTUFEN.md).
#
# `monatslauf` steht bewusst in «start», nicht in «team»: Der Schlüssel trägt
# die Pflichtläufe Sollstellung, Bankabgleich, Mahnlauf, Zahllauf und MWST
# (faelle/management/commands/laeufe_planen.py). Eine Sperre darauf nähme
# einer Verwaltung Pflichtarbeit weg, nicht Komfort.
# ---------------------------------------------------------------------------
_AUFBAUEND = (
    ('start',        ('akten', 'dokumente', 'monatslauf', 'fristenwaechter',
                      'nebenkostenlauf', 'vor_ort', 'mieterportal', 'datenexport')),
    ('team',         ('faelle', 'zulauf', 'eigentuemerportal',
                      'betreibung', 'datenimport', 'stweg')),
    ('professional', ('mandatsrentabilitaet', 'schnittstellen')),
    # Enterprise unterscheidet sich über Grenzen und Betreuung, nicht über
    # Funktionen.
    ('enterprise',   ()),
)

STUFEN = {}
_bisher = ()
for _name, _neu in _AUFBAUEND:
    _bisher = _bisher + _neu
    STUFEN[_name] = frozenset(_bisher)
del _name, _neu, _bisher

STUFEN_REIHENFOLGE = tuple(name for name, _neu in _AUFBAUEND)

#: Produktnamen. Bleiben in jeder Sprache gleich, wie die Abo-Auswahl am
#: Modell (core/tests/test_auswahl_uebersetzt.py, BEWUSST_DEUTSCH).
STUFEN_NAMEN = {
    'start':        'Start',
    'team':         'Team',
    'professional': 'Professional',
    'enterprise':   'Enterprise',
}

# Mengengrenzen je Stufe. `None` heisst unbegrenzt. `einheiten` ist die im
# Grundpreis enthaltene Menge; darüber gelten die Zusatzpakete aus `PREISE`.
GRENZEN = {
    'start':        {'einheiten': 25,   'nutzer': 2},
    'team':         {'einheiten': 150,  'nutzer': 5},
    'professional': {'einheiten': 500,  'nutzer': 15},
    'enterprise':   {'einheiten': 2000, 'nutzer': None},
}

#: Welche Mengengrenzen es überhaupt gibt — abgeleitet, nicht zweitgeschrieben,
#: damit die Liste nicht neben `GRENZEN` herlaufen kann.
GRENZ_ARTEN = frozenset().union(*(werte.keys() for werte in GRENZEN.values()))

# ---------------------------------------------------------------------------
# Preise. VORLÄUFIG: aus den Wettbewerbspreisen abgeleitet, NICHT aus einer
# Kostenrechnung je Mandant (docs/MARKT.md §4, docs/PHASE-3-ENTITLEMENTS.md
# §7.1 «Struktur ja, Preise später»). Die Abo-Seite weist sie deshalb als
# Einführungspreise mit `PREISSTAND` aus.
#
# `zusatz_100`: Preis je angefangene 100 Einheiten über dem Grundumfang,
# `None` heisst: kein Zusatz möglich.
# `deckel`: höchste Einheitenzahl, die die Stufe mit Zusatzpaketen fasst,
# `None` heisst unbegrenzt. Der Deckel hält Professional davon ab, mit
# Zusatzpaketen billiger als Enterprise zu werden
# (MARKET_RESEARCH_COMPETITORS.md §4).
# ---------------------------------------------------------------------------
PREISE = {
    'start':        {'monat': Decimal('39'),  'zusatz_100': None,           'deckel': 25},
    'team':         {'monat': Decimal('119'), 'zusatz_100': Decimal('60'),  'deckel': 300},
    'professional': {'monat': Decimal('329'), 'zusatz_100': Decimal('45'),  'deckel': 1000},
    'enterprise':   {'monat': Decimal('749'), 'zusatz_100': Decimal('30'),  'deckel': None},
}

#: Rabatt bei jährlicher Abrechnung.
JAHRESRABATT = Decimal('0.15')

#: Datum der Preisliste, erscheint auf der Abo-Seite.
PREISSTAND = '29.09.2026'

#: Betreuung je Stufe. Keine Funktion, deshalb nicht im Katalog.
SUPPORT = {
    'start':        _('Support per E-Mail'),
    'team':         _('Support per E-Mail und Telefon'),
    'professional': _('Support per E-Mail und Telefon'),
    'enterprise':   _('Support mit SLA, Onboarding und Datenimport inklusive'),
}

#: Diese Stufe gilt für eine Verwaltung ohne gespeicherte Stufe (Stub-Objekte in
#: Tests, Organisation ohne `abo_plan`). Über die Einstellungen übersteuerbar,
#: damit die Sperrpfade testbar sind, ohne eine Organisation umzubauen.
VORGABE_STUFE = 'team'

#: Zahlungszustände einer Verwaltung (abo.Abonnement.zustand).
ZUSTAND_AKTIV = 'aktiv'
ZUSTAND_MAHNUNG = 'mahnung'
ZUSTAND_LESEMODUS = 'lesemodus'


def abonnement_von(organisation):
    """Die Abonnement-Zeile der Verwaltung, oder `None`.

    `None` heisst «nicht verwaltet»: Organisationen, die vor der
    Funktionsfreigabe entstanden oder ausserhalb des Onboardings angelegt
    wurden, haben keine Zeile und werden nicht eingeschränkt — weder bei
    Modulen noch bei Mengen noch im Zahlungszustand. Das ist die sichere
    Richtung für Bestand, und sie ist an dieser einen Stelle festgelegt.
    """
    if organisation is None:
        return None
    try:
        return organisation.abonnement
    except (ObjectDoesNotExist, AttributeError):
        return None


def _frei(organisation):
    """Bestandsschutz oder nicht verwaltet: nichts wird eingeschränkt."""
    abo = abonnement_von(organisation)
    return abo is None or abo.uneingeschraenkt


def stufe_von(organisation):
    """Die Abostufe einer Verwaltung — die EINE Stelle, die sie bestimmt.

    Quelle ist `Organisation.abo_plan`. Die Einstellung überschreibt sie
    (nur für Tests und Notfälle); fehlt beides, gilt `VORGABE_STUFE`.
    """
    if organisation is None:
        return None
    stufe = getattr(settings, 'SWISSIMMO_VORGABE_STUFE', None) \
        or getattr(organisation, 'abo_plan', None) or VORGABE_STUFE
    if stufe not in STUFEN:
        # Ohne diese Prüfung käme weiter unten ein nacktes `KeyError('premium')`
        # heraus — ohne Hinweis, woher der Wert stammt. Eine umbenannte oder
        # abgelaufene Stufe ist mit echten Abodaten ein realistischer Fall und
        # darf nicht als Rätsel ankommen.
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

    Freigeschaltet ist eine Funktion durch die Stufe, durch eine Zubuchung
    (`Abonnement.zusatzmodule`) oder durch Bestandsschutz. Die Zahlungssperre
    (Lesemodus) ist KEINE Funktionsfrage und steht in `darf_schreiben`.
    """
    if schluessel not in FUNKTIONEN and schluessel not in MODULE:
        raise UnbekannteFunktion(
            f'{schluessel!r} steht weder in FUNKTIONEN noch in MODULE. '
            f'Neue Funktionen gehören in den Katalog in core/funktionen.py.')
    if organisation is None:
        return False
    abo = abonnement_von(organisation)
    if abo is not None and abo.uneingeschraenkt:
        return True
    if schluessel in MODULE:
        # Zubuchbar, hängt nicht an der Stufe. Ohne Abonnement-Zeile offen.
        return abo is None or schluessel in (abo.zusatzmodule or [])
    stufe = stufe_von(organisation)
    if stufe is None:
        return False
    return schluessel in STUFEN[stufe] or (
        abo is not None and schluessel in (abo.zusatzmodule or []))


def zustand_von(organisation):
    """Zahlungszustand: 'aktiv', 'mahnung' oder 'lesemodus'. Ohne Zeile: aktiv."""
    abo = abonnement_von(organisation)
    return abo.zustand if abo is not None else ZUSTAND_AKTIV


def darf_schreiben(organisation):
    """False im Lesemodus (Zahlung lange überfällig). Lesen und Export bleiben."""
    return zustand_von(organisation) != ZUSTAND_LESEMODUS


def hintergrund_erlaubt(organisation):
    """Dürfen Läufe und Versand im Namen dieser Verwaltung laufen?

    Ein Mahnlauf, der nach dem Zahlungsausfall weiterläuft, verschickt Post im
    Namen einer Verwaltung, die dafür nicht mehr zahlt (MARKT.md §7: «Keine
    Hintergrundläufe, kein Versand»). Im Lesemodus ist die Antwort `False`.
    """
    return darf_schreiben(organisation)


def grenze(organisation, was):
    """Mengengrenze der Stufe, oder `None` für unbegrenzt.

    `was` ist 'einheiten' oder 'nutzer'.

    Die Prüfung des Schlüssels steht **vor** der Prüfung der Organisation —
    aus demselben Grund wie in `hat_funktion`: Ohne Organisation gäbe ein
    Tippfehler sonst schweigend 0 zurück, und 0 sieht aus wie eine echte
    Grenze. Gesperrt wäre dann alles, und niemand wüsste warum.

    Das ist die Grenze der Stufe (im Grundpreis enthalten). Wo das ANLEGEN
    endet, sagt `anlege_grenze`.
    """
    if was not in GRENZ_ARTEN:
        raise UnbekannteFunktion(
            f'{was!r} ist keine bekannte Mengengrenze. '
            f'Bekannt: {sorted(GRENZ_ARTEN)}')
    stufe = stufe_von(organisation)
    if stufe is None:
        return 0
    return GRENZEN[stufe][was]


def anlege_grenze(organisation, was):
    """Höchstzahl, bis zu der NEUE Datensätze angelegt werden dürfen, oder `None`.

    Bei Einheiten ist das der Deckel der Stufe (Grundumfang plus Zusatzpakete,
    die der Abrechnungslauf verrechnet), bei Nutzern die Grenze der Stufe.
    `None` heisst: keine Grenze — auch bei Bestandsschutz und nicht verwalteten
    Organisationen. Die Grenze begrenzt nur das Anlegen; was schon da ist,
    bleibt les- und exportierbar.
    """
    if was not in GRENZ_ARTEN:
        raise UnbekannteFunktion(
            f'{was!r} ist keine bekannte Mengengrenze. '
            f'Bekannt: {sorted(GRENZ_ARTEN)}')
    if organisation is None or _frei(organisation):
        return None
    stufe = stufe_von(organisation)
    if was == 'einheiten':
        return PREISE[stufe]['deckel']
    return GRENZEN[stufe][was]


def monatspreis(stufe, einheiten):
    """Monatspreis dieser Stufe für so viele Einheiten, ohne MWST und Rabatt.

    `None`, wenn die Stufe diese Menge nicht fassen kann: über dem Deckel,
    oder über dem Grundumfang einer Stufe ohne Zusatzpakete. Zusatzpakete
    werden je angefangene 100 Einheiten verrechnet.
    """
    if stufe not in PREISE:
        raise ImproperlyConfigured(
            f'{stufe!r} ist keine bekannte Abostufe. '
            f'Bekannt: {list(STUFEN_REIHENFOLGE)}.')
    preis = PREISE[stufe]
    if preis['deckel'] is not None and einheiten > preis['deckel']:
        return None
    ueber = max(0, einheiten - GRENZEN[stufe]['einheiten'])
    if not ueber:
        return preis['monat']
    if preis['zusatz_100'] is None:
        return None
    pakete = -(-ueber // 100)
    return preis['monat'] + pakete * preis['zusatz_100']


def passende_stufe(einheiten):
    """Die günstigste Stufe, die diese Einheitenzahl fasst.

    Bei gleichem Preis gewinnt die tiefere Stufe. Enterprise hat keinen
    Deckel, es gibt also immer eine Antwort.
    """
    preise = [(monatspreis(s, einheiten), i, s)
              for i, s in enumerate(STUFEN_REIHENFOLGE)]
    return min((p, i, s) for p, i, s in preise if p is not None)[2]
