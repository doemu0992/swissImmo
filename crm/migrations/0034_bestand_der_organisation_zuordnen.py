# Etappe 4.1: Der bestehende Bestand bekommt seine Organisation.
#
# Bis hierher gab es genau eine Verwaltung — als Singleton, per
# `Verwaltung.objects.first()` gelesen. Diese eine wird zur Ausgangsorganisation.
#
# ZWEI DINGE PASSIEREN HIER
# -------------------------
# 1. Liegenschaften ohne `organisation` bekommen die Ausgangsorganisation.
#    `organisation` ist heute `null=True` — jede Liegenschaft ohne Bezug wäre
#    ab Etappe 4.2 eine, die niemandem gehört und die folglich jeder sieht.
# 2. Jeder Benutzer mit einer TEAM-Rolle bekommt eine Mitgliedschaft mit
#    genau der Rolle, die er heute über seine Django-Gruppe hat.
#
# WER KEINE MITGLIEDSCHAFT BEKOMMT, UND WARUM
# -------------------------------------------
# - **Portal-Konten** (Mieter, Eigentümer). Sie hängen über `Mieter.benutzer`
#   und `Eigentuemer.benutzer` an ihren Datensätzen. `Eigentümer` ist eine
#   Portal-Rolle, keine Team-Rolle; das nicht vermischen.
# - **Konten ohne Team-Gruppe und ohne Portal-Profil.** Sie haben heute keinen
#   Team-Zugang, und diese Migration ist nicht der Ort, ihnen einen zu geben.
#   Ihnen hier eine Mitgliedschaft zu schenken wäre eine Rechteerweiterung,
#   die niemand beantragt hat.
#
# Superuser bekommen die Rolle `Verwaltung` — sie haben heute über
# `hat_rolle()` ohnehin alle Rechte (`if user.is_superuser: return True`), die
# Mitgliedschaft bildet das nur ab.
#
# RÜCKWÄRTS
# ---------
# Löscht die angelegten Mitgliedschaften und setzt `organisation` dort wieder
# auf NULL, wo diese Migration es gesetzt hat. Beides ist unterscheidbar, weil
# vorher nichts gesetzt war: Vor Etappe 4 hat keine einzige Liegenschaft einen
# `verwaltung`-Bezug getragen ausser den von Hand gepflegten — deshalb wird
# rückwärts NUR die Ausgangsorganisation entfernt, nicht jeder Bezug.
from django.conf import settings
from django.db import migrations

TEAM_ROLLEN = ('Verwaltung', 'Sachbearbeitung', 'Lesend')


def zuordnen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Mitgliedschaft = apps.get_model('crm', 'Mitgliedschaft')
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')
    Benutzer = apps.get_model(settings.AUTH_USER_MODEL)

    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        # Frische Datenbank (Testlauf, Neuinstallation): Es gibt noch keine
        # Verwaltung. Nichts zuzuordnen — die erste entsteht über das
        # Einrichten der Anwendung.
        return

    Liegenschaft.objects.filter(organisation__isnull=True).update(organisation=organisation)

    for benutzer in Benutzer.objects.all():
        rollen = set(benutzer.groups.values_list('name', flat=True)) & set(TEAM_ROLLEN)
        if benutzer.is_superuser:
            rolle = 'Verwaltung'
        elif rollen:
            # Bei mehreren die stärkste — die Reihenfolge in TEAM_ROLLEN ist
            # absteigend nach Rechten.
            rolle = next(r for r in TEAM_ROLLEN if r in rollen)
        else:
            continue
        Mitgliedschaft.objects.get_or_create(
            benutzer=benutzer, organisation=organisation, defaults={'rolle': rolle})


def zuruecknehmen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Mitgliedschaft = apps.get_model('crm', 'Mitgliedschaft')
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')

    organisation = Organisation.objects.order_by('pk').first()
    if organisation is None:
        return
    Mitgliedschaft.objects.filter(organisation=organisation).delete()
    Liegenschaft.objects.filter(organisation=organisation).update(organisation=None)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0033_mitgliedschaft'),
        # Das Feld muss schon `organisation` heissen, wenn diese Migration
        # darauf schreibt.
        ('portfolio', '0032_liegenschaft_organisation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(zuordnen, zuruecknehmen),
    ]
