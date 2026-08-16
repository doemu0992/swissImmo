"""Etappe 5, PR 7 — Schritt 3 von 3: die Pflicht setzen. finance ist vollstaendig.

KEINE CheckConstraint auf den Alternativ-Wegen, anders als bei den leeren
portfolio-Tabellen. Dort war sie folgenlos zu setzen und verhinderte kuenftige
Waisen; hier stehen echte Daten, deren Kombinationen nicht vollstaendig bekannt
sind. Die Zusicherung, auf die es ankommt, ist ohnehin `organisation` selbst:
`null=False` plus die Ableitung im Modell. Eine zusaetzliche Bedingung haette
hier mehr Risiko als Nutzen — und Risiko auf einer Buchhaltungstabelle ist
etwas anderes als Risiko auf einer leeren Zaehlertabelle.
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
        ('finance', '0039_organisation_rest_befuellen'),
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
