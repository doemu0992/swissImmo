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


class VmwgGegenFedlexTests(SimpleTestCase):
    """VMWG-Artikel gegen die Fassung auf fedlex.admin.ch (Stand 1. Oktober 2025), Abgleich 08.11.2026."""

    @staticmethod
    def _v(artikel):
        return next(r for r in REGISTER if r[0] == 'VMWG' and r[1] == artikel)

    def test_artikelnummern_stimmen_mit_den_titeln_ueberein(self):
        titel = {'3': 'Koppelung', '4': 'Nebenkosten im Allgemeinen', '5': 'Anrechenbare Heizungs',
                 '6': 'Nicht anrechenbare', '8': 'Abrechnung', '12': 'Kostensteigerung', '16': 'Teuerung',
                 '17': 'Indexierte', '18': 'Unvollständige', '19a': 'gestaffelten', '20': 'Begründungspflicht'}
        for art, stichwort in titel.items():
            self.assertIn(stichwort, self._v(art)[2], f'VMWG Art. {art}')

    def test_art_26_sind_uebergangsbestimmungen_und_kein_herabsetzungsverfahren(self):
        self.assertFalse([r for r in REGISTER if r[0] == 'VMWG' and r[1] == '26'])

    def test_art_17_nennt_30_tage_auf_ein_monatsende(self):
        self.assertIn('30 Tagen auf ein Monatsende', self._v('17')[3])

    def test_art_19a_vier_monate(self):
        self.assertIn('vier Monate', self._v('19a')[3])

    def test_art_12_ohne_verwaltungskosten_und_pauschale(self):
        t = self._v('12')[3]
        self.assertNotIn('Verwaltung', t)
        self.assertNotIn('Pauschale', t)


class Art269dNeufassung2025Tests(SimpleTestCase):
    """Art. 269d Abs. 4 und 5 OR (AS 2025 197, in Kraft seit 1.10.2025)."""

    def test_faksimile_nur_fuer_erhoehungen_nicht_fuer_kuendigungen(self):
        t = _text('269d')
        self.assertIn('Faksimile', t)
        self.assertIn('nicht bei Kündigungen', t)

    def test_staffelmiete_schriftform_und_vier_monate(self):
        t = _text('269d')
        self.assertIn('Schriftform', t)
        self.assertIn('vier Monate', t)


class FormularpflichtRegisterTests(SimpleTestCase):
    """Das Register der Kantone stimmt mit dem BWO-Verzeichnis 2026 überein (Abgleich 08.11.2026)."""

    def test_pflicht_und_ziffern(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton as f
        erwartet = {'BS': ('ja', '0.78 %'), 'BE': ('ja', '1.04 %'), 'FR': ('ja', '1.26 %'), 'GE': ('ja', '0.31 %'),
                    'LU': ('ja', '0.70 %'), 'NE': ('teilweise', '1.64 %'), 'VD': ('teilweise', '0.87 %'),
                    'VS': ('nein', '1.04 %'), 'ZG': ('ja', '0.20 %'), 'ZH': ('ja', '0.52 %')}
        for kt, (pflicht, ziffer) in erwartet.items():
            p, info = f(kt)
            self.assertEqual((p, info['leerziffer']), (pflicht, ziffer), kt)

    def test_rechtsgrundlagen_sind_nicht_mehr_pauschal(self):
        from core.services.formularpflicht import formularpflicht_fuer_kanton as f
        self.assertIn('§ 94 EGZGB', f('LU')[1]['gesetz'])
        self.assertIn('§ 10e EG OR', f('ZG')[1]['gesetz'])
        self.assertIn('1,8 %', f('FR')[1]['gesetz'])
        self.assertIn('Art. 135a EG ZGB (BSG 211.1)', f('BE')[1]['gesetz'])      # nicht Kantonsverfassung (BWO-Tippfehler)
        for kt in ('BS', 'BE', 'FR', 'GE', 'LU', 'ZG', 'ZH', 'NE', 'VD', 'VS'):
            self.assertNotIn('Kantonale Verordnung', f(kt)[1]['gesetz'], kt)
