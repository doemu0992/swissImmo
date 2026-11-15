"""Rundschreiben per E-Mail als EIN Ablauf — für den Knopf und für den Auftrag im Hintergrund.

Jede Mail geht einzeln über SMTP hinaus; bei vielen Empfängern reicht das Zeitlimit des Hosters nicht. Deshalb kann der
Versand ein Auftrag werden (`core/services/auftraege.py`, Art `rundschreiben`).

KEINE MAIL DOPPELT: Ein abgestürzter Auftrag wird neu gestartet. `versenden` bekommt deshalb `erledigt` (IDs, an die
schon gesendet wurde) und meldet jede gelungene Mail sofort über `nach_jedem`; der Auftrag schreibt das in seine
Parameter. Der Neustart überspringt die Erledigten.
"""
from django.conf import settings

#: Ab so vielen Empfängern geht der Versand IMMER in den Hintergrund (siehe `mahnlauf_lauf.SCHWELLE_HINTERGRUND`).
SCHWELLE_HINTERGRUND = 30


def schwelle():
    return getattr(settings, 'RUNDSCHREIBEN_SCHWELLE_HINTERGRUND', SCHWELLE_HINTERGRUND)


def im_hintergrund(anzahl):
    return anzahl >= schwelle()


def versenden(betreff, text, mieter_ids, benutzer=None, erledigt=(), nach_jedem=None):
    """Schickt die Mitteilung an jeden Mieter mit E-Mail-Adresse und trägt sie ins Kommunikationsjournal ein.

    Gibt die Zahl der in DIESEM Aufruf versandten Mails zurück. Läuft im gesetzten Mandantenkontext: Eine fremde
    Mieter-ID findet der gefilterte Manager nicht und wird übergangen."""
    from core.utils.email_service import journal_email, send_ticket_email
    from crm.models import Mieter
    schon = {int(i) for i in erledigt}
    gesendet = 0
    for mid in mieter_ids:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            continue
        if mid in schon:
            continue
        m = Mieter.objects.filter(id=mid).first()
        if m and m.email and send_ticket_email(m.email, betreff, text):
            gesendet += 1
            schon.add(mid)
            journal_email(betreff, text, mieter=m, user=benutzer, empfaenger=m.email)
            if nach_jedem is not None:
                nach_jedem(mid)
    return gesendet
