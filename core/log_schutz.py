"""Datenbank-Schutz des Audit-Logs (Roadmap Nr. 9): nur anhängbar.

Der Manager (`AktivitaetsLogQuerySet`) und das Modell sperren Änderungen und
Löschungen, solange sie durch Django laufen. Auf PostgreSQL hält zusätzlich ein
Trigger rohes SQL und fremde Skripte auf:

* `DELETE` auf `core_aktivitaetslog`: nie (ausser benannte Ausnahme).
* `UPDATE`: nur das Leeren des Benutzerbezugs (`benutzer_id` -> NULL, wenn ein
  Konto gelöscht wird). Alles Übrige ist gesperrt, auch Spalten, die später
  dazukommen (Zeilenvergleich als JSON).
* Die benannte Ausnahme `finance.db_schutz.ausnahme(grund)` setzt dieselbe
  Sitzungsvariable wie bei den Buchungen; nur damit lässt der Trigger Änderungen
  zu (DSG-Anonymisierung).

Nicht geschützt (ehrlich): `TRUNCATE`, `DROP TABLE`, `DISABLE TRIGGER` für
Tabelleneigentümer/Superuser; SQLite hat keinen Trigger. Wer so an der Tabelle vorbeikommt, bricht die Hash-Kette
(`core/log_kette.py`, `manage.py log_kette_pruefen`) — und, mit Ankerpunkt ausser Haus, auch eine neu berechnete.
"""
from finance.db_schutz import VARIABLE

FUNKTION = 'swissimmo_log_schutz'
TRIGGER = 'swissimmo_log_schutz_trg'

FUNKTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNKTION}() RETURNS trigger AS $fn$
DECLARE
    erlaubt text[] := ARRAY['benutzer_id'];
BEGIN
    IF coalesce(current_setting('{VARIABLE}', true), '') <> '' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Logeintrag % darf nicht geloescht werden (Audit-Trail ist nur anhaengbar).', OLD.id;
    END IF;
    IF (to_jsonb(NEW) - erlaubt) IS DISTINCT FROM (to_jsonb(OLD) - erlaubt) THEN
        RAISE EXCEPTION 'Logeintrag % ist unveraenderlich (Audit-Trail ist nur anhaengbar).', OLD.id;
    END IF;
    IF NEW.benutzer_id IS NOT NULL AND NEW.benutzer_id IS DISTINCT FROM OLD.benutzer_id THEN
        RAISE EXCEPTION 'Logeintrag %: Der Benutzer laesst sich nicht aendern.', OLD.id;
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = f"""
DROP TRIGGER IF EXISTS {TRIGGER} ON core_aktivitaetslog;
CREATE TRIGGER {TRIGGER}
    BEFORE UPDATE OR DELETE ON core_aktivitaetslog
    FOR EACH ROW EXECUTE FUNCTION {FUNKTION}();
"""

ENTFERNEN_SQL = f"""
DROP TRIGGER IF EXISTS {TRIGGER} ON core_aktivitaetslog;
DROP FUNCTION IF EXISTS {FUNKTION}();
"""


def trigger_installieren(schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(FUNKTION_SQL, params=None)
    schema_editor.execute(TRIGGER_SQL, params=None)


def trigger_entfernen(schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(ENTFERNEN_SQL, params=None)


def trigger_vorhanden(using='default'):
    from django.db import connections
    verbindung = connections[using]
    if verbindung.vendor != 'postgresql':
        return False
    with verbindung.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal', [TRIGGER])
        return cur.fetchone() is not None
