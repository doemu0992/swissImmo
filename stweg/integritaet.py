"""Integritätsprüfung einer STWEG-Gemeinschaft und Abstimmung des Hauptbuchs mit den Fachtabellen.

Zwei Fragen, die kein Test einer einzelnen Funktion beantwortet:

1. `pruefe(lg)` — Ist der Bestand in sich stimmig? Wertquoten, Eigentümer, Schlüssel, Fonds. Fängt, was die
   Einzelspeicherung nicht verhindern kann (`QuerySet.update()`, Importe, Handarbeit in der Datenbank).
2. `abstimmung_hauptbuch(lg)` — Stimmt das Hauptbuch mit den Fachtabellen überein? Verglichen werden die Salden der
   Konten 1110, 2035, 3100 und 2800 (alle Buchungen der Liegenschaft, Stornos eingerechnet) mit dem, was sich aus
   Vorschreibungen, Zahlungen, Abrechnungen und Fonds-Bewegungen ergibt. Eine Differenz ist ein Fehler — entweder
   in der Buchung oder in der Fachtabelle.

Nur GEBUCHTE Posten gehen in die Abstimmung ein: Zahlungen aus der Zeit vor der Hauptbuch-Anbindung haben keine
Buchung und würden sonst als Differenz erscheinen.
"""
from decimal import Decimal

from django.db.models import Sum

from finance.models import Buchung, Erneuerungsfonds, ErneuerungsfondsBewegung
from stweg.models import (StwegAbrechnung, StwegAbrechnungPosition, StwegAkonto, StwegInkassoPosition,
                          StwegVorschreibung)
from stweg.validierung import WertquotenFehler, pruefe_wertquoten, stimm_einheiten

NULL = Decimal('0.00')
FEHLER, WARNUNG, HINWEIS = 'fehler', 'warnung', 'hinweis'


def _saldo(lg, nummer):
    """Soll minus Haben auf dem Konto, alle Buchungen der Liegenschaft (ein Storno ist eine Gegenbuchung)."""
    qs = Buchung.objects.filter(liegenschaft=lg)
    soll = qs.filter(soll_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or NULL
    haben = qs.filter(haben_konto__nummer=nummer).aggregate(s=Sum('betrag'))['s'] or NULL
    return soll - haben


def _nicht_storniert(buchung_feld):
    return {f'{buchung_feld}__isnull': False, f'{buchung_feld}__storniert_am__isnull': True}


def erwartet(lg):
    """Die Kontensalden, wie sie die Fachtabellen verlangen: {'1110': …, '2035': …, '3100': …, '2800': …}."""
    vorschr = StwegVorschreibung.objects.filter(budget__liegenschaft=lg, **_nicht_storniert('buchung'))
    v_summe = vorschr.aggregate(s=Sum('betrag'))['s'] or NULL
    zahl = StwegAkonto.objects.filter(einheit__liegenschaft=lg, **_nicht_storniert('buchung'))
    z_summe = zahl.aggregate(s=Sum('betrag'))['s'] or NULL
    zins_summe = zahl.aggregate(s=Sum('an_zins'))['s'] or NULL            # Zinsanteil: Ertrag 3120, nicht 1110
    # Abschluss: je Position die Beträge der Abschlussbuchungen, wie sie `hauptbuch.abschluss_buchen` verlangt.
    freigegeben = abgleich = kostenanteil = NULL
    for p in StwegAbrechnungPosition.objects.filter(abrechnung__liegenschaft=lg,
                                                    buchungen__isnull=False).distinct():
        vorgeschrieben = (StwegVorschreibung.objects
                          .filter(einheit=p.einheit, budget__jahr=p.abrechnung.jahr, budget__liegenschaft=lg)
                          .aggregate(s=Sum('betrag'))['s'] or NULL)
        freigegeben += vorgeschrieben
        abgleich += p.kostenanteil - vorgeschrieben
        kostenanteil += p.kostenanteil
    pos = StwegInkassoPosition.objects.filter(einheit__liegenschaft=lg, buchung__isnull=False,
                                              buchung__storniert_am__isnull=True)
    mahnspesen = pos.filter(art='mahnspesen').aggregate(s=Sum('betrag'))['s'] or NULL
    auslagen = pos.filter(art='betreibungskosten').aggregate(s=Sum('betrag'))['s'] or NULL
    einlagen = (ErneuerungsfondsBewegung.objects.filter(fonds__liegenschaft=lg, art='einlage',
                                                        buchung__isnull=False).aggregate(s=Sum('betrag'))['s'] or NULL)
    entnahmen = (ErneuerungsfondsBewegung.objects.filter(fonds__liegenschaft=lg, art='entnahme',
                                                         buchung__isnull=False).aggregate(s=Sum('betrag'))['s'] or NULL)
    return {
        '1110': v_summe - (z_summe - zins_summe) + abgleich + einlagen + mahnspesen + auslagen,
        '2035': -(v_summe - freigegeben),
        '3100': -kostenanteil,
        '2800': -(einlagen - entnahmen),
        '3110': -mahnspesen,
        '3120': -zins_summe,
    }


def abstimmung_hauptbuch(lg):
    """Gibt {konto: {'hauptbuch', 'erwartet', 'differenz'}} zurück. Alle Differenzen 0 = abgestimmt."""
    soll = erwartet(lg)
    ergebnis = {}
    for nummer, w in soll.items():
        ist = _saldo(lg, nummer)
        ergebnis[nummer] = {'hauptbuch': ist, 'erwartet': w, 'differenz': ist - w}
    return ergebnis


def abgestimmt(lg):
    return all(v['differenz'] == 0 for v in abstimmung_hauptbuch(lg).values())


def pruefe(lg):
    """Befunde als Liste von (Stufe, Text). Leer = nichts zu beanstanden."""
    from stweg.schluessel import SchluesselFehler, gewichte, standard_schluessel
    befunde = []
    try:
        pruefe_wertquoten(lg)
    except WertquotenFehler as e:
        befunde.append((FEHLER, str(e.message)))
    einheiten = list(stimm_einheiten(lg).select_related('stockwerkeigentuemer'))
    for e in einheiten:
        if e.stockwerkeigentuemer_id is None:
            befunde.append((WARNUNG, f'Einheit «{e.bezeichnung}» hat keinen Stockwerkeigentümer.'))
        elif not e.stockwerkeigentuemer.email:
            befunde.append((HINWEIS, f'Eigentümer «{e.stockwerkeigentuemer.firma_oder_name}» hat keine E-Mail-Adresse '
                                     '(Einladung und Rechnung nur per Post).'))
    from tickets.models import SchadenMeldung
    offen = SchadenMeldung.objects.filter(liegenschaft=lg).exclude(status='erledigt')
    ohne = offen.filter(kostentraeger='').count()
    if ohne:
        befunde.append((WARNUNG, f'{ohne} offene Schadenmeldung(en) ohne Kostenträger: «Sonderrecht» oder «gemeinschaftlich» '
                                 'ist nicht erklärt (Art. 712b ZGB) — es wird weder beauftragt noch erledigt.'))
    for n in lg.einheiten.filter(gehoert_zu__isnull=False):
        if n.wertquote and n.wertquote != 0:
            befunde.append((HINWEIS, f'Nebenraum «{n.bezeichnung}» trägt eine Wertquote ({n.wertquote}) — sie zählt '
                                     'nicht mit.'))
    for s in lg.stweg_schluessel.all():
        try:
            gewichte(s, einheiten)
        except SchluesselFehler as e:
            befunde.append((FEHLER, str(e)))
    if lg.status == lg.STATUS_AKTIV and not lg.stweg_schluessel.filter(ist_standard=True).exists():
        befunde.append((HINWEIS, 'Es ist noch kein Standardschlüssel angelegt (entsteht beim ersten Budget).'))
    fonds = Erneuerungsfonds.objects.filter(liegenschaft=lg).first()
    if fonds is not None:
        netto = (ErneuerungsfondsBewegung.objects.filter(fonds=fonds, art='einlage').aggregate(s=Sum('betrag'))['s']
                 or NULL) - (ErneuerungsfondsBewegung.objects.filter(fonds=fonds, art='entnahme')
                             .aggregate(s=Sum('betrag'))['s'] or NULL)
        if (fonds.bestand or NULL) != netto:
            befunde.append((FEHLER, f'Fondsbestand CHF {fonds.bestand} stimmt nicht mit den Bewegungen '
                                    f'(CHF {netto}) überein.'))
        if (fonds.bestand or NULL) < 0:
            befunde.append((FEHLER, 'Der Fondsbestand ist negativ.'))
    for kto in ('2800', '2035'):
        from finance.models import Buchungskonto
        k = Buchungskonto.objects.filter(nummer=kto).first()
        if k is not None and k.typ != 'passiv':
            befunde.append((FEHLER, f'Konto {kto} muss ein Passivkonto sein (ist «{k.typ}»).'))
    ungebucht = StwegAkonto.objects.filter(einheit__liegenschaft=lg, buchung__isnull=True).count()
    if ungebucht:
        befunde.append((HINWEIS, f'{ungebucht} Zahlung(en) ohne Buchung im Hauptbuch (Zeit vor der Anbindung) — '
                                 'sie fehlen in der Abstimmung.'))
    for a in StwegAbrechnung.objects.filter(liegenschaft=lg, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN):
        if not StwegAbrechnungPosition.objects.filter(abrechnung=a, buchungen__isnull=False).exists() \
                and a.positionen.exclude(kostenanteil=0).exists():
            befunde.append((WARNUNG, f'Abrechnung {a.jahr} ist abgeschlossen, aber nicht ins Hauptbuch gebucht.'))
    for konto, z in abstimmung_hauptbuch(lg).items():
        if z['differenz'] != 0:
            befunde.append((FEHLER, f'Hauptbuch {konto}: CHF {z["hauptbuch"]}, erwartet CHF {z["erwartet"]} '
                                    f'(Differenz CHF {z["differenz"]}).'))
    return befunde
