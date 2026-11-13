"""Nachgetragene LIK-Monatswerte: Sie gelten vor der Reihe im Code, und nur der Betreiber trägt sie ein."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import LikWert, SicherheitsEreignis
from core.services import datenpflege, lik, mietzinsmodell


class ReiheTests(TestCase):
    def test_ohne_nachtrag_gilt_die_reihe_im_code(self):
        self.assertEqual(lik.lik_punkte_fuer(2026, 9), Decimal('108.5'))
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))
        self.assertEqual(lik.letzter_tabellenmonat(), (2026, 9))

    def test_ein_nachtrag_ergaenzt_die_reihe(self):
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('108.7'), quelle='BFS, Test')
        self.assertEqual(lik.lik_punkte_fuer(2026, 10), Decimal('108.7'))
        self.assertEqual(lik.letzter_tabellenmonat(), (2026, 10))

    def test_ein_nachtrag_gewinnt_gegen_den_code(self):
        LikWert.objects.create(jahr=2026, monat=9, punkte=Decimal('108.4'), quelle='BFS, Korrektur')
        self.assertEqual(lik.lik_punkte_fuer(2026, 9), Decimal('108.4'))

    def test_eine_andere_basis_wird_nicht_gemischt(self):
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('101.0'), basis='Dezember 2025', quelle='BFS')
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_ist_die_datenbank_nicht_lesbar_gilt_die_reihe_im_code(self):
        with mock.patch('core.models.LikWert.objects') as m:
            m.filter.side_effect = RuntimeError('db weg')
            self.assertEqual(lik.lik_punkte_fuer(2026, 9), Decimal('108.5'))

    def test_der_vertragsassistent_nimmt_den_nachtrag(self):
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('108.7'), quelle='BFS, Test')
        self.assertEqual(mietzinsmodell.basis_lik_vorschlag(date(2026, 12, 1), live=False),
                         (date(2026, 10, 1), Decimal('108.7')))

    def test_die_erinnerung_verschwindet_mit_dem_nachtrag(self):
        heute = date(2026, 11, 13)
        self.assertTrue(any('LIK-Tabelle' in a for a in datenpflege.faellig(heute)))
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('108.7'), quelle='BFS, Test')
        self.assertFalse(any('LIK-Tabelle' in a for a in datenpflege.faellig(heute)))


class SeiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.betreiber = U.objects.create_superuser('bt', 'bt@example.com', 'x')
        cls.normal = U.objects.create_user('nm', 'nm@example.com', 'x')

    def _post(self, **kw):
        werte = {'jahr': '2026', 'monat': '10', 'punkte': '108,7', 'quelle': 'BFS, Medienmitteilung'}
        werte.update(kw)
        self.client.force_login(self.betreiber)
        with mock.patch('core.zeit.datum_heute', return_value=date(2026, 11, 13)), \
                mock.patch('core.views.fw.betreiber.datum_heute', return_value=date(2026, 11, 13)):
            return self.client.post(reverse('fw_betreiber_lik'), werte)

    def test_nur_der_betreiber_darf(self):
        self.client.force_login(self.normal)
        self.assertEqual(self.client.get(reverse('fw_betreiber_lik')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('fw_betreiber_lik')).status_code, 302)

    def test_speichern_legt_den_wert_an_und_protokolliert(self):
        antwort = self._post()
        self.assertEqual(antwort.status_code, 302)
        w = LikWert.objects.get(jahr=2026, monat=10)
        self.assertEqual((w.punkte, w.erfasst_von), (Decimal('108.7'), self.betreiber))
        self.assertTrue(SicherheitsEreignis.objects.filter(aktion='LIK-Wert nachgetragen').exists())

    def test_speichern_eines_vorhandenen_monats_korrigiert(self):
        self._post(); self._post(punkte='108.6')
        self.assertEqual(LikWert.objects.filter(jahr=2026, monat=10).count(), 1)
        self.assertEqual(LikWert.objects.get(jahr=2026, monat=10).punkte, Decimal('108.6'))

    def test_unsinn_wird_abgewiesen_ohne_etwas_zu_speichern(self):
        for kw in ({'punkte': '10.8'}, {'punkte': 'abc'}, {'monat': '13'}, {'jahr': '2019'}, {'jahr': '2027'},
                   {'monat': '12'}, {'quelle': ''}):
            antwort = self._post(**kw)
            self.assertEqual(antwort.status_code, 200, kw)
        self.assertEqual(LikWert.objects.count(), 0)
