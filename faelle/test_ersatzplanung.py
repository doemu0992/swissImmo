"""Geräte in der Ersatzplanung — und die ehrliche Lücke beim Budget (4b.20).

WORUM ES GING

`core/services/ersatzplanung.py` gab es längst: Restnutzungsdauer,
Jahresbudget, Fondsdeckung, PDF-Report. Sie rechnete aber **nur** mit
`Ausstattung` — ausgerechnet die Geräte, die teuren Posten (Heizung, Boiler,
Lift), blieben aussen vor. Sie standen stattdessen auf einer eigenen Seite
`/neu/assets/`, die nur auflistete und nichts rechnete, und deren
CRUD-Pfade (`fw_asset_neu/bearbeiten/loeschen`) eine ZWEITE Fassung von
`/neu/geraet/*` waren — zwei Implementierungen auf demselben Modell.

DER HEIKELSTE PUNKT: GERÄTE HABEN KEIN `neuwert`-FELD

Sie erscheinen in den Zeilen und den Zählern, tragen aber nichts zum
Jahresbudget bei. Einen Preis zu schätzen wäre die schlechtere Antwort als
eine ehrliche Lücke — ein erfundener Boilerpreis wanderte über den PDF-Report
direkt in die Fondsplanung des Eigentümers und sähe dort aus wie eine Zahl.
`BudgetLueckeTests` hält genau das fest.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.services.ersatzplanung import (berechne_ersatzplanung,
                                         geraet_lebensdauer)
from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture

HEUTE = timezone.localdate()


class _Basis(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _lebensdauern(self):
        """Die Standardtabelle — sie entsteht sonst erst beim Seitenaufruf."""
        from core.services.raumkatalog import seed_lebensdauer
        seed_lebensdauer(self.a.organisation)

    def _geraet(self, kategorie, jahre_alt=None, **felder):
        from portfolio.models import Geraet
        werte = {'liegenschaft': self.a.liegenschaft, 'kategorie': kategorie}
        werte.update(felder)
        if jahre_alt is not None:
            werte['installations_datum'] = date(HEUTE.year - jahre_alt,
                                                HEUTE.month, 1)
        return Geraet.objects.create(**werte)

    def _plan(self):
        with mandant(self.a.organisation):
            return berechne_ersatzplanung()

    def _zeile(self, geraet):
        return next(r for r in self._plan()['rows']
                    if r['art'] == 'geraet' and r['g'].id == geraet.id)


class KategorienbrueckeTests(_Basis):
    """Die Lebensdauertabelle heisst «Heizung / Wärmeerzeuger», die
    Geräteliste «Heizung». Ohne Brücke fände keine der beiden die andere."""

    def test_die_bruecke_findet_die_heizung(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Heizung')
            self.assertEqual(geraet_lebensdauer(g), 30)

    def test_identische_namen_brauchen_keine_bruecke(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            self.assertEqual(geraet_lebensdauer(self._geraet('Waschmaschine')), 15)

    def test_der_aufzug_hat_bewusst_keine_lebensdauer(self):
        """Der Raumkatalog kennt keine. Eine Frist zu behaupten, für die es
        keine Grundlage gibt, ist schlechter als «Keine Datenbasis»."""
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Aufzug', jahre_alt=40)
            self.assertIsNone(geraet_lebensdauer(g))
            self.assertEqual(self._zeile(g)['status'], 'unbekannt')

    def test_ohne_kategorie_keine_lebensdauer(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            self.assertIsNone(geraet_lebensdauer(self._geraet('')))


class GeraetZeileTests(_Basis):

    def test_ein_altes_geraet_ist_faellig(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Geschirrspüler', jahre_alt=20)   # Lebensdauer 12
            zeile = self._zeile(g)
        self.assertEqual(zeile['status'], 'faellig')
        self.assertLessEqual(zeile['rest'], 0)

    def test_ein_neues_geraet_ist_im_nutzungszeitraum(self):
        """Gegenprobe — sonst stünde jedes Gerät auf «fällig»."""
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Geschirrspüler', jahre_alt=1)
            self.assertEqual(self._zeile(g)['status'], 'ok')

    def test_kurz_vor_schluss_meldet_bald(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Geschirrspüler', jahre_alt=11)   # Rest ~1 J
            self.assertEqual(self._zeile(g)['status'], 'bald')

    def test_ohne_einbaudatum_ist_der_status_unbekannt(self):
        """Ein Gerät ohne Einbaudatum ist nicht alt, sondern unbekannt."""
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Geschirrspüler')
            zeile = self._zeile(g)
        self.assertEqual(zeile['status'], 'unbekannt')
        self.assertIsNone(zeile['rest'])

    def test_die_zeile_zeigt_auf_ihren_erfassungsort(self):
        """Ein Befund ohne Weg zur Handlung ist eine Beschwerde."""
        from portfolio.models import Einheit
        with mandant(self.a.organisation):
            self._lebensdauern()
            am_haus = self._geraet('Heizung')
            am_objekt = self._geraet('Geschirrspüler', liegenschaft=self.a.liegenschaft,
                                     einheit=self.a.einheit)
            self.assertIn(f'/neu/liegenschaften/{self.a.liegenschaft.id}/',
                          self._zeile(am_haus)['ziel_url'])
            self.assertIn(f'/neu/objekte/{self.a.einheit.id}/',
                          self._zeile(am_objekt)['ziel_url'])


class BudgetLueckeTests(_Basis):
    """Geräte stehen in der Liste, nicht im Budget — und die Seite sagt das."""

    def test_ein_faelliges_geraet_erhoeht_das_budget_nicht(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            vorher = berechne_ersatzplanung()
            self._geraet('Heizung', jahre_alt=40)
            nachher = berechne_ersatzplanung()
        self.assertEqual(nachher['budget_total'], vorher['budget_total'])
        # Relativ gezaehlt: Das `MandantenFixture` bringt selbst ein Geraet
        # mit. Eine absolute Zahl haette hier dessen Bestand geprueft, nicht
        # die Regel — und waere beim naechsten Fixture-Zuwachs rot geworden.
        self.assertEqual(nachher['n_geraete'], vorher['n_geraete'] + 1)
        self.assertEqual(nachher['budget_ohne_neuwert'],
                         vorher['budget_ohne_neuwert'] + 1)

    def test_die_ausstattung_erhoeht_es_sehr_wohl(self):
        """Gegenprobe: Ohne sie wäre der Test oben auch dann grün, wenn das
        Budget gar nicht mehr rechnete."""
        from portfolio.models import Ausstattung
        with mandant(self.a.organisation):
            self._lebensdauern()
            vorher = berechne_ersatzplanung()['budget_total']
            Ausstattung.objects.create(
                einheit=self.a.einheit, raum='Küche', kategorie='Backofen',
                einbau_datum=date(HEUTE.year - 20, 1, 1),
                neuwert=Decimal('1200'), lebensdauer_jahre=15)
            nachher = berechne_ersatzplanung()['budget_total']
        self.assertEqual(nachher - vorher, Decimal('1200'))

    def test_das_geraet_steht_trotzdem_in_den_zeilen(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            g = self._geraet('Heizung', jahre_alt=40)
            arten = [r['art'] for r in berechne_ersatzplanung()['rows']]
        self.assertIn('geraet', arten)
        self.assertEqual(self._zeile(g)['neuwert'], Decimal('0.00'))


class SeitenTests(_Basis):

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def test_das_geraet_erreicht_die_seite(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            self._geraet('Heizung', jahre_alt=40, marke='Viessmann')
            html = self.c.get('/neu/ersatzplanung/').content.decode()
        self.assertIn('Viessmann', html)
        self.assertIn('Gerät', html)

    def test_die_seite_benennt_die_budgetluecke(self):
        """Ein Budget, dem die Heizung fehlt, sieht sonst aus wie ein
        vollständiges."""
        with mandant(self.a.organisation):
            self._lebensdauern()
            self._geraet('Heizung', jahre_alt=40)
            html = self.c.get('/neu/ersatzplanung/').content.decode()
        self.assertIn('nicht im Budget', html)
        self.assertIn('kein Neuwert', html)

    def test_assets_leitet_auf_die_ersatzplanung(self):
        """Die Seite ist aufgelöst — Lesezeichen müssen trotzdem halten."""
        antwort = self.c.get('/neu/assets/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/neu/ersatzplanung/')

    def test_die_weiterleitung_behaelt_den_liegenschaftsfilter(self):
        antwort = self.c.get(f'/neu/assets/?lg={self.a.liegenschaft.id}')
        self.assertIn(f'lg={self.a.liegenschaft.id}', antwort['Location'])

    def test_die_doppelten_crud_pfade_sind_weg(self):
        """`fw_asset_neu/bearbeiten/loeschen` schrieben auf dasselbe Modell wie
        `/neu/geraet/*`. Zwei Fassungen derselben Sache laufen auseinander."""
        from django.urls import NoReverseMatch, reverse
        for name in ('fw_asset_neu', 'fw_asset_bearbeiten', 'fw_asset_loeschen'):
            with self.subTest(name=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(name, args=[1])

    def test_der_verbleibende_weg_zum_geraet_funktioniert(self):
        """Gegenprobe zur vorigen Prüfung: Es darf nicht einfach alles weg
        sein — die Erfassung muss weiterhin erreichbar bleiben."""
        from django.urls import reverse
        self.assertTrue(reverse('fw_geraet_add'))
        self.assertTrue(reverse('fw_geraet_edit', args=[1]))
        self.assertTrue(reverse('fw_geraet_del', args=[1]))


class TrennungTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_b_sieht_die_geraete_von_a_nicht(self):
        """Das Gerät von A trägt seinen Bezug über die Liegenschaft.

        Liefe die Abfrage am Mandantenfilter vorbei, stünde die Heizung von A
        in der Ersatzplanung von B — und über den PDF-Report in dessen
        Fondsplanung.
        """
        from portfolio.models import Geraet
        with mandant(self.a.organisation):
            Geraet.objects.create(liegenschaft=self.a.liegenschaft,
                                  kategorie='Heizung', marke='NurBeiA')
        with mandant(self.b.organisation):
            rows = berechne_ersatzplanung()['rows']
        marken = [r['g'].marke for r in rows if r['art'] == 'geraet']
        self.assertNotIn('NurBeiA', marken)


class BudgetPdfTests(_Basis):
    """Der Budget-Report muss Gerätezeilen aushalten — und sie zeigen.

    BEFUND 21.08.2026, eingeschleppt von 4b.20 selbst: `ersatzplanung_pdf.py`
    las je Zeile `r['a'].kategorie` und `r['a'].raum`. Seit 4b.20 stehen in
    `rows` auch Geräte, und die tragen `'a': None` — der Schlüssel gehört der
    Ausstattung. Sobald eine Verwaltung ein einziges Gerät erfasst hatte,
    endete `/neu/ersatzplanung/?pdf=1` in einem `AttributeError`.

    WARUM ES DURCHRUTSCHTE: Auf der Seite selbst passiert nichts. Die Vorlage
    liest `bezeichnung`, das beide Zeilenarten führen — `test_das_geraet_-
    erreicht_die_seite` weiter oben blieb die ganze Zeit grün. Nur der
    PDF-Knopf starb, ausgerechnet bei dem Dokument, das der Eigentümer
    bekommt. Kein Test zu 4b.20 rief das PDF auf.

    GEPRÜFT WIRD DER INHALT, NICHT DER STATUSCODE. Ein Report, der Geräte
    stillschweigend überspringt, antwortete ebenfalls mit 200 — und wäre der
    schlimmere Fehler: Der Absturz ist sichtbar, die Lücke nicht. `pypdf`
    liegt bereits im Bestand (requirements.txt), es kommt nichts Neues dazu.
    """

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _pdf_text(self, antwort):
        import io

        from pypdf import PdfReader
        return '\n'.join(s.extract_text() or ''
                         for s in PdfReader(io.BytesIO(antwort.content)).pages)

    def test_das_geraet_steht_im_budget_report(self):
        with mandant(self.a.organisation):
            self._lebensdauern()
            self._geraet('Heizung', jahre_alt=40, marke='Viessmann')
            antwort = self.c.get('/neu/ersatzplanung/?pdf=1')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        text = self._pdf_text(antwort)
        self.assertIn('Heizung', text)
        self.assertIn('Viessmann', text)

    def test_ein_geraet_ohne_datenbasis_bringt_den_report_nicht_um(self):
        """Weder `ersatz_jahr` noch `rest` — wenn irgendwo blind gerechnet
        wird, fällt es hier auf."""
        with mandant(self.a.organisation):
            self._geraet('Gartengerät')
            antwort = self.c.get('/neu/ersatzplanung/?pdf=1')
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('Gartengerät', self._pdf_text(antwort))

    def test_ein_geraet_ohne_marke_beginnt_nicht_mit_einem_trenner(self):
        """Ist nur die Kategorie erfasst, ist `detail` ein LEERER String —
        ohne Ersatz begänne die Detailzeile mit einem herrenlosen « · »."""
        with mandant(self.a.organisation):
            self._lebensdauern()
            self._geraet('Heizung', jahre_alt=40)
            text = self._pdf_text(self.c.get('/neu/ersatzplanung/?pdf=1'))
        self.assertNotIn('\n · ', text)
        self.assertIn('—', text)

    def test_geraet_und_ausstattung_gemischt(self):
        """Der Normalfall einer echten Verwaltung: beide Zeilenarten in einem
        Report, beide sichtbar."""
        from portfolio.models import Ausstattung
        with mandant(self.a.organisation):
            self._lebensdauern()
            self._geraet('Heizung', jahre_alt=40, marke='Viessmann')
            Ausstattung.objects.create(
                einheit=self.a.einheit, raum='Küche', kategorie='Backofen',
                einbau_datum=date(HEUTE.year - 20, 1, 1),
                neuwert=Decimal('1200'), lebensdauer_jahre=15)
            text = self._pdf_text(self.c.get('/neu/ersatzplanung/?pdf=1'))
        self.assertIn('Viessmann', text)
        self.assertIn('Backofen', text)
        self.assertIn('Küche', text)
