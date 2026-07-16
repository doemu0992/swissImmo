from django.db import migrations


# Titel der automatisch generierten Vertragspaket-Dokumente.
VERTRAGSPAKET_TITEL = ['Mietvertrag', 'Allgemeine Bedingungen', 'Hausordnung',
                       'Merkblatt Lüften', 'Wohnungsausweis', 'Begleitbrief Mietvertrag']


def cleanup_verwaiste(apps, schema_editor):
    """Entfernt verwaiste automatisch generierte Vertragspaket-Dokumente
    (vertrag=None, kategorie='vertrag') — sie entstanden, als frühere Verträge
    gelöscht wurden (SET_NULL liess die Kopien in der Akte zurück). Nur die
    Standard-Beilagen mit bekanntem Titel; sonstige Uploads bleiben unberührt."""
    Dokument = apps.get_model('rentals', 'Dokument')
    Dokument.objects.filter(
        vertrag__isnull=True, kategorie='vertrag',
        bezeichnung__in=VERTRAGSPAKET_TITEL,
    ).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0024_vertragmietzins_rabatt_netto_and_more'),
    ]

    operations = [
        migrations.RunPython(cleanup_verwaiste, noop),
    ]
