"""Ruft das Plattform-Postfach ab (Sammelpostfach beim Hoster, Catch-all der ANTWORT_DOMAIN) und verarbeitet die Mails.

Anders als ``fetch_replies`` / ``fetch_rechnungen`` gibt es hier EIN Postfach für alle Verwaltungen: die
Empfängeradresse (``<kennung>@…`` Antworten, ``<kennung>-rechnungen@…`` Rechnungen) sagt, wem eine Mail gehört. Die
Zugangsdaten stehen in der ``.env`` (``PLATTFORM_IMAP_HOST``, ``_PORT``, ``_BENUTZER``, ``_PASSWORT``, ``_ORDNER``).
Zuordnung, Verarbeitung, Wiederholung und Aufräumen: ``core/services/plattform_postfach.py``.

Aufruf:
    python manage.py fetch_plattform_eingang --einmal       # ein Durchlauf (Scheduled Task, so oft der Hoster erlaubt)
    python manage.py fetch_plattform_eingang --dauerlauf    # Schleife alle 60 s (Always-on-Task)

Nur EINE der beiden Formen gleichzeitig laufen lassen. Ohne Angabe läuft ein einzelner Durchlauf.
Nicht eingerichtet (PLATTFORM_IMAP_* fehlt): freundliche Meldung, Ende ohne Fehler.
"""
import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.services import plattform_postfach as pp
from core.services.postfach_abruf import AbrufFehler

logger = logging.getLogger(__name__)

PAUSE_SEKUNDEN = 60


class Command(BaseCommand):
    help = 'Holt Mails aus dem Plattform-Postfach (Sammelpostfach) ab und ordnet sie den Verwaltungen zu.'

    def add_arguments(self, parser):
        gruppe = parser.add_mutually_exclusive_group()
        gruppe.add_argument('--einmal', action='store_true',
                            help='Ein Durchlauf (für Scheduled Tasks). Vorgabe, wenn nichts angegeben ist.')
        gruppe.add_argument('--dauerlauf', action='store_true',
                            help=f'Schleife alle {PAUSE_SEKUNDEN} s (für Always-on-Tasks); beendet sich sauber bei '
                                 'SIGTERM/SIGINT.')

    def handle(self, *args, **options):
        if pp.konfiguration() is None:
            self.stdout.write(self.style.WARNING(
                'Plattform-Postfach nicht eingerichtet: PLATTFORM_IMAP_HOST, PLATTFORM_IMAP_BENUTZER und '
                'PLATTFORM_IMAP_PASSWORT fehlen in der .env. Nichts zu tun. Anleitung: docs/ANTWORTADRESSEN.md '
                '(Variante A).'))
            return
        if not options['dauerlauf']:
            self.durchlauf()
            return
        self._stopp = threading.Event()
        self._signale_einrichten()
        self.stdout.write(f'Abruf des Plattform-Postfachs gestartet (Schleife, alle {PAUSE_SEKUNDEN} s) …')
        while not self._stopp.is_set():
            try:
                self.durchlauf()
            except Exception as fehler:                        # noqa: BLE001
                # Die Schleife darf nicht sterben; ein Ausfall wäre sonst erst bemerkt, wenn tagelang nichts
                # mehr angekommen ist. Der Fehler steht im Status und im Serverprotokoll.
                logger.exception('Plattform-Postfach: Durchlauf abgebrochen')
                self.stdout.write(self.style.ERROR(f'Fehler im Lauf: {fehler}'))
            close_old_connections()
            if self._warten(PAUSE_SEKUNDEN):
                break
        self.stdout.write('Abruf des Plattform-Postfachs beendet.')

    def _warten(self, sekunden):
        """Wartet bis zum nächsten Lauf. ``True``, wenn zwischenzeitlich beendet werden soll."""
        return self._stopp.wait(sekunden)

    def _signale_einrichten(self):
        def beenden(_nummer, _rahmen):
            self.stdout.write('Beenden angefordert, der laufende Durchlauf wird noch abgeschlossen …')
            self._stopp.set()
        for nummer in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(nummer, beenden)
            except ValueError:
                # nicht im Hauptthread (Tests); dann gibt es nichts zu verdrahten
                logger.debug('Signal %s nicht verdrahtet (kein Hauptthread)', nummer)

    def zustellen(self):
        """Gebündelte Chat-Nachrichten des Direktkanals zustellen (alle Verwaltungen).

        Mieter und Handwerker schreiben im Chat; geht innerhalb von 5 Minuten eine zweite Nachricht
        derselben Seite hinaus, wartet sie auf diesen Lauf — ebenso eine Mail, die beim ersten Versuch
        nicht rausging. Früher kam das nur von ``fetch_replies``; wo nur der Plattform-Eingang läuft,
        blieben solche Nachrichten für immer liegen."""
        from core.tenancy import je_organisation
        from tickets.direktkanal import ausstehende_zustellen
        _ergebnisse, fehler = je_organisation(lambda _organisation: ausstehende_zustellen())
        for organisation, ausnahme in fehler:
            logger.error('%s: Zustellung gebündelter Chat-Nachrichten fehlgeschlagen: %s', organisation, ausnahme)

    def durchlauf(self):
        # Zuerst zustellen: ein Ausfall des Postfach-Abrufs darf ausgehende Chat-Mails nicht aufhalten.
        try:
            self.zustellen()
        except Exception:                                      # noqa: BLE001
            logger.exception('Plattform-Postfach: Zustellung gebündelter Chat-Nachrichten fehlgeschlagen')
        try:
            zahlen = pp.abrufen(ausgabe=self.stdout.write)
        except AbrufFehler as fehler:
            self.stdout.write(self.style.ERROR(f'FEHLER: {fehler}'))
            return None
        self.stdout.write(self.style.SUCCESS(
            f"verarbeitet: {zahlen['verarbeitet']}, ignoriert: {zahlen['ignoriert']}, "
            f"aufgegeben: {zahlen['aufgegeben']}, fehlgeschlagen: {zahlen['fehlgeschlagen']}, "
            f"gelöscht: {zahlen['geloescht']}"))
        return zahlen
