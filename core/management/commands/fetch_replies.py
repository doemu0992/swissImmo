"""Antworten auf Ticket-Mails einlesen — je Verwaltung ein Postfach.

Mieter und Handwerker antworten auf die Benachrichtigung zu einem Ticket. Der
Betreff trägt «Ticket #123»; diese Nummer ordnet die Antwort dem Ticket zu.

ZWEI DINGE HABEN SICH AM 18.08.2026 GEÄNDERT

**1. Das Postfach kommt aus der Datenbank, nicht aus dem Code.** Bis dahin
stand der Server fest in dieser Datei (`IMAP_SERVER = "lx37.hoststar.hosting"`)
und die Zugangsdaten in `EMAIL_REPLY_USER` / `EMAIL_REPLY_PASSWORD` — ein
Postfach für alle Verwaltungen. Jetzt: `core.Postfach`, Zweck «antworten».
Kein stiller Rückfall auf die Umgebungsvariablen.

**2. Der Mandantenkontext wird gesetzt — vorher fehlte er, und der Befehl war
dadurch KAPUTT.** `SchadenMeldung` erbt von `OrganisationAusKette`, sein
`objects` ist also ein `TenantManager`. Der wirft seit Etappe 6.2 ohne
gesetzten Kontext. Der alte Code rief `SchadenMeldung.objects.get(id=…)`
mitten aus dem Befehl heraus auf, wo es nie einen Kontext gab — und fing das
Ergebnis mit

    except Exception as db_err:
        self.stdout.write(self.style.ERROR(f"❌ DB Fehler: {db_err}"))

wieder ein. Jede eingehende Antwort scheiterte also still, mit einer Zeile im
Protokoll, die nach einem Datenbankproblem aussah. Genau das ist der Grund,
warum ein `except Exception` mit einer Sammelmeldung so teuer ist: Der Fehler
war nicht unsichtbar — er war nur nicht als Fehler erkennbar.

DIE ZUORDNUNG IST JETZT ZWEISTUFIG

Postfach → Verwaltung, dann Ticketnummer **innerhalb** dieser Verwaltung. Eine
Nummer aus einem fremden Bestand findet damit nichts, statt in den falschen
Bestand zu schreiben.

Aufruf:
    python manage.py fetch_replies --einmal
    python manage.py fetch_replies                  # Dauerschleife (alle 60 s)
"""
import email
import html
import logging
import re
import time
from email.header import decode_header

from django.core.management.base import BaseCommand
from django.db import connections
from django.utils.html import strip_tags

from core.services.postfach_abruf import AbrufFehler, hole_ungelesene, postfaecher_fuer
from core.tenancy import organisation_kontext

logger = logging.getLogger(__name__)

PAUSE_SEKUNDEN = 60

#: Ab hier beginnt das zitierte Original. Alles danach wird abgeschnitten —
#: sonst steht die ganze Verlaufskette in jeder Antwort.
ZITAT_MUSTER = [
    r'ImmoSwiss Verwaltung\s+schrieb am',
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


class Command(BaseCommand):
    help = 'Holt Antworten auf Ticket-Mails ab, je Verwaltung aus ihrem eigenen Postfach.'

    def add_arguments(self, parser):
        parser.add_argument('--einmal', action='store_true',
                            help='Nur ein Durchlauf (für Scheduled Tasks) statt Dauerschleife.')
        parser.add_argument('--verwaltung', type=int, default=None,
                            help='Nur diese Organisations-ID abrufen.')

    def handle(self, *args, **options):
        if options['einmal']:
            self.durchlauf(options['verwaltung'])
            return
        self.stdout.write(f'Antwort-Abruf gestartet (Schleife, alle {PAUSE_SEKUNDEN} s) …')
        while True:
            try:
                self.durchlauf(options['verwaltung'])
            except Exception as fehler:                        # noqa: BLE001
                logger.exception('Antwort-Abruf: Durchlauf abgebrochen')
                self.stdout.write(self.style.ERROR(f'Fehler im Lauf: {fehler}'))
            for verbindung in connections.all():
                verbindung.close()
            time.sleep(PAUSE_SEKUNDEN)

    def durchlauf(self, nur_verwaltung=None):
        postfaecher = postfaecher_fuer('antworten')
        if nur_verwaltung is not None:
            postfaecher = postfaecher.filter(organisation_id=nur_verwaltung)

        if not postfaecher.exists():
            self.stdout.write(self.style.WARNING(
                'Kein eingerichtetes Antwort-Postfach gefunden. In den Einstellungen '
                'der Verwaltung unter «Postfächer» hinterlegen.'))
            return

        for postfach in postfaecher:
            self.stdout.write(f'{postfach.organisation} · {postfach.benutzer}')
            try:
                # DER KONTEXT — siehe Kopf. Ohne ihn wirft jeder Zugriff auf
                # SchadenMeldung.objects, und zwar zu Recht.
                with organisation_kontext(postfach.organisation):
                    self._ein_postfach(postfach)
            except Exception as fehler:                        # noqa: BLE001
                # Dieselbe Zusage wie `je_organisation` (core/tenancy.py:171):
                # Ein Fehler bei Verwaltung 3 darf 4 bis 20 nicht ohne Abruf
                # lassen — sonst fällt er erst auf, wenn wochenlang bei
                # niemandem mehr Antworten ankamen.
                logger.exception('%s: Abruf abgebrochen', postfach.organisation)
                self.stdout.write(self.style.ERROR(f'   FEHLER: {fehler}'))

    def _ein_postfach(self, postfach):
        try:
            verarbeitet, fehlgeschlagen = hole_ungelesene(
                postfach, self.verarbeite_mail, self.stdout)
        except AbrufFehler as fehler:
            postfach.fehler_vermerken(str(fehler))
            self.stdout.write(self.style.ERROR(f'   {fehler}'))
            return

        if fehlgeschlagen:
            postfach.fehler_vermerken(
                f'{fehlgeschlagen} von {verarbeitet + fehlgeschlagen} Mails liessen sich '
                'nicht verarbeiten. Einzelheiten im Serverprotokoll.')
        else:
            postfach.erfolg_vermerken()

    # -- Eine einzelne Mail -------------------------------------------------

    def verarbeite_mail(self, roh):
        """Wird je ungelesener Mail aufgerufen — im Kontext ihrer Verwaltung.

        Wirft bei einem Fehler; der Aufrufer zählt ihn und macht weiter. Das
        ist der Unterschied zur alten Fassung: Ein Fehler ist hier ein Fehler
        und keine Protokollzeile.
        """
        from tickets.models import SchadenMeldung, TicketNachricht

        nachricht = email.message_from_bytes(roh)
        betreff = self._betreff(nachricht)
        absender = nachricht.get('From', 'Unbekannt')
        self.stdout.write(f'   Prüfe: {betreff}')

        treffer = re.search(r'Ticket #(\d+)', betreff, re.IGNORECASE)
        if not treffer:
            self.stdout.write('   Keine Ticketnummer im Betreff — übersprungen.')
            return
        nummer = treffer.group(1)

        # `objects` und NICHT `alle_organisationen`: Der gefilterte Manager ist
        # hier die eigentliche Absicherung. Eine Nummer aus einem fremden
        # Bestand findet damit nichts, statt fremde Post zu ergänzen.
        ticket = SchadenMeldung.objects.filter(pk=nummer).first()
        if ticket is None:
            self.stdout.write(self.style.WARNING(
                f'   Ticket #{nummer} gibt es in dieser Verwaltung nicht — übersprungen.'))
            return

        inhalt = self._inhalt(nachricht)
        if not inhalt.strip():
            self.stdout.write('   Inhalt leer — übersprungen.')
            return

        TicketNachricht.objects.create(
            ticket=ticket, absender_name=absender, typ='mail_antwort',
            nachricht=inhalt, gelesen=False)
        ticket.gelesen = False
        ticket.save(update_fields=['gelesen'])
        self.stdout.write(self.style.SUCCESS(f'   In Ticket #{nummer} übernommen.'))

    @staticmethod
    def _betreff(nachricht):
        roh = nachricht.get('Subject')
        if not roh:
            return 'Kein Betreff'
        teile = []
        for inhalt, kodierung in decode_header(roh):
            if isinstance(inhalt, bytes):
                teile.append(inhalt.decode(kodierung or 'utf-8', errors='ignore'))
            else:
                teile.append(str(inhalt))
        return ''.join(teile)

    def _inhalt(self, nachricht):
        """HTML bevorzugt, sonst Text — und in beiden Fällen aufbereitet."""
        roh_html = roh_text = ''
        if nachricht.is_multipart():
            for teil in nachricht.walk():
                nutzlast = teil.get_payload(decode=True)
                if not nutzlast:
                    continue
                lesbar = nutzlast.decode('utf-8', errors='ignore')
                if teil.get_content_type() == 'text/html':
                    roh_html = lesbar
                elif teil.get_content_type() == 'text/plain':
                    roh_text = lesbar
        else:
            nutzlast = nachricht.get_payload(decode=True)
            if nutzlast:
                lesbar = nutzlast.decode('utf-8', errors='ignore')
                if nachricht.get_content_type() == 'text/html':
                    roh_html = lesbar
                else:
                    roh_text = lesbar
        if roh_html:
            return self.aufbereiten(roh_html)
        return self._zitat_abschneiden(roh_text or '').strip()

    def aufbereiten(self, html_inhalt):
        """HTML-Mail zu lesbarem Text.

        Der Umweg über einen Platzhalter ist Absicht: `strip_tags` wirft die
        Tags weg, ohne einen Umbruch zu hinterlassen — aus einer Mail mit zehn
        Absätzen würde sonst eine einzige Textwurst. Also erst die
        block-schliessenden Tags durch eine Marke ersetzen, dann entkernen,
        dann die Marke zum Umbruch machen.
        """
        if not html_inhalt:
            return ''
        text = html_inhalt
        text = re.sub(r'<br\s*/?>', PLATZHALTER, text, flags=re.IGNORECASE)
        text = re.sub(r'</(div|p|h[1-6]|table|tr|li|blockquote)>', PLATZHALTER, text,
                      flags=re.IGNORECASE)
        text = re.sub(r'<(div|p|h[1-6]|table|tr|li|blockquote)[^>]*>', PLATZHALTER, text,
                      flags=re.IGNORECASE)
        text = re.sub(r'</?(td|th)[^>]*>', ' ', text, flags=re.IGNORECASE)
        text = strip_tags(text)
        text = text.replace(PLATZHALTER, '\n')
        text = html.unescape(text).replace('\xa0', ' ')
        text = self._zitat_abschneiden(text)
        return self._leerzeilen_zusammenfassen(text)

    @staticmethod
    def _zitat_abschneiden(text):
        frueheste = len(text)
        for muster in ZITAT_MUSTER:
            treffer = re.search(muster, text, re.IGNORECASE)
            if treffer and treffer.start() < frueheste:
                frueheste = treffer.start()
        return text[:frueheste]

    @staticmethod
    def _leerzeilen_zusammenfassen(text):
        ergebnis = ''
        for zeile in (z.strip() for z in text.splitlines()):
            if zeile:
                ergebnis += zeile + '\n'
            elif not ergebnis.endswith('\n\n'):
                ergebnis += '\n'
        return ergebnis.strip()
