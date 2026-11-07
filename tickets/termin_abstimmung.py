# tickets/termin_abstimmung.py
"""Terminabstimmung Mieter <-> Handwerker (die Verwaltung vermittelt nicht).

ABLAUF
  1. Eine Seite (Mieter oder Handwerker) macht einen VORSCHLAG (Datum, Uhrzeit, Hinweis):
     ``termin_status = 'vorgeschlagen'``, der Vorschlag steht in ``termin_vorschlag_*``. Die Gegenseite
     bekommt eine Mail mit signiertem Link (``direktkanal.link_url``, ohne Anmeldung) und sieht ihn im Portal.
  2. Die Gegenseite BESTÄTIGT oder macht einen GEGENVORSCHLAG (= ``vorschlagen`` von der anderen Seite;
     der alte Vorschlag wird ersetzt, die alten Links zeigen den neuen Stand).
  3. Erst die Bestätigung setzt den Termin (``workflow.termin_festlegen``: ``vereinbart``, Kalendereintrag an
     beide) und informiert die VERWALTUNG (Mail «Termin steht» + Verlauf).
  4. Wird ein vereinbarter Termin abgesagt oder durch einen neuen Vorschlag ersetzt, geht die Absage
     (Kalendereintrag storniert, ``workflow.termin_absagen``) an beide, und die Verwaltung erfährt es.

Eine Mail-Antwort setzt nie einen Termin (kein Text-Parsing): Sie ist eine Chat-Nachricht
(``direktkanal.aus_mail``). Der bisherige Weg «Verwaltung setzt den Termin» (``termin_festlegen``) bleibt.
"""
import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services.dokumentsprache import STANDARD, in_sprache

from . import direktkanal
from .workflow import (AUFTRAG_STORNIERT, _protokoll, _termin_text, termin_absagen, termin_festlegen,
                       verwaltung_benachrichtigen)

logger = logging.getLogger(__name__)

#: Ein Vorschlag liegt höchstens so weit in der Zukunft.
MAX_VORLAUF = timedelta(days=365)
HINWEIS_MAX = 300
SEITEN = ('mieter', 'handwerker')


def _gegenseite(seite):
    return 'handwerker' if seite == 'mieter' else 'mieter'


def _pruefen(auftrag, seite):
    if seite not in SEITEN:
        raise ValidationError(_('Unbekannte Seite.'), code='seite')
    if auftrag.status == AUFTRAG_STORNIERT or not direktkanal.ist_offen(auftrag):
        raise ValidationError(_('Der Auftrag ist abgeschlossen.'), code='geschlossen')


def _chat(auftrag, seite, text):
    """Eintrag im Chat — ohne eigene Mail (die Termin-Mails gehen separat) und als zugestellt markiert."""
    n = direktkanal.schreiben(auftrag, seite, text, zustellen=False)
    type(n).objects.filter(pk=n.pk).update(zugestellt_am=timezone.now())
    return n


def vorschlagen(auftrag, von, termin_am, hinweis='', jetzt=None):
    """Terminvorschlag von ``von`` an die Gegenseite (oder Gegenvorschlag / Verschiebung).

    Gibt True zurück, wenn die Mail an die Gegenseite hinausging (False auch bei fehlender Adresse —
    dann sieht sie den Vorschlag im Portal)."""
    _pruefen(auftrag, von)
    jetzt = jetzt or timezone.now()
    if termin_am is None:
        raise ValidationError(_('Bitte Datum und Zeit angeben.'), code='termin_fehlt')
    if timezone.is_naive(termin_am):
        termin_am = timezone.make_aware(termin_am)
    if termin_am <= jetzt:
        raise ValidationError(_('Der Termin liegt in der Vergangenheit.'), code='vergangenheit')
    if termin_am > jetzt + MAX_VORLAUF:
        raise ValidationError(_('Der Termin liegt zu weit in der Zukunft.'), code='zu_weit')
    hinweis = (hinweis or '').strip()
    if len(hinweis) > HINWEIS_MAX:
        raise ValidationError(_('Der Hinweis ist zu lang (höchstens %(n)s Zeichen).') % {'n': HINWEIS_MAX},
                              code='zu_lang')
    ticket = auftrag.ticket
    verschoben_von = None
    if auftrag.termin_status == 'vereinbart' and auftrag.termin_am:
        verschoben_von = auftrag.termin_am
        termin_absagen(auftrag)              # Kalendereintrag wird storniert, beide erfahren es
    with transaction.atomic():
        auftrag.termin_status = 'vorgeschlagen'
        auftrag.termin_vorschlag_am = termin_am
        auftrag.termin_vorschlag_von = von
        auftrag.termin_vorschlag_hinweis = hinweis
        auftrag.save(update_fields=['termin_status', 'termin_vorschlag_am', 'termin_vorschlag_von',
                                    'termin_vorschlag_hinweis'])
        _chat(auftrag, von, f"Terminvorschlag: {_termin_text(termin_am)}" + (f" — {hinweis}" if hinweis else ''))
    if verschoben_von:
        verwaltung_benachrichtigen(
            ticket, f"Termin verschoben: {ticket.titel}",
            f"{direktkanal.seiten_name(auftrag, von)} möchte den Termin vom {_termin_text(verschoben_von)} "
            f"für «{ticket.titel}» (Auftrag #{auftrag.pk}, {auftrag.handwerker.firma}) verschieben und schlägt "
            f"{_termin_text(termin_am)} vor. Der alte Kalendereintrag ist abgesagt. Die Abstimmung läuft direkt "
            f"zwischen Mieter und Handwerker.")
        _protokoll(ticket, f"Termin verschoben: neuer Vorschlag {_termin_text(termin_am)} von "
                           f"{direktkanal.seiten_name(auftrag, von)}; Verwaltung informiert.")
    return _vorschlag_mail(auftrag, von, termin_am, hinweis)


def _vorschlag_mail(auftrag, von, termin_am, hinweis):
    from core.services.anrede import handwerker_gruss
    from core.services.ticket_workflow import melder_gruss, melder_sprache
    from core.utils.email_service import klartext_html, send_via_hoststar
    from .workflow import reply_to
    ziel = _gegenseite(von)
    adresse = direktkanal.seiten_adresse(auftrag, ziel)
    if not adresse:
        return False
    ticket = auftrag.ticket
    link = direktkanal.link_url(auftrag, ziel)
    wer = direktkanal.seiten_name(auftrag, von)
    zeit = _termin_text(termin_am)
    try:
        with in_sprache(melder_sprache(ticket) if ziel == 'mieter' else STANDARD):
            gruss = melder_gruss(ticket) if ziel == 'mieter' else handwerker_gruss(auftrag.handwerker)
            betreff = direktkanal.betreff_fuer(auftrag, _("Terminvorschlag: %(zeit)s") % {'zeit': zeit})
            inhalt = _("%(gruss)s\n\n%(wer)s schlägt für «%(schaden)s» folgenden Termin vor:\n\n"
                       "Wann: %(zeit)s\n%(hinweis)s\n"
                       "Bestätigen oder einen anderen Termin vorschlagen (ohne Anmeldung):\n%(link)s\n\n"
                       "Sie können auch direkt auf diese Mail antworten. Verbindlich wird der Termin erst, "
                       "wenn Sie ihn bestätigen.") % {
                'gruss': gruss, 'wer': wer, 'schaden': ticket.titel, 'zeit': zeit, 'link': link,
                'hinweis': (_("Hinweis: %(h)s") % {'h': hinweis} + "\n") if hinweis else ''}
        html = klartext_html(inhalt, link)
        return send_via_hoststar(adresse, betreff, html, reply_to=reply_to(ticket),
                                 organisation=ticket.organisation_id, absender_name=wer,
                                 headers={direktkanal.KOPF_BRUECKE: '1', 'Auto-Submitted': 'auto-generated'})
    except Exception:
        logger.exception("Terminvorschlag-Mail zu Auftrag #%s fehlgeschlagen", auftrag.pk)
        return False


def bestaetigen(auftrag, durch, kennung=None, jetzt=None):
    """Die Gegenseite bestätigt den offenen Vorschlag: Termin steht, Verwaltung wird informiert.

    ``kennung``: der Zeitpunkt (Sekunden) des Vorschlags, den die bestätigende Person gesehen hat. Hat die Gegenseite
    inzwischen einen anderen vorgeschlagen, wird abgelehnt statt den falschen Termin zu bestätigen."""
    _pruefen(auftrag, durch)
    jetzt = jetzt or timezone.now()
    from .models import HandwerkerAuftrag
    with transaction.atomic():
        # Sperren: zwei gleichzeitige Bestätigungen (Doppelklick, Portal + Mail-Link) setzen nur einmal.
        frisch = HandwerkerAuftrag.alle_organisationen.select_for_update().get(pk=auftrag.pk)
        if frisch.termin_status != 'vorgeschlagen' or not frisch.termin_vorschlag_am:
            raise ValidationError(_('Es gibt keinen offenen Terminvorschlag.'), code='kein_vorschlag')
        if kennung is not None and int(frisch.termin_vorschlag_am.timestamp()) != kennung:
            raise ValidationError(_('Der Vorschlag wurde inzwischen geändert. Bitte den aktuellen ansehen.'),
                                  code='veraltet')
        if frisch.termin_vorschlag_von == durch:
            raise ValidationError(_('Der Vorschlag stammt von Ihnen — die Gegenseite muss ihn bestätigen.'),
                                  code='eigener_vorschlag')
        if frisch.termin_vorschlag_am <= jetzt:
            raise ValidationError(_('Der Termin liegt in der Vergangenheit.'), code='vergangenheit')
        for feld in ('termin_status', 'termin_am', 'termin_vorschlag_am', 'termin_vorschlag_von',
                     'termin_vorschlag_hinweis'):
            setattr(auftrag, feld, getattr(frisch, feld))
        zeit, vorgeschlagen_von = auftrag.termin_vorschlag_am, auftrag.termin_vorschlag_von
        _chat(auftrag, durch, f"Termin bestätigt: {_termin_text(zeit)}")
    m_ok, h_ok = termin_festlegen(auftrag, zeit)       # setzt vereinbart, löscht den Vorschlag, ICS an beide
    _termin_steht_melden(auftrag, zeit, vorgeschlagen_von, durch)
    return m_ok, h_ok


def _termin_steht_melden(auftrag, zeit, vorgeschlagen_von, bestaetigt_von):
    ticket = auftrag.ticket
    text = (f"Termin steht: {_termin_text(zeit)}, {auftrag.handwerker.firma}, "
            f"{direktkanal.mieter_name(ticket)}.\n\n"
            f"Ticket #{ticket.pk} «{ticket.titel}» (Auftrag #{auftrag.pk}). Der Termin wurde direkt zwischen "
            f"Mieter und Handwerker abgestimmt (Vorschlag: {direktkanal.seiten_name(auftrag, vorgeschlagen_von)}, "
            f"bestätigt: {direktkanal.seiten_name(auftrag, bestaetigt_von)}); beide haben den Kalendereintrag.")
    ok = verwaltung_benachrichtigen(ticket, f"Termin steht: {_termin_text(zeit)}", text)
    _protokoll(ticket, f"Termin direkt abgestimmt (Vorschlag {direktkanal.seiten_name(auftrag, vorgeschlagen_von)}, "
                       f"bestätigt {direktkanal.seiten_name(auftrag, bestaetigt_von)}); Verwaltung "
                       f"{'informiert' if ok else 'NICHT informiert'}.")
    return ok


def absagen_durch(auftrag, durch, hinweis=''):
    """Mieter oder Handwerker sagt den vereinbarten Termin ab (ohne neuen Vorschlag)."""
    _pruefen(auftrag, durch)
    if auftrag.termin_status != 'vereinbart' or not auftrag.termin_am:
        raise ValidationError(_('Es gibt keinen vereinbarten Termin.'), code='kein_termin')
    alt = auftrag.termin_am
    hinweis = (hinweis or '').strip()[:HINWEIS_MAX]
    termin_absagen(auftrag)
    _chat(auftrag, durch, f"Termin abgesagt: {_termin_text(alt)}" + (f" — {hinweis}" if hinweis else ''))
    ticket = auftrag.ticket
    verwaltung_benachrichtigen(
        ticket, f"Termin abgesagt: {ticket.titel}",
        f"{direktkanal.seiten_name(auftrag, durch)} hat den Termin vom {_termin_text(alt)} für «{ticket.titel}» "
        f"(Auftrag #{auftrag.pk}, {auftrag.handwerker.firma}) abgesagt." + (f"\nHinweis: {hinweis}" if hinweis else '')
        + "\nMieter und Handwerker stimmen einen neuen Termin direkt ab.")
    return True
