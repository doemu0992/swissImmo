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
import logging
import time
from email.header import decode_header

from django.core.management.base import BaseCommand
from django.db import connections

from core.services.antwort_eingang import (ZITAT_MUSTER as ZITAT_MUSTER_GEMEINSAM, html_zu_text,
                                           leerzeilen_zusammenfassen, zitat_abschneiden)
from core.services.postfach_abruf import AbrufFehler, hole_ungelesene, postfaecher_fuer
from core.tenancy import organisation_kontext

logger = logging.getLogger(__name__)

PAUSE_SEKUNDEN = 60

ZITAT_MUSTER = ZITAT_MUSTER_GEMEINSAM
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
                'Kein eigenes Antwort-Postfach (IMAP) eingerichtet. Antworten kommen '
                'über die Plattformadresse (Einstellungen, E-Mail-Eingang).'))

        from core.funktionen import hintergrund_erlaubt
        mit_postfach = set()
        for postfach in postfaecher:
            mit_postfach.add(postfach.organisation_id)
            self.stdout.write(f'{postfach.organisation} · {postfach.benutzer}')
            if not hintergrund_erlaubt(postfach.organisation):
                self.stdout.write('   Abonnement im Lesemodus (Zahlung überfällig) — übersprungen.')
                continue
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
        self._ohne_postfach(nur_verwaltung, mit_postfach)

    def _ohne_postfach(self, nur_verwaltung, mit_postfach):
        """Verwaltungen ohne eigenes Postfach antworten über die Plattformadresse (Webhook). Dort gibt es
        nichts abzuholen, aber gebündelte Chat-Nachrichten des Direktkanals warten auf ihre Mail."""
        from core.tenancy import je_organisation
        from tickets.direktkanal import ausstehende_zustellen

        def zustellen(organisation):
            if organisation.pk not in mit_postfach:
                ausstehende_zustellen()

        _ergebnisse, fehler = je_organisation(zustellen, auswahl=nur_verwaltung, ausgabe=self.stdout)
        for organisation, ausnahme in fehler:
            logger.error('%s: Zustellung gebündelter Chat-Nachrichten fehlgeschlagen: %s', organisation, ausnahme)

    def _ein_postfach(self, postfach):
        try:
            verarbeitet, fehlgeschlagen = hole_ungelesene(
                postfach, self.verarbeite_mail, self.stdout)
        except AbrufFehler as fehler:
            postfach.fehler_vermerken(str(fehler))
            self.stdout.write(self.style.ERROR(f'   {fehler}'))
            return

        # Gebündelte Chat-Nachrichten, deren Fenster vorbei ist, als Mail an die Gegenseite (Direktkanal).
        try:
            from tickets.direktkanal import ausstehende_zustellen
            ausstehende_zustellen()
        except Exception:                                      # noqa: BLE001
            logger.exception('%s: Zustellung gebündelter Chat-Nachrichten fehlgeschlagen', postfach.organisation)
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
        from core.services.antwort_eingang import eingehende_antwort_verarbeiten, ticketnummer_aus_betreff
        from core.tenancy import aktuelle_organisation

        nachricht = email.message_from_bytes(roh)
        betreff = self._betreff(nachricht)
        absender = nachricht.get('From', 'Unbekannt')
        self.stdout.write(f'   Prüfe: {betreff}')

        nummer = ticketnummer_aus_betreff(betreff, locker=False)
        if not nummer:
            self.stdout.write('   Keine Ticketnummer im Betreff — übersprungen.')
            return
        inhalt = self._inhalt(nachricht)
        if not inhalt.strip():
            self.stdout.write('   Inhalt leer — übersprungen.')
            return

        # Dieselbe Zuordnung wie beim Webhook (core/services/antwort_eingang.py): Ticketnummer NUR in dieser
        # Verwaltung (gefilterter Manager), Auftragsmarke «[A12]» -> Direktkanal Mieter/Handwerker.
        seite = eingehende_antwort_verarbeiten(aktuelle_organisation(), absender, betreff, inhalt,
                                               kopf=dict(nachricht.items()), locker=False)
        if seite == 'ohne_ticket':
            self.stdout.write(self.style.WARNING(
                f'   Ticket #{nummer} gibt es in dieser Verwaltung nicht — übersprungen.'))
            return
        if seite.startswith('direkt_'):
            self.stdout.write(self.style.SUCCESS(
                f'   In Ticket #{nummer} im Chat übernommen und der Gegenseite zugestellt ({seite[7:]}).'))
            return
        self.stdout.write(self.style.SUCCESS(
            f'   In Ticket #{nummer} übernommen ({"Handwerker" if seite == "handwerker" else "Melder"}).'))

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
        """HTML-Mail zu lesbarem Text (gemeinsam mit dem Webhook: ``antwort_eingang.html_zu_text``)."""
        return html_zu_text(html_inhalt)

    @staticmethod
    def _zitat_abschneiden(text):
        return zitat_abschneiden(text)

    @staticmethod
    def _leerzeilen_zusammenfassen(text):
        return leerzeilen_zusammenfassen(text)
