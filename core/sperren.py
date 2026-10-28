"""Sperren für Geldpfade: zwei gleichzeitige Anfragen dürfen nicht beide buchen.

WARUM ES DAS BRAUCHT

Ein Doppelklick, zwei Browser-Tabs, ein Scheduler neben dem Knopf: Dieselbe
Aktion läuft zweimal gleichzeitig. Wer erst den Zustand liest («offen?»), dann
prüft und dann bucht, hat zwischen Lesen und Buchen ein Fenster, in dem der
zweite Lauf dasselbe liest. Gemessen am 28.10.2026 (Audit FIN-01/02/04/05):
vier parallele Klicks auf eine Rechnung über CHF 1'700 buchten CHF 6'800 ein,
und das Hauptbuch blieb dabei in sich stimmig — es gab nichts, was den Fehler
anzeigte.

DIE REGEL, DIE ALLE PFADE TEILEN

    with transaction.atomic():
        zeile = Modell.objects.select_for_update().get(pk=...)   # sperren
        if zeile.status != 'offen': ...                           # DANACH prüfen
        ...buchen...

Der Zustand wird **nach** dem Sperren gelesen. Eine Prüfung vor dem Sperren
beweist nichts: Sie sieht den Stand von vor dem Warten.

ZWEI WERKZEUGE

* `select_for_update()` auf der Zeile — für alles, was an EINEM Datensatz hängt
  (Rechnung, Zahlung, Buchung).
* `sperre_organisation(name, organisation_id)` — für Läufe, die an keinem
  einzelnen Datensatz hängen (Jahresabschluss, Kontoauszug-Import, Belegnummer,
  Eigentümerauszahlung gegen ein gemeinsames Bankkonto). Das ist eine
  PostgreSQL-«Advisory Lock» auf einen Namen: Wer sie hält, hält sie bis zum
  Ende seiner Transaktion; der Nächste wartet. Eine Tabelle, eine Migration
  oder eine Zeile als Anker braucht es dafür nicht.

AUF SQLITE sind beide Werkzeuge wirkungslos (`select_for_update` wird von
Django ignoriert, die Advisory Lock gibt es nicht). Das ist gewollt: SQLite
serialisiert Schreiber ohnehin, und die Tests laufen dort als Folgetests. Dass
die Sperre wirkt, belegen nur Tests mit echten Threads auf PostgreSQL
(`core/tests/test_geld_parallel.py`).
"""
import hashlib

from django.db import DEFAULT_DB_ALIAS, connections
from django.db.transaction import TransactionManagementError


def _schluessel(*teile):
    """64-Bit-Schlüssel (vorzeichenbehaftet) aus den Namensteilen."""
    roh = ':'.join(str(t) for t in ('swissimmo', *teile)).encode('utf-8')
    return int.from_bytes(hashlib.blake2b(roh, digest_size=8).digest(), 'big', signed=True)


def sperre(*teile):
    """Wartet, bis niemand sonst die Sperre `teile` hält, und hält sie bis zum
    Ende der laufenden Transaktion (Commit oder Rollback gibt sie frei).

    Muss in `transaction.atomic()` stehen — ausserhalb wäre sie schon beim
    Rückkehren der Anweisung wieder frei und schützte nichts. Das ist ein
    Programmfehler und wird laut gemeldet, auch auf SQLite, damit er dort
    schon im Test auffällt und nicht erst auf PostgreSQL.
    """
    verbindung = connections[DEFAULT_DB_ALIAS]
    if not verbindung.in_atomic_block:
        raise TransactionManagementError(
            'sperre() gehört in eine transaction.atomic()-Sperrzone — sonst ist '
            'die Sperre schon wieder frei, bevor gebucht wird.')
    if verbindung.vendor != 'postgresql':
        return
    with verbindung.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_schluessel(*teile)])


def sperre_organisation(name, organisation_id):
    """Sperre je Organisation und Vorgang. Verwaltungen blockieren sich nicht
    gegenseitig: Der Schlüssel enthält die Organisations-ID."""
    sperre(name, organisation_id)


def erwarteter_betrag(post, feld='erwartet_offen'):
    """Der Betrag, den die Maske beim Öffnen gezeigt hat (verstecktes Feld), oder `None`.

    WARUM: Ein Doppelklick mit AUSDRÜCKLICHEM Teilbetrag ist von zwei echten
    Teilzahlungen nicht zu unterscheiden — beide tragen denselben Betrag. Die
    Maske schickt deshalb mit, was sie als «offen» gezeigt hat. Hat die erste
    Anfrage gebucht, stimmt der Stand für die zweite nicht mehr, und sie wird
    als «bereits verbucht» abgewiesen. Eine Anfrage ohne das Feld (API,
    Skript, alte Maske) wird nicht geprüft und verhält sich wie bisher.
    """
    from decimal import Decimal, InvalidOperation
    roh = (post.get(feld) or '').strip()
    if not roh:
        return None
    try:
        wert = Decimal(roh.replace("'", '').replace('’', ''))
    except InvalidOperation:
        return None
    return wert if wert.is_finite() else None
