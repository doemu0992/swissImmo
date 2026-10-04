"""Anfragen von Stockwerkeigentümern: erfassen, beantworten, erledigen."""

from django.utils import timezone

from core.models import Pendenz
from core.services.dokumentsprache import in_sprache
from stweg.aufgaben import PREFIX, erledigen
from stweg.models import StwegAnfrage



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
