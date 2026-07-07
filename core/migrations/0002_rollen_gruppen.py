# Daten-Migration: legt die vier Rollen-Gruppen des Bedienerkonzepts an
# (siehe core/auth.py) und weist alle bestehenden aktiven Benutzer der Rolle
# "Verwaltung" zu, damit beim Deployment niemand ausgesperrt wird.
from django.db import migrations

ROLLEN = ["Verwaltung", "Sachbearbeitung", "Lesend", "Eigentümer"]


def gruppen_anlegen(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('auth', 'User')

    gruppen = {}
    for name in ROLLEN:
        gruppen[name], _ = Group.objects.get_or_create(name=name)

    # Bestehende aktive Benutzer behalten vollen Zugriff (Rolle "Verwaltung").
    # Feinere Abstufung kann danach im Admin pro Benutzer gesetzt werden.
    verwaltung = gruppen["Verwaltung"]
    for user in User.objects.filter(is_active=True):
        user.groups.add(verwaltung)


def gruppen_entfernen(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=ROLLEN).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(gruppen_anlegen, gruppen_entfernen),
    ]
