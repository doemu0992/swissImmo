"""Etappe 5, PR 5 — Schritt 3 von 3: die Pflicht setzen."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('mietprozess', '0007_organisation_befuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mietbewerbung',
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
