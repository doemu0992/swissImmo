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
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

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


class AbschnitteErreichenDieSeiteTests(TestCase):
    """Die Abschnitte werden nicht nur berechnet, sondern auch gezeigt.

    DIESE LÜCKE IST DER ANLASS DER GANZEN ETAPPE. Bis 4b.13 berechnete der
    Arbeitsvorrat `av_termine`, `av_freigaben`, `av_vertretung` und
    `av_liegezeit` — und auf `/neu/` wurde **keiner** davon angezeigt. Gebaut
    in 4b.7 und 4b.8, auf der meistbesuchten Seite nie angekommen.

    Aufgefallen ist es erst beim Vergleich zweier Startflächen, nicht durch
    einen Test: Die Tests prüften die Funktionen, und die waren grün.

    Beim Umbau wäre es beinahe wieder passiert — eine Gegenprobe, die den
    Sammler aus dem Kontext nimmt, blieb grün. Deshalb dieser Test: Er
    schreibt Daten und prüft die **gerenderte Seite**.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _seite(self):
        c = Client()
        c.force_login(self.a.benutzer)
        return c.get('/neu/').content.decode()

    def test_termin_erscheint_auf_der_startseite(self):
        from datetime import timedelta

        from django.utils import timezone

        from faelle.termin_models import Termin
        with mandant(self.a.organisation):
            Termin.objects.create(
                titel='Eigentuemergespraech Blattner', art=Termin.GESPRAECH,
                beginn=timezone.now() + timedelta(days=2))
            inhalt = self._seite()
        self.assertIn('Termine', inhalt)
        self.assertIn('Eigentuemergespraech Blattner', inhalt,
                      'Der Termin wird berechnet, aber nicht angezeigt.')

    def test_freigabe_erscheint_auf_der_startseite(self):
        from datetime import timedelta

        from django.utils import timezone

        from finance.models import KreditorenRechnung
        with mandant(self.a.organisation):
            KreditorenRechnung.objects.create(
                liegenschaft=self.a.liegenschaft, lieferant='Sanitaer Widmer AG',
                status='neu', betrag=880,
                datum=timezone.localdate() - timedelta(days=3))
            inhalt = self._seite()
        self.assertIn('Wartet auf Freigabe', inhalt)
        self.assertIn('Sanitaer Widmer AG', inhalt,
                      'Die Freigabe wird berechnet, aber nicht angezeigt.')

    def test_vertretung_erscheint_auf_der_startseite(self):
        from datetime import timedelta

        from django.utils import timezone

        from faelle.termin_models import Abwesenheit
        with mandant(self.a.organisation):
            heute = timezone.localdate()
            Abwesenheit.objects.create(
                benutzer=self.a.benutzer, von=heute - timedelta(days=1),
                bis=heute + timedelta(days=5), grund=Abwesenheit.FERIEN)
            inhalt = self._seite()
        self.assertIn('Vertretung', inhalt,
                      'Die Abwesenheit wird berechnet, aber nicht angezeigt.')
        self.assertIn('ohne Vertretung', inhalt,
                      'Eine ungedeckte Abwesenheit muss als solche auffallen.')

    def test_der_zulauf_erscheint_auf_der_startseite(self):
        from faelle.zulauf_models import Eingang
        with mandant(self.a.organisation):
            Eingang.objects.create(quelle=Eingang.MAIL,
                                   betreff='Heizung im Bad wieder kalt')
            inhalt = self._seite()
        self.assertIn('Heizung im Bad wieder kalt', inhalt,
                      'Der Zulauf wird berechnet, aber nicht angezeigt.')


class VergleichswerteTests(TestCase):
    """«Kennzahlen nur mit Vergleich» — Konzept v7.

    Bis E2.58 hatten zwei der vier Kacheln `delta: None`: Ausstände und offene
    Fälle. «CHF 23'140» ohne Bezugspunkt ist eine Zahl, keine Aussage.

    WARUM DIE AUSSTÄNDE IN POSITIONEN VERGLICHEN WERDEN, NICHT IN FRANKEN

    Eine einzelne grosse Rechnung lässt den Betrag springen, ohne dass sich an
    der Lage etwas geändert hätte. Zwei Positionen mehr heisst: zwei Mieter
    mehr, die nicht bezahlt haben.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _kachel(self, schluessel, stichtag=None, org=None):
        with mandant(org or self.a.organisation):
            for k in streifen(stichtag or timezone.localdate()):
                if k['schluessel'] == schluessel:
                    return k
        self.fail(f'Kachel «{schluessel}» fehlt.')

    def _fall(self, org, betreff, tage_zurueck=0, **felder):
        from faelle.models import Fall, Fallart

        with mandant(org):
            art = Fallart.objects.filter(schluessel='mieterwechsel').first()
            f = Fall(organisation=org, fallart=art, betreff=betreff, **felder)
            f.save()
            if tage_zurueck:
                Fall.objects.filter(pk=f.pk).update(
                    eroeffnet_am=timezone.now() - timedelta(days=tage_zurueck))
        return f

    def test_jede_kachel_kann_einen_vergleich_tragen(self):
        """Keine darf `delta` gar nicht erst kennen.

        `None` heisst «kein Vergleichswert vorhanden» und ist erlaubt — der
        Schlüssel zu fehlen heisst «hier war nie einer vorgesehen», und das
        widerspricht v7.
        """
        for schluessel in ('eingang', 'ausstaende', 'leerstand', 'faelle'):
            with self.subTest(kachel=schluessel):
                self.assertIn('delta', self._kachel(schluessel))

    def test_die_richtung_ist_bei_jedem_vergleich_benannt(self):
        """Ohne sie weiss die Oberfläche nicht, ob mehr gut oder schlecht ist.

        Bei den Ausständen ist weniger besser, beim Zahlungseingang mehr. Ein
        Pfeil nach oben in Grün wäre bei den Ausständen genau falsch.
        """
        for schluessel in ('eingang', 'ausstaende', 'leerstand', 'faelle'):
            with self.subTest(kachel=schluessel):
                k = self._kachel(schluessel)
                self.assertIn(
                    'delta_gut_wenn', k,
                    f'«{schluessel}» sagt nicht, in welche Richtung gut ist.')
                # `hoch` oder `runter` — die Vorlage prüft NUR auf `runter`
                # (`dashboard.html:45/46`). Jeder andere Wert fiele durch beide
                # Zweige und färbte den Pfeil falsch, ohne zu scheitern.
                #
                # Im Bestand stand das nie falsch: Vor E2.58 gab es genau zwei
                # `delta_gut_wenn`, `hoch` und `runter`, beide richtig. Das
                # Skript zu dieser Etappe meldete «dreimal `tief`» — nachgesehen
                # in `git log -S`, im ganzen Verlauf null Treffer. Der Wächter
                # bleibt trotzdem: Er kostet nichts und fängt den Tippfehler ab,
                # der beim nächsten Zusatz naheliegt.
                self.assertIn(k['delta_gut_wenn'], ('hoch', 'runter'))

    def test_offene_faelle_vergleichen_gegen_den_vormonat(self):
        # Ein Fall von vor zwei Monaten, noch offen: zählt damals und heute.
        self._fall(self.a.organisation, 'Alt', tage_zurueck=60)

        # RELATIV MESSEN, NICHT ABSOLUT.
        #
        # Ein erster Entwurf erwartete `delta == 1`. Die Fixture bringt aber
        # selbst einen heute eröffneten Fall mit — es sind zwei. Derselbe
        # Fehler wie bei den festen Positionen im Finanzkorb (E2.30): ein Test,
        # der die eigene Ausgangslage nicht mitzählt, bricht, sobald jemand die
        # Fixture ergänzt.
        vorher = self._kachel('faelle')['delta']
        self.assertIsNotNone(vorher, 'Ohne Vergleichswert misst der Rest nichts.')

        self._fall(self.a.organisation, 'Neu')

        self.assertEqual(
            self._kachel('faelle')['delta'], vorher + 1,
            'Ein neuer Fall erhöht den Vergleich nicht — dann steht dort eine '
            'Zahl ohne Bezug zum Vormonat.')

    def test_ein_alter_fall_zaehlt_auf_beiden_seiten_und_veraendert_nichts(self):
        """Die Gegenprobe zum Test darüber.

        Ein Fall von vor zwei Monaten war damals offen UND ist es heute. Er
        gehört in beide Zahlen, hebt sich also auf. Zählte die historische
        Abfrage ihn nicht mit — etwa weil sie auf `eroeffnet_am__gte` steht
        oder die Zeitgrenze falsch liegt —, spränge das Delta bei jedem
        Altbestand nach oben, und die Kachel meldete Wachstum, wo nichts
        wächst.
        """
        vorher = self._kachel('faelle')['delta']
        self._fall(self.a.organisation, 'Altlast', tage_zurueck=60)
        self.assertEqual(
            self._kachel('faelle')['delta'], vorher,
            'Ein seit zwei Monaten offener Fall verändert den Vormonatsvergleich '
            '— dann zählt die historische Abfrage ihn nur auf einer Seite.')

    def test_ein_diesen_monat_erledigter_altfall_senkt_den_vergleich(self):
        """Er zählte damals mit und heute nicht mehr — genau das ist Fortschritt.

        Die historische Zahl richtet sich nach dem damaligen Zustand, NICHT nach
        dem heutigen Status. Nähme sie den Status von heute, verschwände der
        Fall aus beiden Zahlen, und das Delta bliebe stehen: Erledigte Arbeit
        wäre auf der Startseite unsichtbar.
        """
        from faelle.models import Fall

        vorher = self._kachel('faelle')['delta']
        f = self._fall(self.a.organisation, 'Erledigt', tage_zurueck=60)
        with mandant(self.a.organisation):
            Fall.objects.filter(pk=f.pk).update(
                status=Fall.ABGESCHLOSSEN, abgeschlossen_am=timezone.now())
        self.assertEqual(
            self._kachel('faelle')['delta'], vorher - 1,
            'Ein diesen Monat erledigter Altfall senkt den Vergleich nicht — '
            'dann rechnet die historische Zahl mit dem heutigen Status.')

    def test_ein_laengst_erledigter_fall_zaehlt_auf_KEINER_seite(self):
        """HIER wird `abgeschlossen_am` wirklich gebraucht — und nur hier.

        Der Test darüber blieb bei der Gegenprobe GRÜN, als ich die
        `abgeschlossen_am`-Bedingung entfernte: Er schliesst den Fall HEUTE ab,
        also nach der Monatsgrenze, wo die Bedingung ohnehin nicht greift. Das
        Delta bewegte sich dort, weil die heutige Zahl sinkt — nicht, weil die
        historische richtig rechnet. Ein Test, dessen Fehlerfall sich nicht
        herstellen lässt, beweist nichts.

        Der Fall, der die Bedingung braucht, liegt ganz im VORMONAT: vor drei
        Monaten eröffnet, vor eineinhalb abgeschlossen. Er gehört in keine der
        beiden Zahlen. Ohne `abgeschlossen_am` zählte er im Vormonat mit, und
        die Startseite meldete einen Rückgang, den es nicht gab — jeden Monat
        aufs Neue, für jeden je erledigten Fall.
        """
        from faelle.models import Fall

        vorher = self._kachel('faelle')['delta']
        f = self._fall(self.a.organisation, 'Längst erledigt', tage_zurueck=90)
        with mandant(self.a.organisation):
            Fall.objects.filter(pk=f.pk).update(
                status=Fall.ABGESCHLOSSEN,
                abgeschlossen_am=timezone.now() - timedelta(days=45))
        self.assertEqual(
            self._kachel('faelle')['delta'], vorher,
            'Ein vor eineinhalb Monaten abgeschlossener Fall bewegt den '
            'Vergleich — dann wird `abgeschlossen_am` nicht gelesen und er '
            'zählt im Vormonat als offen.')

    def test_der_vormonatsstand_endet_wirklich_am_monatsersten(self):
        """Die Zeitgrenze, an der der erste Entwurf danebenlag.

        `eroeffnet_am` ist ein `DateTimeField` und `USE_TZ` ist an. Gegen
        `vor_letzter` (ein `date`) zu filtern legt die Grenze auf MITTERNACHT
        des letzten Vormonatstags — der ganze 31. fällt heraus, und Django
        warnt bei jedem Seitenaufruf über die naive Zeitangabe.

        Ein Fall vom letzten Tag des Vormonats, mittags, gehört auf beide
        Seiten und darf das Delta nicht bewegen. Mit der falschen Grenze zählt
        er nur heute — Delta um eins zu hoch.
        """
        heute = timezone.localdate()
        letzter_vormonat = heute.replace(day=1) - timedelta(days=1)
        vorher = self._kachel('faelle')['delta']

        from faelle.models import Fall
        f = self._fall(self.a.organisation, 'Letzter Vormonatstag')
        mittags = timezone.make_aware(
            timezone.datetime.combine(letzter_vormonat,
                                      timezone.datetime.min.time())
            + timedelta(hours=12))
        with mandant(self.a.organisation):
            Fall.objects.filter(pk=f.pk).update(eroeffnet_am=mittags)

        self.assertEqual(
            self._kachel('faelle')['delta'], vorher,
            f'Ein am {letzter_vormonat} um 12:00 eröffneter Fall bewegt den '
            'Vergleich — dann endet der Vormonat um Mitternacht statt am '
            'Monatsersten.')

    def test_faelle_fremder_organisationen_zaehlen_im_vergleich_nicht_mit(self):
        """Die Mandantengrenze gilt auch für die historische Zahl.

        Der neue Vergleich ist eine ZWEITE Abfrage auf `Fall` — die erste ist
        seit E2.29 mandantengetrennt, die neue muss es eigenständig sein. Ein
        `alle_organisationen` an dieser Stelle liesse die Kachel von A mit den
        Fällen von B rechnen: kein sichtbares Leck, aber eine Zahl, die den
        Bestand eines Wettbewerbers verrät.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        vorher = self._kachel('faelle')['delta']
        self._fall(b.organisation, 'Fremd, alt', tage_zurueck=60)
        self._fall(b.organisation, 'Fremd, neu')
        self.assertEqual(
            self._kachel('faelle')['delta'], vorher,
            'Die Fälle von B verändern den Vergleich von A — dann rechnet die '
            'historische Abfrage über die Mandantengrenze hinweg.')

    def test_ein_abgebrochener_fall_zaehlt_auf_KEINER_seite(self):
        """Sonst vergleicht die Kachel zwei verschieden gerechnete Zahlen.

        Die heutige Zahl schliesst `ABGEBROCHEN` seit E2.29 aus. Täte die
        historische es nicht, zählte ein abgebrochener Altfall nur im Vormonat
        — und ein Abbruch sähe aus wie ein erledigter Fall, obwohl niemand
        etwas erledigt hat.
        """
        from faelle.models import Fall

        vorher = self._kachel('faelle')['delta']
        f = self._fall(self.a.organisation, 'Abgebrochen', tage_zurueck=60)
        with mandant(self.a.organisation):
            Fall.objects.filter(pk=f.pk).update(status=Fall.ABGEBROCHEN)
        self.assertEqual(
            self._kachel('faelle')['delta'], vorher,
            'Ein abgebrochener Altfall bewegt den Vergleich — dann zählt die '
            'historische Abfrage ihn mit und die heutige nicht.')

    def test_ausstaende_vergleichen_positionen_und_nicht_franken(self):
        """Die zweite Kachel, die bis E2.58 `delta: None` trug.

        Verglichen wird die ANZAHL: Eine einzelne grosse Rechnung lässt den
        Betrag springen, ohne dass sich an der Lage etwas geändert hätte. Der
        Test setzt deshalb im Vormonat EINE kleine offene Position und im
        laufenden Monat ZWEI grosse — der Franken-Betrag verzehnfacht sich, das
        Delta ist +1.
        """
        with mandant(self.a.organisation):
            _rechnung(self.a.vertrag, '100', date(2026, 7, 5), 'offen')
            _rechnung(self.a.vertrag, '5000', date(2026, 8, 1), 'offen')
            _rechnung(self.a.vertrag, '5000', date(2026, 8, 2), 'offen')

        k = self._kachel('ausstaende', stichtag=STICHTAG)
        self.assertEqual(
            k['delta'], 1,
            'Eine Position mehr als im Vormonat — steht dort `None`, ist die '
            'Kachel eine Zahl ohne Bezugspunkt; steht dort 9900, wird in '
            'Franken verglichen.')
        self.assertEqual(k['delta_einheit'], 'Position')

    def test_ohne_vormonat_bleibt_der_vergleich_leer(self):
        """`None`, nicht `0`.

        Eine Null hiesse «unverändert» und wäre eine Aussage. «Kein
        Vormonatswert» ist eine andere — dieselbe Unterscheidung wie beim
        Stundensatz und bei `Geraet.neuwert`.

        DIE LAGE WIRD HERGESTELLT, NICHT ABGEWARTET. Ein erster Entwurf prüfte
        `if k['delta'] is None:` und war grün, sobald sie nicht eintrat — ein
        Test ohne Zusicherung. Ein Stichtag im Jahr 2099 hat garantiert keinen
        Vormonat mit Sollstellung, und damit ist der Fall gebaut statt erhofft.
        """
        for schluessel in ('eingang', 'ausstaende'):
            with self.subTest(kachel=schluessel):
                k = self._kachel(schluessel, stichtag=date(2099, 2, 15))
                self.assertIsNone(
                    k['delta'],
                    f'«{schluessel}» meldet einen Vergleich gegen einen Monat, '
                    'in dem nichts fällig war. Auf einer frischen Installation '
                    'stünde dort ein Anstieg gegen nichts.')
        self.assertIn('kein Vormonatswert',
                      self._kachel('eingang', stichtag=date(2099, 2, 15))['fuss'])

    def test_die_startseite_zeigt_den_pfeil_mit_einheit_und_richtung(self):
        """Von der Zahl bis zum Pixel — die Vorlage wurde mitgeändert.

        Drei Dinge, die nur hier zusammenkommen:

        · Die EINHEIT. Ohne sie steht dort «▲ 3» und niemand weiss, wovon.
        · Die ZAHLFORM. `floatformat:1` erzwang «▲ 3,0 Fälle»; eine Fallzahl
          ist ganz. Ohne Argument zeigt Django die Stelle nur, wenn es eine gibt.
        · Die RICHTUNG, und zwar als FARBE. Die Klassen heissen `hoch`/`runter`,
          meinen aber die BEWERTUNG, nicht die Pfeilrichtung: `_schicht.html:898`
          setzt `.fw-trend.hoch` auf `--ds-crit` (rot) und `.fw-trend.runter`
          auf `--ds-good` (grün). Ein wachsender Fallvorrat ist schlecht, also
          rot, also `hoch` — obwohl der Name das Gegenteil nahelegt.

          Ich habe die Namen beim Schreiben dieses Tests als Richtung gelesen
          und `runter` erwartet. Deshalb prüft er unten nicht nur die Klasse,
          sondern hält daneben fest, welche Farbe sie trägt.

        ZAHL RELATIV, NICHT ABSOLUT: Die Fixture bringt selbst einen heute
        eröffneten Fall mit, das Delta startet also bei 1 und nicht bei 0. Der
        erste Entwurf erwartete «▲ 3 Fälle» und mass «▲ 4» — genau der Fehler,
        den diese Etappe im Nachbartest korrigiert hat.
        """
        vorher = self._kachel('faelle')['delta']
        for i in range(3):
            self._fall(self.a.organisation, f'Neu {i}')
        erwartet = vorher + 3

        with mandant(self.a.organisation):
            c = Client()
            c.force_login(self.a.benutzer)
            inhalt = c.get('/neu/').content.decode()

        self.assertIn(f'▲ {erwartet} Fälle</span>', inhalt,
                      f'Kein «▲ {erwartet} Fälle» auf der Startseite — entweder '
                      'fehlt die Einheit, oder `floatformat:1` macht «,0» daraus.')
        self.assertNotIn(f'{erwartet},0 Fälle', inhalt)
        self.assertIn(f'class="fw-trend hoch">▲ {erwartet} Fälle', inhalt,
                      'Der Pfeil trägt nicht die kritische Klasse — ein '
                      'wachsender Fallvorrat stünde damit in Grün.')
        # Und der Beleg, dass «hoch» hier wirklich rot bedeutet. Ohne ihn prüft
        # die Zeile darüber nur einen Namen. Die Farbe steht nicht in der Seite,
        # sondern in der gebauten Schicht (`schicht_bauen`), die sie verlinkt.
        from pathlib import Path

        from django.conf import settings

        schicht = Path(settings.BASE_DIR) / 'static' / 'css' / 'schicht.css'
        self.assertIn('.fw-trend.hoch{color:var(--ds-crit)}',
                      schicht.read_text(encoding='utf-8').replace('\n', '').replace(' ', ''),
                      '`fw-trend hoch` ist nicht mehr die kritische Farbe — dann '
                      'sagt die Klasse oben das Gegenteil dessen, was sie malt.')

    def test_die_einheit_steht_in_der_richtigen_zahlform(self):
        """«▲ 1 Fälle» — und ±1 ist der häufigste Wert überhaupt."""
        from faelle.lage import _einheit

        self.assertEqual(_einheit(1, 'Fall', 'Fälle'), 'Fall')
        self.assertEqual(_einheit(-1, 'Fall', 'Fälle'), 'Fall')
        self.assertEqual(_einheit(2, 'Fall', 'Fälle'), 'Fälle')
        self.assertEqual(_einheit(0, 'Fall', 'Fälle'), 'Fälle')
        self.assertEqual(_einheit(None, 'Fall', 'Fälle'), 'Fälle')

    def test_die_startseite_warnt_nicht_ueber_naive_zeitangaben(self):
        """Der Nebenbefund, der den Zeitgrenzen-Fehler sichtbar gemacht hat.

        `DateTimeField … received a naive datetime while time zone support is
        active` ist eine `RuntimeWarning` und bricht nichts — sie stand nur bei
        jedem Aufruf der meistbesuchten Seite im Log. Wer eine Warnung dauerhaft
        im Log stehen lässt, liest bald keine mehr.
        """
        import warnings

        with warnings.catch_warnings(record=True) as gesammelt:
            warnings.simplefilter('always')
            self._kachel('faelle')
        naiv = [str(w.message) for w in gesammelt
                if 'naive datetime' in str(w.message)]
        self.assertEqual(
            naiv, [],
            'Die Lage vergleicht ein `DateTimeField` gegen ein `date`.')


class ErsterTagTests(TestCase):
    """Was eine taufrische Installation zeigt — und was nicht.

    DIE FRAGE AUS DER GEGENPRÜFUNG ZU E2.58

    Die Fall-Kachel rechnet auch am ersten Tag `delta = offen - 0`, während die
    Ausstände dort «kein Vormonatswert» sagen. Ist das zu forsch?

    NEIN — UND DER UNTERSCHIED IST DERSELBE WIE ÜBERALL SONST.

    Eine Fallzahl von null ist eine GEMESSENE Zahl: Am ersten Tag gab es keine
    offenen Fälle. Eine Sollstellung von null im Vormonat ist eine FEHLENDE
    MESSUNG: Es war nichts fällig, also gibt es nichts zu vergleichen.

    Wie bei `Geraet.neuwert`: `None` heisst «nicht erfasst», `0` heisst «kostet
    nichts». Zwei verschiedene Aussagen.
    """

    def _neue_organisation(self, name):
        from crm.models import Organisation
        return Organisation.objects.create(
            firma=name, strasse='X 1', plz='8000', ort='Zürich')

    def test_leere_installation_zeigt_keinen_pfeil(self):
        """`delta = 0`, und die Vorlage blendet das aus.

        Am ersten Tag steht also nichts Falsches da — auch ohne Schranke.
        """
        org = self._neue_organisation('Neu AG')
        with mandant(org):
            kacheln = {k['schluessel']: k for k in streifen()}
        self.assertEqual(kacheln['faelle']['delta'], 0)
        self.assertIsNone(
            kacheln['ausstaende']['delta'],
            'Ohne fällige Sollstellung im Vormonat darf kein Vergleich '
            'entstehen — eine Null wäre eine erfundene Vergleichsbasis.')

    def test_die_vorlage_blendet_ein_delta_von_null_wirklich_aus(self):
        """Die zweite Hälfte der Antwort — und sie steht nicht in `lage.py`.

        Der Test darüber zeigt `delta == 0`. Dass daraus KEIN Pfeil wird, ist
        eine Eigenschaft der Vorlage (`{% if k.delta %}`, und `0` ist falsch).
        Ohne diese Prüfung ruht die ganze Begründung «am ersten Tag steht
        nichts Falsches da» auf einer Annahme über Django-Wahrheitswerte.
        """
        from django.template import Context, Template

        gerendert = Template(
            '{% if k.delta %}PFEIL{% endif %}'
        ).render(Context({'k': {'delta': 0}}))
        self.assertEqual(gerendert, '',
                         'Ein Delta von 0 erzeugt einen Pfeil — dann meldet '
                         'die frische Installation eine Veränderung gegen '
                         'nichts.')

    def test_der_erste_fall_ergibt_einen_echten_vergleich(self):
        """«▲ 1 Fall» ist wahr: vorher null, jetzt einer."""
        from faelle.models import Fall, Fallart

        org = self._neue_organisation('Neu 2 AG')
        with mandant(org):
            art = Fallart.objects.create(
                organisation=org, schluessel='e', bezeichnung='E')
            Fall(organisation=org, fallart=art, akte=None, betreff='Erster').save()
            kacheln = {k['schluessel']: k for k in streifen()}
        self.assertEqual(kacheln['faelle']['delta'], 1)
        self.assertEqual(kacheln['faelle']['delta_einheit'], 'Fall')


class KopfzeileTests(TestCase):
    """Kalenderwoche und Vertretungshinweis — Konzept v7.

    Der Prototyp zeigt: «Freitag, 21. August 2026 · KW 34 · Vertretung für
    Lea F. bis 29.08.»

    DIE KALENDERWOCHE ist in der Schweizer Verwaltung die übliche Zeitangabe:
    Termine, Handwerker und Läufe werden in KW vereinbart, nicht im Datum. Sie
    stand bis E2.59 nirgends.

    DER VERTRETUNGSHINWEIS sagt, dass gerade FREMDE Arbeit mitläuft. Ohne ihn
    wundert man sich über Fälle, die einem nicht gehören.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _seite(self, benutzer=None):
        c = Client()
        c.force_login(benutzer or self.a.benutzer)
        return c.get('/neu/')

    def _abwesend(self, org, username, vertreter, von, bis):
        from django.contrib.auth import get_user_model

        from faelle.termin_models import Abwesenheit

        with mandant(org):
            wer = get_user_model().objects.create_user(
                username=username, password='x', first_name='Lea')
            Abwesenheit.objects.create(
                organisation=org, benutzer=wer, von=von, bis=bis,
                vertreten_durch=vertreter)
        return wer

    def test_die_kalenderwoche_steht_im_kopf(self):
        """Nicht nur «KW» irgendwo — die richtige Zahl an der richtigen Stelle.

        `assertIn('KW', …)` wäre wertlos: Zwei Buchstaben, die auf einer
        Verwaltungsseite überall vorkommen können. Geprüft wird der gerenderte
        Text mitsamt Nummer.
        """
        kw = timezone.localdate().isocalendar()[1]
        antwort = self._seite()
        self.assertEqual(antwort.context['kw'], kw)
        self.assertIn(f'KW&nbsp;{kw}', antwort.content.decode(),
                      'Die Kalenderwoche steht nicht in der Kopfzeile.')

    def test_ohne_vertretung_steht_dort_nichts(self):
        """Kein leerer Platzhalter, keine Null.

        Wer niemanden vertritt, soll auch nichts darüber lesen.
        """
        antwort = self._seite()
        self.assertEqual(antwort.context['vertretung_fuer'], [])
        self.assertNotIn('Vertretung für', antwort.content.decode())

    def test_wer_vertritt_sieht_es_im_kopf(self):
        heute = timezone.localdate()
        self._abwesend(self.a.organisation, 'lea-kopf', self.a.benutzer,
                       heute - timedelta(days=1), heute + timedelta(days=3))

        antwort = self._seite()
        self.assertEqual(len(antwort.context['vertretung_fuer']), 1)
        self.assertIn('Vertretung für Lea bis', antwort.content.decode())

    def test_wer_nicht_vertritt_sieht_fremde_abwesenheiten_nicht_im_kopf(self):
        """Die Gegenprobe: Der Hinweis hängt an `vertreten_durch`, nicht daran,
        dass überhaupt jemand weg ist.

        Ohne diesen Filter stünde bei JEDEM im Team «Vertretung für Lea» —
        und dann übernimmt niemand, weil alle es für den anderen halten.
        """
        heute = timezone.localdate()
        # Abwesend, aber von NIEMANDEM vertreten.
        self._abwesend(self.a.organisation, 'lea-ungedeckt', None,
                       heute - timedelta(days=1), heute + timedelta(days=3))

        antwort = self._seite()
        self.assertEqual(antwort.context['vertretung_fuer'], [])
        self.assertNotIn('Vertretung für', antwort.content.decode())

    def test_eine_fremde_abwesenheit_erscheint_nie_im_kopf(self):
        """Die Mandantengrenze — der Hinweis ist eine NEUE Abfrage.

        `_vertretung_fuer` fragt `Abwesenheit` eigenständig ab; der Bezug kommt
        allein vom `TenantManager`. Trägt eine fremde Organisation denselben
        Benutzer als Vertretung ein — bei geteilten Konten oder schlicht durch
        einen Importfehler —, dürfte im Kopf von A trotzdem nie ein Name aus B
        stehen. Ein Name ist hier bereits die Auskunft: Er verrät, wer bei der
        anderen Verwaltung arbeitet und wann diese Person Ferien hat.
        """
        from faelle.termin_models import Abwesenheit

        b = MandantenFixture('B', '3000', 'Bern')
        heute = timezone.localdate()
        # Angelegt im Kontext B, Vertretung ist der Benutzer von A.
        self._abwesend(b.organisation, 'lea-fremd', self.a.benutzer,
                       heute - timedelta(days=1), heute + timedelta(days=3))

        # Die Abwesenheit existiert wirklich — sonst prüfte der Test nichts.
        self.assertEqual(
            Abwesenheit.alle_organisationen.filter(
                vertreten_durch=self.a.benutzer).count(), 1,
            'Die fremde Abwesenheit wurde gar nicht angelegt.')

        antwort = self._seite()
        self.assertEqual(
            antwort.context['vertretung_fuer'], [],
            'Eine Abwesenheit aus einer fremden Organisation steht im Kopf von '
            'A — dann fragt `_vertretung_fuer` über die Mandantengrenze hinweg.')
        self.assertNotIn('Vertretung für', antwort.content.decode())

    def test_der_abschnitt_vertretung_zeigt_keine_fremden_abwesenheiten(self):
        """Die Mandantengrenze auch für den Abschnitt unter dem Kopf.

        Aufgefallen bei der Gegenprobe: Der `alle_organisationen`-Tausch in
        `arbeitsvorrat.vertretung()` blieb GRÜN — für den Abschnitt gab es
        keinen Isolationstest, obwohl er Namen und Ferienzeiten von Kolleginnen
        auflistet. Der Schutz war da (der `TenantManager`), der Nachweis nicht.

        Jetzt geprüft, weil E2.59 diese Funktion angefasst hat.

        GEMESSEN WIRD DIE ZUGEHÖRIGKEIT, NICHT DIE LEERE LISTE. Die Fixture
        legt für A selbst eine laufende Abwesenheit an — auf `[]` zu prüfen war
        von Anfang an falsch und scheiterte auch am unveränderten Bestand.
        Dieselbe Lehre wie beim Fallvergleich: ein Test, der die eigene
        Ausgangslage nicht mitzählt, misst die Fixture statt die Sache.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        heute = timezone.localdate()
        self._abwesend(b.organisation, 'lea-b-abschnitt', b.benutzer,
                       heute - timedelta(days=1), heute + timedelta(days=3))

        zeilen = self._seite().context['av_vertretung']
        self.assertTrue(zeilen, 'Ohne Zeilen sagt die Prüfung nichts.')
        fremd = [z['wer'] for z in zeilen
                 if z['abwesenheit'].organisation_id != self.a.organisation.id]
        self.assertEqual(
            fremd, [],
            'Der Abschnitt «Vertretung» von A führt eine Abwesenheit aus B — '
            'dann steht dort, wer bei der anderen Verwaltung wann Ferien hat.')

    def test_bis_ist_einschliesslich(self):
        """Wer «bis heute» abwesend ist, ist HEUTE noch weg.

        `von` und `bis` sind beide inklusiv — das steht im Modell begründet und
        ist die häufigste Fehlerquelle bei Zeiträumen. Ein exklusives Ende
        liesse den Hinweis einen Tag zu früh verschwinden, und zwar an dem Tag,
        an dem die Vertretung noch gilt.
        """
        heute = timezone.localdate()
        self._abwesend(self.a.organisation, 'lea-heute', self.a.benutzer,
                       heute - timedelta(days=3), heute)

        self.assertEqual(
            len(self._seite().context['vertretung_fuer']), 1,
            'Der Hinweis fehlt am letzten Tag der Abwesenheit — dann steht '
            'jemand ohne Vertretung da, während sie noch gilt.')

    def test_eine_abgelaufene_vertretung_steht_nicht_mehr_da(self):
        """Die Gegenprobe zur Zeile darüber.

        Ohne sie wäre «bis ist einschliesslich» auch dann grün, wenn der
        Hinweis gar nie verschwände — und ein Hinweis, der immer steht, ist
        keiner.
        """
        heute = timezone.localdate()
        self._abwesend(self.a.organisation, 'lea-vorbei', self.a.benutzer,
                       heute - timedelta(days=5), heute - timedelta(days=1))

        self.assertEqual(
            self._seite().context['vertretung_fuer'], [],
            'Eine gestern abgelaufene Vertretung steht noch im Kopf.')

    def test_der_hinweis_kostet_die_startseite_nicht(self):
        """Fällt die Abfrage aus, bleibt die Zeile leer — die Seite steht.

        Der Hinweis ist Beiwerk; die Startseite ist es nicht. Geprüft wird der
        echte Ausfall, nicht der Kommentar darüber: Das Modell wird durch eines
        ersetzt, dessen Abfrage wirft.

        DIESER TEST HAT EINEN FEHLER IM BESTAND GEFUNDEN.

        Er scheiterte beim ersten Lauf — nicht am neuen Kopf, sondern an
        `arbeitsvorrat.vertretung()` darunter. Dort lag der `try` nur um den
        IMPORT, nicht um die Abfrage: also genau um die Zeile herum, die keinen
        Schutz braucht. Ein Fehler beim Laden der Abwesenheiten riss die ganze
        Startseite mit. Beide Stellen fangen jetzt die Abfrage, und der Test
        deckt beide ab — er misst die Seite, nicht eine Funktion.
        """
        from unittest.mock import patch

        import faelle.termin_models as tm

        class Kaputt:
            class objects:
                @staticmethod
                def laufend(*a, **k):
                    raise RuntimeError('Abwesenheiten nicht ladbar')

        with patch.object(tm, 'Abwesenheit', Kaputt), \
                self.assertLogs('core.views.fw.dashboard', level='ERROR'):
            antwort = self._seite()

        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.context['vertretung_fuer'], [])
        self.assertEqual(
            antwort.context['av_vertretung'], [],
            'Der Abschnitt «Vertretung» im Arbeitsvorrat hat den Ausfall nicht '
            'aufgefangen.')


class KopfFilterTests(TestCase):
    """«Zuständigkeit» und «Mandat» — Konzept v7.

    SIE GREIFEN IN DIE ABFRAGE, NICHT AUF DIE FERTIGE LISTE

    Das ist der Kern: Würde erst die fertige Liste gefiltert, zeigte die
    Kopfzeile weiter «6 fällig heute» und nur die sichtbaren Zeilen wären
    weniger. Ausserdem schneidet `[:20]` VOR dem Filter — die eigenen Fälle
    könnten aus dem Fenster fallen, während fremde den Platz belegen.

    NUR DIE FALLSCHRITTE WERDEN GEFILTERT

    Läufe, Pendenzen und Wartungsfristen hängen an keinem Fall. Sie
    ungefiltert zu lassen ist richtig: Ein Zahllauf gehört allen, auch wenn
    gerade jemand nach seinen eigenen Fällen sucht.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _mit_frist(self, betreff, zustaendig=None, akte=None, org=None):
        """Ein Fall mit fälligem Schritt — sonst steht er nicht im Vorrat."""
        from faelle.models import Fall, Fallart, SchrittVorlage

        org = org or self.a.organisation
        with mandant(org):
            art = Fallart.objects.create(
                organisation=org, schluessel=betreff[:8].lower(),
                bezeichnung=betreff)
            # OHNE SCHRITTVORLAGE ENTSTEHEN KEINE SCHRITTE.
            #
            # `schritte_anlegen()` kopiert die Vorlagen der Fallart. Fehlt eine,
            # bleibt der Fall ohne Schritt — und damit ohne Frist und ohne Zeile
            # im Arbeitsvorrat. Ein leerer Vorrat sieht dann aus wie ein
            # Filterfehler und ist keiner.
            SchrittVorlage(fallart=art, nr=1, etappe_nr=1, etappe='E',
                           bezeichnung=f'Schritt {betreff}').save()
            fall = Fall(organisation=org, fallart=art, akte=akte,
                        betreff=betreff, zustaendig=zustaendig)
            fall.save()
            fall.schritte_anlegen()
            s = fall.schritte.first()
            self.assertIsNotNone(
                s, 'Der Fall hat keinen Schritt — dann prüft der Test nichts.')
            s.frist = timezone.localdate()
            s.save()
        return fall

    def _vorrat(self, org=None, **filter):
        from faelle.arbeitsvorrat import was_reisst

        # `titel` ist die SCHRITTbezeichnung; der Fallbetreff steht in `zeile`.
        # Nachgesehen in `_fallschritte`, nicht geraten.
        with mandant(org or self.a.organisation):
            return [f"{e.get('titel', '')} {e.get('zeile', '')}"
                    for e in was_reisst(timezone.localdate(), **filter)]

    def _team_mitglied(self, org, username):
        from django.contrib.auth import get_user_model

        from crm.models import Mitgliedschaft

        with mandant(org):
            u = get_user_model().objects.create_user(username=username,
                                                     password='x')
            Mitgliedschaft.objects.create(
                benutzer=u, organisation=org,
                rolle=Mitgliedschaft.ROLLE_SACHBEARBEITER)
        return u

    # -- Die Wirkung der Filter -------------------------------------------

    def test_ohne_filter_stehen_beide_faelle_da(self):
        """Die Gegenprobe zum Test darunter.

        Ohne sie wäre «gefiltert» nicht von «gar nichts gefunden» zu
        unterscheiden.
        """
        lea = self._team_mitglied(self.a.organisation, 'lea-f')
        self._mit_frist('Meiner', zustaendig=self.a.benutzer)
        self._mit_frist('Ihrer', zustaendig=lea)

        alle = ' '.join(self._vorrat())
        self.assertIn('Meiner', alle)
        self.assertIn('Ihrer', alle)

    def test_die_zustaendigkeit_schraenkt_ein(self):
        lea = self._team_mitglied(self.a.organisation, 'lea-g')
        self._mit_frist('Meiner', zustaendig=self.a.benutzer)
        self._mit_frist('Ihrer', zustaendig=lea)

        meins = ' '.join(self._vorrat(wer=self.a.benutzer))
        self.assertIn('Meiner', meins)
        self.assertNotIn(
            'Ihrer', meins,
            'Ein fremder Fall steht trotz Filter im Vorrat — dann filtert die '
            'Seite nur die Anzeige, nicht die Abfrage.')

    def test_der_mandatsfilter_schraenkt_auf_die_akte_ein(self):
        """«Fälle dieses Mandats» — was DIREKT am Eigentümer hängt.

        Ein Fall an einer Liegenschaft dieses Eigentümers erscheint nicht. Das
        ist eine benannte Einschränkung: `Fall` hat kein `liegenschaft`-Feld,
        er hängt über `akte_typ`/`akte_id` an einer beliebigen Akte.
        """
        from crm.models import Eigentuemer

        with mandant(self.a.organisation):
            zweiter = Eigentuemer.objects.create(
                organisation=self.a.organisation, firma_oder_name='Zweiter')
        self._mit_frist('AmMandat', akte=self.a.eigentuemer)
        self._mit_frist('AmAndern', akte=zweiter)

        nur = ' '.join(self._vorrat(mandat=self.a.eigentuemer))
        self.assertIn('AmMandat', nur)
        self.assertNotIn('AmAndern', nur)

    def test_laeufe_bleiben_trotz_filter_stehen(self):
        """Ein Zahllauf gehört allen — GEMESSEN, nicht an der Tabelle abgelesen.

        Die erste Fassung dieses Tests las nur `QUELLEN` und prüfte, dass dort
        genau `_fallschritte` steht. Das ist eine Aussage über eine Liste, nicht
        über das Verhalten: Sie bliebe grün, wenn `was_reisst` beim Filtern
        alle anderen Quellen überspringt. Jetzt wird ein echter Lauf angelegt
        und im gefilterten Vorrat gesucht.

        Warum das zählt: Wer nach seinen eigenen Fällen sucht, verlöre sonst
        den Blick auf einen blockierten Lauf — und ein Lauf, der nicht
        ausgelöst wurde, kostet mehr als ein übersehener Fallschritt.
        """
        from faelle.lauf_models import Lauf, Laufart

        org = self.a.organisation
        with mandant(org):
            art = Laufart.objects.create(
                organisation=org, schluessel='soll', bezeichnung='Sollstellung',
                rhythmus='monatlich')
            Lauf.objects.create(organisation=org, laufart=art, periode='2026-08',
                                faellig_am=timezone.localdate())
        self._mit_frist('Meiner', zustaendig=self.a.benutzer)

        gefiltert = ' '.join(self._vorrat(wer=self.a.benutzer))
        self.assertIn('Meiner', gefiltert)
        self.assertIn(
            'Sollstellung', gefiltert,
            'Der Lauf verschwindet, sobald jemand nach seinen Fällen filtert — '
            'dann greift der Filter auf Quellen, die an keinem Fall hängen.')

    def test_ein_ausfall_der_gefilterten_abfrage_kostet_die_seite_nicht(self):
        """Der Ausfallschutz muss auch im gefilterten Zweig greifen.

        Ein erster Entwurf zog den gefilterten Aufruf mit `continue` VOR den
        `try`. Damit lief ausgerechnet die neue Abfrage ohne Schutz, und ein
        Fehler dort hätte die Startseite mit 500 beendet statt eine Quelle
        auszulassen. Derselbe Fund wie in E2.59 bei `vertretung()` — dort lag
        der `try` um den Import statt um die Abfrage.
        """
        from unittest.mock import patch

        import faelle.arbeitsvorrat as av

        def kaputt(*a, **k):
            raise RuntimeError('Fallschritte nicht ladbar')

        quellen = tuple((n, kaputt if f is av._fallschritte else f, lg)
                        for n, f, lg in av.QUELLEN)
        with patch.object(av, 'QUELLEN', quellen), \
                patch.object(av, '_fallschritte', kaputt), \
                self.assertLogs('faelle.arbeitsvorrat', level='ERROR'):
            zeilen = self._vorrat(wer=self.a.benutzer)

        self.assertIsInstance(zeilen, list)

    # -- Die Mandantengrenze ----------------------------------------------

    def test_das_auswahlfeld_zeigt_nur_das_eigene_team(self):
        """`Benutzer.objects` IST NICHT MANDANTENGETRENNT.

        Das Modell ist ein schlichter `AbstractUser` mit Djangos `UserManager`;
        die Zugehörigkeit hängt an `Mitgliedschaft`, weil eine Treuhänderin für
        zwei Verwaltungen arbeiten kann. Ohne `mitgliedschaften__organisation`
        stünde hier das vollständige Team jeder anderen Verwaltung, mit Namen.

        Genau dieser Fund steht seit dem 17.08.2026 in `profil.py` — dort fiel
        er durchs Raster des Registrylaufs, weil die URL keinen ID-Parameter
        trägt. Ein Auswahlfeld trägt auch keinen.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get('/neu/')

        namen = {u.username for u in antwort.context['f_wer_auswahl']}
        self.assertIn(self.a.benutzer.username, namen,
                      'Ohne das eigene Team prüft der Test nichts.')
        self.assertNotIn(
            b.benutzer.username, namen,
            'Im Auswahlfeld von A steht ein Benutzer von B — dann liest die '
            'Startseite das Team der anderen Verwaltung.')

    def test_das_mandatsfeld_zeigt_nur_die_eigenen_eigentuemer(self):
        b = MandantenFixture('B', '3000', 'Bern')
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get('/neu/')

        ids = {m.pk for m in antwort.context['f_mandat_auswahl']}
        self.assertIn(self.a.eigentuemer.pk, ids)
        self.assertNotIn(b.eigentuemer.pk, ids)

    def test_eine_fremde_benutzer_id_greift_nicht(self):
        """Ein geratener `?wer=` darf nicht auf einen fremden Benutzer zeigen.

        Die Fälle sind ohnehin mandantengetrennt, das Ergebnis bliebe also
        leer. Aber `f_wer` landet im Auswahlfeld als ausgewählter Eintrag —
        dort stünde dann der NAME einer fremden Person.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        c = Client()
        c.force_login(self.a.benutzer)
        antwort = c.get(f'/neu/?wer={b.benutzer.pk}')

        self.assertIsNone(
            antwort.context['f_wer'],
            'Eine fremde Benutzer-ID wird aufgelöst — dann steht der Name '
            'einer fremden Person im Auswahlfeld von A.')

    # -- Die Filter überleben einen Reiterwechsel --------------------------

    def test_ein_reiterwechsel_verliert_die_filter_nicht(self):
        """`?ansicht=x` ersetzt die ganze Abfragezeichenfolge.

        Ohne `f_query` in den Reiter-Adressen hebt jeder Wechsel still alle
        Filter auf. `f_query` wurde im ersten Entwurf berechnet und NIRGENDS
        verwendet — die Begründung stand da, die Wirkung fehlte.
        """
        lea = self._team_mitglied(self.a.organisation, 'lea-reiter')
        c = Client()
        c.force_login(self.a.benutzer)
        inhalt = c.get(f'/neu/?wer={lea.pk}').content.decode()

        # `&amp;`, nicht `&` — Django maskiert die Adresse beim Rendern. Die
        # erste Fassung suchte das rohe Zeichen und war rot, obwohl die
        # Verdrahtung stimmte.
        self.assertIn(f'?ansicht=woche&amp;wer={lea.pk}', inhalt,
                      'Die Reiter tragen den Zuständigkeitsfilter nicht mit.')

    def test_ein_reiterwechsel_verliert_den_liegenschaftsfilter_nicht(self):
        """Derselbe Verlust, nur älter — und schwerer.

        Der Liegenschaftsfilter gilt für die ganze Anwendung. Bis E2.60 warf
        jeder Reiterwechsel auf der Startseite ihn weg, weil `?ansicht=x` die
        Adresse ersetzt. Aufgefallen beim Einbauen von `f_query`, nicht durch
        einen Bericht.
        """
        c = Client()
        c.force_login(self.a.benutzer)
        inhalt = c.get(f'/neu/?lg={self.a.liegenschaft.pk}').content.decode()

        self.assertIn(f'?ansicht=woche&amp;lg={self.a.liegenschaft.pk}', inhalt,
                      'Ein Reiterwechsel wirft den Liegenschaftsfilter weg.')


class FallartBandTests(TestCase):
    """Das Filterband aus Konzept v7 — geprüft an der SEITE, nicht an der Funktion.

    WARUM AN DER SEITE

    Ein Test auf `was_reisst()` wäre grün geblieben, während die Seite alles
    zeigte: Die Ansicht ruft die Sammelfunktion ein ZWEITES Mal als Obermenge
    für alle Reiter, und diese Liste überschrieb das gefilterte Ergebnis.
    Adresse richtig, Band markiert, Zähler stimmten — und die Liste
    unverändert. Ein Filter, der aussieht, als wirke er, ist schlimmer als
    keiner.

    UND WARUM IN JEDEM REITER

    Die Reiter «Wartet auf Dritte» und «Liegengeblieben» zeigen `Fall`-Objekte
    statt Vorratszeilen. Der erste Entwurf filterte nur die Vorratszeilen; dort
    stand das Band sichtbar und wirkungslos — derselbe Fehler, eine Ebene
    tiefer. Gemessen, nicht vermutet.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _fall(self, schluessel, bezeichnung, betreff, tage=0, org=None):
        from faelle.models import Fall, Fallart, SchrittVorlage

        org = org or self.a.organisation
        with mandant(org):
            art, neu = Fallart.objects.get_or_create(
                organisation=org, schluessel=schluessel,
                defaults={'bezeichnung': bezeichnung})
            if neu:
                SchrittVorlage(fallart=art, nr=1, etappe_nr=1, etappe='E',
                               bezeichnung=f'{bezeichnung} prüfen').save()
            fall = Fall(organisation=org, fallart=art, akte=None, betreff=betreff)
            fall.save()
            fall.schritte_anlegen()
            s = fall.schritte.first()
            self.assertIsNotNone(
                s, 'Ohne Schritt steht der Fall nicht im Vorrat — dann prüft '
                   'der Test nichts.')
            s.frist = timezone.localdate() + timedelta(days=tage)
            s.save()
        return fall

    def _liegengeblieben(self, fall):
        from faelle.models import Fall

        with mandant(self.a.organisation):
            Fall.objects.filter(pk=fall.pk).update(
                letzte_bewegung=timezone.now() - timedelta(days=30))

    def _seite(self, **abfrage):
        c = Client()
        c.force_login(self.a.benutzer)
        teile = '&'.join(f'{k}={v}' for k, v in abfrage.items())
        return c.get(f'/neu/?{teile}' if teile else '/neu/')

    # -- Die Wirkung -------------------------------------------------------

    def test_ohne_band_stehen_beide_arten_da(self):
        """Die Gegenprobe. Ohne sie wäre «gefiltert» nicht von «leer» zu
        unterscheiden."""
        self._fall('schaden-b', 'Schaden', 'Wasserschaden')
        self._fall('mietzins-b', 'Mietzins', 'Erhöhung')

        html = self._seite(ansicht='alle').content.decode()
        self.assertIn('Wasserschaden', html)
        self.assertIn('Erhöhung', html)

    def test_das_band_filtert_die_ausgelieferte_seite(self):
        self._fall('schaden-c', 'Schaden', 'Wasserschaden')
        self._fall('mietzins-c', 'Mietzins', 'Erhöhung')

        html = self._seite(ansicht='alle', fallart='schaden-c').content.decode()
        self.assertIn('Wasserschaden', html)
        self.assertNotIn(
            'Erhöhung', html,
            'Eine fremde Fallart steht trotz Band auf der Seite — dann '
            'filtert die Ansicht nur die Zähler, nicht die Liste.')

    def test_das_band_wirkt_auch_im_reiter_liegengeblieben(self):
        """Der Reiter zeigt `Fall`-Objekte, nicht Vorratszeilen.

        Der erste Entwurf filterte nur die Vorratszeilen. In «Wartet auf
        Dritte» und «Liegengeblieben» war das Band damit sichtbar und
        wirkungslos — genau der Zustand, den diese Etappe beheben soll, nur
        eine Ebene tiefer. Gemessen: Liste vor und nach dem Klick identisch.
        """
        a = self._fall('schaden-l', 'Schaden', 'Wasserschaden')
        b = self._fall('mietzins-l', 'Mietzins', 'Erhöhung')
        self._liegengeblieben(a)
        self._liegengeblieben(b)

        offen = self._seite(ansicht='liegen')
        self.assertEqual(len(offen.context['faelle']), 2,
                         'Ohne zwei liegengebliebene Fälle prüft der Test nichts.')

        eng = self._seite(ansicht='liegen', fallart='schaden-l')
        betreffe = {f.betreff for f in eng.context['faelle']}
        self.assertEqual(
            betreffe, {'Wasserschaden'},
            'Das Band lässt die Liste im Reiter «Liegengeblieben» unverändert — '
            'dann steht dort ein Filter, der nichts tut.')

    # -- Die Zähler --------------------------------------------------------

    def test_die_zaehler_passen_zur_liste_darunter(self):
        """Der Fund, der diese Etappe geprägt hat.

        Das Band wurde in `arbeitsvorrat()` gebaut, aus einem eigenen Aufruf
        von `was_reisst()` mit dem 14-Tage-Fenster. Der Reiter «Alle» zeigt
        aber ein Jahr. Gemessen: Band «Alle 2» über einer Liste von VIER
        Zeilen — und die Fallart der vierten hatte gar kein Feld im Band, war
        also nicht auswählbar.

        Ein Zähler, der nicht zu seiner Liste passt, ist schlimmer als keiner:
        Er sieht aus wie eine Auskunft.
        """
        self._fall('schaden-z', 'Schaden', 'Wasserschaden', tage=0)
        self._fall('mietzins-z', 'Mietzins', 'Erhöhung', tage=100)

        antwort = self._seite(ansicht='alle')
        self.assertEqual(
            antwort.context['av_band_gesamt'], len(antwort.context['vorrat']),
            '«Alle N» zählt etwas anderes als die Liste darunter.')
        arten = {b['schluessel'] for b in antwort.context['av_band']}
        self.assertIn(
            'mietzins-z', arten,
            'Eine Fallart aus der Liste fehlt im Band — sie ist damit nicht '
            'auswählbar, und der Nutzer sieht nicht, warum.')

    def test_die_zaehler_stehen_vor_dem_filtern_fest(self):
        """Wer «Schaden 2» sieht und klickt, muss «Mietzins 1» daneben behalten.

        Sonst gäbe es keinen Weg zurück ausser über «Alle».
        """
        self._fall('schaden-d', 'Schaden', 'Wasserschaden')
        self._fall('mietzins-d', 'Mietzins', 'Erhöhung')

        band = self._seite(ansicht='alle', fallart='schaden-d').context['av_band']
        self.assertIn('mietzins-d', {b['schluessel'] for b in band},
                      'Nach dem Filtern fehlt die andere Fallart im Band.')

    def test_bei_einer_einzigen_fallart_erscheint_kein_band(self):
        """Eine Zeile ohne Wahl ist keine Wahl."""
        self._fall('schaden-e1', 'Schaden', 'Wasserschaden')
        antwort = self._seite(ansicht='alle')
        self.assertLessEqual(len(antwort.context['av_band']), 1)
        self.assertNotIn('fw-band', antwort.content.decode())

    # -- Die Adressen ------------------------------------------------------

    def test_ein_reiterwechsel_behaelt_die_fallart(self):
        """Am gerenderten Verweis geprüft, nicht am berechneten Wert.

        `f_query` stand in E2.60 schon einmal richtig im Kontext und war
        NIRGENDS verdrahtet. Ein Test auf `context['f_query']` hätte das nicht
        gemeldet.
        """
        self._fall('schaden-f', 'Schaden', 'Wasserschaden')
        self._fall('mietzins-f', 'Mietzins', 'Erhöhung')

        html = self._seite(ansicht='alle', fallart='schaden-f').content.decode()
        self.assertIn('?ansicht=woche&amp;fallart=schaden-f', html,
                      'Ein Reiterwechsel verliert die Bandauswahl.')

    def test_die_bandfelder_tragen_die_eigene_auswahl_nicht_mit(self):
        """Sonst entstünde `?fallart=a&fallart=b`, und «Alle» höbe nichts auf.

        Die Felder des Bandes setzen die Fallart selbst; sie dürfen sie nicht
        zusätzlich aus `f_query` mitschleppen.
        """
        self._fall('schaden-g', 'Schaden', 'Wasserschaden')
        self._fall('mietzins-g', 'Mietzins', 'Erhöhung')

        html = self._seite(ansicht='alle', fallart='schaden-g').content.decode()
        self.assertNotIn('fallart=mietzins-g&amp;fallart=', html)
        self.assertNotIn('fallart=schaden-g&amp;fallart=', html)
        # «Alle» muss den Filter wirklich aufheben.
        self.assertIn('href="?ansicht=alle"', html,
                      'Das Feld «Alle» trägt noch einen Filter mit.')

    def test_eine_fremde_fallart_zeigt_keine_fremden_faelle(self):
        """Die Mandantengrenze — hier über die Liste, nicht über die Abfrage.

        Der Bandfilter vergleicht eine Zeichenkette aus der Adresse gegen die
        fertige Liste. Die Liste stammt bereits aus mandantengetrennten
        Abfragen, ein fremder Schlüssel kann also nichts Fremdes hereinholen.
        Der Test hält das fest, weil `Fallart.schluessel` NUR je Organisation
        eindeutig ist: Zwei Verwaltungen dürfen «schaden» heissen, ohne dass
        die eine die Fälle der anderen sieht.
        """
        b = MandantenFixture('B', '3000', 'Bern')
        self._fall('gleich', 'Schaden', 'Meiner')
        self._fall('gleich', 'Schaden', 'Ihrer', org=b.organisation)

        html = self._seite(ansicht='alle', fallart='gleich').content.decode()
        self.assertIn('Meiner', html)
        self.assertNotIn(
            'Ihrer', html,
            'Ein gleichnamiger Schlüssel holt Fälle aus der anderen '
            'Organisation herein.')


class ZeilenangabenTests(TestCase):
    """Fallnummer, Fortschritt und Zuständigkeit in der Vorratszeile.

    Konzept v7 zeigt je Zeile mehr als Titel und Betreff: «Mieterwechsel ·
    F-2026-0184», darunter «Schritt 3 von 6» und rechts das Kürzel der
    zuständigen Person.

    WAS FEHLTE, IST DIE EINORDNUNG. Ein Fall bei Schritt 3 von 6 ist etwas
    anderes als einer bei 5 von 6 — und wer ihn führt, entscheidet, ob man ihn
    anfasst oder liegen lässt.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _fall(self, zustaendig=None):
        from faelle.models import Fall, Fallart, SchrittVorlage

        org = self.a.organisation
        with mandant(org):
            art, neu = Fallart.objects.get_or_create(
                organisation=org, schluessel='za',
                defaults={'bezeichnung': 'Prüfung'})
            if neu:
                for nr in (1, 2):
                    SchrittVorlage(fallart=art, nr=nr, etappe_nr=1, etappe='E',
                                   bezeichnung=f'Schritt {nr}').save()
            fall = Fall(organisation=org, fallart=art, akte=None,
                        betreff='Prüffall', zustaendig=zustaendig)
            fall.save()
            fall.schritte_anlegen()
            s = fall.schritte.first()
            s.frist = timezone.localdate()
            s.save()
        return fall

    def _zeile(self):
        from faelle.arbeitsvorrat import was_reisst

        with mandant(self.a.organisation):
            for e in was_reisst(timezone.localdate()):
                if e.get('art') == 'fall':
                    return e
        self.fail('Keine Fallzeile im Vorrat.')

    def test_die_fallnummer_steht_in_der_zeile(self):
        fall = self._fall()
        self.assertEqual(self._zeile()['nummer'], fall.nummer)

    def test_der_fortschritt_zaehlt_die_schritte(self):
        """«Schritt 1 von 2» — nicht «0 von 2».

        Die Zeile IST ein bestimmter Schritt; gezeigt wird seine Nummer.
        """
        self._fall()
        self.assertEqual(self._zeile()['fortschritt'], 'Schritt 1 von 2')

    def test_der_fortschritt_nennt_den_schritt_der_zeile(self):
        """Nicht «erledigte + 1» — das stimmt nur bei Abarbeitung der Reihe nach.

        Der Entwurf rechnete die Position aus der Zahl der ERLEDIGTEN Schritte.
        Sind Schritt 1 und 3 erledigt und 2 offen, stünde an der Zeile von
        Schritt 2 «Schritt 3 von 3» — die Zeile spräche über einen anderen
        Schritt als den, den sie zeigt.

        Aus der Reihe zu arbeiten ist erlaubt: `Fallschritt` kennt keine
        Sperre, die den nächsten Schritt erzwingt.
        """
        from faelle.models import Fallschritt

        fall = self._fall()
        with mandant(self.a.organisation):
            spaeter = fall.schritte.order_by('nr').last()
            Fallschritt.objects.filter(pk=spaeter.pk).update(
                erledigt_am=timezone.now())

        self.assertEqual(
            self._zeile()['fortschritt'], 'Schritt 1 von 2',
            'Die Zeile nennt eine andere Schrittnummer als den Schritt, den '
            'sie zeigt — dann wird die Position geschätzt statt gelesen.')

    # DER ABFRAGEZAEHLER STEHT JETZT IN `ArbeitsvorratAbfragezahlTests`.
    #
    # E2.62 hatte ihn hier, mit einer Obergrenze (`< 12`) und einem inline
    # aufgebauten Bestand. Der eigene Waechter unten misst dieselbe Sache
    # GENAU (vier Abfragen, eine je Quelle), an einem Fixture, das gross genug
    # ist, dass eine Schleife nicht wie eine Abfrage aussieht. Zwei Waechter
    # fuer dieselbe Zusicherung waeren einer zu viel — und der schwaechere
    # bliebe stehen, wenn jemand den staerkeren lockert.

    def test_das_kuerzel_kommt_aus_dem_namen(self):
        from benutzer.models import Benutzer

        with mandant(self.a.organisation):
            dm = Benutzer.objects.create_user(
                username='dm-z', password='x',
                first_name='Dominik', last_name='Muster')
        self._fall(zustaendig=dm)
        self.assertEqual(self._zeile()['wer'], 'DM')

    def test_ohne_zustaendigkeit_steht_niemand_da(self):
        """Nicht ein leeres Feld.

        Ein leeres Feld sähe aus wie ein Darstellungsfehler. Ein Fall ohne
        Zuständigkeit soll auffallen — das ist der Sinn der Angabe.
        """
        self._fall()
        self.assertEqual(self._zeile()['wer'], 'niemand')

    def test_die_angaben_stehen_auch_auf_der_seite(self):
        """Am gerenderten HTML geprüft, nicht nur am Wörterbuch.

        In E2.60 stand `f_query` schon einmal richtig im Kontext und war
        NIRGENDS verdrahtet. Ein Test auf die Sammelfunktion hätte das nicht
        gemeldet — dieselbe Lücke wie hier, wenn niemand die Vorlage prüft.
        """
        from django.contrib.auth import get_user_model

        from crm.models import Mitgliedschaft

        with mandant(self.a.organisation):
            dm = get_user_model().objects.create_user(
                username='dm-seite', password='x',
                first_name='Dominik', last_name='Muster')
            Mitgliedschaft.objects.create(
                benutzer=dm, organisation=self.a.organisation,
                rolle=Mitgliedschaft.ROLLE_SACHBEARBEITER)
        fall = self._fall(zustaendig=dm)

        c = Client()
        c.force_login(self.a.benutzer)
        html = c.get('/neu/?ansicht=alle').content.decode()

        self.assertIn(fall.nummer, html, 'Die Fallnummer fehlt in der Zeile.')
        self.assertIn('Schritt 1 von 2', html, 'Der Fortschritt fehlt in der Zeile.')
        self.assertIn('class="fw-kuerzel"', html,
                      'Das Kürzel wird berechnet, aber nicht gezeigt.')
        self.assertIn('>DM</span>', html)

    def test_ohne_namen_traegt_das_kuerzel_den_anmeldenamen(self):
        """Sonst stünde dort ein leeres Feld — und das sähe aus wie ein Fehler.

        Ein Konto ohne Vor- und Nachnamen ist der Normalfall bei
        Sammelzugängen und frisch eingeladenen Mitgliedern.
        """
        from django.contrib.auth import get_user_model

        from faelle.arbeitsvorrat import _kuerzel

        with mandant(self.a.organisation):
            nur_login = get_user_model().objects.create_user(
                username='rezeption', password='x')
        self.assertEqual(_kuerzel(nur_login), 'RE')

    def test_nur_der_vorname_genuegt(self):
        from django.contrib.auth import get_user_model

        from faelle.arbeitsvorrat import _kuerzel

        with mandant(self.a.organisation):
            lea = get_user_model().objects.create_user(
                username='lea-k', password='x', first_name='Lea')
        self.assertEqual(_kuerzel(lea), 'LE')


class ArbeitsvorratAbfragezahlTests(TestCase):
    """Auch `was_reisst()` darf nicht je Zeile rechnen.

    DIE LÜCKE, DIE DIESER TEST SCHLIESST

    `AbfragezahlTests` oben prüft `mandate()` und die Senkungsansprüche — nicht
    die Sammelfunktion des Arbeitsvorrats. Genau dort ist in E2.62 ein N+1
    entstanden: `Fall.fortschritt` in der Schleife, zwei `COUNT` je Zeile.

    GEMESSEN: 4 Abfragen mit Annotation, 28 mit der Eigenschaft — bei zwölf
    Zeilen. Bei der Obergrenze von zwanzig wären es 44 statt 4. Auf der
    meistbesuchten Seite der Anwendung.

    Aufgefallen ist es der Gegenprüfung, nicht der Suite: Meine eigene
    Gegenprobe blieb grün, weil sie den falschen Test anstiess.

    WARUM DIE DATENMENGE HIER WÄCHST

    Bei drei Fällen sähe eine Schleife wie eine Abfrage aus. Erst ab einem
    Dutzend wird der Unterschied zwischen «je Menge» und «je Datensatz»
    sichtbar — derselbe Grund wie beim Fixture oben.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        from faelle.models import Fall, Fallart, SchrittVorlage

        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with mandant(cls.a.organisation):
            art = Fallart.objects.create(
                organisation=cls.a.organisation, schluessel='az',
                bezeichnung='Abfragezahl')
            for nr in range(1, 5):
                SchrittVorlage(fallart=art, nr=nr, etappe_nr=1, etappe='E',
                               bezeichnung=f'Schritt {nr}').save()
            # JEDER FALL HAT EINE ZUSTAENDIGE PERSON — sonst prueft der
            # Zaehler die halbe Zeile.
            #
            # Ohne sie ruft `_kuerzel` nie auf, `s.fall.zustaendig` wird nie
            # gelesen, und `select_related('fall__zustaendig')` ist unbelegt:
            # Die Gegenprobe «select_related entfernt» blieb GRUEN. Ein
            # Waechter, der einen Verweis zaehlt, den sein Bestand nicht
            # benutzt, zaehlt die falsche Sache.
            wer = get_user_model().objects.create_user(
                username='az-zustaendig', password='x',
                first_name='Dominik', last_name='Muster')
            for i in range(12):
                fall = Fall(organisation=cls.a.organisation, fallart=art,
                            akte=None, betreff=f'Fall {i}', zustaendig=wer)
                fall.save()
                fall.schritte_anlegen()
                s = fall.schritte.first()
                s.frist = timezone.localdate()
                s.save()

    def test_der_vorrat_rechnet_je_menge(self):
        """Die Obergrenze ist grosszügig — sie fängt den Rückbau ab, nicht
        jede Verfeinerung."""
        from faelle.arbeitsvorrat import was_reisst

        with mandant(self.a.organisation):
            # VIER — EINE JE QUELLE, und das ist die ganze Aussage.
            #
            # `assertNumQueries` prueft auf GLEICHHEIT, nicht auf eine
            # Obergrenze: Ein zu hoher Wert schlaegt genauso fehl wie ein zu
            # tiefer. Das ist hier Absicht und entspricht den zwei Waechtern
            # oben (`mandate` = 1, Senkungsansprueche = 2). Ein «Puffer» waere
            # kein Puffer, sondern eine unmessbare Erwartung.
            #
            # WAS DIESE ZAHL LEGITIM AENDERT: eine fuenfte Quelle in `QUELLEN`,
            # oder ein Lauf im Fixture — `_laeufe` holt seine Blockaden per
            # `prefetch_related`, und Django ueberspringt das nur bei leerer
            # Grundmenge. Dann ist die neue Zahl zu messen und einzutragen,
            # nicht aufzurunden.
            #
            # Der N+1 aus E2.62 lag bei 28.
            with self.assertNumQueries(4):
                zeilen = was_reisst(timezone.localdate())
            self.assertGreaterEqual(
                len(zeilen), 12,
                'Der Vorrat liefert weniger Zeilen als angelegt — dann misst '
                'der Test eine leere Menge und beweist nichts.')
            self.assertTrue(
                all(z.get('wer') == 'DM' for z in zeilen
                    if z.get('art') == 'fall'),
                'Die Zeilen tragen keine Zustaendigkeit — dann bleibt der '
                'Verweis auf `zustaendig` ungelesen und ungezaehlt.')

    def test_der_fortschritt_kommt_ohne_zusatzabfrage(self):
        """Die Angabe selbst muss dastehen, nicht nur die Abfragezahl stimmen.

        Ein Test, der nur zählt, bliebe grün, wenn jemand den Fortschritt
        ersatzlos entfernt.
        """
        from faelle.arbeitsvorrat import was_reisst

        with mandant(self.a.organisation):
            zeilen = [e for e in was_reisst(timezone.localdate())
                      if e.get('art') == 'fall']
        self.assertTrue(zeilen)
        self.assertEqual(zeilen[0]['fortschritt'], 'Schritt 1 von 4')


class FusszeilenZweiteAngabeTests(TestCase):
    """«11 Positionen, 3 in Mahnstufe 2» — die zweite Zahl ist eine TEILMENGE.

    Beide Fusszeilen lesen sich so, und deshalb müssen sie dieselbe Menge
    einschränken statt eine andere zu zählen. Elf offene Posten sind Alltag,
    drei davon in der zweiten Mahnung nicht; Leerstand ist eine Zahl,
    Leerstand ohne Ausschreibung eine Unterlassung.

    DER ERSTE ENTWURF ZÄHLTE ZWEI FREMDE MENGEN — gemessen: Eine im Januar
    2025 gemahnte, längst bezahlte Rechnung ergab «1 Position, 1 in Mahnstufe
    2», obwohl die eine offene Position nie gemahnt worden war.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _kacheln(self, stichtag=None, aktive_lg=None):
        with mandant(self.a.organisation):
            return {k['schluessel']: k
                    for k in streifen(stichtag or timezone.localdate(), aktive_lg)}

    def test_eine_bezahlte_altmahnung_faerbt_die_fusszeile_nicht(self):
        """Der gemessene Fall.

        Die Mahnung gehört zu einer bezahlten Rechnung aus dem Vorjahr. Sie
        gehört in keine Aussage über die offenen Positionen DIESES Monats.
        """
        from finance.models import Mahnung

        heute = timezone.localdate()
        with mandant(self.a.organisation):
            alt = _rechnung(self.a.vertrag, '500', date(2025, 1, 5), 'bezahlt')
            Mahnung.objects.create(debitoren_rechnung=alt, stufe=3)
            _rechnung(self.a.vertrag, '900', heute.replace(day=1), 'offen')

        fuss = self._kacheln()['ausstaende']['fuss']
        self.assertIn('1 Position', fuss)
        self.assertNotIn(
            'Mahnstufe', fuss,
            'Eine bezahlte Rechnung aus dem Vorjahr steht in der Fusszeile '
            'dieses Monats — dann zählt die zweite Zahl eine andere Menge als '
            'die erste.')

    def test_eine_gemahnte_offene_position_steht_in_der_fusszeile(self):
        """Die Gegenprobe: Der echte Fall MUSS erscheinen.

        Ohne sie wäre der Test darüber auch dann grün, wenn die Angabe nie
        erscheint.
        """
        from finance.models import Mahnung

        heute = timezone.localdate()
        with mandant(self.a.organisation):
            offen = _rechnung(self.a.vertrag, '900', heute.replace(day=1), 'offen')
            Mahnung.objects.create(debitoren_rechnung=offen, stufe=2)

        self.assertIn('1 in Mahnstufe 2', self._kacheln()['ausstaende']['fuss'])

    def test_die_erste_mahnstufe_zaehlt_nicht_mit(self):
        """«Mahnstufe 2» heisst ab der zweiten — die erste ist Alltag."""
        from finance.models import Mahnung

        heute = timezone.localdate()
        with mandant(self.a.organisation):
            offen = _rechnung(self.a.vertrag, '900', heute.replace(day=1), 'offen')
            Mahnung.objects.create(debitoren_rechnung=offen, stufe=1)

        self.assertNotIn('Mahnstufe', self._kacheln()['ausstaende']['fuss'])

    def test_der_liegenschaftsfilter_gilt_fuer_beide_zahlen(self):
        """Sonst ist die erste Zahl gefiltert und die zweite nicht.

        Jede andere Zahl im Streifen beachtet `aktive_lg`. Eine Fusszeile, die
        ihn übergeht, meldet eine Mahnstufe zu einer Liegenschaft, die gerade
        gar nicht angezeigt wird.
        """
        from finance.models import Mahnung
        from portfolio.models import Liegenschaft

        heute = timezone.localdate()
        with mandant(self.a.organisation):
            offen = _rechnung(self.a.vertrag, '900', heute.replace(day=1), 'offen')
            Mahnung.objects.create(debitoren_rechnung=offen, stufe=2)
            fremd = Liegenschaft.objects.create(
                organisation=self.a.organisation, eigentuemer=self.a.eigentuemer,
                strasse='Anderswo 1', plz='3000', ort='Bern')

        # Auf der eigenen Liegenschaft sichtbar …
        self.assertIn('Mahnstufe 2',
                      self._kacheln(aktive_lg=self.a.liegenschaft)['ausstaende']['fuss'])
        # … auf einer anderen nicht.
        self.assertNotIn(
            'Mahnstufe',
            self._kacheln(aktive_lg=fremd)['ausstaende']['fuss'],
            'Die Mahnstufe erscheint trotz Filter auf eine fremde '
            'Liegenschaft — dann übergeht die zweite Zahl den Filter.')

    def test_ohne_ausschreibung_zaehlt_nur_wirklich_leere_objekte(self):
        """Dieselbe Leerstandsdefinition wie der Wert darüber.

        `_leerstandsquote` prüft den Vertrag AM STICHTAG (`beginn <= tag <=
        ende`), nicht nur seinen Status. Ein aktiver Vertrag, der erst nächsten
        Monat beginnt, macht die Einheit heute nicht belegt — sie gehört in
        beide Zahlen.
        """
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag

        heute = timezone.localdate()
        with mandant(self.a.organisation):
            eh = Einheit.objects.create(
                liegenschaft=self.a.liegenschaft, bezeichnung='Leer 1',
                zur_ausschreibung=False)
            # Aktiv, aber erst in einem Monat — heute also leer.
            Mietvertrag.objects.create(
                mieter=self.a.mieter, einheit=eh, status='aktiv',
                beginn=heute + timedelta(days=30),
                netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'))

        fuss = self._kacheln()['leerstand']['fuss']
        self.assertIn(
            'ohne Ausschreibung', fuss,
            'Die künftig vermietete Einheit zählt als belegt — dann benutzt '
            'die zweite Zahl eine andere Leerstandsdefinition als die erste.')

    def test_ein_ausgeschriebenes_leeres_objekt_zaehlt_nicht(self):
        """Die Gegenprobe: Ausgeschrieben ist keine Unterlassung."""
        from portfolio.models import Einheit

        with mandant(self.a.organisation):
            Einheit.objects.create(
                liegenschaft=self.a.liegenschaft, bezeichnung='Leer 2',
                zur_ausschreibung=True)

        self.assertNotIn('ohne Ausschreibung',
                         self._kacheln()['leerstand']['fuss'])
