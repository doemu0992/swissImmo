"""Änderungsanfragen aus den Portalen: stellen, bestätigen, ablehnen.

Das Portal ändert nie selbst Stammdaten. Es legt eine `Aenderungsanfrage` an; die Verwaltung bestätigt oder lehnt ab.
Erst die Bestätigung führt die Änderung aus. Beides steht im Logbuch (Kategorie Sicherheit), und die Antragsteller
erfahren das Ergebnis per Mail und im Portal.
"""
import logging

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from core.models import Aenderungsanfrage
from core.tenancy import organisation_kontext

logger = logging.getLogger(__name__)

#: Welche Felder eine Art ändern darf (nichts ausserhalb der Liste wird je geschrieben, auch nicht bei manipulierten Daten).
ERLAUBTE_FELDER = {
    Aenderungsanfrage.ART_KONTAKT: ('mobile', 'telefon_privat', 'email'),
    Aenderungsanfrage.ART_EIG_KONTAKT: ('telefon', 'email'),
    Aenderungsanfrage.ART_EIG_BANK: ('bank_name', 'iban'),
}

FELDNAMEN = {'mobile': 'Mobile', 'telefon_privat': 'Telefon', 'email': 'E-Mail', 'telefon': 'Telefon',
             'bank_name': 'Bank', 'iban': 'IBAN'}


FREITEXT_ARTEN = (Aenderungsanfrage.ART_MITTEILUNG, Aenderungsanfrage.ART_ZAHLUNGSPLAN, Aenderungsanfrage.ART_EIG_ANFRAGE)


def erlaubt_arten_mit_feldern():
    return tuple(ERLAUBTE_FELDER)


class AnfrageFehler(ValueError):
    """Die Anfrage lässt sich nicht stellen oder entscheiden (Meldung ist für Menschen lesbar)."""


def _absender_name(anfrage):
    a = anfrage.absender
    return getattr(a, 'display_name', None) or getattr(a, 'firma_oder_name', '') or str(a)


def _logbuch(anfrage, aktion, benutzer):
    from core.auth import log_aktion
    try:
        with organisation_kontext(anfrage.organisation):
            log_aktion(None, aktion, objekt=f'{anfrage.get_art_display()}: {_absender_name(anfrage)}',
                       details=anfrage.zusammenfassung[:500], kategorie='sicherheit', user=benutzer)
    except Exception:                                      # noqa: BLE001 — das Logbuch bricht keinen Vorgang
        logger.warning('Logbucheintrag zur Anfrage %s fehlgeschlagen', anfrage.pk, exc_info=True)


def _mail(adresse, betreff, text, organisation):
    if not adresse:
        return False
    from core.utils.email_service import send_ticket_email
    try:
        return send_ticket_email(adresse, betreff, text, organisation=organisation)
    except Exception:                                      # noqa: BLE001
        logger.warning('Mail zur Anfrage an %s fehlgeschlagen', adresse, exc_info=True)
        return False


def zusammenfassung_aus(art, daten, bisher=None):
    """Der Text für die Verwaltung: bei Feldern «Feld: alt → neu»."""
    bisher = bisher or {}
    zeilen = [f"{_(FELDNAMEN.get(k, k))}: «{bisher.get(k) or '—'}» → «{v or '—'}»" for k, v in daten.items()
              if k in ERLAUBTE_FELDER.get(art, ())]
    if daten.get('text'):
        zeilen.append(daten['text'])
    return '\n'.join(zeilen)


def stellen(*, art, daten=None, mieter=None, eigentuemer=None, text=''):
    """Legt eine Anfrage an und meldet sie der Verwaltung. Gibt die Anfrage zurück (oder `None`, wenn nichts zu melden ist)."""
    if (mieter is None) == (eigentuemer is None):
        raise AnfrageFehler('Eine Anfrage hat genau einen Absender.')
    absender = mieter or eigentuemer
    erlaubt = ERLAUBTE_FELDER.get(art, ())
    daten = {k: str(v).strip() for k, v in (daten or {}).items() if k in erlaubt}
    bisher = {k: getattr(absender, k, '') or '' for k in erlaubt}
    # Von den Feldern zählen nur wirkliche Änderungen; der Freitext gehört dazu, wenn es ihn gibt.
    geaendert = {k: v for k, v in daten.items() if v != bisher.get(k, '')}
    if text and text.strip():
        geaendert['text'] = text.strip()
    if art in erlaubt_arten_mit_feldern() and not any(k in erlaubt for k in geaendert):
        return None                                        # nichts geändert: keine Anfrage
    if art in FREITEXT_ARTEN and not geaendert.get('text'):
        return None
    zus = zusammenfassung_aus(art, geaendert, bisher)
    if art == Aenderungsanfrage.ART_MIETBESTAETIGUNG and not zus:
        zus = _('Bestätigung des Mietverhältnisses (PDF) gewünscht.')
    anfrage = Aenderungsanfrage.alle_organisationen.create(
        organisation=absender.organisation, mieter=mieter, eigentuemer=eigentuemer, art=art, daten=geaendert,
        zusammenfassung=zus)
    _logbuch(anfrage, 'Änderungsanfrage gestellt', getattr(absender, 'benutzer', None))
    org = absender.organisation
    _mail(getattr(org, 'email', ''), f'{anfrage.get_art_display()}: {_absender_name(anfrage)}',
          f'{_absender_name(anfrage)} hat über das Portal eine Anfrage gestellt:\n\n{zus}\n\n'
          'Bitte in der Anwendung unter «Heute → Anfragen» bestätigen oder ablehnen.', org)
    return anfrage


@transaction.atomic
def bestaetigen(anfrage, benutzer):
    """Führt die Änderung aus und schliesst die Anfrage."""
    anfrage = Aenderungsanfrage.alle_organisationen.select_for_update().get(pk=anfrage.pk)
    if not anfrage.offen:
        raise AnfrageFehler(_('Diese Anfrage ist bereits entschieden.'))
    erlaubt = ERLAUBTE_FELDER.get(anfrage.art, ())
    if erlaubt:
        ziel = anfrage.absender
        felder = [k for k in erlaubt if k in anfrage.daten]
        for k in felder:
            setattr(ziel, k, anfrage.daten[k])
        if felder:
            ziel.save(update_fields=felder)
    anfrage.status = Aenderungsanfrage.STATUS_BESTAETIGT
    anfrage.entschieden_am = timezone.now()
    anfrage.entschieden_von = benutzer
    anfrage.save(update_fields=['status', 'entschieden_am', 'entschieden_von'])
    _logbuch(anfrage, 'Änderungsanfrage bestätigt', benutzer)
    _benachrichtigen(anfrage)
    return anfrage


@transaction.atomic
def ablehnen(anfrage, benutzer, begruendung=''):
    anfrage = Aenderungsanfrage.alle_organisationen.select_for_update().get(pk=anfrage.pk)
    if not anfrage.offen:
        raise AnfrageFehler(_('Diese Anfrage ist bereits entschieden.'))
    anfrage.status = Aenderungsanfrage.STATUS_ABGELEHNT
    anfrage.entschieden_am = timezone.now()
    anfrage.entschieden_von = benutzer
    anfrage.antwort = (begruendung or '').strip()
    anfrage.save(update_fields=['status', 'entschieden_am', 'entschieden_von', 'antwort'])
    _logbuch(anfrage, 'Änderungsanfrage abgelehnt', benutzer)
    _benachrichtigen(anfrage)
    return anfrage


def _benachrichtigen(anfrage):
    a = anfrage.absender
    sprache = (getattr(a, 'sprache', '') or 'de')[:2]
    with translation.override(sprache if sprache in ('de', 'fr', 'it', 'en') else 'de'):
        if anfrage.status == Aenderungsanfrage.STATUS_BESTAETIGT:
            text = _('Ihre Anfrage «%(art)s» wurde von der Verwaltung bestätigt.') % {'art': anfrage.get_art_display()}
        else:
            text = _('Ihre Anfrage «%(art)s» wurde von der Verwaltung abgelehnt.') % {'art': anfrage.get_art_display()}
            if anfrage.antwort:
                text += '\n\n' + anfrage.antwort
        betreff = _('Ihre Anfrage an die Verwaltung')
        text += '\n\n' + _('Den Stand sehen Sie im Portal.')
    _mail(getattr(a, 'email', ''), betreff, text, anfrage.organisation)
