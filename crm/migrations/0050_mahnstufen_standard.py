"""Standard-Mahnstufen für die bestehenden Organisationen.

Neue Organisationen bekommen sie beim Anlegen (`Organisation.save`, via
`core.services.mahnstufen.standard_mahnstufen_anlegen`). Diese Migration holt die
vorhandenen nach — mit den Werten, die bisher im Code standen (14/30/60 Tage,
Spesen 0/20/40, Art. 257d auf der dritten Stufe), damit sich für niemanden etwas
ändert. Die Werte stehen hier bewusst als Kopie: Eine Migration darf sich nicht
ändern, wenn der Startwert im Code später angepasst wird.
"""
from decimal import Decimal

from django.db import migrations

STANDARD = (
    (1, '1. Mahnung - Erste Zahlungserinnerung', 14, Decimal('0.00'), False),
    (2, '2. Mahnung - Zweite schriftliche Erinnerung', 30, Decimal('20.00'), False),
    (3, '3. Mahnung - Letzte Mahnung (Fristansetzung nach Art. 257d OR)', 60,
     Decimal('40.00'), True),
)


def anlegen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    MahnStufe = apps.get_model('crm', 'MahnStufe')
    for org in Organisation.objects.all():
        vorhanden = set(MahnStufe.objects.filter(organisation=org).values_list('stufe', flat=True))
        for stufe, bezeichnung, ab_tage, gebuehr, art_257d in STANDARD:
            if stufe not in vorhanden:
                MahnStufe.objects.create(organisation=org, stufe=stufe, bezeichnung=bezeichnung,
                                         ab_tage=ab_tage, gebuehr=gebuehr, art_257d=art_257d)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0049_mahnstufen'),
    ]

    operations = [
        migrations.RunPython(anlegen, migrations.RunPython.noop),
    ]
