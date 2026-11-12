"""Plausibilitätsprüfung der Zählerstände: Fehler, Warnungen und die Bestätigung «Trotzdem speichern»."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from core.services import zaehlerstaende
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture


class ZaehlerstandPruefungTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _zaehler(self, staende):
        """Ein Zähler mit Ständen [(Tage vor heute, Wert)]."""
        from portfolio.models import Zaehler, ZaehlerStand
        heute = date.today()
        with organisation_kontext(self.a.organisation):
            z = Zaehler.objects.create(einheit=self.a.einheit, typ='Wasser', zaehler_nummer=f'W{Zaehler.objects.count()}')
            for tage, wert in staende:
                ZaehlerStand.objects.create(zaehler=z, datum=heute - timedelta(days=tage), wert=Decimal(wert))
        return z

    def _pruefen(self, z, tage_zurueck, wert):
        with organisation_kontext(self.a.organisation):
            return zaehlerstaende.pruefen(z, date.today() - timedelta(days=tage_zurueck), Decimal(wert))

    def test_normaler_verbrauch_ist_unauffaellig(self):
        z = self._zaehler([(300, 100), (200, 110), (100, 120)])
        self.assertEqual(self._pruefen(z, 0, 130), {'fehler': [], 'warnungen': []})

    def test_sinkender_stand_ist_ein_fehler(self):
        z = self._zaehler([(100, 120)])
        self.assertEqual(len(self._pruefen(z, 0, 110)['fehler']), 1)

    def test_stand_ueber_dem_spaeteren_ist_ein_fehler(self):
        z = self._zaehler([(100, 100), (10, 150)])
        self.assertEqual(len(self._pruefen(z, 50, 160)['fehler']), 1)

    def test_auffaellig_hoher_verbrauch_ist_eine_warnung(self):
        z = self._zaehler([(300, 100), (200, 110), (100, 120)])          # 0.1 je Tag
        befund = self._pruefen(z, 0, 160)                                  # 0.4 je Tag: vierfach
        self.assertEqual(befund['fehler'], [])
        self.assertEqual(len(befund['warnungen']), 1)
        self.assertIn('auffällig hoch', befund['warnungen'][0])

    def test_zwei_zeitraeume_brauchen_es_fuer_die_hochwarnung(self):
        z = self._zaehler([(100, 100), (50, 110)])                         # erst EIN Zeitraum bekannt
        self.assertEqual(self._pruefen(z, 0, 300)['warnungen'], [])

    def test_kein_verbrauch_ueber_60_tage_ist_eine_warnung(self):
        z = self._zaehler([(90, 100)])
        self.assertEqual(len(self._pruefen(z, 0, 100)['warnungen']), 1)
        self.assertEqual(self._pruefen(z, 40, 100)['warnungen'], [])      # nur 50 Tage: noch nicht
        z2 = self._zaehler([(30, 100)])
        self.assertEqual(self._pruefen(z2, 0, 100)['warnungen'], [])      # 30 Tage: normal

    def test_erster_stand_hat_nichts_zu_pruefen(self):
        z = self._zaehler([])
        self.assertEqual(self._pruefen(z, 0, 5), {'fehler': [], 'warnungen': []})


class ZaehlerstandErfassenTests(TestCase):
    """Die Erfassung der Verwaltung: Warnung zeigt «Trotzdem speichern», erst die Bestätigung speichert."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        from portfolio.models import Zaehler, ZaehlerStand
        heute = date.today()
        with organisation_kontext(self.a.organisation):
            self.z = Zaehler.objects.create(einheit=self.a.einheit, typ='Strom', zaehler_nummer='S1')
            for tage, wert in ((300, 100), (200, 110), (100, 120)):
                ZaehlerStand.objects.create(zaehler=self.z, datum=heute - timedelta(days=tage), wert=Decimal(wert))
        self.c = Client()
        self.c.force_login(self.a.benutzer)
        self.url = f'/neu/liegenschaften/{self.a.liegenschaft.pk}/zaehlerstand/'

    def _anzahl(self):
        from portfolio.models import ZaehlerStand
        with organisation_kontext(self.a.organisation):
            return ZaehlerStand.objects.filter(zaehler=self.z).count()

    def _post(self, wert, **extra):
        return self.c.post(self.url, {'zaehler': self.z.pk, 'datum': date.today().isoformat(), 'wert': wert, **extra})

    def test_normaler_stand_wird_gespeichert(self):
        self.assertEqual(self._post('130').status_code, 302)
        self.assertEqual(self._anzahl(), 4)

    def test_auffaelliger_stand_zeigt_warnung_und_speichert_noch_nicht(self):
        r = self._post('160')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'auffällig hoch')
        self.assertContains(r, 'Trotzdem speichern')
        self.assertEqual(self._anzahl(), 3)

    def test_mit_bestaetigung_wird_gespeichert(self):
        self.assertEqual(self._post('160', trotzdem='1').status_code, 302)
        self.assertEqual(self._anzahl(), 4)

    def test_sinkender_stand_bleibt_ein_fehler_auch_mit_bestaetigung(self):
        r = self._post('90', trotzdem='1')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._anzahl(), 3)


class AblesungDurchMieterTests(TestCase):
    """Die Mieterschaft meldet Stände (Anfrage), die Verwaltung bestätigt; Aufruf per Mail."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        User = get_user_model()
        for f in (cls.a, cls.b):
            with organisation_kontext(f.organisation):
                f.mieter.benutzer = User.objects.create_user(username=f'zm-{f.kuerzel}', password='x')
                f.mieter.email = f'zm-{f.kuerzel.lower()}@example.ch'
                f.mieter.save()

    def setUp(self):
        from portfolio.models import Zaehler, ZaehlerStand
        heute = date.today()
        with organisation_kontext(self.a.organisation):
            self.z = Zaehler.objects.create(einheit=self.a.einheit, typ='Wasser', zaehler_nummer='W-A')
            ZaehlerStand.objects.create(zaehler=self.z, datum=heute - timedelta(days=30), wert=Decimal('100'))
        with organisation_kontext(self.b.organisation):
            self.zb = Zaehler.objects.create(einheit=self.b.einheit, typ='Wasser', zaehler_nummer='W-B')

    def _mieter(self, f=None):
        c = Client()
        c.force_login((f or self.a).mieter.benutzer)
        return c

    def _verwaltung(self):
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def _melden(self, wert, zaehler=None, c=None, tage_zurueck=0):
        return (c or self._mieter()).post('/mieter/zaehler/', {
            'zaehler': (zaehler or self.z).pk, 'wert': wert,
            'datum': (date.today() - timedelta(days=tage_zurueck)).isoformat()})

    def _staende(self):
        from portfolio.models import ZaehlerStand
        with organisation_kontext(self.a.organisation):
            return ZaehlerStand.objects.filter(zaehler=self.z).count()

    def test_melden_ist_nur_eine_anfrage_und_zaehlt_erst_nach_bestaetigung(self):
        from core.models import Aenderungsanfrage
        self._melden('110')
        anfrage = Aenderungsanfrage.alle_organisationen.get(art='zaehlerstand')
        self.assertEqual((anfrage.status, self._staende()), ('offen', 1))
        self.assertIn('110', anfrage.zusammenfassung)
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        self.assertEqual(self._staende(), 2)
        from portfolio.models import ZaehlerStand
        with organisation_kontext(self.a.organisation):
            self.z.refresh_from_db()
            neu = ZaehlerStand.objects.filter(zaehler=self.z).order_by('-id').first()
        self.assertEqual((neu.herkunft, self.z.aktueller_stand), ('portal', Decimal('110')))

    def test_sinkender_stand_wird_sofort_abgewiesen(self):
        from core.models import Aenderungsanfrage
        c = self._mieter()
        r = self._melden('90', c=c)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Aenderungsanfrage.alle_organisationen.filter(art='zaehlerstand').exists())
        self.assertContains(c.get('/mieter/zaehler/'), 'unter dem Stand')

    def test_ablehnen_legt_nichts_an(self):
        from core.models import Aenderungsanfrage
        self._melden('110')
        anfrage = Aenderungsanfrage.alle_organisationen.get(art='zaehlerstand')
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/ablehnen/', {'antwort': 'Bitte neu ablesen'})
        self.assertEqual(self._staende(), 1)

    def test_nur_eigene_zaehler(self):
        from core.models import Aenderungsanfrage
        self._melden('5', zaehler=self.zb)                                   # Zähler einer fremden Verwaltung
        self.assertFalse(Aenderungsanfrage.alle_organisationen.filter(art='zaehlerstand').exists())
        body = self._mieter().get('/mieter/zaehler/').content.decode()
        self.assertIn('W-A', body)
        self.assertNotIn('W-B', body)

    def test_bestaetigung_prueft_nochmals(self):
        """Kam seit der Meldung ein höherer Stand dazu, wird der gemeldete nicht mehr übernommen."""
        from core.models import Aenderungsanfrage
        from portfolio.models import ZaehlerStand
        self._melden('110', tage_zurueck=10)
        anfrage = Aenderungsanfrage.alle_organisationen.get(art='zaehlerstand')
        with organisation_kontext(self.a.organisation):
            ZaehlerStand.objects.create(zaehler=self.z, datum=date.today() - timedelta(days=5), wert=Decimal('108'))
        self._verwaltung().post(f'/neu/anfragen/{anfrage.pk}/bestaetigen/')
        anfrage.refresh_from_db()
        self.assertEqual(anfrage.status, 'offen')                           # bleibt offen, mit Fehlermeldung

    def test_aufruf_geht_per_mail_und_steht_im_logbuch(self):
        from django.core import mail

        from core.models import AktivitaetsLog
        from rentals.models import Mietvertrag
        with organisation_kontext(self.a.organisation):
            Mietvertrag.objects.filter(pk=self.a.vertrag.pk).update(status='aktiv')
        mail.outbox.clear()
        r = self._verwaltung().post(f'/neu/ablesung/{self.a.liegenschaft.pk}/aufruf/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any(m.to == ['zm-a@example.ch'] and '/mieter/zaehler/' in m.body for m in mail.outbox))
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
            organisation=self.a.organisation, aktion='Ablese-Aufruf gesendet').exists())
        self.assertContains(self._verwaltung().get('/neu/ablesung/'), 'zuletzt aufgerufen')

    def test_fremde_liegenschaft_ist_404(self):
        self.assertEqual(self._verwaltung().post(f'/neu/ablesung/{self.b.liegenschaft.pk}/aufruf/').status_code, 404)
