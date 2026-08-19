"""Tests der Läufe mit Zustand.

Der Zweck dieser Etappe ist eine einzige Eigenschaft: **Ein überfälliger Lauf
meldet sich von selbst.** Alles andere hier stützt nur diese Aussage ab.

Zwei Fehler wären teuer und werden deshalb einzeln geprüft:

1. Ein Lauf lässt sich abschliessen, obwohl eine Blockade offen ist. Er
   verschwindet dann aus dem Arbeitsvorrat, während die Ursache steht.
2. «Übersprungen» ist von «vergessen» nicht zu unterscheiden. Genau diese
   Unterscheidung ist der Zweck des Status.
"""
from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.lauf_models import Blockade, Lauf, Laufart
from faelle.management.commands.laeufe_planen import periode_fuer


def _art(org, schluessel='pruefungslauf', tag=15, rhythmus=Laufart.MONATLICH):
    a = Laufart(organisation=org, schluessel=schluessel, bezeichnung='Prüfung',
                rhythmus=rhythmus, faellig_am_tag=tag)
    a.save()
    return a


def _lauf(org, art, periode='2026-08', tage_zurueck=0):
    lauf = Lauf(organisation=org, laufart=art, periode=periode,
                faellig_am=timezone.localdate() - timedelta(days=tage_zurueck))
    lauf.save()
    return lauf


class _Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')


class UeberfaelligTests(_Basis):
    def test_lauf_vor_dem_faelligkeitstag_ist_nicht_ueberfaellig(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation),
                         tage_zurueck=-1)
            self.assertFalse(lauf.ist_ueberfaellig)

    def test_lauf_nach_dem_faelligkeitstag_ist_ueberfaellig(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation),
                         tage_zurueck=4)
            self.assertTrue(lauf.ist_ueberfaellig)
            self.assertEqual(lauf.tage_ueberfaellig, 4)

    def test_abgeschlossener_lauf_ist_nie_ueberfaellig(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation),
                         tage_zurueck=99)
            lauf.abschliessen()
            self.assertFalse(lauf.ist_ueberfaellig)

    def test_uebersprungener_lauf_ist_nie_ueberfaellig(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation),
                         tage_zurueck=99)
            lauf.ueberspringen('Keine offenen Posten in dieser Periode.')
            self.assertFalse(lauf.ist_ueberfaellig)

    def test_queryset_und_eigenschaft_stimmen_ueberein(self):
        """Zwei Wege zur selben Aussage — sie dürfen nicht auseinanderlaufen."""
        with mandant(self.a.organisation):
            for i, tage in enumerate((-2, 0, 3, 40)):
                _lauf(self.a.organisation, _art(self.a.organisation, f'art{i}'),
                      periode=f'2026-0{i+1}', tage_zurueck=tage)
            aus_query = set(Lauf.objects.ueberfaellig().values_list('pk', flat=True))
            aus_eigenschaft = {x.pk for x in Lauf.objects.all() if x.ist_ueberfaellig}
            self.assertEqual(aus_query, aus_eigenschaft)


class BlockadeTests(_Basis):
    def test_blockade_haelt_den_abschluss_auf(self):
        """Der wichtigste Test dieser Etappe.

        Ein Lauf, der sich trotz offener Blockade abschliessen liesse,
        verschwindet aus dem Arbeitsvorrat, während die Ursache steht.
        """
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            lauf.blockieren('Verbrauchsablesung fehlt', quelle='Techem')
            with self.assertRaises(ValueError) as fehler:
                lauf.abschliessen()
            self.assertIn('Verbrauchsablesung', str(fehler.exception))
            lauf.refresh_from_db()
            self.assertEqual(lauf.status, Lauf.OFFEN)

    def test_nach_behebung_laesst_er_sich_abschliessen(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            b = lauf.blockieren('Ablesung fehlt')
            b.beheben()
            lauf.abschliessen(positionen=178, summe='184250.00')
            self.assertEqual(lauf.status, Lauf.ABGESCHLOSSEN)
            self.assertEqual(lauf.kennzahlen['positionen'], 178)

    def test_dieselbe_blockade_wird_nicht_verdoppelt(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            erste = lauf.blockieren('Ablesung fehlt')
            zweite = lauf.blockieren('Ablesung fehlt')
            self.assertEqual(erste.pk, zweite.pk)
            self.assertEqual(lauf.offene_blockaden.count(), 1)

    def test_behobene_blockade_zaehlt_nicht_mehr(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            lauf.blockieren('Ablesung fehlt').beheben()
            self.assertFalse(lauf.ist_blockiert)
            self.assertNotIn(lauf, Lauf.objects.blockiert())

    def test_beheben_ist_idempotent(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            b = lauf.blockieren('Ablesung fehlt')
            b.beheben()
            erstes = b.behoben_am
            b.beheben()
            self.assertEqual(b.behoben_am, erstes)

    def test_grund_bleibt_lesbar(self):
        """Klartext statt Schlüssel — er wird gelesen, nicht ausgewertet."""
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            b = lauf.blockieren('7 Zahlungseingänge ohne Zuordnung', quelle='Bankabgleich')
            self.assertEqual(str(b), '7 Zahlungseingänge ohne Zuordnung')


class UeberspringenTests(_Basis):
    def test_ueberspringen_braucht_eine_begruendung(self):
        """Sonst ist «übersprungen» von «vergessen» nicht zu unterscheiden."""
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            for leer in ('', '   ', None):
                with self.subTest(bemerkung=leer):
                    with self.assertRaises(ValueError):
                        lauf.ueberspringen(leer)
            lauf.refresh_from_db()
            self.assertEqual(lauf.status, Lauf.OFFEN)

    def test_begruendung_wird_festgehalten(self):
        with mandant(self.a.organisation):
            lauf = _lauf(self.a.organisation, _art(self.a.organisation))
            lauf.ueberspringen('Mandat erst ab September aktiv.')
            self.assertEqual(lauf.status, Lauf.UEBERSPRUNGEN)
            self.assertIn('September', lauf.bemerkung)


class PeriodenTests(TestCase):
    def test_monatlich(self):
        art = Laufart(rhythmus=Laufart.MONATLICH)
        self.assertEqual(periode_fuer(art, date(2026, 8, 19)), '2026-08')

    def test_quartalsweise_nur_im_quartalsmonat(self):
        art = Laufart(rhythmus=Laufart.QUARTALSWEISE)
        self.assertEqual(periode_fuer(art, date(2026, 10, 5)), '2026-Q4')
        self.assertIsNone(periode_fuer(art, date(2026, 8, 5)))

    def test_jaehrlich_rechnet_das_vorjahr_ab(self):
        """Die Nebenkostenabrechnung 2025 wird im September 2026 fällig."""
        art = Laufart(rhythmus=Laufart.JAEHRLICH)
        self.assertEqual(periode_fuer(art, date(2026, 9, 1)), '2025')
        self.assertIsNone(periode_fuer(art, date(2026, 8, 1)))


class PlanungTests(_Basis):
    def test_befehl_legt_arten_und_perioden_an(self):
        call_command('laeufe_planen', periode='2026-08', verbosity=0)
        for org in (self.a.organisation, self.b.organisation):
            with self.subTest(org=org.pk):
                self.assertEqual(
                    Laufart.alle_organisationen.filter(organisation=org).count(), 6)
                # Im August: vier monatliche, kein Quartal, kein Jahreslauf.
                # Auf die geplante Periode eingegrenzt — das Mandantenfixture
                # bringt einen eigenen Lauf mit, und der gehoert nicht in diese
                # Zaehlung.
                self.assertEqual(
                    Lauf.alle_organisationen.filter(
                        organisation=org, periode='2026-08').count(), 4)

    def test_befehl_ist_idempotent(self):
        call_command('laeufe_planen', periode='2026-08', verbosity=0)
        vorher = (Laufart.alle_organisationen.count(),
                  Lauf.alle_organisationen.count())
        call_command('laeufe_planen', periode='2026-08', verbosity=0)
        self.assertEqual((Laufart.alle_organisationen.count(),
                          Lauf.alle_organisationen.count()), vorher)

    def test_im_quartalsmonat_kommt_die_mwst_dazu(self):
        call_command('laeufe_planen', periode='2026-10', verbosity=0)
        self.assertTrue(Lauf.alle_organisationen.filter(
            laufart__schluessel='mwst', periode='2026-Q4').exists())

    def test_im_september_kommt_die_nebenkostenabrechnung_dazu(self):
        call_command('laeufe_planen', periode='2026-09', verbosity=0)
        self.assertTrue(Lauf.alle_organisationen.filter(
            laufart__schluessel='nebenkosten', periode='2025').exists())

    def test_angepasster_faelligkeitstag_bleibt_erhalten(self):
        """Sonst verlöre eine Verwaltung ihre Einstellung beim nächsten Lauf."""
        call_command('laeufe_planen', periode='2026-08', verbosity=0)
        art = Laufart.alle_organisationen.filter(
            organisation=self.a.organisation, schluessel='mahnlauf').first()
        art.faellig_am_tag = 20
        art.save()
        call_command('laeufe_planen', periode='2026-09', verbosity=0)
        art.refresh_from_db()
        self.assertEqual(art.faellig_am_tag, 20)

    def test_entitlements_verweisen_auf_bekannte_schluessel(self):
        from core.funktionen import FUNKTIONEN, MODULE
        call_command('laeufe_planen', periode='2026-08', verbosity=0)
        for art in Laufart.alle_organisationen.all():
            with self.subTest(art=art.schluessel):
                self.assertIn(art.entitlement, {**FUNKTIONEN, **MODULE})


class MandantentrennungTests(_Basis):
    def setUp(self):
        with mandant(self.a.organisation):
            self.lauf_a = _lauf(self.a.organisation, _art(self.a.organisation),
                                tage_zurueck=10)
            self.lauf_a.blockieren('Nur für A')
        with mandant(self.b.organisation):
            self.lauf_b = _lauf(self.b.organisation, _art(self.b.organisation),
                                tage_zurueck=10)

    def test_b_sieht_den_lauf_von_a_nicht(self):
        with mandant(self.b.organisation):
            self.assertEqual(Lauf.objects.filter(pk=self.lauf_a.pk).count(), 0)

    def test_b_sieht_die_blockade_von_a_nicht(self):
        with mandant(self.a.organisation):
            blockade_a = self.lauf_a.blockaden.get(grund='Nur für A')
        with mandant(self.b.organisation):
            self.assertEqual(
                Blockade.objects.filter(pk=blockade_a.pk).count(), 0)

    def test_b_sieht_die_eigenen_sehr_wohl(self):
        """Gegenprobe: Ein leerer Manager bestünde sonst alle Trennungstests.

        Beide Verwaltungen führen Läufe — das Mandantenfixture legt für jede
        eine Laufart, einen Lauf und eine Blockade an. Der Fixture-Lauf ist
        bewusst nicht überfällig, deshalb zählt hier nur der eigene.
        """
        with mandant(self.b.organisation):
            self.assertEqual(Lauf.objects.filter(pk=self.lauf_b.pk).count(), 1)
            self.assertEqual(Lauf.objects.ueberfaellig().count(), 1)
            self.assertGreater(Blockade.objects.count(), 0)

    def test_ueberfaellige_von_a_erscheinen_nicht_bei_b(self):
        with mandant(self.b.organisation):
            pks = set(Lauf.objects.ueberfaellig().values_list('pk', flat=True))
            self.assertNotIn(self.lauf_a.pk, pks)

    def test_abgeleitete_organisation_stimmt(self):
        for modell in (Lauf, Blockade, Laufart):
            with self.subTest(modell=modell.__name__):
                fremde = modell.alle_organisationen.exclude(
                    organisation__in=[self.a.organisation, self.b.organisation])
                self.assertEqual(fremde.count(), 0)
