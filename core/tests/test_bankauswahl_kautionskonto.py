"""Das Kautionssperrkonto 1015 gehört in keine Bankauswahl (Audit FUNK-01, Etappe 2).

Etappe 0 hat es aus der Eigentümerauszahlung genommen. Dieselbe Auswahl
(`nummer__startswith='10'`) stand noch in Bankabgleich, Zahllauf und
Zahlungsklärung, und die Formulare nahmen jede Kontonummer an, die ein POST
mitschickte. Jetzt: Die Listen schliessen 1015 aus, und der Server fällt bei
1015 (oder jedem Nicht-Bankkonto) auf 1020 zurück.
"""
from decimal import Decimal

from finance.booking import bank_nr_aus_eingabe, bankkonten

from .test_geld_parallel import GeldPfadBasis


class BankauswahlTests(GeldPfadBasis):

    def test_helfer_laesst_1015_und_fremde_konten_nicht_durch(self):
        self.assertEqual(bank_nr_aus_eingabe('1015'), '1020')
        self.assertEqual(bank_nr_aus_eingabe('3000'), '1020')
        self.assertEqual(bank_nr_aus_eingabe('9999'), '1020')
        self.assertEqual(bank_nr_aus_eingabe(''), '1020')
        self.assertEqual(bank_nr_aus_eingabe(None), '1020')
        self.assertEqual(bank_nr_aus_eingabe('1020'), '1020')

    def test_helfer_nimmt_ein_weiteres_bankkonto(self):
        from finance.models import Buchungskonto
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        self.assertEqual(bank_nr_aus_eingabe('1021'), '1021')

    def test_liste_der_bankkonten_ohne_1015(self):
        nummern = [k.nummer for k in bankkonten()]
        self.assertIn('1020', nummern)
        self.assertNotIn('1015', nummern)

    def test_auswahl_auf_den_seiten(self):
        """Bankabgleich, Zahllauf: 1015 steht in keiner Auswahl."""
        from finance.models import Buchungskonto
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        c = self.neuer_client()
        for url in ('/neu/bankabgleich/', '/neu/zahllauf/'):
            antwort = c.get(url)
            self.assertEqual(antwort.status_code, 200, url)
            nummern = [k.nummer for k in antwort.context['bankkonten']]
            self.assertIn('1021', nummern, url)
            self.assertNotIn('1015', nummern, url)

    def test_kreditor_zahlung_mit_1015_bucht_auf_1020(self):
        k = self.kreditor()
        self.post('/neu/kreditoren/bezahlen/', {'rechnung_id': k.pk, 'bank_konto': '1015'})
        self.assertEqual(self.saldo('1015'), Decimal('0'))
        self.assertEqual(self.saldo('1020'), Decimal('-800.00'))
