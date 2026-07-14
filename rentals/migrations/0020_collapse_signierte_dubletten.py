from django.db import migrations


def collapse(apps, schema_editor):
    """Einmalige Aufräumung bereits entstandener Ablage-Explosionen:
    je Vertrag alle signierten Dokumente auf das neueste reduzieren."""
    Dokument = apps.get_model('rentals', 'Dokument')
    from django.db.models import Count
    prefix = 'Mietvertrag (unterzeichnet)'
    vids = (Dokument.objects
            .filter(kategorie='vertrag', bezeichnung__startswith=prefix, vertrag__isnull=False)
            .values('vertrag').annotate(n=Count('id')).filter(n__gt=1)
            .values_list('vertrag', flat=True))
    for vid in list(vids):
        docs = list(Dokument.objects.filter(
            vertrag_id=vid, kategorie='vertrag',
            bezeichnung__startswith=prefix).order_by('-erstellt_am', '-id'))
        for d in docs[1:]:
            d.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0019_dokument_erstellt_am_mietvertrag_unterzeichnet_am'),
    ]

    operations = [
        migrations.RunPython(collapse, migrations.RunPython.noop),
    ]
