"""Bestandsschutz für Abnahmeprotokolle aus dem klassischen Formular.

Bis zum Production-Check (26.10.2026) galt ein Protokoll ohne Bauteile (das
klassische Formular) als «Abnahme erfolgt», auch ohne Abschluss — dort war
«abgeschlossen» ein Häkchen, das oft fehlte. Seither zählt nur der Abschluss
mit Unterschriften (`core/services/abnahme_vorgaenger.durchgefuehrt`).

Für den Bestand bleibt die alte Bedeutung: Alle offenen Protokolle ohne
Bauteile, die bis heute angelegt waren, werden als durchgeführt übernommen.
Ohne das würde für Mieter, die längst zurückgegeben haben, wieder
Nutzungsentschädigung fällig, und erledigte Auto-Pendenzen lebten auf.
"""
from django.db import migrations, models


def altbestand_markieren(apps, schema_editor):
    Abnahmeprotokoll = apps.get_model('rentals', 'Abnahmeprotokoll')
    # Über den Basismanager: eine Datenmigration läuft ohne Organisationskontext
    # und muss den ganzen Bestand aller Organisationen erreichen.
    (Abnahmeprotokoll._base_manager
     .filter(abgeschlossen=False, positionen__isnull=True)
     .update(altbestand_durchgefuehrt=True))


class Migration(migrations.Migration):

    dependencies = [
        ("rentals", "0046_abnahme_produktionsreife"),
    ]

    operations = [
        migrations.AddField(
            model_name="abnahmeprotokoll",
            name="altbestand_durchgefuehrt",
            field=models.BooleanField(default=False, editable=False,
                                      verbose_name="Altbestand: als durchgeführt übernommen"),
        ),
        migrations.RunPython(altbestand_markieren, migrations.RunPython.noop),
    ]
