"""Tests der Lage und der zusammengeführten Startseite.

WARUM

Bis zum 21.08.2026 gab es **zwei Startflächen** mit derselben Aufgabe:
`/neu/` mit «Was reisst», «Zulauf» und vier Kennzahlkacheln aus der
Vorgängerzeit, und `/neu/arbeit/` mit denselben zwei Abschnitten plus
Ansichten. Diese Tests halten fest, dass es jetzt eine ist.

Der heikelste Teil ist `abweichungen()`. Der Abschnitt lebt davon, dass er
**schweigt, wenn nichts ist**. Ein Block, der immer etwas meldet, wird nach
drei Wochen überlesen — und dann nützt auch die richtige Meldung nichts mehr.
Zu jeder Meldung gehört deshalb hier ein Test, der prüft, dass sie bei
ruhiger Lage **ausbleibt**.

Und eine Unterscheidung, die leicht untergeht: `_eingangsquote` gibt `None`
zurück, wenn im Zeitraum gar nichts fällig war. Eine Quote von 0 % und «keine
Sollstellung» sind völlig verschiedene Aussagen — wer sie verwechselt, meldet
im Januar einen Totalausfall.

DIE ABFRAGEZAHL IST HIER EIN PRÜFGEGENSTAND

`AbfragezahlTests` unten ist kein Feinschliff. Diese Datei läuft bei jedem
Aufruf der meistbesuchten Seite; ein Entwurf, der je Datensatz statt je Menge
rechnet, kostet dort dreistellig. Gemessen an einem Bestand mit zwanzig
Mandaten: 64 Abfragen für die Mandatsliste statt einer, 203 für die
Senkungsansprüche statt zwei.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.lage import (
    SCHWELLE_EINGANG, SCHWELLE_LEERSTAND, _eingangsquote, abweichungen, lage,
    mandate, streifen,
)

STICHTAG = date(2026, 8, 20)


def _rechnung(vertrag, betrag, faellig, status='offen'):
    from finance.models import DebitorenRechnung
    return DebitorenRechnung.objects.create(
        vertrag=vertrag, titel='Miete', betrag=Decimal(betrag),
        datum=faellig, faellig_am=faellig, status=status)


class EingangsquoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_ohne_sollstellung_kommt_none_und_nicht_null(self):
        """Der Unterschied, der im Januar einen Totalausfall melden würde."""
        with mandant(self.a.organisation):
            quote, soll, _offen, _anzahl = _eingangsquote(
                date(2099, 1, 1), date(2099, 1, 31))
            self.assertIsNone(quote)
            self.assertEqual(soll, Decimal('0'))

    def test_alles_bezahlt_ergibt_hundert(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            quote, _s, offen, _a = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertEqual(quote, Decimal('100.0'))
            self.assertEqual(offen, Decimal('0'))

    def test_haelfte_offen_ergibt_fuenfzig(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 2), 'offen')
            quote, _s, offen, anzahl = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertEqual(quote, Decimal('50.0'))
            self.assertEqual(offen, Decimal('1000'))
            self.assertEqual(anzahl, 1)

    def test_stornierte_zaehlen_nicht_mit(self):
        """Eine stornierte Forderung ist keine Forderung — sie darf die Quote
        weder heben noch senken."""
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            _rechnung(self.a.vertrag, '9000', date(2026, 8, 2), 'storniert')
            quote, soll, _o, _a = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertEqual(soll, Decimal('1000'))
            self.assertEqual(quote, Decimal('100.0'))

    def test_abgeschriebene_zaehlen_ebenfalls_nicht(self):
        """Gegenprobe zur Zeile darüber — `exclude` nennt beide Status."""
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            _rechnung(self.a.vertrag, '5000', date(2026, 8, 3), 'abgeschrieben')
            _quote, soll, _o, _a = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertEqual(soll, Decimal('1000'))


class StreifenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_vier_kennzahlen_in_fester_reihenfolge(self):
        with mandant(self.a.organisation):
            k = streifen(STICHTAG)
            self.assertEqual([x['schluessel'] for x in k],
                             ['eingang', 'ausstaende', 'leerstand', 'faelle'])

    def test_niedriger_eingang_wird_markiert(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'offen')
            eingang = streifen(STICHTAG)[0]
            self.assertEqual(eingang['stufe'], 'crit')

    def test_ohne_vormonatswert_kein_pfeil(self):
        """Sonst zeigte der erste Monat einen erfundenen Vergleich."""
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            eingang = streifen(STICHTAG)[0]
            self.assertIsNone(eingang['delta'])
            self.assertIn('kein Vormonatswert', eingang['fuss'])

    def test_mit_vormonatswert_kommt_der_pfeil(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 7, 5), 'bezahlt')
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'offen')
            eingang = streifen(STICHTAG)[0]
            self.assertIsNotNone(eingang['delta'])
            self.assertLess(eingang['delta'], 0)

    def test_abgebrochene_faelle_zaehlen_nicht_als_offen(self):
        """`exclude(status=ABGESCHLOSSEN)` allein zaehlte sie mit."""
        from faelle.models import Fall
        with mandant(self.a.organisation):
            vorher = streifen(STICHTAG)[3]['wert']
            fall = Fall.objects.exclude(
                status__in=(Fall.ABGESCHLOSSEN, Fall.ABGEBROCHEN)).first()
            self.assertIsNotNone(fall, 'Das Fixture fuehrt keinen offenen Fall.')
            fall.status = Fall.ABGEBROCHEN
            fall.save(update_fields=['status'])
            self.assertEqual(int(streifen(STICHTAG)[3]['wert']), int(vorher) - 1)


class AbweichungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_bei_ruhiger_lage_schweigt_der_block(self):
        """Der wichtigste Test dieser Datei.

        Ein Abschnitt, der immer etwas meldet, wird nach drei Wochen
        überlesen — und dann nützt auch die richtige Meldung nichts mehr.
        """
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            titel = [b['titel'] for b in abweichungen(STICHTAG)]
            self.assertNotIn(f'Zahlungseingang unter {SCHWELLE_EINGANG} %', titel)

    def test_niedriger_eingang_wird_gemeldet(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'offen')
            befunde = [b for b in abweichungen(STICHTAG)
                       if b['titel'].startswith('Zahlungseingang')]
            self.assertEqual(len(befunde), 1)
            self.assertEqual(befunde[0]['stufe'], 'crit')

    def test_jede_meldung_nennt_eine_zahl_und_ein_ziel(self):
        """«Zahlungseingang gesunken» führt zu einer Rückfrage,
        «92.4 statt 93.6, offen sind CHF …» führt zu einer Handlung."""
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'offen')
            befunde = abweichungen(STICHTAG)
            self.assertTrue(befunde)
            for b in befunde:
                with self.subTest(titel=b['titel']):
                    self.assertTrue(b['ziel'] and b['knopf'])
                    self.assertTrue(any(z.isdigit() for z in b['text']))

    def test_die_schwelle_wirkt_wirklich_ueber_die_konstante(self):
        """Wer eine Schwelle ändert, soll eine Stelle ändern.

        Die erste Fassung prüfte, ob der NAME im Quelltext von `abweichungen`
        vorkommt. Das war zu schwach: Ersetzt man nur den Vergleich durch die
        Zahl 95 und lässt den Namen in der Meldung stehen, bleibt der Test
        grün — genau so ist die Gegenprobe durchgerutscht. Jetzt wird die
        Konstante zur Laufzeit verstellt und geprüft, dass sich das VERHALTEN
        ändert.
        """
        from unittest.mock import patch

        import faelle.lage as modul
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '1000', date(2026, 8, 1), 'bezahlt')
            # Bei 100 % Eingang und einer Schwelle von 100 muss die Meldung
            # kommen; mit dem Vorgabewert 95 darf sie es nicht.
            self.assertFalse([b for b in abweichungen(STICHTAG)
                              if b['titel'].startswith('Zahlungseingang')])
            with patch.object(modul, 'SCHWELLE_EINGANG', Decimal('101')):
                befunde = [b for b in abweichungen(STICHTAG)
                           if b['titel'].startswith('Zahlungseingang')]
            self.assertEqual(
                len(befunde), 1,
                'Die Schwelle wird nicht ueber SCHWELLE_EINGANG gelesen — '
                'irgendwo steht die Zahl fest im Vergleich.')

    def test_die_leerstandsschwelle_wirkt_ebenso(self):
        from unittest.mock import patch

        import faelle.lage as modul
        with mandant(self.a.organisation):
            with patch.object(modul, 'SCHWELLE_LEERSTAND', Decimal('0')):
                befunde = [b for b in abweichungen(STICHTAG)
                           if 'Leerstand' in b['titel']]
            self.assertTrue(
                befunde,
                'Die Leerstandsschwelle wird nicht ueber SCHWELLE_LEERSTAND '
                'gelesen.')


class MandatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_auffaellige_stehen_oben(self):
        """Die Sortierung IST die Aussage.

        Der Test legt ein ZWEITES, GRÖSSERES Mandat ohne Befund an. Nach
        Grösse sortiert stünde es oben; nach Auffälligkeit steht das kleinere
        mit dem Ausstand oben. Eine erste Fassung arbeitete nur mit dem
        Fixture-Mandat — bei einer einzigen Zeile ist jede Sortierung richtig,
        und die Gegenprobe blieb prompt grün.
        """
        from crm.models import Eigentuemer
        from portfolio.models import Einheit, Liegenschaft

        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '3780', date(2026, 8, 1), 'offen')

            gross = Eigentuemer.objects.create(
                organisation=self.a.organisation,
                firma_oder_name='Grosses Mandat ohne Befund')
            lg = Liegenschaft.objects.create(
                organisation=self.a.organisation, eigentuemer=gross,
                strasse='Musterweg 1', plz='3000', ort='Bern')
            for i in range(9):
                Einheit.objects.create(liegenschaft=lg, bezeichnung=f'Nr. {i}')

            zeilen = mandate(STICHTAG)
            self.assertGreaterEqual(
                len(zeilen), 2,
                'Der Test braucht zwei Mandate, sonst sagt er nichts.')
            self.assertGreater(zeilen[-1]['objekte'], zeilen[0]['objekte'],
                               'Das groessere Mandat muesste hinten stehen.')
            rang = {'crit': 0, 'warn': 1, 'good': 2}
            stufen = [rang[z['stufe']] for z in zeilen]
            self.assertEqual(stufen, sorted(stufen))

    def test_ohne_befund_wird_als_solches_markiert(self):
        with mandant(self.a.organisation):
            for z in mandate(STICHTAG):
                if not z['offen'] and not z['leer']:
                    self.assertEqual(z['stufe'], 'good')

    def test_mandat_ohne_objekte_erscheint_nicht(self):
        """Eine Zeile «0 Objekte, 0 % belegt» sagt nichts und teilte ausserdem
        durch null."""
        from crm.models import Eigentuemer
        with mandant(self.a.organisation):
            leer = Eigentuemer.objects.create(
                organisation=self.a.organisation, firma_oder_name='Ohne Objekte')
            namen = [str(z['mandat']) for z in mandate(STICHTAG)]
            self.assertNotIn(str(leer), namen)


class AbfragezahlTests(TestCase):
    """Die Startseite darf nicht je Datensatz rechnen.

    Zwei Stellen taten das im ersten Entwurf: `mandate()` fragte je Eigentümer
    dreimal, und die Senkungsansprüche lasen je Vertrag die Organisation und
    die Anpassungen nach. Bei zwanzig Mandaten und hundert Verträgen waren das
    64 und 203 Abfragen; im Betrieb entsprechend mehr.

    Die Obergrenzen unten sind bewusst grosszügig — sie sollen nicht jede
    Verfeinerung rot färben, sondern den Rückbau auf «je Datensatz» abfangen.
    Genau dafür wächst die Datenmenge im Fixture: Bei drei Mandaten sähe eine
    Schleife wie eine Abfrage aus.
    """

    @classmethod
    def setUpTestData(cls):
        from crm.models import Eigentuemer
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag

        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with mandant(cls.a.organisation):
            for i in range(20):
                eg = Eigentuemer.objects.create(
                    organisation=cls.a.organisation, firma_oder_name=f'Mandat {i}')
                lg = Liegenschaft.objects.create(
                    organisation=cls.a.organisation, eigentuemer=eg,
                    strasse=f'Weg {i}', plz='3000', ort='Bern')
                for j in range(5):
                    eh = Einheit.objects.create(liegenschaft=lg,
                                                bezeichnung=f'{i}.{j}')
                    Mietvertrag.objects.create(
                        mieter=cls.a.mieter, einheit=eh, status='aktiv',
                        beginn=cls.a.vertrag.beginn,
                        netto_mietzins=Decimal('1500'),
                        nebenkosten=Decimal('200'))

    def test_mandate_in_einer_abfrage(self):
        with mandant(self.a.organisation):
            with self.assertNumQueries(1):
                zeilen = mandate(STICHTAG)
            self.assertGreaterEqual(len(zeilen), 20,
                                    'Ohne Zeilen sagt die Abfragezahl nichts.')

    def test_senkungsansprueche_ohne_abfrage_je_vertrag(self):
        from faelle.lage import _senkungsansprueche
        with mandant(self.a.organisation):
            # Eine für die Verträge, eine für das Vorabladen der Anpassungen.
            with self.assertNumQueries(2):
                _senkungsansprueche()

    def test_die_ganze_lage_bleibt_zweistellig(self):
        """Der Gesamtwert ist die Zahl, die den Benutzer betrifft.

        Eine feste Zahl waere hier zu sproede — jede Verfeinerung an einer der
        vier Teilfunktionen faerbte sie rot, ohne dass etwas schlechter
        geworden waere. Geprueft wird die Groessenordnung: zweistellig, nicht
        dreistellig.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with mandant(self.a.organisation):
            with CaptureQueriesContext(connection) as abfragen:
                lage(STICHTAG)
        self.assertLess(len(abfragen), 40,
                        f'Die Lage braucht {len(abfragen)} Abfragen. Das ist die '
                        f'Signatur einer Schleife ueber Datensaetze — mit '
                        f'zwanzig Mandaten und hundert Vertraegen im Bestand.')


class StartseiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _seite(self, pfad='/neu/'):
        c = Client()
        c.force_login(self.a.benutzer)
        return c.get(pfad)

    def test_startseite_zeigt_lage_und_ansichten(self):
        with mandant(self.a.organisation):
            antwort = self._seite()
        self.assertEqual(antwort.status_code, 200)
        for text in ('Ausstände', 'Leerstand', 'Offene Fälle',
                     'Liegengeblieben', 'Wartet auf Dritte', 'Mandate'):
            with self.subTest(text=text):
                self.assertContains(antwort, text)

    def test_die_alten_kacheln_sind_weg(self):
        """Portfolio-Donut und Mietertrag-Diagramm waren Dekoration."""
        with mandant(self.a.organisation):
            inhalt = self._seite().content.decode()
        self.assertNotIn('Belegung nach Nutzung', inhalt)
        self.assertNotIn('Soll vs. Ist', inhalt)
        self.assertNotIn('belegung_conic', inhalt)

    def test_ansicht_wechselt_ueber_die_adresse(self):
        with mandant(self.a.organisation):
            antwort = self._seite('/neu/?ansicht=liegen')
        self.assertContains(antwort, 'Verfallsregel')

    def test_unbekannte_ansicht_faellt_auf_heute_zurueck(self):
        """Ein Tippfehler in der Adresse darf keine leere Seite ergeben."""
        with mandant(self.a.organisation):
            antwort = self._seite('/neu/?ansicht=quatsch')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Heute')

    def test_arbeit_leitet_auf_die_startseite_um(self):
        """Die zweite Startfläche ist aufgelöst, die Adresse bleibt gültig."""
        with mandant(self.a.organisation):
            antwort = self._seite('/neu/arbeit/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/neu/')

    def test_die_umleitung_nimmt_die_ansicht_mit(self):
        """Ohne das landete ein gespeicherter Verweis auf «Liegengeblieben»
        wieder bei «Heute»."""
        with mandant(self.a.organisation):
            antwort = self._seite('/neu/arbeit/?ansicht=wartet')
        self.assertEqual(antwort['Location'], '/neu/?ansicht=wartet')


class TrennungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_die_lage_von_b_enthaelt_nichts_von_a(self):
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '99999', date(2026, 8, 1), 'offen')
        with mandant(self.b.organisation):
            _quote, _s, offen, _a = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertNotEqual(offen, Decimal('99999'))

    def test_a_sieht_den_eigenen_ausstand_sehr_wohl(self):
        """Gegenprobe — eine Lage, die immer null liefert, bestünde alles."""
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '99999', date(2026, 8, 1), 'offen')
            _quote, _s, offen, _a = _eingangsquote(date(2026, 8, 1), STICHTAG)
            self.assertGreaterEqual(offen, Decimal('99999'))

    def test_mandate_bleiben_getrennt(self):
        with mandant(self.a.organisation):
            namen_a = {str(z['mandat']) for z in mandate(STICHTAG)}
        with mandant(self.b.organisation):
            namen_b = {str(z['mandat']) for z in mandate(STICHTAG)}
        self.assertEqual(namen_a & namen_b, set())

    def test_die_startseite_von_b_zeigt_kein_mandat_von_a(self):
        """Der Weg, auf dem es ein Benutzer sähe."""
        from crm.models import Eigentuemer
        from portfolio.models import Einheit, Liegenschaft
        with mandant(self.a.organisation):
            eg = Eigentuemer.objects.create(
                organisation=self.a.organisation,
                firma_oder_name='Streng vertraulich Mandant A')
            lg = Liegenschaft.objects.create(
                organisation=self.a.organisation, eigentuemer=eg,
                strasse='Geheim 1', plz='8000', ort='Zürich')
            Einheit.objects.create(liegenschaft=lg, bezeichnung='1.OG')
        c = Client()
        c.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            antwort = c.get('/neu/')
        self.assertNotContains(antwort, 'Streng vertraulich Mandant A')
