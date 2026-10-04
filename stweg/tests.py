"""Tests des STWEG-Moduls."""
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _test_organisation
from portfolio.models import Einheit, Liegenschaft
from stweg.validierung import WertquotenFehler, pruefe_wertquoten


def neue_stweg(name='Sonnenblick', quoten=(200, 300, 500), total=1000, status='entwurf'):
    """STWEG als Entwurf mit Einheiten; Status wird erst danach gesetzt."""
    lg = Liegenschaft.objects.create(
        strasse=f'{name}weg 1', plz='8000', ort='Zürich', typ='STWEG',
        status='entwurf', wertquote_total=total, organisation=_test_organisation())
    einheiten = [
        Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Whg {i + 1}', typ='stwe',
                               wertquote=Decimal(q))
        for i, q in enumerate(quoten)]
    if status != 'entwurf':
        lg.status = status
        lg.save()
    return lg, einheiten


class WertquotenValidierungTests(TestCase):
    def test_999_von_1000_blockiert_aktivierung(self):
        lg, _ = neue_stweg(quoten=(200, 300, 499))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler) as ctx:
            lg.save()
        self.assertIn('999/1000', str(ctx.exception))
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'entwurf')      # nichts gespeichert

    def test_1001_von_1000_blockiert_ebenfalls(self):
        lg, _ = neue_stweg(quoten=(200, 300, 501))
        lg.status = 'aktiv'
        with self.assertRaises(WertquotenFehler):
            lg.save()

    def test_exakt_1000_wird_aktiv(self):
        lg, _ = neue_stweg(quoten=(200, 300, 500))
        lg.status = 'aktiv'
        lg.save()
        lg.refresh_from_db()
        self.assertEqual(lg.status, 'aktiv')

    def test_anderer_nenner_100(self):
        lg, _ = neue_stweg(quoten=(20, 30, 50), total=100)
        lg.status = 'aktiv'
        lg.save()

    def test_neue_stweg_nicht_direkt_aktiv(self):
        with self.assertRaises(WertquotenFehler):
            Liegenschaft.objects.create(
                strasse='X 1', plz='8000', ort='Zürich', typ='STWEG', status='aktiv',
                organisation=_test_organisation())

    def test_mietliegenschaft_wird_nicht_geprueft(self):
        lg = Liegenschaft.objects.create(
            strasse='Miete 1', plz='8000', ort='Zürich', organisation=_test_organisation())
        Einheit.objects.create(liegenschaft=lg, bezeichnung='A', typ='whg')   # Quote Default 10
        lg.save()
        pruefe_wertquoten(lg)                       # wirft nicht
        self.assertEqual((lg.typ, lg.status), ('MIETE', 'aktiv'))

    def test_entwurf_darf_unvollstaendig_sein(self):
        lg, _ = neue_stweg(quoten=(200, 300))
        lg.save()                                   # Entwurf: keine Prüfung


class VerteilungTests(TestCase):
    def test_summe_ist_exakt(self):
        from stweg.verteilung import verteile_nach_quoten
        r = verteile_nach_quoten(Decimal('100.00'), {1: 1, 2: 1, 3: 1})
        self.assertEqual(sum(r.values()), Decimal('100.00'))
        self.assertEqual(sorted(r.values()), [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')])

    def test_proportional(self):
        from stweg.verteilung import verteile_nach_quoten
        r = verteile_nach_quoten(Decimal('4000'), {1: 200, 2: 300, 3: 500})
        self.assertEqual(r, {1: Decimal('800.00'), 2: Decimal('1200.00'), 3: Decimal('2000.00')})


class ErneuerungsfondsTests(TestCase):
    def setUp(self):
        self.lg, self.einheiten = neue_stweg(quoten=(200, 300, 500), status='aktiv')

    def test_einlage_nach_wertquoten_und_als_passivum(self):
        from finance.models import Buchung, Buchungskonto
        from stweg.fonds import jahreseinlage_belasten
        r = jahreseinlage_belasten(self.lg, 2026, Decimal('10000'))
        self.assertEqual([r[e] for e in self.einheiten],
                         [Decimal('2000.00'), Decimal('3000.00'), Decimal('5000.00')])
        fonds = self.lg.erneuerungsfonds
        self.assertEqual(fonds.bestand, Decimal('10000.00'))
        # Passivum, kein Ertrag, kein Aufwand
        k2800 = Buchungskonto.objects.get(nummer='2800')
        self.assertEqual(k2800.typ, 'passiv')
        b = Buchung.objects.filter(liegenschaft=self.lg)
        self.assertEqual(b.count(), 3)
        self.assertTrue(all(x.haben_konto.nummer == '2800' and x.soll_konto.nummer == '1110' for x in b))
        self.assertFalse(b.filter(soll_konto__typ__in=['aufwand', 'ertrag']).exists())
        self.assertFalse(b.filter(haben_konto__typ__in=['aufwand', 'ertrag']).exists())

    def test_einlage_nur_einmal_pro_jahr(self):
        from stweg.fonds import FondsFehler, jahreseinlage_belasten
        jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))
        with self.assertRaises(FondsFehler):
            jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))

    def test_einlage_bei_falschen_quoten_blockiert(self):
        from stweg.fonds import jahreseinlage_belasten
        e = self.einheiten[0]
        e.wertquote = Decimal(199)
        e.save()
        with self.assertRaises(WertquotenFehler):
            jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))

    def test_entnahme_und_saldo(self):
        from stweg.fonds import FondsFehler, entnahme_buchen, jahreseinlage_belasten
        jahreseinlage_belasten(self.lg, 2026, Decimal('1000'))
        entnahme_buchen(self.lg, 2026, Decimal('400'), 'Dach')
        self.lg.erneuerungsfonds.refresh_from_db()
        self.assertEqual(self.lg.erneuerungsfonds.bestand, Decimal('600.00'))
        with self.assertRaises(FondsFehler):
            entnahme_buchen(self.lg, 2026, Decimal('601'), 'zu viel')

    def test_miet_job_ueberspringt_stweg(self):
        from core.services.automation import run_erneuerungsfonds_einlage
        from stweg.fonds import fonds_von
        f = fonds_von(self.lg)
        f.jaehrliche_einlage = Decimal('500')
        f.save()
        self.assertEqual(run_erneuerungsfonds_einlage(2026)[0], 0)
