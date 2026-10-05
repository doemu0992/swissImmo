"""Hauptbuch-Anbindung: Vorschreibung, Zahlung (direkt und aus dem Import), Abschluss."""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase

from finance.booking import konto as konto_nr
from finance.models import Buchung, Zahlungseingang
from stweg import budget as bd
from stweg import hauptbuch
from stweg.models import StwegAkonto, StwegVorschreibung
from stweg.schluessel import kostenart_zuordnen, lift_schluessel
from stweg.services import AbrechnungsFehler, StwegAbrechnungService
from stweg.test_budget import budget_2026, haus_mit_eigentuemern
from stweg.test_schluessel import konto
from stweg.tests import rechnung

D = Decimal


def saldo(nummer):
    """Soll minus Haben auf dem Konto, alle Buchungen (Stornos sind Gegenbuchungen)."""
    k = konto_nr(nummer)
    soll = Buchung.objects.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or D('0')
    haben = Buchung.objects.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or D('0')
    return soll - haben


def eingang(betrag, konto_nummer='1190', status='verbucht'):
    """Ein importierter, nicht zuordenbarer Bankeingang: Soll 1020 / Haben 1190 + Zahlungseingang."""
    from finance.booking import buche
    ze = Zahlungseingang.objects.create(betrag=D(betrag), konto=konto_nr(konto_nummer), status=status,
                                        bemerkung='Import UNGEKLÄRT: Anna', datum_eingang=date(2026, 2, 1))
    buche('1020', konto_nummer, betrag, 'Import', datum=date(2026, 2, 1), zahlung=ze)
    return ze


class VorschreibungBuchenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = budget_2026(self.lg)
        bd.vorlegen(self.b)

    def test_genehmigung_bucht_jede_rate(self):
        bd.budget_genehmigen(self.b)
        self.assertEqual(Buchung.objects.filter(soll_konto__nummer='1110', haben_konto__nummer='2035').count(), 20)
        self.assertEqual(saldo('1110'), D('1850.00'))             # Budget 1000 + 850
        self.assertEqual(saldo('2035'), D('-1850.00'))            # Passiv: Haben-Überhang
        self.assertTrue(all(v.buchung_id for v in StwegVorschreibung.objects.all()))
        self.assertEqual({b.liegenschaft_id for b in Buchung.objects.all()}, {self.lg.pk})

    def test_gesperrte_periode_verhindert_die_genehmigung_ganz(self):
        from django.utils import timezone
        org = self.lg.organisation
        org.buchung_gesperrt_bis = timezone.localdate()
        org.save()
        with self.assertRaises(bd.BudgetFehler) as ctx:
            bd.budget_genehmigen(self.b)
        self.assertIn('Periode', str(ctx.exception))
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'vorgelegt')
        self.assertFalse(StwegVorschreibung.objects.exists())
        self.assertFalse(Buchung.objects.exists())


class ZahlungBuchenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.a = self.e[1]

    def zahlung(self, betrag='100', **kw):
        return StwegAkonto.objects.create(einheit=self.a, betrag=D(betrag), datum=date(2026, 2, 1), **kw)

    def test_direkte_zahlung_geht_auf_die_bank(self):
        z = self.zahlung()
        hauptbuch.zahlung_buchen(z)
        b = Buchung.objects.get()
        self.assertEqual((b.soll_konto.nummer, b.haben_konto.nummer, b.betrag), ('1020', '1110', D('100.00')))
        self.assertEqual(z.buchung_id, b.pk)
        with self.assertRaises(hauptbuch.HauptbuchFehler):         # nicht zweimal
            hauptbuch.zahlung_buchen(z)

    def test_zahlung_aus_dem_import_bucht_die_bank_nicht_nochmals(self):
        ze = eingang('100')
        bank_vorher = saldo('1020')
        z = self.zahlung(zahlungseingang=ze)
        hauptbuch.zahlung_buchen(z)
        self.assertEqual(saldo('1020'), bank_vorher)               # die Bank stand schon im Import
        self.assertEqual(saldo('1190'), D('0.00'))                 # Durchlaufkonto geleert
        self.assertEqual(saldo('1110'), D('-100.00'))
        ze.refresh_from_db()
        self.assertIsNone(ze.konto_id)
        self.assertEqual(ze.liegenschaft_id, self.lg.pk)
        self.assertIn('STWEG', ze.bemerkung)

    def test_import_zuordnung_wird_geprueft(self):
        for ze, text in ((eingang('50'), 'lautet auf'),                         # anderer Betrag
                         (eingang('100', konto_nummer='2030'), 'Durchlaufkonto')):
            z = self.zahlung(zahlungseingang=ze)
            with self.assertRaisesRegex(hauptbuch.HauptbuchFehler, text):
                hauptbuch.zahlung_buchen(z)
            z.delete()
        ze = eingang('100')
        hauptbuch.zahlung_buchen(self.zahlung(zahlungseingang=ze))
        ze.refresh_from_db()
        z2 = self.zahlung(zahlungseingang=ze)
        with self.assertRaises(hauptbuch.HauptbuchFehler):         # ist nicht mehr geparkt
            hauptbuch.zahlung_buchen(z2)

    def test_ein_eingang_nicht_zwei_zahlungen(self):
        ze = eingang('100')
        self.zahlung(zahlungseingang=ze)                           # erfasst, noch nicht gebucht
        z2 = self.zahlung(zahlungseingang=ze)
        with self.assertRaisesRegex(hauptbuch.HauptbuchFehler, 'schon einer Zahlung zugeordnet'):
            hauptbuch.zahlung_buchen(z2)

    def test_storno_ist_eine_gegenbuchung_und_gibt_den_eingang_frei(self):
        ze = eingang('100')
        z = self.zahlung(zahlungseingang=ze)
        hauptbuch.zahlung_buchen(z)
        hauptbuch.zahlung_stornieren(z)
        z.refresh_from_db()
        self.assertEqual(saldo('1110'), D('0.00'))
        self.assertEqual(saldo('1190'), D('-100.00'))              # wieder geparkt, wie nach dem Import (Haben)
        self.assertTrue(Buchung.objects.filter(ist_storno=True, storno_von_id=z.buchung_id).exists())
        self.assertIsNotNone(z.buchung.storniert_am)
        ze.refresh_from_db()
        self.assertEqual(ze.konto.nummer, '1190')                  # wieder zuordenbar
        self.assertIsNone(hauptbuch.zahlung_stornieren(z))         # ein zweites Mal: nichts

    def test_altbestand_ohne_buchung_wird_nicht_angefasst(self):
        z = self.zahlung()
        self.assertIsNone(hauptbuch.zahlung_stornieren(z))
        self.assertFalse(Buchung.objects.exists())


class AbschlussBuchenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.k_lift = konto('4200', 'Lift')
        kostenart_zuordnen(self.lg, self.k_lift, lift_schluessel(self.lg))
        self.b = budget_2026(self.lg)
        bd.vorlegen(self.b)
        bd.budget_genehmigen(self.b)
        for e in self.e:
            for v in StwegVorschreibung.objects.filter(einheit=e):
                hauptbuch.zahlung_buchen(StwegAkonto.objects.create(einheit=e, betrag=v.betrag, datum=v.faellig_am))
        rechnung(self.lg, 1300, date(2026, 3, 1))
        rechnung(self.lg, 700, date(2026, 6, 1), konto=self.k_lift)
        self.a = StwegAbrechnungService(self.lg).abrechnen(2026)

    def test_beitraege_ergeben_genau_die_kostenanteile(self):
        StwegAbrechnungService.abschliessen(self.a)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'abgeschlossen')
        self.assertEqual(-saldo('3100'), self.a.gesamtkosten)       # Ertrag = Kostenanteile
        self.assertEqual(saldo('2035'), D('0.00'))                  # Akonto vollständig freigegeben
        # 1110 je Gemeinschaft = Kostenanteile − Zahlungen = Summe der Salden der Abrechnung
        self.assertEqual(saldo('1110'), sum(p.saldo for p in self.a.positionen.all()))
        self.assertEqual(saldo('1020'), D('1850.00'))               # was tatsächlich bezahlt wurde

    def test_zweiter_abschluss_bucht_nichts_nochmals(self):
        StwegAbrechnungService.abschliessen(self.a)
        n = Buchung.objects.count()
        StwegAbrechnungService.abschliessen(self.a)
        self.assertEqual(Buchung.objects.count(), n)
        with self.assertRaises(hauptbuch.HauptbuchFehler):
            hauptbuch.abschluss_buchen(self.a)

    def test_nachzahlung_und_guthaben_haben_die_richtige_richtung(self):
        StwegAbrechnungService.abschliessen(self.a)
        for p in self.a.positionen.select_related('einheit'):
            belege = list(p.buchungen.all())
            if p.saldo > 0:
                self.assertTrue(any(b.soll_konto.nummer == '1110' and b.haben_konto.nummer == '3100'
                                    and b.betrag == p.saldo for b in belege), p.einheit)
            elif p.saldo < 0:
                self.assertTrue(any(b.soll_konto.nummer == '3100' and b.haben_konto.nummer == '1110'
                                    and b.betrag == -p.saldo for b in belege), p.einheit)

    def test_gesperrte_periode_schliesst_nicht_ab_und_bucht_nichts(self):
        org = self.lg.organisation
        org.buchung_gesperrt_bis = date(2026, 12, 31)
        org.save()
        n = Buchung.objects.count()
        with self.assertRaises(AbrechnungsFehler):
            StwegAbrechnungService.abschliessen(self.a)
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, Buchung.objects.count()), ('entwurf', n))

    def test_fondszahlung_deckt_den_kostenanteil_nicht(self):
        z = StwegAkonto.objects.create(einheit=self.e[0], betrag=D('500'), datum=date(2026, 6, 1), zweck='fonds')
        hauptbuch.zahlung_buchen(z)
        vorher = self.a.positionen.get(einheit=self.e[0]).akonto
        a2 = StwegAbrechnungService(self.lg).abrechnen(2026)           # ersetzt den Entwurf
        self.assertEqual(a2.positionen.get(einheit=self.e[0]).akonto, vorher)
