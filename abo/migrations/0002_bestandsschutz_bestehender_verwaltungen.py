"""Jede bestehende Verwaltung bekommt ein Abonnement MIT Bestandsschutz.

Bis zu dieser Migration hatte jede Verwaltung jede Funktion und jede Menge,
unabhängig von `abo_plan` (nachgemessen: keine einzige Abfrage). Würde die
Funktionsfreigabe ohne Übergang einschalten, verlöre eine Verwaltung am
Tag des Einsatzes Funktionen, die sie gestern benutzt hat.

Darum:

* `uneingeschraenkt=True`: alle Funktionen offen, keine Mengengrenze, bis die
  Verwaltung (oder der Betreiber) bewusst einen Plan wählt.
* `zusatzmodule` = die drei zubuchbaren Module, die sie bisher nutzen konnte.
  Wählt die Verwaltung einen Plan, bleiben sie gebucht, bis der Betreiber sie
  zurücknimmt — es schliesst sich nichts hinter dem Rücken der Kundschaft.
* `abrechnung_ab` bleibt leer: Es wird nichts in Rechnung gestellt, bis der
  Betreiber den Beginn setzt. Was mit Bestandskunden geschieht, ist seine
  Entscheidung, nicht die dieser Migration.

Rückwärts werden die Zeilen entfernt (nur Abonnement-Zustand, keine Fachdaten).
"""
from django.db import migrations

# Die Schlüssel stehen bewusst hier und nicht als Import aus core.funktionen:
# Eine Migration beschreibt den Stand von damals, nicht den von heute.
MODULE_BISHER = ['signatur', 'belegerkennung', 'reporting_erweitert']


def vorwaerts(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Abonnement = apps.get_model('abo', 'Abonnement')
    for organisation in Organisation.objects.all():
        Abonnement.objects.get_or_create(
            organisation=organisation,
            defaults={'uneingeschraenkt': True, 'zusatzmodule': list(MODULE_BISHER)})


def rueckwaerts(apps, schema_editor):
    apps.get_model('abo', 'Abonnement').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('abo', '0001_abonnement_und_rechnung'),
    ]

    operations = [
        migrations.RunPython(vorwaerts, rueckwaerts),
    ]
