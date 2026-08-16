"""Etappe 5, PR 3 — Schritt 2 von 3: den Bestand aus der Kette ableiten.

Die Reihenfolge ist hier zwingend und nicht bloss ordentlich: `Mietvertrag`
bekommt seinen Bezug von der Einheit, und fuenf weitere Modelle bekommen ihn
vom Vertrag. Liefe der Vertrag nicht zuerst, erbten sie dessen Luecken.

    Einheit (traegt seit PR 1)
      └─ Mietvertrag ─┬─ Staffelstufe, VertragMietzins, MietzinsAnpassung,
                      │  Kuendigung
                      └─ Abnahmeprotokoll ── AbnahmeMangel
    Einheit ── Leerstand

Es gibt hier KEINE Waisen zu behandeln: Alle acht Ketten sind pflichtig, jeder
Datensatz hat also einen Weg. Was die Datenbank trotzdem nicht abdeckt, faengt
die Pruefung am Ende ab — eine Migration, die stillschweigend Zeilen ohne Bezug
zuruecklaesst, waere schlimmer als eine, die abbricht.
"""
from django.db import migrations


def befuellen(apps, schema_editor):
    Einheit = apps.get_model('portfolio', 'Einheit')
    Mietvertrag = apps.get_model('rentals', 'Mietvertrag')
    Abnahmeprotokoll = apps.get_model('rentals', 'Abnahmeprotokoll')

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, nicht je Zeile."""
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            ziel_modell.objects.filter(**{f'{feld}_id__in': traeger_ids}).update(
                organisation_id=organisation_id)

    # --- von der Einheit ---------------------------------------------------
    uebertragen(Einheit, Mietvertrag, 'einheit')
    uebertragen(Einheit, apps.get_model('rentals', 'Leerstand'), 'einheit')

    # --- vom Vertrag (der jetzt traegt) ------------------------------------
    for modellname in ('Staffelstufe', 'VertragMietzins', 'MietzinsAnpassung',
                       'Kuendigung', 'Abnahmeprotokoll'):
        uebertragen(Mietvertrag, apps.get_model('rentals', modellname), 'vertrag')

    # --- vom Protokoll (das jetzt traegt) ----------------------------------
    uebertragen(Abnahmeprotokoll, apps.get_model('rentals', 'AbnahmeMangel'), 'protokoll')

    # --- Kontrolle ---------------------------------------------------------
    # Erst Schritt 3 setzt die Pflicht, und die Datenbank wuerde dort abbrechen.
    # Diese Pruefung sagt aber, WELCHES Modell haengt — der Fehler der Datenbank
    # nennt nur die Spalte.
    for modellname in ('Mietvertrag', 'Leerstand', 'Staffelstufe', 'VertragMietzins',
                       'MietzinsAnpassung', 'Kuendigung', 'Abnahmeprotokoll',
                       'AbnahmeMangel'):
        modell = apps.get_model('rentals', modellname)
        offen = modell.objects.filter(organisation__isnull=True).count()
        if offen:
            raise RuntimeError(
                f'{offen} {modellname}-Datensatz/-saetze ohne Organisation, obwohl '
                f'die Kette pflichtig ist. Das deutet auf eine unterbrochene '
                f'Beziehung im Bestand hin — bitte pruefen, bevor die Spalte '
                f'pflichtig wird.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('rentals', '0032_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
