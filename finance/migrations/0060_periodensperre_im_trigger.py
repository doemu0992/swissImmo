"""Die Periodensperre gilt auch im Datenbank-Trigger der Buchungen (Roadmap 2.2).

Funktion und Trigger werden neu angelegt (`CREATE OR REPLACE` / `DROP TRIGGER IF EXISTS`): INSERT einer Buchung in gesperrter
Periode und das Ändern der Verknüpfungen einer Buchung in gesperrter Periode werden abgewiesen. Nur PostgreSQL; auf SQLite
gilt weiter der Schutz im Modell. Rückwärts bleibt der erweiterte Trigger bestehen (er ist mit dem alten verträglich).
"""
from django.db import migrations

from finance import db_schutz


def _trigger(apps, schema_editor):
    db_schutz.trigger_installieren(schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0059_sperre_aenderung"),
    ]

    operations = [
        migrations.RunPython(_trigger, migrations.RunPython.noop),
    ]
