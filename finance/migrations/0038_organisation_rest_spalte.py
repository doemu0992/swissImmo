"""Etappe 5, PR 7 — Schritt 1 von 3: Spalten fuer die letzten sieben Modelle.

Damit ist finance vollstaendig. Sechs leiten ihren Bezug aus einem Pfad-TUPEL
oder einer Pflicht-Kette ab, `EigentuemerAuszahlung` traegt eine eigene Spalte
(ihr Pflichtfeld `eigentuemer` bekommt seinen Bezug erst in PR 8).

WAISEN, am 16.08.2026 gegen die Produktion gemessen:

    Mahnung               1 / 0
    DebitorenRechnung     3 / 1   (Nr. 35, storniert — zuordnen, nicht loeschen)
    Zahlungseingang      14 / 14  (Bank-CSV UNGEKLAERT, alle mit konto=86)
    die uebrigen vier     leer

Die 14 sind kein Defekt, sondern ein regulaerer Arbeitszustand: Zahlungen aus
dem Bankabgleich, die nicht automatisch zugeordnet werden konnten. Sie leiten
ihren Bezug ueber `konto` ab — die Begruendung steht am Modell.
"""
from django.db import migrations, models
import django.db.models.deletion


MODELLE = [
    'debitorenrechnung', 'eigentuemerauszahlung', 'kreditorenrechnung',
    'kreditorenzahlung', 'kreditorposition', 'mahnung', 'zahlungseingang',
]


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('finance', '0037_organisation_pflicht'),
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
