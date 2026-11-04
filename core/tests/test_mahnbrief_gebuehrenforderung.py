"""Mahnung über eine Mahngebühr: Der Brief sagt es, und es kommt keine Gebühr auf die Gebühr (4.11.2026).

ANLASS: Ein Mieter bekam eine «Zahlungserinnerung» mit «… dass für Oktober 2026 noch CHF 40.00 ausstehend sind …
Für diese Mahnung stellen wir eine Mahngebühr von CHF 40.00 in Rechnung.» Der offene Betrag war aber keine Miete,
sondern eine frühere Mahngebühr (eigene Forderung `Mahngebühr N. Mahnung`, `forderungsart='sonstige'`). Verlangt:
«für den Monat Oktober sind noch 40 Franken Mahngebühren offen» — und auf diese Mahnung keine neue Gebühr.

RECHTSLAGE (nicht neu erfunden, sondern aus dem Bestand: `core/services/mahnstufen.py`): Eine Mahngebühr braucht
eine vertragliche Grundlage oder einen nachgewiesenen Verzugsschaden (Art. 106 OR); auf eine Gebühr gibt es keine
weitere, und Zinseszins schliesst Art. 105 Abs. 3 OR aus. Die Gebühr in der Frist nach Art. 257d OR zu nennen,
wäre falsch: Dort zählen nur Mietzins und Nebenkosten (bestehende Tests in `test_257d_zugang_betrag.py`).

Gegenproben (von Hand gemacht, rot gesehen, zurückgebaut):
* in `gebuehr_fuer_forderung` den Zweig `if ist_abgeleitet(rechnung)` entfernen -> die Tests «keine Gebühr auf
  die Gebühr» (Brief, Mahnlauf, Erfassen) sind rot;
* in `mahnbrief_pdf` den Zweig `_text_abgeleitet` entfernen -> `test_brief_nennt_die_mahngebuehr` ist rot;
* in `abgeleitete_art` das Erkennen am Titel entfernen -> `test_titel_erkennung` und der Brief über die verwaiste
  Gebühr sind rot.
"""
import io
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from pypdf import PdfReader

from core.services.mahnbrief import mahnbrief_pdf
from core.services.mahnstufen import abgeleitete_art, gebuehr_fuer_forderung, ist_abgeleitet, zusammensetzung

from ._helfer import _basis_objekte
from ._uhr import bei_stichtag

HEUTE = date(2026, 11, 4)


def _text(pdf):
    return ' '.join(' '.join(s.extract_text().split()) for s in PdfReader(io.BytesIO(pdf)).pages)


class _R:
    """Eine Forderung ohne Datenbank: nur, was die Erkennung liest."""

    def __init__(self, titel, stamm=None, betrag='40.00'):
        self.titel, self.stammrechnung_id, self.betrag = titel, stamm, Decimal(betrag)


class ErkennungTests(SimpleTestCase):

    def test_titel_erkennung(self):
        self.assertEqual(abgeleitete_art(_R('Mahngebühr 1. Mahnung')), 'gebuehr')
        self.assertEqual(abgeleitete_art(_R('Verzugszins 5%')), 'zins')
        self.assertEqual(abgeleitete_art(_R('Mahngebühr 2. Mahnung + Verzugszins 5%')), 'gebuehr_zins')
        self.assertIsNone(abgeleitete_art(_R('Miete & NK 10/2026')))
        # Gegenprobe: Betreibungskosten hängen an einer Stammrechnung, sind aber keine Mahngebühr.
        self.assertIsNone(abgeleitete_art(_R('Betreibungskosten', stamm=1)))
        self.assertTrue(ist_abgeleitet(_R('Betreibungskosten', stamm=1)))
        self.assertFalse(ist_abgeleitet(_R('Miete & NK 10/2026')))

    def test_gebuehr_fuer_forderung(self):
        vertrag = type('V', (), {'mahngebuehr_vereinbart': True})()
        self.assertEqual(gebuehr_fuer_forderung(vertrag, _R('Miete'), Decimal('40.00')), Decimal('40.00'))
        self.assertEqual(gebuehr_fuer_forderung(vertrag, _R('Mahngebühr 1. Mahnung'), Decimal('40.00')),
                         Decimal('0.00'))
        self.assertEqual(gebuehr_fuer_forderung(vertrag, _R('Miete', stamm=3), Decimal('40.00')), Decimal('0.00'))
        self.assertIsNone(gebuehr_fuer_forderung(vertrag, _R('Miete'), None))
        # Der Schalter am Vertrag gilt weiter.
        vertrag.mahngebuehr_vereinbart = False
        self.assertEqual(gebuehr_fuer_forderung(vertrag, _R('Miete'), Decimal('40.00')), Decimal('0.00'))

    def test_zusammensetzung_einfach(self):
        self.assertEqual(zusammensetzung(_R('Miete'), '1700.00'), [('forderung', Decimal('1700.00'))])
        self.assertEqual(zusammensetzung(_R('Mahngebühr 1. Mahnung'), '40.00'), [('gebuehr', Decimal('40.00'))])
        self.assertEqual(zusammensetzung(_R('Verzugszins 5%'), '12.35'), [('zins', Decimal('12.35'))])


@bei_stichtag(HEUTE)
class BriefTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from finance.models import DebitorenRechnung, Mahnung
        _lg, _e, _m, cls.v = _basis_objekte()
        cls.org = cls.v.organisation
        okt = date(2026, 10, 15)
        cls.miete = DebitorenRechnung.objects.create(
            vertrag=cls.v, titel='Miete & NK 10/2026', betrag=Decimal('1700.00'), datum=okt, faellig_am=okt,
            status='offen')
        # Die Mahngebühr der Miete (eigene Forderung, `stammrechnung`) ...
        cls.gebuehr = DebitorenRechnung.objects.create(
            vertrag=cls.v, titel='Mahngebühr 1. Mahnung', betrag=Decimal('40.00'), datum=okt, faellig_am=okt,
            status='offen', forderungsart='sonstige', stammrechnung=cls.miete)
        # ... und dieselbe Gebühr, deren Stammrechnung gelöscht wurde (SET_NULL): nur noch der Titel verrät sie.
        cls.verwaist = DebitorenRechnung.objects.create(
            vertrag=cls.v, titel='Mahngebühr 1. Mahnung', betrag=Decimal('40.00'), datum=okt, faellig_am=okt,
            status='offen', forderungsart='sonstige')
        cls.gemischt = DebitorenRechnung.objects.create(
            vertrag=cls.v, titel='Mahngebühr 2. Mahnung + Verzugszins 5%', betrag=Decimal('60.00'), datum=okt,
            faellig_am=okt, status='offen', forderungsart='sonstige', stammrechnung=cls.miete)
        Mahnung.objects.create(debitoren_rechnung=cls.miete, vertrag=cls.v, stufe=2, datum=okt,
                               betrag_offen=Decimal('1700.00'), gebuehr=Decimal('40.00'), zins=Decimal('20.00'))

    def _brief(self, rechnung, stufe=1, betrag=None, gebuehr=Decimal('40.00'), letzte=False):
        return _text(mahnbrief_pdf(self.v, self.org, stufe=stufe, monat='Oktober 2026',
                                   betrag=betrag or f'{rechnung.offener_betrag:.2f}', datum=HEUTE,
                                   gebuehr=gebuehr, letzte_stufe=letzte, rechnung=rechnung))

    def test_brief_nennt_die_mahngebuehr(self):
        for r in (self.gebuehr, self.verwaist):
            with self.subTest(stamm=r.stammrechnung_id):
                text = self._brief(r)
                self.assertIn('für den Monat Oktober 2026 noch Mahngebühren von CHF 40.00 offen sind', text)
                self.assertNotIn('ausstehend', text)

    def test_keine_gebuehr_auf_die_gebuehr(self):
        for r in (self.gebuehr, self.verwaist):
            with self.subTest(stamm=r.stammrechnung_id):
                text = self._brief(r)
                self.assertNotIn('Für diese Mahnung stellen wir', text)
                self.assertNotIn('Mahngebühr von', text)
        # auch auf der Stufe mit Kündigungsandrohung (Gebühr ist keine Miete: gewöhnliche Mahnung)
        text = self._brief(self.gebuehr, stufe=3, letzte=True)
        self.assertNotIn('Für diese Mahnung stellen wir', text)
        self.assertNotIn('257d', text)

    def test_folgemahnung_ueber_gebuehr(self):
        text = self._brief(self.gebuehr, stufe=2)
        self.assertIn('die Mahngebühren für den Monat Oktober 2026 über CHF 40.00 weiterhin offen', text)
        self.assertNotIn('Für diese Mahnung stellen wir', text)

    def test_gemischter_betrag_wird_aufgeschluesselt(self):
        # 60.00 = 40.00 Gebühr (Mahnung Stufe 2) + 20.00 Zins
        text = self._brief(self.gemischt)
        self.assertIn('Mahngebühren: CHF 40.00', text)
        self.assertIn('Verzugszinsen: CHF 20.00', text)
        self.assertIn('Total: CHF 60.00', text)
        self.assertNotIn('Für diese Mahnung stellen wir', text)

    def test_miete_bleibt_wie_bisher(self):
        """Gegenprobe zur Gegenprobe: eine Mietforderung wird nicht umgeschrieben und trägt weiter die Gebühr."""
        text = self._brief(self.miete, betrag='1700.00')
        self.assertIn('Oktober 2026 noch CHF 1700.00 ausstehend sind', text)
        self.assertIn('Für diese Mahnung stellen wir eine Mahngebühr von CHF 40.00 in Rechnung', text)
        self.assertNotIn('Mahngebühren von', text)

    def test_257d_frist_summe_ohne_gebuehr(self):
        """Das 257d-Schreiben nennt die Gebühr getrennt (Wunsch der Verwaltung); sie steckt nie im Betrag der Frist."""
        text = self._brief(self.miete, stufe=3, betrag='100.00', letzte=True)
        self.assertIn('Zahlungsverzug gemäss Art. 257d OR', text)
        self.assertIn('Monat Oktober 2026 noch ein Betrag von CHF 100.00 ausstehend', text)
        self.assertIn('Mahngebühr von CHF 40.00', text)
        self.assertNotIn('140.00', text)
        # ohne Gebühr (Stufe CHF 0 bzw. Schalter am Vertrag aus) entfällt der Absatz
        ohne = self._brief(self.miete, stufe=3, betrag='100.00', letzte=True, gebuehr=Decimal('0.00'))
        self.assertNotIn('Mahngebühr von', ohne)
        from rentals.models import Mietvertrag
        Mietvertrag.objects.filter(pk=self.v.pk).update(mahngebuehr_vereinbart=False)
        self.v.refresh_from_db()
        self.assertNotIn('Mahngebühr von', self._brief(self.miete, stufe=3, betrag='100.00', letzte=True))


@bei_stichtag(HEUTE)
class MahnwesenGleichTests(TestCase):
    """Liste, Trockenlauf, Erfassen: dieselbe Gebühr wie der Brief (eine Quelle)."""

    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _stufe(self, gebuehr='40.00'):
        from core.tenancy import organisation_kontext
        from crm.models import MahnStufe
        with organisation_kontext(self.a.organisation):
            MahnStufe.objects.filter(stufe=1).update(ab_tage=1, gebuehr=Decimal(gebuehr), art_257d=False)
            MahnStufe.objects.filter(stufe__gt=1).delete()

    def _gebuehr_forderung(self, tage=3, stamm=None):
        from datetime import timedelta

        from django.utils import timezone

        from core.tenancy import organisation_kontext
        from finance.models import DebitorenRechnung
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.filter(pk=self.a.debitor.pk).update(status='bezahlt')
            faellig = timezone.localdate() - timedelta(days=tage)
            return DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, liegenschaft=self.a.liegenschaft, titel='Mahngebühr 1. Mahnung',
                betrag=Decimal('40.00'), datum=faellig, faellig_am=faellig, status='offen',
                forderungsart='sonstige', stammrechnung=stamm)

    def test_liste_zeigt_die_gebuehrenzeile_ohne_weitere_gebuehr(self):
        from django.test import Client
        self._stufe()
        self._gebuehr_forderung()
        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/mahnwesen/').content.decode()
        self.assertIn('es wird keine weitere Mahngebühr erhoben', html)

    def test_erfassen_stellt_keine_gebuehr_auf_die_gebuehr(self):
        """Auch ein von Hand eingegebener Betrag ergibt auf einer verwaisten Gebühr keine neue Gebühr."""
        from django.test import Client

        from core.tenancy import organisation_kontext
        from finance.models import DebitorenRechnung, Mahnung
        self._stufe()
        g = self._gebuehr_forderung()
        c = Client()
        c.force_login(self.a.benutzer)
        c.post('/neu/mahnwesen/erfassen/', {'rechnung_id': g.pk, 'stufe': '1', 'gebuehr': '40.00'})
        with organisation_kontext(self.a.organisation):
            m = Mahnung.objects.get(debitoren_rechnung=g)
            self.assertEqual(m.gebuehr, Decimal('0.00'))
            self.assertFalse(DebitorenRechnung.objects.filter(stammrechnung=g).exists())

    def test_trockenlauf_und_gebuehr_der_historie(self):
        """Eine gewöhnliche Mietforderung desselben Mieters bekommt die Gebühr weiter (Gegenprobe)."""
        from datetime import timedelta

        from django.utils import timezone

        from core.services.automation import run_mahnlauf
        from core.tenancy import organisation_kontext
        from finance.models import DebitorenRechnung
        self._stufe()
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.filter(pk=self.a.debitor.pk).update(status='bezahlt')
            faellig = timezone.localdate() - timedelta(days=3)
            miete = DebitorenRechnung.objects.create(
                vertrag=self.a.vertrag, liegenschaft=self.a.liegenschaft, titel='Miete Oktober', betrag=Decimal('1700'),
                datum=faellig, faellig_am=faellig, status='offen')
            res = run_mahnlauf(send_email=False, mit_zins=False, dry_run=True)
        self.assertEqual([p['rechnung'].pk for p in res['plan']], [miete.pk])
        self.assertEqual(res['plan'][0]['gebuehr'], Decimal('40.00'))
        # Die verwaiste Gebühr wird vom Lauf nicht gemahnt, wo stammrechnung gesetzt ist; sonst nur ohne Gebühr.
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.filter(pk=miete.pk).update(status='bezahlt')
        self._gebuehr_forderung()
        with organisation_kontext(self.a.organisation):
            res = run_mahnlauf(send_email=False, mit_zins=False, dry_run=True)
        self.assertEqual([p['gebuehr'] for p in res['plan']], [Decimal('0.00')])
