"""Der Sammel-Mahnlauf als EIN Ablauf — für den Knopf und für den Auftrag im Hintergrund.

Wie `sollstellung_lauf`: Das Nachspiel (Lauf der Periode abschliessen, Logbuch) stand nur in der Ansicht. Ein Lauf im
Hintergrund hätte gemahnt, den Monatslauf aber offen gelassen und nichts protokolliert.
"""
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

#: Ab so vielen offenen Rechnungen geht der Lauf in den Hintergrund — falls ein Läufer aktiv ist. Der Lauf verschickt
#: je Mahnung eine E-Mail; das ist der langsame Teil.
SCHWELLE_HINTERGRUND = 100


def schwelle():
    return getattr(settings, 'MAHNLAUF_SCHWELLE_HINTERGRUND', SCHWELLE_HINTERGRUND)


def im_hintergrund(liegenschaft=None):
    """Soll dieser Lauf als Auftrag laufen? Nur bei vielen offenen Rechnungen UND aktivem Läufer; sonst sofort."""
    from core.services import auftraege
    from finance.models import DebitorenRechnung
    offene = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'], stammrechnung__isnull=True)
    if liegenschaft is not None:
        offene = offene.filter(Q(liegenschaft=liegenschaft) | Q(vertrag__einheit__liegenschaft=liegenschaft))
    return offene.count() >= schwelle() and auftraege.laeufer_aktiv()


def ausfuehren(liegenschaft=None, send_email=True, mit_zins=False, erzwingen=False, benutzer=None, herkunft='',
               request=None):
    """Mahnt, schliesst den Monatslauf ab (nur regulärer Lauf über das ganze Portfolio) und schreibt ins Logbuch.

    Gibt das Ergebnis von `run_mahnlauf` zurück. Läuft im gesetzten Mandantenkontext. Ein erzwungener Lauf ist ein
    Zusatzlauf und schliesst den regulären Monatslauf nicht ab."""
    from core.auth import log_aktion
    from core.services.automation import run_mahnlauf
    res = run_mahnlauf(aktive_lg=liegenschaft, send_email=send_email, mit_zins=mit_zins, user=benutzer,
                       erzwingen=erzwingen)
    if liegenschaft is None and not erzwingen:
        from faelle.lauf_dienst import lauf_erledigt, periode_von
        lauf_erledigt('mahnlauf', periode_von(timezone.localdate()), benutzer=benutzer, auch_aeltere=True,
                      gemahnt=res['gemahnt'])
    log_aktion(request, 'Mahnlauf erzwungen' if erzwingen else 'Mahnlauf ausgeführt', 'Sammellauf',
               f"{res['gemahnt']} gemahnt, {res['emails']} E-Mails, Gebühren CHF {res['gebuehren']}, "
               f"Zins CHF {res['zins']}" + (f' · {herkunft}' if herkunft else ''), user=benutzer)
    return res
