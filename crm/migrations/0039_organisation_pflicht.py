"""Etappe 5, PR 8 — Schritt 3 von 3: die Pflicht setzen. crm ist damit fertig.

FUENF von sechs Modellen. `Vorlage` fehlt hier absichtlich: Ihre Spalte bleibt
nullbar, weil `NULL` dort eine Bedeutung hat (mitgelieferte Systemvorlage) und
kein fehlender Wert ist. Begruendung am Modell und in Schritt 1.
"""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = ['eigentuemer', 'handwerker', 'kommunikation', 'mieter', 'mieteradresse']


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0038_organisation_befuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in MODELLE
    ]
