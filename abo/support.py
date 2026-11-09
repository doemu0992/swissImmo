"""Support-Anfragen der Verwaltungen an den Betreiber: ein Knopf auf der Abo-Seite, kein Ticketsystem.

Die Anfrage geht als Mail an den Betreiber (Antworten gehen an die Person, die sie gestellt hat) und steht zugleich als Eintrag
«Support-Anfrage» im Verlauf der Kundenkartei. Dort ist sie offen, bis der Betreiber sie erledigt markiert. Der Eintrag entsteht
vor dem Versand: Scheitert die Mail, geht die Anfrage nicht verloren, der Betreiber sieht sie im Portal.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

#: So viele Anfragen darf eine Verwaltung pro Stunde stellen (Schutz vor Missbrauch und versehentlichem Mehrfachsenden).
MAX_PRO_STUNDE = 5
BETREFF_MIN, BETREFF_MAX = 3, 120
TEXT_MIN, TEXT_MAX = 10, 4000


def support_adresse():
    """Wohin Anfragen gehen: ABO_SUPPORT_EMAIL, sonst die Absenderadresse der Rechnungen, sonst DEFAULT_FROM_EMAIL."""
    return (getattr(settings, 'ABO_SUPPORT_EMAIL', '') or settings.ABO_RECHNUNGSSTELLER.get('email')
            or settings.DEFAULT_FROM_EMAIL or '')


def anfrage_stellen(organisation, benutzer, betreff, nachricht):
    """Nimmt eine Anfrage entgegen. Gibt `(eintrag, versandt)` zurück; ungültige Eingaben und zu viele Anfragen: `ValueError`."""
    from abo.models import KundenKontakt
    from core import funktionen as f

    betreff, nachricht = (betreff or '').strip(), (nachricht or '').strip()
    if not (BETREFF_MIN <= len(betreff) <= BETREFF_MAX):
        raise ValueError(_('Bitte einen Betreff angeben (%(min)s bis %(max)s Zeichen).')
                         % {'min': BETREFF_MIN, 'max': BETREFF_MAX})
    if not (TEXT_MIN <= len(nachricht) <= TEXT_MAX):
        raise ValueError(_('Bitte die Anfrage beschreiben (%(min)s bis %(max)s Zeichen).')
                         % {'min': TEXT_MIN, 'max': TEXT_MAX})
    jetzt = timezone.now()
    kuerzlich = KundenKontakt.alle_organisationen.filter(
        organisation=organisation, art=KundenKontakt.ART_SUPPORT, zeitpunkt__gte=jetzt - timedelta(hours=1)).count()
    if kuerzlich >= MAX_PRO_STUNDE:
        raise ValueError(_('Es sind zu viele Anfragen in kurzer Zeit eingegangen. Bitte später noch einmal versuchen '
                           'oder direkt anrufen.'))

    eintrag = KundenKontakt.alle_organisationen.create(
        organisation=organisation, zeitpunkt=jetzt, art=KundenKontakt.ART_SUPPORT,
        text=f'{betreff}\n\n{nachricht}', erfasst_von=benutzer.get_username())

    ziel = support_adresse()
    if not ziel:
        logger.warning('%s: Support-Anfrage gespeichert, aber keine Support-Adresse eingestellt', organisation)
        return eintrag, False
    absender = settings.ABO_RECHNUNGSSTELLER.get('email') or settings.DEFAULT_FROM_EMAIL
    kopf = (f'Verwaltung: {organisation.firma} (K-{organisation.pk:04d})\n'
            f'Von: {benutzer.get_full_name() or benutzer.get_username()} <{benutzer.email}>\n'
            f'Stufe: {f.STUFEN_NAMEN.get(f.stufe_von(organisation), "")}\n\n')
    mail = EmailMessage(f'[Support] {organisation.firma}: {betreff}', kopf + nachricht, absender, [ziel],
                        reply_to=[benutzer.email] if benutzer.email else None)
    try:
        mail.send(fail_silently=False)
    except OSError:
        logger.warning('%s: Support-Mail nicht versandt', organisation, exc_info=True)
        return eintrag, False
    return eintrag, True
