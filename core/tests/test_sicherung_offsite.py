"""Roadmap Nr. 12: verschlüsselte Kopie ausser Haus, Prüfsummen, gestaffelte Aufbewahrung."""
import json
import os
import shutil
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.sicherung_krypto import (SicherungsFehler, entschluesseln, gfs_behalten, stempel_von,
                                   verschluesseln)

from .test_sicherung import _quelldatenbank

PHRASE = 'eine-lange-test-passphrase'


class KryptoTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.klar = self.tmp / 'klar'
        self.klar.write_bytes(os.urandom(2_300_000))          # mehr als zwei Blöcke

    def test_roundtrip_ueber_mehrere_bloecke(self):
        enc, aus = self.tmp / 'k.enc', self.tmp / 'aus'
        verschluesseln(self.klar, enc, PHRASE)
        entschluesseln(enc, aus, PHRASE)
        self.assertEqual(aus.read_bytes(), self.klar.read_bytes())

    def test_geheimtext_enthaelt_den_klartext_nicht(self):
        self.klar.write_bytes(b'GEHEIMER-INHALT-' * 1000)
        enc = self.tmp / 'k.enc'
        verschluesseln(self.klar, enc, PHRASE)
        self.assertNotIn(b'GEHEIMER-INHALT', enc.read_bytes())

    def test_falsche_passphrase_scheitert_und_hinterlaesst_nichts(self):
        enc, aus = self.tmp / 'k.enc', self.tmp / 'aus'
        verschluesseln(self.klar, enc, PHRASE)
        with self.assertRaises(SicherungsFehler):
            entschluesseln(enc, aus, 'eine-ganz-andere-phrase')
        self.assertFalse(aus.exists())

    def test_abgeschnittene_datei_wird_erkannt(self):
        enc, aus = self.tmp / 'k.enc', self.tmp / 'aus'
        verschluesseln(self.klar, enc, PHRASE)
        daten = enc.read_bytes()
        enc.write_bytes(daten[:len(daten) - 1_100_000])      # letzten Block(e) weg
        with self.assertRaises(SicherungsFehler):
            entschluesseln(enc, aus, PHRASE)

    def test_abschneiden_an_blockgrenze_wird_erkannt(self):
        """Der Fall, den nur die Kennung «letzter Block» im AAD abfängt: ganze Blöcke am Ende fehlen."""
        import struct
        enc, aus = self.tmp / 'k.enc', self.tmp / 'aus'
        verschluesseln(self.klar, enc, PHRASE)
        daten = enc.read_bytes()
        pos, grenzen = 6 + 24, []
        while pos < len(daten):
            (n,) = struct.unpack('>I', daten[pos:pos + 4])
            pos += 4 + n
            grenzen.append(pos)
        self.assertGreaterEqual(len(grenzen), 3)
        enc.write_bytes(daten[:grenzen[-2]])                  # letzten Block sauber abgetrennt
        with self.assertRaises(SicherungsFehler):
            entschluesseln(enc, aus, PHRASE)
        self.assertFalse(aus.exists())

    def test_veraenderte_datei_wird_erkannt(self):
        enc, aus = self.tmp / 'k.enc', self.tmp / 'aus'
        verschluesseln(self.klar, enc, PHRASE)
        daten = bytearray(enc.read_bytes())
        daten[5000] ^= 0xFF
        enc.write_bytes(bytes(daten))
        with self.assertRaises(SicherungsFehler):
            entschluesseln(enc, aus, PHRASE)

    def test_leere_datei_geht(self):
        leer, enc, aus = self.tmp / 'leer', self.tmp / 'l.enc', self.tmp / 'aus'
        leer.write_bytes(b'')
        verschluesseln(leer, enc, PHRASE)
        entschluesseln(enc, aus, PHRASE)
        self.assertEqual(aus.read_bytes(), b'')


class AufbewahrungTests(SimpleTestCase):
    def test_zehn_jahre_bleiben_je_ein_stand_pro_jahr(self):
        # Ein Stand pro Tag seit 2014: Nach der Auswahl bleiben die jüngsten 14, 12 Monatsenden, 10 Jahresenden.
        tage = [datetime(2014, 1, 1) + __import__('datetime').timedelta(days=i) for i in range(0, 4350)]
        behalten = gfs_behalten(tage, 14, 12, 10)
        jahre = {s.year for s in behalten}
        self.assertTrue(set(range(2017, 2026)) <= jahre)               # die letzten Jahre sind alle da
        for jahr in range(2017, 2025):
            letzter = max(s for s in tage if s.year == jahr)
            self.assertIn(letzter, behalten)                           # Jahresende bleibt
        self.assertLess(len(behalten), 14 + 12 + 10 + 1)               # und es wird nicht alles behalten

    def test_aelter_als_zehn_jahre_darf_weg(self):
        tage = [datetime(2010, 12, 31), datetime(2020, 6, 30), datetime(2026, 1, 5)]
        behalten = gfs_behalten(tage, 1, 1, 10)
        self.assertNotIn(datetime(2010, 12, 31), behalten)
        self.assertIn(datetime(2020, 6, 30), behalten)

    def test_jungste_staende_bleiben_immer(self):
        tage = [datetime(2026, 1, d) for d in range(1, 21)]
        behalten = gfs_behalten(tage, 14, 0, 0)
        self.assertEqual(len(behalten), 14)
        self.assertIn(datetime(2026, 1, 20), behalten)

    def test_stempel_aus_dateiname(self):
        self.assertEqual(stempel_von('20260817-030000-db.dump.enc'), datetime(2026, 8, 17, 3, 0, 0))
        self.assertIsNone(stempel_von('notizen.txt'))


class BefehlTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.quelle = _quelldatenbank(self.tmp)
        self.ziel, self.offsite = self.tmp / 'ziel', self.tmp / 'ausser-haus'
        self.medien = self.tmp / 'medien'
        self.medien.mkdir()
        (self.medien / 'a.pdf').write_bytes(b'%PDF-1.4 test')

    def _lauf(self, **optionen):
        raus = StringIO()
        umgebung = {'SICHERUNG_SCHLUESSEL': PHRASE} if optionen.pop('mit_schluessel', True) else {}
        with override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                                                      'NAME': str(self.quelle)}},
                               MEDIA_ROOT=str(self.medien)), \
                mock.patch.dict(os.environ, umgebung, clear=False):
            if not umgebung:
                os.environ.pop('SICHERUNG_SCHLUESSEL', None)
            call_command('sicherung', ziel=str(self.ziel), stdout=raus, **optionen)
        return raus.getvalue()

    def test_offsite_legt_verschluesselte_kopie_mit_pruefsummenliste_ab(self):
        self._lauf(offsite=str(self.offsite))
        enc = sorted(p.name for p in self.offsite.glob('*.enc'))
        self.assertEqual(len(enc), 2)                                     # Datenbank + Medien
        self.assertTrue(all(n.endswith('.enc') for n in enc))
        manifest = json.loads(next(self.offsite.glob('*-manifest.json')).read_text())
        self.assertEqual(len(manifest['dateien']), 2)
        # Kein Klartext ausser Haus.
        self.assertFalse([p for p in self.offsite.iterdir() if not p.name.endswith(('.enc', '.json'))])

    def test_offsite_ohne_passphrase_bricht_ab_bevor_etwas_entsteht(self):
        with self.assertRaises(CommandError):
            self._lauf(offsite=str(self.offsite), mit_schluessel=False)
        self.assertFalse(self.ziel.exists() and any(self.ziel.iterdir()))
        self.assertFalse(self.offsite.exists())

    def test_entschluesseln_stellt_den_stand_her(self):
        self._lauf(offsite=str(self.offsite))
        enc = next(self.offsite.glob('*-db.sqlite3.enc'))
        aus = self.tmp / 'wieder.sqlite3'
        with mock.patch.dict(os.environ, {'SICHERUNG_SCHLUESSEL': PHRASE}):
            call_command('sicherung', entschluesseln=str(enc), nach=str(aus), stdout=StringIO())
        original = next(self.ziel.glob('*-db.sqlite3'))
        self.assertEqual(aus.read_bytes(), original.read_bytes())

    def test_entschluesseln_mit_falscher_phrase_scheitert(self):
        self._lauf(offsite=str(self.offsite))
        enc = next(self.offsite.glob('*-db.sqlite3.enc'))
        with mock.patch.dict(os.environ, {'SICHERUNG_SCHLUESSEL': 'falsche-phrase-1234'}):
            with self.assertRaises(CommandError):
                call_command('sicherung', entschluesseln=str(enc), nach=str(self.tmp / 'x'), stdout=StringIO())
        self.assertFalse((self.tmp / 'x').exists())

    def test_entschluesseln_ueberschreibt_nichts(self):
        self._lauf(offsite=str(self.offsite))
        enc = next(self.offsite.glob('*-db.sqlite3.enc'))
        vorhanden = self.tmp / 'da'
        vorhanden.write_bytes(b'wichtig')
        with mock.patch.dict(os.environ, {'SICHERUNG_SCHLUESSEL': PHRASE}):
            with self.assertRaises(CommandError):
                call_command('sicherung', entschluesseln=str(enc), nach=str(vorhanden), stdout=StringIO())
        self.assertEqual(vorhanden.read_bytes(), b'wichtig')
