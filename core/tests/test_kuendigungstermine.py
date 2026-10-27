"""Kündigungstermine aus dem Freitextfeld des Vertrags (Befund E, 26.10.2026).

Bis zu dieser Fassung las `_erlaubte_termin_monate` Ziffern wie «31.03., 30.06.,
30.09.» und ein leeres Feld als «jedes Monatsende». Ein Vertrag mit drei
Quartalsterminen wurde dadurch bis zu zwei Monate zu früh kündbar gerechnet —
und dieselbe Rechnung bestimmt den frühesten Termin einer Mietzinserhöhung.
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from ._helfer import _basis_objekte, _test_organisation


class ParserTests(SimpleTestCase):
    def test_ziffern_werden_gelesen(self):
        from rentals.services import kuendigungstermine_parsen
        self.assertEqual(kuendigungstermine_parsen('31.03., 30.06., 30.09.'),
                         [(31, 3), (30, 6), (30, 9)])

    def test_ziffern_ohne_schlusspunkt_und_mit_jahr(self):
        from rentals.services import kuendigungstermine_parsen
        self.assertEqual(kuendigungstermine_parsen('30.6 und 31.12.2027'), [(30, 6), (31, 12)])

    def test_monatsnamen_wie_bisher(self):
        from rentals.services import kuendigungstermine_parsen
        self.assertEqual(kuendigungstermine_parsen('Ende März, Juni, September'),
                         [(31, 3), (31, 6), (31, 9)])

    def test_jedes_monatsende_ausser_dezember(self):
        from rentals.services import kuendigungstermine_parsen
        termine = kuendigungstermine_parsen('Ende jedes Monats ausser Dezember')
        self.assertEqual(len(termine), 11)
        self.assertNotIn((31, 12), termine)

    def test_ausschluss_per_ziffer(self):
        from rentals.services import kuendigungstermine_parsen
        termine = kuendigungstermine_parsen('Ende jedes Monats ausser 31.12.')
        self.assertEqual(len(termine), 11)
        self.assertNotIn((31, 12), termine)

    def test_leer_und_unlesbar_heisst_nichts_erkannt(self):
        from rentals.services import kuendigungstermine_parsen
        self.assertIsNone(kuendigungstermine_parsen(''))
        self.assertIsNone(kuendigungstermine_parsen('ortsüblich'))


class BerechnungTests(TestCase):
    def _v(self, termine, frist=3):
        _lg, _e, _m, v = _basis_objekte()
        v.kuendigungstermine = termine
        v.kuendigungsfrist_monate = frist
        v.save()
        return v

    def test_quartalstermine_in_ziffern(self):
        """Eingang 26.10.2026 + 3 Monate = 26.01.2027 → nächster Termin 31.03.2027,
        nicht 31.01.2027 wie bei «jedes Monatsende»."""
        from rentals.services import berechne_kuendigungstermin
        v = self._v('31.03., 30.06., 30.09.')
        self.assertEqual(berechne_kuendigungstermin(v, date(2026, 10, 26)), date(2027, 3, 31))

    def test_genannter_tag_gilt(self):
        from rentals.services import berechne_kuendigungstermin
        v = self._v('31.03., 30.06., 30.09.')
        self.assertEqual(berechne_kuendigungstermin(v, date(2027, 3, 1)), date(2027, 6, 30))

    def test_naechster_anpassungstermin_folgt_den_terminen(self):
        from rentals.services import naechster_anpassungstermin
        v = self._v('31.03., 30.06., 30.09.')
        # 26.10. + 7 + 10 Tage = 12.11. + 3 Mt. = 12.02.2027 → 31.03.2027 → ab 01.04.2027
        self.assertEqual(naechster_anpassungstermin(v, date(2026, 10, 26)), date(2027, 4, 1))

    def test_leeres_feld_ohne_kantonsregel_wird_gemeldet(self):
        from rentals.services import TERMINE_FEHLEN, kuendigungstermine_fuer, termine_aus_vertrag
        v = self._v('')
        _termine, herkunft = kuendigungstermine_fuer(v)
        self.assertEqual(herkunft, TERMINE_FEHLEN)
        # Das Regelwerk bekommt nichts vorgetäuscht — es meldet dann selbst.
        self.assertEqual(termine_aus_vertrag(v), [])

    def test_leeres_feld_nimmt_die_kantonsregel(self):
        from faelle.regelwerk_models import Regel, Regelsatz
        from rentals.services import TERMINE_KANTON, berechne_kuendigungstermin, kuendigungstermine_fuer
        v = self._v('')
        v.einheit.liegenschaft.kanton = 'ZH'
        v.einheit.liegenschaft.save()
        satz = Regelsatz.objects.create(organisation=_test_organisation(), bezeichnung='ZH',
                                        kanton='ZH')
        Regel.objects.create(regelsatz=satz, art=Regel.KUENDIGUNGSTERMIN,
                             parameter={'frist_monate': 3, 'termine': ['31.03', '30.09']})
        v = type(v).objects.get(pk=v.pk)
        termine, herkunft = kuendigungstermine_fuer(v)
        self.assertEqual(herkunft, TERMINE_KANTON)
        self.assertEqual(termine, [(31, 3), (30, 9)])
        self.assertEqual(berechne_kuendigungstermin(v, date(2026, 10, 26)), date(2027, 3, 31))

    def test_termine_aus_vertrag_uebernimmt_den_tag(self):
        from rentals.services import termine_aus_vertrag
        v = self._v('31.03., 30.06., 30.09.')
        self.assertEqual(termine_aus_vertrag(v), ['31.03', '30.06', '30.09'])

    def test_kuendigungsformular_warnt_bei_fehlenden_terminen(self):
        from ._helfer import _team_user
        v = self._v('')
        v.netto_mietzins = Decimal('1500')
        v.save()
        self.client.force_login(_team_user('Verwaltung'))
        r = self.client.get(f'/neu/vertraege/{v.pk}/kuendigen/')
        self.assertContains(r, 'Kündigungstermine fehlen im Vertrag')
