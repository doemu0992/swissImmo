"""Priorität «Notfall»: im Meldeformular wählbar, in Frist und Sortierung wirksam.

Ohne Eintrag in `PRIO_RANG` würde ein Notfall-Ticket wie «mittel» einsortiert (Vorgabewert
der Rangtabelle) — die Stufe stünde im Formular, ohne etwas zu bewirken.
"""
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation
from django.test import Client, TestCase


class NotfallTests(TestCase):
    def setUp(self):
        _seed_konten()
        self.org = _test_organisation()
        self.lg, *_ = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def _melden(self, titel, prio):
        from tickets.models import SchadenMeldung
        self.c.post('/neu/schaeden/neu/', {'titel': titel, 'liegenschaft_id': self.lg.id,
                                           'beschreibung': 'x', 'prioritaet': prio})
        return SchadenMeldung.objects.get(titel=titel)

    def test_notfall_hat_frist_heute_und_steht_im_formular(self):
        t = self._melden('Rohrbruch', 'notfall')
        self.assertEqual(t.prioritaet, 'notfall')
        self.assertEqual(t.faellig_bis, timezone.localdate())
        self.assertContains(self.c.get('/neu/schaeden/'), 'value="notfall"')

    def test_unbekannte_prioritaet_faellt_auf_mittel(self):
        t = self._melden('Irgendwas', 'dringendst')
        self.assertEqual(t.prioritaet, 'mittel')

    def test_notfall_steht_vor_hoch_und_mittel(self):
        from faelle.schaeden import PRIO_RANG
        self.assertLess(PRIO_RANG['notfall'], PRIO_RANG['hoch'])
        self._melden('Ticket-M-qx', 'mittel')
        self._melden('Ticket-H-qx', 'hoch')
        self._melden('Ticket-N-qx', 'notfall')
        html = self.c.get('/neu/schaeden/?sicht=').content.decode()
        n, h, m = (html.index(f'Ticket-{k}-qx') for k in 'NHM')
        self.assertLess(n, h)
        self.assertLess(h, m)
