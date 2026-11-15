"""Zugangslinks stehen nicht im Protokoll — weder beim Schreiben noch in der Anzeige älterer Zeilen.

Gegenprobe (15.11.2026): Filter aus einem Handler in `settings.LOGGING` entfernt -> Wächtertest rot;
`bereinigen` in `betreiber_protokoll.aus_log` entfernt -> Test der Anzeige rot.
"""
import io
import logging
import os
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core.logschutz import ERSATZ, GeheimnisFilter, alte_logdateien_loeschen, bereinigen
from core.services import betreiber_protokoll

GEHEIM = 'Zk3xQ9-geheim_Token-AbC123'


class BereinigenTests(SimpleTestCase):

    def test_pfade_mit_geheimnis(self):
        for roh in (f'/auftrag/{GEHEIM}/', f'/auftrag/{GEHEIM}/pdf/', f'/auftrag/{GEHEIM}/foto/3/',
                    f'/direkt/{GEHEIM}/', f'/aushang/{GEHEIM}/', f'https://x.ch/auftrag/{GEHEIM}',
                    f'/fristen.ics?token={GEHEIM}', f'/x/?a=1&token={GEHEIM}&b=2',
                    f'/passwort/neu/MTE/{GEHEIM}/'):
            with self.subTest(roh=roh):
                sauber = bereinigen(f'Internal Server Error: {roh}')
                self.assertNotIn(GEHEIM, sauber)
                self.assertIn(ERSATZ, sauber)

    def test_der_rest_der_adresse_bleibt_lesbar(self):
        self.assertEqual(bereinigen(f'/auftrag/{GEHEIM}/foto/3/'), f'/auftrag/{ERSATZ}/foto/3/')
        self.assertEqual(bereinigen(f'/x/?a=1&token={GEHEIM}&b=2'), f'/x/?a=1&token={ERSATZ}&b=2')

    def test_gewoehnliche_zeilen_bleiben_unveraendert(self):
        for text in ('Mail an a@b.ch gesendet: Ihre Meldung', 'Not Found: /neu/auftraege/', '/neu/vertraege/12/',
                     'Auftrag 7 (mahnlauf) eingereiht', '', None):
            self.assertEqual(bereinigen(text), text)


class FilterTests(SimpleTestCase):

    def _schreiben(self, *args, **kwargs):
        strom = io.StringIO()
        handler = logging.StreamHandler(strom)
        handler.addFilter(GeheimnisFilter())
        logger = logging.getLogger('test.logschutz')
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.error(*args, **kwargs)
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        return strom.getvalue()

    def test_meldung_mit_argumenten(self):
        zeile = self._schreiben('Internal Server Error: %s', f'/auftrag/{GEHEIM}/')
        self.assertNotIn(GEHEIM, zeile)
        self.assertIn('/auftrag/', zeile)

    def test_traceback(self):
        try:
            raise ValueError(f'kaputt bei /direkt/{GEHEIM}/')
        except ValueError:
            zeile = self._schreiben('Fehler', exc_info=True)
        self.assertIn('ValueError', zeile)
        self.assertNotIn(GEHEIM, zeile)

    def test_jeder_handler_der_anwendung_traegt_den_filter(self):
        """Wächter: Ein neuer Handler ohne Filter schriebe die Links wieder im Klartext."""
        self.assertEqual(settings.LOGGING['filters']['geheimnisse']['()'], 'core.logschutz.GeheimnisFilter')
        for name, handler in settings.LOGGING['handlers'].items():
            self.assertIn('geheimnisse', handler.get('filters', []), name)


class AnzeigeTests(SimpleTestCase):

    def test_aeltere_zeilen_werden_in_der_anzeige_gekuerzt(self):
        zeilen = [f'2026-11-01 10:00:00,000 ERROR django.request: Internal Server Error: /auftrag/{GEHEIM}/\n',
                  'Traceback (most recent call last):\n',
                  f'ValueError: kaputt bei /direkt/{GEHEIM}/\n']
        eintrag = betreiber_protokoll.aus_log(zeilen)[0]
        self.assertNotIn(GEHEIM, eintrag['titel'])
        self.assertNotIn(GEHEIM, eintrag['detail'])
        csv = betreiber_protokoll.als_csv([{**eintrag, 'quelle': 'anwendung'}], {'anwendung': 'Anwendung'})
        self.assertNotIn(GEHEIM, csv if isinstance(csv, str) else csv.content.decode())


class LoeschfristTests(SimpleTestCase):

    def test_nur_alte_rotierte_dateien_gehen(self):
        with tempfile.TemporaryDirectory() as ordner:
            haupt = Path(ordner) / 'app.log'
            alt, jung, fremd = haupt.with_name('app.log.3'), haupt.with_name('app.log.1'), Path(ordner) / 'anderes.txt'
            for datei in (haupt, alt, jung, fremd):
                datei.write_text('x')
            vor_100_tagen = time.time() - 100 * 86400
            for datei in (haupt, alt, fremd):
                os.utime(datei, (vor_100_tagen, vor_100_tagen))
            self.assertEqual(alte_logdateien_loeschen(90, haupt=haupt), 1)
            self.assertFalse(alt.exists())
            self.assertTrue(haupt.exists())          # die laufende Datei bleibt
            self.assertTrue(jung.exists())
            self.assertTrue(fremd.exists())
