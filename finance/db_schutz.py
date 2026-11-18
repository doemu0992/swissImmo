"""Datenbank-Schutz der Buchungen (Audit FIN-15 / SICH-06, Etappe 2).

WARUM ES DAS GIBT

Der Manager-Schutz (`BuchungQuerySet`) hält nur, was durch Django läuft. Rohes
SQL, ein Skript mit eigener Verbindung oder die Kaskade beim Löschen einer
Organisation umgingen ihn. Unter OR 957a/958f und GeBüV Art. 3/9 gilt ein Beleg
erst als unveränderlich, wenn auch die Datenbank die Änderung verweigert.

WAS DER TRIGGER (PostgreSQL) TUT

* `DELETE` auf `core_buchung`: nie.
* `UPDATE`: nur das, was ein Beleg nachträglich darf — die Verknüpfungen zu den
  Nebenbüchern (Zahlung, Rechnung), die Storno-Marke (einmal setzen, nie
  zurücknehmen) und `erstellt_von` auf NULL (wenn das Konto gelöscht wird).
  Alles andere ist gesperrt, **auch eine Spalte, die erst später dazukommt**: Der
  Trigger vergleicht die ganze Zeile als JSON und nimmt nur die erlaubten
  Spalten aus. Eine neue Spalte an `Buchung` ist damit erst einmal gesperrt und
  muss hier bewusst freigegeben werden.
* Die benannte Ausnahme (`ausnahme_aendern` / `ausnahme_loeschen` /
  `Buchung.delete(force=True)`, Datenreset) setzt innerhalb ihrer Transaktion die
  Sitzungsvariable `swissimmo.buchung_ausnahme` auf die Begründung. Nur mit ihr
  lässt der Trigger Änderungen zu. Die Variable gilt nur bis zum Ende der
  Transaktion (`set_config(..., true)`) und wird nach der Ausnahme sofort wieder
  geleert.

WAS NICHT GESCHÜTZT IST (ehrlich)
* `TRUNCATE` (Django-Tests leeren Tabellen damit; ein Trigger darauf hielte jede
  `TransactionTestCase` an), `DROP TABLE`, `ALTER TABLE ... DISABLE TRIGGER`:
  wer Eigentümer der Tabelle oder Superuser ist, kommt vorbei. Der Betrieb
  verwendet für die Anwendung eine Rolle ohne diese Rechte (Betriebsdoku).
* SQLite: kein Trigger. Dort gilt weiter der Manager-Schutz.
* Die Periodensperre gilt seit Roadmap 2.2 auch im Trigger (siehe unten); die Prüfung im Manager/Modell
  bleibt als erste, klar formulierte Schranke.

PERIODENSPERRE IM TRIGGER (PostgreSQL)

* `INSERT`: eine neue Buchung mit `datum <= Organisation.buchung_gesperrt_bis` wird abgewiesen.
* `UPDATE`: wer die Verknüpfung zu Zahlung oder Rechnung einer Buchung in gesperrter Periode ändert, wird abgewiesen (die
  Storno-Marke bleibt erlaubt, wie im Modell). Die Sperre liest der Trigger aus `core_verwaltung` (der Tabelle von
  `crm.Organisation`) je Organisation der Buchung.
* Die benannte Ausnahme öffnet auch das. Sie ist die einzige Hintertür, und sie steht im Protokoll.
* Wiederherstellung: Eine vollständige `pg_restore` legt die Trigger erst NACH dem Laden der Daten an und ist nicht betroffen;
  wer nur Daten einspielt (`--data-only`), muss die Sperre vorher aufheben oder `--disable-triggers` (Superuser) verwenden.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connections, transaction

logger = logging.getLogger(__name__)

VARIABLE = 'swissimmo.buchung_ausnahme'
FUNKTION = 'swissimmo_buchung_schutz'
TRIGGER = 'swissimmo_buchung_schutz_trg'

#: Spalten, die sich nachträglich ändern dürfen (siehe Modul-Doku).
ERLAUBT = ('zahlungseingang_id', 'kreditoren_rechnung_id', 'debitoren_rechnung_id', 'storniert_am')

FUNKTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNKTION}() RETURNS trigger AS $fn$
DECLARE
    erlaubt text[] := ARRAY['zahlungseingang_id', 'kreditoren_rechnung_id',
                            'debitoren_rechnung_id', 'storniert_am', 'erstellt_von_id'];
    sperre date;
BEGIN
    IF coalesce(current_setting('{VARIABLE}', true), '') <> '' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Buchung % darf nicht geloescht werden (Revisionssicherheit, OR 957a/958f): bitte stornieren.',
            OLD.id;
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT buchung_gesperrt_bis INTO sperre FROM core_verwaltung WHERE id = NEW.organisation_id;
        IF sperre IS NOT NULL AND NEW.datum <= sperre THEN
            RAISE EXCEPTION 'Periode gesperrt: Buchungen bis % sind abgeschlossen (Datum %). Bitte spaetere Periode waehlen.',
                sperre, NEW.datum;
        END IF;
        RETURN NEW;
    END IF;

    IF (to_jsonb(NEW) - erlaubt) IS DISTINCT FROM (to_jsonb(OLD) - erlaubt) THEN
        RAISE EXCEPTION 'Buchung % ist unveraenderlich (Revisionssicherheit, OR 957a/958f): bitte stornieren und neu buchen.',
            OLD.id;
    END IF;
    IF OLD.storniert_am IS NOT NULL AND NEW.storniert_am IS DISTINCT FROM OLD.storniert_am THEN
        RAISE EXCEPTION 'Buchung %: Ein Storno laesst sich nicht zuruecknehmen.', OLD.id;
    END IF;
    IF OLD.erstellt_von_id IS NOT NULL AND NEW.erstellt_von_id IS NOT NULL
       AND NEW.erstellt_von_id <> OLD.erstellt_von_id THEN
        RAISE EXCEPTION 'Buchung %: Der Ersteller laesst sich nicht aendern.', OLD.id;
    END IF;
    IF OLD.erstellt_von_id IS NULL AND NEW.erstellt_von_id IS NOT NULL THEN
        RAISE EXCEPTION 'Buchung %: Der Ersteller laesst sich nicht nachtragen.', OLD.id;
    END IF;
    IF NEW.zahlungseingang_id IS DISTINCT FROM OLD.zahlungseingang_id
       OR NEW.kreditoren_rechnung_id IS DISTINCT FROM OLD.kreditoren_rechnung_id
       OR NEW.debitoren_rechnung_id IS DISTINCT FROM OLD.debitoren_rechnung_id THEN
        SELECT buchung_gesperrt_bis INTO sperre FROM core_verwaltung WHERE id = OLD.organisation_id;
        IF sperre IS NOT NULL AND OLD.datum <= sperre THEN
            RAISE EXCEPTION 'Periode gesperrt: Buchungen bis % sind abgeschlossen und lassen sich nicht mehr aendern.', sperre;
        END IF;
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = f"""
DROP TRIGGER IF EXISTS {TRIGGER} ON core_buchung;
CREATE TRIGGER {TRIGGER}
    BEFORE INSERT OR UPDATE OR DELETE ON core_buchung
    FOR EACH ROW EXECUTE FUNCTION {FUNKTION}();
"""

TRIGGER_ENTFERNEN_SQL = f"""
DROP TRIGGER IF EXISTS {TRIGGER} ON core_buchung;
DROP FUNCTION IF EXISTS {FUNKTION}();
"""


def trigger_installieren(schema_editor):
    """Legt Funktion und Trigger an (nur PostgreSQL; sonst nichts)."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(FUNKTION_SQL, params=None)
    schema_editor.execute(TRIGGER_SQL, params=None)


def trigger_entfernen(schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(TRIGGER_ENTFERNEN_SQL, params=None)


def trigger_vorhanden(using='default'):
    """True, wenn der Schutz auf dieser Datenbank aktiv ist (PostgreSQL)."""
    verbindung = connections[using]
    if verbindung.vendor != 'postgresql':
        return False
    with verbindung.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal', [TRIGGER])
        return cur.fetchone() is not None


#: Gilt nur im Block von `ausnahme()`: Auch die Sperren des QuerySets sehen so, dass die
#: Kaskade (Django schreibt die Selbstreferenz `storno_von` per `update()` auf NULL)
#: innerhalb einer benannten Ausnahme nicht an der eigenen Sperre scheitert.
_AKTIV = ContextVar('buchung_ausnahme', default='')


def ausnahme_aktiv():
    return bool(_AKTIV.get())


@contextmanager
def ausnahme(grund, using='default'):
    """Öffnet für den Block die Ausnahme vom DB-Schutz (nur mit Begründung).

    Läuft in einer eigenen Transaktion bzw. einem Sicherungspunkt: wirft der Block,
    rollt alles zurück — auch die Variable. Nach dem Block wird sie geleert, damit
    eine umgebende Transaktion nicht ungeschützt weiterläuft.
    """
    verbindung = connections[using]
    marke = _AKTIV.set(str(grund).strip() or '?')
    try:
        with transaction.atomic(using=using):
            if verbindung.vendor == 'postgresql':
                with verbindung.cursor() as cur:
                    cur.execute('SELECT set_config(%s, %s, true)', [VARIABLE, str(grund).strip() or '?'])
            yield
            if verbindung.vendor == 'postgresql':
                with verbindung.cursor() as cur:
                    cur.execute('SELECT set_config(%s, %s, true)', [VARIABLE, ''])
    finally:
        _AKTIV.reset(marke)


# ---------------------------------------------------------------------------
# Eindeutigkeit für Storno und Bankreferenz (Teilindizes)
# ---------------------------------------------------------------------------

#: (Indexname, Tabelle, Spalten, Bedingung, Prüfabfrage auf Dubletten)
EINDEUTIGKEITEN = (
    ('uniq_storno_je_original', 'core_buchung', 'storno_von_id',
     'ist_storno AND storno_von_id IS NOT NULL',
     'SELECT storno_von_id, COUNT(*) FROM core_buchung '
     'WHERE ist_storno AND storno_von_id IS NOT NULL GROUP BY storno_von_id HAVING COUNT(*) > 1'),
    ('uniq_bankreferenz_je_organisation', 'core_zahlungseingang', 'organisation_id, bank_referenz',
     "bank_referenz <> '' AND status <> 'storniert'",
     "SELECT organisation_id, bank_referenz, COUNT(*) FROM core_zahlungseingang "
     "WHERE bank_referenz <> '' AND status <> 'storniert' "
     "GROUP BY organisation_id, bank_referenz HAVING COUNT(*) > 1"),
)


def eindeutigkeiten_nachziehen(schema_editor):
    """Legt die Teilindizes an, die der Bestand zulässt. Gibt die ÜBERSPRUNGENEN zurück.

    Ein Altbestand mit Dubletten darf die Migration nicht brechen und lässt sich nicht
    automatisch bereinigen (es sind echte Buchungen). Enthält er welche, wird der
    Index NICHT angelegt, der Fall mit den betroffenen Schlüsseln laut protokolliert
    und der Rest läuft weiter. Nach der Bereinigung (Gegenbuchung/Stornierung der
    Dublette) holt `manage.py db_schutz` den Index nach.
    """
    verbindung = schema_editor.connection
    uebersprungen = []
    with verbindung.cursor() as cur:
        tabellen = set(verbindung.introspection.table_names(cur))
        for name, tabelle, spalten, bedingung, pruefung in EINDEUTIGKEITEN:
            if tabelle not in tabellen:
                continue
            cur.execute('SELECT 1 FROM pg_indexes WHERE indexname = %s'
                        if verbindung.vendor == 'postgresql'
                        else "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = %s", [name])
            if cur.fetchone():
                continue
            cur.execute(pruefung)
            dubletten = cur.fetchall()
            if dubletten:
                uebersprungen.append((name, dubletten))
                logger.error('Eindeutigkeit %s NICHT angelegt: %d doppelte Schlüssel im Bestand, '
                             'zum Beispiel %s. Bestand bereinigen, dann "manage.py db_schutz".',
                             name, len(dubletten), dubletten[:5])
                continue
            schema_editor.execute(f'CREATE UNIQUE INDEX {name} ON {tabelle} ({spalten}) WHERE {bedingung}')
    return uebersprungen


# ---------------------------------------------------------------------------
# Prüfregeln (CHECK) für Buchungen
# ---------------------------------------------------------------------------

#: (Name, Tabelle, Bedingung, Abfrage auf Verletzungen im Bestand)
PRUEFREGELN = (
    ('chk_buchung_betrag_positiv', 'core_buchung', 'betrag > 0',
     'SELECT id, betrag FROM core_buchung WHERE NOT (betrag > 0) ORDER BY id'),
    ('chk_buchung_soll_ungleich_haben', 'core_buchung', 'soll_konto_id <> haben_konto_id',
     'SELECT id, soll_konto_id FROM core_buchung WHERE NOT (soll_konto_id <> haben_konto_id) ORDER BY id'),
)


def pruefregeln_nachziehen(schema_editor):
    """Legt die CHECK-Constraints an, die der Bestand zulässt (PostgreSQL). Gibt die ÜBERSPRUNGENEN zurück.

    Wie bei den Eindeutigkeiten: Ein Altbestand mit Buchungen, die gegen die Regel verstossen, darf die Migration nicht
    brechen und lässt sich nicht bereinigen (es sind echte, unveränderliche Buchungen). Dann wird die Regel NICHT
    angelegt, der Fall mit Beispielen laut protokolliert, und `manage.py db_schutz` holt sie nach der Klärung nach.
    Neue Buchungen prüft in jedem Fall das Modell (`Buchung._pruefe_neue_buchung`).

    SQLite kennt `ALTER TABLE ... ADD CONSTRAINT` nicht; dort gilt nur die Prüfung im Modell.
    """
    verbindung = schema_editor.connection
    uebersprungen = []
    if verbindung.vendor != 'postgresql':
        return uebersprungen
    with verbindung.cursor() as cur:
        tabellen = set(verbindung.introspection.table_names(cur))
        for name, tabelle, bedingung, pruefung in PRUEFREGELN:
            if tabelle not in tabellen:
                continue
            cur.execute('SELECT 1 FROM pg_constraint WHERE conname = %s', [name])
            if cur.fetchone():
                continue
            cur.execute(pruefung)
            verletzer = cur.fetchall()
            if verletzer:
                uebersprungen.append((name, verletzer))
                logger.error('Prüfregel %s NICHT angelegt: %d Buchung(en) verstossen im Bestand dagegen, zum Beispiel %s. '
                             'Fall klären (Gegenbuchung), dann "manage.py db_schutz".', name, len(verletzer), verletzer[:5])
                continue
            schema_editor.execute(f'ALTER TABLE {tabelle} ADD CONSTRAINT {name} CHECK ({bedingung})')
    return uebersprungen


def pruefregeln_entfernen(schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for name, tabelle, *_rest in PRUEFREGELN:
        schema_editor.execute(f'ALTER TABLE {tabelle} DROP CONSTRAINT IF EXISTS {name}')


def pruefregeln_vorhanden(using='default'):
    """Die Namen der Prüfregeln, die in der Datenbank bestehen (PostgreSQL; sonst leer)."""
    verbindung = connections[using]
    if verbindung.vendor != 'postgresql':
        return set()
    with verbindung.cursor() as cur:
        cur.execute('SELECT conname FROM pg_constraint WHERE conname = ANY(%s)', [[n for n, *_ in PRUEFREGELN]])
        return {zeile[0] for zeile in cur.fetchall()}


def eindeutigkeiten_entfernen(schema_editor):
    for name, *_rest in EINDEUTIGKEITEN:
        schema_editor.execute(f'DROP INDEX IF EXISTS {name}')
