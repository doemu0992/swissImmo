"""Etappe 5, PR 1 — Schritt 3 von 3: die Pflicht setzen.

Erst hier wird aus „hat meistens eine Organisation" ein „hat immer eine".
Laeuft nur durch, wenn Schritt 2 vollstaendig war — bleibt eine Zeile ohne
Bezug, bricht die Datenbank die Aenderung ab. Das ist erwuenscht: Ein
stillschweigend uebersprungener Datensatz waere ein Datensatz ohne Mandant,
und der ist in einer mandantenfaehigen Anwendung fuer jeden sichtbar, der
irgendeine Organisation hat.

Der Anker `Liegenschaft.organisation` wechselt hier zugleich von `SET_NULL` auf
`CASCADE` — Begruendung im Modell.
"""
from django.db import migrations, models
import django.db.models.deletion

#: Bewusst wiederholt statt aus 0033 importiert: Ein Modulname, der mit einer
#: Ziffer beginnt, laesst sich nicht importieren — und eine Migration soll
#: ohnehin fuer sich lesbar sein und nicht von einer anderen abhaengen, die
#: spaeter jemand bearbeitet.
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
        ('portfolio', '0034_organisation_befuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='liegenschaft',
            name='organisation',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='liegenschaften',
                to='crm.organisation',
            ),
        ),
    ] + [
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
