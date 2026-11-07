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
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.services import geheimnis

#: Alles, was mit dem Schlüssel verschlüsselt in der Datenbank steht: (App, Modell, Feld).
#: Neue verschlüsselte Spalten gehören HIER hinein — sonst überleben sie keinen Schlüsselwechsel.
GEHEIME_FELDER = (
    ('core', 'Postfach', 'passwort_geheim'),
    ('core', 'Postfach', 'refresh_token_geheim'),
    ('crm', 'Mieter', 'ahv_nummer'),
)


def _spalte(app, modell, feld):
    m = apps.get_model(app, modell)
    return m._meta.db_table, m._meta.get_field(feld).column, m._meta.pk.column


class Command(BaseCommand):
    help = 'Prüft und stellt verschlüsselte Werte auf den ersten (aktuellen) Schlüssel um.'

    def add_arguments(self, parser):
        parser.add_argument('--ausfuehren', action='store_true',
                            help='Umschreiben (ohne diese Angabe wird nur geprüft).')

    def handle(self, *args, **optionen):
        if not geheimnis.schluessel_vorhanden():
            raise CommandError(f'{geheimnis.NEUER_NAME} ist nicht gesetzt.')
        anzahl = len(geheimnis._schluesselliste())
        self.stdout.write(f'{anzahl} Schlüssel gesetzt; der erste ist der aktuelle.')

        umschreiben, unlesbar, aktuell = [], [], 0
        with connection.cursor() as cur:
            for app, modell, feld in GEHEIME_FELDER:
                tabelle, spalte, pk = _spalte(app, modell, feld)
                cur.execute(f'SELECT "{pk}", "{spalte}" FROM "{tabelle}" WHERE "{spalte}" <> %s', [''])
                for zeile_pk, wert in cur.fetchall():
                    if not geheimnis_aussehen(wert):
                        continue                    # Alt-Bestand im Klartext: das macht `ahv_verschluesseln`
                    if geheimnis.mit_erstem_schluessel_lesbar(wert):
                        aktuell += 1
                        continue
                    try:
                        neu = geheimnis.neu_verschluesseln(wert)
                    except geheimnis.GeheimtextKaputt:
                        unlesbar.append(f'{app}.{modell}.{feld} #{zeile_pk}')
                        continue
                    umschreiben.append((tabelle, spalte, pk, zeile_pk, neu))

        self.stdout.write(f'· schon auf dem aktuellen Schlüssel: {aktuell}')
        self.stdout.write(f'· auf den aktuellen Schlüssel umzuschreiben: {len(umschreiben)}')
        if unlesbar:
            self.stderr.write(self.style.ERROR(
                f'· mit KEINEM gesetzten Schlüssel lesbar: {len(unlesbar)} (z. B. {", ".join(unlesbar[:5])}). '
                'Der alte Schlüssel fehlt in der Liste, oder die Werte sind verloren.'))

        if not optionen['ausfuehren']:
            self.stdout.write('Nur geprüft. Zum Umschreiben: --ausfuehren')
            return
        with transaction.atomic(), connection.cursor() as cur:
            for tabelle, spalte, pk, zeile_pk, neu in umschreiben:
                cur.execute(f'UPDATE "{tabelle}" SET "{spalte}" = %s WHERE "{pk}" = %s', [neu, zeile_pk])
        if unlesbar:
            raise CommandError('Umgeschrieben, was lesbar war. Unlesbare Werte bleiben unverändert: '
                               'fehlenden alten Schlüssel ergänzen und erneut ausführen.')
        self.stdout.write(self.style.SUCCESS(
            f'✓ {len(umschreiben)} Werte umgeschrieben; alles liegt auf dem aktuellen Schlüssel. '
            'Jetzt darf der alte Schlüssel aus der Liste.'))


def geheimnis_aussehen(wert):
    from core.verschluesselt import sieht_verschluesselt_aus
    return sieht_verschluesselt_aus(wert)
