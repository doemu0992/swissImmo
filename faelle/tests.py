"""Tests der Fallmaschine.

Vier Dinge werden hier geprüft, und zwar getrennt, weil sie unterschiedlich
teuer scheitern:

1. **Mandantentrennung.** Ein Fall von A darf für B nicht existieren. Das ist
   die Bedingung, unter der diese App überhaupt gebaut werden durfte.
2. **Die Verfallsregel.** Sie ist der Grund für die ganze Maschine. Wenn sie
   nicht greift, ist ein Fall nur eine Zeile mehr.
3. **Idempotenz.** `schritte_anlegen()` und `fallarten_anlegen` laufen
   mehrfach — ein Doppelaufruf darf nichts verdoppeln.
4. **Die Aktenbindung.** Genau eine Akte, und nur aus der erlaubten Liste.
"""
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.models import Fall, Fallart, Fallschritt, SchrittVorlage, Zeiteintrag


def _fallart(org, schluessel='pruefvorgang', schritte=3):
    """Eigene Fallart für den Test.

    Der Schlüssel ist bewusst **nicht** einer der fünf Standardschlüssel: Das
    Mandantenfixture legt selbst einen `mieterwechsel` je Organisation an, und
    `(organisation, schluessel)` ist eindeutig. Ein Test, der sich an einem
    Produktivschlüssel bedient, kollidiert mit jedem Bestand, der ihn ebenfalls
    führt.
    """
    art = Fallart(organisation=org, schluessel=schluessel,
                  bezeichnung=schluessel.title())
    art.save()
    for nr in range(1, schritte + 1):
        SchrittVorlage(fallart=art, nr=nr, etappe_nr=1, etappe='Etappe',
                       bezeichnung=f'Schritt {nr}').save()
    return art


class FallartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_schritte_werden_aus_der_vorlage_erzeugt(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation, schritte=4)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            self.assertEqual(fall.schritte_anlegen(), 4)
            self.assertEqual(fall.schritte.count(), 4)

    def test_schritte_anlegen_ist_idempotent(self):
        """Ein Doppelaufruf darf keinen Fall mit acht statt vier Schritten hinterlassen."""
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation, schritte=4)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            fall.schritte_anlegen()
            self.assertEqual(fall.schritte_anlegen(), 0)
            self.assertEqual(fall.schritte.count(), 4)

    def test_bezeichnung_wird_kopiert_nicht_verlinkt(self):
        """Eine geänderte Vorlage darf laufende Fälle nicht rückwirkend ändern."""
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation, schritte=2)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            fall.schritte_anlegen()
            vorlage = art.schrittvorlagen.first()
            vorlage.bezeichnung = 'Ganz anders'
            vorlage.save()
            self.assertEqual(
                fall.schritte.order_by('nr').first().bezeichnung, 'Schritt 1',
                'Der Schritt hat sich mit der Vorlage geändert.')

    def test_fallnummer_wird_vergeben(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            self.assertRegex(fall.nummer, r'^F-\d{4}-\d{4}$')


class VerfallsregelTests(TestCase):
    """Die Regel, wegen der es die Maschine gibt."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _fall(self, tage, status=Fall.OFFEN):
        art = _fallart(self.a.organisation, schluessel=f'art{tage}{status}')
        fall = Fall(fallart=art, organisation=self.a.organisation, status=status)
        fall.save()
        Fall.alle_organisationen.filter(pk=fall.pk).update(
            letzte_bewegung=timezone.now() - timedelta(days=tage))
        return Fall.alle_organisationen.get(pk=fall.pk)

    def test_offener_fall_faellt_nach_14_tagen(self):
        with mandant(self.a.organisation):
            self.assertFalse(self._fall(13).ist_liegengeblieben)
            self.assertTrue(self._fall(14).ist_liegengeblieben)

    def test_wartender_fall_faellt_schon_nach_10_tagen(self):
        """Beim Warten auf Dritte ist das Nachfassen die Arbeit."""
        with mandant(self.a.organisation):
            self.assertFalse(self._fall(9, Fall.WARTET).ist_liegengeblieben)
            self.assertTrue(self._fall(10, Fall.WARTET).ist_liegengeblieben)

    def test_abgeschlossener_fall_faellt_nie(self):
        with mandant(self.a.organisation):
            self.assertFalse(self._fall(999, Fall.ABGESCHLOSSEN).ist_liegengeblieben)
            self.assertFalse(self._fall(999, Fall.ABGEBROCHEN).ist_liegengeblieben)

    def test_queryset_und_eigenschaft_stimmen_ueberein(self):
        """Zwei Implementierungen derselben Regel — sie dürfen nicht auseinanderlaufen."""
        with mandant(self.a.organisation):
            for tage, status in ((5, Fall.OFFEN), (14, Fall.OFFEN),
                                 (9, Fall.WARTET), (11, Fall.WARTET),
                                 (30, Fall.ABGESCHLOSSEN)):
                self._fall(tage, status)
            aus_query = set(Fall.objects.liegengeblieben().values_list('pk', flat=True))
            aus_eigenschaft = {f.pk for f in Fall.objects.all() if f.ist_liegengeblieben}
            self.assertEqual(aus_query, aus_eigenschaft)

    def test_erledigen_setzt_die_uhr_zurueck(self):
        with mandant(self.a.organisation):
            fall = self._fall(20)
            self.assertTrue(fall.ist_liegengeblieben)
            fall.schritte_anlegen()
            fall.schritte.first().erledigen()
            fall.refresh_from_db()
            self.assertFalse(fall.ist_liegengeblieben)


class MandantentrennungTests(TestCase):
    """Ein Fall von A existiert für B nicht.

    Die erste Fassung prüfte „B sieht **nichts**" (`Fall.objects.count() == 0`).
    Das ging nur so lange gut, wie das Mandantenfixture für B gar keine Fälle
    anlegte — also solange die Prüfung nichts zu unterscheiden hatte. Seit die
    Fallmaschine im Fixture steht, hat B eigene Fälle, und die Tests sagen
    jetzt, was sie meinen: **B sieht die eigenen und nie die von A.**

    Das ist die schärfere Aussage. „Leer" bestünde auch ein Manager, der
    versehentlich alles wegfiltert.
    """

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            self.fall_a = Fall(fallart=art, organisation=self.a.organisation)
            self.fall_a.save()
            self.fall_a.schritte_anlegen()
            Zeiteintrag(fall=self.fall_a, minuten=45).save()

    def test_b_sieht_den_fall_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(Fall.objects.filter(pk=self.fall_a.pk).count(), 0)

    def test_b_sieht_die_schritte_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(
                Fallschritt.objects.filter(fall=self.fall_a).count(), 0)

    def test_b_sieht_die_zeiteintraege_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(
                Zeiteintrag.objects.filter(fall=self.fall_a).count(), 0)

    def test_b_sieht_die_fallarten_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(
                Fallart.objects.filter(pk=self.fall_a.fallart_id).count(), 0)

    def test_b_sieht_dabei_die_eigenen_daten_sehr_wohl(self):
        """Die Gegenprobe zu den vier Tests darüber.

        Ohne sie bestünde ein Manager, der grundsätzlich nichts liefert, alle
        Trennungstests mit Bestnote — und die Anwendung wäre unbenutzbar.
        """
        with mandant(self.b.organisation):
            self.assertGreater(Fall.objects.count(), 0)
            self.assertGreater(Fallart.objects.count(), 0)

    def test_a_sieht_den_eigenen_fall(self):
        with mandant(self.a.organisation):
            self.assertEqual(Fall.objects.filter(pk=self.fall_a.pk).count(), 1)
            self.assertEqual(
                Fallschritt.objects.filter(fall=self.fall_a).count(), 3)
            self.assertEqual(
                Zeiteintrag.objects.filter(fall=self.fall_a).count(), 1)

    def test_abgeleitete_organisation_stimmt(self):
        """Die Kette muss die Organisation aus dem Fall ziehen, nicht raten."""
        for modell in (Fallschritt, Zeiteintrag):
            with self.subTest(modell=modell.__name__):
                self.assertEqual(
                    modell.alle_organisationen.filter(fall=self.fall_a).exclude(
                        organisation=self.a.organisation).count(), 0)


class AktenbindungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_unzulaessiger_aktentyp_wird_abgelehnt(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, organisation=self.a.organisation,
                        akte_typ=ContentType.objects.get_for_model(Fallart),
                        akte_id=art.pk)
            with self.assertRaises(ValidationError):
                fall.full_clean(exclude=['nummer', 'betreff', 'notiz'])

    def test_organisation_kommt_aus_der_akte(self):
        """Die Akte ist die genauere Quelle als der Kontext."""
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, akte=self.a.liegenschaft)
            fall.save()
            self.assertEqual(fall.organisation_id, self.a.organisation.pk)


class ZeiterfassungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_summe_je_fall(self):
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            Zeiteintrag(fall=fall, minuten=45).save()
            Zeiteintrag(fall=fall, minuten=90, taetigkeit=Zeiteintrag.SONDER,
                        verrechenbar=True).save()
            self.assertEqual(fall.erfasste_minuten, 135)

    def test_ohne_eintraege_null_statt_none(self):
        """`None` würde jede Rechnung damit zum Absturz bringen."""
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            self.assertEqual(fall.erfasste_minuten, 0)

    def test_null_minuten_werden_abgelehnt(self):
        from django.db.utils import IntegrityError
        with mandant(self.a.organisation):
            art = _fallart(self.a.organisation)
            fall = Fall(fallart=art, organisation=self.a.organisation)
            fall.save()
            with self.assertRaises(IntegrityError):
                Zeiteintrag(fall=fall, minuten=0).save()


class EinrichtungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_befehl_legt_fuer_jede_organisation_an(self):
        call_command('fallarten_anlegen', verbosity=0)
        for org in (self.a.organisation, self.b.organisation):
            with self.subTest(org=org.pk):
                self.assertEqual(
                    Fallart.alle_organisationen.filter(organisation=org).count(), 5)

    def test_befehl_ist_idempotent(self):
        call_command('fallarten_anlegen', verbosity=0)
        vorher = (Fallart.alle_organisationen.count(),
                  SchrittVorlage.alle_organisationen.count())
        call_command('fallarten_anlegen', verbosity=0)
        self.assertEqual(
            (Fallart.alle_organisationen.count(),
             SchrittVorlage.alle_organisationen.count()), vorher)

    def test_angepasste_vorlage_wird_nicht_zurueckgesetzt(self):
        """Sonst verlöre eine Verwaltung ihre Anpassung beim nächsten Lauf."""
        call_command('fallarten_anlegen', verbosity=0)
        vorlage = SchrittVorlage.alle_organisationen.filter(
            fallart__organisation=self.a.organisation).first()
        vorlage.bezeichnung = 'Von der Verwaltung angepasst'
        vorlage.save()
        call_command('fallarten_anlegen', verbosity=0)
        vorlage.refresh_from_db()
        self.assertEqual(vorlage.bezeichnung, 'Von der Verwaltung angepasst')

    def test_jede_fallart_hat_schritte(self):
        call_command('fallarten_anlegen', verbosity=0)
        for art in Fallart.alle_organisationen.all():
            with self.subTest(art=art.schluessel):
                self.assertGreater(
                    SchrittVorlage.alle_organisationen.filter(fallart=art).count(), 0)

    def test_entitlement_verweist_auf_bekannten_schluessel(self):
        from core.funktionen import FUNKTIONEN, MODULE
        call_command('fallarten_anlegen', verbosity=0)
        for art in Fallart.alle_organisationen.all():
            with self.subTest(art=art.schluessel):
                self.assertIn(art.entitlement, {**FUNKTIONEN, **MODULE},
                              'Fallart verweist auf einen Funktionsschlüssel, '
                              'den core.funktionen nicht kennt.')
