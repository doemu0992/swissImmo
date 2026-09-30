"""Stresstest 30.09.2026, Punkte 3 und 13: Überzahlung und Valuta im Bankabgleich."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user


class BankabgleichUeberzahlungValutaTests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        from finance.models import DebitorenRechnung
        self.heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=20),
            faellig_am=self.heute - timedelta(days=20), betrag=Decimal('1810.00'))
        self.c = Client(); self.c.force_login(_team_user())

    def _post(self, **daten):
        daten.setdefault('rechnung_id', self.r.id)
        return self.c.post('/neu/bankabgleich/verbuchen/', daten, secure=True)

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        k = Buchungskonto.objects.get(nummer=nummer)
        soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k)), Decimal('0'))
        haben = sum((b.betrag for b in Buchung.objects.filter(haben_konto=k)), Decimal('0'))
        return soll - haben

    def test_ueberzahlung_geht_nicht_verloren(self):
        """2110 Eingang auf 1810 offen: CHF 300 müssen als Guthaben auf 2030 stehen."""
        from finance.models import Zahlungseingang
        self._post(betrag='2110.00')
        self.r.refresh_from_db()
        self.assertEqual(self.r.status, 'bezahlt')
        self.assertEqual(self.r.offener_betrag, Decimal('0.00'))
        self.assertEqual(self._saldo('1020'), Decimal('2110.00'),
                         'Die Bank zeigt 2110, die Buchhaltung weiss weniger.')
        self.assertEqual(self._saldo('2030'), Decimal('-300.00'))
        ueber = Zahlungseingang.objects.get(bank_referenz__endswith=':ueber')
        self.assertEqual(ueber.betrag, Decimal('300.00'))
        self.assertEqual(ueber.vertrag_id, self.v.id)

    def test_storno_hebt_die_ueberzahlung_mit_auf(self):
        from finance.models import Zahlungseingang
        self._post(betrag='2110.00')
        haupt = Zahlungseingang.objects.get(debitoren_rechnung=self.r)
        self.c.post(f'/neu/zahlungen/{haupt.id}/stornieren/', {}, secure=True)
        self.assertFalse(Zahlungseingang.objects.filter(status='verbucht').exists())
        self.assertEqual(self._saldo('2030'), Decimal('0.00'))
        self.r.refresh_from_db()
        self.assertEqual(self.r.status, 'offen')

    def test_genauer_betrag_erzeugt_kein_guthaben(self):
        from finance.models import Zahlungseingang
        self._post(betrag='1810.00')
        self.assertFalse(Zahlungseingang.objects.filter(bank_referenz__endswith=':ueber').exists())

    def test_valuta_bestimmt_den_zahltag(self):
        from finance.models import Buchung, Zahlungseingang
        valuta = self.heute - timedelta(days=3)
        self._post(betrag='1810.00', valuta=valuta.isoformat())
        z = Zahlungseingang.objects.get(debitoren_rechnung=self.r)
        self.assertEqual(z.datum_eingang, valuta,
                         'Der Erfassungstag gilt als Zahltag statt der Valuta.')
        self.assertEqual(Buchung.objects.get(zahlungseingang=z).datum, valuta)

    def test_valuta_in_schweizer_schreibweise(self):
        from finance.models import Zahlungseingang
        valuta = self.heute - timedelta(days=2)
        self._post(valuta=valuta.strftime('%d.%m.%Y'))
        self.assertEqual(Zahlungseingang.objects.get().datum_eingang, valuta)

    def test_valuta_in_der_zukunft_wird_abgewiesen(self):
        from finance.models import Zahlungseingang
        self._post(valuta=(self.heute + timedelta(days=2)).isoformat())
        self.assertFalse(Zahlungseingang.objects.exists())

    def test_ohne_valuta_gilt_heute(self):
        from finance.models import Zahlungseingang
        self._post()
        self.assertEqual(Zahlungseingang.objects.get().datum_eingang, self.heute)

    def test_valuta_am_fristende_wahrt_die_257d_frist(self):
        """Am letzten Fristtag gutgeschrieben, nach Fristende erfasst: Die Frist ist gewahrt."""
        from core.models import Pendenz
        p = Pendenz.objects.create(
            titel='Art. 257d: Zahlungsfrist läuft ab – X', kategorie='frist', vertrag=self.v,
            quelle=f'257d:{self.v.pk}', faellig_am=self.heute - timedelta(days=1))
        # Fristansetzung vor 31 Tagen — die Miete (fällig vor 20 Tagen) war da noch nicht fällig;
        # darum Ansetzung NACH dem Fälligkeitstag, Fristende gestern.
        Pendenz.objects.filter(pk=p.pk).update(erstellt_am=timezone.now() - timedelta(days=18))
        self._post(valuta=(self.heute - timedelta(days=1)).isoformat())
        p.refresh_from_db()
        self.assertTrue(p.erledigt, 'Valuta am Fristende wurde als verspätet gewertet.')
