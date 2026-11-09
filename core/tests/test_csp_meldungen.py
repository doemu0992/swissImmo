"""Betreiber-Portal: CSP-Meldungen aus dem Log, zusammengefasst, ohne Tokens aus Adressen."""
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.services import csp_meldungen

ZEILE = ('2026-11-09 08:15:03,123 WARNING csp: CSP-Verstoss: {regel} | blockiert={blockiert} | Seite={seite} | Zeile={zeile}')


class LesenTests(SimpleTestCase):

    def test_gleiche_meldungen_werden_gezaehlt(self):
        z = ZEILE.format(regel='script-src-elem', blockiert='inline', seite='https://x.ch/neu/', zeile='12')
        e = csp_meldungen.lesen([z, z, z, 'irgendeine andere Zeile'])
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]['anzahl'], e[0]['regel'], e[0]['blockiert']), (3, 'script-src-elem', 'inline'))

    def test_abfrageteil_und_lange_tokens_fallen_weg(self):
        z = ZEILE.format(regel='style-src', blockiert='inline', zeile='1',
                         seite='https://x.ch/portal/abc?token=geheim123&x=1#frag')
        e = csp_meldungen.lesen([z])
        self.assertEqual(e[0]['seite'], 'https://x.ch/portal/abc')
        self.assertNotIn('geheim', str(e))
        lang = ZEILE.format(regel='r', blockiert='b', zeile='1', seite='https://x.ch/handwerker/' + 'A' * 40 + '/')
        self.assertNotIn('A' * 30, str(csp_meldungen.lesen([lang])))

    def test_haeufigste_zuerst(self):
        a = ZEILE.format(regel='a', blockiert='x', seite='/s1', zeile='1')
        b = ZEILE.format(regel='b', blockiert='x', seite='/s2', zeile='1')
        e = csp_meldungen.lesen([a, b, b])
        self.assertEqual([x['regel'] for x in e], ['b', 'a'])


class SeiteTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / 'swissimmo.log'
        logging = {'handlers': {'file': {'filename': str(self.log)}}}
        ue = override_settings(LOGGING=logging)
        ue.enable()
        self.addCleanup(ue.disable)
        self.c = Client()
        self.c.force_login(get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12))

    def test_nur_der_betreiber(self):
        from ._helfer import _team_user
        team = Client()
        team.force_login(_team_user())
        self.assertEqual(team.get('/betreiber/csp/').status_code, 403)
        self.assertEqual(Client().get('/betreiber/csp/').status_code, 302)

    def test_ohne_logdatei_steht_ein_klarer_hinweis(self):
        antwort = self.c.get('/betreiber/csp/')
        self.assertContains(antwort, 'nicht lesbar oder noch nicht angelegt')

    def test_leeres_log_ist_ruhig(self):
        self.log.write_text('2026-11-09 08:00:00,000 INFO x: alles gut\n', encoding='utf-8')
        antwort = self.c.get('/betreiber/csp/')
        self.assertContains(antwort, 'Keine Verstösse')

    def test_meldungen_erscheinen_ohne_token(self):
        self.log.write_text(
            ZEILE.format(regel='script-src-elem', blockiert='inline', zeile='9',
                         seite='https://x.ch/neu/vertraege/?token=geheim123') + '\n', encoding='utf-8')
        antwort = self.c.get('/betreiber/csp/')
        self.assertContains(antwort, 'script-src-elem')
        self.assertContains(antwort, 'https://x.ch/neu/vertraege/')
        self.assertNotContains(antwort, 'geheim123')
