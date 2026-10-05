"""Zielzeiten (SLA) für Tickets, abgeleitet aus der Priorität.

Die Priorität ist ein Freitextfeld mit gewachsenen Werten ('hoch', 'mittel',
'tief', teils 'niedrig'); unbekannte Werte fallen auf «mittel».
"""
from datetime import timedelta

from django.utils import timezone

#: Tage bis zur Erledigung je Priorität. 'notfall' (Wasserschaden,
#: Heizungsausfall im Winter) ist neu: am selben Tag.
SLA_TAGE = {'notfall': 0, 'hoch': 2, 'mittel': 7, 'tief': 14, 'niedrig': 14}


def sla_tage(prioritaet):
    return SLA_TAGE.get((prioritaet or '').strip().lower(), SLA_TAGE['mittel'])


def faellig_bis_fuer(prioritaet, ab=None):
    return (ab or timezone.localdate()) + timedelta(days=sla_tage(prioritaet))


def ist_ueberfaellig(ticket, heute=None):
    """Offenes Ticket mit abgelaufener Zielzeit."""
    heute = heute or timezone.localdate()
    return bool(ticket.faellig_bis and ticket.status != 'erledigt' and ticket.faellig_bis < heute)
