# Etappe 4.3: Die Rollen wandern von den Django-Gruppen in die Mitgliedschaft.
#
# Bis hierher las `core/auth.py::hat_rolle()` `user.groups` — global. Eine
# Person, die für zwei Verwaltungen arbeitet, hatte damit überall dieselbe
# Rolle, und wer bei A „Verwaltung" war, war es bei B auch.
#
# DIE ZUORDNUNG, entschieden am 15.08.2026:
#
#   Verwaltung      → Verwalter
#   Sachbearbeitung → Sachbearbeiter
#   Lesend          → Lesezugriff
#   Eigentümer      → gar nicht: Portal-Rolle, keine Team-Rolle
#
# `Inhaber` ist NEU und hatte im Bestand keine Entsprechung. Er bekommt, was
# heute niemand hat: Abo und Rechnung, die Organisation löschen, Mitglieder
# einladen. Genau EINER wird gesetzt — der älteste Superuser, ersatzweise die
# älteste Verwalter-Mitgliedschaft.
#
# Der umgekehrte Weg (Verwaltung → Inhaber) wurde verworfen: Er hätte allen
# heutigen Verwaltungs-Konten stillschweigend Abo- und Löschrechte gegeben.
#
# RÜCKWÄRTS läuft die Zuordnung zurück. Der Inhaber wird dabei zu `Verwalter`
# — die Rolle, die er vorher hatte.
from django.db import migrations, models

VORWAERTS = {
    'Verwaltung': 'Verwalter',
    'Sachbearbeitung': 'Sachbearbeiter',
    'Lesend': 'Lesezugriff',
}
RUECKWAERTS = {neu: alt for alt, neu in VORWAERTS.items()}


def rollen_umstellen(apps, schema_editor):
    Mitgliedschaft = apps.get_model('crm', 'Mitgliedschaft')
    for alt, neu in VORWAERTS.items():
        Mitgliedschaft.objects.filter(rolle=alt).update(rolle=neu)

    # Genau einen Inhaber je Organisation. Ohne ihn hätte niemand die Rechte,
    # die es nur einmal geben soll — und beim ersten Bedarf würde jemand raten.
    for organisation_id in (Mitgliedschaft.objects
                            .values_list('organisation_id', flat=True).distinct()):
        vorhanden = Mitgliedschaft.objects.filter(
            organisation_id=organisation_id, rolle='Inhaber').exists()
        if vorhanden:
            continue
        kandidat = (Mitgliedschaft.objects
                    .filter(organisation_id=organisation_id, benutzer__is_superuser=True)
                    .order_by('pk').first()
                    or Mitgliedschaft.objects
                    .filter(organisation_id=organisation_id, rolle='Verwalter')
                    .order_by('pk').first())
        if kandidat is not None:
            kandidat.rolle = 'Inhaber'
            kandidat.save(update_fields=['rolle'])


def rollen_zurueck(apps, schema_editor):
    Mitgliedschaft = apps.get_model('crm', 'Mitgliedschaft')
    # Der Inhaber war vorher Verwalter — sonst entstünde beim Rückweg eine
    # Rolle, die es im alten Modell nicht gab.
    Mitgliedschaft.objects.filter(rolle='Inhaber').update(rolle='Verwaltung')
    for neu, alt in RUECKWAERTS.items():
        Mitgliedschaft.objects.filter(rolle=neu).update(rolle=alt)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0035_alter_mitgliedschaft_rolle'),
    ]

    operations = [
        migrations.RunPython(rollen_umstellen, rollen_zurueck),
    ]
