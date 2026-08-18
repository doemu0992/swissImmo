"""E-Mail-Eingang für den KI-Rechnungsscanner — je Verwaltung ein Postfach.

Handwerker und Lieferanten senden ihre Rechnung an die Adresse ihrer
Verwaltung. Dieser Befehl holt ungelesene Mails ab, importiert jeden PDF-/
Bild-Anhang über den gemeinsamen Beleg-Import (`core.services.belegimport`) —
denselben KI-Scanner wie beim Upload — und legt Kreditorenrechnungen mit
Status «Neu» an.

WAS SICH AM 18.08.2026 GEÄNDERT HAT

Vorher: EIN Postfach aus den Umgebungsvariablen `RECHNUNGS_IMAP_USER` /
`_PASSWORD` / `_HOST`, für alle Verwaltungen dasselbe. Mit einer zweiten
Verwaltung wäre das eine Fehlzuordnung gewesen — die Rechnung von B landete im
Bestand von A, und aufgefallen wäre es niemandem.

Jetzt: `core.Postfach` je Verwaltung, Zweck «rechnungen». Die Zuordnung ist
damit **Voraussetzung** statt Ergebnis: Was in Postfach B liegt, gehört B.

**Kein stiller Rückfall auf die Umgebungsvariablen.** Eine Verwaltung ohne
eingerichtetes Postfach wird übersprungen und im Protokoll genannt.

Aufruf:
    python manage.py fetch_rechnungen --einmal        # ein Durchlauf (Scheduled Task)
    python manage.py fetch_rechnungen                 # Dauerschleife (alle 120 s)
    python manage.py fetch_rechnungen --einmal --verwaltung 3   # nur eine Verwaltung
"""
import logging
import time

from django.core.management.base import BaseCommand
from django.db import connections

from core.services.postfach_abruf import AbrufFehler, hole_ungelesene, postfaecher_fuer
from core.tenancy import organisation_kontext

logger = logging.getLogger(__name__)

PAUSE_SEKUNDEN = 120


class Command(BaseCommand):
    help = ('Holt Rechnungs-Mails je Verwaltung ab und importiert die Anhänge '
            'über den KI-Rechnungsscanner.')

    def add_arguments(self, parser):
        parser.add_argument('--einmal', action='store_true',
                            help='Nur ein Durchlauf (für Scheduled Tasks) statt Dauerschleife.')
        parser.add_argument('--verwaltung', type=int, default=None,
                            help='Nur diese Organisations-ID abrufen.')

    def handle(self, *args, **options):
        if options['einmal']:
            self.durchlauf(options['verwaltung'])
            return
        self.stdout.write(f'Rechnungs-Mail-Import gestartet (Schleife, alle {PAUSE_SEKUNDEN} s) …')
        while True:
            try:
                self.durchlauf(options['verwaltung'])
            except Exception as fehler:                        # noqa: BLE001
                # Die Schleife darf nicht sterben; ein Ausfall wäre sonst erst
                # bemerkt, wenn tagelang keine Rechnung mehr angekommen ist.
                logger.exception('Rechnungsabruf: Durchlauf abgebrochen')
                self.stdout.write(self.style.ERROR(f'Fehler im Lauf: {fehler}'))
            for verbindung in connections.all():
                verbindung.close()
            time.sleep(PAUSE_SEKUNDEN)

    def durchlauf(self, nur_verwaltung=None):
        from core.services.belegimport import importiere_rechnungsmail_bytes

        postfaecher = postfaecher_fuer('rechnungen')
        if nur_verwaltung is not None:
            postfaecher = postfaecher.filter(organisation_id=nur_verwaltung)

        if not postfaecher.exists():
            # Keine stille Null: Ohne diese Zeile sähe ein leerer Lauf genauso
            # aus wie ein Lauf ohne neue Mails.
            self.stdout.write(self.style.WARNING(
                'Kein eingerichtetes Rechnungs-Postfach gefunden. In den '
                'Einstellungen der Verwaltung unter «Postfächer» hinterlegen.'))
            return

        for postfach in postfaecher:
            self.stdout.write(f'{postfach.organisation} · {postfach.benutzer}')
            try:
                with organisation_kontext(postfach.organisation):
                    self._ein_postfach(postfach, importiere_rechnungsmail_bytes)
            except Exception as fehler:                        # noqa: BLE001
                # Dieselbe Zusage wie `je_organisation` (core/tenancy.py:171):
                # Ein Fehler bei Verwaltung 3 darf 4 bis 20 nicht ohne Abruf
                # lassen.
                logger.exception('%s: Abruf abgebrochen', postfach.organisation)
                self.stdout.write(self.style.ERROR(f'   FEHLER: {fehler}'))

    def _ein_postfach(self, postfach, importieren):
        def verarbeiten(roh):
            rechnungen = importieren(roh)
            if not rechnungen:
                self.stdout.write('   Mail ohne PDF-/Bild-Anhang — übersprungen.')
                return
            for rechnung in rechnungen:
                self.stdout.write(self.style.SUCCESS(
                    f'   Rechnung #{rechnung.id}: '
                    f'{rechnung.lieferant or "Lieferant unbekannt"} · '
                    f'CHF {rechnung.betrag or 0} '
                    f'({rechnung.fehlermeldung or "KI erkannt"})'))

        try:
            verarbeitet, fehlgeschlagen = hole_ungelesene(postfach, verarbeiten, self.stdout)
        except AbrufFehler as fehler:
            # Am Postfach vermerken, nicht nur ins Protokoll: Die Verwaltung
            # soll den Grund in ihren Einstellungen sehen, ohne dass jemand
            # ein Serverprotokoll aufmacht.
            postfach.fehler_vermerken(str(fehler))
            self.stdout.write(self.style.ERROR(f'   {fehler}'))
            return

        if fehlgeschlagen:
            postfach.fehler_vermerken(
                f'{fehlgeschlagen} von {verarbeitet + fehlgeschlagen} Mails liessen sich '
                'nicht verarbeiten. Einzelheiten im Serverprotokoll.')
        else:
            postfach.erfolg_vermerken()
