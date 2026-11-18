"""Eingaben aus Formularen, die nicht abstürzen: ein ungültiger Wert ergibt `None`, nie eine Fehlerseite.

`django.utils.dateparse.parse_date` gibt nur bei falschem FORMAT `None` zurück; ein Datum im richtigen Format, das
es nicht gibt («2026-02-30»), wirft `ValueError` und endete bisher als Fehler 500. Ebenso ist `Decimal('NaN')` ein
gültiger Wert, der erst beim Vergleichen oder Speichern knallt.
"""
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date, parse_datetime


def datum_oder_none(roh):
    """`YYYY-MM-DD` → `date`; leer, falsch formatiert oder nicht existierend → `None`."""
    try:
        return parse_date((roh or '').strip())
    except ValueError:
        return None


def zeit_oder_none(roh):
    """ISO-Datum mit Uhrzeit → `datetime`; sonst `None` (gleiche Falle wie bei `datum_oder_none`)."""
    try:
        return parse_datetime((roh or '').strip())
    except ValueError:
        return None


def endlicher_betrag(roh):
    """Ein bereits normalisierter Betrag (`core.utils.betrag.betrag_normalisieren`) → `Decimal`.

    Leer → `None`. Kein Betrag, `NaN` oder `Infinity` → `ValueError`, damit der Aufrufer eine Meldung zeigen kann."""
    if not roh:
        return None
    try:
        wert = Decimal(roh)
    except (InvalidOperation, ValueError):
        raise ValueError(roh)
    if not wert.is_finite():
        raise ValueError(roh)
    return wert
