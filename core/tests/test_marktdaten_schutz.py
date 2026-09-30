"""Ein misslungener Abruf darf den Referenzzinssatz nicht überschreiben.

Stresstest 30.09.2026: Ein manuell gesetzter Satz von 1.00 % sprang im täglichen
Lauf auf 1.25 % zurück («Marktdaten aktualisiert»), weil bei Fehlschlag der feste
Rückfallwert geschrieben wurde. Zudem erkannte die Prüfung nur 1.00–3.50 %: Ein
Satz von 0.75 % oder 0.50 % wurde nie gelesen. Alle Anpassungen nach Art. 269a OR
rechnen gegen diesen Satz.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from ._helfer import _test_organisation


class MarktdatenSchutzTests(TestCase):

    def _org(self, zins='1.00'):
        vw = _test_organisation(firma='T AG', strasse='W 1', plz='3000', ort='Bern',
                                aktueller_referenzzinssatz=Decimal(zins))
        vw.letztes_update_marktdaten = None
        vw.save()
        return vw

    def test_fehlgeschlagener_abruf_laesst_den_satz_stehen(self):
        from core.utils import market_data
        vw = self._org('1.00')
        with mock.patch.object(market_data.requests, 'get', side_effect=OSError('offline')):
            msg, errors = market_data.update_verwaltung_rates(alle=True)
        vw.refresh_from_db()
        self.assertEqual(vw.aktueller_referenzzinssatz, Decimal('1.00'),
                         'Der Satz wurde bei Fehlschlag überschrieben.')
        self.assertIsNone(vw.letztes_update_marktdaten,
                          'Ein Fehlschlag gilt als frische Prüfung.')
        self.assertIn('NICHT aktualisiert', msg)
        self.assertTrue(errors)

    def test_seite_ohne_satz_laesst_den_wert_stehen(self):
        from core.utils import market_data
        vw = self._org('0.75')
        antwort = mock.Mock(text='<html>keine Zahlen hier</html>')
        with mock.patch.object(market_data.requests, 'get', return_value=antwort):
            market_data.update_verwaltung_rates(alle=True)
        vw.refresh_from_db()
        self.assertEqual(vw.aktueller_referenzzinssatz, Decimal('0.75'))

    def test_niedrige_saetze_werden_erkannt(self):
        from core.utils.market_data import ref_zins_aus_html
        for text, erwartet in (('Referenzzinssatz 0,75 %', Decimal('0.75')),
                               ('Der Referenzzinssatz beträgt 0.50%', Decimal('0.50')),
                               ('Referenzzinssatz: 1,25 %', Decimal('1.25')),
                               ('Referenzzinssatz 0,25 %', Decimal('0.25'))):
            self.assertEqual(ref_zins_aus_html(text), erwartet, text)

    def test_ungueltige_schritte_werden_abgelehnt(self):
        from core.utils.market_data import ref_zins_aus_html
        self.assertIsNone(ref_zins_aus_html('Referenzzinssatz 1,33 %'))
        self.assertIsNone(ref_zins_aus_html('Referenzzinssatz 7,25 %'))

    def test_stichwort_hat_vorrang_vor_beliebigen_prozentwerten(self):
        from core.utils.market_data import ref_zins_aus_html
        html = 'Hypothek 2,50 % Beispiel. <p>Der Referenzzinssatz beträgt 1,00 %.</p>'
        self.assertEqual(ref_zins_aus_html(html), Decimal('1.00'))

    def test_erfolgreicher_abruf_schreibt_weiterhin(self):
        from core.utils import market_data
        vw = self._org('1.25')
        with mock.patch.object(market_data, 'fetch_market_rates',
                               return_value=({'ref_zins': Decimal('1.00')}, [])):
            market_data.update_verwaltung_rates(alle=True)
        vw.refresh_from_db()
        self.assertEqual(vw.aktueller_referenzzinssatz, Decimal('1.00'))
        self.assertIsNotNone(vw.letztes_update_marktdaten)
