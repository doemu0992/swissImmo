"""Etappe 5, PR 2 — Schritt 2 von 3: den Bestand versorgen.

Reihenfolge wie in PR 1: erst die Traeger, dann was von ihnen ableitet.
`Zaehler` muss vor `ZaehlerStand` stehen.

WAISEN
------
`Dokument`, `Geraet` und `Zaehler` koennen Datensaetze ohne jede Beziehung
haben — weder Einheit noch Liegenschaft. Die lassen sich nicht ableiten. Auf
der Produktion sind alle drei Tabellen leer (nachgezaehlt am 16.08.2026), der
Fall tritt dort also nicht ein. Diese Migration RAET trotzdem nicht, sondern
bricht ab: Ob eine Waise Datenmuell, Altlast einer einzigen Verwaltung oder ein
uebersehener Fachfall ist, entscheidet kein Skript.

Die Bedingung aus Schritt 3 verhindert danach, dass neue entstehen.
"""
from django.db import migrations


def befuellen(apps, schema_editor):
    Organisation = apps.get_model('crm', 'Organisation')
    Liegenschaft = apps.get_model('portfolio', 'Liegenschaft')
    Einheit = apps.get_model('portfolio', 'Einheit')

    organisationen = list(Organisation.objects.order_by('pk')[:2])
    if not organisationen:
        # FRISCHE DATENBANK — und trotzdem ist etwas zu tun.
        #
        # `0019_seed_lebensdauer` legt 69 Standardwerte an, bevor es irgendeine
        # Organisation gibt. Diese Zeilen gehoeren also niemandem. Bliebe es
        # dabei, scheiterte Schritt 3 mit
        #
        #     NOT NULL constraint failed: core_lebensdauer.organisation_id
        #
        # und zwar bei JEDER Neuinstallation — und bei jedem Aufbau der
        # Testdatenbank. Genau daran ist diese Migration beim ersten Lauf
        # aufgefallen.
        #
        # Sie werden geloescht, nicht zugeordnet: Es gibt niemanden, dem man sie
        # zuordnen koennte. `seed_lebensdauer()` (core/services/raumkatalog.py)
        # legt sie ohnehin idempotent neu an, sobald eine Verwaltung existiert —
        # dann mit Bezug. Verloren geht nichts, was nicht ein Aufruf
        # wiederherstellt.
        Lebensdauer = apps.get_model('portfolio', 'Lebensdauer')
        Lebensdauer.objects.filter(organisation__isnull=True).delete()
        return
    ausgangs_organisation = organisationen[0]

    def uebertragen(traeger, ziel_modell, feld):
        """Je Organisation EIN `UPDATE`, nicht je Zeile."""
        for organisation_id in (traeger.objects.values_list('organisation_id', flat=True)
                                .distinct()):
            traeger_ids = list(traeger.objects.filter(
                organisation_id=organisation_id).values_list('pk', flat=True))
            (ziel_modell.objects
             .filter(**{f'{feld}_id__in': traeger_ids, 'organisation__isnull': True})
             .update(organisation_id=organisation_id))

    # --- Entweder-oder: erst ueber die Einheit, dann ueber die Liegenschaft ---
    # Die Einheit zuerst, weil sie die genauere Angabe ist. Der zweite Durchgang
    # fasst dank `organisation__isnull=True` nur noch an, was uebrig blieb.
    for modellname in ('Dokument', 'Geraet', 'Zaehler'):
        modell = apps.get_model('portfolio', modellname)
        uebertragen(Einheit, modell, 'einheit')
        uebertragen(Liegenschaft, modell, 'liegenschaft')

        waisen = modell.objects.filter(organisation__isnull=True).count()
        if waisen:
            raise RuntimeError(
                f'{waisen} {modellname}-Datensatz/-saetze ohne Einheit UND ohne '
                f'Liegenschaft. Sie lassen sich nicht ableiten, und ob sie '
                f'Datenmuell, Altlast oder ein uebersehener Fachfall sind, '
                f'entscheidet keine Migration. Bitte pruefen und den Bezug von '
                f'Hand setzen, dann erneut starten.')

    # --- ZaehlerStand haengt pflichtig am Zaehler, der jetzt traegt -----------
    Zaehler = apps.get_model('portfolio', 'Zaehler')
    uebertragen(Zaehler, apps.get_model('portfolio', 'ZaehlerStand'), 'zaehler')

    # --- Lebensdauer: kein Weg, also die Ausgangsorganisation ----------------
    # Dieselbe Regel wie in crm/0034: die aelteste Organisation. Gibt es mehr
    # als eine, ist die Zuordnung eine fachliche Frage — dann Abbruch statt
    # Raten. Heute ist die Anwendung einmandantig; genau das aendert Phase 2.
    Lebensdauer = apps.get_model('portfolio', 'Lebensdauer')
    ohne_bezug = Lebensdauer.objects.filter(organisation__isnull=True)
    anzahl = ohne_bezug.count()
    if anzahl:
        if len(organisationen) > 1:
            raise RuntimeError(
                f'{anzahl} Lebensdauer-Eintraege ohne Organisation, aber es gibt '
                f'mehr als eine. Welche zustaendig ist, entscheidet diese '
                f'Migration nicht.')
        ohne_bezug.update(organisation=ausgangs_organisation)


def zurueck(apps, schema_editor):
    """Nichts zu tun — Schritt 1 entfernt die Spalten beim Rueckwaertslauf."""


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0036_organisation_rest_spalte'),
    ]

    operations = [
        migrations.RunPython(befuellen, zurueck),
    ]
