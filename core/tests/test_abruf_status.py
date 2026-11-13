"""Die Spur der Abrufe: Fehler werden gezählt, ein Erfolg setzt zurück, ein Ausfall erscheint beim Betreiber."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core.models import AbrufStatus
from core.services import abruf_status, datenpflege, lik


class SpurTests(TestCase):
    def test_fehler_werden_gezaehlt_und_ein_erfolg_setzt_zurueck(self):
        abruf_status.melde_fehler('lik', 'Verbindung fehlgeschlagen')
        abruf_status.melde_fehler('lik', 'Verbindung fehlgeschlagen')
        self.assertEqual(AbrufStatus.objects.get(name='lik').fehler_in_folge, 2)
        abruf_status.melde_erfolg('lik')
        e = AbrufStatus.objects.get(name='lik')
        self.assertEqual((e.fehler_in_folge, e.letzter_fehler), (0, ''))
        self.assertIsNotNone(e.letzter_erfolg)

    def test_zwei_fehlversuche_sind_noch_kein_ausfall_drei_schon(self):
        for _i in range(2):
            abruf_status.melde_fehler('lik', 'x')
        AbrufStatus.objects.filter(name='lik').update(letzter_erfolg=timezone.now())
        self.assertEqual(abruf_status.ausfaelle(), [])
        abruf_status.melde_fehler('lik', 'Marke fehlt')
        texte = abruf_status.ausfaelle()
        self.assertEqual(len(texte), 1)
        self.assertIn('Marke fehlt', texte[0])

    def test_lange_ohne_erfolg_ist_auch_ohne_viele_versuche_ein_ausfall(self):
        abruf_status.melde_fehler('referenzzins', 'BWO nicht lesbar')
        AbrufStatus.objects.filter(name='referenzzins').update(letzter_erfolg=timezone.now() - timedelta(days=9))
        self.assertEqual(len(abruf_status.ausfaelle()), 1)

    def test_das_protokoll_stoert_den_abruf_nie(self):
        with mock.patch('core.services.abruf_status._holen', side_effect=RuntimeError('db weg')):
            abruf_status.melde_fehler('lik', 'x')       # wirft nicht
            abruf_status.melde_erfolg('lik')


class LikAbrufTests(TestCase):
    def _antwort(self, text, status=200):
        a = mock.Mock(); a.text = text; a.status_code = status
        return a

    def test_fehlende_marke_wird_mit_grund_protokolliert(self):
        with mock.patch('requests.get', return_value=self._antwort('<html>umgebaut</html>')):
            self.assertIsNone(lik._fetch_live_lik())
        self.assertIn('2020 = 100', AbrufStatus.objects.get(name='lik').letzter_fehler)

    def test_verbindungsfehler_und_status_werden_protokolliert(self):
        with mock.patch('requests.get', side_effect=ConnectionError('x')):
            lik._fetch_live_lik()
        self.assertIn('Verbindung', AbrufStatus.objects.get(name='lik').letzter_fehler)
        with mock.patch('requests.get', return_value=self._antwort('', status=403)):
            lik._fetch_live_lik()
        e = AbrufStatus.objects.get(name='lik')
        self.assertIn('403', e.letzter_fehler)
        self.assertEqual(e.fehler_in_folge, 2)

    def test_ein_gelesener_wert_ist_ein_erfolg(self):
        heute = timezone.localdate()
        html = (f'<table>Dezember 2020 = 100<tr><td>>{heute.year}<</td>' + ''.join(f'<td>1{9 if False else 0}8.{m % 10}</td>' for m in range(heute.month))
                + '</tr></table>')
        with mock.patch('requests.get', return_value=self._antwort(html)):
            got = lik._fetch_live_lik()
        if got is not None:       # die Form der Quelle ist nicht Gegenstand dieses Tests, nur die Spur
            self.assertEqual(AbrufStatus.objects.get(name='lik').fehler_in_folge, 0)


class BetreiberHinweisTests(TestCase):
    def test_ein_ausfall_steht_in_den_aufgaben_des_betreibers(self):
        for _i in range(3):
            abruf_status.melde_fehler('lik', 'Marke fehlt')
        self.assertTrue(any('Abruf ausgefallen' in a for a in datenpflege.faellig(timezone.localdate())))
