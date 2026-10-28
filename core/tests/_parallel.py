"""Hilfen für Tests mit echten Threads (Parallelität gibt es nur auf PostgreSQL).

SQLite stellt Schreiber ohnehin hintereinander, und `select_for_update` ist dort
wirkungslos: Ein Rennen, das auf PostgreSQL Geld doppelt bucht, bleibt dort
unsichtbar. Tests, die eine Sperre BELEGEN sollen, laufen deshalb nur auf
PostgreSQL (`NUR_POSTGRES`) — in der CI im Job `test-postgres`.
"""
import threading
from unittest import skipUnless

from django.db import connection, connections

NUR_POSTGRES = skipUnless(connection.vendor == 'postgresql',
                          'Echte Parallelität gibt es nur auf PostgreSQL (SQLite serialisiert Schreiber).')


def parallel(anzahl, arbeit):
    """Führt `arbeit(i)` in `anzahl` Threads GLEICHZEITIG aus (Barriere) und gibt
    die Ergebnisse zurück. Jeder Thread hat seine eigene Datenbankverbindung
    und schliesst sie am Ende; eine Ausnahme wird als Ergebnis geliefert statt
    den Test zu beenden, damit der Test sie benennen kann.

    Die Mandantenkontext-Variable gilt je Thread: Wer ohne Anfrage arbeitet,
    setzt `organisation_kontext(...)` in `arbeit` selbst."""
    barriere = threading.Barrier(anzahl)
    ergebnisse = [None] * anzahl

    def lauf(i):
        try:
            barriere.wait(timeout=60)
            ergebnisse[i] = arbeit(i)
        except BaseException as exc:                     # noqa: BLE001
            ergebnisse[i] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=lauf, args=(i,)) for i in range(anzahl)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)
    return ergebnisse
