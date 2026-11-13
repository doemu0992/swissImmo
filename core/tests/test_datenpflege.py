"""Pflege-Erinnerungen für die von Hand gepflegten Tabellen (Roadmap 1.3)."""
from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase

from core.services import datenpflege, formularpflicht, lik
from core.tests._isolation import MandantenFixture


class FaelligTests(TestCase):
    def _letzter(self):
        jahr, monat = lik.letzter_tabellenmonat()
        return date(jahr, monat, 15)

    def test_nichts_faellig_im_letzten_tabellenmonat_und_frisch_gepruefter_formularpflicht(self):
        with mock.patch.object(formularpflicht, 'GEPRUEFT_AM', self._letzter()):
            self.assertEqual(datenpflege.faellig(self._letzter()), [])

    def test_lik_wird_faellig_wenn_die_tabelle_hinterherhinkt(self):
        spaeter = self._letzter() + timedelta(days=75)               # gut zwei Monate danach
        with mock.patch.object(formularpflicht, 'GEPRUEFT_AM', spaeter):
            aufgaben = datenpflege.faellig(spaeter)
        self.assertEqual(len(aufgaben), 1)
        self.assertIn('LIK-Tabelle', aufgaben[0])

    def test_formularpflicht_wird_nach_einem_jahr_faellig(self):
        geprueft = formularpflicht.GEPRUEFT_AM
        with mock.patch.object(lik, 'tabelle_rueckstand_monate', return_value=0):
            self.assertEqual(datenpflege.faellig(geprueft + timedelta(days=364)), [])
            aufgaben = datenpflege.faellig(geprueft + timedelta(days=366))
        self.assertEqual(len(aufgaben), 1)
        self.assertIn('Formularpflicht', aufgaben[0])


class BetreiberSeiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_betreiberseite_zeigt_die_erinnerung_nur_wenn_etwas_faellig_ist(self):
        from django.contrib.auth import get_user_model
        op = get_user_model().objects.create_superuser('betr', 'b@example.ch', 'Ein-langes-Passwort-1')
        self.client.force_login(op)
        with mock.patch('core.services.datenpflege.faellig', return_value=['LIK-Tabelle nachtragen: Test']):
            self.assertIn('LIK-Tabelle nachtragen: Test', self.client.get('/betreiber/').content.decode())
        with mock.patch('core.services.datenpflege.faellig', return_value=[]):
            self.assertNotIn('LIK-Tabelle nachtragen', self.client.get('/betreiber/').content.decode())
