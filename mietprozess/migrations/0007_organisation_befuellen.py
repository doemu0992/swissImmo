"""Etappe 5, PR 5 — Schritt 2 von 3: den Bestand aus der Einheit ableiten."""
from django.db import migrations


def befuellen(apps, schema_editor):
    Einheit = apps.get_model('portfolio', 'Einheit')
    Mietbewerbung = apps.get_model('mietprozess', 'Mietbewerbung')

    for organisation_id in Einheit.objects.values_list('organisation_id', flat=True).distinct():
        einheit_ids = list(Einheit.objects.filter(
            organisation_id=organisation_id).values_list('pk', flat=True))
        Mietbewerbung.objects.filter(einheit_id__in=einheit_ids).update(
            organisation_id=organisation_id)

    offen = Mietbewerbung.objects.filter(organisation__isnull=True).count()
    if offen:
        raise RuntimeError(
            f'{offen} Mietbewerbung(en) ohne Organisation, obwohl `einheit` '
            f'pflichtig ist. Bitte pruefen, bevor die Spalte pflichtig wird.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalte beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('mietprozess', '0006_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
