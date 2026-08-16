"""Etappe 5, PR 9 — rentals abgeschlossen: das letzte Modell.

`Dokument` hat FUENF optionale Wege, und seit PR 8 tragen sie alle die
Organisation — `mieter` und `eigentuemer` haben sie dort selbst bekommen. Was
in der ersten Einordnung als schwerer Gruppe-B-Fall aussah, ist damit ein
gewoehnliches Tupel geworden.

Produktiv gemessen (16.08.2026): 7 Zeilen, 0 ohne Weg. Lokal 158, ebenfalls 0.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0039_organisation_pflicht'),
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0034_organisation_pflicht'),
    ]

    operations = [
        migrations.AddField(
            model_name='dokument',
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        ),
    ]
