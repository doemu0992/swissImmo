"""E-Mail-Eingang für den KI-Rechnungsscanner.

Handwerker/Lieferanten senden ihre Rechnung an eine dedizierte Mailbox
(z.B. rechnung@immoswiss.app). Dieses Command holt ungelesene Mails per IMAP
ab, importiert jeden PDF-/Bild-Anhang über den gemeinsamen Beleg-Import
(core.services.belegimport) — d.h. derselbe KI-Scanner wie beim Upload —
und legt Kreditorenrechnungen mit Status «Neu» an. Die Herkunft
(«Per E-Mail von …») steht am Datensatz und ist im Edit-Panel sichtbar.

Konfiguration (Umgebungsvariablen / .env):
    RECHNUNGS_IMAP_USER      Mailbox-Login (z.B. rechnung@immoswiss.app)
    RECHNUNGS_IMAP_PASSWORD  Passwort
    RECHNUNGS_IMAP_HOST      IMAP-Server (Default: lx37.hoststar.hosting)

Aufruf:
    python manage.py fetch_rechnungen --einmal   # ein Durchlauf (Scheduled Task)
    python manage.py fetch_rechnungen            # Dauerschleife (alle 120 s)
"""
import logging
import imaplib
import os
import time

from django.core.management.base import BaseCommand
from django.db import connections

logger = logging.getLogger(__name__)



class Command(BaseCommand):
    help = 'Holt Rechnungs-Mails ab und importiert Anhänge über den KI-Rechnungsscanner.'

    def add_arguments(self, parser):
        parser.add_argument('--einmal', action='store_true',
                            help='Nur ein Durchlauf (für Scheduled Tasks) statt Dauerschleife.')

    def handle(self, *args, **options):
        if options['einmal']:
            self.check_mails()
            return
        self.stdout.write("🚀 Rechnungs-Mail-Import gestartet (Schleife, alle 120 s) …")
        while True:
            try:
                self.check_mails()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"💥 Fehler im Loop: {e}"))
            for conn in connections.all():
                conn.close()
            time.sleep(120)

    def check_mails(self):
        from core.services.belegimport import importiere_rechnungsmail_bytes
        user = os.environ.get('RECHNUNGS_IMAP_USER')
        passwort = os.environ.get('RECHNUNGS_IMAP_PASSWORD')
        host = os.environ.get('RECHNUNGS_IMAP_HOST', 'lx37.hoststar.hosting')
        if not user or not passwort:
            self.stdout.write(self.style.ERROR(
                '❌ RECHNUNGS_IMAP_USER / RECHNUNGS_IMAP_PASSWORD fehlen (.env) — '
                'E-Mail-Eingang für Rechnungen nicht konfiguriert.'))
            return

        mail = imaplib.IMAP4_SSL(host)
        try:
            mail.login(user, passwort)
            mail.select('inbox')
            _, nachrichten = mail.search(None, 'UNSEEN')
            ids = nachrichten[0].split()
            if not ids:
                self.stdout.write("   (Verbunden, keine neuen Rechnungs-Mails)")
                return
            self.stdout.write(self.style.SUCCESS(f"📨 {len(ids)} neue Mail(s)"))
            for i in ids:
                try:
                    _, daten = mail.fetch(i, '(RFC822)')
                    for teil in daten:
                        if isinstance(teil, tuple):
                            rechnungen = importiere_rechnungsmail_bytes(teil[1])
                            if rechnungen:
                                for r in rechnungen:
                                    self.stdout.write(self.style.SUCCESS(
                                        f"✅ Rechnung #{r.id}: {r.lieferant or 'Lieferant unbekannt'}"
                                        f" · CHF {r.betrag or 0} ({r.fehlermeldung or 'KI erkannt'})"))
                            else:
                                self.stdout.write("ℹ️ Mail ohne PDF-/Bild-Anhang — übersprungen.")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"❌ Fehler bei Mail: {e}"))
        finally:
            try:
                mail.close()
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
            try:
                mail.logout()
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
