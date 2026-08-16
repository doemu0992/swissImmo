"""Etappe 5, PR 4 — Schritt 3 von 3: die Pflicht setzen."""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = ['handwerkerauftrag', 'schadenfoto', 'schadenmeldung', 'ticketnachricht']


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('tickets', '0009_organisation_befuellen'),
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
