"""Zeit-Hilfen, die auch Migrationen importieren dürfen (SICH-24).

`datum_heute` ist der Vorgabewert für `DateField`s: das heutige Datum in der Zeitzone
der Anwendung (`settings.TIME_ZONE`, Europa/Zürich).

WARUM NICHT `default=timezone.now`
Das liefert ein `datetime` in UTC. Im Speicher blieb es ein Datum-mit-Uhrzeit, bis das
Objekt neu geladen wurde: Der Vergleich `buchung.datum <= gesperrt_bis` warf
`TypeError: can't compare datetime.datetime to datetime.date`, sobald eine Buchung ohne
Datum in eine gesperrte Periode fiel; und das Datum selbst war zwischen 00:00 und 01:00
(Sommerzeit: 02:00) noch das des Vortags. `localdate()` gibt ein `date` und den Zürcher Tag.

Eine eigene Funktion statt `timezone.localdate` direkt, weil Django `default=` in die
Migration schreibt: Der Verweis muss ein importierbarer Name bleiben.
"""
from django.utils import timezone


def datum_heute():
    """Das heutige Datum in der Zeitzone der Anwendung."""
    return timezone.localdate()
