"""Stresstest 30.09.2026: Herabsetzungsbegehren als Vorgang mit 30 Tagen Antwortfrist (Art. 270a OR)."""
from datetime import date, timedelta

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class HerabsetzungTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.c = Client(); self.c.force_login(_team_user('Sachbearbeiter'))
        self.url = f'/neu/vertraege/{self.v.id}/herabsetzung/'

    def _eingang(self, datum=None):
        return self.c.post(self.url, {'aktion': 'eingang',
                                      'eingang_datum': (datum or self.heute).isoformat()}, secure=True)

    def test_begehren_erzeugt_frist_pendenz_mit_30_tagen(self):
        from core.models import Pendenz
        eingang = self.heute - timedelta(days=5)
        self._eingang(eingang)
        p = Pendenz.objects.get(vertrag=self.v, quelle__startswith='270a:')
        self.assertEqual(p.faellig_am, eingang + timedelta(days=30))
        self.assertEqual(p.kategorie, 'frist')
        self.assertFalse(p.erledigt)

    def test_doppelt_erfasst_ergibt_eine_pendenz(self):
        from core.models import Pendenz
        self._eingang(); self._eingang()
        self.assertEqual(Pendenz.objects.filter(quelle__startswith='270a:').count(), 1)

    def test_eingang_in_der_zukunft_wird_abgewiesen(self):
        from core.models import Pendenz
        self._eingang(self.heute + timedelta(days=3))
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='270a:').exists())

    def test_ablehnung_schliesst_die_frist_und_legt_die_anrufungsfrist_an(self):
        from core.models import Pendenz
        self._eingang()
        p = Pendenz.objects.get(quelle__startswith='270a:')
        self.c.post(self.url, {'aktion': 'antwort', 'pendenz': p.id, 'ergebnis': 'ablehnung',
                               'antwort_datum': self.heute.isoformat()}, secure=True)
        p.refresh_from_db()
        self.assertTrue(p.erledigt)
        self.assertIn('Ablehnung', p.beschreibung)
        info = Pendenz.objects.get(quelle__startswith='270a-anrufung:')
        self.assertEqual(info.faellig_am, self.heute + timedelta(days=30))

    def test_zustimmung_schliesst_ohne_anrufungsfrist(self):
        from core.models import Pendenz
        self._eingang()
        p = Pendenz.objects.get(quelle__startswith='270a:')
        self.c.post(self.url, {'aktion': 'antwort', 'pendenz': p.id, 'ergebnis': 'zustimmung'}, secure=True)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='270a-anrufung:').exists())

    def test_antwort_ohne_ergebnis_aendert_nichts(self):
        from core.models import Pendenz
        self._eingang()
        p = Pendenz.objects.get(quelle__startswith='270a:')
        self.c.post(self.url, {'aktion': 'antwort', 'pendenz': p.id, 'ergebnis': 'egal'}, secure=True)
        p.refresh_from_db()
        self.assertFalse(p.erledigt)

    def test_seite_laedt_und_lesende_duerfen_nicht_erfassen(self):
        self.assertEqual(self.c.get(self.url, secure=True).status_code, 200)
        c2 = Client(); c2.force_login(_team_user('Lesend'))
        self.assertEqual(c2.post(self.url, {'aktion': 'eingang'}, secure=True).status_code, 403)
