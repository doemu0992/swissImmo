# tickets/erinnerungen.py
"""Automatische Erinnerungen im Ticket-Ablauf.

Drei Fälle, je mit Abstand und Obergrenze — ein Ticket soll nachfassen, nicht
nerven:

* **Auftrag ohne Rückmeldung**: Handwerker beauftragt, kein Termin, keine
  Antwort -> Erinnerung an den Handwerker.
* **Rechnung fehlt**: Ticket «Wartet auf Rechnung» -> Erinnerung an den
  Handwerker, die Rechnung zu senden.
* **Mieter schweigt**: Ticket «Warte auf Mieter» -> Erinnerung an den Melder.

Jede gesendete Erinnerung steht als interne Systemnotiz mit Marke
``[Erinnerung:<art>]`` im Verlauf; daran werden Abstand und Obergrenze
gezählt (kein zusätzliches Feld, nichts, was auseinanderlaufen kann).
Nach der Obergrenze bleibt es bei der Pendenz (``auto:rechnung:``/
``auto:ticket:`` in ``core/services/automation.py``) — dann ist ein Mensch dran.

Läuft im Kontext einer Verwaltung (``taeglicher_lauf``); ``heute`` ist
injizierbar, damit Tests die Zeit nicht abwarten müssen.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

#: art -> (Tage bis zur ersten Erinnerung, Abstand, Obergrenze)
REGELN = {
    'auftrag': (3, 3, 3),
    'rechnung': (7, 7, 3),
    'mieter': (5, 5, 2),
}


def _marke(art):
    return f'[Erinnerung:{art}]'


def _bisherige(ticket, art):
    """(Anzahl, Zeitpunkt der letzten) Erinnerungen dieser Art am Ticket."""
    n = list(ticket.nachrichten.filter(typ='system', nachricht__startswith=_marke(art))
             .order_by('-erstellt_am').values_list('erstellt_am', flat=True))
    return len(n), (n[0] if n else None)


def _faellig(ticket, art, seit, jetzt):
    """Ist eine Erinnerung der Art fällig? ``seit`` = Beginn des Wartens."""
    erste, abstand, maximum = REGELN[art]
    anzahl, letzte = _bisherige(ticket, art)
    if anzahl >= maximum:
        return False
    bezug = letzte or seit
    wartezeit = timedelta(days=abstand if letzte else erste)
    return jetzt - bezug >= wartezeit


def _vermerken(ticket, art, empfaenger, ok, jetzt):
    """Systemnotiz mit dem Zeitpunkt des Laufs (``jetzt``), nicht dem der Uhr:
    Abstand und Deckel rechnen mit demselben Zeitbezug wie die Fälligkeit."""
    from .models import TicketNachricht
    n = TicketNachricht.objects.create(
        ticket=ticket, absender_name='System', typ='system', is_intern=True,
        nachricht=f"{_marke(art)} an {empfaenger} {'gesendet' if ok else 'NICHT gesendet'}.")
    TicketNachricht.objects.filter(pk=n.pk).update(erstellt_am=jetzt)    # auto_now_add


def erinnerungen_senden(jetzt=None):
    """Alle fälligen Erinnerungen der aktuellen Verwaltung senden.

    Gibt ``dict(art -> Anzahl gesendet)`` zurück. Einzelne Fehler werden
    protokolliert und stoppen den Lauf nicht.
    """
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from .models import HandwerkerAuftrag, SchadenMeldung
    from .workflow import melder_adresse, reply_to

    jetzt = jetzt or timezone.now()
    gesendet = {'auftrag': 0, 'rechnung': 0, 'mieter': 0}

    # 1) Aufträge ohne Rückmeldung (kein Termin, keine Antwort des Handwerkers)
    offen = (HandwerkerAuftrag.objects.filter(status='offen', termin_status='offen')
             .exclude(ticket__status='erledigt')
             .select_related('ticket', 'handwerker'))
    for a in offen:
        t = a.ticket
        if not a.handwerker.email:
            continue
        hat_geantwortet = t.nachrichten.filter(
            typ='handwerker_mail', empfaenger_handwerker=a.handwerker,
            is_von_verwaltung=False).exists()
        if hat_geantwortet or not _faellig(t, 'auftrag', a.beauftragt_am, jetzt):
            continue
        try:
            betreff, text = vorlage_text('ticket_erinnerung_handwerker', t, handwerker=a.handwerker)
            ok = send_ticket_email(a.handwerker.email, betreff, text, reply_to=reply_to(t))
        except Exception:
            logger.exception("Erinnerung (Auftrag) zu Ticket #%s fehlgeschlagen", t.pk)
            ok = False
        _vermerken(t, 'auftrag', a.handwerker.firma, ok, jetzt)
        gesendet['auftrag'] += int(bool(ok))

    # 2) Rechnung fehlt
    for t in SchadenMeldung.objects.filter(status='wartet_auf_rechnung'):
        if not _faellig(t, 'rechnung', t.aktualisiert_am, jetzt):
            continue
        for a in t.handwerker_auftraege.filter(kreditoren_rechnung__isnull=True) \
                .exclude(status='storniert').select_related('handwerker'):
            if not a.handwerker.email:
                continue
            try:
                betreff, text = vorlage_text('ticket_erinnerung_rechnung', t, handwerker=a.handwerker)
                ok = send_ticket_email(a.handwerker.email, betreff, text, reply_to=reply_to(t))
            except Exception:
                logger.exception("Erinnerung (Rechnung) zu Ticket #%s fehlgeschlagen", t.pk)
                ok = False
            _vermerken(t, 'rechnung', a.handwerker.firma, ok, jetzt)
            gesendet['rechnung'] += int(bool(ok))

    # 3) Mieter schweigt
    for t in SchadenMeldung.objects.filter(status='warte_auf_mieter').select_related('gemeldet_von'):
        adresse = melder_adresse(t)
        if not adresse or not _faellig(t, 'mieter', t.aktualisiert_am, jetzt):
            continue
        try:
            betreff, text = vorlage_text('ticket_erinnerung_mieter', t)
            ok = send_ticket_email(adresse, betreff, text, reply_to=reply_to(t))
        except Exception:
            logger.exception("Erinnerung (Mieter) zu Ticket #%s fehlgeschlagen", t.pk)
            ok = False
        _vermerken(t, 'mieter', 'Melder', ok, jetzt)
        gesendet['mieter'] += int(bool(ok))

    return gesendet
