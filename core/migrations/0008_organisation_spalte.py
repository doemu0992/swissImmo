"""Etappe 5, PR 9 — Schritt 1 von 3: die letzten Spalten in core.

`AktivitaetsLog` ist der Fall, den der Skill `phase-2-migration` ausdruecklich
als heikelsten nennt. Er hat genau EINEN Fremdschluessel — `benutzer` —, und der
fuehrt seit dem Entscheid vom 15.08.2026 bewusst nirgendwohin: `Benutzer` traegt
keinen Organisationsbezug, damit eine Person ueber `Mitgliedschaft` fuer mehrere
Verwaltungen arbeiten kann. Es gibt hier nichts abzuleiten.

Er waechst laufend und ist rechtlich relevant. 546 Zeilen heute — jede Woche
Warten macht die Datenmigration groesser, nicht kleiner.

`Pendenz` bekommt ein Tupel: Beide Wege sind optional, und das ist fachlich
richtig — eine allgemeine Aufgabe der Verwaltung haengt weder an einer
Liegenschaft noch an einem Vertrag.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0038_organisation_rest_pflicht'),
        ('rentals', '0034_organisation_pflicht'),
        ('crm', '0039_organisation_pflicht'),
        ('core', '0007_pendenz_frist_tage_pendenz_sendungsnummer_and_more'),
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
        for modell in ['aktivitaetslog', 'pendenz']
    ]
