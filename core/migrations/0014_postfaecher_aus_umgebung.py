"""Die heutigen Zugangsdaten aus der Umgebung in die Postfächer übernehmen.

Betrifft **eine Zeile je Zweck**, weil es genau eine Organisation gibt — das
ist der Grund, warum dieser Umbau jetzt und nicht nach der zweiten Verwaltung
kommt.

WARUM DIESE MIGRATION NIEMALS SCHEITERT

Sie läuft im Deploy, unmittelbar vor dem Reload. Ein `migrate`, das an
fehlenden Zugangsdaten oder einem noch nicht gesetzten `IMAP_SCHLUESSEL`
abbricht, legt die ganze Anwendung lahm — wegen einer Bequemlichkeit. Fehlt
etwas, wird die Übernahme deshalb übersprungen und gemeldet.

UND WARUM DAS TROTZDEM KEINE EINBAHNSTRASSE IST

Eine übersprungene Übernahme wäre sonst endgültig: Ein zweites `migrate` führt
eine bereits angewendete Migration nicht erneut aus. Die Arbeit liegt deshalb
in `core/services/postfach_uebernahme.py` und ist von dort auch als Befehl
erreichbar:

    python manage.py postfaecher_uebernehmen

Wer den Schlüssel erst nach dem Deploy setzt, holt die Übernahme damit nach.
Die Reihenfolge ist so keine Bedingung mehr, sondern nur noch bequemer.

Die Umgebungsvariablen bleiben nach dieser Migration bestehen. Entfernt werden
sie erst, wenn der Verbindungstest in der Oberfläche grün ist — vorher wäre der
Rückweg verbaut.
"""
from django.db import migrations


def uebernehmen(apps, schema_editor):
    from core.services.postfach_uebernahme import uebernehmen as arbeit

    arbeit(apps.get_model('core', 'Postfach'),
           apps.get_model('crm', 'Organisation'))


def zurueck(apps, schema_editor):
    """Rückwärts: die Postfächer wieder entfernen.

    Verlustfrei, solange die Umgebungsvariablen noch stehen — und genau
    deshalb werden sie erst nach dem geglückten Verbindungstest entfernt.
    """
    apps.get_model('core', 'Postfach').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0013_postfach')]
    operations = [migrations.RunPython(uebernehmen, zurueck)]
