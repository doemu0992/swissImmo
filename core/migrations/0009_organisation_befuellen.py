"""Etappe 5, PR 9 — Schritt 2 von 3: den Bestand versorgen.

`AktivitaetsLog` bekommt die Ausgangsorganisation — es gibt keinen anderen Weg,
das ist ja der Grund fuer die eigene Spalte. Chargenweise ueber `iterator`, wie
das Rezept es verlangt: Der Audit-Trail ist das groesste Modell im Bestand und
waechst weiter.

`Pendenz` leitet aus Vertrag und Liegenschaft ab; was uebrig bleibt (allgemeine
Aufgaben ohne Bezug), bekommt ebenfalls die Ausgangsorganisation.
"""
from django.db import migrations


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        return
    if len(organisationen) > 1:
        raise RuntimeError(
            'Mehr als eine Organisation. Welcher die Log-Eintraege und Pendenzen '
            'gehoeren, entscheidet keine Migration — der Audit-Trail schon gar nicht.')
    ausgangs_organisation = organisationen[0]

    AktivitaetsLog = apps.get_model('core', 'AktivitaetsLog')
    # Chargenweise: der Produktivbestand passt nicht zwingend in den Speicher,
    # und der Audit-Trail ist das Modell, das am schnellsten waechst.
    offen = AktivitaetsLog.objects.filter(organisation__isnull=True)
    while True:
        ids = list(offen.values_list('pk', flat=True)[:500])
        if not ids:
            break
        AktivitaetsLog.objects.filter(pk__in=ids).update(
            organisation=ausgangs_organisation)

    Pendenz = apps.get_model('core', 'Pendenz')

    def uebertragen(traeger, feld):
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            (Pendenz.objects
             .filter(**{f'{feld}_id__in': traeger_ids, 'organisation__isnull': True})
             .update(organisation_id=organisation_id))

    uebertragen(apps.get_model('rentals', 'Mietvertrag'), 'vertrag')
    uebertragen(apps.get_model('portfolio', 'Liegenschaft'), 'liegenschaft')
    Pendenz.objects.filter(organisation__isnull=True).update(
        organisation=ausgangs_organisation)

    for modellname in ('AktivitaetsLog', 'Pendenz'):
        modell = apps.get_model('core', modellname)
        rest = modell.objects.filter(organisation__isnull=True).count()
        if rest:
            raise RuntimeError(f'{rest} {modellname}-Datensatz/-saetze ohne Organisation.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
