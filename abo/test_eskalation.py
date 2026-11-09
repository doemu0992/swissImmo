"""Eskalation bei ausbleibender Zahlung: 1. Mahnung, 2. Mahnung mit Gebühr, Lesemodus, gesperrter Zugang, Wiederöffnung."""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings

from abo import dienst
from abo.models import AboRechnung, Abonnement
from core.tests._isolation import MandantenFixture

User = get_user_model()
HEUTE = date(2026, 12, 20)
STELLER = {'name': 'Plattform AG', 'strasse': 'Bahnhofstrasse 1', 'plz': '8001', 'ort': 'Zürich',
           'iban': 'CH9300762011623852957', 'uid': '', 'email': 'abo@example.ch'}


class EskalationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        AboRechnung.alle_organisationen.all().delete()

    def setUp(self):
        self.org = type(self.a.organisation).objects.get(pk=self.a.organisation.pk)
        type(self.org).objects.filter(pk=self.org.pk).update(email='verwaltung@example.ch')
        self.org.refresh_from_db()
        Abonnement.alle_organisationen.update_or_create(
            organisation=self.org, defaults={'uneingeschraenkt': False, 'zusatzmodule': [], 'zustand': 'aktiv',
                                             'ueberfaellig_seit': None})
        self.rechnung = AboRechnung.alle_organisationen.create(
            organisation=self.org, nummer='AB-2026-000007', periode_von=HEUTE - timedelta(days=90),
            periode_bis=HEUTE - timedelta(days=60), stufe='team', intervall='monatlich', einheiten=1,
            netto=Decimal('119.00'), brutto=Decimal('119.00'), rechnungsdatum=HEUTE - timedelta(days=90),
            faellig_am=HEUTE - timedelta(days=90))
        mail.outbox.clear()

    def _tage(self, n):
        AboRechnung.alle_organisationen.filter(pk=self.rechnung.pk).update(faellig_am=HEUTE - timedelta(days=n))

    def _lauf(self):
        org = type(self.org).objects.get(pk=self.org.pk)
        with override_settings(ABO_RECHNUNGSSTELLER=STELLER, ABO_MAHNGEBUEHR=Decimal('20')):
            return dienst.abrechnen(org, heute=HEUTE)

    def _rechnung(self):
        return AboRechnung.alle_organisationen.get(pk=self.rechnung.pk)

    # --- die Stufen ----------------------------------------------------------------------------------------------

    def test_zustand_nach_tagen(self):
        for tage, soll in ((0, 'aktiv'), (1, 'mahnung'), (14, 'mahnung'), (15, 'lesemodus'), (44, 'lesemodus'),
                           (45, 'gesperrt')):
            self.assertEqual(dienst.zustand_fuer(HEUTE - timedelta(days=tage), HEUTE), soll, tage)

    def test_erste_mahnung_mit_pdf_und_nur_einmal(self):
        self._tage(1)
        bericht = self._lauf()
        self.assertEqual((bericht['zustand'], bericht['mahnstufe']), ('mahnung', 1))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Zahlungserinnerung', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].attachments[0][0], 'AB-2026-000007.pdf')
        self.assertEqual(self._rechnung().mahngebuehr, 0, 'die 1. Mahnung kostet nichts')
        self._lauf()
        self.assertEqual(len(mail.outbox), 1, 'jede Stufe geht pro Rechnung genau einmal hinaus')

    def test_zweite_mahnung_mit_gebuehr(self):
        self._tage(1)
        self._lauf()
        mail.outbox.clear()
        self._tage(10)
        bericht = self._lauf()
        self.assertEqual((bericht['zustand'], bericht['mahnstufe']), ('mahnung', 2))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('2. Mahnung', mail.outbox[0].subject)
        self.assertIn('CHF 139.00', mail.outbox[0].body)
        self.assertIn('Mahngebühr CHF 20.00', mail.outbox[0].body)
        r = self._rechnung()
        self.assertEqual((r.mahnstufe, r.mahngebuehr), (2, Decimal('20.00')))
        self._lauf()
        self.assertEqual(len(mail.outbox), 1)

    def test_ohne_festgelegte_gebuehr_keine_gebuehr(self):
        self._tage(10)
        org = type(self.org).objects.get(pk=self.org.pk)
        with override_settings(ABO_RECHNUNGSSTELLER=STELLER, ABO_MAHNGEBUEHR=Decimal('0')):
            dienst.abrechnen(org, heute=HEUTE)
        self.assertEqual(self._rechnung().mahngebuehr, 0)
        self.assertNotIn('Mahngebühr', mail.outbox[-1].body)

    def test_gebuehr_steht_im_pdf(self):
        from abo.rechnung_pdf import abo_rechnung_pdf
        AboRechnung.alle_organisationen.filter(pk=self.rechnung.pk).update(mahngebuehr=Decimal('20'))
        with override_settings(ABO_RECHNUNGSSTELLER=STELLER):
            pdf = abo_rechnung_pdf(self._rechnung())
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_lesemodus_und_sperre_haben_ihre_eigene_mitteilung(self):
        self._tage(16)
        self.assertEqual(self._lauf()['zustand'], 'lesemodus')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('schreibgeschützt', mail.outbox[0].subject)
        mail.outbox.clear()
        self._tage(46)
        self.assertEqual(self._lauf()['zustand'], 'gesperrt')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('gesperrt', mail.outbox[0].subject)

    def test_zahlung_oeffnet_alles_wieder(self):
        self._tage(46)
        self._lauf()
        self.assertEqual(Abonnement.alle_organisationen.get(organisation=self.org).zustand, 'gesperrt')
        dienst.als_bezahlt(self._rechnung(), HEUTE)
        abo = Abonnement.alle_organisationen.get(organisation=self.org)
        self.assertEqual((abo.zustand, abo.ueberfaellig_seit), ('aktiv', None))

    # --- der gesperrte Zugang ------------------------------------------------------------------------------------

    def _gesperrt_client(self):
        self._tage(46)
        self._lauf()
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def test_gesperrt_zeigt_sperrseite_ausser_abo_und_export(self):
        c = self._gesperrt_client()
        sperre = c.get('/neu/liegenschaften/')
        self.assertEqual(sperre.status_code, 402)
        self.assertContains(sperre, 'gesperrt', status_code=402)
        self.assertEqual(c.get('/neu/personen/').status_code, 402)
        self.assertEqual(c.get('/neu/abonnement/').status_code, 200)
        self.assertEqual(c.get('/neu/einstellungen/daten/export/').status_code, 200)

    def test_gesperrt_trifft_weder_superuser_noch_andere_verwaltung(self):
        c = self._gesperrt_client()
        self.assertEqual(c.get('/neu/liegenschaften/').status_code, 402)
        andere = MandantenFixture('B', '3000', 'Bern')
        AboRechnung.alle_organisationen.filter(organisation=andere.organisation).delete()
        Abonnement.alle_organisationen.update_or_create(
            organisation=andere.organisation, defaults={'uneingeschraenkt': False, 'zusatzmodule': []})
        cb = Client()
        cb.force_login(andere.benutzer)
        self.assertEqual(cb.get('/neu/liegenschaften/').status_code, 200)

    def test_versand_wird_festgehalten_und_fehlender_versand_ist_ein_befund(self):
        from core.services import betreiber
        AboRechnung.alle_organisationen.filter(pk=self.rechnung.pk).update(faellig_am=HEUTE + timedelta(days=5))
        befunde = [b for k in betreiber.kunden() if k.organisation.pk == self.org.pk for b in k.befunde]
        self.assertTrue(any('noch nicht per Mail versandt' in b for b in befunde), befunde)
        with override_settings(ABO_RECHNUNGSSTELLER=STELLER):
            dienst.rechnung_senden(self._rechnung(), heute=HEUTE)
        self.assertEqual(self._rechnung().versendet_am, HEUTE)
        befunde = [b for k in betreiber.kunden() if k.organisation.pk == self.org.pk for b in k.befunde]
        self.assertFalse(any('noch nicht per Mail versandt' in b for b in befunde), befunde)
