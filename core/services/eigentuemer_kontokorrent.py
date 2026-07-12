"""Kontokorrent Eigentümer (Mandant): das Ergebnis der bewirtschafteten
Liegenschaften (Ertrag − Aufwand) abzüglich der bereits an den Eigentümer
ausbezahlten Beträge = offener Saldo (Verbindlichkeit gegenüber dem Eigentümer).

Bewusst als *berechnete* Verwaltungssicht aus dem Hauptbuch — die tatsächlichen
Auszahlungen werden über EigentuemerAuszahlung (Buchung Soll 2850 / Haben Bank)
geführt und hier abgezogen."""
from datetime import date
from decimal import Decimal


def kontokorrent(mandant, jahr=None):
    """Gibt ein dict mit Ergebnis je Liegenschaft, Auszahlungen und offenem Saldo.

    jahr=None → kumulativ über alle Jahre. Sonst nur das Geschäftsjahr.
    """
    from finance.models import Buchung, Buchungskonto, EigentuemerAuszahlung
    from portfolio.models import Liegenschaft
    from django.db.models import Sum

    ertrag_konten = list(Buchungskonto.objects.filter(typ='ertrag'))
    aufwand_konten = list(Buchungskonto.objects.filter(typ='aufwand'))
    liegenschaften = Liegenschaft.objects.filter(mandant=mandant).order_by('strasse')

    von = date(jahr, 1, 1) if jahr else None
    bis = date(jahr, 12, 31) if jahr else None

    zeilen = []
    sum_ertrag = sum_aufwand = Decimal('0.00')
    for lg in liegenschaften:
        bqs = Buchung.objects.filter(liegenschaft=lg)
        if von:
            bqs = bqs.filter(datum__gte=von, datum__lte=bis)
        ertrag = Decimal('0.00')
        for k in ertrag_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            ertrag += (h - s)
        aufwand = Decimal('0.00')
        for k in aufwand_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            aufwand += (s - h)
        if ertrag == 0 and aufwand == 0:
            continue
        zeilen.append({'lg': lg, 'ertrag': ertrag, 'aufwand': aufwand, 'ergebnis': ertrag - aufwand})
        sum_ertrag += ertrag
        sum_aufwand += aufwand
    ergebnis = sum_ertrag - sum_aufwand

    ausz = EigentuemerAuszahlung.objects.filter(mandant=mandant, status='verbucht')
    if von:
        ausz = ausz.filter(datum__gte=von, datum__lte=bis)
    ausz = list(ausz.select_related('konto').order_by('-datum', '-id'))
    ausbezahlt = sum((a.betrag for a in ausz), Decimal('0.00'))

    return {
        'zeilen': zeilen,
        'ertrag': sum_ertrag, 'aufwand': sum_aufwand, 'ergebnis': ergebnis,
        'auszahlungen': ausz, 'ausbezahlt': ausbezahlt,
        'offen': ergebnis - ausbezahlt,
        'liegenschaften_n': liegenschaften.count(),
    }
