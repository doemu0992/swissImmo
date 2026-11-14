"""Die Sollstellung als EIN Ablauf — für den Knopf und für den Auftrag im Hintergrund.

Vorher stand das Nachspiel (Periode abschliessen, Logbuch) nur in der Ansicht. Ein Lauf im Hintergrund hätte gestellt,
aber die Periode offen gelassen und nichts protokolliert. Hier steht beides an einer Stelle.
"""
from django.conf import settings

#: Ab so vielen Verträgen geht der Lauf in den Hintergrund — falls ein Läufer aktiv ist (`auftraege.laeufer_aktiv`).
SCHWELLE_HINTERGRUND = 150


def schwelle():
    return getattr(settings, 'SOLLSTELLUNG_SCHWELLE_HINTERGRUND', SCHWELLE_HINTERGRUND)


def im_hintergrund(liegenschaft=None):
    """Soll dieser Lauf als Auftrag laufen? Nur bei vielen Verträgen UND aktivem Läufer; sonst sofort wie bisher."""
    from core.services import auftraege
    from rentals.models import Mietvertrag
    vertraege = Mietvertrag.objects.all()
    if liegenschaft is not None:
        vertraege = vertraege.filter(einheit__liegenschaft=liegenschaft)
    return vertraege.count() >= schwelle() and auftraege.laeufer_aktiv()


def ausfuehren(jahr, monat, benutzer=None, liegenschaft=None, herkunft='', request=None):
    """Stellt, schliesst die Periode ab (nur ganzes Portfolio) und schreibt ins Logbuch. Gibt die Zahl neuer Rechnungen.

    Wirft, was `run_sollstellung` wirft (`RuntimeError`, `SollstellungTeilfehler`): Der Aufrufer meldet es.
    Läuft im gesetzten Mandantenkontext. `request` (nur beim Knopf) gibt dem Logbuch die IP-Adresse."""
    from core.auth import log_aktion
    from core.services.automation import run_sollstellung
    erstellt = run_sollstellung(jahr, monat, user=benutzer, liegenschaft=liegenschaft)
    if liegenschaft is None:
        # Nur ein Lauf über das ganze Portfolio schliesst die Periode; ein Teillauf lässt sie offen.
        from faelle.lauf_dienst import lauf_erledigt
        lauf_erledigt('sollstellung', f'{jahr}-{monat:02d}', benutzer=benutzer, rechnungen=erstellt)
    log_aktion(request, 'Sollstellung ausgeführt', f'Miete & NK {monat:02d}/{jahr}',
               f'{erstellt} Rechnungen erstellt'
               + (f' · nur {liegenschaft.strasse}' if liegenschaft else ' · ganzes Portfolio')
               + (f' · {herkunft}' if herkunft else ''), user=benutzer)
    return erstellt
