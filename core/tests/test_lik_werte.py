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
    def setUp(self):
        lik.cache_leeren()
        self.addCleanup(lik.cache_leeren)

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

    def test_die_reihe_endet_vor_einer_luecke(self):
        """Der Fall vom 14.11.2026: November von Hand eingetragen, Oktober fehlt."""
        LikWert.objects.create(jahr=2026, monat=11, punkte=Decimal('108.7'), quelle='HEV')
        self.assertEqual(lik.letzter_tabellenmonat(), (2026, 9))

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
    def setUp(self):
        lik.cache_leeren()
        self.addCleanup(lik.cache_leeren)

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

    def test_der_laufende_monat_ist_noch_nicht_veroeffentlicht(self):
        antwort = self._post(monat='11')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'noch nicht veröffentlicht')
        self.assertEqual(LikWert.objects.count(), 0)

    def test_ein_monat_hinter_einer_luecke_wird_abgewiesen(self):
        self.client.force_login(self.betreiber)
        with mock.patch('core.views.fw.betreiber.datum_heute', return_value=date(2026, 12, 13)):
            antwort = self.client.post(reverse('fw_betreiber_lik'), {
                'jahr': '2026', 'monat': '11', 'punkte': '108.7', 'quelle': 'BFS'})
        self.assertContains(antwort, 'Vormonat fehlt')
        self.assertEqual(LikWert.objects.count(), 0)

    def test_ein_nachgetragener_wert_laesst_sich_loeschen_und_das_steht_im_protokoll(self):
        self._post()
        w = LikWert.objects.get(jahr=2026, monat=10)
        antwort = self.client.post(reverse('fw_betreiber_lik'), {'aktion': 'loeschen', 'pk': w.pk})
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(LikWert.objects.count(), 0)
        self.assertTrue(SicherheitsEreignis.objects.filter(aktion='LIK-Wert gelöscht', objekt='10/2026').exists())
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_loeschen_darf_nur_der_betreiber(self):
        self._post()
        w = LikWert.objects.get(jahr=2026, monat=10)
        self.client.force_login(self.normal)
        self.assertEqual(self.client.post(reverse('fw_betreiber_lik'), {'aktion': 'loeschen', 'pk': w.pk}).status_code, 403)
        self.assertEqual(LikWert.objects.count(), 1)

    def test_die_seite_bietet_loeschen_nur_bei_nachgetragenen_werten(self):
        self._post()
        with mock.patch('core.views.fw.betreiber.datum_heute', return_value=date(2026, 11, 13)):
            inhalt = self.client.get(reverse('fw_betreiber_lik')).content.decode()
        self.assertEqual(inhalt.count('data-testid="lik-loeschen"'), 1)

    def _abrufen(self, rueckgabe, fehler=None):
        from core.services import abruf_status
        self.client.force_login(self.betreiber)

        def attrappe(_heute):
            if fehler:
                abruf_status.melde_fehler('lik', fehler)
            return rueckgabe
        with mock.patch('core.views.fw.betreiber.datum_heute', return_value=date(2026, 11, 13)), \
                mock.patch.object(lik, 'automatisch_nachfuehren', side_effect=attrappe):
            return self.client.post(reverse('fw_betreiber_lik'), {'aktion': 'abrufen'}, follow=True)

    def test_der_knopf_ruft_ab_und_meldet_die_gespeicherten_werte(self):
        antwort = self._abrufen([(2026, 10, Decimal('108.7'))])
        self.assertContains(antwort, '10/2026: 108.7')
        self.assertTrue(SicherheitsEreignis.objects.filter(aktion='LIK-Wert automatisch nachgetragen').exists())

    def test_der_knopf_nennt_den_grund_wenn_nichts_gespeichert_wurde(self):
        antwort = self._abrufen([], fehler='Marke «2020 = 100» fehlt in der Quelle')
        self.assertContains(antwort, 'Marke «2020 = 100» fehlt')

    def test_der_knopf_sagt_wenn_es_nichts_neues_gibt(self):
        self.assertContains(self._abrufen([]), 'keinen neuen Monatswert')

    def test_abrufen_darf_nur_der_betreiber(self):
        self.client.force_login(self.normal)
        with mock.patch.object(lik, 'automatisch_nachfuehren') as m:
            self.assertEqual(self.client.post(reverse('fw_betreiber_lik'), {'aktion': 'abrufen'}).status_code, 403)
        m.assert_not_called()

    def test_unsinn_wird_abgewiesen_ohne_etwas_zu_speichern(self):
        for kw in ({'punkte': '10.8'}, {'punkte': 'abc'}, {'monat': '13'}, {'jahr': '2019'}, {'jahr': '2027'},
                   {'monat': '12'}, {'monat': '11'}, {'quelle': ''}):
            antwort = self._post(**kw)
            self.assertEqual(antwort.status_code, 200, kw)
        self.assertEqual(LikWert.objects.count(), 0)


class CacheTests(TestCase):
    def setUp(self):
        lik.cache_leeren()
        self.addCleanup(lik.cache_leeren)

    def test_zweiter_aufruf_kostet_keine_abfrage(self):
        lik.lik_reihen()
        with self.assertNumQueries(0):
            lik.lik_reihen()

    def test_speichern_raeumt_den_cache_auf(self):
        lik.lik_reihen()
        LikWert.objects.create(jahr=2026, monat=10, punkte=Decimal('108.7'), quelle='BFS, Test')
        self.assertEqual(lik.lik_punkte_fuer(2026, 10), Decimal('108.7'))
        LikWert.objects.all().delete()
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_die_rueckgabe_ist_eine_kopie(self):
        reihen = lik.lik_reihen()
        reihen[2026][0] = 999.0
        self.assertEqual(lik.lik_punkte_fuer(2026, 1), Decimal('106.9'))
