from django.db import migrations


def seed(apps, schema_editor):
    Lebensdauer = apps.get_model('portfolio', 'Lebensdauer')
    from core.services.raumkatalog import STANDARD_LEBENSDAUER
    for kat, jahre in STANDARD_LEBENSDAUER.items():
        Lebensdauer.objects.get_or_create(
            kategorie=kat, defaults={'jahre': jahre, 'bemerkung': 'Standardwert (anpassbar)'})


def unseed(apps, schema_editor):
    # Standardwerte wieder entfernen (nur die geseedeten Bemerkungen)
    Lebensdauer = apps.get_model('portfolio', 'Lebensdauer')
    Lebensdauer.objects.filter(bemerkung='Standardwert (anpassbar)').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0018_lebensdauer_ausstattung'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
