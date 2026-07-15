from django.db import migrations


def sync_aktiv(apps, schema_editor):
    """aktiv an den Status angleichen: nur status='aktiv' ist aktiv=True.
    Behebt Alt-Daten, in denen Entwürfe (Default aktiv=True) oder gekündigte
    Verträge fälschlich als aktiv galten."""
    Mietvertrag = apps.get_model('rentals', 'Mietvertrag')
    Mietvertrag.objects.filter(aktiv=True).exclude(status='aktiv').update(aktiv=False)
    Mietvertrag.objects.filter(status='aktiv', aktiv=False).update(aktiv=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('rentals', '0021_collapse_vertragsbeilagen_dubletten'),
    ]
    operations = [
        migrations.RunPython(sync_aktiv, noop),
    ]
