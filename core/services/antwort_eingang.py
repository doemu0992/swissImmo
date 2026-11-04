"""Antwortadresse der Plattform und der gemeinsame Eingang für Antworten auf Ticket-Mails.

DIE IDEE (Entscheid 4.11.2026)

Jede Verwaltung bekommt automatisch eine eigene Adresse ``<kennung>@<ANTWORT_DOMAIN>``. Ticket- und
Chat-Mails tragen sie als Reply-To; eine Antwort kommt über den Brevo-Inbound-Webhook
(``core/views/webhooks.py``) zurück, und die **Empfängeradresse** sagt, zu welcher Verwaltung sie gehört.
Die Verwaltung braucht kein eigenes Postfach. Hat sie eines (``core.Postfach``, Zweck «antworten»,
aktiv UND lesbar), gilt weiter dieses: ``tickets.workflow.reply_to``.

ZWEITE ADRESSE: EINGEHENDE RECHNUNGEN (Entscheid 4.11.2026)

Zu jeder Kennung gehört eine zweite Adresse ``<kennung>-rechnungen@<ANTWORT_DOMAIN>`` für Kreditoren-
rechnungen. Sie hat dieselbe Kennung (also dieselbe Erneuerung und dasselbe 30-Tage-Fenster) und nur den
festen Zusatz ``-rechnungen``; ``zuordnung_zu_adresse`` liefert ``(Verwaltung, Zweck)``. Die Kennung bleibt
der nicht erratbare Teil, der Zusatz ist öffentlich. Wer sein eigenes Postfach behalten will, richtet dort
eine Weiterleitung auf diese Adresse ein — es werden keine Zugangsdaten hinterlegt.

WARUM DIE EMPFÄNGERADRESSE UND NICHT DER BETREFF

Die Zuordnung über den Betreff rät (eine Ticketnummer ist fortlaufend und ratbar). Die Kennung ist ein
Zufallswert (10 Zeichen aus 31, rund 50 Bit) und wird nur in Mails genannt, die diese Verwaltung selbst
verschickt hat. Ticketnummer und Auftragsmarke werden danach NUR innerhalb der gefundenen Verwaltung
aufgelöst: ein Ticket einer anderen Verwaltung findet nichts, und die Antwort ist dieselbe wie bei einer
Nummer, die es nirgends gibt.

KENNUNG ERNEUERN

``kennung_erneuern`` vergibt eine neue Kennung. Die vorherige bleibt ``ALT_GUELTIG`` (30 Tage) gültig,
damit Antworten auf schon versandte Mails nicht verloren gehen. Ablauf mit ``timezone.now()``.

DIE GEMEINSAME VERARBEITUNG

``eingehende_antwort_verarbeiten`` ist der eine Weg für Webhook UND IMAP-Abruf (``fetch_replies``):
Ticketnummer im Betreff, Auftragsmarke ``[A<id>]``, Schleifenschutz, Zuordnung zum Direktkanal oder zum
Ticket-Verlauf. Sie läuft im Mandantenkontext der Verwaltung und nimmt ``objects``, nie
``alle_organisationen``.
"""
import html
import logging
import re
import secrets
from datetime import timedelta
from email.utils import parseaddr

from django.conf import settings
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

logger = logging.getLogger(__name__)

#: Ohne leicht zu verwechselnde Zeichen (0/o, 1/l/i) — Adressen werden auch diktiert.
KENNUNG_ZEICHEN = 'abcdefghjkmnpqrstuvwxyz23456789'
KENNUNG_LAENGE = 10
PRAEFIX_MAX = 12
#: So lange gilt die vorherige Kennung nach «Adresse erneuern».
ALT_GUELTIG = timedelta(days=30)
#: Längenlimit des gespeicherten Antworttextes (Zeichen). Länger wird gekürzt, nicht abgewiesen.
TEXT_MAX = 10000
STANDARD_DOMAIN = 'immoswiss.app'
GLOBALE_ADRESSE_LOKAL = 'reply'

ZWECK_ANTWORTEN = 'antworten'
ZWECK_RECHNUNGEN = 'rechnungen'
#: Zusatz hinter der Kennung für die Rechnungsadresse. Eine Kennung selbst endet nie darauf: ``neue_kennung``
#: lässt den Zufallsteil ``rechnungen`` nicht zu (sonst wäre ``x-rechnungen`` zugleich Kennung und Rechnungs-
#: adresse von ``x``).
RECHNUNGS_ZUSATZ = '-rechnungen'

#: Ab hier beginnt das zitierte Original. Alles danach wird abgeschnitten — sonst steht die ganze
#: Verlaufskette in jeder Antwort. (Vorher in ``fetch_replies``.)
ZITAT_MUSTER = [
    r'ImmoSwiss Verwaltung\s+schrieb am',
    r'via immoswiss\s+(schrieb|wrote)',
    r'schrieb am.*?um.*?:',
    r'On\s+.*?wrote:',
    r'Am\s+.*?schrieb.*?:',
    r'-+Original\s+Message-+',
    r'From:\s+.*',
    r'Von:\s+.*',
    r'Gesendet von meinem iPhone',
    r'Sent from my iPhone',
]
PLATZHALTER = '[[ZEILENUMBRUCH]]'


# --- Kennung und Adresse ---------------------------------------------------------------------------------

def antwort_domain():
    return (getattr(settings, 'ANTWORT_DOMAIN', '') or STANDARD_DOMAIN).strip().lower()


def eingang_aktiv():
    """Ist der Empfang auf diesem Server eingerichtet? Mindestens ein Kanal muss stehen: der Brevo-Webhook
    (``BREVO_WEBHOOK_SECRET``) oder das Plattform-Postfach per IMAP (``PLATTFORM_IMAP_*``,
    ``core.services.plattform_postfach``). Ohne Kanal kann keine Mail ankommen — dann bleibt es beim bisherigen
    Reply-To, statt Antworten an eine tote Adresse zu schicken."""
    from core.services.plattform_postfach import plattform_eingang_status
    return plattform_eingang_status()['eingerichtet']


def _praefix(firma):
    roh = re.sub(r'[^a-z0-9]', '', slugify(firma or '').lower())[:PRAEFIX_MAX]
    return roh or 'verwaltung'


def neue_kennung(firma=''):
    """Lesbares Präfix aus der Firma plus Zufall; kollidiert nicht mit einer bestehenden oder
    noch gültigen vorherigen Kennung."""
    from crm.models import Organisation
    while True:
        zufall = ''.join(secrets.choice(KENNUNG_ZEICHEN) for _ in range(KENNUNG_LAENGE))
        kennung = f'{_praefix(firma)}-{zufall}'
        if zufall == RECHNUNGS_ZUSATZ[1:]:
            continue
        if not (Organisation.objects.filter(antwort_kennung=kennung).exists()
                or Organisation.objects.filter(antwort_kennung_alt=kennung).exists()):
            return kennung


def antwort_adresse(organisation):
    return f'{organisation.antwort_kennung}@{antwort_domain()}'


def rechnungs_adresse(organisation):
    return f'{organisation.antwort_kennung}{RECHNUNGS_ZUSATZ}@{antwort_domain()}'


def kennung_erneuern(organisation, jetzt=None):
    """Neue Kennung; die bisherige gilt noch ``ALT_GUELTIG`` (für beide Adressen: Antworten und Rechnungen
    hängen an derselben Kennung). Gibt die neue Antwortadresse zurück."""
    jetzt = jetzt or timezone.now()
    organisation.antwort_kennung_alt = organisation.antwort_kennung
    organisation.antwort_kennung_alt_bis = jetzt + ALT_GUELTIG
    organisation.antwort_kennung = neue_kennung(organisation.firma)
    organisation.save(update_fields=['antwort_kennung', 'antwort_kennung_alt', 'antwort_kennung_alt_bis'])
    return antwort_adresse(organisation)


def alte_kennung_gilt(organisation, jetzt=None):
    jetzt = jetzt or timezone.now()
    return bool(organisation.antwort_kennung_alt and organisation.antwort_kennung_alt_bis
                and organisation.antwort_kennung_alt_bis > jetzt)


def rein_adresse(wert):
    """Die reine Adresse (klein) aus ``"Name <a@b>"``, einem Mailbox-Objekt ``{Name, Address}`` oder
    einer blossen Adresse; ``''`` wenn keine erkennbar."""
    if isinstance(wert, dict):
        wert = wert.get('Address') or wert.get('address') or wert.get('Email') or ''
    if not isinstance(wert, str):
        return ''
    adresse = parseaddr(wert)[1].strip().lower()
    return adresse if adresse.count('@') == 1 else ''


def zuordnung_zu_adresse(adresse, jetzt=None):
    """``(Verwaltung, Zweck)`` zu dieser Empfängeradresse — oder ``None``.

    Zweck ist ``ZWECK_ANTWORTEN`` (``<kennung>@…``) oder ``ZWECK_RECHNUNGEN`` (``<kennung>-rechnungen@…``).
    Nur Adressen auf ``ANTWORT_DOMAIN``. Gilt die aktuelle Kennung oder die vorherige innerhalb ihres
    Fensters. ``Organisation`` selbst trägt keinen Mandantenfilter (sie IST der Mandant)."""
    adresse = rein_adresse(adresse)
    if not adresse:
        return None
    lokal, domain = adresse.split('@')
    if domain != antwort_domain() or not lokal:
        return None
    org = _organisation_zu_kennung(lokal, jetzt)
    if org is not None:
        return org, ZWECK_ANTWORTEN
    if lokal.endswith(RECHNUNGS_ZUSATZ):
        org = _organisation_zu_kennung(lokal[:-len(RECHNUNGS_ZUSATZ)], jetzt)
        if org is not None:
            return org, ZWECK_RECHNUNGEN
    return None


def _organisation_zu_kennung(kennung, jetzt=None):
    from crm.models import Organisation
    if not kennung:
        return None
    org = Organisation.objects.filter(antwort_kennung=kennung).first()
    if org is not None:
        return org
    org = Organisation.objects.filter(antwort_kennung_alt=kennung).first()
    if org is not None and alte_kennung_gilt(org, jetzt):
        return org
    return None


def organisation_zu_adresse(adresse, jetzt=None):
    """Die Verwaltung, der diese ANTWORTadresse gehört — oder ``None`` (die Rechnungsadresse zählt hier
    nicht: dafür ``zuordnung_zu_adresse``)."""
    treffer = zuordnung_zu_adresse(adresse, jetzt)
    return treffer[0] if treffer and treffer[1] == ZWECK_ANTWORTEN else None


def ist_plattform_adresse(adresse):
    """Liegt die Adresse auf der Antwort-Domain (egal ob die Kennung stimmt)?"""
    adresse = rein_adresse(adresse)
    return bool(adresse) and adresse.split('@')[1] == antwort_domain()


def ist_globale_adresse(adresse):
    """Das alte gemeinsame ``reply@…`` (Zuordnung nur über die Ticketnummer)."""
    adresse = rein_adresse(adresse)
    return bool(adresse) and adresse.split('@')[0] == GLOBALE_ADRESSE_LOKAL and ist_plattform_adresse(adresse)


# --- Text aufbereiten --------------------------------------------------------------------------------------

def zitat_abschneiden(text):
    frueheste = len(text)
    for muster in ZITAT_MUSTER:
        treffer = re.search(muster, text, re.IGNORECASE)
        if treffer and treffer.start() < frueheste:
            frueheste = treffer.start()
    return text[:frueheste]


def leerzeilen_zusammenfassen(text):
    ergebnis = ''
    for zeile in (z.strip() for z in text.splitlines()):
        if zeile:
            ergebnis += zeile + '\n'
        elif not ergebnis.endswith('\n\n'):
            ergebnis += '\n'
    return ergebnis.strip()


def html_zu_text(html_inhalt):
    """HTML-Mail zu lesbarem Text. Der Umweg über einen Platzhalter ist Absicht: ``strip_tags`` wirft die
    Tags weg, ohne einen Umbruch zu hinterlassen."""
    if not html_inhalt:
        return ''
    text = html_inhalt
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<br\s*/?>', PLATZHALTER, text, flags=re.IGNORECASE)
    text = re.sub(r'</(div|p|h[1-6]|table|tr|li|blockquote)>', PLATZHALTER, text, flags=re.IGNORECASE)
    text = re.sub(r'<(div|p|h[1-6]|table|tr|li|blockquote)[^>]*>', PLATZHALTER, text, flags=re.IGNORECASE)
    text = re.sub(r'</?(td|th)[^>]*>', ' ', text, flags=re.IGNORECASE)
    text = strip_tags(text)
    text = text.replace(PLATZHALTER, '\n')
    text = html.unescape(text).replace('\xa0', ' ')
    return leerzeilen_zusammenfassen(zitat_abschneiden(text))


def antworttext(item):
    """Nur der Textteil einer Brevo-Mail: ``ExtractedMarkdownMessage`` (Antwort ohne Zitat und Signatur),
    sonst ``RawTextBody`` ohne Zitat, sonst der in Text gewandelte HTML-Teil. HTML wird nie übernommen."""
    for feld in ('ExtractedMarkdownMessage',):
        wert = item.get(feld)
        if isinstance(wert, str) and wert.strip():
            return wert.strip()[:TEXT_MAX]
    roh = item.get('RawTextBody')
    if isinstance(roh, str) and roh.strip():
        return leerzeilen_zusammenfassen(zitat_abschneiden(roh))[:TEXT_MAX]
    return html_zu_text(item.get('RawHtmlBody') if isinstance(item.get('RawHtmlBody'), str) else '')[:TEXT_MAX]


def kopf_als_dict(roh):
    """Kopfzeilen als ``{Name: Wert}``. Brevo liefert ``Headers`` als Objekt (Wert Text oder Liste), je
    nach Konfiguration auch als Liste/Text aus ``Name: Wert``-Zeilen; alles andere ergibt ``{}``."""
    ergebnis = {}
    if isinstance(roh, dict):
        for name, wert in roh.items():
            if isinstance(wert, (list, tuple)):
                wert = ' '.join(str(w) for w in wert)
            ergebnis[str(name)] = str(wert)
        return ergebnis
    zeilen = roh if isinstance(roh, (list, tuple)) else (roh.splitlines() if isinstance(roh, str) else [])
    for zeile in zeilen:
        if isinstance(zeile, str) and ':' in zeile:
            name, wert = zeile.split(':', 1)
            ergebnis[name.strip()] = wert.strip()
    return ergebnis


# --- Die gemeinsame Verarbeitung ------------------------------------------------------------------------------

_TICKET_NR_STRENG = re.compile(r'Ticket\s*#(\d+)', re.IGNORECASE)
_TICKET_NR_LOCKER = re.compile(r'#(\d+)')


def ticketnummer_aus_betreff(betreff, locker=True):
    """Die Ticketnummer aus «Ticket #123». ``locker``: sonst auch ein blosses «#123» (Webhook seit je)."""
    m = _TICKET_NR_STRENG.search(betreff or '') or (_TICKET_NR_LOCKER.search(betreff or '') if locker else None)
    return int(m.group(1)) if m else None


def eingehende_antwort_verarbeiten(organisation, absender, betreff, text, kopf=None, locker=True):
    """Eine eingehende Antwort in der Verwaltung ``organisation`` ablegen.

    Läuft im Mandantenkontext der Verwaltung (der Aufrufer setzt ihn; ``organisation`` wird hier nur zur
    Sicherheit gegen den Kontext geprüft). ``absender``: roher From-Wert. Ergebnis:

    * ``'direkt_mieter'`` / ``'direkt_handwerker'``: Chat am Auftrag, Gegenseite per Mail bedient
    * ``'handwerker'`` / ``'melder'``: im Ticket-Verlauf abgelegt (``tickets.workflow.antwort_zuordnen``)
    * ``'ohne_ticket'``: keine Nummer im Betreff, leerer Text oder das Ticket gibt es in DIESER Verwaltung
      nicht. Der Grund wird bewusst nicht unterschieden: kein Hinweis, ob es anderswo existiert.
    """
    from core.tenancy import aktuelle_organisation
    from tickets import direktkanal
    from tickets.models import SchadenMeldung
    from tickets.workflow import antwort_zuordnen

    aktuell = aktuelle_organisation()
    if organisation is None or aktuell is None or aktuell.pk != organisation.pk:
        raise RuntimeError('Antwort ausserhalb des Mandantenkontexts der Verwaltung verarbeitet.')
    text = (text or '').strip()
    nummer = ticketnummer_aus_betreff(betreff, locker=locker)
    if not nummer or not text:
        return 'ohne_ticket'
    # `objects`: der gefilterte Manager ist hier die Absicherung (Kontext = gefundene Verwaltung).
    ticket = SchadenMeldung.objects.filter(pk=nummer).first()
    if ticket is None:
        return 'ohne_ticket'
    return antwort_zuordnen(ticket, absender, text[:TEXT_MAX],
                            auftrag_id=direktkanal.auftrag_id_aus_betreff(betreff), kopf=kopf)
