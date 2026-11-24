"""MWST-Periode ohne Betrag (Nullabrechnung) lässt sich abschliessen.

Gemeldet 24.11.2026: «MWST kann nicht abgeschlossen werden, wenn der Betrag gleich null ist.» Ob eine Periode verbucht
ist, las das Programm nur an der Ausbuchung von 2200 ab — ohne Betrag gibt es keine Buchung, die Periode blieb für immer
offen. Jetzt hält ein Vermerk (`finance.MwstAbschluss`) den Abschluss fest.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from core.tenancy import organisation_kontext
from crm.models import Organisation
from finance.models import Buchung, MwstAbschluss

from ._helfer import _basis_objekte, _team_user


class MwstNullabrechnungTests(TestCase):

    def setUp(self):
        from finance.booking import ensure_kontenplan
        self.lg, _e, _m, _v = _basis_objekte()
        ensure_kontenplan()
        self.c = Client()
        self.c.force_login(_team_user(rolle='Verwaltung'))

    def _abschliessen(self, **daten):
        return self.c.post('/neu/mwst/verbuchen/', {'jahr': '2024', 'quartal': '1', **daten}, follow=True)

    def test_periode_ohne_betrag_laesst_sich_abschliessen(self):
        seite = self.c.get('/neu/mwst/?jahr=2024&quartal=1')
        self.assertContains(seite, 'Periode abschliessen')            # der Knopf nennt, was geschieht
        self.assertNotContains(seite, 'Periode abgeschlossen')
        antwort = self._abschliessen()
        self.assertContains(antwort, 'Periode abgeschlossen')
        self.assertContains(antwort, 'Nullabrechnung')
        self.assertEqual(MwstAbschluss.objects.filter(jahr=2024, quartal='1').count(), 1)
        self.assertFalse(Buchung.objects.filter(beleg_text__startswith='MWST-Abrechnung').exists())   # keine Buchung

    def test_zweiter_klick_legt_keinen_zweiten_vermerk_an(self):
        self._abschliessen()
        antwort = self._abschliessen()
        self.assertContains(antwort, 'bereits verbucht')
        self.assertEqual(MwstAbschluss.objects.count(), 1)

    def test_jahr_und_quartal_ueberlappen_wie_bei_den_buchungen(self):
        """Ein abgeschlossenes Quartal sperrt den Jahresabschluss und umgekehrt (sonst doppelt)."""
        self._abschliessen()
        self.assertContains(self._abschliessen(quartal=''), 'bereits verbucht')
        self.assertEqual(MwstAbschluss.objects.count(), 1)
        self.assertNotContains(self.c.get('/neu/mwst/?jahr=2024&quartal=2'), 'Periode abgeschlossen')   # Q2 bleibt offen

    def test_abschluss_laesst_sich_wieder_aufheben(self):
        self._abschliessen()
        antwort = self._abschliessen(aufheben='1')
        self.assertContains(antwort, 'wieder offen')
        self.assertEqual(MwstAbschluss.objects.count(), 0)
        self.assertContains(self.c.get('/neu/mwst/?jahr=2024&quartal=1'), 'Periode abschliessen')

    def test_periode_mit_betrag_wird_weiter_verbucht_nicht_nur_vermerkt(self):
        from finance.booking import buche
        buche('1100', '2200', Decimal('810'), 'MWST Q1', datum=date(2024, 3, 31), liegenschaft=self.lg)
        seite = self.c.get('/neu/mwst/?jahr=2024&quartal=1')
        self.assertContains(seite, 'Abrechnung verbuchen')
        self._abschliessen()
        self.assertEqual(MwstAbschluss.objects.count(), 0)
        self.assertTrue(Buchung.objects.filter(beleg_text__startswith='MWST-Abrechnung 2024 Q1').exists())

    def test_der_vermerk_einer_anderen_verwaltung_schliesst_nichts_ab(self):
        """Mandantentrennung: Der Abschluss von Verwaltung B darf die Periode von Verwaltung A nicht als abgeschlossen
        zeigen — und A sieht ihn nicht."""
        fremd = Organisation.objects.create(firma='Fremde AG', strasse='Fremdweg 1', plz='3000', ort='Bern')
        with organisation_kontext(fremd):
            MwstAbschluss.objects.create(jahr=2024, quartal='1')
        self.assertEqual(MwstAbschluss.objects.count(), 0)                       # A sieht den fremden Vermerk nicht
        self.assertEqual(MwstAbschluss.alle_organisationen.count(), 1)
        seite = self.c.get('/neu/mwst/?jahr=2024&quartal=1')
        self.assertNotContains(seite, 'Periode abgeschlossen')
        self.assertContains(seite, 'Periode abschliessen')
        # A schliesst die eigene Periode ab; der fremde Vermerk bleibt unberührt, auch beim Aufheben
        self._abschliessen()
        self._abschliessen(aufheben='1')
        self.assertEqual(MwstAbschluss.alle_organisationen.filter(organisation=fremd).count(), 1)
