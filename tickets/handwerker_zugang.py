# tickets/handwerker_zugang.py
"""Der geheime Link je Handwerkerauftrag (Modul 3, Entscheid E6).

WAS DER LINK IST

Ein Handwerker bekommt kein Konto. Er bekommt je Auftrag einen Link
`/auftrag/<token>/`, der genau diesen einen Auftrag öffnet. Der Token sind 32
Zufallsbytes (`secrets.token_urlsafe(32)`). In der Datenbank steht nur sein
SHA-256 — wer die Tabelle liest, kann damit keinen Link bauen. Der Klartext
existiert genau zweimal: in der Auftrags-Mail und auf der Seite, die ihn nach
«neu erzeugen» einmal anzeigt.

WIE LANGE ER GILT (E6)

Solange der Auftrag offen ist, ohne Ablauf. Mit dem Abschluss — Auftrag
«erledigt» oder «storniert», bzw. Ticket «erledigt» — wird er nur noch lesend
und läuft 30 Tage später ab (`token_gueltig_bis`). Widerrufen lässt er sich
jederzeit im Reiter «Handwerker» des Schadens; ein neu erzeugter Link ersetzt
den alten.

FAIL-CLOSED

Ein abgeschlossener Auftrag ohne `token_gueltig_bis` gilt als abgelaufen. Das
kann nur entstehen, wenn ein Weg den Auftrag schliesst, ohne `abschluss_vermerken`
aufzurufen — dann lieber ein toter Link als ein ewig offener.
"""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

#: E6: so lange bleibt der Link nach dem Abschluss lesbar.
ZUGANG_NACH_ABSCHLUSS = timedelta(days=30)

#: Status, mit denen ein Auftrag abgeschlossen ist (tickets/workflow.py).
ABGESCHLOSSEN = ('erledigt', 'storniert')

#: `token_urlsafe(32)` ergibt 43 Zeichen aus [A-Za-z0-9_-]. Alles andere wird
#: gar nicht erst gehasht und gesucht.
_TOKEN_FORM = re.compile(r'^[A-Za-z0-9_-]{32,64}$')


def token_hash(token):
    """SHA-256 (hex) des Klartext-Tokens — das, was in der Datenbank steht."""
    return hashlib.sha256((token or '').encode('ascii', 'ignore')).hexdigest()


def ist_abgeschlossen(auftrag):
    """Ist der Auftrag abgeschlossen? Dann ist der Zugang nur noch lesend."""
    if auftrag.status in ABGESCHLOSSEN:
        return True
    return getattr(auftrag.ticket, 'status', None) == 'erledigt'


def link_url(token):
    """Absolute Adresse des Links. `PORTAL_BASE_URL` statt Host der Anfrage —
    die Mail liegt beim Handwerker, auch wenn sie aus einer internen Adresse
    heraus verschickt wurde (wie `generate_hallway_poster`)."""
    basis = (getattr(settings, 'PORTAL_BASE_URL', '') or '').rstrip('/')
    return basis + reverse('handwerker_auftrag', args=[token])


def link_erzeugen(auftrag):
    """Neuen Token setzen (ersetzt einen alten) und den Klartext zurückgeben.

    Für einen schon abgeschlossenen Auftrag beginnt die 30-Tage-Frist neu: Wer
    einen Link bewusst neu erzeugt, will ihn dem Handwerker jetzt geben.
    """
    token = secrets.token_urlsafe(32)
    auftrag.token_hash = token_hash(token)
    auftrag.token_widerrufen_am = None
    auftrag.token_gueltig_bis = (timezone.now() + ZUGANG_NACH_ABSCHLUSS
                                 if ist_abgeschlossen(auftrag) else None)
    auftrag.save(update_fields=['token_hash', 'token_widerrufen_am', 'token_gueltig_bis'])
    return token


def link_widerrufen(auftrag):
    """Link sofort ungültig machen. Der Hash bleibt stehen, damit die Akte
    zeigen kann, dass und wann widerrufen wurde."""
    if not auftrag.token_hash or auftrag.token_widerrufen_am:
        return False
    auftrag.token_widerrufen_am = timezone.now()
    auftrag.save(update_fields=['token_widerrufen_am'])
    return True


def abschluss_vermerken(auftraege):
    """Beim Abschluss: Lesefrist von 30 Tagen setzen, wo ein Link besteht.

    Nimmt ein QuerySet (Massenabschluss in `SchadenMeldung.save`) oder einen
    einzelnen Auftrag. Eine schon gesetzte Frist bleibt.
    """
    bis = timezone.now() + ZUGANG_NACH_ABSCHLUSS
    if hasattr(auftraege, 'filter'):
        auftraege.filter(token_hash__isnull=False, token_gueltig_bis__isnull=True).update(
            token_gueltig_bis=bis)
        return
    if auftraege.token_hash and auftraege.token_gueltig_bis is None:
        auftraege.token_gueltig_bis = bis


def link_status(auftrag):
    """Für die Akte: 'kein', 'aktiv', 'lesend', 'abgelaufen' oder 'widerrufen'."""
    if not auftrag.token_hash:
        return 'kein'
    if auftrag.token_widerrufen_am:
        return 'widerrufen'
    if ist_abgeschlossen(auftrag):
        bis = auftrag.token_gueltig_bis
        if bis is None or bis < timezone.now():
            return 'abgelaufen'
        return 'lesend'
    return 'aktiv'


def auftrag_zum_token(token):
    """Der Auftrag zu einem Klartext-Token — oder `None`, ohne Unterschied warum.

    `alle_organisationen` an genau dieser Stelle: Die Anfrage kommt ohne
    Anmeldung, es gibt keinen Mandantenkontext, und gesucht wird über den
    Hash, der global eindeutig ist. Der Aufrufer arbeitet danach im Kontext
    des gefundenen Auftrags weiter (`kontext_des_objekts`).
    """
    from .models import HandwerkerAuftrag

    if not token or not _TOKEN_FORM.match(token):
        return None
    h = token_hash(token)
    auftrag = (HandwerkerAuftrag.alle_organisationen
               .select_related('ticket__liegenschaft', 'ticket__betroffene_einheit',
                               'ticket__organisation', 'handwerker')
               .filter(token_hash=h).first())
    if auftrag is None or not hmac.compare_digest(auftrag.token_hash or '', h):
        return None
    if link_status(auftrag) not in ('aktiv', 'lesend'):
        return None
    return auftrag
