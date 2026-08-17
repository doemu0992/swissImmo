"""Die Sicherung — und vor allem: dass sie eine kaputte nicht durchwinkt.

Eine Sicherung, die niemand je zurückgespielt hat, ist eine Hoffnung. Diese
Tests prüfen deshalb nicht nur, dass eine Datei entsteht, sondern dass sie
lesbar ist, denselben Inhalt trägt, aus **einer** Datei besteht — und dass ein
beschädigter Stand verworfen statt gemeldet wird.
"""
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


def _quelldatenbank(ordner: Path, zeilen=25) -> Path:
    """Eine kleine SQLite-Datei, die aussieht wie die echte (im WAL-Modus)."""
    pfad = ordner / 'quelle.sqlite3'
    with closing(sqlite3.connect(pfad)) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT)')
        c.execute('CREATE TABLE crm_mieter (id INTEGER PRIMARY KEY, name TEXT)')
        c.executemany('INSERT INTO django_migrations (app) VALUES (?)',
                      [(f'app{i}',) for i in range(zeilen)])
        c.commit()
    return pfad


class SicherungTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.quelle = _quelldatenbank(self.tmp)
        self.ziel = self.tmp / 'ziel'
        self.medien = self.tmp / 'medien'
        (self.medien / 'vertraege').mkdir(parents=True)
        (self.medien / 'vertraege' / 'a.pdf').write_bytes(b'%PDF-1.4 test')
        (self.medien / 'b.jpg').write_bytes(b'\xff\xd8\xff test')

    def _sichern(self, **optionen):
        raus = StringIO()
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(self.quelle)}},
                MEDIA_ROOT=str(self.medien)):
            call_command('sicherung', ziel=str(self.ziel), stdout=raus, **optionen)
        return raus.getvalue()

    def test_sicherung_ist_lesbar_und_vollstaendig(self):
        self._sichern()
        stand = next(self.ziel.glob('*-db.sqlite3'))
        with closing(sqlite3.connect(f'file:{stand}?mode=ro', uri=True)) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('SELECT count(*) FROM django_migrations').fetchone()[0], 25)

    def test_sicherung_besteht_aus_genau_einer_datei(self):
        # Die Quelle läuft im WAL-Modus; die Sicherung erbt ihn, wenn man
        # nichts tut. Sie bestünde dann aus drei Dateien — und wer beim
        # Zurückspielen nur die Hauptdatei mitnimmt, verliert die letzten
        # Transaktionen, ohne dass irgendetwas fehlschlägt.
        self._sichern(ohne_medien=True)
        dateien = sorted(p.name for p in self.ziel.iterdir())
        self.assertEqual(len(dateien), 1, f'Erwartet genau eine Datei, gefunden: {dateien}')
        self.assertFalse(list(self.ziel.glob('*-wal')) + list(self.ziel.glob('*-shm')))

    def test_medien_kommen_mit(self):
        # Bei einer Hausverwaltung liegt ein grosser Teil der Kundendaten als
        # hochgeladene Datei vor, nicht in der Datenbank.
        self._sichern()
        archiv = next(self.ziel.glob('*-medien.tar.gz'))
        with tarfile.open(archiv, 'r:gz') as t:
            namen = [m.name for m in t if m.isfile()]
        self.assertEqual(len(namen), 2)
        self.assertTrue(any(n.endswith('a.pdf') for n in namen), namen)

    def test_ohne_medien_laesst_sie_weg(self):
        self._sichern(ohne_medien=True)
        self.assertEqual(list(self.ziel.glob('*-medien.tar.gz')), [])

    def test_leerer_medienordner_ist_kein_fehler(self):
        for p in sorted(self.medien.rglob('*'), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        ausgabe = self._sichern()
        self.assertIn('Keine Medien', ausgabe)


class BeschaedigungTests(SimpleTestCase):
    """Der wichtigste Test: Eine kaputte Sicherung darf nicht als gut gelten."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_leere_quelle_wird_verworfen(self):
        # Eine Datenbank ohne django_migrations ist keine swissImmo-Datenbank.
        # Sie zu sichern und Erfolg zu melden, wäre die schlechteste Antwort.
        quelle = self.tmp / 'leer.sqlite3'
        with closing(sqlite3.connect(quelle)) as c:
            c.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY)')
            c.commit()
        ziel = self.tmp / 'ziel'
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(quelle)}}):
            with self.assertRaises(CommandError) as fehler:
                call_command('sicherung', ziel=str(ziel), ohne_medien=True, stdout=StringIO())
        self.assertIn('leer', str(fehler.exception))
        # Und die unbrauchbare Datei bleibt NICHT liegen.
        self.assertEqual(list(ziel.glob('*-db.sqlite3')), [])

    def test_gegenprobe_gefuellte_quelle_geht_durch(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass der Test oben die
        # Leere misst und nicht einfach immer scheitert.
        quelle = _quelldatenbank(self.tmp)
        ziel = self.tmp / 'ziel2'
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(quelle)}}):
            call_command('sicherung', ziel=str(ziel), ohne_medien=True, stdout=StringIO())
        self.assertEqual(len(list(ziel.glob('*-db.sqlite3'))), 1)


class AufbewahrungTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.quelle = _quelldatenbank(self.tmp)
        self.ziel = self.tmp / 'ziel'
        self.ziel.mkdir()

    def _alte_staende(self, anzahl, kennung, inhalt=b'x'):
        for i in range(anzahl):
            (self.ziel / f'2026010{i}-000000{kennung}').write_bytes(inhalt)

    def test_datenbank_und_medien_werden_getrennt_aufbewahrt(self):
        # Getrennt, weil sich beide verschieden verhalten: Die Datenbank ist
        # klein und ändert sich täglich, das Medien-Archiv ist gross und kaum.
        self._alte_staende(6, '-db.sqlite3')
        self._alte_staende(6, '-medien.tar.gz')
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(self.quelle)}}):
            call_command('sicherung', ziel=str(self.ziel), ohne_medien=True,
                         behalten=3, medien_behalten=2, stdout=StringIO())
        # 6 alte + 1 neuer = 7, davon 3 behalten
        self.assertEqual(len(list(self.ziel.glob('*-db.sqlite3'))), 3)
        self.assertEqual(len(list(self.ziel.glob('*-medien.tar.gz'))), 2)

    def test_die_neuesten_bleiben(self):
        self._alte_staende(6, '-db.sqlite3')
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(self.quelle)}}):
            call_command('sicherung', ziel=str(self.ziel), ohne_medien=True,
                         behalten=2, stdout=StringIO())
        uebrig = sorted(p.name for p in self.ziel.glob('*-db.sqlite3'))
        # Der frisch erzeugte Stand (2026…) ist der jüngste und muss dabei sein.
        self.assertEqual(len(uebrig), 2)
        self.assertTrue(uebrig[-1] > '20260105', uebrig)

    def test_null_bedeutet_alles_behalten(self):
        self._alte_staende(5, '-db.sqlite3')
        with override_settings(
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                       'NAME': str(self.quelle)}}):
            call_command('sicherung', ziel=str(self.ziel), ohne_medien=True,
                         behalten=0, stdout=StringIO())
        self.assertEqual(len(list(self.ziel.glob('*-db.sqlite3'))), 6)
