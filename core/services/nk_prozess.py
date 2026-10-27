"""Prozessleiste der Nebenkosten-/Heizkostenabrechnung (UI-Analyse 26.10.2026).

Bis hierher lagen die Schritte einer Abrechnung auf getrennten Seiten und
Knöpfen — Kosten, Zähler, Verteilung, Akonto, Verbuchen, Versand, Zustellung —
ohne Antwort auf «was zuerst, was fehlt noch, was ist erledigt». Diese Funktion
leitet den Zustand jedes Schritts aus den Werten ab, die die Detailansicht
ohnehin rechnet (`core.utils.billing.hole_abrechnung`). Sie rechnet NICHTS neu;
eine zweite Abrechnungslogik gäbe es sonst irgendwann mit anderen Zahlen.

Zustände: erledigt · warnung (geht, aber etwas ist zu prüfen) · offen ·
gesperrt (erst nach einem früheren Schritt möglich) · entfaellt (z. B. ohne HKVO).
`hier` ist der erste Schritt, der weder erledigt noch entfallen ist.
"""
from decimal import Decimal

from django.utils.translation import gettext as _, gettext_lazy as _lazy, ngettext


def schritte(p, *, total_kosten, warnungen, akonto_vorschlaege, hkvo_aktiv, hkvo_angewendet):
    basis = f'/neu/nebenkosten/{p.id}/'
    kosten_da = (total_kosten or Decimal('0')) > 0
    zu = p.abgeschlossen
    s = [
        {'titel': _('Periode'), 'info': f'{p.start_datum:%d.%m.%Y} – {p.ende_datum:%d.%m.%Y}',
         'zustand': 'erledigt', 'url': '/neu/nebenkosten/'},
        {'titel': _('Kosten & Belege'),
         'info': _('erfasst') if kosten_da else _('noch keine Kosten'),
         'zustand': 'erledigt' if kosten_da else 'offen', 'url': basis + 'kosten/'},
    ]
    if hkvo_aktiv:
        s.append({'titel': _('Zähler & HKVO'),
                  'info': _('angewendet') if hkvo_angewendet else _('Zählerstände prüfen'),
                  'zustand': 'erledigt' if hkvo_angewendet else 'warnung',
                  'url': basis + 'heizung/'})
    else:
        s.append({'titel': _('Zähler & HKVO'), 'info': _('nicht aktiv'), 'zustand': 'entfaellt',
                  'url': basis + 'heizung/'})
    s += [
        {'titel': _('Verteilung prüfen'),
         'info': (ngettext('%(n)s Hinweis', '%(n)s Hinweise', len(warnungen)) % {'n': len(warnungen)})
                 if warnungen else _('ohne Hinweis'),
         'zustand': 'gesperrt' if not kosten_da else ('warnung' if warnungen else 'erledigt'),
         'url': basis + 'pruefen/'},
        {'titel': _('Akonto'),
         'info': _('Anpassung empfohlen') if akonto_vorschlaege else _('passt'),
         'zustand': 'gesperrt' if not kosten_da else ('warnung' if akonto_vorschlaege else 'erledigt'),
         'url': basis + 'pruefen/#akonto'},
        {'titel': _('Verbuchen'),
         'info': _('verbucht') if zu else _('Nachzahlungen und Guthaben stellen'),
         'zustand': 'erledigt' if zu else ('gesperrt' if not kosten_da else 'offen'), 'url': basis + 'abschluss/'},
        {'titel': _('Versand & Zustellung'),
         'info': (_('zugestellt %(d)s') % {'d': f'{p.versendet_am:%d.%m.%Y}'}) if p.versendet_am else
                 (_('nach dem Verbuchen') if not zu else _('Zustellung erfassen')),
         'zustand': 'erledigt' if p.versendet_am else ('offen' if zu else 'gesperrt'),
         'url': basis + 'zustellung/' if zu else basis + 'abschluss/'},
    ]
    hier = next((i for i, x in enumerate(s) if x['zustand'] not in ('erledigt', 'entfaellt')), None)
    for i, x in enumerate(s):
        x['nr'] = i + 1
        x['hier'] = i == hier
    return s


# ---------------------------------------------------------------------------
# Wizard (Modul 1, 27.10.2026): sechs Schritte auf der Grundlage der sieben oben
# ---------------------------------------------------------------------------

#: (Nummer, URL-Teil, Titel) der sechs Wizard-Schritte. Die URL-Teile sind Unterpfade von
#: /neu/nebenkosten/<pk>/ (swiss_immo/urls.py).
WIZARD = (
    (1, 'periode', _lazy('Periode & Objekte')),
    (2, 'kosten', _lazy('Kosten')),
    (3, 'verteilung', _lazy('Verteilung')),
    (4, 'heizung', _lazy('Heizung & Zähler')),
    (5, 'pruefen', _lazy('Prüfen')),
    (6, 'abschluss', _lazy('Verbuchen & Zustellen')),
)

#: Art einer Engine-Warnung (`warnung_arten`) → Schritt, über dem sie steht.
WARNUNG_SCHRITT = {'flaeche': (1, 3), 'volumen': (1, 3), 'schluessel': (3,), 'oel': (2,), 'hkvo': (4,)}


def warnungen_fuer(result, nr):
    """Die Warnungen der Engine, die Schritt `nr` betreffen. Schritt 5 zeigt alle.
    Ein alter Snapshot ohne `warnung_arten` zeigt seine Warnungen nur in Schritt 5."""
    warnungen = list(result.get('warnungen') or [])
    if nr == 5:
        return warnungen
    arten = list(result.get('warnung_arten') or [])
    return [w for w, a in zip(warnungen, arten) if nr in WARNUNG_SCHRITT.get(a, (5,))]


def wizard_schritte(p, prozess, *, objekt_luecken, periode_zu_lang, warnungen_je_schritt,
                    hinweise, differenz, anzahl_kosten, total_kosten):
    """Die sechs Wizard-Schritte, abgeleitet aus `schritte()` (sieben) und dem, was die Seiten
    ohnehin wissen. Rechnet nichts: Zustand, Info und Ziel je Schritt.

    `prozess` ist die Ausgabe von `schritte()`: 0 Periode · 1 Kosten · 2 Zähler · 3 Verteilung ·
    4 Akonto · 5 Verbuchen · 6 Versand.
    """
    basis = f'/neu/nebenkosten/{p.id}/'
    monate = _monate(p.start_datum, p.ende_datum)
    kosten_da = (total_kosten or Decimal('0')) > 0
    s = []
    # 1 Periode & Objekte
    luecken = objekt_luecken or []
    s.append({'zustand': 'warnung' if (luecken or periode_zu_lang or warnungen_je_schritt.get(1)) else 'erledigt',
              'info': f'{p.start_datum:%d.%m.%y}–{p.ende_datum:%d.%m.%y} · '
                      + (_('%(n)s Mt.') % {'n': monate})})
    # 2 Kosten
    s.append({'zustand': 'warnung' if (kosten_da and warnungen_je_schritt.get(2)) else prozess[1]['zustand'],
              'info': (ngettext('%(n)s Posten · CHF %(b)s', '%(n)s Posten · CHF %(b)s', anzahl_kosten)
                       % {'n': anzahl_kosten, 'b': _chf(total_kosten)}) if kosten_da else prozess[1]['info']})
    # 3 Verteilung
    w3 = warnungen_je_schritt.get(3) or []
    s.append({'zustand': 'gesperrt' if not kosten_da else ('warnung' if w3 else 'erledigt'),
              'info': (ngettext('%(n)s Hinweis', '%(n)s Hinweise', len(w3)) % {'n': len(w3)}) if w3
                      else _('je Kostenart')})
    # 4 Heizung & Zähler
    z = dict(prozess[2])
    if z['zustand'] == 'erledigt' and hinweise:
        z['zustand'], z['info'] = 'warnung', _('Zwischenstand fehlt')
    s.append({'zustand': z['zustand'], 'info': z['info']})
    # 5 Prüfen
    akonto = prozess[4]['zustand'] == 'warnung'
    w5 = warnungen_je_schritt.get(5) or []
    if not kosten_da:
        zustand5, info5 = 'gesperrt', _('pro Mieter')
    elif p.abgeschlossen:
        zustand5, info5 = 'erledigt', _('verbucht')
    elif w5 or differenz:
        zustand5, info5 = 'warnung', _('Differenz prüfen') if differenz else prozess[3]['info']
    else:
        zustand5, info5 = 'offen', _('Akonto-Anpassung empfohlen') if akonto else _('pro Mieter')
    s.append({'zustand': zustand5, 'info': info5})
    # 6 Verbuchen & Zustellen
    s.append({'zustand': prozess[6]['zustand'] if p.abgeschlossen else prozess[5]['zustand'],
              'info': prozess[6]['info'] if p.abgeschlossen else _('Versand nach Buchung')})

    hier = next((i for i, x in enumerate(s) if x['zustand'] not in ('erledigt', 'entfaellt')), None)
    for i, (x, (nr, teil, titel)) in enumerate(zip(s, WIZARD)):
        x.update({'nr': nr, 'teil': teil, 'titel': titel, 'url': basis + teil + '/', 'hier': i == hier})
    return s


def _monate(start, ende):
    """Dauer in Monaten zur Anzeige (01.07.–30.06. = 12). Die Grenze von 12 Monaten prüft
    `core.services.nk_wizard.periode_pruefen` taggenau."""
    return round(((ende - start).days + 1) / 30.4375)


def _chf(betrag):
    try:
        return f"{Decimal(betrag):,.0f}".replace(',', "'")
    except Exception:
        return '0'
