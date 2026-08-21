"""Der Anzeigestatus eines Mietvertrags — und die Vertragsliste.

WORUM ES GEHT

Ein Live-Befund zeigte auf der alten Startseite eine Statussumme von 4 statt
5 Objekten: Ein gekündigter Vertrag mit abgelaufenem Ende wurde zugleich als
«gekündigt» und als «beendet» gezählt. Die Regel «gekündigt plus Ende vorbei
= beendet» wurde damals **nur in jener Kachel** angewandt. Die Vertragsliste
zählte weiter roh nach `status`; wer dort auf «Gekündigt» klickte, sah den
abgelaufenen Vertrag wieder mit.

Mit dem Wegfall der Kachel (Phase 4b.13) verlor die Regel ihren Ort. Sie
steht jetzt in `Mietvertrag.anzeige_status` — an einer Stelle, für jeden
Aufrufer.

WAS DIESE TESTS SICHERN

1. Die Regel greift **im Modell**, nicht in einer View. Wer sie in einer
   zweiten View nachbaut, hat sie schon wieder verdoppelt.
2. `status` bleibt **unangetastet**. Er sagt, was verfügt wurde;
   `anzeige_status` sagt, was heute gilt. Beides zu verschmelzen hiesse, die
   Kündigung aus der Geschichte zu löschen — und die Sollstellung läuft
   bewusst weiter nach `status` (Befund H4).
3. Liste und Akte sagen **dasselbe**. Ein Widerspruch zwischen beiden wäre
   schlimmer als die ursprüngliche Ungenauigkeit — man wüsste nicht, welcher
   Seite zu trauen ist.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture


class AnzeigeStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _vertrag(self, status, ende=None):
        v = self.a.vertrag
        v.status = status
        v.ende = ende
        v.save(update_fields=['status', 'ende', 'aktiv'])
        return v

    def test_laufende_kuendigung_bleibt_gekuendigt(self):
        v = self._vertrag('gekuendigt', timezone.localdate() + timedelta(days=40))
        self.assertEqual(v.anzeige_status, 'gekuendigt')
        self.assertFalse(v.ist_beendet)

    def test_kuendigung_ohne_enddatum_bleibt_gekuendigt(self):
        """Ohne Ende ist nichts abgelaufen — und schon gar nicht beendet."""
        v = self._vertrag('gekuendigt', None)
        self.assertEqual(v.anzeige_status, 'gekuendigt')

    def test_abgelaufene_kuendigung_gilt_als_beendet(self):
        """Der eigentliche Fall — die Regel, die ihren Ort verloren hatte."""
        v = self._vertrag('gekuendigt', timezone.localdate() - timedelta(days=1))
        self.assertEqual(v.anzeige_status, 'beendet')
        self.assertTrue(v.ist_beendet)

    def test_am_letzten_tag_noch_nicht_beendet(self):
        """Grenzfall: Am Endtag selbst läuft das Verhältnis noch.

        `<` und nicht `<=`. Ein Mietverhältnis, das «per 31.03.» endet, endet
        am Abend des 31., nicht am Morgen.
        """
        v = self._vertrag('gekuendigt', timezone.localdate())
        self.assertEqual(v.anzeige_status, 'gekuendigt')

    def test_archiviert_ist_immer_beendet(self):
        v = self._vertrag('archiviert', timezone.localdate() + timedelta(days=90))
        self.assertEqual(v.anzeige_status, 'beendet')

    def test_der_gespeicherte_status_bleibt_unberuehrt(self):
        """`status` sagt, was verfügt wurde. Das darf die Anzeige nicht ändern."""
        v = self._vertrag('gekuendigt', timezone.localdate() - timedelta(days=5))
        self.assertEqual(v.anzeige_status, 'beendet')
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')

    def test_aktiver_vertrag_bleibt_aktiv(self):
        """Gegenprobe — sonst gälte alles mit Enddatum als beendet."""
        v = self._vertrag('aktiv', timezone.localdate() + timedelta(days=200))
        self.assertEqual(v.anzeige_status, 'aktiv')

    def test_die_regel_steht_im_modell_und_nicht_in_einer_view(self):
        """Sie hatte ihren Ort schon einmal verloren, weil sie in einer View
        stand. Wer sie dort wieder nachbaut, verdoppelt sie."""
        from rentals.models import Mietvertrag
        self.assertTrue(hasattr(Mietvertrag, 'anzeige_status'))
        self.assertTrue(hasattr(Mietvertrag, 'ist_beendet'))


class SollstellungBleibtUnberuehrt(TestCase):
    """Der Anzeigestatus darf die Verrechnung NICHT anfassen.

    Befund H4 hält fest: Ein gekündigter Vertrag wird bis zum Vertragsende
    weiter sollgestellt. Würde die Sollstellung auf `anzeige_status` umgestellt,
    fiele die letzte Monatsmiete aus — ein stiller Ertragsverlust.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_die_sollstellung_liest_weiterhin_status(self):
        import inspect

        from core.views.fw import sollstellung
        quelle = inspect.getsource(sollstellung)
        self.assertNotIn('anzeige_status', quelle,
                         'Die Sollstellung darf nicht nach dem Anzeigestatus '
                         'laufen — sonst faellt die letzte Monatsmiete eines '
                         'gekuendigten Vertrags aus (Befund H4).')


class ListenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _seite(self, pfad='/neu/vertraege/'):
        c = Client()
        c.force_login(self.a.benutzer)
        return c.get(pfad)

    def _abgelaufen(self):
        v = self.a.vertrag
        v.status = 'gekuendigt'
        v.ende = timezone.localdate() - timedelta(days=3)
        v.save(update_fields=['status', 'ende', 'aktiv'])
        return v

    def test_abgelaufener_vertrag_erscheint_nicht_unter_gekuendigt(self):
        """Genau das war der Fehler: der Filter lieferte ihn mit."""
        with mandant(self.a.organisation):
            v = self._abgelaufen()
            inhalt = self._seite('/neu/vertraege/?status=gekuendigt').content.decode()
        self.assertNotIn(f'/neu/vertraege/{v.id}/', inhalt)

    def test_er_erscheint_unter_beendet(self):
        """Gegenprobe: Er darf nicht einfach verschwinden."""
        with mandant(self.a.organisation):
            v = self._abgelaufen()
            inhalt = self._seite('/neu/vertraege/?status=beendet').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/', inhalt)

    def test_laufende_kuendigung_bleibt_im_filter_gekuendigt(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.status = 'gekuendigt'
            v.ende = timezone.localdate() + timedelta(days=30)
            v.save(update_fields=['status', 'ende', 'aktiv'])
            inhalt = self._seite('/neu/vertraege/?status=gekuendigt').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/', inhalt)

    def test_kuendigung_ohne_ende_bleibt_im_filter_gekuendigt(self):
        """Ohne Enddatum darf der `ende__gte`-Vergleich sie nicht wegfiltern."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.status = 'gekuendigt'
            v.ende = None
            v.save(update_fields=['status', 'ende', 'aktiv'])
            inhalt = self._seite('/neu/vertraege/?status=gekuendigt').content.decode()
        self.assertIn(f'/neu/vertraege/{v.id}/', inhalt)

    def test_die_liste_beschriftet_ihn_als_beendet(self):
        with mandant(self.a.organisation):
            self._abgelaufen()
            antwort = self._seite()
        self.assertContains(antwort, 'Beendet')

    def test_der_filter_beendet_steht_zur_auswahl(self):
        with mandant(self.a.organisation):
            antwort = self._seite()
        self.assertContains(antwort, 'status=beendet')

    def test_archiviert_taucht_nicht_als_zweiter_filter_auf(self):
        """Zwei Auswahlpunkte für dieselbe Sache sind ein Bedienfehler."""
        with mandant(self.a.organisation):
            inhalt = self._seite().content.decode()
        self.assertNotIn('status=archiviert', inhalt)

    def test_aktiv_zaehlt_abgelaufene_nicht_mit(self):
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.status = 'aktiv'
            v.ende = timezone.localdate() - timedelta(days=2)
            v.save(update_fields=['status', 'ende', 'aktiv'])
            inhalt = self._seite('/neu/vertraege/?status=aktiv').content.decode()
        self.assertNotIn(f'/neu/vertraege/{v.id}/', inhalt)


class AkteUndListeStimmenUeberein(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_die_akte_sagt_dasselbe_wie_die_liste(self):
        """Ein Widerspruch wäre schlimmer als die alte Ungenauigkeit."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.status = 'gekuendigt'
            v.ende = timezone.localdate() - timedelta(days=7)
            v.save(update_fields=['status', 'ende', 'aktiv'])
            c = Client()
            c.force_login(self.a.benutzer)
            akte = c.get(f'/neu/vertraege/{v.id}/').content.decode()
            liste = c.get('/neu/vertraege/').content.decode()
        self.assertIn('Beendet', akte)
        self.assertIn('Beendet', liste)
        # Und die Kündigung bleibt in den Stammdaten sichtbar — sie ist
        # geschehen, auch wenn der Vertrag heute beendet ist.
        v.refresh_from_db()
        self.assertEqual(v.status, 'gekuendigt')


class StatuspilleTests(TestCase):
    """`_vertrag_status_pill` ist ein ZWEITER Anzeigepfad.

    Er speist die Statuspille im Aktenkopf und die Zeilen der «Verhältnisse»
    auf der Objektakte. Eine Gegenprobe hat gezeigt, dass er sich unbemerkt
    auf den gespeicherten Status zurückstellen liess: Der Test, der die Akte
    als Ganzes las, fand «Beendet» über die Chips daneben und blieb grün.
    Zwei Wege, dasselbe anzuzeigen, brauchen zwei Prüfungen.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _pille(self, status, ende):
        from core.views.fw.detailseiten import _vertrag_status_pill
        v = self.a.vertrag
        v.status = status
        v.ende = ende
        v.save(update_fields=['status', 'ende', 'aktiv'])
        return _vertrag_status_pill(v)

    def test_abgelaufene_kuendigung_ergibt_die_pille_beendet(self):
        p = self._pille('gekuendigt', timezone.localdate() - timedelta(days=4))
        self.assertEqual(p['label'], 'Beendet')

    def test_laufende_kuendigung_ergibt_die_pille_gekuendigt(self):
        """Gegenprobe — sonst hiesse jede Kündigung «Beendet»."""
        p = self._pille('gekuendigt', timezone.localdate() + timedelta(days=20))
        self.assertEqual(p['label'], 'Gekündigt')

    def test_die_verhaeltnisse_der_objektakte_zeigen_dasselbe(self):
        """Der Weg, auf dem ein Benutzer die Pille wirklich sieht."""
        with mandant(self.a.organisation):
            v = self.a.vertrag
            v.status = 'gekuendigt'
            v.ende = timezone.localdate() - timedelta(days=4)
            v.save(update_fields=['status', 'ende', 'aktiv'])
            c = Client()
            c.force_login(self.a.benutzer)
            antwort = c.get(f'/neu/objekte/{v.einheit_id}/')
        self.assertContains(antwort, 'Beendet')


class TrennungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_der_filter_zeigt_keine_fremden_vertraege(self):
        """Ein neuer Filterzweig ist ein neuer Weg, fremde Daten zu zeigen."""
        with mandant(self.b.organisation):
            v = self.b.vertrag
            v.status = 'gekuendigt'
            v.ende = timezone.localdate() - timedelta(days=3)
            v.save(update_fields=['status', 'ende', 'aktiv'])
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            inhalt = c.get('/neu/vertraege/?status=beendet').content.decode()
        self.assertNotIn(f'/neu/vertraege/{v.id}/', inhalt)
