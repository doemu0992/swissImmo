"""Eingehende Kreditorenrechnungen per Weiterleitung (Brevo Inbound Parsing) — Entscheid 4.11.2026.

DER WEG
Jede Verwaltung hat eine zweite Plattformadresse ``<kennung>-rechnungen@<ANTWORT_DOMAIN>``
(``antwort_eingang.rechnungs_adresse``). Eine Mail daran kommt über denselben Webhook wie die Antworten auf
Ticket-Mails (``core/views/webhooks.py``); die EMPFÄNGERADRESSE sagt, zu welcher Verwaltung und zu welchem
Zweck sie gehört. Brevo liefert die Anhänge nicht mit, sondern je einen ``DownloadToken``; die Dateien holt
``anhang_laden`` mit dem API-Schlüssel (``BREVO_API_KEY``).

Aus jedem brauchbaren Anhang wird DIESELBE Kreditorenrechnung wie beim IMAP-Abruf und beim Upload:
``core.services.belegimport.anhang_importieren`` (Beleg speichern, KI-Scanner, Status «Neu», Logbuch). Es gibt
hier keine zweite Verarbeitung. Wer sein eigenes Postfach behalten will, richtet dort eine Weiterleitung auf
die Plattformadresse ein; Zugangsdaten braucht niemand mehr zu hinterlegen.

WAS EIN ANHANG ERFÜLLEN MUSS (``auswahl_anhaenge``)
* ContentType PDF, JPEG oder PNG (``application/octet-stream`` nur mit passender Dateiendung) UND die ersten
  Bytes passen dazu (Magic-Bytes). Beides, weil Typ und Name vom Absender kommen.
* höchstens ``MAX_GROESSE`` Byte (vorab nach ``ContentLength``, beim Laden nochmals hart), höchstens
  ``MAX_ANHAENGE`` Anhänge je Mail.
* Signaturlogos zählen nicht: Bilder unter ``MIN_BILD`` Byte und Inline-Bilder (``ContentID``) ohne
  Dateiendung werden übergangen.

WENN ETWAS NICHT GEHT, VERSCHWINDET DIE MAIL NICHT STILL
* Kein ``BREVO_API_KEY``: die Anhänge lassen sich nicht laden. Die Antwort an Brevo ist trotzdem 200 (ein
  500 hiesse «bitte wiederholen», und ohne Schlüssel hilft das nicht), aber im Logbuch der Verwaltung steht
  «Rechnungsmail ohne Anhang abgerufen» mit Absender und Betreff. Sie sieht, dass etwas ankam, und kann den
  Absender bitten, es erneut zu senden. Das ist der Ersatz für eine Pendenz: ein eigenes Pendenzmodell gibt es
  für so etwas nicht, und das Logbuch ist je Verwaltung sichtbar.
* Brevo antwortet auf den Download mit 4xx (Token abgelaufen, unbekannt): ebenfalls Logbuch, 200 — eine
  Wiederholung ändert daran nichts.
* Netzfehler, Zeitüberschreitung, 5xx: Ausnahme, also 500, Brevo wiederholt. Die Transaktion rollt den
  ``EingegangeneMail``-Eintrag und bereits angelegte Rechnungen zurück, es entsteht nichts doppelt.
* Spam (``Spam.Score`` ab ``SPAM_AB``): nicht verarbeitet, nur im Serverprotokoll (ein Logbucheintrag je
  Spam-Mail liesse sich von aussen füllen).

LÄUFT im Mandantenkontext der gefundenen Verwaltung; der Aufrufer setzt ihn.
"""
import logging
import re
from email.utils import parseaddr
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

#: «Get inbound email attachment» der Brevo-API. QUELLE: Brevo-Doku
#: https://developers.brevo.com/docs/inbound-parse-webhooks (Abschnitt Anhänge: ``DownloadToken``) und
#: API-Referenz «Get inbound email attachment». Der Pfad stammt aus der Doku-Zusammenfassung, nicht aus einem
#: Livetest; stimmt er nicht, meldet der Download 404 und die Mail landet im Logbuch (siehe oben).
BREVO_HOST = 'api.brevo.com'
BREVO_ANHANG_URL = f'https://{BREVO_HOST}/v3/inbound/attachments/{{token}}'

MAX_GROESSE = 15 * 1024 * 1024
MAX_ANHAENGE = 10
#: Kleiner als das ist ein Signaturlogo, keine Rechnung.
MIN_BILD = 20 * 1024
#: Ab diesem Spam-Wert (Brevo ``Spam.Score``) wird nichts verarbeitet.
SPAM_AB = 8.0
#: (Verbindung, Lesen) in Sekunden.
ZEITLIMIT = (5, 30)
MAX_UMLEITUNGEN = 3

#: ContentType → Anfang der Datei. Das ist die Magic-Bytes-Prüfung.
TYPEN = {
    'application/pdf': (b'%PDF-',),
    'image/jpeg': (b'\xff\xd8\xff',),
    'image/png': (b'\x89PNG\r\n\x1a\n',),
}
ENDUNGEN = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
UNSPEZIFISCH = ('application/octet-stream', 'binary/octet-stream', '')


class AnhangFehler(Exception):
    """Der Anhang liess sich nicht laden. ``dauerhaft``: Wiederholen hilft nicht (4xx, Umleitung ins
    Ausland, zu gross)."""

    def __init__(self, text, dauerhaft):
        super().__init__(text)
        self.dauerhaft = dauerhaft


def api_schluessel():
    return (getattr(settings, 'BREVO_API_KEY', None) or '').strip()


def spam_wert(item):
    """Der ``Spam.Score`` der Mail als Zahl, ``0.0`` wenn keiner geliefert wird."""
    spam = item.get('Spam')
    roh = spam.get('Score') if isinstance(spam, dict) else item.get('Spam.Score', item.get('SpamScore'))
    try:
        return float(roh)
    except (TypeError, ValueError):
        return 0.0


def magic_passt(inhalt, typ):
    return any(inhalt.startswith(m) for m in TYPEN.get(typ, ()))


def _endung(name):
    m = re.search(r'\.[A-Za-z0-9]{1,5}$', name or '')
    return m.group(0).lower() if m else ''


def auswahl_anhaenge(item):
    """Welche Anhänge einer Brevo-Mail kommen in Frage. Gibt ``(kandidaten, uebergangen)`` zurück:
    ``kandidaten`` sind Dicts ``name``, ``typ``, ``token``; ``uebergangen`` Gründe (für das Protokoll)."""
    kandidaten, uebergangen = [], []
    roh = item.get('Attachments')
    for a in roh if isinstance(roh, list) else []:
        if not isinstance(a, dict):
            continue
        name = str(a.get('Name') or '')
        typ = str(a.get('ContentType') or '').split(';')[0].strip().lower()
        endung = _endung(name)
        token = str(a.get('DownloadToken') or '').strip()
        try:
            groesse = int(a.get('ContentLength') or 0)
        except (TypeError, ValueError):
            groesse = 0
        if typ in UNSPEZIFISCH and endung in ENDUNGEN:
            typ = ENDUNGEN[endung]
        if typ not in TYPEN:
            uebergangen.append(f'{name or "(ohne Name)"}: Typ {typ or "unbekannt"}')
            continue
        if not token:
            uebergangen.append(f'{name}: ohne Download-Token')
            continue
        if groesse > MAX_GROESSE:
            uebergangen.append(f'{name}: zu gross ({groesse} Byte)')
            continue
        if typ != 'application/pdf' and (0 < groesse < MIN_BILD
                                         or (a.get('ContentID') and not endung)):
            uebergangen.append(f'{name or "(ohne Name)"}: Signaturbild')
            continue
        if len(kandidaten) >= MAX_ANHAENGE:
            uebergangen.append(f'{name}: mehr als {MAX_ANHAENGE} Anhänge')
            continue
        if not endung:
            name = (name or 'beleg') + {'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png'}[typ]
        kandidaten.append({'name': name, 'typ': typ, 'token': token})
    return kandidaten, uebergangen


def anhang_laden(token):
    """Der Anhang als Bytes — von ``api.brevo.com`` und nirgendwo sonst.

    Umleitungen werden von Hand verfolgt, und nur solche auf ``https://api.brevo.com``: ein Ziel
    anderswo bekäme sonst den API-Schlüssel mit. Wirft ``AnhangFehler``."""
    schluessel = api_schluessel()
    if not schluessel:
        raise AnhangFehler('Brevo-API-Schlüssel fehlt', dauerhaft=True)
    url = BREVO_ANHANG_URL.format(token=requests.utils.quote(token, safe=''))
    for _ in range(MAX_UMLEITUNGEN + 1):
        try:
            antwort = requests.get(url, headers={'api-key': schluessel, 'accept': 'application/octet-stream'},
                                   timeout=ZEITLIMIT, stream=True, allow_redirects=False)
        except requests.RequestException as fehler:
            raise AnhangFehler(f'Brevo nicht erreichbar ({type(fehler).__name__})', dauerhaft=False) from fehler
        try:
            if antwort.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, antwort.headers.get('Location', ''))
                teile = urlsplit(url)
                if teile.scheme != 'https' or teile.hostname != BREVO_HOST:
                    raise AnhangFehler('Umleitung ausserhalb von api.brevo.com, nicht verfolgt', dauerhaft=True)
                continue
            if antwort.status_code >= 500 or antwort.status_code == 429:
                raise AnhangFehler(f'Brevo antwortet mit {antwort.status_code}', dauerhaft=False)
            if antwort.status_code != 200:
                raise AnhangFehler(f'Brevo antwortet mit {antwort.status_code}', dauerhaft=True)
            gelesen = bytearray()
            try:
                for stueck in antwort.iter_content(64 * 1024):
                    gelesen.extend(stueck)
                    if len(gelesen) > MAX_GROESSE:
                        raise AnhangFehler('Anhang grösser als erlaubt', dauerhaft=True)
            except requests.RequestException as fehler:
                raise AnhangFehler(f'Download abgebrochen ({type(fehler).__name__})', dauerhaft=False) from fehler
            return bytes(gelesen)
        finally:
            antwort.close()
    raise AnhangFehler('Zu viele Umleitungen', dauerhaft=True)


def _logbuch(text, objekt, details):
    from core.auth import log_aktion
    log_aktion(None, text, objekt[:200], details[:1000])


def rechnungsmail_verarbeiten(organisation, item, absender, betreff, jetzt=None):
    """Eine Mail an die Rechnungsadresse von ``organisation`` verarbeiten (Mandantenkontext gesetzt).

    Gibt den Ausgang als kurzen Text für die Webhook-Antwort zurück: ``'ok, N Rechnung(en)'``, ``'spam'``,
    ``'no attachment'``, ``'attachments not loaded'``. Wirft bei vorübergehenden Ladefehlern (siehe Kopf)."""
    from core.services.belegimport import anhang_importieren

    jetzt = jetzt or timezone.now()
    adresse = parseaddr(absender or '')[1].strip()[:100] or (absender or 'Unbekannt')[:100]

    if spam_wert(item) >= SPAM_AB:
        logger.info('Rechnungseingang: Mail für Verwaltung %s als Spam verworfen (Wert %s)',
                    organisation.pk, spam_wert(item))
        return 'spam'

    kandidaten, uebergangen = auswahl_anhaenge(item)
    for grund in uebergangen:
        logger.info('Rechnungseingang (Verwaltung %s): Anhang übergangen — %s', organisation.pk, grund)
    objekt = f'{adresse} · {(betreff or "(ohne Betreff)")[:80]}'
    if not kandidaten:
        _logbuch('Rechnungsmail ohne Anhang abgerufen', objekt,
                 'Kein PDF- oder Bild-Anhang gefunden.' + (f' Übergangen: {"; ".join(uebergangen)[:600]}'
                                                            if uebergangen else ''))
        return 'no attachment'
    if not api_schluessel():
        logger.warning('Anhang nicht geladen: Brevo-API-Schlüssel fehlt (Verwaltung %s)', organisation.pk)
        _logbuch('Rechnungsmail ohne Anhang abgerufen', objekt,
                 'Anhang nicht geladen: Brevo-API-Schlüssel fehlt. Bitte den Absender um erneuten Versand '
                 'bitten, sobald der Betreiber den Schlüssel eingetragen hat.')
        return 'attachments not loaded'

    angelegt, fehler = 0, []
    for k in kandidaten:
        try:
            inhalt = anhang_laden(k['token'])
        except AnhangFehler as e:
            if not e.dauerhaft:
                raise
            fehler.append(f'{k["name"]}: {e}')
            continue
        if not magic_passt(inhalt, k['typ']):
            logger.info('Rechnungseingang (Verwaltung %s): %s — Dateikopf passt nicht zu %s, übergangen',
                        organisation.pk, k['name'], k['typ'])
            fehler.append(f'{k["name"]}: Dateiinhalt passt nicht zum Typ')
            continue
        anhang_importieren(inhalt, k['name'], adresse, betreff=betreff or '', eingang=timezone.localtime(jetzt))
        angelegt += 1
    if fehler:
        _logbuch('Rechnungsmail ohne Anhang abgerufen' if not angelegt else 'Rechnungsmail teilweise abgerufen',
                 objekt, 'Nicht übernommen: ' + '; '.join(fehler)[:900])
    return f'ok, {angelegt} invoice(s)' if angelegt else 'attachments not loaded'


# --- Anhänge direkt aus der Mail (Plattform-Postfach per IMAP, ohne Brevo) ----------------------------------------

def anhaenge_aus_mail(msg):
    """Die brauchbaren Anhänge einer eingelesenen Mail (``email.message.Message``). Gibt
    ``(kandidaten, uebergangen)`` zurück: ``kandidaten`` sind Dicts ``name``, ``typ``, ``inhalt`` (Bytes),
    ``uebergangen`` Gründe fürs Protokoll.

    DIESELBEN REGELN wie ``auswahl_anhaenge`` (Brevo): Typ PDF/JPEG/PNG (``application/octet-stream`` nur mit
    passender Endung), Dateikopf passt zum Typ (Magic-Bytes), höchstens ``MAX_GROESSE`` Byte und
    ``MAX_ANHAENGE`` Anhänge, Signaturlogos (kleine Bilder, Inline-Bilder ohne Endung) zählen nicht. Der Text
    der Mail selbst (ohne Dateiname) ist kein Anhang. Eine weitergeleitete Mail als Anhang
    (``message/rfc822``) wird durchsucht: ``walk`` geht hinein."""
    kandidaten, uebergangen = [], []
    for teil in msg.walk():
        if teil.is_multipart():
            continue
        name = str(teil.get_filename() or '')
        typ = teil.get_content_type()
        if not name and typ in ('text/plain', 'text/html'):
            continue
        endung = _endung(name)
        if typ in UNSPEZIFISCH and endung in ENDUNGEN:
            typ = ENDUNGEN[endung]
        if typ not in TYPEN:
            if name:
                uebergangen.append(f'{name}: Typ {typ or "unbekannt"}')
            continue
        inhalt = teil.get_payload(decode=True) or b''
        groesse = len(inhalt)
        if not groesse:
            uebergangen.append(f'{name or "(ohne Name)"}: leer')
            continue
        if groesse > MAX_GROESSE:
            uebergangen.append(f'{name}: zu gross ({groesse} Byte)')
            continue
        if not magic_passt(inhalt, typ):
            uebergangen.append(f'{name or "(ohne Name)"}: Dateiinhalt passt nicht zum Typ')
            continue
        if typ != 'application/pdf' and (groesse < MIN_BILD or (teil.get('Content-ID') and not endung)):
            uebergangen.append(f'{name or "(ohne Name)"}: Signaturbild')
            continue
        if len(kandidaten) >= MAX_ANHAENGE:
            uebergangen.append(f'{name}: mehr als {MAX_ANHAENGE} Anhänge')
            continue
        if not endung:
            name = (name or 'beleg') + {'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png'}[typ]
        kandidaten.append({'name': name, 'typ': typ, 'inhalt': inhalt})
    return kandidaten, uebergangen


def rechnungsmail_aus_mail_verarbeiten(organisation, msg, absender, betreff, jetzt=None):
    """Eine Mail an die Rechnungsadresse von ``organisation`` verarbeiten, wenn die Anhänge in der Mail selbst
    liegen (Plattform-Postfach). Mandantenkontext gesetzt; der Aufrufer prüft Spam und Idempotenz.

    Der Ausgang wie bei ``rechnungsmail_verarbeiten``: ``'ok, N invoice(s)'`` oder ``'no attachment'``. Ohne
    brauchbaren Anhang steht ein Logbucheintrag da (kein Brevo-Schlüssel nötig). Wirft bei Fehlern des
    Beleg-Imports; die Transaktion des Aufrufers rollt alles zurück, und der Abruf wiederholt die Mail."""
    from core.services.belegimport import anhang_importieren

    jetzt = jetzt or timezone.now()
    adresse = parseaddr(absender or '')[1].strip()[:100] or (absender or 'Unbekannt')[:100]
    objekt = f'{adresse} · {(betreff or "(ohne Betreff)")[:80]}'
    kandidaten, uebergangen = anhaenge_aus_mail(msg)
    for grund in uebergangen:
        logger.info('Rechnungseingang (Verwaltung %s): Anhang übergangen — %s', organisation.pk, grund)
    if not kandidaten:
        _logbuch('Rechnungsmail ohne Anhang abgerufen', objekt,
                 'Kein PDF- oder Bild-Anhang gefunden.' + (f' Übergangen: {"; ".join(uebergangen)[:600]}'
                                                            if uebergangen else ''))
        return 'no attachment'
    for k in kandidaten:
        anhang_importieren(k['inhalt'], k['name'], adresse, betreff=betreff or '',
                           eingang=timezone.localtime(jetzt))
    if uebergangen:
        _logbuch('Rechnungsmail teilweise abgerufen', objekt, 'Nicht übernommen: ' + '; '.join(uebergangen)[:900])
    return f'ok, {len(kandidaten)} invoice(s)'
