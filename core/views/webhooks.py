"""Eingehende Mails von Brevo (Inbound Parsing) → Antworten auf Ticket-Mails.

FORMATE. Brevo liefert ein JSON mit dem Array ``items`` (je Mail ein Objekt: ``From`` und ``To`` /
``Recipients`` als Mailbox ``{Name, Address}``, ``Subject``, ``RawTextBody``, ``RawHtmlBody``,
``ExtractedMarkdownMessage``, ``Headers``, ``MessageId``). Die frühere Fassung dieser View las die Felder
auf oberster Ebene — das passt nicht zu diesem Format; sie hätte bei echter Brevo-Post nichts gefunden.
Beide Formen werden angenommen: ``items[]`` und das alte flache Objekt (Felder oben, ``From`` als Text).

ZUORDNUNG. Zuerst die Empfängeradresse (``Recipients``, sonst ``To``): ``<kennung>@<ANTWORT_DOMAIN>``
nennt die Verwaltung. Ticketnummer und Auftragsmarke gelten dann NUR in dieser Verwaltung; ein Ticket einer
anderen Verwaltung ergibt dieselbe stille Antwort wie ein nicht vorhandenes. Eine Adresse auf der
Antwort-Domain mit unbekannter (oder abgelaufener) Kennung wird verworfen — nicht über die Ticketnummer
geraten. Nur ohne Plattformadresse (altes ``reply@…`` oder flaches Altformat ohne ``To``) gilt der Rückfall
über die Ticketnummer im Betreff wie bisher.

Die Verarbeitung selbst ist ``core.services.antwort_eingang.eingehende_antwort_verarbeiten`` (dieselbe wie
beim IMAP-Abruf). Anhänge werden ignoriert, HTML nie übernommen. Dieselbe ``MessageId`` wird je Verwaltung
nur einmal verarbeitet (``tickets.EingegangeneMail``).
"""
import hmac
import json
import logging
from email.utils import formataddr, getaddresses

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

#: Antwort bei allem, was bewusst nichts bewirkt. Immer dieselbe, damit sie nichts über Bestand verrät.
IGNORIERT = ('ignored', 200)


def _adressen(wert):
    """Reine Adressen (klein) aus Mailbox, Mailbox-Liste oder Text («a@b, Name <c@d>»)."""
    from core.services.antwort_eingang import rein_adresse
    if isinstance(wert, dict):
        wert = [wert]
    if isinstance(wert, str):
        wert = [formataddr(a) for a in getaddresses([wert])]
    ergebnis = []
    for eintrag in wert if isinstance(wert, (list, tuple)) else []:
        adresse = rein_adresse(eintrag)
        if adresse:
            ergebnis.append(adresse)
    return ergebnis


def _absender(wert):
    """Der From-Wert als Text ``Name <adresse>`` (Mailbox-Objekt oder schon Text)."""
    if isinstance(wert, dict):
        adresse = str(wert.get('Address') or wert.get('address') or '')
        name = str(wert.get('Name') or wert.get('name') or '')
        return formataddr((name, adresse)) if adresse else name
    return wert if isinstance(wert, str) else ''


def _message_id(item, kopf):
    roh = item.get('MessageId') or item.get('Message-Id') or next(
        (v for k, v in kopf.items() if k.lower() == 'message-id'), '')
    roh = str(roh or '').strip().strip('<>').strip()
    return roh[:255]


def _eine_mail(item):
    """Eine Mail verarbeiten. Gibt ``(status, http)`` zurück."""
    from core.funktionen import hintergrund_erlaubt
    from core.services import antwort_eingang as ae
    from core.tenancy import kontext_des_objekts
    from tickets.models import EingegangeneMail, SchadenMeldung

    betreff = item.get('Subject') if isinstance(item.get('Subject'), str) else ''
    absender = _absender(item.get('From'))
    text = ae.antworttext(item)
    kopf = ae.kopf_als_dict(item.get('Headers'))
    mail_id = _message_id(item, kopf)
    empfaenger = _adressen(item.get('Recipients') or item.get('To') or [])

    verwaltungen = {}
    for adresse in empfaenger:
        org = ae.organisation_zu_adresse(adresse)
        if org is not None:
            verwaltungen[org.pk] = org
    if len(verwaltungen) > 1:
        logger.warning("Brevo-Webhook: Mail an mehrere Verwaltungen, verworfen")
        return IGNORIERT

    if verwaltungen:
        organisation = next(iter(verwaltungen.values()))
        mit_ticket = None
    elif any(ae.ist_plattform_adresse(a) and not ae.ist_globale_adresse(a) for a in empfaenger):
        logger.info("Brevo-Webhook: Adresse auf der Antwort-Domain ohne gültige Kennung, verworfen")
        return IGNORIERT
    else:
        # Rückfall wie bisher: nur die Ticketnummer im Betreff.
        nummer = ae.ticketnummer_aus_betreff(betreff)
        if not nummer:
            return 'no ticket id in subject', 200
        # `alle_organisationen`: Brevo liefert die Mail ohne Anmeldung und ohne Mandantenkontext;
        # die Nummer ist das Einzige, was die Mail nennt. Danach läuft alles im Kontext des Tickets.
        mit_ticket = SchadenMeldung.alle_organisationen.filter(pk=nummer).first()
        if mit_ticket is None:
            return 'ticket not found', 404
        organisation = mit_ticket.organisation

    with kontext_des_objekts(organisation):
        if not hintergrund_erlaubt(organisation):
            logger.info("Brevo-Webhook: Verwaltung %s im Lesemodus, Antwort nicht verarbeitet", organisation.pk)
            return IGNORIERT
        with transaction.atomic():
            if mail_id:
                _eintrag, neu = EingegangeneMail.objects.get_or_create(message_id=mail_id)
                if not neu:
                    return 'duplicate', 200
            ergebnis = ae.eingehende_antwort_verarbeiten(organisation, absender, betreff, text, kopf)
    if ergebnis == 'ohne_ticket':
        return ('empty', 200) if mit_ticket is not None else IGNORIERT
    return ('ok, chat' if ergebnis.startswith('direkt_') else 'ok, saved'), 200


@csrf_exempt
def brevo_inbound_webhook(request):
    if request.method == 'POST':
        # Ohne konfiguriertes Secret wird ABGEWIESEN. Früher stand hier `if secret:`
        # — war keines gesetzt, entfiel die Prüfung ganz und jeder konnte über
        # diesen Endpunkt Nachrichten in fremde Ticketverläufe schreiben.
        secret = getattr(settings, 'BREVO_WEBHOOK_SECRET', None)
        gesendet = request.headers.get('X-Webhook-Secret') or request.GET.get('token', '')
        if not secret or not hmac.compare_digest(str(gesendet), str(secret)):
            logger.warning("Brevo-Webhook: ungültiges/fehlendes Secret abgewiesen")
            return JsonResponse({'status': 'forbidden'}, status=403)
        try:
            daten = json.loads(request.body)
        except RequestDataTooBig:
            return JsonResponse({'status': 'too large'}, status=413)
        except ValueError:
            return JsonResponse({'status': 'invalid json'}, status=400)
        if isinstance(daten, dict) and isinstance(daten.get('items'), list):
            mails = daten['items']
        elif isinstance(daten, list):
            mails = daten
        else:
            mails = [daten]
        mails = [m for m in mails if isinstance(m, dict)]
        if not mails:
            return JsonResponse({'status': 'no items'}, status=400)
        ergebnisse = []
        try:
            for mail in mails:
                ergebnisse.append(_eine_mail(mail))
        except Exception:
            # 500: Brevo wiederholt; die MessageId verhindert, dass Fertiges doppelt entsteht.
            logger.error("Brevo-Webhook: Verarbeitung fehlgeschlagen", exc_info=True)
            return JsonResponse({'error': 'internal error'}, status=500)
        if len(ergebnisse) == 1:
            status, code = ergebnisse[0]
            return JsonResponse({'status': status}, status=code)
        return JsonResponse({'status': 'ok', 'items': [s for s, _c in ergebnisse]})
    return JsonResponse({'status': 'invalid method'}, status=405)
