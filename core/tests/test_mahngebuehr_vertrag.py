"""Mahngebühren nur mit vertraglicher Grundlage (`Mietvertrag.mahngebuehr_vereinbart`).

Mahngebühren brauchen eine vertragliche Grundlage oder einen nachgewiesenen Verzugsschaden (Art. 106 OR). Das
Mahnwesen verrechnet sie je Stufe frei konfigurierbar (z. B. Stufe 1 ab Tag 1 mit Kündigungsandrohung und CHF 40).
Neu ist nur der Schalter am Vertrag. DAS LAUFENDE VERHALTEN BLEIBT: Die Vorgabe ist True, bestehende Verträge
werden weiter gemahnt wie bisher; ihre Gebühr ändert sich erst, wenn die Verwaltung den Schalter selbst umlegt.

Gegenproben: in `gebuehr_fuer_vertrag` die Prüfung entfernen -> die Tests «ohne Vereinbarung keine Gebühr» sind rot;
Vorgabe des Feldes auf False -> die Tests «Vorgabe verrechnet wie bisher» sind rot.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext
from core.tests._isolation import MandantenFixture
from core.tests.test_mahnstufen_je_organisation import _ueberfaellige_rechnung


def _stufe_1_ab_tag_1_mit_androhung_und_40(organisation):
    """So stellt eine Verwaltung ihr Mahnwesen ein: Mahnung mit Kündigungsandrohung ab Tag 1, CHF 40."""
    from crm.models import MahnStufe
    with organisation_kontext(organisation):
        MahnStufe.objects.filter(stufe=1).update(ab_tage=1, gebuehr=Decimal('40.00'), art_257d=True)
        MahnStufe.objects.filter(stufe__gt=1).delete()


class HelferTests(SimpleTestCase):

    def test_vorgabe_und_fehlender_vertrag_aendern_nichts(self):
        from core.services.mahnstufen import gebuehr_fuer_vertrag

        class Vertrag:
            mahngebuehr_vereinbart = True
        self.assertEqual(gebuehr_fuer_vertrag(Vertrag(), Decimal('40.00')), Decimal('40.00'))
        self.assertEqual(gebuehr_fuer_vertrag(None, Decimal('40.00')), Decimal('40.00'))
        self.assertEqual(gebuehr_fuer_vertrag(object(), Decimal('40.00')), Decimal('40.00'))

    def test_ohne_vereinbarung_keine_gebuehr(self):
        from core.services.mahnstufen import gebuehr_fuer_vertrag

        class Vertrag:
            mahngebuehr_vereinbart = False
        self.assertEqual(gebuehr_fuer_vertrag(Vertrag(), Decimal('40.00')), Decimal('0.00'))


class MahnlaufTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        _stufe_1_ab_tag_1_mit_androhung_und_40(cls.a.organisation)

    def _mahngebuehr_der_stufe_1(self, rechnung):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung, Mahnung
        with organisation_kontext(self.a.organisation):
            run_mahnlauf(send_email=False, mit_zins=False)
            m = Mahnung.objects.get(debitoren_rechnung=rechnung)
            hat_gebuehrenrechnung = DebitorenRechnung.objects.filter(
                stammrechnung=rechnung, titel__startswith='Mahngebühr').exclude(status='storniert').exists()
            return m.stufe, m.gebuehr, hat_gebuehrenrechnung

    def test_vorgabe_verrechnet_wie_bisher(self):
        """Die Einstellung der Verwaltung (ab Tag 1, CHF 40) wirkt unverändert, wenn nichts umgelegt wird."""
        rechnung = _ueberfaellige_rechnung(self.a, 3)
        stufe, gebuehr, hat = self._mahngebuehr_der_stufe_1(rechnung)
        self.assertEqual((stufe, gebuehr), (1, Decimal('40.00')))
        self.assertTrue(hat, 'Die Gebührenrechnung (CHF 40) fehlt: das laufende Verhalten hat sich geändert.')

    def test_ohne_vereinbarung_keine_gebuehr_aber_die_mahnung_bleibt(self):
        from rentals.models import Mietvertrag
        with organisation_kontext(self.a.organisation):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(mahngebuehr_vereinbart=False)
        rechnung = _ueberfaellige_rechnung(self.a, 3)
        stufe, gebuehr, hat = self._mahngebuehr_der_stufe_1(rechnung)
        self.assertEqual(stufe, 1, 'Die Mahnung selbst muss bleiben.')
        self.assertEqual(gebuehr, Decimal('0.00'))
        self.assertFalse(hat, 'Es wurde eine Gebührenrechnung gestellt, obwohl keine Mahngebühr vereinbart ist.')


class SchalterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _client(self, fixture):
        c = Client()
        c.force_login(fixture.benutzer)
        return c

    def test_umlegen_speichert_und_protokolliert(self):
        from rentals.models import Mietvertrag
        c = self._client(self.a)
        r = c.post(f'/neu/vertraege/{self.a.vertrag.pk}/mahngebuehr/', {'vereinbart': '0'})
        self.assertEqual(r.status_code, 302)
        with organisation_kontext(self.a.organisation):
            self.assertFalse(Mietvertrag.objects.get(pk=self.a.vertrag.pk).mahngebuehr_vereinbart)
        c.post(f'/neu/vertraege/{self.a.vertrag.pk}/mahngebuehr/', {'vereinbart': '1'})
        with organisation_kontext(self.a.organisation):
            self.assertTrue(Mietvertrag.objects.get(pk=self.a.vertrag.pk).mahngebuehr_vereinbart)

    def test_ungueltiger_wert_aendert_nichts(self):
        from rentals.models import Mietvertrag
        self._client(self.a).post(f'/neu/vertraege/{self.a.vertrag.pk}/mahngebuehr/', {'vereinbart': 'vielleicht'})
        with organisation_kontext(self.a.organisation):
            self.assertTrue(Mietvertrag.objects.get(pk=self.a.vertrag.pk).mahngebuehr_vereinbart)

    def test_fremder_vertrag_ist_404(self):
        r = self._client(self.a).post(f'/neu/vertraege/{self.b.vertrag.pk}/mahngebuehr/', {'vereinbart': '0'})
        self.assertEqual(r.status_code, 404)
        from rentals.models import Mietvertrag
        with organisation_kontext(self.b.organisation):
            self.assertTrue(Mietvertrag.objects.get(pk=self.b.vertrag.pk).mahngebuehr_vereinbart)

    def test_die_vertragsakte_zeigt_den_stand(self):
        html = self._client(self.a).get(f'/neu/vertraege/{self.a.vertrag.pk}/').content.decode()
        self.assertIn('Im Vertrag vereinbart: Das Mahnwesen verrechnet die Gebühr', html)
        self.assertIn(f'/neu/vertraege/{self.a.vertrag.pk}/mahngebuehr/', html)


class MahnwesenAnzeigeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        _stufe_1_ab_tag_1_mit_androhung_und_40(cls.a.organisation)

    def test_gebuehrenzeile_traegt_keine_androhung(self):
        """Eine Mahngebühr steht auf der Stufe «mit Kündigungsandrohung», bekommt aber nur eine gewöhnliche Mahnung."""
        from finance.models import DebitorenRechnung
        heute = timezone.localdate()
        _ueberfaellige_rechnung(self.a, 3)
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, liegenschaft=self.a.liegenschaft, titel='Mahngebühr 1. Mahnung',
                betrag=Decimal('40.00'), datum=heute, faellig_am=heute - timedelta(days=3), status='offen', forderungsart='sonstige')
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/mahnwesen/').content.decode()
        self.assertEqual(html.count('keine Kündigungsandrohung (Art. 257d OR gilt nur für Miete und Nebenkosten)'), 1,
                         'Nur die Gebührenzeile trägt den Hinweis, die Mietzeile nicht.')
