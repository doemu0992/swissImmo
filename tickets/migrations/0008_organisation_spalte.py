"""Etappe 5, PR 4 — Schritt 1 von 3: Spalten fuer tickets.

Vier Modelle, alle Gruppe C und alle mit einglied­rigem Pfad, weil die Traeger
ihre Organisation bereits selbst haben:

    SchadenMeldung                     → liegenschaft   (seit PR 1)
    SchadenFoto                        → schaden
    HandwerkerAuftrag, TicketNachricht → ticket

Nachgemessen, nicht aus dem Plan uebernommen: In tickets gibt es weder Gruppe B
noch A. Die drei optionalen Fremdschluessel (`betroffene_einheit`,
`gemeldet_von`, `ausstattung` an `SchadenMeldung`) spielen fuer den Bezug keine
Rolle — `liegenschaft` ist pflichtig und traegt allein.
"""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = ['handwerkerauftrag', 'schadenfoto', 'schadenmeldung', 'ticketnachricht']


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('tickets', '0007_schadenmeldung_ausstattung'),
    ]

    operations = [
        migrations.AddField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in MODELLE
    ]
