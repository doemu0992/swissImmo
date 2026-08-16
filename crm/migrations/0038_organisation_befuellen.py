"""Etappe 5, PR 8 — Schritt 2 von 3: den Bestand versorgen.

Reihenfolge: `Mieter` vor `MieterAdresse`, sonst erbt die Adresse eine Luecke.

`Vorlage` wird ABSICHTLICH NICHT angefasst. Der Bestand besteht aus den
mitgelieferten Systemvorlagen, und die bleiben bei `NULL` — genau dafuer ist die
Spalte nullbar. Wuerde diese Migration sie der Ausgangsorganisation zuordnen,
waeren sie fuer jede kuenftige Verwaltung unsichtbar, und der Sinn der Ausnahme
waere beim ersten Lauf verspielt.
"""
from django.db import migrations


#: Stammdaten ohne Weg — bekommen die Ausgangsorganisation.
OHNE_WEG = ['Eigentuemer', 'Mieter', 'Handwerker']


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        return                      # frische Datenbank, nichts zuzuordnen
    ausgangs_organisation = organisationen[0]

    if len(organisationen) > 1:
        raise RuntimeError(
            'Mehr als eine Organisation. Welcher die Stammdaten (Eigentuemer, '
            'Mieter, Handwerker) gehoeren, entscheidet keine Migration.')

    for modellname in OHNE_WEG:
        modell = apps.get_model('crm', modellname)
        modell.objects.filter(organisation__isnull=True).update(
            organisation=ausgangs_organisation)

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, nur auf noch leere Zeilen."""
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            (ziel_modell.objects
             .filter(**{f'{feld}_id__in': traeger_ids, 'organisation__isnull': True})
             .update(organisation_id=organisation_id))

    # --- vom Mieter (der jetzt traegt) ------------------------------------
    Mieter = apps.get_model('crm', 'Mieter')
    uebertragen(Mieter, apps.get_model('crm', 'MieterAdresse'), 'mieter')

    # --- Kommunikation: drei Wege, dann der Rest --------------------------
    Kommunikation = apps.get_model('crm', 'Kommunikation')
    uebertragen(Mieter, Kommunikation, 'mieter')
    uebertragen(apps.get_model('rentals', 'Mietvertrag'), Kommunikation, 'vertrag')
    uebertragen(apps.get_model('portfolio', 'Liegenschaft'), Kommunikation, 'liegenschaft')
    Kommunikation.objects.filter(organisation__isnull=True).update(
        organisation=ausgangs_organisation)

    # --- Kontrolle (Vorlage bewusst ausgenommen) --------------------------
    for modellname in OHNE_WEG + ['MieterAdresse', 'Kommunikation']:
        modell = apps.get_model('crm', modellname)
        offen = modell.objects.filter(organisation__isnull=True).count()
        if offen:
            raise RuntimeError(
                f'{offen} {modellname}-Datensatz/-saetze ohne Organisation. '
                f'Bitte pruefen, bevor die Spalte pflichtig wird.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0037_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
