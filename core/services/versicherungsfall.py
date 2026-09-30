"""Versicherungsfall: Schaden melden, Selbstbehalt klären, Entschädigung verbuchen.

Stresstest 30.09.2026: Ein Wasserschaden lief 83 Tage durch, ohne dass je eine
Meldung an die Gebäudeversicherung, eine Police oder ein Selbstbehalt zur Sprache
kam. Jetzt:

· `melden` hält Police, Schadennummer, Meldedatum und Schadensumme fest. Den
  Selbstbehalt übernimmt es von der Police (`Versicherung.selbstbehalt`).
· Der Selbstbehalt trägt der Eigentümer — oder der Mieter, wenn die Verwaltung ihn
  überwälzt (`selbstbehalt_ueberwaelzen`). Ob der Mieter haftet, entscheidet die
  Verwaltung im Einzelfall; das System rechnet nur, wenn sie es bestimmt.
· Die Versicherungsleistung wird als Minderung des Schadenaufwands gebucht
  (`entschaedigung_verbuchen`): Bank an das Aufwandskonto der Reparatur.
"""
from decimal import Decimal

from django.utils import timezone

FALLART_SCHLUESSEL = 'versicherungsfall'


def aufwand_konto(ticket):
    """Aufwandskonto der Reparatur: Konto der zugehörigen Kreditorenrechnung, sonst 4000."""
    for a in ticket.handwerker_auftraege.select_related('kreditoren_rechnung__konto').all():
        kr = a.kreditoren_rechnung
        if kr is not None and kr.konto_id:
            return kr.konto.nummer
    return '4000'


def schadensumme_vorschlag(ticket):
    """Summe der effektiven (sonst geschätzten) Kosten der Handwerkeraufträge."""
    summe = Decimal('0.00')
    for a in ticket.handwerker_auftraege.all():
        summe += a.kosten_effektiv or a.kosten_geschaetzt or Decimal('0.00')
    return summe


def _fall(ticket, benutzer=None, eroeffnen=False):
    from django.contrib.contenttypes.models import ContentType

    from faelle.models import Fall, Fallart
    ct = ContentType.objects.get_for_model(type(ticket))
    fall = (Fall.objects.offen().filter(akte_typ=ct, akte_id=ticket.pk,
                                        fallart__schluessel=FALLART_SCHLUESSEL).first())
    if fall is None and eroeffnen:
        art = Fallart.objects.filter(schluessel=FALLART_SCHLUESSEL, aktiv=True).first()
        if art is not None:
            fall = Fall(fallart=art, akte=ticket, zustaendig=benutzer,
                        betreff=f'Versicherungsfall Ticket #{ticket.pk}: {ticket.titel}'[:200])
            fall.save()
            fall.schritte_anlegen()
    return fall


def _schritte(ticket, teile, benutzer=None):
    fall = _fall(ticket)
    if fall is None:
        return 0
    n = 0
    for s in fall.schritte.filter(erledigt_am__isnull=True):
        if any(t.lower() in s.bezeichnung.lower() for t in teile):
            s.erledigen(benutzer)
            n += 1
    return n


def melden(ticket, *, police=None, schadennummer='', gemeldet_am=None, schadensumme=None,
           traeger='eigentuemer', benutzer=None, bemerkung=''):
    """Erfasst den Versicherungsfall. Wirft ValueError bei unzulässigen Angaben."""
    from core.models import Pendenz
    from tickets.models import Versicherungsfall

    heute = timezone.localdate()
    gemeldet_am = gemeldet_am or heute
    if gemeldet_am > heute:
        raise ValueError('Das Meldedatum liegt in der Zukunft.')
    if traeger not in dict(Versicherungsfall.TRAEGER):
        raise ValueError('Unbekannter Kostenträger für den Selbstbehalt.')
    if police is not None and police.liegenschaft_id != ticket.liegenschaft_id:
        raise ValueError('Die Police gehört zu einer anderen Liegenschaft.')
    if ticket.versicherungsfaelle.exclude(status='abgelehnt').exists():
        raise ValueError('Dieser Schaden ist bereits als Versicherungsfall erfasst.')
    if schadensumme is not None and schadensumme < 0:
        raise ValueError('Die Schadensumme darf nicht negativ sein.')
    selbstbehalt = (police.selbstbehalt if police is not None and police.selbstbehalt is not None
                    else Decimal('0.00'))
    vf = Versicherungsfall.objects.create(
        ticket=ticket, police=police, schadennummer=schadennummer.strip()[:60],
        gemeldet_am=gemeldet_am, schadensumme=schadensumme, selbstbehalt=selbstbehalt,
        selbstbehalt_traeger=traeger, bemerkung=bemerkung[:255])
    _fall(ticket, benutzer, eroeffnen=True)
    _schritte(ticket, ('melden',), benutzer)
    if vf.schadennummer:
        _schritte(ticket, ('Schadennummer',), benutzer)
    # Die Pendenz «Versicherungsmeldung prüfen» ist damit erledigt.
    for p in Pendenz.objects.filter(quelle=f'auto:versicherung:{ticket.pk}', erledigt=False):
        p.erledigt = True
        p.erledigt_am = heute
        p.save(update_fields=['erledigt', 'erledigt_am'])
    return vf


def selbstbehalt_ueberwaelzen(vf, vertrag, benutzer=None):
    """Stellt dem Mieter den Selbstbehalt in Rechnung (Soll Debitoren an Aufwandsminderung).

    Nur wenn der Kostenträger «Mieter» ist, ein Selbstbehalt besteht und der Vertrag zur
    betroffenen Einheit gehört. Einmalig.
    """
    from finance.booking import buche
    from finance.models import DebitorenRechnung

    if vf.selbstbehalt_traeger != 'mieter':
        raise ValueError('Der Selbstbehalt ist nicht dem Mieter zugewiesen.')
    if vf.selbstbehalt <= 0:
        raise ValueError('Es ist kein Selbstbehalt zu überwälzen.')
    if vf.selbstbehalt_rechnung_id:
        raise ValueError('Der Selbstbehalt wurde bereits in Rechnung gestellt.')
    ticket = vf.ticket
    if ticket.betroffene_einheit_id and vertrag.einheit_id != ticket.betroffene_einheit_id:
        raise ValueError('Der Vertrag gehört nicht zur betroffenen Einheit.')
    heute = timezone.localdate()
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else ticket.liegenschaft
    rechnung = DebitorenRechnung.objects.create(
        vertrag=vertrag, liegenschaft=lg, einheit=vertrag.einheit,
        titel=f'Selbstbehalt Versicherungsschaden (Ticket #{ticket.pk})',
        beschreibung=f'Selbstbehalt aus Schadenfall {vf.schadennummer or ticket.titel}.',
        datum=heute, faellig_am=heute + timezone.timedelta(days=30),
        betrag=vf.selbstbehalt, status='offen')
    buche('1100', aufwand_konto(ticket), vf.selbstbehalt,
          f'Selbstbehalt {vertrag.mieter} — Versicherungsschaden Ticket #{ticket.pk}',
          datum=heute, liegenschaft=lg, debitor=rechnung, user=benutzer)
    vf.selbstbehalt_rechnung = rechnung
    vf.save(update_fields=['selbstbehalt_rechnung'])
    _schritte(ticket, ('Selbstbehalt',), benutzer)
    return rechnung


def entschaedigung_verbuchen(vf, betrag, datum=None, bank='1020', benutzer=None):
    """Bucht die Versicherungsleistung (Bank an Aufwandskonto). Einmalig."""
    from finance.booking import buche
    from finance.models import Buchungskonto

    if vf.entschaedigung_am is not None:
        raise ValueError('Die Entschädigung ist bereits verbucht.')
    if betrag is None or betrag <= 0:
        raise ValueError('Die Entschädigung muss grösser als 0 sein.')
    if vf.status == 'abgelehnt':
        raise ValueError('Der Fall ist als abgelehnt erfasst.')
    heute = timezone.localdate()
    datum = datum or heute
    if datum > heute:
        raise ValueError('Das Datum der Entschädigung liegt in der Zukunft.')
    if not Buchungskonto.objects.filter(nummer=bank).exists():
        bank = '1020'
    ticket = vf.ticket
    buche(bank, aufwand_konto(ticket), betrag,
          f'Versicherungsleistung {vf.police.gesellschaft if vf.police_id else ""} — Ticket #{ticket.pk}'.replace('  ', ' '),
          datum=datum, liegenschaft=ticket.liegenschaft, user=benutzer)
    vf.entschaedigung_erhalten = betrag
    vf.entschaedigung_am = datum
    vf.status = 'entschaedigt'
    vf.save(update_fields=['entschaedigung_erhalten', 'entschaedigung_am', 'status'])
    _schritte(ticket, ('Entschädigung',), benutzer)
    return vf


def ablehnen(vf, benutzer=None):
    if vf.entschaedigung_am is not None:
        raise ValueError('Die Entschädigung ist bereits verbucht.')
    vf.status = 'abgelehnt'
    vf.save(update_fields=['status'])
    return vf
