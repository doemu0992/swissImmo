# tickets/direktkanal.py
"""Direktkanal Mieter <-> Handwerker je Auftrag (Chat UND Mail, gleichwertig).

DIE VERWALTUNG IST KEIN VERMITTLER. Mieter und Handwerker stimmen sich direkt ab, auch den Termin
(`tickets/termin_abstimmung.py`). Jede Nachricht steht als ``TicketNachricht(typ='direkt')`` am Auftrag
und ist damit im Mieterportal, auf der Auftragsseite des Handwerkers und im Verlauf der Verwaltung
(Mitleser) sichtbar.

BEIDE KANÄLE SIND SYNCHRON
* **Chat -> Mail:** Wer im Portal bzw. auf der Auftragsseite schreibt, dessen Gegenseite bekommt dieselbe
  Nachricht per Mail (Text + Link zum Chat). Eine Nachricht existiert nie nur in einem Kanal.
* **Mail -> Chat -> Mail:** Wer auf eine solche Mail antwortet, landet im Chat (``aus_mail``) und die
  Gegenseite bekommt wieder eine Mail.
* Die Zuordnung der Mail läuft über den Betreff: ``Ticket #<id>`` wie bisher plus die Auftragsmarke
  ``[A<auftrag-id>]``. Die Antwortadresse bleibt das Postfach der Verwaltung (ein Postfach je Verwaltung,
  ``fetch_replies``): die Mail nennt die Adresse der Gegenseite nie.

SCHUTZ VOR SCHLEIFEN UND FLUT
* Der Absender bekommt seine Nachricht nie zurück (Empfänger ist immer die Gegenseite).
* Weitergeleitete Mails tragen ``X-Immoswiss-Bridge`` und ``Auto-Submitted: auto-generated``; kommen
  sie (oder eine Abwesenheitsnotiz, ein Mailer-Daemon, die eigene Absenderadresse) zurück, wird nichts
  weitergeleitet (``automatisch``).
* **Bündelung:** Die erste Nachricht geht sofort per Mail. Weitere Nachrichten derselben Seite innerhalb
  von ``BUENDELUNG`` (5 Minuten) nach der letzten Mail warten und gehen gesammelt in EINER Mail hinaus —
  spätestens, wenn ``fetch_replies`` (jede Minute) ``ausstehende_zustellen`` aufruft.
* Die Verwaltung wird durch den Direktkanal NICHT per Mail benachrichtigt. Sie liest im Verlauf mit.
  (Nur «Termin steht» / Absage: ``termin_abstimmung``.)
"""
import logging
import re
from datetime import timedelta
from email.utils import parseaddr

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services.dokumentsprache import STANDARD, in_sprache

logger = logging.getLogger(__name__)

SEITEN = ('mieter', 'handwerker', 'verwaltung')
#: Längenlimit einer Nachricht (Chat). Mail-Antworten werden auf diese Länge gekürzt.
MAX_LAENGE = 2000
#: Mindestabstand zwischen zwei Mails derselben Seite an die Gegenseite.
BUENDELUNG = timedelta(minutes=5)
#: So lange gilt der signierte Link (Chat/Termin ohne Anmeldung).
LINK_GUELTIG_SEKUNDEN = 30 * 24 * 3600
_SALT = 'direktkanal-link'
_MARKE = re.compile(r'\[A(\d+)\]')
KOPF_BRUECKE = 'X-Immoswiss-Bridge'

_AUTOMATISCHE_ABSENDER = ('mailer-daemon', 'postmaster', 'noreply', 'no-reply', 'donotreply', 'do-not-reply')


# --- Kennungen ---------------------------------------------------------------------------------------

def marke(auftrag):
    return f'[A{auftrag.pk}]'


def auftrag_id_aus_betreff(betreff):
    """Die Auftragsnummer aus ``[A12]`` im Betreff, sonst ``None``."""
    m = _MARKE.search(betreff or '')
    return int(m.group(1)) if m else None


def betreff_fuer(auftrag, titel=None):
    t = auftrag.ticket
    return f"{titel or t.titel} (Ticket #{t.pk}) {marke(auftrag)}"


# --- Signierter Link (ohne Anmeldung) ------------------------------------------------------------------

def link_token(auftrag, seite):
    """Signierter Zugang für ``seite`` ('mieter' oder 'handwerker') zum Chat dieses Auftrags."""
    if seite not in ('mieter', 'handwerker'):
        raise ValueError(seite)
    return signing.dumps({'a': auftrag.pk, 'w': seite}, salt=_SALT, compress=False)


def link_url(auftrag, seite):
    basis = (getattr(settings, 'PORTAL_BASE_URL', '') or '').rstrip('/')
    return basis + reverse('direkt_link', args=[link_token(auftrag, seite)])


def auftrag_aus_link(signiert):
    """``(auftrag, seite)`` zu einem signierten Link — oder ``None`` (ungültig, abgelaufen, widerrufen).

    ``alle_organisationen`` an genau dieser Stelle: Die Anfrage kommt ohne Anmeldung; die Signatur ist der
    Schlüssel. Der Aufrufer arbeitet danach im Kontext des Auftrags (``kontext_des_objekts``). Ein
    widerrufener Handwerker-Link (``token_widerrufen_am``) sperrt auch diesen Zugang."""
    from .models import HandwerkerAuftrag
    try:
        daten = signing.loads(signiert or '', salt=_SALT, max_age=LINK_GUELTIG_SEKUNDEN)
        pk, seite = int(daten['a']), daten['w']
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        return None
    if seite not in ('mieter', 'handwerker'):
        return None
    auftrag = (HandwerkerAuftrag.alle_organisationen
               .select_related('ticket__liegenschaft', 'ticket__betroffene_einheit', 'ticket__organisation',
                               'ticket__gemeldet_von', 'handwerker')
               .filter(pk=pk).first())
    if auftrag is None:
        return None
    if seite == 'handwerker' and auftrag.token_widerrufen_am:
        return None
    return auftrag, seite


# --- Namen und Adressen --------------------------------------------------------------------------------

def mieter_name(ticket):
    if ticket.gemeldet_von_id:
        return ticket.gemeldet_von.display_name
    return f"{ticket.melder_vorname or ''} {ticket.melder_nachname or ''}".strip() or 'Mieter'


def seiten_name(auftrag, seite):
    if seite == 'handwerker':
        return auftrag.handwerker.firma
    if seite == 'mieter':
        return mieter_name(auftrag.ticket)
    return 'Verwaltung'


def seiten_adresse(auftrag, seite):
    from .workflow import melder_adresse
    if seite == 'handwerker':
        return (auftrag.handwerker.email or '').strip()
    if seite == 'mieter':
        return (melder_adresse(auftrag.ticket) or '').strip()
    return ''


def ist_offen(auftrag):
    """Schreiben ist nur bei offenem Auftrag möglich (wie die Auftragsseite: danach nur lesend)."""
    from .handwerker_zugang import ist_abgeschlossen
    return not ist_abgeschlossen(auftrag)


def verlauf(auftrag):
    """Der Chat dieses Auftrags, älteste zuerst. Im Mandantenkontext des Auftrags aufrufen."""
    from .models import TicketNachricht
    return (TicketNachricht.objects.filter(ticket_id=auftrag.ticket_id, auftrag=auftrag, typ='direkt')
            .order_by('erstellt_am', 'pk'))


# --- Schreiben (Chat und Mail landen hier) ---------------------------------------------------------------

def schreiben(auftrag, seite, text, name=None, jetzt=None, zustellen=True):
    """Eine Nachricht im Direktkanal ablegen und der Gegenseite per Mail zustellen.

    ``seite``: wer schreibt. Die Berechtigung (richtiger Mieter, gültiger Token, Rolle) prüft der
    Aufrufer; hier wird nur Inhalt und Zustand geprüft. Der Eintrag ist intern (``is_intern``): Er
    erscheint nicht im allgemeinen Verlauf des Mieters, sondern nur im Chat — und ungelesen-Badge der
    Verwaltung bleibt aus (``gelesen=True``)."""
    from .models import TicketNachricht
    if seite not in SEITEN:
        raise ValidationError(_('Unbekannter Absender.'), code='seite')
    text = (text or '').strip()
    if not text:
        raise ValidationError(_('Bitte eine Nachricht eingeben.'), code='leer')
    if len(text) > MAX_LAENGE:
        raise ValidationError(_('Die Nachricht ist zu lang (höchstens %(n)s Zeichen).') % {'n': MAX_LAENGE},
                              code='zu_lang')
    if not ist_offen(auftrag):
        raise ValidationError(_('Der Auftrag ist abgeschlossen — der Chat ist nur noch lesbar.'),
                              code='geschlossen')
    n = TicketNachricht.objects.create(
        ticket=auftrag.ticket, auftrag=auftrag, typ='direkt', seite=seite,
        absender_name=(name or seiten_name(auftrag, seite))[:100], nachricht=text,
        is_intern=True, is_von_verwaltung=(seite == 'verwaltung'), gelesen=True)
    if zustellen:
        zustellung_pruefen(auftrag, seite, jetzt=jetzt)
    return n


# --- Zustellung per Mail (mit Bündelung) -------------------------------------------------------------------

def zustellung_pruefen(auftrag, seite, jetzt=None):
    """Noch nicht zugestellte Nachrichten von ``seite`` als EINE Mail an die Gegenseite senden —
    sofern die letzte Mail dieser Seite länger als ``BUENDELUNG`` her ist. Gibt True zurück, wenn gesendet."""
    from .models import TicketNachricht
    jetzt = jetzt or timezone.now()
    basis = TicketNachricht.objects.filter(ticket_id=auftrag.ticket_id, auftrag=auftrag, typ='direkt', seite=seite)
    offen = list(basis.filter(zugestellt_am__isnull=True).order_by('erstellt_am', 'pk'))
    if not offen:
        return False
    if seite != 'verwaltung':
        letzte = (basis.filter(zugestellt_am__isnull=False).order_by('-zugestellt_am')
                  .values_list('zugestellt_am', flat=True).first())
        if letzte and jetzt - letzte < BUENDELUNG:
            return False
    ids = [n.pk for n in offen]
    # Beanspruchen, bevor gesendet wird: zwei gleichzeitige Läufe senden nicht doppelt.
    if basis.filter(pk__in=ids, zugestellt_am__isnull=True).update(zugestellt_am=jetzt) != len(ids):
        basis.filter(pk__in=ids).update(zugestellt_am=jetzt)
        return False
    ziele = ('mieter', 'handwerker') if seite == 'verwaltung' else (
        'handwerker' if seite == 'mieter' else 'mieter',)
    alle_ok = True
    for ziel in ziele:
        adresse = seiten_adresse(auftrag, ziel)
        if not adresse:
            logger.info("Direktkanal Auftrag #%s: %s ohne E-Mail-Adresse, Nachricht nur im Chat",
                        auftrag.pk, ziel)
            continue
        if not _mail_senden(auftrag, seite, ziel, adresse, offen):
            alle_ok = False
    if not alle_ok:
        # Nochmals versuchen (nächster Lauf von fetch_replies bzw. nächste Nachricht).
        basis.filter(pk__in=ids).update(zugestellt_am=None)
        return False
    return True


def ausstehende_zustellen(jetzt=None):
    """Alle gebündelten Nachrichten der aktuellen Verwaltung zustellen, deren Fenster vorbei ist.
    Läuft im Mandantenkontext (``fetch_replies``). Gibt die Zahl der gesendeten Mails zurück."""
    from .models import HandwerkerAuftrag, TicketNachricht
    paare = list(TicketNachricht.objects.filter(typ='direkt', zugestellt_am__isnull=True, auftrag__isnull=False)
                 .values_list('auftrag_id', 'seite').distinct())
    gesendet = 0
    for auftrag_id, seite in paare:
        auftrag = (HandwerkerAuftrag.objects.select_related('ticket__gemeldet_von', 'handwerker')
                   .filter(pk=auftrag_id).first())
        if auftrag is None:
            continue
        try:
            gesendet += int(zustellung_pruefen(auftrag, seite, jetzt=jetzt))
        except Exception:
            logger.exception("Direktkanal: Zustellung zu Auftrag #%s fehlgeschlagen", auftrag_id)
    return gesendet


def _mail_senden(auftrag, von_seite, ziel, adresse, nachrichten):
    from core.services.ticket_workflow import melder_gruss, melder_sprache
    from core.services.anrede import handwerker_gruss
    from core.utils.email_service import _klartext_als_html, send_via_hoststar
    from .workflow import reply_to
    ticket = auftrag.ticket
    link = link_url(auftrag, ziel)
    texte = '\n\n'.join(n.nachricht for n in nachrichten)
    wer = nachrichten[-1].absender_name
    sprache = melder_sprache(ticket) if ziel == 'mieter' else STANDARD
    try:
        with in_sprache(sprache):
            if ziel == 'mieter':
                gruss = melder_gruss(ticket)
                inhalt = _("%(gruss)s\n\n%(wer)s schreibt zu «%(schaden)s»:\n\n%(text)s\n\n"
                           "Sie können direkt auf diese Mail antworten — Ihre Antwort geht an den "
                           "Handwerker. Oder öffnen Sie den Chat:\n%(link)s") % {
                    'gruss': gruss, 'wer': wer, 'schaden': ticket.titel, 'text': texte, 'link': link}
            else:
                gruss = handwerker_gruss(auftrag.handwerker)
                inhalt = _("%(gruss)s\n\n%(wer)s schreibt zu «%(schaden)s»:\n\n%(text)s\n\n"
                           "Sie können direkt auf diese Mail antworten — Ihre Antwort geht an den "
                           "Mieter. Oder öffnen Sie den Chat:\n%(link)s") % {
                    'gruss': gruss, 'wer': wer, 'schaden': ticket.titel, 'text': texte, 'link': link}
            betreff = betreff_fuer(auftrag)
        html = ("<html><body style='font-family:Arial,sans-serif'>"
                + _klartext_als_html(inhalt).replace(link, f"<a href='{link}'>{link}</a>")
                + "</body></html>")
        return send_via_hoststar(
            adresse, betreff, html, reply_to=reply_to(ticket), organisation=ticket.organisation_id,
            absender_name=None if von_seite == 'verwaltung' else wer,
            headers={KOPF_BRUECKE: '1', 'Auto-Submitted': 'auto-generated'})
    except Exception:
        logger.exception("Direktkanal: Mail zu Auftrag #%s fehlgeschlagen", auftrag.pk)
        return False


# --- Eingehende Mail -> Chat ---------------------------------------------------------------------------

def automatisch(absender, kopf=None):
    """Ist die Mail eine automatische (Abwesenheitsnotiz, Mailer-Daemon, unsere eigene Weiterleitung)?
    ``kopf``: Mapping der Kopfzeilen (Gross-/Kleinschreibung egal)."""
    kopf = {str(k).lower(): str(v) for k, v in (kopf or {}).items()}
    if KOPF_BRUECKE.lower() in kopf:
        return True
    if kopf.get('auto-submitted', 'no').strip().lower() not in ('', 'no'):
        return True
    if 'x-autoreply' in kopf or 'x-autorespond' in kopf:
        return True
    if kopf.get('precedence', '').strip().lower() in ('bulk', 'junk', 'list', 'auto_reply'):
        return True
    if kopf.get('return-path', '').strip() == '<>':
        return True
    lokal = parseaddr(absender or '')[1].split('@')[0].strip().lower()
    return lokal in _AUTOMATISCHE_ABSENDER


def _eigene_adresse(adresse, ticket):
    from .workflow import reply_to
    eigene = {parseaddr(settings.DEFAULT_FROM_EMAIL)[1].strip().lower()}
    rt = reply_to(ticket)
    if rt:
        eigene.add(rt.strip().lower())
    return adresse in eigene


def aus_mail(ticket, auftrag_id, absender, inhalt, kopf=None, jetzt=None):
    """Eine Mail-Antwort mit Auftragsmarke in den Chat legen und der Gegenseite zustellen.

    Gibt ``'mieter'`` / ``'handwerker'`` (Seite des Absenders) zurück — oder ``None``, wenn die Mail
    NICHT weitergeleitet wird (keine Marke, kein Auftrag am Ticket, Auftrag geschlossen, automatische
    Mail, eigener Absender, unbekannter Absender). Dann gilt der bisherige Weg (Ticket-Verlauf)."""
    if not auftrag_id or automatisch(absender, kopf):
        return None
    auftrag = (ticket.handwerker_auftraege.select_related('handwerker', 'ticket__gemeldet_von')
               .filter(pk=auftrag_id).first())
    if auftrag is None or not ist_offen(auftrag):
        return None
    adresse = parseaddr(absender or '')[1].strip().lower()
    if not adresse or _eigene_adresse(adresse, ticket):
        return None
    if seiten_adresse(auftrag, 'handwerker').lower() == adresse:
        seite = 'handwerker'
    elif seiten_adresse(auftrag, 'mieter').lower() == adresse:
        seite = 'mieter'
    else:
        return None
    try:
        schreiben(auftrag, seite, (inhalt or '').strip()[:MAX_LAENGE], jetzt=jetzt)
    except ValidationError:
        return None
    return seite
