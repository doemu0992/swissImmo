"""Etappe 5, PR 4 — Schritt 2 von 3: den Bestand ableiten.

Reihenfolge zwingend: `SchadenMeldung` zuerst, denn die anderen drei haengen an
ihr. Liefe sie spaeter, erbten Foto, Auftrag und Nachricht ihre Luecken.
"""
from django.db import migrations


def befuellen(apps, schema_editor):
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')
    SchadenMeldung = apps.get_model('tickets', 'SchadenMeldung')

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, nicht je Zeile."""
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            ziel_modell.objects.filter(**{f'{feld}_id__in': traeger_ids}).update(
                organisation_id=organisation_id)

    uebertragen(Liegenschaft, SchadenMeldung, 'liegenschaft')
    uebertragen(SchadenMeldung, apps.get_model('tickets', 'SchadenFoto'), 'schaden')
    for modellname in ('HandwerkerAuftrag', 'TicketNachricht'):
        uebertragen(SchadenMeldung, apps.get_model('tickets', modellname), 'ticket')

    # Nennt das Modell, nicht bloss die Spalte — anders als der Fehler, mit dem
    # die Datenbank in Schritt 3 abbraeche.
    for modellname in ('SchadenMeldung', 'SchadenFoto', 'HandwerkerAuftrag',
                       'TicketNachricht'):
        modell = apps.get_model('tickets', modellname)
        offen = modell.objects.filter(organisation__isnull=True).count()
        if offen:
            raise RuntimeError(
                f'{offen} {modellname}-Datensatz/-saetze ohne Organisation, obwohl '
                f'die Kette pflichtig ist. Bitte pruefen, bevor die Spalte '
                f'pflichtig wird.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0008_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
