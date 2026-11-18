"""Verschlüsselte Werte auf den aktuellen (ersten) Schlüssel umstellen — Schlüsselwechsel ohne Verlust.

    python manage.py schluessel_wechseln               # nur prüfen: was ist womit lesbar?
    python manage.py schluessel_wechseln --ausfuehren  # umschreiben

ABLAUF EINES SCHLÜSSELWECHSELS (z. B. jährlich, oder bei Verdacht):
  1. Neuen Schlüssel erzeugen:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. In der `.env` den neuen Schlüssel VOR den alten stellen (durch Komma getrennt):
       GEHEIMNIS_SCHLUESSEL=<NEU>,<ALT>
     Web-App neu laden. Ab jetzt wird mit <NEU> verschlüsselt, mit beiden gelesen.
  3. `python manage.py schluessel_wechseln --ausfuehren` schreibt alle Werte auf <NEU> um.
  4. Erst wenn der Befehl «alles auf dem aktuellen Schlüssel» meldet: <ALT> aus der `.env` nehmen,
     Web-App neu laden. Sicherungen, die vor Schritt 3 entstanden sind, brauchen <ALT> zum Zurückspielen.

Gerechnet wird mit SQL auf der Spalte, nicht über die Felder: Die Werte werden nur umgeschrieben, nie
im Klartext gehalten oder protokolliert. Läuft in EINER Transaktion: Bricht etwas ab, bleibt alles wie vorher.
"""
from django.core.management.base import BaseCommand, CommandError

from core.services import geheimnis, geheimnis_pflege


class Command(BaseCommand):
    help = 'Prüft und stellt verschlüsselte Werte auf den ersten (aktuellen) Schlüssel um.'

    def add_arguments(self, parser):
        parser.add_argument('--ausfuehren', action='store_true',
                            help='Umschreiben (ohne diese Angabe wird nur geprüft).')

    def handle(self, *args, **optionen):
        if not geheimnis.schluessel_vorhanden():
            raise CommandError(f'{geheimnis.NEUER_NAME} ist nicht gesetzt.')
        z = geheimnis_pflege.zustand()
        self.stdout.write(f'{z.schluessel_anzahl} Schlüssel gesetzt; der erste ist der aktuelle.')
        self.stdout.write(f'· schon auf dem aktuellen Schlüssel: {z.aktuell}')
        self.stdout.write(f'· auf den aktuellen Schlüssel umzuschreiben: {z.alt}')
        if z.klartext:
            self.stdout.write(f'· noch unverschlüsselt (Altbestand): {z.klartext} — wird beim Umstellen mit erledigt')
        if z.unlesbar:
            self.stderr.write(self.style.ERROR(
                f'· mit KEINEM gesetzten Schlüssel lesbar: {len(z.unlesbar)} (z. B. {", ".join(z.unlesbar[:5])}). '
                'Der alte Schlüssel fehlt in der Liste, oder die Werte sind verloren.'))
        if not optionen['ausfuehren']:
            self.stdout.write('Nur geprüft. Zum Umschreiben: --ausfuehren')
            return
        geheimnis_pflege.nachholen()
        n, unlesbar = geheimnis_pflege.umstellen()
        if unlesbar:
            raise CommandError('Umgeschrieben, was lesbar war. Unlesbare Werte bleiben unverändert: '
                               'fehlenden alten Schlüssel ergänzen und erneut ausführen.')
        self.stdout.write(self.style.SUCCESS(
            f'✓ {n} Werte umgeschrieben; alles liegt auf dem aktuellen Schlüssel. '
            'Jetzt darf der alte Schlüssel aus der Liste.'))
