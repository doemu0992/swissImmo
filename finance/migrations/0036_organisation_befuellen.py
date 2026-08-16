"""Etappe 5, PR 6 — Schritt 2 von 3: den Bestand versorgen.

Die Reihenfolge ist eine Abhaengigkeitskette und nicht bloss ordentlich:

    (Ausgangsorganisation)
      ├─ Buchungskonto ──┬─ Buchung, Bankbewegung, Kontoauszug
      ├─ LieferantProfil │
      └─ NebenkostenLernRegel
    Liegenschaft ─┬─ AbrechnungsPeriode ── NebenkostenBeleg
                  ├─ Anlage ── Abschreibung
                  ├─ Hypothek, Jahresabschluss, MietzinsKontrolle, Erneuerungsfonds
    Mietvertrag ──── ZahlerZuordnung

`Buchungskonto` MUSS vor `Buchung` laufen: ueber tausend Buchungen leiten ihren
Bezug aus dem Soll-Konto ab. Liefe der Kontenplan spaeter, erbte die gesamte
Buchhaltung seine Luecken.
"""
from django.db import migrations


#: Stammdaten ohne Weg — bekommen die Ausgangsorganisation (Rezept A).
STAMMDATEN = ['Buchungskonto', 'LieferantProfil', 'NebenkostenLernRegel']

#: Direkt an der Liegenschaft.
AN_LIEGENSCHAFT = ['AbrechnungsPeriode', 'Anlage', 'Hypothek', 'Jahresabschluss',
                   'MietzinsKontrolle', 'Erneuerungsfonds']

#: Am Buchungskonto — Feldname je Modell.
AN_KONTO = [('Buchung', 'soll_konto'), ('Bankbewegung', 'konto'), ('Kontoauszug', 'konto')]


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')
    Mietvertrag = apps.get_model('rentals', 'Mietvertrag')

    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        return                      # frische Datenbank, nichts zuzuordnen
    ausgangs_organisation = organisationen[0]

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, nicht je Zeile."""
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            ziel_modell.objects.filter(**{f'{feld}_id__in': traeger_ids}).update(
                organisation_id=organisation_id)

    # --- Stammdaten (Rezept A) --------------------------------------------
    for modellname in STAMMDATEN:
        modell = apps.get_model('finance', modellname)
        offen = modell.objects.filter(organisation__isnull=True)
        if offen.exists() and len(organisationen) > 1:
            raise RuntimeError(
                f'{modellname} ohne Organisation, aber es gibt mehr als eine. '
                f'Welche zustaendig ist, entscheidet diese Migration nicht.')
        offen.update(organisation=ausgangs_organisation)

    # --- von der Liegenschaft ---------------------------------------------
    for modellname in AN_LIEGENSCHAFT:
        uebertragen(Liegenschaft, apps.get_model('finance', modellname), 'liegenschaft')

    # --- eine Stufe weiter -------------------------------------------------
    uebertragen(apps.get_model('finance', 'Anlage'),
                apps.get_model('finance', 'Abschreibung'), 'anlage')
    uebertragen(apps.get_model('finance', 'AbrechnungsPeriode'),
                apps.get_model('finance', 'NebenkostenBeleg'), 'periode')
    uebertragen(Mietvertrag, apps.get_model('finance', 'ZahlerZuordnung'), 'vertrag')

    # --- vom Kontenplan (der jetzt traegt) --------------------------------
    Buchungskonto = apps.get_model('finance', 'Buchungskonto')
    for modellname, feld in AN_KONTO:
        uebertragen(Buchungskonto, apps.get_model('finance', modellname), feld)

    # --- Kontrolle ---------------------------------------------------------
    # Nennt das MODELL. Der Fehler, mit dem die Datenbank in Schritt 3 abbraeche,
    # nennt nur die Spalte — und bei fuenfzehn Modellen ist das der Unterschied
    # zwischen einer Minute und einer Stunde.
    for modellname in (STAMMDATEN + AN_LIEGENSCHAFT
                       + ['Abschreibung', 'NebenkostenBeleg', 'ZahlerZuordnung']
                       + [m for m, _f in AN_KONTO]):
        modell = apps.get_model('finance', modellname)
        offen = modell.objects.filter(organisation__isnull=True).count()
        if offen:
            raise RuntimeError(
                f'{offen} {modellname}-Datensatz/-saetze ohne Organisation. '
                f'Bitte pruefen, bevor die Spalte pflichtig wird.')


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0035_organisation_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
