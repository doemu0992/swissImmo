"""Roadmap Nr. 10: die Rolle «Revision» — nur lesen, nur Journal und Logbuch.

* Positivliste: genau diese Views nennen die Revision.
* Sie öffnet Journal, Kontenplan, Abschluss-PDF und Logbuch, aber keine Stammdaten,
  Verträge, Personen oder Einstellungen, und sie schreibt nirgends.
* Ihre Abrufe (Export, PDF, Logbuch-CSV) stehen im Audit-Log.
* Landung nach dem Login ist das Journal; der zweite Faktor ist Pflicht.
"""
from django.contrib.auth import get_user_model
from django.test import Client

from core.models import AktivitaetsLog
from crm.models import Mitgliedschaft

from ._rollen import RollenBasis
from .test_rolle_buchhaltung import _alle_views

REVISION_DARF = {
    'fw_buchhaltung', 'fw_buchhaltung_export', 'fw_buchhaltung_pdf', 'fw_kontoblatt',
    'fw_kontenplan', 'fw_logbuch',
}

GESPERRT = [
    '/neu/personen/', '/neu/vertraege/', '/neu/liegenschaften/', '/neu/dokumente/',
    '/neu/debitoren/', '/neu/kreditoren/', '/neu/benutzer/', '/neu/einstellungen/',
    '/neu/kommunikation/', '/neu/schaeden/',
]


class RevisionTests(RollenBasis):

    def setUp(self):
        u = get_user_model().objects.create_user(username='revisor', password='x', email='rev@example.ch')
        Mitgliedschaft.alle_organisationen.create(benutzer=u, organisation=self.org, rolle='Revision')
        self.revisor = u
        self.c = Client(raise_request_exception=False)
        self.c.force_login(u)

    def test_positivliste(self):
        gefunden = {name for _m, name, rollen in _alle_views() if rollen and 'Revision' in rollen}
        self.assertEqual(gefunden, REVISION_DARF,
                         f'zu viel: {sorted(gefunden - REVISION_DARF)}; fehlt: {sorted(REVISION_DARF - gefunden)}')

    def test_journal_und_logbuch_sind_offen(self):
        for url in ('/neu/buchhaltung/', '/neu/kontenplan/', '/neu/logbuch/'):
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_stammdaten_und_einstellungen_sind_gesperrt(self):
        for url in GESPERRT:
            self.assertEqual(self.c.get(url).status_code, 403, url)

    def test_schreiben_ist_gesperrt(self):
        for url in ('/neu/buchhaltung/neu/', '/neu/benutzer/neu/'):
            antwort = self.c.post(url, {})
            self.assertIn(antwort.status_code, (403, 404, 405), url)

    def test_abruf_steht_im_audit_log(self):
        vorher = AktivitaetsLog.alle_organisationen.filter(aktion__startswith='Abruf').count()
        self.c.get('/neu/logbuch/?export=csv')
        self.c.get('/neu/buchhaltung/pdf/')
        nachher = AktivitaetsLog.alle_organisationen.filter(
            aktion__startswith='Abruf', benutzer=self.revisor).count()
        self.assertGreater(AktivitaetsLog.alle_organisationen.filter(aktion__startswith='Abruf').count(), vorher)
        self.assertGreaterEqual(nachher, 1)

    def test_login_fuehrt_ins_journal(self):
        antwort = self.c.get('/nach-login/')
        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(antwort['Location'].endswith('/neu/buchhaltung/'))

    def test_zweiter_faktor_ist_pflicht(self):
        from core.auth import ZWEIFAKTOR_PFLICHT_ROLLEN
        self.assertIn('Revision', ZWEIFAKTOR_PFLICHT_ROLLEN)

    def test_buchhaltung_sieht_das_logbuch_weiterhin_nicht(self):
        self.assertEqual(self.client_von('buchhaltung').get('/neu/logbuch/').status_code, 403)
