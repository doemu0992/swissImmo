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

from django.utils.translation import gettext as _, ngettext


def schritte(p, *, total_kosten, warnungen, akonto_vorschlaege, hkvo_aktiv, hkvo_angewendet):
    lg = p.liegenschaft
    basis = f'/neu/nebenkosten/{p.id}/'
    kosten_da = (total_kosten or Decimal('0')) > 0
    zu = p.abgeschlossen
    s = [
        {'titel': _('Periode'), 'info': f'{p.start_datum:%d.%m.%Y} – {p.ende_datum:%d.%m.%Y}',
         'zustand': 'erledigt', 'url': '/neu/nebenkosten/'},
        {'titel': _('Kosten & Belege'),
         'info': _('erfasst') if kosten_da else _('noch keine Kosten'),
         'zustand': 'erledigt' if kosten_da else 'offen', 'url': basis + '?tab=belege'},
    ]
    if hkvo_aktiv:
        s.append({'titel': _('Zähler & HKVO'),
                  'info': _('angewendet') if hkvo_angewendet else _('Zählerstände prüfen'),
                  'zustand': 'erledigt' if hkvo_angewendet else 'warnung',
                  'url': f'/neu/zaehler/?lg={lg.id}' if lg else '/neu/zaehler/'})
    else:
        s.append({'titel': _('Zähler & HKVO'), 'info': _('nicht aktiv'), 'zustand': 'entfaellt',
                  'url': f'/neu/liegenschaften/{lg.id}/verteilschluessel/' if lg else ''})
    s += [
        {'titel': _('Verteilung prüfen'),
         'info': (ngettext('%(n)s Hinweis', '%(n)s Hinweise', len(warnungen)) % {'n': len(warnungen)})
                 if warnungen else _('ohne Hinweis'),
         'zustand': 'gesperrt' if not kosten_da else ('warnung' if warnungen else 'erledigt'),
         'url': basis + '?tab=abrechnung'},
        {'titel': _('Akonto'),
         'info': _('Anpassung empfohlen') if akonto_vorschlaege else _('passt'),
         'zustand': 'gesperrt' if not kosten_da else ('warnung' if akonto_vorschlaege else 'erledigt'),
         'url': basis + '?tab=abrechnung#akonto'},
        {'titel': _('Verbuchen'),
         'info': _('verbucht') if zu else _('Nachzahlungen und Guthaben stellen'),
         'zustand': 'erledigt' if zu else ('gesperrt' if not kosten_da else 'offen'), 'url': basis},
        {'titel': _('Versand & Zustellung'),
         'info': (_('zugestellt %(d)s') % {'d': f'{p.versendet_am:%d.%m.%Y}'}) if p.versendet_am else
                 (_('nach dem Verbuchen') if not zu else _('Zustellung erfassen')),
         'zustand': 'erledigt' if p.versendet_am else ('offen' if zu else 'gesperrt'),
         'url': basis + 'zustellung/' if zu else basis},
    ]
    hier = next((i for i, x in enumerate(s) if x['zustand'] not in ('erledigt', 'entfaellt')), None)
    for i, x in enumerate(s):
        x['nr'] = i + 1
        x['hier'] = i == hier
    return s
