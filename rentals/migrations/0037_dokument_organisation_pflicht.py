"""Etappe 5, PR 9 — Schritt 3: die Pflicht setzen. Etappe 5 ist damit fertig."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0036_dokument_organisation_befuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dokument',
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        ),
    ]
