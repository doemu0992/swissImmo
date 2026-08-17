"""Sicherung von Datenbank und hochgeladenen Dateien — motorunabhängig.

    python manage.py sicherung                  # nach ~/sicherungen/
    python manage.py sicherung --behalten 30    # mehr Stände aufbewahren
    python manage.py sicherung --ohne-medien    # nur die Datenbank

Drei Dinge, die dieser Befehl anders macht als ein `cp`:

**1. SQLite wird nicht kopiert, sondern gesichert.** Seit der Härtung läuft die
Datenbank im WAL-Modus. Dabei stehen bestätigte Transaktionen zunächst in einer
Nebendatei (`db.sqlite3-wal`) und wandern erst später in die Hauptdatei. Wer nur
`db.sqlite3` kopiert, bekommt auf einem laufenden Server einen Stand, dem die
letzten Buchungen fehlen — ohne dass irgendetwas fehlschlägt. Die
`sqlite3`-Sicherungsschnittstelle (`Connection.backup`) liest stattdessen einen
in sich stimmigen Stand, auch während geschrieben wird.

**2. Die Medien kommen mit.** Bei einer Hausverwaltung liegt ein erheblicher
Teil der Kundendaten nicht in der Datenbank, sondern als hochgeladene Datei:
Verträge, Belege, Schadensfotos. Eine Sicherung, die nur die Datenbank umfasst,
stellt im Ernstfall eine Verwaltung mit lauter toten Verweisen wieder her.

**3. Jede Sicherung wird gelesen, bevor sie als gelungen gilt.** Eine
Sicherungsdatei, die niemand je geöffnet hat, ist eine Hoffnung. SQLite-Stände
werden mit `PRAGMA integrity_check` und einer Zeilenzählung geprüft,
PostgreSQL-Stände mit `pg_restore --list`.

Was dieser Befehl NICHT leistet: Die Stände liegen auf demselben Rechner. Das
schützt gegen »versehentlich gelöscht« und gegen einen missratenen Deploy, aber
nicht gegen den Verlust des Kontos oder der Maschine. Eine Kopie ausser Haus
ist ein eigener Entscheid (externer Dienst, laufende Kosten) und bewusst nicht
Teil dieses Befehls.
"""
import os
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _lesbar(pfad: Path) -> str:
    groesse = pfad.stat().st_size
    for einheit in ('B', 'kB', 'MB', 'GB'):
        if groesse < 1024 or einheit == 'GB':
            return f'{groesse:.0f} {einheit}' if einheit == 'B' else f'{groesse:.1f} {einheit}'
        groesse /= 1024
    return f'{groesse:.1f} GB'


class Command(BaseCommand):
    help = 'Sichert Datenbank und Medien, prüft die Sicherung und räumt alte Stände ab.'

    def add_arguments(self, parser):
        parser.add_argument('--ziel', metavar='ORDNER',
                            help='Zielordner (Standard: ~/sicherungen).')
        parser.add_argument('--behalten', type=int, default=14, metavar='N',
                            help='So viele Datenbank-Stände aufbewahren (Standard: 14). 0 = alle.')
        parser.add_argument('--medien-behalten', type=int, default=4, metavar='N',
                            help='So viele Medien-Archive aufbewahren (Standard: 4). 0 = alle.')
        parser.add_argument('--ohne-medien', action='store_true',
                            help='Nur die Datenbank sichern.')

    def handle(self, *args, **optionen):
        ziel = Path(optionen['ziel'] or (Path.home() / 'sicherungen'))
        ziel.mkdir(parents=True, exist_ok=True)
        stempel = datetime.now().strftime('%Y%m%d-%H%M%S')

        self.stdout.write(f'→ Ziel: {ziel}')

        erzeugt = []
        if connection.vendor == 'sqlite':
            erzeugt.append(self._sqlite(ziel, stempel))
        elif connection.vendor == 'postgresql':
            erzeugt.append(self._postgres(ziel, stempel))
        else:
            raise CommandError(
                f'Für «{connection.vendor}» ist hier kein Weg hinterlegt. '
                f'Ohne geprüfte Sicherung bricht der Befehl lieber ab, als etwas '
                f'zu erzeugen, dessen Wiederherstellbarkeit niemand kennt.')

        if not optionen['ohne_medien']:
            medien = self._medien(ziel, stempel)
            if medien:
                erzeugt.append(medien)

        for pfad in erzeugt:
            self.stdout.write(f'  {pfad.name}  ({_lesbar(pfad)})')

        self._abraeumen(ziel, '-db.', optionen['behalten'], 'Datenbank')
        self._abraeumen(ziel, '-medien.', optionen['medien_behalten'], 'Medien')

        self.stdout.write(self.style.SUCCESS('✓ Sicherung erstellt und gelesen.'))

    # --- SQLite ------------------------------------------------------------

    def _sqlite(self, ziel: Path, stempel: str) -> Path:
        quelle = Path(str(settings.DATABASES['default']['NAME']))
        datei = ziel / f'{stempel}-db.sqlite3'

        # `closing`, nicht `with connect(...)`: Der Verbindungs-Kontextmanager
        # von sqlite3 verwaltet nur die TRANSAKTION, er schliesst die Verbindung
        # nicht. Ohne das explizite Schliessen bleiben Sperr- und WAL-Dateien
        # neben der Sicherung liegen.
        with closing(sqlite3.connect(f'file:{quelle}?mode=ro', uri=True)) as auf:
            with closing(sqlite3.connect(datei)) as ab:
                # `backup()` statt Dateikopie — siehe Kopf der Datei (WAL).
                auf.backup(ab)
                # Die Sicherung erbt den WAL-Modus der Quelle und bestünde damit
                # aus DREI Dateien. Wer beim Zurückspielen nur die Hauptdatei
                # mitnimmt, verliert die letzten Transaktionen — und merkt es
                # nicht. `DELETE` schreibt alles in die eine Datei zurück.
                ab.execute('PRAGMA journal_mode=DELETE')

        # Gelesen, nicht nur geschrieben: Struktur und Inhalt gegenprüfen.
        with closing(sqlite3.connect(f'file:{datei}?mode=ro', uri=True)) as pruef:
            befund = pruef.execute('PRAGMA integrity_check').fetchone()[0]
            if befund != 'ok':
                datei.unlink(missing_ok=True)
                raise CommandError(f'Sicherung unbrauchbar (integrity_check: {befund}) — verworfen.')
            tabellen = pruef.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            zeilen = pruef.execute('SELECT count(*) FROM django_migrations').fetchone()[0]

        # Eine Sicherung muss aus GENAU einer Datei bestehen.
        for rest in ('-wal', '-shm'):
            Path(str(datei) + rest).unlink(missing_ok=True)

        if tabellen < 2 or zeilen < 1:
            datei.unlink(missing_ok=True)
            raise CommandError(
                f'Sicherung wirkt leer ({tabellen} Tabellen, {zeilen} Migrationen) — verworfen.')

        self.stdout.write(f'· SQLite geprüft: {tabellen} Tabellen, {zeilen} Migrationen.')
        return datei

    # --- PostgreSQL --------------------------------------------------------

    def _postgres(self, ziel: Path, stempel: str) -> Path:
        konfig = settings.DATABASES['default']
        umgebung = {**os.environ}
        if konfig.get('PASSWORD'):
            # Über die Umgebung, nicht über die Kommandozeile — Argumente
            # stehen in der Prozessliste und sind für andere Nutzer lesbar.
            umgebung['PGPASSWORD'] = str(konfig['PASSWORD'])

        verbindung = [
            '-h', str(konfig.get('HOST') or 'localhost'),
            '-p', str(konfig.get('PORT') or 5432),
            '-U', str(konfig.get('USER') or ''),
            str(konfig.get('NAME') or ''),
        ]

        if shutil.which('pg_dump'):
            datei = ziel / f'{stempel}-db.dump'
            # -Fc: eigenes Format, komprimiert, erlaubt gezieltes
            # Wiederherstellen einzelner Tabellen mit pg_restore.
            lauf = subprocess.run(['pg_dump', '-Fc', '-f', str(datei), *verbindung],
                                  env=umgebung, capture_output=True, text=True)
            if lauf.returncode != 0:
                datei.unlink(missing_ok=True)
                raise CommandError(f'pg_dump fehlgeschlagen:\n{lauf.stderr.strip()}')

            if shutil.which('pg_restore'):
                pruef = subprocess.run(['pg_restore', '--list', str(datei)],
                                       capture_output=True, text=True)
                if pruef.returncode != 0 or not pruef.stdout.strip():
                    datei.unlink(missing_ok=True)
                    raise CommandError('Sicherung nicht lesbar (pg_restore --list) — verworfen.')
                eintraege = len([z for z in pruef.stdout.splitlines() if z and not z.startswith(';')])
                self.stdout.write(f'· pg_dump geprüft: {eintraege} Objekte im Stand.')
            else:
                self.stdout.write(self.style.WARNING(
                    '⚠ pg_restore fehlt — die Sicherung wurde NICHT gegengelesen.'))
            return datei

        # Kein pg_dump: lieber ein schwächerer Stand als gar keiner — aber
        # unter anderem Namen, damit bei der Wiederherstellung niemand das eine
        # für das andere hält. Ein stiller Rückfall wäre die schlechtere Wahl.
        self.stdout.write(self.style.WARNING(
            '⚠ pg_dump ist auf diesem Rechner nicht vorhanden.\n'
            '  Ersatzweise `dumpdata` — das sichert die DATEN, aber weder Sequenzen\n'
            '  noch Rechte, und die Wiederherstellung braucht ein vorheriges migrate.\n'
            '  Für einen vollwertigen Stand: postgresql-client installieren.'))
        datei = ziel / f'{stempel}-db.dumpdata.json'
        from django.core.management import call_command
        with open(datei, 'w', encoding='utf-8') as ausgabe:
            call_command('dumpdata', exclude=['contenttypes', 'auth.Permission'],
                         indent=1, stdout=ausgabe)
        if datei.stat().st_size < 100:
            datei.unlink(missing_ok=True)
            raise CommandError('dumpdata lieferte praktisch nichts — verworfen.')
        return datei

    # --- Medien ------------------------------------------------------------

    def _medien(self, ziel: Path, stempel: str) -> Path | None:
        wurzel = Path(settings.MEDIA_ROOT)
        if not wurzel.exists() or not any(wurzel.rglob('*')):
            self.stdout.write('· Keine Medien vorhanden — übersprungen.')
            return None

        datei = ziel / f'{stempel}-medien.tar.gz'
        with tarfile.open(datei, 'w:gz') as archiv:
            archiv.add(wurzel, arcname='media')

        # Gegengelesen: Ein leeres oder abgeschnittenes Archiv fällt hier auf.
        with tarfile.open(datei, 'r:gz') as archiv:
            anzahl = sum(1 for m in archiv if m.isfile())
        if anzahl == 0:
            datei.unlink(missing_ok=True)
            raise CommandError('Medien-Archiv enthält keine Datei — verworfen.')

        self.stdout.write(f'· Medien geprüft: {anzahl} Datei(en).')
        return datei

    # --- Aufräumen ---------------------------------------------------------

    def _abraeumen(self, ziel: Path, kennung: str, behalten: int, was: str):
        """Räumt eine Familie ab — Datenbank und Medien getrennt.

        Getrennt, weil sich beide unterschiedlich verhalten: Die Datenbank ist
        klein und ändert sich täglich, das Medien-Archiv ist gross und ändert
        sich kaum. Gemeinsam rotiert, müsste man sich zwischen »zu wenig
        Datenbank-Stände« und »Platte voll« entscheiden.
        """
        if behalten <= 0:
            return
        # Der Dateiname beginnt mit dem sortierbaren Zeitstempel, alphabetisch
        # sortiert ist also zugleich chronologisch.
        staende = sorted(p for p in ziel.iterdir() if p.is_file() and kennung in p.name)
        alt = staende[:-behalten] if len(staende) > behalten else []
        for p in alt:
            p.unlink()
        if alt:
            self.stdout.write(f'· {was}: {len(alt)} alte(r) Stand/Stände entfernt, {behalten} behalten.')
