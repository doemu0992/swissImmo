"""Eine Organisation entsteht — und niemand sieht dabei die Daten der anderen.

WAS HIER SCHARF SEIN MUSS

Dieser Dienst legt den Mandanten selbst an. Er ist damit die einzige Stelle
im Bestand, die ausserhalb jedes Mandantenkontexts beginnt — vorher gibt es
die Organisation ja nicht, zu der ein Kontext gehören könnte.

Der Skill `mandantentrennung` verlangt für jede Änderung mindestens einen
Test, der den Zugriff über die Grenze **aktiv versucht**. Bei einem Dienst,
der Mandanten erzeugt, heisst das zweierlei: Die neue Organisation darf
nichts von den bestehenden sehen, und die bestehenden nichts von ihr.
"""
from datetime import date

from django.test import TestCase

from core.services.onboarding import (TESTPHASE_TAGE, OnboardingFehler,
                                      organisation_anlegen)
from core.tenancy import organisation_kontext as mandant


class AnlegenTests(TestCase):

    def test_organisation_inhaber_und_mitgliedschaft_entstehen_zusammen(self):
        from crm.models import Mitgliedschaft

        org, benutzer, neu = organisation_anlegen(
            firma='Muster Immobilien AG', benutzername='lea',
            email='lea@muster.ch')

        self.assertTrue(neu)
        self.assertEqual(org.firma, 'Muster Immobilien AG')
        with mandant(org):
            m = Mitgliedschaft.objects.get(benutzer=benutzer, organisation=org)
        self.assertEqual(m.rolle, Mitgliedschaft.ROLLE_INHABER)

    def test_der_inhaber_traegt_auch_die_gruppe(self):
        """Mitgliedschaft ist die Zugehörigkeit, die Gruppe sind die Rechte.

        Wer nur eines setzt, baut einen Inhaber, der nichts darf —
        `core/auth.py` prüft über die Gruppe.
        """
        from crm.models import Mitgliedschaft

        _org, benutzer, _neu = organisation_anlegen(
            firma='Muster AG', benutzername='lea', email='lea@muster.ch')
        self.assertIn(Mitgliedschaft.ROLLE_INHABER,
                      list(benutzer.groups.values_list('name', flat=True)))

    def test_die_testphase_steht_als_datum(self):
        org, _b, _n = organisation_anlegen(
            firma='Muster AG', benutzername='lea', email='lea@muster.ch',
            heute=date(2026, 9, 20))
        self.assertEqual(org.abo_start, date(2026, 9, 20))
        self.assertEqual((org.abo_bis - org.abo_start).days, TESTPHASE_TAGE)

    def test_ohne_testphase_bleibt_das_ende_offen(self):
        org, _b, _n = organisation_anlegen(
            firma='Muster AG', benutzername='lea', email='lea@muster.ch',
            testphase_tage=None)
        self.assertIsNone(org.abo_bis)

    def test_ein_bestehender_benutzer_wird_wiederverwendet(self):
        """Derselbe Mensch kann für zwei Verwaltungen arbeiten — das ist der
        Grund, warum `Mitgliedschaft` ein eigenes Modell ist."""
        from django.contrib.auth import get_user_model

        a, benutzer_a, neu_a = organisation_anlegen(
            firma='Erste AG', benutzername='lea', email='lea@erste.ch',
            passwort='geheim-123')
        hash_vorher = benutzer_a.password

        b, benutzer_b, neu_b = organisation_anlegen(
            firma='Zweite AG', benutzername='lea', email='lea@zweite.ch')

        self.assertTrue(neu_a)
        self.assertFalse(neu_b, 'Der Benutzer wurde ein zweites Mal angelegt.')
        self.assertEqual(benutzer_a.pk, benutzer_b.pk)
        self.assertNotEqual(a.pk, b.pk)
        # Das Passwort bleibt, wie es ist — sonst sperrt das Anlegen einer
        # zweiten Organisation jemanden aus seiner ersten aus.
        self.assertEqual(
            get_user_model().objects.get(pk=benutzer_a.pk).password, hash_vorher)

    def test_ohne_firma_ohne_benutzer_ohne_email_entsteht_nichts(self):
        from crm.models import Organisation

        for kwargs in ({'firma': '  ', 'benutzername': 'lea', 'email': 'a@b.ch'},
                       {'firma': 'AG', 'benutzername': '', 'email': 'a@b.ch'},
                       {'firma': 'AG', 'benutzername': 'lea', 'email': ''}):
            with self.subTest(**kwargs):
                with self.assertRaises(OnboardingFehler):
                    organisation_anlegen(**kwargs)
        self.assertEqual(Organisation.objects.count(), 0,
                         'Es ist eine Organisation zurückgeblieben.')

    def test_bricht_etwas_ab_bleibt_keine_waise(self):
        """Eine Organisation ohne Inhaber gehört niemandem.

        Gegenprobe zur `transaction.atomic`-Klammer: Schlägt das Anlegen der
        Mitgliedschaft fehl, darf die Organisation nicht zurückbleiben.
        """
        from unittest.mock import patch

        from crm.models import Organisation

        with patch('crm.models.Mitgliedschaft.objects.update_or_create',
                   side_effect=RuntimeError('Abbruch mitten im Vorgang')):
            with self.assertRaises(RuntimeError):
                organisation_anlegen(firma='Muster AG', benutzername='lea',
                                     email='lea@muster.ch')
        self.assertEqual(Organisation.objects.count(), 0,
                         'Die Organisation blieb ohne Inhaber zurück — eine '
                         'Waise, die niemandem gehört.')


class IsolationTests(TestCase):
    """Der Zugriff über die Grenze, aktiv versucht."""

    def test_die_neue_organisation_sieht_nichts_von_der_bestehenden(self):
        from core.tests._isolation import MandantenFixture
        from portfolio.models import Liegenschaft

        alt = MandantenFixture('A', '8000', 'Zürich')
        neu, _b, _n = organisation_anlegen(
            firma='Neue AG', benutzername='neu', email='neu@neu.ch')

        # ZUERST BELEGEN, DASS ES ETWAS ZU SEHEN GÄBE. Ohne diese Zeile
        # bestünde der Test auch auf einem leeren Bestand — und prüfte dann
        # nichts ausser, dass 0 gleich 0 ist.
        with mandant(alt.organisation):
            self.assertGreater(Liegenschaft.objects.count(), 0)

        with mandant(neu):
            self.assertEqual(Liegenschaft.objects.count(), 0,
                             'Die frische Organisation sieht fremde '
                             'Liegenschaften.')
            self.assertEqual(
                Liegenschaft.objects.filter(pk=alt.liegenschaft.pk).count(), 0)

    def test_die_bestehende_sieht_nichts_von_der_neuen(self):
        from core.tests._isolation import MandantenFixture
        from crm.models import Mitgliedschaft

        alt = MandantenFixture('A', '8000', 'Zürich')
        neu, benutzer, _n = organisation_anlegen(
            firma='Neue AG', benutzername='neu', email='neu@neu.ch')

        # Die Mitgliedschaft gibt es — im Kontext ihrer eigenen Organisation.
        # Ohne diesen Beleg prüfte der Test unten eine Abwesenheit, die auch
        # dann bestünde, wenn gar nichts angelegt worden wäre.
        with mandant(neu):
            self.assertTrue(
                Mitgliedschaft.objects.filter(benutzer=benutzer).exists())

        with mandant(alt.organisation):
            self.assertFalse(
                Mitgliedschaft.objects.filter(benutzer=benutzer).exists(),
                'Die bestehende Organisation sieht die Mitgliedschaft der '
                'neuen.')

    def test_der_neue_inhaber_ist_nur_in_seiner_organisation_inhaber(self):
        """Die Rolle gilt je Organisation, nicht global.

        Sonst wäre jeder neue Kunde Inhaber überall — der Fehler, gegen den
        `crm.Mitgliedschaft` als eigenes Modell gebaut wurde.
        """
        from core.tests._isolation import MandantenFixture
        from crm.models import Mitgliedschaft

        alt = MandantenFixture('A', '8000', 'Zürich')
        neu, benutzer, _n = organisation_anlegen(
            firma='Neue AG', benutzername='neu', email='neu@neu.ch')

        # Er IST Inhaber — aber nur bei sich.
        self.assertTrue(
            Mitgliedschaft.alle_organisationen.filter(
                benutzer=benutzer, organisation=neu,
                rolle=Mitgliedschaft.ROLLE_INHABER).exists())
        self.assertFalse(
            Mitgliedschaft.alle_organisationen.filter(
                benutzer=benutzer, organisation=alt.organisation).exists())


class CommandTests(TestCase):

    def _lauf(self, **kwargs):
        from io import StringIO

        from django.core.management import call_command

        aus = StringIO()
        call_command('organisation_anlegen', stdout=aus, **kwargs)
        return aus.getvalue()

    def test_der_erste_lauf_legt_an(self):
        from crm.models import Organisation

        text = self._lauf(firma='Muster AG', benutzer='lea', email='lea@m.ch')
        self.assertIn('angelegt', text)
        self.assertEqual(Organisation.objects.count(), 1)

    def test_eine_zweite_organisation_verlangt_eine_zweite_eingabe(self):
        """Die harte Grenze aus PHASE-2-ABSCHLUSS steht im Weg, nicht im Text.

        Eine Warnung, die man übergehen kann, ist keine.
        """
        from django.core.management.base import CommandError

        from crm.models import Organisation

        self._lauf(firma='Erste AG', benutzer='lea', email='lea@m.ch')
        with self.assertRaises(CommandError) as gefangen:
            self._lauf(firma='Zweite AG', benutzer='max', email='max@m.ch')
        self.assertIn('PostgreSQL', str(gefangen.exception))
        self.assertEqual(Organisation.objects.count(), 1)

        # Mit der ausdrücklichen Bestätigung geht es.
        self._lauf(firma='Zweite AG', benutzer='max', email='max@m.ch', zweite=True)
        self.assertEqual(Organisation.objects.count(), 2)

    def test_der_probelauf_legt_nichts_an(self):
        from crm.models import Organisation

        text = self._lauf(firma='Muster AG', benutzer='lea', email='lea@m.ch',
                          probe=True)
        self.assertIn('Probelauf', text)
        self.assertEqual(Organisation.objects.count(), 0)
