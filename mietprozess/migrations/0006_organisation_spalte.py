"""Etappe 5, PR 5 — Schritt 1 von 3: Spalte fuer mietprozess.

Ein einziges Modell. `Mietbewerbung.einheit` ist pflichtig, und `Einheit` traegt
die Organisation seit PR 1 — der Pfad ist einglied­rig.

Bemerkenswert ist hier weniger die Migration als das, woran sie haengt: Die
Mietbewerbung entsteht ueber ein OEFFENTLICHES Formular (`/bewerben/<id>/`),
also ohne angemeldeten Benutzer und damit ohne Mandantenkontext. Der Bezug
kommt trotzdem zustande, weil er aus der Einheit abgeleitet wird und nicht aus
dem Kontext. Haette man ihn als Kontextfeld gebaut, waere ausgerechnet der
oeffentliche Weg der einzige, auf dem er fehlt.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('mietprozess', '0005_zivilstand_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='mietbewerbung',
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
