"""Etappe 5, PR 9 — Schritt 2: den Dokumentenbestand versorgen."""
from django.db import migrations


#: Reihenfolge nach Genauigkeit — der Vertrag ist praeziser als die Liegenschaft.
WEGE = [
    ('rentals',   'Mietvertrag',  'vertrag'),
    ('portfolio', 'Einheit',      'einheit'),
    ('portfolio', 'Liegenschaft', 'liegenschaft'),
    ('crm',       'Mieter',       'mieter'),
    ('crm',       'Eigentuemer',  'eigentuemer'),
]


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        return
    Dokument = apps.get_model('rentals', 'Dokument')

    for app, name, feld in WEGE:
        traeger = apps.get_model(app, name)
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            (Dokument.objects
             .filter(**{f'{feld}_id__in': traeger_ids, 'organisation__isnull': True})
             .update(organisation_id=organisation_id))

    offen = Dokument.objects.filter(organisation__isnull=True)
    if offen.exists():
        if len(organisationen) > 1:
            raise RuntimeError(
                f'{offen.count()} Dokument(e) ohne ableitbaren Bezug, aber es gibt '
                f'mehr als eine Organisation.')
        offen.update(organisation=organisationen[0])


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalte beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0035_dokument_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
