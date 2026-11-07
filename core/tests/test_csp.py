"""Roadmap Nr. 23, Etappe 1: Content-Security-Policy mit Nonce (zunächst nur melden) und eine Ratsche für Inline-Code."""
import json
import logging
import pathlib
import re
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase, override_settings

from core import csp

from ._helfer import _team_user
from .csp_handler_stand import KOMMENTAR, zaehlen

STAND = pathlib.Path(__file__).with_name('csp_handler_stand.json')


class RichtlinieTests(SimpleTestCase):

    def test_richtlinie_enthaelt_nonce_und_sperrt_fremdes(self):
        r = csp.richtlinie('ABC123')
        self.assertIn("script-src 'self' 'nonce-ABC123'", r)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", r)
        for erwartet in ("object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'", "form-action 'self'",
                         f'report-uri {csp.BERICHT_PFAD}'):
            self.assertIn(erwartet, r)

    def test_modus_faellt_bei_unsinn_auf_report_only_zurueck(self):
        for wert, soll in (('enforce', 'enforce'), ('AUS', 'aus'), ('quatsch', 'report-only'), ('', 'report-only')):
            with override_settings(CSP_MODUS=wert):
                self.assertEqual(csp.modus(), soll, wert)


class MiddlewareTests(TestCase):

    def _seite(self, url='/login/'):
        return Client().get(url)

    def test_vorgabe_ist_report_only_und_blockiert_nichts(self):
        antwort = self._seite()
        self.assertIn(csp.HEADER_REPORT, antwort)
        self.assertNotIn(csp.HEADER_ENFORCE, antwort)

    def test_nonce_im_kopf_passt_zu_den_skripten_der_seite(self):
        c = Client()
        c.force_login(_team_user())
        antwort = c.get('/neu/')
        nonce = re.search(r"'nonce-([^']+)'", antwort[csp.HEADER_REPORT]).group(1)
        html = antwort.content.decode()
        inline = [m for m in re.finditer(r'<script\b([^>]*)>', html) if 'src=' not in m.group(1)
                  and 'application/json' not in m.group(1)]
        self.assertGreater(len(inline), 0)
        for m in inline:
            self.assertIn(f'nonce="{nonce}"', m.group(1), 'Inline-Skript ohne den Nonce dieser Antwort')

    def test_nonce_wechselt_je_anfrage(self):
        a = re.search(r"'nonce-([^']+)'", self._seite()[csp.HEADER_REPORT]).group(1)
        b = re.search(r"'nonce-([^']+)'", self._seite()[csp.HEADER_REPORT]).group(1)
        self.assertNotEqual(a, b)

    @override_settings(CSP_MODUS='enforce')
    def test_enforce_setzt_den_sperrenden_kopf(self):
        antwort = self._seite()
        self.assertIn(csp.HEADER_ENFORCE, antwort)
        self.assertNotIn(csp.HEADER_REPORT, antwort)

    @override_settings(CSP_MODUS='aus')
    def test_aus_setzt_keinen_kopf(self):
        antwort = self._seite()
        self.assertNotIn(csp.HEADER_ENFORCE, antwort)
        self.assertNotIn(csp.HEADER_REPORT, antwort)


class BerichtsstelleTests(TestCase):

    def _melden(self, daten, **extra):
        return Client().post(csp.BERICHT_PFAD, data=daten if isinstance(daten, str) else json.dumps(daten),
                             content_type='application/csp-report', **extra)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_bericht_wird_geloggt_und_mit_204_beantwortet(self):
        bericht = {'csp-report': {'violated-directive': "script-src-attr", 'blocked-uri': 'inline',
                                  'document-uri': 'https://x.ch/neu/', 'line-number': 12}}
        with self.assertLogs('csp', level=logging.WARNING) as erfasst:
            antwort = self._melden(bericht)
        self.assertEqual(antwort.status_code, 204)
        self.assertIn('script-src-attr', erfasst.output[0])
        self.assertIn('inline', erfasst.output[0])

    def test_neues_berichtsformat_wird_gelesen(self):
        bericht = [{'type': 'csp-violation', 'body': {'effectiveDirective': 'script-src-elem',
                                                       'blockedURL': 'https://fremd.example/x.js'}}]
        with self.assertLogs('csp', level=logging.WARNING) as erfasst:
            self.assertEqual(self._melden(bericht).status_code, 204)
        self.assertIn('fremd.example', erfasst.output[0])

    def test_unsinn_und_zu_grosses_wird_abgewiesen(self):
        self.assertEqual(self._melden('kein json').status_code, 400)
        self.assertEqual(self._melden('x' * 9000).status_code, 413)

    def test_nur_post(self):
        self.assertEqual(Client().get(csp.BERICHT_PFAD).status_code, 405)

    def test_flut_wird_gedeckelt(self):
        codes = []
        with mock.patch.object(csp.logger, 'warning'):
            for _ in range(65):
                codes.append(self._melden({'csp-report': {'violated-directive': 'x'}}).status_code)
        self.assertEqual(codes[:60], [204] * 60)
        self.assertIn(429, codes[60:])

    def test_text_in_meldung_kann_das_log_nicht_zerlegen(self):
        with self.assertLogs('csp', level=logging.WARNING) as erfasst:
            self._melden({'csp-report': {'blocked-uri': 'a\nGEFAELSCHTE ZEILE'}})
        self.assertEqual(len(erfasst.output), 1)
        self.assertNotIn('\nGEFAELSCHTE', erfasst.output[0])


class RatscheTests(SimpleTestCase):
    """Inline-Code darf nicht zunehmen — der Weg zu `CSP_MODUS=enforce` ist, dass die Zahl auf null sinkt."""

    def test_jedes_inline_skript_traegt_einen_nonce(self):
        ohne = []
        for pfad in sorted(pathlib.Path('core/templates').rglob('*.html')):
            text = KOMMENTAR.sub(' ', pfad.read_text(encoding='utf-8'))
            for m in re.finditer(r'<script\b([^>]*)>', text):
                a = m.group(1)
                if 'src=' not in a and 'nonce=' not in a and 'application/json' not in a:
                    ohne.append(str(pfad))
        self.assertEqual(ohne, [], 'Inline-<script> ohne nonce="{{ csp_nonce }}" würde mit CSP blockiert.')

    def test_inline_handler_nehmen_nicht_zu(self):
        soll = json.loads(STAND.read_text(encoding='utf-8'))
        ist = zaehlen()
        mehr = {d: (soll.get(d, 0), n) for d, n in ist.items() if n > soll.get(d, 0)}
        self.assertEqual(mehr, {}, 'Neue Inline-Handler (onclick= …): bitte per addEventListener/Datenattribut '
                                   'in static/js lösen, nicht in die Vorlage schreiben.')

    def test_gesunkene_zahlen_werden_nachgefuehrt(self):
        soll = json.loads(STAND.read_text(encoding='utf-8'))
        ist = zaehlen()
        weniger = {d: (n, ist.get(d, 0)) for d, n in soll.items() if ist.get(d, 0) < n}
        self.assertEqual(weniger, {}, 'Handler wurden entfernt: core/tests/csp_handler_stand.json nachführen '
                                      '(Befehl im Kopf von csp_handler_stand.py).')

    def test_zaehler_erkennt_handler(self):
        """Gegenprobe: Der Zähler sieht einen Handler (sonst wäre die Ratsche blind)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'a.html').write_text('<button onclick="x()">a</button><a onClick=\'y()\'>b</a>'
                                                       '{# <i onclick="z()"> #}')
            self.assertEqual(zaehlen(tmp), {'a.html': 2})
