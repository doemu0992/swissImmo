"""Aufträge im Hintergrund: anlegen, abarbeiten, Stand lesen.

DER ABLAUF
  1. `anlegen(art, parameter, benutzer)` legt den Auftrag an (Zustand «wartet») und kehrt sofort zurück.
  2. `manage.py auftraege_abarbeiten` holt den ältesten wartenden Auftrag (auf PostgreSQL mit `skip_locked`, damit zwei
     Läufer nie denselben nehmen), setzt ihn auf «läuft» und führt die Funktion der Art im Mandantenkontext seiner
     Organisation aus.
  3. Die Funktion bekommt `(auftrag, fortschritt)`; `fortschritt(prozent, text)` hält den Stand fest. Sie gibt den
     Ergebnistext zurück. Wirft sie, wird der Auftrag «fehlgeschlagen» mit kurzem Grund; der Lauf geht weiter.
  4. Ein Auftrag, der länger als `LAEUFT_HOECHSTENS_MINUTEN` «läuft», gilt als abgestürzt (Läufer beendet, Rechner
     neu gestartet): Er wartet erneut, höchstens `MAX_VERSUCHE` Mal, danach ist er fehlgeschlagen.

NEUE ART: Funktion mit `@auftragsart('schluessel', 'Bezeichnung')` in diesem Modul oder in einem Dienst eintragen, der
von `registrieren()` geladen wird. Die Funktion muss IDEMPOTENT sein: Ein Wiederanlauf nach einem Absturz darf nichts
doppelt buchen (Regeln in `docs/GELDPFADE.md`).
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Auftrag
from core.tenancy import organisation_kontext

logger = logging.getLogger(__name__)

#: Ab so vielen Minuten im Zustand «läuft» gilt ein Auftrag als abgestürzt.
LAEUFT_HOECHSTENS_MINUTEN = 30
#: So oft wird ein Auftrag höchstens gestartet (inklusive Wiederanläufe nach einem Absturz).
MAX_VERSUCHE = 3

#: Der Läufer meldet sich bei jedem Durchlauf im gemeinsamen Cache; so lange gilt die Meldung.
PULS_SCHLUESSEL = 'auftragslaeufer_puls'
PULS_SEKUNDEN = 180

#: Schlüssel → (Bezeichnung, Funktion). Gefüllt durch `@auftragsart`.
ARTEN = {}


class UnbekannteArt(KeyError):
    pass


def auftragsart(schluessel, bezeichnung):
    """Trägt eine Funktion `(auftrag, fortschritt) -> str` als Art ein."""
    def eintragen(funktion):
        ARTEN[schluessel] = (bezeichnung, funktion)
        return funktion
    return eintragen


def anlegen(art, parameter=None, benutzer=None, organisation=None):
    """Legt einen wartenden Auftrag für die aktuelle (oder angegebene) Organisation an."""
    from core.tenancy import aktuelle_organisation
    if art not in ARTEN:
        raise UnbekannteArt(art)
    organisation = organisation or aktuelle_organisation()
    if organisation is None:
        raise ValueError('Ein Auftrag braucht eine Organisation (Kontext oder Angabe).')
    return Auftrag.alle_organisationen.create(
        organisation=organisation, art=art, parameter=parameter or {}, erstellt_von=benutzer)


def puls_melden():
    """Der Läufer lebt (aufgerufen von `auftraege_abarbeiten` bei jedem Durchlauf)."""
    from django.core.cache import cache
    cache.set(PULS_SCHLUESSEL, timezone.now().isoformat(), PULS_SEKUNDEN)


def laeufer_aktiv():
    """Hat sich der Läufer in den letzten `PULS_SEKUNDEN` gemeldet?

    WOFÜR: Eine Arbeit darf nur dann in den Hintergrund, wenn sie dort auch jemand abholt. Ohne eingerichteten Läufer
    bliebe sie in der Warteschlange liegen, und die Verwaltung wartete auf eine Sollstellung, die nie kommt. Wer eine
    Arbeit wahlweise sofort oder im Hintergrund ausführt, fragt deshalb hier und läuft im Zweifel sofort."""
    from django.core.cache import cache
    try:
        return cache.get(PULS_SCHLUESSEL) is not None
    except Exception:                                        # noqa: BLE001 — im Zweifel: kein Läufer, also sofort
        return False


def bezeichnung(art):
    eintrag = ARTEN.get(art)
    return eintrag[0] if eintrag else art


def _abgestuerzte_wieder_einreihen(jetzt):
    """Aufträge, die zu lange «laufen», warten erneut — oder sind nach `MAX_VERSUCHE` fehlgeschlagen."""
    grenze = jetzt - timedelta(minutes=LAEUFT_HOECHSTENS_MINUTEN)
    for a in Auftrag.alle_organisationen.filter(zustand=Auftrag.ZUSTAND_LAEUFT, gestartet_am__lt=grenze):
        if a.versuche >= MAX_VERSUCHE:
            a.zustand, a.beendet_am = Auftrag.ZUSTAND_FEHLER, jetzt
            a.fehler = 'Abgestürzt: lief zu lange, keine Versuche mehr übrig.'
        else:
            a.zustand = Auftrag.ZUSTAND_WARTET
            a.fortschritt_text = 'Wiederanlauf nach Absturz'
        a.save(update_fields=['zustand', 'beendet_am', 'fehler', 'fortschritt_text'])


def _naechsten_holen(jetzt):
    """Der älteste wartende Auftrag, als «läuft» markiert — oder None. Zwei Läufer bekommen nie denselben."""
    with transaction.atomic():
        a = (Auftrag.alle_organisationen.select_for_update(skip_locked=True, of=('self',))
             .filter(zustand=Auftrag.ZUSTAND_WARTET).select_related('organisation')
             .order_by('erstellt_am', 'pk').first())
        if a is None:
            return None
        a.zustand, a.gestartet_am, a.versuche = Auftrag.ZUSTAND_LAEUFT, jetzt, a.versuche + 1
        a.save(update_fields=['zustand', 'gestartet_am', 'versuche'])
        return a


def _ausfuehren(auftrag):
    from core.funktionen import hintergrund_erlaubt

    def fortschritt(prozent, text=''):
        Auftrag.alle_organisationen.filter(pk=auftrag.pk).update(
            fortschritt=max(0, min(100, int(prozent))), fortschritt_text=str(text)[:200])

    def beenden(zustand, ergebnis='', fehler=''):
        Auftrag.alle_organisationen.filter(pk=auftrag.pk).update(
            zustand=zustand, ergebnis=ergebnis, fehler=fehler[:300], beendet_am=timezone.now(),
            fortschritt=100 if zustand == Auftrag.ZUSTAND_FERTIG else auftrag.fortschritt)

    eintrag = ARTEN.get(auftrag.art)
    if eintrag is None:
        return beenden(Auftrag.ZUSTAND_FEHLER, fehler=f'Unbekannte Art «{auftrag.art}».')
    with organisation_kontext(auftrag.organisation):
        if not hintergrund_erlaubt(auftrag.organisation):
            return beenden(Auftrag.ZUSTAND_FEHLER, fehler='Das Abonnement erlaubt keine Hintergrundarbeit (Lesemodus).')
        try:
            ergebnis = eintrag[1](auftrag, fortschritt)
        except Exception as e:                                # noqa: BLE001 — jeder Fehler endet im Auftrag, nicht im Läufer
            logger.exception('Auftrag %s (%s) fehlgeschlagen', auftrag.pk, auftrag.art)
            return beenden(Auftrag.ZUSTAND_FEHLER, fehler=f'{type(e).__name__}: {e}')
    beenden(Auftrag.ZUSTAND_FERTIG, ergebnis=str(ergebnis or ''))


def abarbeiten(grenze=20):
    """Arbeitet bis zu `grenze` wartende Aufträge ab. Gibt die Zahl der bearbeiteten zurück."""
    _abgestuerzte_wieder_einreihen(timezone.now())
    n = 0
    while n < grenze:
        auftrag = _naechsten_holen(timezone.now())
        if auftrag is None:
            break
        _ausfuehren(auftrag)
        n += 1
    return n


# ── Arten ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@auftragsart('sollstellung', _('Sollstellung (Mietenlauf)'))
def _sollstellung(auftrag, fortschritt):
    """Parameter: `jahr`, `monat`, optional `liegenschaft` (ID). Idempotent (die Sollstellung legt nichts doppelt an).

    Derselbe Ablauf wie der Knopf (`core.services.sollstellung_lauf.ausfuehren`): stellen, die Periode abschliessen
    (nur beim Lauf über das ganze Portfolio) und ins Logbuch schreiben."""
    from core.services import sollstellung_lauf
    from portfolio.models import Liegenschaft
    jahr, monat = int(auftrag.parameter['jahr']), int(auftrag.parameter['monat'])
    lg_id = auftrag.parameter.get('liegenschaft')
    liegenschaft = Liegenschaft.objects.filter(pk=lg_id).first() if lg_id else None
    if lg_id and liegenschaft is None:
        raise ValueError('Die Liegenschaft dieses Auftrags gibt es nicht mehr.')
    fortschritt(10, f'Sollstellung {monat:02d}/{jahr}')
    erstellt = sollstellung_lauf.ausfuehren(jahr, monat, benutzer=auftrag.erstellt_von, liegenschaft=liegenschaft,
                                            herkunft='Auftrag')
    return f'{erstellt} Rechnung(en) neu gestellt.'


@auftragsart('mahnlauf', _('Mahnlauf (Sammellauf)'))
def _mahnlauf(auftrag, fortschritt):
    """Parameter: `liegenschaft` (ID oder None), `send_email`, `mit_zins`, `erzwingen`. Idempotent je Mahnstufe.

    Derselbe Ablauf wie der Knopf (`core.services.mahnlauf_lauf.ausfuehren`)."""
    from core.services import mahnlauf_lauf
    from portfolio.models import Liegenschaft
    p = auftrag.parameter
    lg_id = p.get('liegenschaft')
    liegenschaft = Liegenschaft.objects.filter(pk=lg_id).first() if lg_id else None
    if lg_id and liegenschaft is None:
        raise ValueError('Die Liegenschaft dieses Auftrags gibt es nicht mehr.')
    fortschritt(10, 'Mahnlauf')
    res = mahnlauf_lauf.ausfuehren(
        liegenschaft=liegenschaft, send_email=bool(p.get('send_email', True)), mit_zins=bool(p.get('mit_zins')),
        erzwingen=bool(p.get('erzwingen')), benutzer=auftrag.erstellt_von, herkunft='Auftrag')
    return (f"{res['gemahnt']} Mahnung(en), {res['emails']} E-Mail(s), Gebühren CHF {res['gebuehren']}, "
            f"Zins CHF {res['zins']}.")
