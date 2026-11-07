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

**4. Eine verschlüsselte Kopie ausser Haus (Roadmap Nr. 12).** Mit `--offsite ORDNER`
und der Passphrase in der Umgebung (`SICHERUNG_SCHLUESSEL`) wird jeder frische Stand
AES-256-GCM-verschlüsselt in den Ordner gelegt (ein eingehängtes Laufwerk, ein
rclone-/sshfs-Mount …), mit einer Prüfsummenliste. Die Kopie wird sofort wieder
entschlüsselt und gegen die Prüfsumme gelesen. Aufbewahrung gestaffelt:
täglich 14, monatlich 12, jährlich 10 (OR 958f: zehn Jahre).

    python manage.py sicherung --offsite /mnt/ausser-haus
    python manage.py sicherung --entschluesseln DATEI.enc --nach DATEI

Was dieser Befehl NICHT leistet: Der Ordner hinter `--offsite` muss wirklich
ausser Haus liegen — das kann der Befehl nicht prüfen. Die Passphrase gehört
getrennt von den Sicherungen aufbewahrt (ohne sie ist die Kopie unlesbar).
"""
import hashlib
import json
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

from core.sicherung_krypto import (SicherungsFehler, entschluesseln, gfs_behalten, stempel_von,
                                   verschluesseln)

SCHLUESSEL_VARIABLE = 'SICHERUNG_SCHLUESSEL'


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


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
        parser.add_argument('--offsite', metavar='ORDNER',
                            help='Verschlüsselte Kopie ausser Haus (braucht %s).' % SCHLUESSEL_VARIABLE)
        parser.add_argument('--offsite-taeglich', type=int, default=14, metavar='N')
        parser.add_argument('--offsite-monate', type=int, default=12, metavar='N')
        parser.add_argument('--offsite-jahre', type=int, default=10, metavar='N')
        parser.add_argument('--entschluesseln', metavar='DATEI',
                            help='Eine verschlüsselte Sicherung (.enc) entschlüsseln und prüfen.')
        parser.add_argument('--nach', metavar='DATEI', help='Ausgabedatei für --entschluesseln.')

    def _passphrase(self) -> str:
        phrase = os.environ.get(SCHLUESSEL_VARIABLE, '')
        if len(phrase) < 12:
            raise CommandError(
                f'{SCHLUESSEL_VARIABLE} fehlt oder ist zu kurz (mindestens 12 Zeichen). '
                f'Ohne Passphrase wird nichts ausser Haus gelegt.')
        return phrase

    def handle(self, *args, **optionen):
        if optionen.get('entschluesseln'):
            return self._entschluesseln(optionen['entschluesseln'], optionen.get('nach'))
        if optionen.get('offsite'):
            self._passphrase()      # früh scheitern, bevor irgendetwas erzeugt wird
        ziel = Path(optionen['ziel'] or (Path.home() / 'sicherungen'))
        ziel.mkdir(parents=True, exist_ok=True)
        stempel = datetime.now().strftime('%Y%m%d-%H%M%S')

        self.stdout.write(f'→ Ziel: {ziel}')

        erzeugt = []
        art = self._datenbankart()
        if art == 'sqlite':
            erzeugt.append(self._sqlite(ziel, stempel))
        elif art == 'postgresql':
            erzeugt.append(self._postgres(ziel, stempel))
        else:
            raise CommandError(
                f'Für «{art}» ist hier kein Weg hinterlegt. '
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

        if optionen.get('offsite'):
            self._offsite(Path(optionen['offsite']), erzeugt, stempel, optionen)

        self.stdout.write(self.style.SUCCESS('✓ Sicherung erstellt und gelesen.'))

    # --- Ausser Haus ---------------------------------------------------------

    def _offsite(self, ort: Path, erzeugt, stempel, optionen):
        """Verschlüsselt die frischen Stände nach `ort`, liest sie zurück und räumt gestaffelt ab."""
        import tempfile
        phrase = self._passphrase()
        ort.mkdir(parents=True, exist_ok=True)
        manifest = {'stempel': stempel, 'dateien': []}
        for pfad in erzeugt:
            ziel = ort / (pfad.name + '.enc')
            klar_hash = _sha256(pfad)
            groesse = verschluesseln(pfad, ziel, phrase)
            # Zurückgelesen: Die Kopie gilt erst, wenn sie sich entschlüsseln lässt und der Prüfsumme entspricht.
            with tempfile.TemporaryDirectory() as tmp:
                probe = Path(tmp) / 'probe'
                try:
                    entschluesseln(ziel, probe, phrase)
                except SicherungsFehler as exc:
                    ziel.unlink(missing_ok=True)
                    raise CommandError(f'Ausser-Haus-Kopie von {pfad.name} nicht lesbar: {exc}') from exc
                if _sha256(probe) != klar_hash:
                    ziel.unlink(missing_ok=True)
                    raise CommandError(f'Ausser-Haus-Kopie von {pfad.name} weicht von der Sicherung ab — verworfen.')
            manifest['dateien'].append({'name': pfad.name, 'bytes': groesse, 'sha256': klar_hash,
                                        'verschluesselt': ziel.name, 'sha256_verschluesselt': _sha256(ziel)})
            self.stdout.write(f'  → ausser Haus: {ziel.name}')
        (ort / f'{stempel}-manifest.json').write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
        for kennung in ('-db.', '-medien.'):
            self._abraeumen_gestaffelt(ort, kennung, optionen)
        self._manifeste_abraeumen(ort)

    def _abraeumen_gestaffelt(self, ort: Path, kennung: str, optionen):
        dateien = [p for p in ort.iterdir() if p.is_file() and kennung in p.name and p.name.endswith('.enc')
                   and stempel_von(p.name)]
        behalten = gfs_behalten([stempel_von(p.name) for p in dateien], optionen['offsite_taeglich'],
                                optionen['offsite_monate'], optionen['offsite_jahre'])
        weg = [p for p in dateien if stempel_von(p.name) not in behalten]
        for p in weg:
            p.unlink()
        if weg:
            self.stdout.write(f'· Ausser Haus {kennung.strip("-.")}: {len(weg)} alte(r) Stand/Stände entfernt.')

    def _manifeste_abraeumen(self, ort: Path):
        """Prüfsummenlisten ohne zugehörige Dateien entfernen."""
        stempel_da = {p.name[:15] for p in ort.iterdir() if p.name.endswith('.enc')}
        for p in ort.glob('*-manifest.json'):
            if p.name[:15] not in stempel_da:
                p.unlink()

    def _entschluesseln(self, quelle, nach):
        quelle = Path(quelle)
        if not quelle.is_file():
            raise CommandError(f'Datei nicht gefunden: {quelle}')
        if not nach:
            raise CommandError('--nach DATEI fehlt (wohin soll entschlüsselt werden?).')
        ausgabe = Path(nach)
        if ausgabe.exists():
            raise CommandError(f'{ausgabe} existiert schon — nichts überschrieben.')
        try:
            n = entschluesseln(quelle, ausgabe, self._passphrase())
        except SicherungsFehler as exc:
            raise CommandError(str(exc)) from exc
        manifest = quelle.parent / f'{quelle.name[:15]}-manifest.json'
        if manifest.is_file():
            erwartet = {d['verschluesselt']: d['sha256']
                        for d in json.loads(manifest.read_text(encoding='utf-8'))['dateien']}.get(quelle.name)
            if erwartet and _sha256(ausgabe) != erwartet:
                ausgabe.unlink(missing_ok=True)
                raise CommandError('Prüfsumme stimmt nicht mit der Prüfsummenliste überein — verworfen.')
            self.stdout.write('· Prüfsumme gegen die Liste geprüft.')
        self.stdout.write(self.style.SUCCESS(f'✓ Entschlüsselt: {ausgabe} ({n} Byte).'))

    # --- SQLite ------------------------------------------------------------

    # --- Welche Datenbank? -------------------------------------------------

    def _datenbankart(self) -> str:
        """Die Art der Datenbank — aus DERSELBEN Quelle wie ihre Zugangsdaten.

        WARUM NICHT `connection.vendor`

        Bis E0.3 entschied `connection.vendor` den Weg, waehrend `_postgres`
        seine Zugangsdaten aus `settings.DATABASES['default']` las. Zwei
        Quellen fuer eine Sache. In der Produktion sagen beide dasselbe, im
        Test nicht: `test_sicherung` setzt per `override_settings` eine
        SQLite-Datei ein, die offene Verbindung bleibt aber PostgreSQL. Der
        Befehl lief deshalb auf einem PostgreSQL-Rechner in den pg_dump-Zweig
        und griff dort die SQLite-Konfiguration ab — ohne Host, Port und
        Benutzer. Ergebnis: `pg_dump` gegen localhost:5432, zehn rote Tests,
        und die Vermutung, die Sicherung sei kaputt. Kaputt war die Messung.

        Der Rueckfall auf `connection.vendor` bleibt fuer den Fall, dass eine
        unbekannte ENGINE eingetragen ist — dann soll die Fehlermeldung den
        tatsaechlichen Treiber nennen, nicht die Zeichenkette aus den Settings.
        """
        engine = str(self._konfig().get('ENGINE', ''))
        if 'sqlite' in engine:
            return 'sqlite'
        if 'postgresql' in engine or 'postgis' in engine:
            return 'postgresql'
        return connection.vendor

    def _konfig(self) -> dict:
        """Die Zugangsdaten der zu sichernden Datenbank."""
        return settings.DATABASES['default']

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
        konfig = self._konfig()
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
            # `all=True` → `_base_manager`. Ohne das nimmt dumpdata den
            # Default-Manager, und der filtert seit 6.2 auf den Mandanten —
            # eine Sicherung mit dem Bestand genau EINER Verwaltung, die wie
            # eine vollstaendige aussieht.
            call_command('dumpdata', exclude=['contenttypes', 'auth.Permission'],
                         all=True, indent=1, stdout=ausgabe)
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
