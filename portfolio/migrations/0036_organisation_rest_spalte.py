"""Etappe 5, PR 2 — Schritt 1 von 3: Spalten fuer den Rest von portfolio.

PR 1 hat die zwoelf Modelle mit geschlossener Pflicht-Kette versorgt (Gruppe C).
Hier kommen die fuenf uebrigen:

  Gruppe B — `Dokument`, `Geraet`, `Zaehler` haengen an einer Einheit ODER an
  einer Liegenschaft, beide Fremdschluessel optional. `ZaehlerStand` haengt
  pflichtig am Zaehler und ist damit Gruppe C, sobald der Zaehler traegt.

  Gruppe A — `Lebensdauer` hat gar keinen Weg. Entscheidung im Modell
  begruendet: je Organisation, weil die Tabelle ueber die Oberflaeche
  bearbeitbar ist.

Auf der Produktion sind die vier Tabellen der Gruppe B am 16.08.2026 als LEER
nachgezaehlt worden — es gibt dort also keine Waisen vorzulegen, und Schritt 3
kann die Bedingung folgenlos setzen. `Lebensdauer` hat 69 Zeilen.
"""
from django.db import migrations, models
import django.db.models.deletion


KETTENMODELLE = ['dokument', 'geraet', 'zaehler', 'zaehlerstand']


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0035_organisation_pflicht'),
    ]

    operations = [
        migrations.AddField(
            model_name=modell,
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                # Woertlich das Muster, nicht aufgeloest — Django legt es aus der
                # abstrakten Basis unveraendert im Migrationszustand ab.
                related_name='%(app_label)s_%(class)s',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        )
        for modell in KETTENMODELLE
    ] + [
        migrations.AddField(
            model_name='lebensdauer',
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='lebensdauern',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        ),
        # Die globale Eindeutigkeit faellt hier, nicht erst in Schritt 3: Sonst
        # koennte die Datenmigration keine zweite Zeile mit derselben Kategorie
        # anlegen, und der spaetere Constraint je Organisation waere nicht
        # setzbar, solange der alte noch steht.
        migrations.AlterField(
            model_name='lebensdauer',
            name='kategorie',
            field=models.CharField(max_length=80),
        ),
    ]
