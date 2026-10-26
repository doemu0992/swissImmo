"""Leerstands-Cockpit (Akten → Leerstand) — was leer steht, was frei wird, was es kostet.

WARUM (UI-Audit 26.10.2026)
Der Leerstand stand bis hierher an drei Stellen, keine davon war eine
Arbeitsfläche: als Zahl im Portfolio, als Verlauf unter Berichte und als
Befund «Steht leer» in der Objektliste, dort zwischen allen übrigen Objekten.
Wer in einer Verwaltung den Leerstand abbauen soll, braucht EINE Liste: jede
leere oder bald freie Einheit, wie lange schon, was sie im Monat kostet und
woran die Vermietung gerade hängt — mit dem Knopf, der das behebt.

DIESELBE REGEL WIE ÜBERALL
Belegt, leer, «wird frei» und «Nachmieter vorhanden» kommen aus
`faelle.objekte._belegung` — derselben Funktion, die die Objektliste nutzt und
deren Gleichlauf mit der Liegenschaftsliste `faelle/test_objektliste.py`
prüft. Eine dritte Fassung der Regel gibt es nicht.

WAS «AUSFALL» HEISST
Der Netto-Sollmietzins der Einheit (`nettomiete_aktuell`) je Monat. Der
aufgelaufene Ausfall ist dieser Betrag mal die Leermonate seit Vertragsende —
eine Schätzung, und die Seite sagt das. Ohne hinterlegten Mietzins steht kein
Betrag, sondern der Befund «Kein Mietzins»: Das ist der Grund, warum die
Wohnung nicht ausgeschrieben werden kann.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from faelle.objekte import LANGE_LEER_TAGE, TYP_GRUPPEN, VORSCHAU_TAGE, _belegung

NULL = Decimal('0.00')

#: Bewerbungen, die noch im Rennen sind (abgelehnte zählen nicht).
OFFENE_BEWERBUNG = ('neu', 'geprueft', 'besichtigung', 'zugesagt')


def _schritt(z):
    """Der nächste Handgriff — genau einer, der wichtigste zuerst."""
    e = z['e']
    if not e.nettomiete_aktuell:
        return {'text': 'Mietzins festlegen', 'url': f'/neu/objekte/{e.id}/bearbeiten/', 'stufe': 'crit'}
    if z['zusage']:
        return {'text': 'Vertrag erfassen', 'url': f'/neu/vertraege/neu/?einheit={e.id}', 'stufe': 'good'}
    if z['bewerbungen']:
        return {'text': 'Bewerbungen prüfen', 'url': f'/neu/vermarktung/{e.id}/bewerber/', 'stufe': 'warn'}
    if not e.zur_ausschreibung:
        return {'text': 'Ausschreiben', 'url': f'/neu/objekte/{e.id}/ausschreiben/', 'stufe': 'warn', 'modal': True}
    return {'text': 'Inserat ansehen', 'url': '/neu/vermarktung/', 'stufe': 'info'}


def cockpit(einheiten, stichtag=None):
    """Leere, bald freie und versorgte Einheiten samt Kennzahlen.

    `einheiten` ist ein Queryset (schon nach Liegenschaft gefiltert). Rückgabe:
    `zeilen` (leer und bald frei, nach Dringlichkeit), `versorgt` (frei, aber mit
    Nachmieter), Summen.
    """
    from mietprozess.models import Mietbewerbung

    stichtag = stichtag or timezone.localdate()
    einheiten = list(einheiten.select_related('liegenschaft'))
    zustand = _belegung(einheiten, stichtag)
    bis = stichtag + timedelta(days=VORSCHAU_TAGE)

    ids = [e.id for e in einheiten]
    bew = {r['einheit_id']: r for r in (
        Mietbewerbung.objects.filter(einheit_id__in=ids, status__in=OFFENE_BEWERBUNG)
        .values('einheit_id').annotate(n=Count('id'), zusage=Count('id', filter=Q(status='zugesagt'))))}

    zeilen, versorgt = [], []
    for e in einheiten:
        z = zustand[e.id]
        leer_jetzt = not z['unbefristet'] and z['belegt_bis'] is None
        bald = (not leer_jetzt and z['belegt_bis'] is not None and z['belegt_bis'] <= bis)
        if not (leer_jetzt or bald):
            continue
        b = bew.get(e.id, {})
        zeile = {
            'e': e, 'lg': e.liegenschaft,
            'zustand': 'leer' if leer_jetzt else 'bald',
            'leer_seit': z['leer_seit'] if leer_jetzt else None,
            'frei_ab': (z['belegt_bis'] + timedelta(days=1)) if bald else None,
            'nachmieter_ab': z['nachmieter_ab'],
            'miete': e.nettomiete_aktuell or None,
            'bewerbungen': b.get('n', 0), 'zusage': b.get('zusage', 0),
            'inseriert': bool(e.zur_ausschreibung),
        }
        if leer_jetzt:
            tage = (stichtag - z['leer_seit']).days if z['leer_seit'] else None
            zeile['tage'] = tage
            monate = Decimal(tage) / Decimal(30) if tage else Decimal(0)
            zeile['ausfall_bisher'] = (e.nettomiete_aktuell * monate).quantize(Decimal('1')) if e.nettomiete_aktuell and tage else None
            zeile['stufe'] = 'crit' if (tage is not None and tage > LANGE_LEER_TAGE) or not e.nettomiete_aktuell else 'warn'
        else:
            zeile['tage'] = None
            zeile['ausfall_bisher'] = None
            zeile['tage_bis_frei'] = (zeile['frei_ab'] - stichtag).days
            zeile['stufe'] = 'warn' if zeile['tage_bis_frei'] <= 60 else 'info'
        zeile['schritt'] = _schritt(zeile)
        # Frei, aber ein Nachmieter ist unterschrieben: niemand muss etwas tun.
        (versorgt if z['nachmieter_ab'] else zeilen).append(zeile)

    rang = {'crit': 0, 'warn': 1, 'info': 2, 'good': 3}
    zeilen.sort(key=lambda r: (rang[r['stufe']], r['zustand'] != 'leer',
                               -(r['tage'] or 0), r.get('tage_bis_frei') or 0, -(r['miete'] or 0)))
    leer = [r for r in zeilen if r['zustand'] == 'leer']
    bald = [r for r in zeilen if r['zustand'] == 'bald']
    tage = [r['tage'] for r in leer if r['tage'] is not None]
    gesamt = len(einheiten)
    return {
        'zeilen': zeilen, 'versorgt': versorgt,
        'n_leer': len(leer), 'n_bald': len(bald), 'n_versorgt': len(versorgt), 'gesamt': gesamt,
        'quote': (len(leer) / gesamt * 100) if gesamt else None,
        'ausfall_monat': sum((r['miete'] or NULL for r in leer), NULL),
        'ausfall_bald': sum((r['miete'] or NULL for r in bald), NULL),
        'ohne_preis': sum(1 for r in zeilen if not r['miete']),
        'nicht_inseriert': sum(1 for r in zeilen if r['miete'] and not r['inseriert']),
        'schnitt_tage': round(sum(tage) / len(tage)) if tage else None,
        'lange': sum(1 for t in tage if t > LANGE_LEER_TAGE),
    }


def typ_filter(qs, typ):
    if typ in TYP_GRUPPEN:
        return qs.filter(typ__in=TYP_GRUPPEN[typ])
    return qs
