"""Dienste zum Abonnement: Nutzung, Grenzen, Planwechsel, Rechnungslauf, Zahlungszustand.

Alles hier arbeitet mit einer ausdrücklich übergebenen Organisation (oder ihrer
ID) und greift auf Mandantendaten nur über `alle_organisationen` MIT Filter auf
diese Organisation zu — so läuft derselbe Code in der Anfrage, im Management-Command
und im Test, ohne vom gesetzten Kontext abzuhängen.

Es gibt keinen Zahlungsanbieter (ENTSCHEIDE-V7 D6): Die Rechnung geht per
QR-Rechnung hinaus, der Zahlungseingang wird von Hand bestätigt
(`als_bezahlt`).
"""
import calendar
import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils.translation import gettext as _

from core import funktionen as f
from core.zeit import datum_heute

logger = logging.getLogger(__name__)

RAPPEN = Decimal('0.01')


class RechnungNichtSendbar(ValueError):
    """Die Rechnung lässt sich nicht verschicken (keine Adresse, keine Zahlungsverbindung). Der Text ist für den Betreiber."""


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
    # Module, die bisher im Grundpreis steckten und in der neuen Stufe zugebucht werden müssten.
    alt = f.stufe_von(organisation)
    schliesst += [k for k in f.MODULE
                  if k not in zugebucht and f.modul_inklusive(alt, k) and not f.modul_inklusive(neue_stufe, k)
                  and not (abo is not None and abo.uneingeschraenkt)]
    deckel = f.PREISE[neue_stufe]['deckel']
    einheiten = zaehle(organisation.pk, 'einheiten')
    return {'schliesst': schliesst,
            'bestand_ueber': einheiten if deckel is not None and einheiten > deckel else 0,
            'deckel': deckel}


def _zustand_des_abos(organisation, abo):
    """Was die Rechnung bestimmt: Stufe, Intervall, zugebuchte Module (für den Vergleich vor/nach einer Änderung)."""
    return {'stufe': f.stufe_von(organisation), 'jaehrlich': bool(organisation.abo_jaehrlich),
            'module': tuple(abo.zusatzmodule or ()) if abo is not None else ()}


def plan_wechseln(organisation, stufe, jaehrlich, heute=None):
    """Setzt Stufe und Intervall. Beendet den Bestandsschutz (aktive Planwahl).

    Der Wechsel gilt sofort für die Funktionen. Mitten in einer bereits gestellten Periode wird der Unterschied anteilig
    verrechnet (`aenderung_verrechnen`): Aufwertung als Zusatzrechnung, Abwertung als Gutschrift für die nächste Rechnung.
    """
    from abo.models import Abonnement
    if stufe not in f.STUFEN:
        raise ValueError(f'Unbekannte Stufe {stufe!r}.')
    with transaction.atomic():
        abo_vorher = Abonnement.alle_organisationen.filter(organisation=organisation).first()
        vorher = _zustand_des_abos(organisation, abo_vorher)
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
        aenderung_verrechnen(organisation, abo, vorher, _zustand_des_abos(organisation, abo), heute)
    return abo


def module_setzen(organisation, abo, module, heute=None):
    """Setzt die zugebuchten Module; mitten in der Periode wird der Unterschied anteilig verrechnet."""
    with transaction.atomic():
        vorher = _zustand_des_abos(organisation, abo)
        abo.zusatzmodule = list(module)
        abo.save(update_fields=['zusatzmodule'])
        aenderung_verrechnen(organisation, abo, vorher, _zustand_des_abos(organisation, abo), heute)


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


def _plus_monate(tag, monate):
    """`tag` plus ganze Monate; der Tag wird auf das Monatsende geklemmt (31.01. + 1 Monat = 28./29.02.)."""
    gesamt = tag.year * 12 + (tag.month - 1) + monate
    jahr, monat = divmod(gesamt, 12)
    monat += 1
    return tag.replace(year=jahr, month=monat, day=min(tag.day, calendar.monthrange(jahr, monat)[1]))


def _monatsende(tag):
    return tag.replace(day=calendar.monthrange(tag.year, tag.month)[1])


def naechste_periode(abo, organisation):
    """(von, bis) der nächsten unverrechneten Periode, oder None ohne Abrechnungsbeginn.

    Monatlich: Kalendermonate. Die erste Periode (und eine nach Bestandsdaten angebrochene) reicht vom Beginn bis zum
    Monatsende und wird anteilig verrechnet; danach gilt jeweils der 1. bis Monatsende. Jährlich: ein Jahr ab Beginn.
    """
    if abo.abrechnung_ab is None:
        return None
    von = abo.abgerechnet_bis + timedelta(days=1) if abo.abgerechnet_bis else abo.abrechnung_ab
    if organisation.abo_jaehrlich:
        return von, _plus_monate(von, 12) - timedelta(days=1)
    return von, _monatsende(von)


def anteil_der_periode(von, bis, jaehrlich):
    """(tage, gesamt): Tage der Periode und Tage einer vollen Periode (Kalendermonat, bei jährlich die Periode selbst)."""
    tage = (bis - von).days + 1
    gesamt = tage if jaehrlich else calendar.monthrange(von.year, von.month)[1]
    return tage, gesamt


def _anteilig(netto, positionen, tage, gesamt):
    """Skaliert Netto und Positionen auf `tage` von `gesamt`; die Summe der Zeilen bleibt gleich dem Netto."""
    if tage >= gesamt:
        return netto, positionen
    faktor = Decimal(tage) / Decimal(gesamt)
    zeilen = [{'text': p['text'], 'betrag': (Decimal(p['betrag']) * faktor).quantize(RAPPEN, rounding=ROUND_HALF_UP)}
              for p in positionen]
    neues_netto = (netto * faktor).quantize(RAPPEN, rounding=ROUND_HALF_UP)
    zeilen[0]['betrag'] += neues_netto - sum((z['betrag'] for z in zeilen), Decimal('0'))
    from django.utils import translation
    with translation.override('de'):
        zeilen[0]['text'] += ', ' + _('anteilig %(t)s von %(g)s Tagen') % {'t': tage, 'g': gesamt}
    return neues_netto, [{'text': z['text'], 'betrag': str(z['betrag'])} for z in zeilen]


def positionen_fuer(stufe, einheiten, jaehrlich, module=()):
    """(netto, bemerkung, positionen) für eine Periode. Netto ohne MWST.

    `positionen` sind die Zeilen der Rechnung als `[{'text', 'betrag'}]` (Texte deutsch, wie die Rechnung): der Grundpreis der
    Stufe, je zugebuchtes Modul eine Zeile (ausser es steckt im Grundpreis der Stufe), bei jährlicher Abrechnung der Rabatt.
    Die Summe der Beträge ist das Netto. Gespeichert wird das mit der Rechnung: Eine spätere Preisänderung ändert sie nicht.

    Passt der Bestand nicht in die Stufe (Downgrade mit mehr Einheiten als der
    Deckel fasst), wird zum Preis des Deckels abgerechnet und das vermerkt:
    Weder wird der Bestand beschnitten noch stillschweigend mehr verlangt.
    """
    from django.utils import translation
    bemerkung = ''
    deckel = f.PREISE[stufe]['deckel']
    monat = f.monatspreis(stufe, einheiten)
    if monat is None:
        monat = f.monatspreis(stufe, deckel if deckel is not None else einheiten)
        bemerkung = _('Bestand von %(n)s Einheiten übersteigt die Stufe (höchstens %(d)s); '
                      'abgerechnet zum Preis der Stufe.') % {'n': einheiten, 'd': deckel}
    faktor = 12 if jaehrlich else 1
    with translation.override('de'):
        zeilen = [(_('Abonnement %(stufe)s, %(intervall)s') % {
            'stufe': f.STUFEN_NAMEN[stufe], 'intervall': _('jährlich') if jaehrlich else _('monatlich')}, monat * faktor)]
        for schluessel in f.MODULE:
            if schluessel in (module or ()) and schluessel in f.MODULPREISE:
                preis = f.modul_monatspreis(stufe, schluessel)
                if preis > 0:
                    zeilen.append((str(f.MODULE[schluessel]), preis * faktor))
        summe = sum((b for _t, b in zeilen), Decimal('0'))
        if jaehrlich:
            netto = (summe * (1 - f.JAHRESRABATT)).quantize(RAPPEN, rounding=ROUND_HALF_UP)
            zeilen.append((_('Jahresrabatt %(p)s %%') % {'p': int(f.JAHRESRABATT * 100)}, netto - summe))
        else:
            netto = summe.quantize(RAPPEN, rounding=ROUND_HALF_UP)
    positionen = [{'text': text, 'betrag': str(betrag.quantize(RAPPEN, rounding=ROUND_HALF_UP))} for text, betrag in zeilen]
    return netto, bemerkung[:240], positionen


def betrag_fuer(stufe, einheiten, jaehrlich, module=()):
    """(netto, bemerkung) für eine Periode, mit den zugebuchten Modulen. Netto ohne MWST."""
    netto, bemerkung, _positionen = positionen_fuer(stufe, einheiten, jaehrlich, module)
    return netto, bemerkung


def guthaben_von(organisation):
    """Noch nicht verrechnetes Guthaben (Gutschriften aus Abwertungen) einer Organisation in CHF."""
    from abo.models import AboGutschrift
    return sum((g.offen for g in AboGutschrift.alle_organisationen.filter(organisation=organisation)), Decimal('0'))


def _gutschriften_abziehen(organisation, netto):
    """Welche offenen Gutschriften diese Rechnung mindern: `[{'gutschrift', 'betrag', 'text'}]`, ohne etwas zu speichern."""
    from django.utils import translation

    from abo.models import AboGutschrift
    rest = netto
    abzuege = []
    for gutschrift in AboGutschrift.alle_organisationen.filter(organisation=organisation).order_by('datum', 'pk'):
        nehmen = min(gutschrift.offen, rest)
        if nehmen <= 0:
            continue
        with translation.override('de'):
            text = _('Gutschrift vom %(d)s: %(t)s') % {'d': gutschrift.datum.strftime('%d.%m.%Y'), 't': gutschrift.text}
        abzuege.append({'gutschrift': gutschrift, 'betrag': nehmen, 'text': text[:240]})
        rest -= nehmen
    return abzuege


def _beschreibung_der_aenderung(vorher, nachher, ab):
    """Deutscher Text der Änderung für die Rechnungszeile, z. B. «Team → Professional, Modul Unterschrift hinzu»."""
    from django.utils import translation
    teile = []
    with translation.override('de'):
        if vorher['stufe'] != nachher['stufe']:
            teile.append(f"{f.STUFEN_NAMEN[vorher['stufe']]} → {f.STUFEN_NAMEN[nachher['stufe']]}")
        for k in f.MODULE:
            if k in nachher['module'] and k not in vorher['module']:
                teile.append(_('Modul %(m)s hinzu') % {'m': f.MODULE[k]})
            elif k in vorher['module'] and k not in nachher['module']:
                teile.append(_('Modul %(m)s entfällt') % {'m': f.MODULE[k]})
        kopf = _('Änderung des Abonnements ab %(d)s') % {'d': ab.strftime('%d.%m.%Y')}
    return f"{kopf}: {', '.join(teile) or '-'}"


def aenderung_verrechnen(organisation, abo, vorher, nachher, heute=None, mail=True):
    """Verrechnet den Preisunterschied einer Änderung mitten in der laufenden Periode anteilig (ab heute bis Periodenende).

    Mehr als vorher → Zusatzrechnung (sofort, mit Versand). Weniger → Gutschrift, die die nächste Abo-Rechnung mindert.
    Nichts geschieht, wenn keine Periode läuft (noch nicht abgerechnet, Bestandsschutz), das Intervall wechselt (gilt ab
    der nächsten Periode) oder der Unterschied null ist. Gibt die Zusatzrechnung, die Gutschrift oder `None` zurück.
    """
    from core.utils.qr_code import qrr_referenz
    from abo.models import AboGutschrift, AboRechnung

    heute = heute or datum_heute()
    if vorher['jaehrlich'] != nachher['jaehrlich'] or (vorher['stufe'], vorher['module']) == (nachher['stufe'], nachher['module']):
        return None
    if not settings.ABO_PREISE_FESTGELEGT:
        return None
    laufend = (AboRechnung.alle_organisationen
               .filter(organisation=organisation, art=AboRechnung.ART_ABO, periode_von__lte=heute, periode_bis__gte=heute)
               .exclude(status=AboRechnung.STATUS_STORNIERT).order_by('-periode_von').first())
    if laufend is None:
        return None
    einheiten = zaehle(organisation.pk, 'einheiten')
    jaehrlich = nachher['jaehrlich']
    alt = positionen_fuer(vorher['stufe'], einheiten, jaehrlich, vorher['module'])[0]
    neu = positionen_fuer(nachher['stufe'], einheiten, jaehrlich, nachher['module'])[0]
    _t, gesamt = anteil_der_periode(laufend.periode_von, laufend.periode_bis, jaehrlich)
    rest = (laufend.periode_bis - heute).days + 1
    unterschied = ((neu - alt) * Decimal(rest) / Decimal(gesamt)).quantize(RAPPEN, rounding=ROUND_HALF_UP)
    if unterschied == 0:
        return None
    from django.utils import translation
    with translation.override('de'):
        text = _beschreibung_der_aenderung(vorher, nachher, heute) + ', ' + _('anteilig %(t)s von %(g)s Tagen') % {'t': rest, 'g': gesamt}
    if unterschied < 0:
        return AboGutschrift.alle_organisationen.create(
            organisation=organisation, datum=heute, text=text[:240], betrag=-unterschied)

    satz = settings.ABO_MWST_SATZ
    satz = Decimal(str(satz)) if satz is not None else None
    mwst = (unterschied * satz / 100).quantize(RAPPEN, rounding=ROUND_HALF_UP) if satz else Decimal('0.00')
    with transaction.atomic():
        rechnung = AboRechnung.alle_organisationen.create(
            organisation=organisation, art=AboRechnung.ART_ZUSATZ, periode_von=heute, periode_bis=laufend.periode_bis,
            stufe=nachher['stufe'], intervall=intervall_von(organisation), einheiten=einheiten, netto=unterschied,
            mwst_satz=satz, mwst_betrag=mwst, brutto=unterschied + mwst, rechnungsdatum=heute,
            faellig_am=faellig_fuer(heute, heute), positionen=[{'text': text, 'betrag': str(unterschied)}])
        rechnung.qr_referenz = qrr_referenz(organisation.pk, rechnung.pk)[0]
        rechnung.save(update_fields=['qr_referenz'])
    if mail:
        try:
            rechnung_senden(rechnung, heute=heute)
        except (RechnungNichtSendbar, OSError) as fehler:
            logger.warning('%s: Zusatzrechnung %s nicht versandt: %s', organisation, rechnung.nummer, fehler)
    return rechnung


def faellig_fuer(von, heute):
    """Fälligkeit einer Abo-Rechnung: im Voraus, also am Periodenbeginn.

    Läuft die Periode schon (Rechnung gestellt am oder nach dem Beginn), gilt die Zahlungsfrist ab Rechnungsdatum.
    """
    if von > heute:
        return von
    return heute + timedelta(days=settings.ABO_ZAHLUNGSFRIST_TAGE)


def rechnung_stellen(organisation, abo, heute=None, trotz_platzhalter=False):
    """Stellt die Rechnung der nächsten Periode aus. Gibt sie zurück oder `None`.

    Idempotent: Die Periode ist je Organisation eindeutig; ein zweiter Lauf am
    selben Tag stellt nichts nach. Pro Aufruf höchstens eine Periode.
    """
    from core.utils.qr_code import qrr_referenz
    from abo.models import AboRechnung

    heute = heute or datum_heute()
    periode = naechste_periode(abo, organisation)
    # Im Voraus: Die Rechnung entsteht bis zu ABO_VORLAUF_TAGE vor Periodenbeginn (oder sofort, wenn die Periode läuft).
    if periode is None or periode[0] > heute + timedelta(days=getattr(settings, 'ABO_VORLAUF_TAGE', 0)):
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
    # Zugebuchte Module kosten mit: ausser bei Bestandsschutz (alles offen, keine Rechnung) und wenn sie im Grundpreis stecken.
    netto, bemerkung, positionen = positionen_fuer(stufe, einheiten, jaehrlich, tuple(abo.zusatzmodule or ()))
    # Angebrochene Periode (Start mitten im Monat): anteilig nach Tagen.
    tage, gesamt = anteil_der_periode(von, bis, jaehrlich)
    netto, positionen = _anteilig(netto, positionen, tage, gesamt)
    # Offene Gutschriften (Abwertung mitten in einer früheren Periode) mindern diese Rechnung, nie unter null.
    abzuege = _gutschriften_abziehen(organisation, netto)
    for abzug in abzuege:
        positionen.append({'text': abzug['text'], 'betrag': str(-abzug['betrag'])})
        netto -= abzug['betrag']

    satz = settings.ABO_MWST_SATZ
    satz = Decimal(str(satz)) if satz is not None else None
    mwst = (netto * satz / 100).quantize(RAPPEN, rounding=ROUND_HALF_UP) if satz else Decimal('0.00')

    with transaction.atomic():
        rechnung, neu = AboRechnung.alle_organisationen.get_or_create(
            organisation=organisation, periode_von=von,
            defaults=dict(
                periode_bis=bis, stufe=stufe, intervall=intervall_von(organisation), einheiten=einheiten,
                netto=netto, mwst_satz=satz, mwst_betrag=mwst, brutto=netto + mwst,
                rechnungsdatum=heute, faellig_am=faellig_fuer(von, heute),
                platzhalter=not settings.ABO_PREISE_FESTGELEGT, bemerkung=bemerkung[:240], positionen=positionen))
        if neu:
            rechnung.qr_referenz = qrr_referenz(organisation.pk, rechnung.pk)[0]
            rechnung.save(update_fields=['qr_referenz'])
            for abzug in abzuege:
                gutschrift = abzug['gutschrift']
                gutschrift.verrechnet += abzug['betrag']
                gutschrift.save(update_fields=['verrechnet'])
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
    if tage >= settings.ABO_SPERRE_NACH_TAGEN:
        return f.ZUSTAND_GESPERRT
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


def rechnung_senden(rechnung, erinnerung=False, heute=None, stufe=1):
    """Schickt die Rechnung als PDF (mit QR-Einzahlungsschein) per Mail an die Verwaltung.

    `erinnerung=True`: als Zahlungserinnerung zur offenen Rechnung (setzt `erinnert_am`); `stufe=2`: als 2. Mahnung mit der
    Mahngebühr, die auf der Rechnung steht. Das PDF hängt immer an: Wer
    die Mail liest, soll bezahlen können, ohne sich anzumelden. Gibt die Empfängeradresse zurück; kann der Betreiber
    nichts versenden, steht der Grund in `RechnungNichtSendbar`.
    """
    from django.core.mail import EmailMessage

    from abo.rechnung_pdf import abo_rechnung_pdf

    organisation = rechnung.organisation
    empfaenger = rechnungs_adresse(organisation)
    if not empfaenger:
        raise RechnungNichtSendbar(_('Diese Verwaltung hat keine E-Mail-Adresse hinterlegt.'))
    if not anschrift_vollstaendig(organisation):
        raise RechnungNichtSendbar(_('Die Anschrift der Verwaltung fehlt (Strasse, PLZ, Ort): in der Kundenkartei ergänzen.'))
    pdf = abo_rechnung_pdf(rechnung)
    if pdf is None:
        raise RechnungNichtSendbar(_('Es ist keine Zahlungsverbindung (IBAN) des Rechnungsstellers hinterlegt.'))
    absender = settings.ABO_RECHNUNGSSTELLER.get('email') or settings.DEFAULT_FROM_EMAIL
    angaben = {'nummer': rechnung.nummer, 'betrag': f'{rechnung.brutto + rechnung.mahngebuehr:.2f}',
               'gebuehr': f'{rechnung.mahngebuehr:.2f}',
               'faellig': rechnung.faellig_am.strftime('%d.%m.%Y'),
               'von': rechnung.periode_von.strftime('%d.%m.%Y'), 'bis': rechnung.periode_bis.strftime('%d.%m.%Y')}
    if erinnerung and stufe >= 2:
        betreff = _('immoswiss: 2. Mahnung zur Rechnung %(nummer)s') % angaben
        if rechnung.mahngebuehr > 0:
            text = _('Die Rechnung %(nummer)s für Ihr immoswiss-Abonnement (%(von)s bis %(bis)s) war am %(faellig)s fällig '
                     'und ist trotz unserer Zahlungserinnerung noch offen. Wir bitten Sie, den Gesamtbetrag von CHF '
                     '%(betrag)s (inklusive Mahngebühr CHF %(gebuehr)s) umgehend mit dem QR-Einzahlungsschein auf der '
                     'Rechnung im Anhang zu bezahlen. Bleibt die Zahlung weiter aus, wird Ihr Zugang schreibgeschützt und '
                     'später gesperrt; Ihre Daten bleiben in jedem Fall erhalten.') % angaben
        else:
            text = _('Die Rechnung %(nummer)s für Ihr immoswiss-Abonnement (%(von)s bis %(bis)s) war am %(faellig)s fällig '
                     'und ist trotz unserer Zahlungserinnerung noch offen. Wir bitten Sie, den Betrag von CHF %(betrag)s '
                     'umgehend mit dem QR-Einzahlungsschein auf der Rechnung im Anhang zu bezahlen. Bleibt die Zahlung '
                     'weiter aus, wird Ihr Zugang schreibgeschützt und später gesperrt; Ihre Daten bleiben in jedem Fall '
                     'erhalten.') % angaben
    elif erinnerung:
        betreff = _('immoswiss: Zahlungserinnerung zur Rechnung %(nummer)s') % angaben
        text = _('Die Rechnung %(nummer)s über CHF %(betrag)s für Ihr immoswiss-Abonnement (%(von)s bis %(bis)s) war '
                 'am %(faellig)s fällig und ist noch offen. Bitte begleichen Sie sie mit dem QR-Einzahlungsschein auf '
                 'der Rechnung im Anhang. Ist die Zahlung bereits erfolgt, ist diese Mail gegenstandslos.') % angaben
    else:
        betreff = _('immoswiss: Rechnung %(nummer)s') % angaben
        text = _('Im Anhang finden Sie die Rechnung %(nummer)s über CHF %(betrag)s für Ihr immoswiss-Abonnement '
                 '(%(von)s bis %(bis)s). Sie ist bis zum %(faellig)s zu bezahlen, am einfachsten mit dem '
                 'QR-Einzahlungsschein auf der Rechnung. Dieselbe Rechnung finden Sie unter Einstellungen > Abonnement.'
                 ) % angaben
    nachricht = EmailMessage(betreff, text, absender, [empfaenger])
    nachricht.attach(f'{rechnung.nummer}.pdf', pdf, 'application/pdf')
    nachricht.send(fail_silently=False)
    heute = heute or datum_heute()
    rechnung.versendet_am = heute
    felder = ['versendet_am']
    if erinnerung:
        rechnung.erinnert_am = heute
        felder.append('erinnert_am')
    rechnung.save(update_fields=felder)
    return empfaenger


def anschrift_vollstaendig(organisation):
    """Hat die Verwaltung Strasse, PLZ und Ort? Ohne sie hat die Rechnung keine Anschrift und keinen gültigen Zahlteil."""
    return bool((organisation.strasse or '').strip() and (organisation.plz or '').strip()
                and (organisation.ort or '').strip())


def rechnungs_adresse(organisation):
    """Die Mail-Adresse für Rechnungen und Mahnungen: die abweichende aus der Kundenkartei, sonst die der Verwaltung."""
    from abo.models import Kundenstamm
    stamm = Kundenstamm.alle_organisationen.filter(organisation=organisation).first()
    return (stamm.rechnung_email if stamm is not None and stamm.rechnung_email else organisation.email) or ''


def erinnerung_senden(organisation, neu_zustand):
    """Zahlungserinnerung per E-Mail an die Verwaltung. Gibt True zurück, wenn versandt."""
    empfaenger = rechnungs_adresse(organisation)
    if not empfaenger:
        logger.warning('%s: keine E-Mail-Adresse, Erinnerung nicht versandt', organisation)
        return False
    absender = (settings.ABO_RECHNUNGSSTELLER.get('email') or settings.DEFAULT_FROM_EMAIL)
    if neu_zustand == f.ZUSTAND_GESPERRT:
        betreff = _('immoswiss: Ihr Zugang ist gesperrt')
        text = _('Die Rechnung für Ihr Abonnement ist seit mehr als %(tage)s Tagen überfällig. Ihr Zugang ist deshalb '
                 'gesperrt. Anmeldung, Abonnement (Rechnung und Einzahlungsschein) und der Datenexport bleiben '
                 'erreichbar. Mit dem Zahlungseingang ist alles wieder offen. Es wird nichts gelöscht.'
                 ) % {'tage': settings.ABO_SPERRE_NACH_TAGEN}
    elif neu_zustand == f.ZUSTAND_LESEMODUS:
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
    send_mail(betreff, text, absender, [empfaenger], fail_silently=False)
    return True


def mahnen(organisation, heute=None):
    """Führt die Mahnstufe der ältesten überfälligen Rechnung nach und mahnt, wenn eine neue Stufe erreicht ist.

    1. Mahnung nach `ABO_MAHNUNG_NACH_TAGEN`, 2. Mahnung nach `ABO_MAHNUNG2_NACH_TAGEN`, mit der Mahngebühr
    `ABO_MAHNGEBUEHR` (0 = ohne). Jede Stufe geht pro Rechnung genau einmal hinaus. Lesemodus und Sperre haben ihre eigene
    Mitteilung. Die Mahnung geht mit dem PDF hinaus; fehlt dafür die Zahlungsverbindung, geht der Text allein hinaus
    (`erinnerung_senden`). Gibt die versandte Stufe zurück, sonst `None`.
    """
    from abo.models import AboRechnung
    heute = heute or datum_heute()
    rechnung = (AboRechnung.alle_organisationen
                .filter(organisation=organisation, status=AboRechnung.STATUS_OFFEN, faellig_am__lt=heute)
                .order_by('faellig_am').first())
    if rechnung is None:
        return None
    tage = (heute - rechnung.faellig_am).days
    ziel = (2 if tage >= settings.ABO_MAHNUNG2_NACH_TAGEN
            else 1 if tage >= settings.ABO_MAHNUNG_NACH_TAGEN else 0)
    if ziel <= rechnung.mahnstufe:
        return None
    if ziel == 2:
        rechnung.mahngebuehr = Decimal(str(settings.ABO_MAHNGEBUEHR or 0)).quantize(RAPPEN)
        rechnung.save(update_fields=['mahngebuehr'])
    try:
        rechnung_senden(rechnung, erinnerung=True, heute=heute, stufe=ziel)
        versandt = True
    except (RechnungNichtSendbar, OSError) as fehler:
        logger.warning('%s: Mahnung %s zu %s ohne PDF: %s', organisation, ziel, rechnung.nummer, fehler)
        versandt = erinnerung_senden(organisation, f.ZUSTAND_MAHNUNG)
    if not versandt:
        return None
    rechnung.mahnstufe = ziel
    rechnung.save(update_fields=['mahnstufe'])
    return ziel


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
    if rechnung is not None and mail:
        # Die neue Rechnung geht mit dem PDF hinaus. Scheitert der Versand (keine Adresse, keine IBAN), bleibt die
        # Rechnung bestehen und der Betreiber kann sie im Portal erneut senden.
        try:
            rechnung_senden(rechnung, heute=heute)
            bericht['versandt'] = True
        except (RechnungNichtSendbar, OSError) as fehler:
            logger.warning('%s: Rechnung %s nicht versandt: %s', organisation, rechnung.nummer, fehler)
            bericht['versandt'] = False
    alt, neu = zustand_aktualisieren(organisation, heute)
    bericht['zustand'] = neu
    if mail and neu == f.ZUSTAND_MAHNUNG:
        bericht['mahnstufe'] = mahnen(organisation, heute)
        bericht['mail'] = bericht['mahnstufe'] is not None
    elif mail and neu != alt and neu != f.ZUSTAND_AKTIV:
        bericht['mail'] = erinnerung_senden(organisation, neu)
    return bericht
