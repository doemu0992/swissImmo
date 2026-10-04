"""Kontokorrent je Einheit und Stand des Erneuerungsfonds — für Verwaltung und Portal.

Der Saldo ist «offen» positiv: was die Einheit der Gemeinschaft noch schuldet; negativ =
Guthaben der Einheit. Er setzt sich aus drei Arten von Bewegungen zusammen:

  · Vorschreibung (Soll): jede Akonto-Rate nach genehmigtem Budget, mit Fälligkeit;
  · Zahlung (Haben): jede erfasste Akonto-Zahlung (`StwegAkonto`);
  · Abgleich (Soll oder Haben): bei einer ABGESCHLOSSENEN Jahresabrechnung der Unterschied
    zwischen tatsächlichem Kostenanteil und den vorgeschriebenen Raten des Jahres. So
    ergibt der Saldo nach dem Abschluss genau den Kostenanteil abzüglich der Zahlungen.

Der Saldo «fällig» zählt nur Bewegungen bis heute: Raten, die erst kommen, sind noch nicht offen.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from finance.models import Erneuerungsfonds
from stweg.models import StwegAbrechnung, StwegAbrechnungPosition, StwegAkonto, StwegVorschreibung
from stweg.validierung import stimm_einheiten

NULL = Decimal('0.00')


def kontokorrent(einheit, heute=None):
    heute = heute or date.today()
    bew = []
    for v in StwegVorschreibung.objects.filter(einheit=einheit).select_related('budget'):
        bew.append({'datum': v.faellig_am, 'art': 'vorschreibung',
                    'text': f'Akonto {v.budget.jahr}, Rate {v.rate_nr}/{v.rate_total}', 'betrag': v.betrag})
    for z in StwegAkonto.objects.filter(einheit=einheit):
        bew.append({'datum': z.datum, 'art': 'zahlung', 'text': z.bemerkung or 'Zahlung', 'betrag': -z.betrag})
    for p in (StwegAbrechnungPosition.objects
              .filter(einheit=einheit, abrechnung__status=StwegAbrechnung.STATUS_ABGESCHLOSSEN)
              .select_related('abrechnung')):
        vorgeschrieben = (StwegVorschreibung.objects
                          .filter(einheit=einheit, budget__jahr=p.abrechnung.jahr, budget__liegenschaft=einheit.liegenschaft)
                          .aggregate(s=Sum('betrag'))['s'] or NULL)
        # Nur wenn für das Jahr vorgeschrieben wurde: Ohne Vorschreibung gibt es nichts abzugleichen,
        # der Kostenanteil steht dann als ganzer Abgleich.
        abgleich = p.kostenanteil - vorgeschrieben
        if abgleich != 0:
            bew.append({'datum': date(p.abrechnung.jahr, 12, 31), 'art': 'abgleich',
                        'text': f'Abrechnung {p.abrechnung.jahr}: Abgleich mit den Vorschreibungen',
                        'betrag': abgleich})
    bew.sort(key=lambda b: (b['datum'], b['art']))
    laufend = NULL
    for b in bew:
        laufend += b['betrag']
        b['saldo'] = laufend
    faellig = sum((b['betrag'] for b in bew if b['datum'] <= heute), NULL)
    return {'bewegungen': bew, 'saldo_faellig': faellig, 'saldo_total': laufend,
            'kuenftig': laufend - faellig}


def fonds_stand(liegenschaft, einheiten=()):
    """Bestand des Erneuerungsfonds der Gemeinschaft und — je Einheit — deren bisherige Einlagen
    und der rechnerische Anteil nach Wertquote."""
    fonds = Erneuerungsfonds.objects.filter(liegenschaft=liegenschaft).first()      # nur lesen
    if fonds is None:
        return {'bestand': NULL, 'letzte_einlage_jahr': None, 'bewegungen': [],
                'einheiten': [{'einheit': e, 'einlagen': NULL, 'anteil': NULL} for e in einheiten]}
    bestand = fonds.bestand or NULL
    total = Decimal(liegenschaft.wertquote_total) or Decimal(1)
    je_einheit = []
    for e in einheiten:
        einlagen = (fonds.bewegungen.filter(art='einlage', einheit=e).aggregate(s=Sum('betrag'))['s'] or NULL)
        je_einheit.append({'einheit': e, 'einlagen': einlagen,
                           'anteil': (bestand * Decimal(e.wertquote) / total).quantize(Decimal('0.01'))})
    return {'bestand': bestand, 'letzte_einlage_jahr': fonds.letzte_einlage_jahr, 'einheiten': je_einheit,
            'bewegungen': list(fonds.bewegungen.order_by('-datum', '-id')[:10])}
