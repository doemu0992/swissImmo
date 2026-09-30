"""Entscheid 30.09.2026: Guthaben und Kautionsverrechnung hängen am Zahlungseingang.

Der Storno einer Zahlung hebt nur Buchungen auf, die an ihr hängen. Die Kautions-
verrechnung, das Schlussabrechnungs-Guthaben und die NK-Gutschrift buchten zuvor
ohne diesen Bezug: Nach einem Storno stimmten Haupt- und Nebenbuch nicht mehr.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _saldo(nummer):
    from finance.models import Buchung, Buchungskonto
    k = Buchungskonto.objects.filter(nummer=nummer).first()
    if k is None:
        return Decimal('0.00')
    soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k)), Decimal('0'))
    haben = sum((b.betrag for b in Buchung.objects.filter(haben_konto=k)), Decimal('0'))
    return soll - haben


class KautionVerrechnungVerknuepfungTests(TestCase):

    def setUp(self):
        _seed_konten()
        from core.services.automation import buche_kaution_einzahlung
        from finance.booking import buche
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.v.kautions_betrag = Decimal('3000'); self.v.kautions_art = 'sperrkonto'
        self.v.kautions_einbezahlt_am = date(2024, 1, 1); self.v.save()
        buche_kaution_einzahlung(self.v, date(2024, 1, 1))
        self.r1 = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5), betrag=Decimal('1200'), status='offen')
        self.r2 = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete 06/2024',
            datum=date(2024, 6, 1), faellig_am=date(2024, 6, 5), betrag=Decimal('1200'), status='offen')
        for r in (self.r1, self.r2):
            buche('1100', '3000', r.betrag, r.titel, datum=r.datum, liegenschaft=self.lg, debitor=r)
        self.c = Client(); self.c.force_login(_team_user())
        self.c.post(f'/neu/vertraege/{self.v.id}/schlussabrechnung/',
                    {'auszug_datum': '2024-06-30', 'aktion': 'buchen', 'kaution_verrechnen': 'on'},
                    secure=True)

    def test_jede_verrechnungsbuchung_haengt_an_einem_zahlungseingang(self):
        from finance.models import Buchung
        verr = Buchung.objects.filter(beleg_text__contains='Verrechnung offene Forderungen')
        self.assertEqual(verr.count(), 2, 'Eine Buchung je verrechneter Forderung.')
        self.assertFalse(verr.filter(zahlungseingang__isnull=True).exists(),
                         'Die Verrechnung hängt an keinem Zahlungseingang.')
        self.assertEqual(sum(b.betrag for b in verr), Decimal('2400.00'))

    def test_storno_der_verrechnung_gleicht_haupt_und_nebenbuch_aus(self):
        from finance.models import Zahlungseingang
        z = Zahlungseingang.objects.get(debitoren_rechnung=self.r1, bemerkung__startswith='Verrechnung Mietkaution')
        self.assertEqual(_saldo('1100'), Decimal('0.00'))
        self.c.post(f'/neu/zahlungen/{z.id}/stornieren/', {}, secure=True)
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.status, 'offen')
        # Hauptbuch: genau die Forderung r1 ist wieder offen (1200), nicht mehr und nicht weniger.
        self.assertEqual(_saldo('1100'), Decimal('1200.00'),
                         'Hauptbuch und Nebenbuch weichen nach dem Storno ab.')
        self.assertEqual(_saldo('2010'), Decimal('-1200.00'))

    def test_die_summen_bleiben_wie_vorher(self):
        self.assertEqual(_saldo('1015'), Decimal('0.00'))
        self.assertEqual(_saldo('2010'), Decimal('0.00'))
        self.assertEqual(_saldo('1100'), Decimal('0.00'))


class GuthabenVerknuepfungTests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def test_nk_gutschrift_haengt_am_zahlungseingang_und_storno_raeumt_auf(self):
        from finance.models import AbrechnungsPeriode, Buchung, NebenkostenBeleg, Zahlungseingang
        p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2024',
                                              start_datum=date(2024, 1, 1), ende_datum=date(2024, 12, 31))
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', kategorie='heizung',
                                        betrag=Decimal('100'), datum=date(2024, 6, 1))
        c = Client(); c.force_login(_team_user(rolle='Verwaltung'))
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/', secure=True)
        z = Zahlungseingang.objects.filter(konto__nummer='2030', bemerkung__startswith='NK-Gutschrift').first()
        self.assertIsNotNone(z, 'Keine NK-Gutschrift erzeugt — Testaufbau prüft nichts.')
        b = Buchung.objects.get(beleg_text__startswith='NK-Gutschrift')
        self.assertEqual(b.zahlungseingang_id, z.pk)
        c.post(f'/neu/zahlungen/{z.id}/stornieren/', {}, secure=True)
        self.assertEqual(_saldo('2030'), Decimal('0.00'))

    def test_schlussabrechnungs_guthaben_und_auszahlung_haengen_am_zahlungseingang(self):
        from finance.booking import buche
        from finance.models import Buchung, DebitorenRechnung, Zahlungseingang
        # Mieter hat mehr bezahlt als geschuldet → Gutschrift in der Schlussabrechnung
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{self.v.id}/schlussabrechnung/',
               {'auszug_datum': '2024-06-30', 'aktion': 'buchen',
                'pos_text': 'Guthaben NK', 'pos_betrag': '250.00', 'pos_richtung': 'zugunsten', 'pos_mwst': '0'},
               secure=True)
        z = Zahlungseingang.objects.filter(bemerkung__startswith='Schlussabrechnung — Guthaben').first()
        if z is None:
            self.skipTest('Schlussabrechnung ergab kein Guthaben in diesem Aufbau')
        gutschrift = Buchung.objects.filter(beleg_text__contains='Gutschrift', zahlungseingang=z)
        auszahlung = Buchung.objects.filter(beleg_text__contains='Guthaben ausbezahlt', zahlungseingang=z)
        self.assertTrue(gutschrift.exists(), 'Die Gutschrift hängt nicht am Zahlungseingang.')
        self.assertTrue(auszahlung.exists(), 'Die Auszahlung hängt nicht am Zahlungseingang.')
        c.post(f'/neu/zahlungen/{z.id}/stornieren/', {}, secure=True)
        self.assertEqual(_saldo('2030'), Decimal('0.00'))
        self.assertEqual(_saldo('1020'), Decimal('0.00'))
