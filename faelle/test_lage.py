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
