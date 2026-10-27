"""Kündigung bis zur Produktionsreife (Audit 26.10.2026, Befunde F und L).

F  Vermieterkündigung: Frist und Anfechtung ab dem Zugang beim Mieter.
L  Art. 266m (Zustimmung Ehegatte), Art. 264 (Ersatzmieter), strukturierte
   ausserordentliche Gründe mit Mindesttermin, Erstreckung verschiebt das Ende.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _team_user


class _Basis(TestCase):
    def setUp(self):
        _lg, _e, _m, self.v = _basis_objekte()      # Wohnung, 3 Mt., Ende jedes Monats ausser Dez.
        self.c = Client()
        self.c.force_login(_team_user('Verwaltung'))
        self.heute = timezone.localdate()

    def _post(self, **daten):
        daten.setdefault('eingang_datum', self.heute.isoformat())
        return self.c.post(f'/neu/vertraege/{self.v.id}/kuendigen/', daten)

    def _k(self):
        from rentals.models import Kuendigung
        return Kuendigung.objects.filter(vertrag=self.v).order_by('-id').first()


class ZugangVermieterTests(_Basis):
    """Befund F: `eingang_datum` ist beim Vermieter der Versand."""

    def test_frist_ab_vermutetem_zugang(self):
        from core.models import Pendenz
        from rentals.services import ZUSTELL_PUFFER_TAGE, berechne_kuendigungstermin
        self._post(absender='vermieter')
        k = self._k()
        zugang = self.heute + timedelta(days=ZUSTELL_PUFFER_TAGE)
        self.assertEqual(k.berechneter_termin, berechne_kuendigungstermin(self.v, zugang))
        p = Pendenz.objects.get(vertrag=self.v, titel__startswith='Anfechtungsfrist Kündigung')
        self.assertEqual(p.faellig_am, zugang + timedelta(days=30))

    def test_bestaetigter_zugang_gilt(self):
        from core.models import Pendenz
        gestern = self.heute - timedelta(days=1)
        self._post(absender='vermieter', eingang_datum=(self.heute - timedelta(days=3)).isoformat(),
                   zugang_am=gestern.isoformat())
        self.assertEqual(self._k().zugang_am, gestern)
        p = Pendenz.objects.get(vertrag=self.v, titel__startswith='Anfechtungsfrist Kündigung')
        self.assertEqual(p.faellig_am, gestern + timedelta(days=30))

    def test_zugang_vor_versand_wird_abgewiesen(self):
        self._post(absender='vermieter', zugang_am=(self.heute - timedelta(days=5)).isoformat())
        self.assertIsNone(self._k())


class FamilienwohnungTests(_Basis):
    """Art. 266m OR: ohne Zustimmung keine Bestätigung und keine Folgen am Vertrag."""

    def setUp(self):
        super().setUp()
        self.v.familienwohnung = True
        self.v.mitmieter_name = 'Erika Muster'
        self.v.save()

    def test_ohne_zustimmung_bleibt_der_vertrag(self):
        from core.models import Pendenz
        self._post(absender='mieter', bestaetigen='on')
        k = self._k()
        self.assertEqual(k.status, 'erfasst')
        self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'aktiv')
        self.assertTrue(Pendenz.objects.filter(vertrag=self.v, quelle=f'266m:{k.pk}').exists())
        # Bestätigen ohne Zustimmung: gesperrt.
        self.c.post(f'/neu/kuendigung/{k.pk}/bestaetigen/')
        k.refresh_from_db()
        self.assertEqual(k.status, 'erfasst')
        # Mit nachgetragener Zustimmung: bestätigt, Vertrag gekündigt.
        self.c.post(f'/neu/kuendigung/{k.pk}/bestaetigen/', {'zustimmung_ehegatte': 'on'})
        k.refresh_from_db()
        self.v.refresh_from_db()
        self.assertEqual((k.status, k.zustimmung_ehegatte, self.v.status), ('bestaetigt', True, 'gekuendigt'))

    def test_mit_zustimmung_normal(self):
        self._post(absender='mieter', bestaetigen='on', zustimmung_ehegatte='on')
        self.v.refresh_from_db()
        self.assertEqual((self._k().status, self.v.status), ('bestaetigt', 'gekuendigt'))


class ErsatzmieterTests(_Basis):
    """Art. 264 OR: Vorzeitiger Auszug befreit nur mit angenommenem Ersatzmieter."""

    def _frueh(self):
        return (self.heute + timedelta(days=20)).isoformat()

    def test_ohne_annahme_haftet_der_mieter_bis_zum_termin(self):
        from core.models import Pendenz
        self._post(absender='mieter', gewuenschtes_ende=self._frueh(), ersatzmieter='Petra Beispiel')
        k = self._k()
        self.assertEqual(k.per_datum, k.berechneter_termin)
        self.assertTrue(Pendenz.objects.filter(vertrag=self.v, quelle=f'264:{k.pk}').exists())

    def test_mit_annahme_endet_der_vertrag_frueher(self):
        self._post(absender='mieter', gewuenschtes_ende=self._frueh(), ersatzmieter='Petra Beispiel',
                   ersatzmieter_akzeptiert='on')
        k = self._k()
        self.assertEqual(k.per_datum.isoformat(), self._frueh())
        self.assertTrue(k.ersatzmieter_akzeptiert)


class AusserordentlichTests(_Basis):
    """Strukturierte Gründe; «ausserordentlich» endet nicht mehr einfach am Wunschdatum."""

    def test_ohne_grund_abgewiesen(self):
        self._post(absender='mieter', ausserordentlich='on', gewuenschtes_ende=self._morgen())
        self.assertIsNone(self._k())

    def test_grund_der_anderen_partei_abgewiesen(self):
        self._post(absender='mieter', ausserordentlich='on', ausserordentlich_art='257d',
                   gewuenschtes_ende=self._morgen())
        self.assertIsNone(self._k())

    def test_266g_klemmt_auf_die_gesetzliche_frist(self):
        from rentals.services import ausserordentlicher_termin
        self._post(absender='vermieter', ausserordentlich='on', ausserordentlich_art='266g',
                   zugang_am=self.heute.isoformat(), gewuenschtes_ende=self._morgen())
        k = self._k()
        self.assertEqual(k.per_datum, ausserordentlicher_termin(self.v, '266g', self.heute))
        self.assertGreater(k.per_datum, self.heute + timedelta(days=80))   # drei Monate, nicht morgen

    def test_266i_gesetzliche_frist_auf_den_termin(self):
        from rentals.services import berechne_kuendigungstermin
        self.v.kuendigungsfrist_monate = 6
        self.v.save()
        self._post(absender='mieter', ausserordentlich='on', ausserordentlich_art='266i')
        k = self._k()
        gesetzlich = type(self.v).objects.get(pk=self.v.pk)
        gesetzlich.kuendigungsfrist_monate = 3
        self.assertEqual(k.per_datum, berechne_kuendigungstermin(gesetzlich, self.heute))
        self.assertLess(k.per_datum, k.berechneter_termin)          # kürzer als die vertraglichen 6

    def test_grund_ohne_belegte_frist_verlangt_ein_datum(self):
        self._post(absender='vermieter', ausserordentlich='on', ausserordentlich_art='257f')
        self.assertIsNone(self._k())
        self._post(absender='vermieter', ausserordentlich='on', ausserordentlich_art='257f',
                   gewuenschtes_ende=self._morgen())
        self.assertEqual(self._k().per_datum.isoformat(), self._morgen())

    def _morgen(self):
        return (self.heute + timedelta(days=1)).isoformat()


class ErstreckungTests(_Basis):
    """Die Erstreckung verschiebt Vertragsende und damit die Sollstellung."""

    def test_erstreckung_wird_vertragsende(self):
        self._post(absender='vermieter', bestaetigen='on', erstreckung_bis='2031-03-31')
        k = self._k()
        self.v.refresh_from_db()
        self.assertEqual(self.v.ende, date(2031, 3, 31))
        self.assertLess(k.per_datum, date(2031, 3, 31))

    def test_erstreckung_vor_dem_ende_abgewiesen(self):
        self._post(absender='vermieter', erstreckung_bis=self.heute.isoformat())
        self.assertIsNone(self._k())

    def test_sollstellung_laeuft_bis_zur_erstreckung(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        self._post(absender='vermieter', bestaetigen='on', erstreckung_bis='2031-03-31')
        k = self._k()
        nach_ende = k.per_datum + timedelta(days=40)
        run_sollstellung(nach_ende.year, nach_ende.month)
        self.assertTrue(DebitorenRechnung.objects.filter(vertrag=self.v, betrag__gt=Decimal('0')).exists())
