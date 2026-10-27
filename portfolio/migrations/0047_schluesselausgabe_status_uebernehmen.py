"""Status der bestehenden Schlüsselausgaben aus dem Rückgabedatum übernehmen.

Bis Modul 2 (27.10.2026) kannte eine Ausgabe nur «zurück am» oder nichts.
Ist das Datum gesetzt, gilt sie als «zurück», sonst als «ausgegeben». Einen
Verlust kannte der Bestand nicht; daraus wird hier nichts geraten.
"""
from django.db import migrations


def status_uebernehmen(apps, schema_editor):
    SchluesselAusgabe = apps.get_model('portfolio', 'SchluesselAusgabe')
    # Über den Basismanager: Eine Datenmigration läuft ohne Organisationskontext
    # und muss den ganzen Bestand aller Organisationen erreichen.
    SchluesselAusgabe._base_manager.filter(rueckgabe_am__isnull=False).update(status='zurueck')
    SchluesselAusgabe._base_manager.filter(rueckgabe_am__isnull=True).update(status='ausgegeben')


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0046_schliessanlage_und_schluesselausgabe"),
    ]

    operations = [
        migrations.RunPython(status_uebernehmen, migrations.RunPython.noop),
    ]
