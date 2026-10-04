"""Erneuerungsfonds einer STWEG: Einlagen und Entnahmen.

BUCHHALTERISCHE REGEL (zwingend): Der Fonds gehört der Gemeinschaft. Einlagen
sind KEIN Ertrag der Verwaltung und auch kein Aufwand, sondern eine
Verbindlichkeit (Passivum, Konto 2800):

    Einlage   Soll 1110 Forderungen Stockwerkeigentümer / Haben 2800 Erneuerungsfonds
    Entnahme  Soll 2800 Erneuerungsfonds / Haben 1020 Bank

Der Miet-Weg (`run_erneuerungsfonds_einlage`: Aufwand 6900 an 2800) bleibt den
Mietliegenschaften vorbehalten und überspringt STWEG.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction

from core.tenancy import organisation_kontext
from finance import booking
from finance.models import Erneuerungsfonds, ErneuerungsfondsBewegung
from stweg.validierung import pruefe_wertquoten
from stweg.verteilung import verteile_nach_quoten


class FondsFehler(ValueError):
    pass


def _verlange_aktive_stweg(liegenschaft):
    if not liegenschaft.ist_stweg:
        raise FondsFehler(f'«{liegenschaft}» ist keine STWEG-Liegenschaft.')
    if liegenschaft.status != liegenschaft.STATUS_AKTIV:
        raise FondsFehler(f'«{liegenschaft}» ist nicht aktiv.')
    pruefe_wertquoten(liegenschaft)


def _fonds_passiv_sicherstellen():
    """2800 ist ein Passivum. Bestehende Kontenpläne führen es evtl. als 'bilanz'."""
    k = booking.konto('2800')
    if k.typ != 'passiv':
        k.typ = 'passiv'
        k.save(update_fields=['typ'])
    return k


def fonds_von(liegenschaft):
    fonds, _ = Erneuerungsfonds.objects.get_or_create(liegenschaft=liegenschaft)
    return fonds


@transaction.atomic
def jahreseinlage_belasten(liegenschaft, jahr, gesamtbetrag, *, datum=None, user=None):
    """Teilt die Jahreseinlage nach Wertquoten auf die Einheiten auf und belastet sie.

    Je Einheit eine Fonds-Bewegung und eine Buchung (Forderung an Fonds).
    Pro Jahr nur einmal. Gibt {einheit: Anteil} zurück.
    """
    _verlange_aktive_stweg(liegenschaft)
    gesamtbetrag = Decimal(gesamtbetrag)
    if gesamtbetrag <= 0:
        raise FondsFehler('Die Einlage muss grösser 0 sein.')
    with organisation_kontext(liegenschaft.organisation):
        fonds = fonds_von(liegenschaft)
        if fonds.bewegungen.filter(art='einlage', jahr=jahr).exists():
            raise FondsFehler(f'Für {jahr} wurde die Einlage bereits belastet.')
        _fonds_passiv_sicherstellen()
        einheiten = list(liegenschaft.einheiten.order_by('pk'))
        anteile = verteile_nach_quoten(gesamtbetrag, {e.pk: e.wertquote for e in einheiten})
        datum = datum or date(jahr, 12, 31)
        ergebnis = {}
        for e in einheiten:
            anteil = anteile[e.pk]
            if anteil == 0:
                continue
            text = f'Einlage Erneuerungsfonds {jahr}: {e.bezeichnung}'
            b = booking.buche('1110', '2800', anteil, text, datum=datum,
                              liegenschaft=liegenschaft, user=user)
            ErneuerungsfondsBewegung.objects.create(
                fonds=fonds, art='einlage', betrag=anteil, jahr=jahr, datum=datum,
                einheit=e, text=text, buchung=b)
            ergebnis[e] = anteil
        fonds.bestand = (fonds.bestand or Decimal('0')) + gesamtbetrag
        fonds.letzte_einlage_jahr = jahr
        fonds.jaehrliche_einlage = gesamtbetrag
        fonds.save(update_fields=['bestand', 'letzte_einlage_jahr', 'jaehrliche_einlage'])
        return ergebnis


@transaction.atomic
def entnahme_buchen(liegenschaft, jahr, betrag, text, *, datum=None, user=None):
    """Entnahme für eine beschlossene Erneuerung (Soll 2800 / Haben Bank)."""
    _verlange_aktive_stweg(liegenschaft)
    betrag = Decimal(betrag)
    if betrag <= 0:
        raise FondsFehler('Die Entnahme muss grösser 0 sein.')
    with organisation_kontext(liegenschaft.organisation):
        fonds = Erneuerungsfonds.objects.select_for_update().get_or_create(liegenschaft=liegenschaft)[0]
        if betrag > (fonds.bestand or Decimal('0')):
            raise FondsFehler(f'Entnahme CHF {betrag} übersteigt den Fondsbestand CHF {fonds.bestand}.')
        _fonds_passiv_sicherstellen()
        datum = datum or date.today()
        b = booking.buche('2800', '1020', betrag, f'Entnahme Erneuerungsfonds: {text}',
                          datum=datum, liegenschaft=liegenschaft, user=user)
        mv = ErneuerungsfondsBewegung.objects.create(
            fonds=fonds, art='entnahme', betrag=betrag, jahr=jahr, datum=datum, text=text, buchung=b)
        fonds.bestand -= betrag
        fonds.save(update_fields=['bestand'])
        return mv
