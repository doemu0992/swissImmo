"""Dienste zum Abonnement: Nutzung, Grenzen, Planwechsel, Rechnungslauf, Zahlungszustand.

Alles hier arbeitet mit einer ausdrücklich übergebenen Organisation (oder ihrer
ID) und greift auf Mandantendaten nur über `alle_organisationen` MIT Filter auf
diese Organisation zu — so läuft derselbe Code in der Anfrage, im Management-Command
und im Test, ohne vom gesetzten Kontext abzuhängen.

Es gibt keinen Zahlungsanbieter (ENTSCHEIDE-V7 D6): Die Rechnung geht per
QR-Rechnung hinaus, der Zahlungseingang wird von Hand bestätigt
(`als_bezahlt`).
"""
import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils.translation import gettext as _

from core import funktionen as f
from core.zeit import datum_heute

logger = logging.getLogger(__name__)

RAPPEN = Decimal('0.01')


class PreiseNichtFestgelegt(RuntimeError):
    """Der Betreiber hat Preise und MWST noch nicht festgelegt (ABO_PREISE_FESTGELEGT)."""


# ---------------------------------------------------------------------------
# Nutzung und Grenzen
# ---------------------------------------------------------------------------

def zaehle(organisation_id, was):
    """Wie viele Datensätze dieser Art die Verwaltung hat (alle, auch gesperrte Stufen)."""
    if was == 'einheiten':
        from portfolio.models import Einheit
        return Einheit.alle_organisationen.filter(organisation_id=organisation_id).count()
    if was == 'nutzer':
        from crm.models import Mitgliedschaft
        return Mitgliedschaft.alle_organisationen.filter(organisation_id=organisation_id).count()
    raise f.UnbekannteFunktion(f'{was!r} ist keine bekannte Mengengrenze.')


def pruefe_anlegen(organisation_id, was, anzahl=1):
    """Wirft `GrenzeErreicht`, wenn `anzahl` weitere Datensätze die Grenze sprengen.

    Prüft nur das ANLEGEN. Ohne Abonnement-Zeile und bei Bestandsschutz gibt es
    keine Grenze (`core.funktionen.anlege_grenze`).
    """
    if organisation_id is None:
        return
    from abo.models import Abonnement
    # Eine Abfrage für den häufigen Fall «nicht verwaltet / Bestandsschutz».
    abo = (Abonnement.alle_organisationen.select_related('organisation')
           .filter(organisation_id=organisation_id).first())
    if abo is None or abo.uneingeschraenkt:
        return
    grenze = f.anlege_grenze(abo.organisation, was)
    if grenze is None:
        return
    if zaehle(organisation_id, was) + anzahl > grenze:
        raise f.GrenzeErreicht(was, grenze)


def nutzung_von(organisation):
    """Der Nutzungszähler für die Abo-Seite: Bestand gegen Stufe und Anlegegrenze."""
    zeilen = []
    for was in ('einheiten', 'nutzer'):
        anzahl = zaehle(organisation.pk, was)
        stufe_grenze = f.grenze(organisation, was)
        anlegen_bis = f.anlege_grenze(organisation, was)
        massgeblich = anlegen_bis if anlegen_bis is not None else stufe_grenze
        zeilen.append({
            'was': was,
            'anzahl': anzahl,
            'grenze': stufe_grenze,
            'anlegen_bis': anlegen_bis,
            'prozent': min(100, int(anzahl * 100 / massgeblich)) if massgeblich else 0,
            # Bestand über der Grenze: bleibt les- und exportierbar, nur Neues geht nicht.
            'darueber': bool(anlegen_bis is not None and anzahl > anlegen_bis),
            'voll': bool(anlegen_bis is not None and anzahl >= anlegen_bis),
        })
    return zeilen


# ---------------------------------------------------------------------------
# Planwechsel
# ---------------------------------------------------------------------------

def folgen_des_wechsels(organisation, neue_stufe):
    """Was ein Wechsel auf `neue_stufe` schliesst — ohne etwas zu ändern.

    Rückgabe: `{'schliesst': [Schlüssel], 'bestand_ueber': Zahl oder 0}`. Daten
    bleiben in jedem Fall erhalten; Funktionen werden gesperrt, nie gelöscht.
    """
    abo = f.abonnement_von(organisation)
    zugebucht = set(abo.zusatzmodule or []) if abo is not None else set()
    schliesst = [k for k in f.FUNKTIONEN
                 if f.hat_funktion(organisation, k)
                 and k not in f.STUFEN[neue_stufe] and k not in zugebucht]
    deckel = f.PREISE[neue_stufe]['deckel']
    einheiten = zaehle(organisation.pk, 'einheiten')
    return {'schliesst': schliesst,
            'bestand_ueber': einheiten if deckel is not None and einheiten > deckel else 0,
            'deckel': deckel}


def plan_wechseln(organisation, stufe, jaehrlich):
    """Setzt Stufe und Intervall. Beendet den Bestandsschutz (aktive Planwahl).

    Der Wechsel gilt sofort für die Funktionen; abgerechnet wird ab der nächsten
    Periode (kein anteiliger Ausgleich — Fachpunkt im Bericht).
    """
    from abo.models import Abonnement
    if stufe not in f.STUFEN:
        raise ValueError(f'Unbekannte Stufe {stufe!r}.')
    with transaction.atomic():
        organisation.abo_plan = stufe
        organisation.abo_jaehrlich = bool(jaehrlich)
        organisation.save(update_fields=['abo_plan', 'abo_jaehrlich'])
        abo, _neu = Abonnement.alle_organisationen.get_or_create(
            organisation=organisation, defaults={'zusatzmodule': []})
        if abo.uneingeschraenkt:
            abo.uneingeschraenkt = False
            abo.save(update_fields=['uneingeschraenkt'])
        # Das geladene Objekt der Anfrage trägt die Zeile im Zwischenspeicher.
        organisation.abonnement = abo
    return abo


def abonnement_anlegen(organisation, uneingeschraenkt=False):
    """Legt die Abonnement-Zeile an (Onboarding). Neue Verwaltungen: ohne Bestandsschutz."""
    from abo.models import Abonnement
    abo, _neu = Abonnement.alle_organisationen.get_or_create(
        organisation=organisation,
        defaults={'zusatzmodule': [], 'uneingeschraenkt': uneingeschraenkt})
    return abo


# ---------------------------------------------------------------------------
# Rechnungsstellung
# ---------------------------------------------------------------------------

def intervall_von(organisation):
    return 'jaehrlich' if organisation.abo_jaehrlich else 'monatlich'


def naechste_periode(abo, organisation):
    """(von, bis) der nächsten unverrechneten Periode, oder None ohne Abrechnungsbeginn."""
    if abo.abrechnung_ab is None:
        return None
    von = abo.abgerechnet_bis + timedelta(days=1) if abo.abgerechnet_bis else abo.abrechnung_ab
    monate = 12 if organisation.abo_jaehrlich else 1
    return von, von + relativedelta(months=monate) - timedelta(days=1)


def betrag_fuer(stufe, einheiten, jaehrlich):
    """(netto, bemerkung) für eine Periode. Netto ohne MWST.

    Passt der Bestand nicht in die Stufe (Downgrade mit mehr Einheiten als der
    Deckel fasst), wird zum Preis des Deckels abgerechnet und das vermerkt:
    Weder wird der Bestand beschnitten noch stillschweigend mehr verlangt.
    """
    bemerkung = ''
    deckel = f.PREISE[stufe]['deckel']
    monat = f.monatspreis(stufe, einheiten)
    if monat is None:
        monat = f.monatspreis(stufe, deckel if deckel is not None else einheiten)
        bemerkung = _('Bestand von %(n)s Einheiten übersteigt die Stufe (höchstens %(d)s); '
                      'abgerechnet zum Preis der Stufe.') % {'n': einheiten, 'd': deckel}
    if jaehrlich:
        netto = monat * 12 * (1 - f.JAHRESRABATT)
    else:
        netto = monat
    return netto.quantize(RAPPEN, rounding=ROUND_HALF_UP), bemerkung


def rechnung_stellen(organisation, abo, heute=None, trotz_platzhalter=False):
    """Stellt die Rechnung der nächsten Periode aus. Gibt sie zurück oder `None`.

    Idempotent: Die Periode ist je Organisation eindeutig; ein zweiter Lauf am
    selben Tag stellt nichts nach. Pro Aufruf höchstens eine Periode.
    """
    from core.utils.qr_code import qrr_referenz
    from abo.models import AboRechnung

    heute = heute or datum_heute()
    periode = naechste_periode(abo, organisation)
    if periode is None or periode[0] > heute:
        return None
    if not settings.ABO_PREISE_FESTGELEGT and not trotz_platzhalter:
        raise PreiseNichtFestgelegt(
            'Preise und MWST sind noch nicht vom Betreiber festgelegt '
            '(settings.ABO_PREISE_FESTGELEGT). Rechnungen mit Platzhalterpreisen '
            'nur mit ausdrücklicher Freigabe.')
    von, bis = periode
    stufe = f.stufe_von(organisation)
    einheiten = zaehle(organisation.pk, 'einheiten')
    jaehrlich = bool(organisation.abo_jaehrlich)
    netto, bemerkung = betrag_fuer(stufe, einheiten, jaehrlich)

    satz = settings.ABO_MWST_SATZ
    satz = Decimal(str(satz)) if satz is not None else None
    mwst = (netto * satz / 100).quantize(RAPPEN, rounding=ROUND_HALF_UP) if satz else Decimal('0.00')

    with transaction.atomic():
        rechnung, neu = AboRechnung.alle_organisationen.get_or_create(
            organisation=organisation, periode_von=von,
            defaults=dict(
                periode_bis=bis, stufe=stufe, intervall=intervall_von(organisation), einheiten=einheiten,
                netto=netto, mwst_satz=satz, mwst_betrag=mwst, brutto=netto + mwst,
                rechnungsdatum=heute, faellig_am=heute + timedelta(days=settings.ABO_ZAHLUNGSFRIST_TAGE),
                platzhalter=not settings.ABO_PREISE_FESTGELEGT, bemerkung=bemerkung[:240]))
        if neu:
            rechnung.qr_referenz = qrr_referenz(organisation.pk, rechnung.pk)[0]
            rechnung.save(update_fields=['qr_referenz'])
        abo.abgerechnet_bis = bis
        abo.save(update_fields=['abgerechnet_bis'])
    return rechnung if neu else None


# ---------------------------------------------------------------------------
# Zahlungszustand
# ---------------------------------------------------------------------------

def zustand_fuer(ueberfaellig_seit, heute):
    """Der Zustand aus dem Fälligkeitstag der ältesten offenen Rechnung."""
    if ueberfaellig_seit is None:
        return f.ZUSTAND_AKTIV
    tage = (heute - ueberfaellig_seit).days
    if tage >= settings.ABO_LESEMODUS_NACH_TAGEN:
        return f.ZUSTAND_LESEMODUS
    if tage >= settings.ABO_MAHNUNG_NACH_TAGEN:
        return f.ZUSTAND_MAHNUNG
    return f.ZUSTAND_AKTIV


def zustand_aktualisieren(organisation, heute=None):
    """Führt den gespeicherten Zustand nach. Gibt `(alt, neu)` zurück.

    Es wird nie etwas gelöscht: Der Zustand ändert nur, was die Verwaltung tun
    darf. Mit dem Zahlungseingang (`als_bezahlt`) ist sie wieder `aktiv`.
    """
    from abo.models import AboRechnung
    abo = f.abonnement_von(organisation)
    if abo is None:
        return f.ZUSTAND_AKTIV, f.ZUSTAND_AKTIV
    heute = heute or datum_heute()
    aelteste = (AboRechnung.alle_organisationen
                .filter(organisation=organisation, status=AboRechnung.STATUS_OFFEN, faellig_am__lt=heute)
                .order_by('faellig_am').first())
    seit = aelteste.faellig_am if aelteste else None
    alt, neu = abo.zustand, zustand_fuer(seit, heute)
    if (alt, abo.ueberfaellig_seit) != (neu, seit):
        abo.zustand, abo.ueberfaellig_seit = neu, seit
        abo.save(update_fields=['zustand', 'ueberfaellig_seit'])
    return alt, neu


def als_bezahlt(rechnung, datum=None):
    """Bestätigt den Zahlungseingang (von Hand, ohne Anbieter) und öffnet die Verwaltung wieder."""
    from abo.models import AboRechnung
    rechnung.status = AboRechnung.STATUS_BEZAHLT
    rechnung.bezahlt_am = datum or datum_heute()
    rechnung.save(update_fields=['status', 'bezahlt_am'])
    return zustand_aktualisieren(rechnung.organisation, rechnung.bezahlt_am)


def stornieren(rechnung):
    from abo.models import AboRechnung
    rechnung.status = AboRechnung.STATUS_STORNIERT
    rechnung.save(update_fields=['status'])
    return zustand_aktualisieren(rechnung.organisation)


def erinnerung_senden(organisation, neu_zustand):
    """Zahlungserinnerung per E-Mail an die Verwaltung. Gibt True zurück, wenn versandt."""
    if not organisation.email:
        logger.warning('%s: keine E-Mail-Adresse, Erinnerung nicht versandt', organisation)
        return False
    absender = (settings.ABO_RECHNUNGSSTELLER.get('email') or settings.DEFAULT_FROM_EMAIL)
    if neu_zustand == f.ZUSTAND_LESEMODUS:
        betreff = _('immoswiss: Ihr Zugang ist schreibgeschützt')
        text = _('Die Rechnung für Ihr Abonnement ist seit mehr als %(tage)s Tagen überfällig. '
                 'Ihr Zugang ist deshalb schreibgeschützt: Sie können alle Daten weiter lesen und '
                 'exportieren, aber nichts mehr ändern, und es laufen keine automatischen Läufe mehr. '
                 'Mit dem Zahlungseingang ist alles wieder offen. Es wird nichts gelöscht.'
                 ) % {'tage': settings.ABO_LESEMODUS_NACH_TAGEN}
    else:
        betreff = _('immoswiss: Zahlungserinnerung zum Abonnement')
        text = _('Die Rechnung für Ihr Abonnement ist überfällig. Bitte begleichen Sie sie mit dem '
                 'QR-Einzahlungsschein, den Sie unter Einstellungen > Abonnement finden. Bleibt die '
                 'Zahlung länger aus, wird Ihr Zugang nach %(tage)s Tagen schreibgeschützt. '
                 'Ihre Daten bleiben in jedem Fall erhalten.'
                 ) % {'tage': settings.ABO_LESEMODUS_NACH_TAGEN}
    send_mail(betreff, text, absender, [organisation.email], fail_silently=False)
    return True


def abrechnen(organisation, heute=None, trotz_platzhalter=False, mail=True):
    """Der Lauf für EINE Verwaltung: Rechnung stellen, Zustand nachführen, erinnern.

    Aufgerufen je Organisation aus `manage.py abo_abrechnung` über
    `core.tenancy.je_organisation` (Fehlerisolation je Verwaltung).
    Rückgabe: Kurzbericht als Dict.
    """
    heute = heute or datum_heute()
    abo = f.abonnement_von(organisation)
    bericht = {'organisation': organisation.pk, 'rechnung': None, 'zustand': f.ZUSTAND_AKTIV, 'mail': False}
    if abo is None:
        return bericht
    try:
        rechnung = rechnung_stellen(organisation, abo, heute, trotz_platzhalter)
    except PreiseNichtFestgelegt:
        # Keine Rechnung mit Platzhalterpreisen. Der Zahlungszustand wird trotzdem
        # nachgeführt: Bereits gestellte Rechnungen laufen weiter ab.
        rechnung = None
        bericht['preise_offen'] = True
    bericht['rechnung'] = rechnung.nummer if rechnung else None
    alt, neu = zustand_aktualisieren(organisation, heute)
    bericht['zustand'] = neu
    if mail and neu != alt and neu != f.ZUSTAND_AKTIV:
        bericht['mail'] = erinnerung_senden(organisation, neu)
    return bericht
