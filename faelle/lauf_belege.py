"""Was ein Lauf verarbeitet hat — und der Weg zurück, wenn es falsch war.

Zwei Dinge, die der Buchhalter beim Monatsabschluss braucht und die die
Läufe-Seite bisher nicht bot:

* `belege(lauf)` — die Liste der Belege, die zur Periode des Laufs gehören
  (Rechnungen der Sollstellung, verbuchte Zahlungseingänge, Mahnungen,
  Kreditorenzahlungen). Damit lässt sich VOR dem Quittieren prüfen, was der
  Lauf bewegt hat.
* `sollstellung_stornieren(...)` — hebt die Rechnungen einer Periode per
  Gegenbuchung auf (revisionssicher, wie `fw_debitor_stornieren`), alles oder
  nichts: Sobald EINE Rechnung der Periode schon bezahlt ist, passiert gar
  nichts, damit keine Hälfte stehen bleibt.
"""
from decimal import Decimal

from django.db import transaction

#: Höchstzahl Zeilen in der Detailansicht — die Summe zählt trotzdem alle.
MAX_ZEILEN = 200


class StornoBlockiert(Exception):
    """Der Storno ist nicht möglich; die Meldung gehört dem Benutzer."""


def _jahr_monat(periode):
    try:
        jahr, monat = (int(t) for t in periode.split('-'))
    except ValueError:
        return None
    return (jahr, monat) if 1 <= monat <= 12 else None


def sollstellung_titel(periode):
    jm = _jahr_monat(periode)
    return f'Miete & NK {jm[1]:02d}/{jm[0]}' if jm else None


def belege(lauf):
    """Belege der Periode: {'spalten', 'zeilen', 'anzahl', 'summe', 'hinweis'}."""
    from finance.models import (DebitorenRechnung, KreditorenRechnung,
                                KreditorenZahlung, Mahnung, Zahlungseingang)

    art = lauf.laufart.schluessel
    jm = _jahr_monat(lauf.periode)
    zeilen, summe, hinweis = [], Decimal('0.00'), ''
    spalten = ('Beleg', 'Betrag', 'Status')

    if art == 'sollstellung' and jm:
        qs = (DebitorenRechnung.objects.filter(titel=sollstellung_titel(lauf.periode))
              .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
              .order_by('vertrag__einheit__liegenschaft__strasse', 'id'))
        anzahl = qs.count()
        for r in qs[:MAX_ZEILEN]:
            mieter = r.vertrag.mieter.display_name if r.vertrag_id else '—'
            zeilen.append((f'{mieter} · {r.titel}', r.betrag, r.get_status_display()))
        summe = sum((r.betrag for r in qs.exclude(status='storniert')), Decimal('0.00'))
        hinweis = 'Summe ohne stornierte Rechnungen.'
    elif art == 'bankabgleich' and jm:
        qs = Zahlungseingang.objects.filter(
            datum_eingang__year=jm[0], datum_eingang__month=jm[1],
            status='verbucht').select_related('debitoren_rechnung').order_by('datum_eingang', 'id')
        anzahl = qs.count()
        for z in qs[:MAX_ZEILEN]:
            zeilen.append((f'{z.datum_eingang:%d.%m.%Y} · {z.bemerkung}', z.betrag, 'verbucht'))
        summe = sum((z.betrag for z in qs), Decimal('0.00'))
    elif art == 'mahnlauf' and jm:
        qs = (Mahnung.objects.filter(datum__year=jm[0], datum__month=jm[1])
              .select_related('debitoren_rechnung').order_by('datum', 'id'))
        anzahl = qs.count()
        for m in qs[:MAX_ZEILEN]:
            titel = m.debitoren_rechnung.titel if m.debitoren_rechnung_id else '—'
            zeilen.append((f'{m.stufe}. Mahnung · {titel}', m.betrag_offen, f'Gebühr CHF {m.gebuehr}'))
        summe = sum((m.betrag_offen for m in qs), Decimal('0.00'))
    elif art == 'zahllauf' and jm:
        zahlungen = (KreditorenZahlung.objects.filter(datum__year=jm[0], datum__month=jm[1])
                     .exclude(status='storniert').select_related('kreditor').order_by('datum', 'id'))
        anzahl = zahlungen.count()
        for z in zahlungen[:MAX_ZEILEN]:
            zeilen.append((f'{z.datum:%d.%m.%Y} · {z.kreditor.lieferant} {z.kreditor.referenz}',
                           z.betrag, 'verbucht'))
        summe = sum((z.betrag for z in zahlungen), Decimal('0.00'))
        # Was bereits in einer Zahlungsdatei steht, aber noch nicht von der Bank bestätigt ist.
        in_zahlung = KreditorenRechnung.objects.filter(status='in_zahlung')
        n_unterwegs = in_zahlung.count()
        if n_unterwegs:
            hinweis = (f'{n_unterwegs} Rechnung(en) stehen in einer Zahlungsdatei, '
                       f'die Bank-Bestätigung (Sammelbestätigung) fehlt noch.')
    else:
        anzahl = 0
        hinweis = 'Für diese Laufart gibt es keine Belegliste.'
    return {'spalten': spalten, 'zeilen': zeilen, 'anzahl': anzahl,
            'summe': summe, 'hinweis': hinweis,
            'gekuerzt': anzahl > len(zeilen)}


def sollstellung_stornieren(periode, benutzer=None):
    """Hebt alle nicht stornierten Sollstellungs-Rechnungen der Periode auf.

    Alles oder nichts, in EINER Transaktion. Blockiert (`StornoBlockiert`),
    sobald eine Rechnung der Periode verbuchte Zahlungen trägt — dort müssen
    zuerst die Zahlungen storniert werden. Rückgabe: Anzahl stornierter Rechnungen.
    """
    from finance.models import Buchung, DebitorenRechnung, Zahlungseingang
    from finance.services import erstelle_storno_buchung
    from core.views.fw.listen import _mahngebuehr_historie_ausgleichen

    titel = sollstellung_titel(periode)
    if titel is None:
        raise StornoBlockiert(f'Periode «{periode}» ist keine Monatsperiode.')
    with transaction.atomic():
        rechnungen = list(DebitorenRechnung.objects.select_for_update()
                          .filter(titel=titel).exclude(status='storniert'))
        mit_zahlung = [r for r in rechnungen
                       if Zahlungseingang.objects.filter(debitoren_rechnung=r,
                                                         status='verbucht').exists()]
        if mit_zahlung:
            raise StornoBlockiert(
                f'{len(mit_zahlung)} Rechnung(en) der Periode haben verbuchte Zahlungen — '
                f'zuerst die Zahlungen stornieren (Bankabgleich), dann die Sollstellung.')
        for r in rechnungen:
            # Abgeleitete Mahngebühren/Zinsen der Rechnung gehen mit.
            for x in [r, *DebitorenRechnung.objects.filter(stammrechnung=r)
                      .exclude(status='storniert')]:
                for b in Buchung.objects.filter(debitoren_rechnung=x, ist_storno=False,
                                                storniert_am__isnull=True):
                    erstelle_storno_buchung(b, benutzer=benutzer)
                x.status = 'storniert'
                x.save(update_fields=['status'])
                _mahngebuehr_historie_ausgleichen(x, benutzer)
    return len(rechnungen)
