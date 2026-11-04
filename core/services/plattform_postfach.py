"""Das Plattform-Postfach: EIN Sammelpostfach beim Mailhoster statt Brevo (Variante A, kein neuer Anbieter).

DER WEG
Der Hoster legt das Catch-all der ``ANTWORT_DOMAIN`` auf ein Postfach (``eingang@immoswiss.app``): alles, was an
nicht vorhandene Adressen der Domain geht, landet dort; bestehende Adressen (info@, buchhaltung@ ...) haben
Vorrang und bleiben unberührt. ``fetch_plattform_eingang`` ruft dieses eine Postfach per IMAP ab. Jede Mail wird
über die EMPFÄNGERADRESSE einer Verwaltung zugeordnet (``antwort_eingang.zuordnung_zu_adresse``: Kennung, alte
Kennung im Fenster, Zweck antworten/rechnungen) und dann GENAU so verarbeitet wie beim Brevo-Webhook
(``eingehende_antwort_verarbeiten``, Rechnungs-Anhänge über ``belegimport.anhang_importieren``). Der Unterschied:
die Anhänge liegen in der Mail selbst, es braucht keinen API-Schlüssel.

Die Zugangsdaten stehen EINMAL in der ``.env`` (``PLATTFORM_IMAP_*``), nie je Verwaltung in der Datenbank.

WELCHE ADRESSE GILT (``empfaenger_adressen``)
Ein Catch-all-Postfach leitet lokal weiter; welche Kopfzeile den ursprünglichen Empfänger behält, hängt vom
Hoster ab. Darum werden ALLE Kandidaten gesammelt (``Delivered-To``, ``X-Original-To``, ``Envelope-To``,
``X-Envelope-To``, ``To``, ``Cc``, ``Resent-To``), klein geschrieben, und nur Adressen auf der ``ANTWORT_DOMAIN``
behalten. Jede wird zugeordnet; führen sie zu verschiedenen Verwaltungen oder Zwecken, ist die Mail mehrdeutig und
wird verworfen (wie im Webhook). Findet keine eine Verwaltung (Spam an erfundene Adressen, abgelaufene Kennung,
fremde Adresse), wird die Mail ignoriert: gelesen markiert, nichts angelegt, kein Hinweis.

WIEDERHOLEN, ABER NICHT EWIG
Gelesen wird erst NACH erfolgreicher Verarbeitung (``BODY.PEEK``, dann ``\\Seen``). Scheitert eine Mail, bleibt sie
ungelesen und der nächste Lauf versucht es noch einmal. ``core.PlattformMail`` zählt die Fehlversuche; ab
``MAX_VERSUCHE`` gilt sie als erledigt (``aufgegeben``), damit eine kaputte Mail den Abruf nicht ewig bremst. Das
steht im Serverprotokoll und, wenn die Verwaltung schon feststand, in deren Logbuch.

AUFRÄUMEN (``aufraeumen``)
Das Sammelpostfach darf nicht überlaufen. Gelöscht wird eine Mail erst, wenn ALLE drei Bedingungen gelten: gelesen,
älter als ``AUFBEWAHRUNG_TAGE`` Tage (IMAP ``BEFORE``) UND in ``core.PlattformMail`` als erledigt vermerkt, und
dieser Vermerk ist ebenfalls so alt. Was dieser Abruf nie angefasst hat (zum Beispiel eine Mail, die jemand im
Webmail gelesen hat) bleibt liegen. Gelöscht wird mit ``\\Deleted`` und ``EXPUNGE``; ein ``EXPUNGE`` entfernt im
Postfach alles, was als gelöscht markiert ist, auch von Hand im Webmail Markiertes.

ZEIT
Alle Zeiten kommen als ``jetzt`` herein (Vorgabe ``timezone.now()``), nichts rechnet mit der Uhr der Maschine.
"""
import hashlib
import imaplib
import logging
import re
import time
from datetime import timedelta
from email import message_from_bytes, policy
from email.utils import getaddresses

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.services.postfach_abruf import AbrufFehler, _schliessen

logger = logging.getLogger(__name__)

#: Nach so vielen fehlgeschlagenen Versuchen gilt eine Mail als erledigt (Poison-Schutz).
MAX_VERSUCHE = 5
#: Grösser als das wird nicht geladen, sondern ignoriert (Bytes).
MAX_MAIL_BYTES = 25 * 1024 * 1024
#: So lange bleiben bearbeitete und ignorierte Mails im Postfach, bevor sie gelöscht werden.
AUFBEWAHRUNG_TAGE = 14
#: Der Vermerk in ``PlattformMail`` wird nach so vielen Tagen entfernt (länger als die Aufbewahrung).
PROTOKOLL_TAGE = 90
#: Höchstens so viele Mails je Lauf; der Rest kommt beim nächsten Lauf. Hält einen Scheduler-Lauf kurz.
MAX_MAILS_JE_LAUF = 100
#: Ein Lauf beginnt keine neue Mail mehr, wenn er so lange gedauert hat (Sekunden).
LAUF_BUDGET_SEKUNDEN = 240
#: Wartezeit auf den Server (Verbindungsaufbau und jede Antwort).
ZEITLIMIT_SEKUNDEN = 60

EMPFAENGER_KOEPFE = ('Delivered-To', 'X-Original-To', 'Envelope-To', 'X-Envelope-To', 'To', 'Cc', 'Resent-To')
_MONATE = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


# --- Konfiguration und Status ----------------------------------------------------------------------------------

def konfiguration():
    """Die IMAP-Zugangsdaten aus der ``.env`` als Dict, oder ``None`` wenn nicht vollständig."""
    host = (getattr(settings, 'PLATTFORM_IMAP_HOST', '') or '').strip()
    benutzer = (getattr(settings, 'PLATTFORM_IMAP_BENUTZER', '') or '').strip()
    passwort = getattr(settings, 'PLATTFORM_IMAP_PASSWORT', '') or ''
    if not (host and benutzer and passwort):
        return None
    try:
        port = int(getattr(settings, 'PLATTFORM_IMAP_PORT', 993) or 993)
    except (TypeError, ValueError):
        port = 993
    return {'host': host, 'port': port, 'benutzer': benutzer, 'passwort': passwort,
            'ordner': (getattr(settings, 'PLATTFORM_IMAP_ORDNER', '') or 'INBOX').strip() or 'INBOX'}


def plattform_eingang_status():
    """Welche Kanäle für den Empfang der Plattformadressen eingerichtet sind.

    * ``brevo``: ``BREVO_WEBHOOK_SECRET`` gesetzt (Webhook nimmt Mails an)
    * ``imap``: alle ``PLATTFORM_IMAP_*`` gesetzt (``fetch_plattform_eingang`` kann abrufen)
    * ``eingerichtet``: mindestens einer; nur dann tragen Ticket-Mails die Plattformadresse als Reply-To
    * ``anhaenge_fehlen``: Brevo ist der EINZIGE Kanal und ``BREVO_API_KEY`` fehlt (nur dann lassen sich Anhänge
      nicht laden; über das Plattform-Postfach liegen sie in der Mail selbst)
    """
    brevo = bool(getattr(settings, 'BREVO_WEBHOOK_SECRET', None))
    imap = konfiguration() is not None
    api = bool((getattr(settings, 'BREVO_API_KEY', None) or '').strip())
    return {
        'brevo': brevo, 'imap': imap, 'brevo_api': api,
        'eingerichtet': brevo or imap,
        'anhaenge_fehlen': brevo and not imap and not api,
    }


# --- Zuordnung -------------------------------------------------------------------------------------------------

def empfaenger_adressen(msg):
    """Alle Adressen auf der ``ANTWORT_DOMAIN`` aus den Empfängerkopfzeilen (klein, ohne Doppelte)."""
    from core.services import antwort_eingang as ae
    adressen = set()
    for name in EMPFAENGER_KOEPFE:
        werte = [str(w) for w in (msg.get_all(name) or [])]
        for _anzeige, roh in getaddresses(werte):
            adresse = ae.rein_adresse(roh)
            if adresse and ae.ist_plattform_adresse(adresse):
                adressen.add(adresse)
    return adressen


def _kopfblock(roh):
    for trenner in (b'\r\n\r\n', b'\n\n'):
        i = roh.find(trenner)
        if i != -1:
            return roh[:i]
    return roh


def schluessel_aus_roh(roh):
    """Der Schlüssel einer Mail in ``PlattformMail``: Message-ID (ersatzweise Hash der Kopfzeilen) plus ein
    Kürzel der Plattform-Empfänger. Das Kürzel trennt Kopien DERSELBEN Mail an verschiedene Verwaltungen
    (Bcc: gleiche Message-ID, verschiedener Empfänger). Funktioniert mit der ganzen Mail und mit dem
    Kopfteil allein, deshalb gibt das Aufräumen denselben Schlüssel."""
    kopf = _kopfblock(roh)
    msg = message_from_bytes(kopf, policy=policy.default)
    mid = message_id(msg) or 'hash:' + hashlib.sha256(kopf).hexdigest()
    empf = ','.join(sorted(empfaenger_adressen(msg)))
    return f'{mid[:220]}#{hashlib.sha1(empf.encode()).hexdigest()[:12]}'


def message_id(msg):
    return str(msg.get('Message-ID') or '').strip().strip('<>').strip()[:255]


def ist_spam(msg):
    """Der Spamfilter des Hosters hat die Mail markiert."""
    if str(msg.get('X-Spam-Flag') or '').strip().lower() == 'yes':
        return True
    return str(msg.get('X-Spam-Status') or '').strip().lower().startswith('yes')


def _selbstantwort(msg):
    """Abwesenheitsmeldung oder Unzustellbarkeitsbericht: dafür legt niemand eine Rechnung an."""
    if str(msg.get('Auto-Submitted') or '').strip().lower() == 'auto-replied':
        return True
    return str(msg.get('Return-Path') or '').strip() == '<>'


def _text_und_html(msg):
    plain = html = ''
    for teil in msg.walk():
        if teil.is_multipart() or teil.get_filename():
            continue
        typ = teil.get_content_type()
        if typ not in ('text/plain', 'text/html'):
            continue
        try:
            inhalt = teil.get_content()
        except (LookupError, UnicodeError):
            nutzlast = teil.get_payload(decode=True) or b''
            inhalt = nutzlast.decode('utf-8', errors='ignore')
        if typ == 'text/plain' and not plain:
            plain = inhalt
        elif typ == 'text/html' and not html:
            html = inhalt
    return plain, html


def mail_verarbeiten(roh, schluessel, jetzt=None):
    """Eine Mail des Plattform-Postfachs einer Verwaltung zuordnen und verarbeiten.

    Gibt den Ausgang als Text zurück: ``'verarbeitet'`` oder ein Grund fürs Ignorieren (``'spam'``,
    ``'fremd'``, ``'mehrdeutig'``, ``'lesemodus'``, ``'doppelt'``, ``'ohne_ticket'``, ``'ohne_anhang'``).
    Wirft bei Fehlern der Verarbeitung; die Transaktion rollt dann alles zurück (auch den Eintrag in
    ``EingegangeneMail``), und der Abruf versucht es später noch einmal."""
    from core.funktionen import hintergrund_erlaubt
    from core.services import antwort_eingang as ae
    from core.tenancy import kontext_des_objekts
    from tickets.models import EingegangeneMail

    msg = message_from_bytes(roh, policy=policy.default)
    if ist_spam(msg):
        return 'spam'

    treffer = {}
    for adresse in empfaenger_adressen(msg):
        zuordnung = ae.zuordnung_zu_adresse(adresse, jetzt)
        if zuordnung is not None:
            treffer[adresse] = zuordnung
    if not treffer:
        return 'fremd'
    if len({o.pk for o, _z in treffer.values()}) > 1 or len({z for _o, z in treffer.values()}) > 1:
        logger.warning('Plattform-Postfach: Mail an mehrere Verwaltungen oder Adressen, verworfen')
        return 'mehrdeutig'
    organisation, zweck = next(iter(treffer.values()))

    absender = str(msg.get('From') or '')
    betreff = str(msg.get('Subject') or '')
    try:
        with kontext_des_objekts(organisation):
            if not hintergrund_erlaubt(organisation):
                logger.info('Plattform-Postfach: Verwaltung %s im Lesemodus, Mail nicht verarbeitet',
                            organisation.pk)
                return 'lesemodus'
            with transaction.atomic():
                _eintrag, neu = EingegangeneMail.objects.get_or_create(
                    message_id=(message_id(msg) or schluessel)[:255], defaults={'zweck': zweck})
                if not neu:
                    return 'doppelt'
                if zweck == ae.ZWECK_RECHNUNGEN:
                    if _selbstantwort(msg):
                        return 'ohne_anhang'
                    from core.services.rechnungseingang import rechnungsmail_aus_mail_verarbeiten
                    ausgang = rechnungsmail_aus_mail_verarbeiten(organisation, msg, absender, betreff, jetzt)
                    return 'verarbeitet' if ausgang.startswith('ok') else 'ohne_anhang'
                plain, html = _text_und_html(msg)
                text = ae.antworttext({'RawTextBody': plain, 'RawHtmlBody': html})
                kopf = {str(k): str(v) for k, v in msg.items()}
                ergebnis = ae.eingehende_antwort_verarbeiten(organisation, absender, betreff, text, kopf)
                return 'ohne_ticket' if ergebnis == 'ohne_ticket' else 'verarbeitet'
    except Exception as fehler:
        # Wer die Verwaltung war, soll der Poison-Schutz im Logbuch nennen können.
        fehler.plattform_info = (organisation, absender, betreff)
        raise


# --- Der Abruf -------------------------------------------------------------------------------------------------

def verbinden(konfig):
    """Angemeldete IMAP-Verbindung mit gewähltem Ordner. Wirft ``AbrufFehler`` mit einer Meldung OHNE
    Servernamen und Benutzer (jede Verwaltung sieht sie auf der Seite «E-Mail-Eingang»)."""
    try:
        verbindung = imaplib.IMAP4_SSL(konfig['host'], konfig['port'], timeout=ZEITLIMIT_SEKUNDEN)
    except Exception as fehler:                                # noqa: BLE001
        logger.warning('Plattform-Postfach: keine Verbindung zu %s:%s — %s', konfig['host'], konfig['port'], fehler)
        raise AbrufFehler(f'Keine Verbindung zum Plattform-Postfach ({type(fehler).__name__}).') from fehler
    try:
        verbindung.login(konfig['benutzer'], konfig['passwort'])
    except imaplib.IMAP4.error as fehler:
        _schliessen(verbindung)
        logger.warning('Plattform-Postfach: Anmeldung als %s abgelehnt — %s', konfig['benutzer'], fehler)
        raise AbrufFehler('Anmeldung am Plattform-Postfach abgelehnt. Benutzer und Passwort in der .env prüfen.'
                          ) from fehler
    try:
        status, _daten = verbindung.select(konfig['ordner'])
    except Exception as fehler:                                # noqa: BLE001
        _schliessen(verbindung)
        raise AbrufFehler(f'Der Ordner des Plattform-Postfachs liess sich nicht öffnen '
                          f'({type(fehler).__name__}).') from fehler
    if status != 'OK':
        _schliessen(verbindung)
        raise AbrufFehler('Der Ordner des Plattform-Postfachs wurde nicht gefunden (PLATTFORM_IMAP_ORDNER).')
    return verbindung


def _groesse(verbindung, kennung):
    """RFC822.SIZE in Byte, ``None`` wenn der Server keine nennt."""
    try:
        status, daten = verbindung.fetch(kennung, '(RFC822.SIZE)')
    except Exception:                                          # noqa: BLE001
        return None
    if status != 'OK':
        return None
    teile = []
    for eintrag in daten or []:
        teile.append(eintrag[0] if isinstance(eintrag, tuple) else eintrag)
    treffer = re.search(rb'RFC822\.SIZE\s+(\d+)', b' '.join(t for t in teile if isinstance(t, bytes)))
    return int(treffer.group(1)) if treffer else None


def _holen(verbindung, kennung, teil):
    """``teil``: ``'BODY.PEEK[]'`` (ganze Mail) oder ``'BODY.PEEK[HEADER]'``. PEEK, damit der Server nichts als
    gelesen markiert, bevor die Verarbeitung durch ist."""
    status, daten = verbindung.fetch(kennung, f'({teil})')
    if status != 'OK':
        raise AbrufFehler('Die Mail liess sich nicht abholen.')
    roh = next((t[1] for t in daten or [] if isinstance(t, tuple)), None)
    if roh is None:
        raise AbrufFehler('Die Antwort des Servers enthielt keine Mail.')
    return roh


def _gelesen(verbindung, kennung):
    try:
        verbindung.store(kennung, '+FLAGS', '\\Seen')
    except Exception:                                          # noqa: BLE001
        # Verarbeitet ist verarbeitet: bleibt das Flag aus, erkennt der nächste Lauf die Mail am Vermerk in
        # PlattformMail und setzt es dann.
        logger.warning('Plattform-Postfach: \\Seen liess sich nicht setzen')


def _erledigt(eintrag, ergebnis, jetzt):
    eintrag.ergebnis = ergebnis[:30]
    eintrag.erledigt_am = jetzt
    eintrag.save(update_fields=['ergebnis', 'erledigt_am'])


def _eine_mail(verbindung, kennung, jetzt):
    """Eine ungelesene Mail abholen und verarbeiten. Gibt ``(art, ausgang)`` zurück, ``art`` ist
    ``'verarbeitet'``, ``'ignoriert'`` oder ``'aufgegeben'``; wirft bei einem Fehler (Mail bleibt ungelesen)."""
    from core.models import PlattformMail

    groesse = _groesse(verbindung, kennung)
    if groesse is not None and groesse > MAX_MAIL_BYTES:
        eintrag, _neu = PlattformMail.objects.get_or_create(
            schluessel=schluessel_aus_roh(_holen(verbindung, kennung, 'BODY.PEEK[HEADER]')))
        _erledigt(eintrag, 'zu_gross', jetzt)
        _gelesen(verbindung, kennung)
        return 'ignoriert', 'zu_gross'

    roh = _holen(verbindung, kennung, 'BODY.PEEK[]')
    schluessel = schluessel_aus_roh(roh)
    eintrag, _neu = PlattformMail.objects.get_or_create(schluessel=schluessel)
    if eintrag.erledigt_am is not None:
        _gelesen(verbindung, kennung)
        return 'ignoriert', 'bereits'
    if len(roh) > MAX_MAIL_BYTES:
        _erledigt(eintrag, 'zu_gross', jetzt)
        _gelesen(verbindung, kennung)
        return 'ignoriert', 'zu_gross'

    try:
        ausgang = mail_verarbeiten(roh, schluessel, jetzt)
    except Exception as fehler:                                # noqa: BLE001
        eintrag.versuche += 1
        eintrag.letzter_fehler = f'{type(fehler).__name__}: {fehler}'[:300]
        eintrag.save(update_fields=['versuche', 'letzter_fehler'])
        logger.exception('Plattform-Postfach: Mail fehlgeschlagen (Versuch %s von %s)', eintrag.versuche,
                         MAX_VERSUCHE)
        if eintrag.versuche < MAX_VERSUCHE:
            raise
        _aufgeben(eintrag, fehler, jetzt)
        _gelesen(verbindung, kennung)
        return 'aufgegeben', 'aufgegeben'

    _erledigt(eintrag, ausgang, jetzt)
    _gelesen(verbindung, kennung)
    return ('verarbeitet' if ausgang == 'verarbeitet' else 'ignoriert'), ausgang


def _aufgeben(eintrag, fehler, jetzt):
    """Poison-Schutz: nach ``MAX_VERSUCHE`` gilt die Mail als erledigt. Serverprotokoll, und wenn die Verwaltung
    feststand, ein Eintrag in deren Logbuch (ohne Inhalt der Mail)."""
    _erledigt(eintrag, 'aufgegeben', jetzt)
    logger.error('Plattform-Postfach: Mail nach %s Versuchen aufgegeben (%s)', MAX_VERSUCHE, eintrag.letzter_fehler)
    info = getattr(fehler, 'plattform_info', None)
    if not info:
        return
    organisation, absender, betreff = info
    from core.auth import log_aktion
    from core.tenancy import kontext_des_objekts
    try:
        with kontext_des_objekts(organisation):
            log_aktion(None, 'Eingegangene Mail nicht verarbeitet', f'{absender[:90]} · {betreff[:90]}',
                       f'Nach {MAX_VERSUCHE} Versuchen aufgegeben ({type(fehler).__name__}). '
                       'Bitte den Absender um erneuten Versand bitten.')
    except Exception:                                          # noqa: BLE001
        logger.exception('Plattform-Postfach: Logbucheintrag zur aufgegebenen Mail fehlgeschlagen')


def _imap_datum(tag):
    return f'{tag.day:02d}-{_MONATE[tag.month - 1]}-{tag.year}'


def aufraeumen(verbindung, jetzt, ausgabe=None):
    """Löscht bearbeitete und ignorierte Mails nach ``AUFBEWAHRUNG_TAGE`` Tagen. Gibt die Zahl gelöschter Mails
    zurück. Löscht nur, was gelesen UND alt UND in ``PlattformMail`` als erledigt vermerkt ist (siehe Kopf)."""
    from core.models import PlattformMail

    grenze = jetzt - timedelta(days=AUFBEWAHRUNG_TAGE)
    status, daten = verbindung.search(None, 'SEEN', 'BEFORE', _imap_datum(grenze))
    if status != 'OK':
        return 0
    geloescht = 0
    for kennung in (daten[0] or b'').split()[:MAX_MAILS_JE_LAUF * 2]:
        try:
            schluessel = schluessel_aus_roh(_holen(verbindung, kennung, 'BODY.PEEK[HEADER]'))
        except Exception:                                      # noqa: BLE001
            logger.warning('Plattform-Postfach: Kopf einer Mail beim Aufräumen nicht lesbar, bleibt liegen')
            continue
        if not PlattformMail.objects.filter(schluessel=schluessel, erledigt_am__isnull=False,
                                            erledigt_am__lte=grenze).exists():
            continue
        verbindung.store(kennung, '+FLAGS', '\\Deleted')
        geloescht += 1
    if geloescht:
        verbindung.expunge()
    PlattformMail.objects.filter(erledigt_am__lt=jetzt - timedelta(days=PROTOKOLL_TAGE)).delete()
    if ausgabe is not None and geloescht:
        ausgabe(f'{geloescht} alte Mail(s) aus dem Postfach gelöscht.')
    return geloescht


def status_vermerken(jetzt, fehler=''):
    from core.models import PlattformEingangStatus
    eintrag = PlattformEingangStatus.holen()
    eintrag.letzter_abruf = jetzt
    eintrag.letzter_fehler = (fehler or '')[:300]
    felder = ['letzter_abruf', 'letzter_fehler']
    if not fehler:
        eintrag.letzter_erfolg = jetzt
        felder.append('letzter_erfolg')
    eintrag.save(update_fields=felder)


def abrufen(jetzt=None, ausgabe=None):
    """Ein Durchlauf: ungelesene Mails holen und verarbeiten, danach aufräumen. Gibt ein Dict mit den Zahlen
    ``verarbeitet``, ``ignoriert``, ``aufgegeben``, ``fehlgeschlagen``, ``geloescht`` zurück.

    Wirft ``AbrufFehler`` (nach Vermerk im Status), wenn Verbindung oder Anmeldung scheitern, und
    ``RuntimeError``, wenn nichts eingerichtet ist. Fehler EINER Mail brechen den Lauf nicht ab."""
    konfig = konfiguration()
    if konfig is None:
        raise RuntimeError('Plattform-Postfach nicht eingerichtet (PLATTFORM_IMAP_* fehlt).')
    jetzt = jetzt or timezone.now()

    def sagen(text):
        if ausgabe is not None:
            ausgabe(text)

    try:
        verbindung = verbinden(konfig)
    except AbrufFehler as fehler:
        status_vermerken(jetzt, str(fehler))
        raise
    zahlen = {'verarbeitet': 0, 'ignoriert': 0, 'aufgegeben': 0, 'fehlgeschlagen': 0, 'geloescht': 0}
    beginn = time.monotonic()
    try:
        status, daten = verbindung.search(None, 'UNSEEN')
        if status != 'OK':
            raise AbrufFehler('Die Suche nach ungelesenen Mails im Plattform-Postfach schlug fehl.')
        kennungen = (daten[0] or b'').split()
        sagen(f'{len(kennungen)} ungelesene Mail(s)' if kennungen else '(verbunden, keine neuen Mails)')
        for kennung in kennungen[:MAX_MAILS_JE_LAUF]:
            if time.monotonic() - beginn > LAUF_BUDGET_SEKUNDEN:
                sagen('Zeitbudget des Laufs erreicht, der Rest kommt beim nächsten Lauf.')
                break
            try:
                art, ausgang = _eine_mail(verbindung, kennung, jetzt)
            except Exception as fehler:                        # noqa: BLE001
                zahlen['fehlgeschlagen'] += 1
                sagen(f'FEHLER bei einer Mail (bleibt ungelesen, nächster Lauf wiederholt): {fehler}')
                continue
            zahlen[art] += 1
            if art == 'aufgegeben':
                sagen('Eine Mail wurde nach mehreren Versuchen aufgegeben (Serverprotokoll, Logbuch).')
        try:
            zahlen['geloescht'] = aufraeumen(verbindung, jetzt, sagen)
        except Exception:                                      # noqa: BLE001
            # Aufräumen ist nie wichtiger als der Eingang: ein Fehler hier bricht nichts ab.
            logger.exception('Plattform-Postfach: Aufräumen fehlgeschlagen')
            sagen('Aufräumen fehlgeschlagen (Serverprotokoll).')
    except AbrufFehler as fehler:
        status_vermerken(jetzt, str(fehler))
        raise
    finally:
        _schliessen(verbindung)

    if zahlen['fehlgeschlagen']:
        status_vermerken(jetzt, f"{zahlen['fehlgeschlagen']} Mail(s) liessen sich nicht verarbeiten. "
                                'Einzelheiten im Serverprotokoll.')
    else:
        status_vermerken(jetzt)
    return zahlen
