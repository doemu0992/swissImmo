"""Die Zusammenfassungen im Gesetzesregister stimmen mit dem Wortlaut des OR überein (Abgleich 08.11.2026).

Quelle des Abgleichs: Obligationenrecht, Achter Titel «Die Miete» (Art. 253–274g). Verbindlich ist die amtliche Fassung
auf fedlex.admin.ch; diese Tests halten fest, was beim Abgleich falsch war, damit es nicht zurückkehrt.
"""
from django.test import SimpleTestCase

from core.services.gesetzestexte import REGISTER


def _text(artikel):
    return next(r[3] for r in REGISTER if r[0] == 'OR' and r[1] == artikel)


class GesetzestexteGegenOrTests(SimpleTestCase):

    def test_erstreckung_frist_30_tage_unbefristet_60_tage_befristet(self):
        t = _text('273')
        self.assertIn('30 Tage ab Empfang der Kündigung', t)
        self.assertIn('60 Tage vor Ablauf', t)
        self.assertNotIn('bis 30 Tage vor Ablauf', t)               # frühere, falsche Fassung

    def test_kuendigungsfristen_nennen_die_mietdauer_ohne_ortsgebrauch(self):
        self.assertIn('sechsmonatigen Mietdauer', _text('266b'))
        self.assertIn('sechs Monate', _text('266d'))
        for art in ('266c', '266d'):
            self.assertIn('dreimonatigen Mietdauer', _text(art))

    def test_266h_ist_der_konkurs_nicht_die_zahlungsunfaehigkeit(self):
        t = _text('266h')
        self.assertIn('Konkurs', t)
        self.assertNotIn('Zahlungsunfähigkeit', t)

    def test_271a_handaenderung_ist_kein_anfechtungsgrund(self):
        t = _text('271a')
        self.assertNotIn('Handänderung', t)
        self.assertIn('Kauf der Wohnung', t)
        self.assertIn('drei Jahre', t)
