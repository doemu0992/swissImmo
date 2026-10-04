"""Anfragen von Stockwerkeigentümern: erfassen, beantworten, erledigen."""

import logging

from django.core.mail import send_mail
from django.utils import timezone

from core.models import Pendenz
from core.services.dokumentsprache import in_sprache
from stweg.aufgaben import PREFIX, erledigen
from stweg.models import StwegAnfrage



logger = logging.getLogger(__name__)


class AnfrageFehler(ValueError):
    pass


def anfrage_erfassen(liegenschaft, betreff, text='', *, einheit=None, eigentuemer=None,
                     kanal='portal', faellig_am=None, user=None):
    """Legt die Anfrage an und eine Pendenz «beantworten» dazu."""
    if not liegenschaft.ist_stweg:
        raise AnfrageFehler('Anfragen gibt es nur bei STWEG-Liegenschaften.')
    if einheit is not None and einheit.liegenschaft_id != liegenschaft.pk:
        raise AnfrageFehler('Die Einheit gehört nicht zu dieser Gemeinschaft.')
    if eigentuemer is None and einheit is not None:
        eigentuemer = einheit.stockwerkeigentuemer
    a = StwegAnfrage.objects.create(
        liegenschaft=liegenschaft, einheit=einheit, eigentuemer=eigentuemer,
        betreff=betreff[:200], text=text, kanal=kanal, faellig_am=faellig_am)
    Pendenz.objects.create(
        liegenschaft=liegenschaft, titel=f'Anfrage beantworten: {betreff}'[:200],
        beschreibung=text, kategorie='aufgabe', faellig_am=faellig_am,
        quelle=f'{PREFIX}anfrage:{a.pk}', erstellt_von=user)
    return a


def _pendenz(anfrage):
    return Pendenz.objects.filter(liegenschaft=anfrage.liegenschaft,
                                  quelle=f'{PREFIX}anfrage:{anfrage.pk}').first()


def in_bearbeitung(anfrage):
    anfrage.status = StwegAnfrage.IN_BEARBEITUNG
    anfrage.save(update_fields=['status'])
    return anfrage


def beantworten(anfrage, antwort, *, per_mail=True):
    """Hält die Antwort fest, schliesst die Pendenz und schickt sie dem Eigentümer."""
    if not antwort.strip():
        raise AnfrageFehler('Die Antwort darf nicht leer sein.')
    anfrage.antwort = antwort
    anfrage.status = StwegAnfrage.BEANTWORTET
    anfrage.beantwortet_am = timezone.now()
    anfrage.save(update_fields=['antwort', 'status', 'beantwortet_am'])
    p = _pendenz(anfrage)
    if p and not p.erledigt:
        erledigen(p)
    gesendet = False
    eig = anfrage.eigentuemer
    if per_mail and eig is not None and eig.email:
        from core.utils.email_service import send_via_hoststar
        from tickets.workflow import reply_to
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {eig.firma_oder_name}</p>"
                f"<p>zu Ihrer Anfrage «{anfrage.betreff}»:</p>"
                f"<p style='white-space:pre-line'>{antwort}</p>"
                f"<p>Freundliche Grüsse<br>{anfrage.liegenschaft.organisation.firma}</p></body></html>")
        with in_sprache('de'):          # Auskunft der Verwaltung bleibt deutsch (D11, ungeprüft)
            gesendet = send_via_hoststar(eig.email, f'Ihre Anfrage: {anfrage.betreff}', html,
                                         reply_to=reply_to(anfrage))
    return gesendet


def erledigt(anfrage):
    anfrage.status = StwegAnfrage.ERLEDIGT
    anfrage.save(update_fields=['status'])
    p = _pendenz(anfrage)
    if p and not p.erledigt:
        erledigen(p)
    return anfrage


def verwaltung_empfaenger(liegenschaft):
    """Wer von einer neuen Portal-Anfrage erfährt: die betreuende Person der Liegenschaft,
    sonst die Adresse der Verwaltung. Leer, wenn beides fehlt."""
    zustaendig = liegenschaft.betreut_von
    if zustaendig is not None and zustaendig.email:
        return [zustaendig.email]
    org = liegenschaft.organisation
    return [org.email] if org.email else []


def verwaltung_benachrichtigen(anfrage):
    """Schickt der Verwaltung einen Hinweis auf eine neue Anfrage; True, wenn er rausging.

    Die Anfrage selbst ist schon gespeichert und als Pendenz sichtbar — die Mail ist nur
    der Hinweis. Ihr Scheitern (oder eine fehlende Adresse) darf die Anfrage nicht verlieren,
    wird aber protokolliert statt verschluckt."""
    empfaenger = verwaltung_empfaenger(anfrage.liegenschaft)
    if not empfaenger:
        logger.warning('STWEG-Anfrage %s: keine Empfängeradresse (weder betreuende Person noch '
                       'Verwaltung) — die Anfrage steht nur in den offenen Punkten.', anfrage.pk)
        return False
    ein = anfrage.einheit
    wer = anfrage.eigentuemer.firma_oder_name if anfrage.eigentuemer_id else 'unbekannt'
    try:
        send_mail(f'Neue STWEG-Anfrage: {anfrage.betreff}',
                  f'{wer} ({ein.bezeichnung if ein else "—"}, {anfrage.liegenschaft}):\n\n{anfrage.text}',
                  None, empfaenger, fail_silently=False)
    except Exception:                                                   # noqa: BLE001
        logger.warning('Benachrichtigung zur STWEG-Anfrage %s fehlgeschlagen', anfrage.pk, exc_info=True)
        return False
    return True
