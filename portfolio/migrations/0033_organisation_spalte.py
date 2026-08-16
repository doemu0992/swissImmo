"""Etappe 5, PR 1 — Schritt 1 von 3: die Spalte anlegen, noch ohne Pflicht.

Drei getrennte Migrationen, nie zusammengefasst. Bricht die Datenmigration
(Schritt 2) auf halber Strecke ab, muss der Zustand davor wiederherstellbar
sein — mit einer einzigen Migration waere er das nicht.

Hier entsteht nur die Spalte, bewusst `null=True`. Zu diesem Zeitpunkt ist sie
fuer jeden Bestandsdatensatz leer; erst Schritt 2 fuellt sie, erst Schritt 3
macht sie pflichtig.
"""
from django.db import migrations, models
import django.db.models.deletion


#: Die zwoelf Modelle mit geschlossener Pflicht-Kette zur Liegenschaft
#: (Gruppe C). Gemessen, nicht aus dem Plan uebernommen — der nannte fuer die
#: ganze Anwendung 34 Modelle in Gruppe C, gezaehlt sind es 32.
MODELLE = [
    'ausstattung',
    'einheit',
    'einheitfoto',
    'liegenschaftverteilschluessel',
    'schluessel',
    'schluesselausgabe',
    'sollmietzins',
    'staffelvorlage',
    'unterhalt',
    'versicherung',
    'verteilschluessel',
    'wartungsfrist',
]


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0032_liegenschaft_organisation'),
    ]

    operations = [
        migrations.AddField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                # Woertlich so, nicht aufgeloest: Django legt das Muster aus der
                # abstrakten Basis unveraendert im Migrationszustand ab und
                # setzt es erst beim Laden der Modelle ein. Steht hier
                # `portfolio_einheit`, meldet `makemigrations --check` ewig eine
                # Abweichung, die es gar nicht gibt.
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in MODELLE
    ]
