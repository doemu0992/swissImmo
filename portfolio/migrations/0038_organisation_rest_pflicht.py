"""Etappe 5, PR 2 — Schritt 3 von 3: Pflicht und Bedingungen setzen.

Drei Dinge auf einmal, weil sie zusammengehoeren:

1. `organisation` wird bei allen fuenf pflichtig.
2. `Dokument`, `Geraet`, `Zaehler` bekommen die Bedingung „Einheit ODER
   Liegenschaft gesetzt". Ohne sie entstuende weiterhin die Waise aus Rezept B —
   ein Datensatz, von dem kein Weg zur Organisation fuehrt. Die drei Tabellen
   sind produktiv leer, die Bedingung laesst sich also folgenlos setzen; ab dem
   ersten Datensatz waere es eine Datenbereinigung.
3. `Lebensdauer.kategorie` wird eindeutig JE ORGANISATION statt global. Global
   koennte Verwaltung B „Kueche" gar nicht anlegen, weil A sie schon hat.
"""
from django.db import migrations, models
import django.db.models.deletion


KETTENMODELLE = ['dokument', 'geraet', 'zaehler', 'zaehlerstand']

#: Nur die drei mit dem Entweder-oder — `ZaehlerStand` haengt pflichtig am
#: Zaehler und braucht keine Bedingung.
ENTWEDER_ODER = ['dokument', 'geraet', 'zaehler']


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0036_rollen_je_organisation'),
        ('portfolio', '0037_organisation_rest_befuellen'),
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
        for modell in KETTENMODELLE
    ] + [
        # Der Name steht hier AUFGELOEST (`portfolio_dokument_hat_bezug`), anders
        # als beim `related_name` oben. Django setzt `%(app_label)s`/`%(class)s`
        # in Constraint-Namen beim Laden des Modells ein und legt im
        # Migrationszustand bereits das Ergebnis ab — schriebe man hier das
        # Muster, meldete `makemigrations --check` dauerhaft eine Abweichung.
        migrations.AddConstraint(
            model_name=modell,
            constraint=models.CheckConstraint(
                condition=models.Q(('einheit__isnull', False)) | models.Q(('liegenschaft__isnull', False)),
                name=f'portfolio_{modell}_hat_bezug'),
        )
        for modell in ENTWEDER_ODER
    ] + [
        migrations.AlterField(
            model_name='lebensdauer',
            name='organisation',
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='lebensdauern',
                to='crm.organisation',
                verbose_name='Organisation',
            ),
        ),
        migrations.AddConstraint(
            model_name='lebensdauer',
            constraint=models.UniqueConstraint(
                fields=('organisation', 'kategorie'),
                name='uniq_lebensdauer_je_organisation'),
        ),
    ]
