from django.db import migrations


def collapse(apps, schema_editor):
    """Einmalige Aufräumung der explodierten Vertrags-Beilagen: je (Objekt, Titel)
    nur das neueste behalten (unterzeichneter Vertrag bleibt unberührt)."""
    Dokument = apps.get_model('rentals', 'Dokument')
    from django.db.models import Count
    SIGNIERT = 'Mietvertrag (unterzeichnet)'
    gruppen = (Dokument.objects
               .filter(kategorie='vertrag', einheit__isnull=False)
               .exclude(bezeichnung__startswith=SIGNIERT)
               .values('einheit', 'bezeichnung')
               .annotate(n=Count('id')).filter(n__gt=1))
    for g in list(gruppen):
        docs = list(Dokument.objects.filter(
            kategorie='vertrag', einheit_id=g['einheit'], bezeichnung=g['bezeichnung'])
            .exclude(bezeichnung__startswith=SIGNIERT)
            .order_by('-erstellt_am', '-id'))
        for d in docs[1:]:
            d.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0020_collapse_signierte_dubletten'),
    ]

    operations = [
        migrations.RunPython(collapse, migrations.RunPython.noop),
    ]
