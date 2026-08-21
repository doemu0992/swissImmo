"""Unterhaltsbudget je Liegenschaft — Befund, Erfassung, Trennung.

DER ENTSCHEID (21.08.2026)

`faelle/liegenschaften.py` fuehrte «Unterhalt ueber Budget» als offenen Punkt:
Es gab kein Budgetfeld, und ob eines je Mandat oder je Liegenschaft gefuehrt
wird, war eine betriebliche Frage, die man nicht plausibel ergaenzen darf.

Die Antwort ist **je Liegenschaft**. Unterhalt faellt am Gebaeude an, nicht am
Eigentuemer: Ein Mandat mit vier Liegenschaften hat vier Daecher, vier
Heizungen, vier Lifte. Ein gemeinsamer Topf verwischt, welches Haus Geld
kostet. Die Summe je Mandat laesst sich aus den Einzelbudgets bilden — der
umgekehrte Weg nicht.

WAS HIER GEPRUEFT WIRD, UND WARUM JEDES DAVON

Der Befund meldet nur, WEIL ein Budget da ist. Das ist die heikelste
Eigenschaft: Ein Hinweis «kein Budget erfasst» an jeder Liegenschaft waere die
klassische Dauerbeschwerde, die nach drei Wochen niemand mehr liest. Deshalb
steht `test_ohne_budget_wird_nicht_gemeldet` an erster Stelle — und deshalb
muss sich ein Budget auch wieder LOESCHEN lassen.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.liegenschaften import zeilen

HEUTE = timezone.localdate()


class _Basis(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    @property
    def lg(self):
        return self.a.liegenschaft

    def setUp(self):
        """Das Fixture bringt SELBST ein Budget mit (CHF 30'000, laufendes
        Jahr) — es wird fuer den Isolations-Sweep gebraucht, damit dieser eine
        echte fremde Id zum Ausprobieren hat.

        Die Tests hier setzen es deshalb bewusst neu, statt seine Abwesenheit
        anzunehmen. Was ein Fixture mitbringt, muss man nachsehen; genau diese
        Annahme hat in dieser Phase schon mehrfach Tests aus dem falschen Grund
        rot gefaerbt.
        """
        from portfolio.models import Liegenschaftsbudget
        with mandant(self.a.organisation):
            Liegenschaftsbudget.objects.filter(liegenschaft=self.lg).delete()

    def _budget(self, betrag, jahr=None):
        from portfolio.models import Liegenschaftsbudget
        return Liegenschaftsbudget.objects.update_or_create(
            liegenschaft=self.lg, jahr=jahr or HEUTE.year,
            defaults={'unterhalt': Decimal(betrag)})[0]

    def _unterhalt(self, kosten, datum=None):
        from portfolio.models import Unterhalt
        return Unterhalt.objects.create(
            liegenschaft=self.lg, titel='Reparatur',
            datum=datum or HEUTE, kosten=Decimal(kosten))

    def _chips(self):
        return zeilen([self.lg])[0]['chips']

    def _texte(self):
        return [c[1] for c in self._chips()]


class BefundTests(_Basis):

    def test_ohne_budget_wird_nicht_gemeldet(self):
        """Wer kein Budget fuehrt, will keines fuehren.

        Der Test setzt bewusst einen ABSURD hohen Unterhalt: Ohne Budget darf
        auch der nichts ausloesen.
        """
        with mandant(self.a.organisation):
            self._unterhalt('99999')
            self.assertNotIn('Unterhalt überschritten', self._texte())
            self.assertNotIn('budget', zeilen([self.lg])[0]['kategorien'])

    def test_ueberschrittenes_budget_ist_kritisch(self):
        with mandant(self.a.organisation):
            self._budget('10000')
            self._unterhalt('12000')
            zeile = zeilen([self.lg])[0]
            self.assertIn('Unterhalt überschritten', [c[1] for c in zeile['chips']])
            self.assertEqual(zeile['stufe'], 'crit')
            self.assertIn('budget', zeile['kategorien'])

    def test_budget_im_rahmen_meldet_nicht(self):
        """Gegenprobe — sonst stuende die Meldung immer da."""
        with mandant(self.a.organisation):
            self._budget('100000')
            self._unterhalt('500')
            self.assertNotIn('Unterhalt', ' '.join(self._texte()))

    def test_die_meldung_nennt_zahlen_und_restjahr(self):
        """«34'800 von 31'000» ist eine Zahl. «bei vier Monaten Restjahr» ist
        eine Aussage — im Februar waeren 60 % alarmierend, im November nicht.
        """
        with mandant(self.a.organisation):
            self._budget('10000')
            self._unterhalt('12000')
            chip = next(c for c in self._chips() if c[1].startswith('Unterhalt'))
            titel = chip[3]
            self.assertIn("12'000", titel)
            self.assertIn("10'000", titel)
            self.assertTrue('Restjahr' in titel or 'Jahr fast vorbei' in titel, titel)

    def test_kreditorenrechnungen_zaehlen_mit(self):
        """Unterhalt wird in diesem Haus auf ZWEI Wegen erfasst.

        Nur `Unterhalt`-Eintraege zu zaehlen hiesse, je nach Arbeitsweise die
        Haelfte zu uebersehen — viele Verwaltungen buchen Handwerkerrechnungen
        ausschliesslich als Kreditor.
        """
        from finance.models import KreditorenRechnung
        with mandant(self.a.organisation):
            self._budget('1000')
            KreditorenRechnung.objects.create(
                liegenschaft=self.lg, datum=HEUTE, betrag=Decimal('5000'),
                lieferant='Sanitär Meier AG')
            self.assertIn('Unterhalt überschritten', self._texte())

    def test_stornierte_kreditoren_zaehlen_nicht(self):
        """Gegenprobe: Eine stornierte Rechnung ist kein Aufwand."""
        from finance.models import KreditorenRechnung
        with mandant(self.a.organisation):
            self._budget('1000')
            KreditorenRechnung.objects.create(
                liegenschaft=self.lg, datum=HEUTE, betrag=Decimal('5000'),
                lieferant='Storniert AG', status='storniert')
            self.assertNotIn('Unterhalt', ' '.join(self._texte()))

    def test_unterhalt_aus_dem_vorjahr_zaehlt_nicht(self):
        """Das Budget gilt fuer EIN Jahr. Rechnete der Befund ueber alle Jahre,
        waere jede aeltere Liegenschaft dauerhaft «überschritten»."""
        with mandant(self.a.organisation):
            self._budget('1000')
            self._unterhalt('9000', datum=date(HEUTE.year - 1, 6, 1))
            self.assertNotIn('Unterhalt', ' '.join(self._texte()))

    def test_budget_eines_anderen_jahres_greift_nicht(self):
        with mandant(self.a.organisation):
            self._budget('1000', jahr=HEUTE.year - 1)
            self._unterhalt('9000')
            self.assertNotIn('Unterhalt', ' '.join(self._texte()))

    def test_budget_null_meldet_nie(self):
        """Ein Budget von 0 ist keine Vorgabe, sondern eine offene Frage —
        und eine Division dadurch waere ein Absturz."""
        with mandant(self.a.organisation):
            self._budget('0')
            self._unterhalt('5000')
            self.assertNotIn('Unterhalt', ' '.join(self._texte()))

    def test_je_liegenschaft_und_jahr_nur_eines(self):
        from django.db.utils import IntegrityError
        from portfolio.models import Liegenschaftsbudget
        with mandant(self.a.organisation):
            self._budget('1000')
            with self.assertRaises(IntegrityError):
                Liegenschaftsbudget.objects.create(
                    liegenschaft=self.lg, jahr=HEUTE.year, unterhalt=Decimal('2000'))


class AbfragezahlTests(_Basis):
    """Der Befund laeuft bei JEDEM Aufruf der Liegenschaftsliste mit.

    Drei Abfragen fuer das ganze Portfolio (Budgets, Unterhalt, Kreditoren) —
    nicht drei je Zeile.
    """

    def test_zehn_liegenschaften_kosten_nicht_mehr_abfragen_als_eine(self):
        from portfolio.models import Liegenschaft, Liegenschaftsbudget
        with mandant(self.a.organisation):
            for i in range(10):
                lg = Liegenschaft.objects.create(
                    strasse=f'Budget-Weg {i}', plz='8000', ort='Zürich',
                    organisation=self.a.organisation, eigentuemer=self.a.eigentuemer)
                Liegenschaftsbudget.objects.create(
                    liegenschaft=lg, jahr=HEUTE.year, unterhalt=Decimal('1000'))
            liste = list(Liegenschaft.objects.all())
            with self.assertNumQueries(9):
                rows = zeilen(liste)
        self.assertEqual(len(rows), 11)


class AkteTests(_Basis):

    def setUp(self):
        super().setUp()
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _akte(self):
        return self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode()

    def test_akte_und_liste_sagen_dasselbe(self):
        """Zwei getrennte Rechnungen waeren die Stelle, an der Liste und Akte
        auseinanderlaufen — und dann weiss niemand, welcher Seite zu trauen ist.
        """
        with mandant(self.a.organisation):
            self._budget('1000')
            self._unterhalt('9000')
            akte = self._akte()
            liste = self.c.get('/neu/liegenschaften/').content.decode()
        self.assertIn('Was auffällt', akte)
        self.assertIn('Unterhalt überschritten', akte)
        self.assertIn('Unterhalt überschritten', liste)

    def test_die_akte_nennt_auch_die_zahlen(self):
        with mandant(self.a.organisation):
            self._budget('1000')
            self._unterhalt('9000')
            akte = self._akte()
        self.assertIn("9'000", akte)

    def test_ohne_budget_sagt_die_kennzahl_das_auch(self):
        """Geprueft wird die KENNZAHLENLEISTE, nicht die ganze Seite.

        «Bruttorendite» steht weiterhin im Reiter Finanzen — dort zu Recht, das
        ist eine Auswertung. Aus dem Aktenkopf ist sie gewichen, weil eine
        Renditezahl, die mangels Verkehrswert «—» anzeigt, dort nur Platz
        kostet. Wer auf der ganzen Seite suchte, faende sie weiterhin und
        haette einen Test, der aus dem falschen Grund rot ist.
        """
        with mandant(self.a.organisation):
            akte = self._akte()
        kzn = _kennzahlenleiste(akte)
        self.assertIn('kein Budget', kzn)
        self.assertIn('Unterhalt', kzn)
        self.assertNotIn('Bruttorendite', kzn)

    def test_die_bruttorendite_steht_weiterhin_im_reiter_finanzen(self):
        """Gegenprobe zur vorigen Pruefung: Sie ist gewichen, nicht geloescht."""
        with mandant(self.a.organisation):
            akte = self._akte()
        self.assertNotIn('Bruttorendite', _kennzahlenleiste(akte))
        self.assertIn('Bruttorendite', akte)

    def test_mit_budget_steht_der_stand_in_der_kennzahl(self):
        with mandant(self.a.organisation):
            self._budget('10000')
            self._unterhalt('2500')
            kzn = _kennzahlenleiste(self._akte())
        self.assertIn("2'500", kzn)
        self.assertIn("10'000", kzn)

    def test_der_waechter_schneidet_nicht_zu_viel_weg(self):
        """Gegenprobe zur Gegenprobe: Faende `_kennzahlenleiste` nichts, waeren
        alle Pruefungen darauf aus dem falschen Grund gruen."""
        with mandant(self.a.organisation):
            kzn = _kennzahlenleiste(self._akte())
        self.assertIn('Vermietung', kzn)
        self.assertGreater(len(kzn), 200)


def _kennzahlenleiste(html):
    """Nur die Kennzahlenleiste des Aktenkopfs, ohne den Rest der Seite."""
    start = html.index('class="fw-kzn"')
    return html[start:html.index('class="fw-reiter"', start)]


class ErfassenTests(_Basis):
    """Erfasst wird in der LIEGENSCHAFTSAKTE, Reiter Finanzen.

    Im Reiter Finanzen, nicht in den Stammdaten: Ein Budget ist eine Planzahl,
    kein Stammdatum. Und in der Akte, nicht in den Mandatseinstellungen — wer
    das Budget setzt, schaut gerade auf diese Liegenschaft.
    """

    def setUp(self):
        super().setUp()
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _speichern(self, **daten):
        felder = {'jahr': HEUTE.year, 'unterhalt': '31000'}
        felder.update(daten)
        return self.c.post(f'/neu/liegenschaften/{self.lg.id}/budget/', felder)

    def _gespeichert(self):
        from portfolio.models import Liegenschaftsbudget
        return Liegenschaftsbudget.objects.filter(liegenschaft=self.lg)

    def test_das_formular_steht_in_der_akte(self):
        with mandant(self.a.organisation):
            akte = self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode()
        self.assertIn(f'/neu/liegenschaften/{self.lg.id}/budget/', akte)
        self.assertIn('Unterhaltsbudget', akte)

    def test_budget_wird_gespeichert(self):
        with mandant(self.a.organisation):
            self._speichern()
            self.assertEqual(self._gespeichert().get().unterhalt, Decimal('31000'))

    def test_zweite_eingabe_ueberschreibt_statt_zu_scheitern(self):
        """Wer das Budget eintippt, will es SETZEN — nicht anlegen.

        Die Datenbank laesst je Liegenschaft und Jahr nur eines zu. Ein Fehler
        statt einer Korrektur waere hier die falsche Antwort.
        """
        with mandant(self.a.organisation):
            self._speichern(unterhalt='31000')
            self._speichern(unterhalt='35000')
            self.assertEqual(self._gespeichert().count(), 1)
            self.assertEqual(self._gespeichert().get().unterhalt, Decimal('35000'))

    def test_schweizer_schreibweise_wird_verstanden(self):
        """«31'000.00» ist die Form, die auf derselben Seite ausgegeben wird.
        Wer sie zurueckkopiert, darf nicht scheitern."""
        with mandant(self.a.organisation):
            self._speichern(unterhalt="31'000.00")
            self.assertEqual(self._gespeichert().get().unterhalt, Decimal('31000.00'))

    def test_unsinn_wird_abgewiesen(self):
        with mandant(self.a.organisation):
            for feld in ({'unterhalt': 'keine Ahnung'}, {'unterhalt': '-500'},
                         {'jahr': 1800}, {'jahr': 'bald'}):
                with self.subTest(**feld):
                    self._speichern(**feld)
                    self.assertFalse(self._gespeichert().exists(), feld)

    def test_get_legt_nichts_an(self):
        """Ein Aufruf per Adresszeile darf nichts veraendern — auch MIT Werten.

        BEFUND ZUR GEGENPROBE: Das Entfernen der `if request.method != 'POST'`-
        Schranke laesst diesen Test gruen. Der Grund ist nicht ein schwacher
        Test, sondern dass die View aus `request.POST` liest, und das ist bei
        GET leer. Die Schranke ist doppelter Boden, keine tragende Regel; die
        Mutation sagt deshalb nichts. Der Test bleibt trotzdem: Er sichert das
        VERHALTEN zu, gleich welche der beiden Sperren es kuenftig traegt.
        """
        with mandant(self.a.organisation):
            self.c.get(f'/neu/liegenschaften/{self.lg.id}/budget/',
                       {'jahr': HEUTE.year, 'unterhalt': '31000'})
            self.assertFalse(self._gespeichert().exists())

    def test_loeschen_laesst_den_befund_verstummen(self):
        """Ohne Loeschen liesse sich ein versehentliches Budget nie
        zuruecknehmen — und der Befund meldet nur, WEIL eines da ist."""
        with mandant(self.a.organisation):
            self._speichern(unterhalt='1000')
            self._unterhalt('9000')
            self.assertIn('Unterhalt überschritten', self._texte())

            b = self._gespeichert().get()
            self.c.post(f'/neu/budget/{b.id}/loeschen/')
            self.assertFalse(self._gespeichert().exists())
            self.assertNotIn('Unterhalt überschritten', self._texte())

    def test_loeschen_per_get_loescht_nicht(self):
        with mandant(self.a.organisation):
            self._speichern()
            b = self._gespeichert().get()
            self.c.get(f'/neu/budget/{b.id}/loeschen/')
            self.assertTrue(self._gespeichert().exists())


class TrennungTests(TestCase):
    """Budgetzahlen sind Geschaeftszahlen des Mandanten.

    Die Pruefungen muessen rot werden, wenn die Isolation faellt — deshalb
    versuchen sie den Zugriff AKTIV, statt nur zu zaehlen, was sichtbar ist.
    Und sie erwarten **404, nicht 403**: Ein 403 bestaetigt die Existenz des
    Datensatzes und erlaubt, ueber fortlaufende Ids den Bestand eines
    Wettbewerbers abzuzaehlen.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.b.benutzer)

    def test_b_kann_das_budget_von_a_nicht_setzen(self):
        """Die gefaehrlichste Variante — fremde Zahlen ueberschreiben."""
        from portfolio.models import Liegenschaftsbudget
        lg_a = self.a.liegenschaft
        with mandant(self.b.organisation):
            antwort = self.c.post(f'/neu/liegenschaften/{lg_a.id}/budget/',
                                  {'jahr': HEUTE.year, 'unterhalt': '99999'})
        self.assertEqual(antwort.status_code, 404)
        with mandant(self.a.organisation):
            b = Liegenschaftsbudget.objects.filter(liegenschaft=lg_a).first()
            self.assertNotEqual(b and b.unterhalt, Decimal('99999'))

    def test_b_kann_das_budget_von_a_nicht_loeschen(self):
        from portfolio.models import Liegenschaftsbudget
        fremdes = self.a.budget
        with mandant(self.b.organisation):
            antwort = self.c.post(f'/neu/budget/{fremdes.id}/loeschen/')
        self.assertEqual(antwort.status_code, 404)
        with mandant(self.a.organisation):
            self.assertTrue(
                Liegenschaftsbudget.objects.filter(id=fremdes.id).exists())

    def test_a_kann_das_eigene_sehr_wohl(self):
        """Gegenprobe: Ohne sie waere die Isolation auch dann gruen, wenn die
        View schlicht jeden Zugriff mit 404 abwiese."""
        from portfolio.models import Liegenschaftsbudget
        lg_a = self.a.liegenschaft
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            c.post(f'/neu/liegenschaften/{lg_a.id}/budget/',
                   {'jahr': HEUTE.year, 'unterhalt': '99999'})
            self.assertEqual(
                Liegenschaftsbudget.objects.get(liegenschaft=lg_a, jahr=HEUTE.year
                                                ).unterhalt, Decimal('99999'))

    def test_der_befund_von_a_faerbt_die_zeile_von_b_nicht_ein(self):
        from portfolio.models import Liegenschaft, Liegenschaftsbudget, Unterhalt
        with mandant(self.a.organisation):
            Liegenschaftsbudget.objects.update_or_create(
                liegenschaft=self.a.liegenschaft, jahr=HEUTE.year,
                defaults={'unterhalt': Decimal('100')})
            Unterhalt.objects.create(liegenschaft=self.a.liegenschaft,
                                     titel='Dach', datum=HEUTE,
                                     kosten=Decimal('9000'))
        with mandant(self.b.organisation):
            rows = zeilen(list(Liegenschaft.objects.all()))
        texte = [c[1] for r in rows for c in r['chips']]
        self.assertNotIn('Unterhalt überschritten', texte)
