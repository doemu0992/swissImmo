"""Anschrift und IBAN des Lieferanten für die Zahlungsdatei.

Die Swiss Payment Standards verlangen ab dem 14.11.2026 in der pain.001 eine
strukturierte Anschrift (mindestens Ort und Land) für Zahlungspflichtigen und
Begünstigten. Der Kreditor (`KreditorenRechnung`) trägt sie in
`lieferant_strasse`, `lieferant_hausnummer`, `lieferant_plz`, `lieferant_ort`
und `lieferant_land`; das Lieferantenprofil (`LieferantProfil`) merkt sich die
zuletzt freigegebene Anschrift unter `strasse` … `land`.

Dieses Modul kennt beide Seiten und hält die Regeln an EINER Stelle: was als
vollständig gilt, wie eine Anschrift aus dem Profil in die Rechnung kommt und
wann eine IBAN vom Gelernten abweicht.
"""
import re

from django.utils.translation import gettext as _

from core.services.iban import normalisiere_iban

#: Reihenfolge wie im ISO-Schema (`PostalAddress24`): Strasse, Hausnummer, PLZ,
#: Ort, Land.
FELDER = ('strasse', 'hausnummer', 'plz', 'ort', 'land')

#: Längen des ISO-Schemas (Max70Text, Max16Text, Max16Text, Max35Text,
#: CountryCode). Dieselben stehen an den Modellfeldern.
LAENGEN = {'strasse': 70, 'hausnummer': 16, 'plz': 16, 'ort': 35, 'land': 2}

_LAND = re.compile(r'^[A-Z]{2}$')


def adresse_von_rechnung(k):
    """Die Anschrift einer Kreditorenrechnung als Wörterbuch ohne Präfix."""
    return {f: (getattr(k, f'lieferant_{f}', '') or '').strip() for f in FELDER}


def adresse_von_profil(profil):
    return {f: (getattr(profil, f, '') or '').strip() for f in FELDER} if profil else {}


def adresse_setzen(k, adresse):
    """Schreibt die Anschrift in die Felder der Rechnung (ohne zu speichern)."""
    for f in FELDER:
        wert = (adresse.get(f) or '').strip()
        if f == 'land':
            wert = wert.upper() or 'CH'
        setattr(k, f'lieferant_{f}', wert[:LAENGEN[f]])


def fehlende_angaben(adresse):
    """Welche Pflichtangaben der Zahlungsdatei fehlen: Teilmenge von
    ('ort', 'land'). «Mindestens Ort und Land» ist die Vorgabe der SPS; Strasse,
    Hausnummer und PLZ stehen in der Datei, wenn sie erfasst sind, und sind
    keine Bedingung (siehe `core/services/pain001.py`)."""
    fehlt = []
    if not (adresse.get('ort') or '').strip():
        fehlt.append('ort')
    if not _LAND.match((adresse.get('land') or '').strip().upper()):
        fehlt.append('land')
    return fehlt


def adresse_vollstaendig(adresse):
    return not fehlende_angaben(adresse)


def aus_profil_uebernehmen(k, profil=None):
    """Füllt eine Rechnung OHNE Anschrift mit der des Lieferantenprofils.

    Überschreibt nie: Hat die Rechnung schon einen Ort, bleibt sie, wie sie ist.
    Gibt True zurück, wenn etwas übernommen wurde (der Aufrufer speichert)."""
    if (k.lieferant_ort or '').strip():
        return False
    if profil is None:
        from finance.lieferanten import lieferant_vorschlag
        profil = lieferant_vorschlag(k.lieferant)
    adresse = adresse_von_profil(profil)
    if not adresse or not (adresse.get('ort') or '').strip():
        return False
    adresse_setzen(k, adresse)
    return True


def iban_abweichung(k, profil=None):
    """Die gelernte IBAN des Lieferanten, wenn die der Rechnung davon abweicht.

    Leer, wenn es kein Profil, keine gelernte IBAN oder keine IBAN an der
    Rechnung gibt, oder wenn beide übereinstimmen. Der Betrugsfall «geänderte
    Kontonummer auf einer gefälschten Rechnung» (FIN-09/FIN-10) zeigt sich
    genau hier."""
    iban = normalisiere_iban(k.iban)
    if not iban:
        return ''
    if profil is None:
        from finance.lieferanten import lieferant_vorschlag
        profil = lieferant_vorschlag(k.lieferant)
    gelernt = normalisiere_iban(profil.iban) if profil else ''
    if gelernt and gelernt != iban:
        return gelernt
    return ''


def iban_meldung(neu, gelernt):
    """Der Warntext, einmal formuliert für Liste, Freigabe und Protokoll."""
    from core.services.iban import formatiere_iban
    return _('IBAN weicht vom Lieferantenprofil ab: bisher %(alt)s, jetzt %(neu)s. '
             'Vor der Freigabe beim Lieferanten nachfragen (Rechnungsbetrug).') % {
        'alt': formatiere_iban(gelernt), 'neu': formatiere_iban(neu)}
