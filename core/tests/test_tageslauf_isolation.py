"""Ein Fehler in einer Verwaltung stoppt den Tageslauf der anderen nicht (SICH-05).

Der Tageslauf ruft `generate_auto_pendenzen` einmal für alle Verwaltungen. Bis
28.10.2026 stand der Aufruf ohne Fehlerschutz am Anfang: Eine defekte
Verwaltung brach den Befehl ab, und Marktdaten, Fristen-Mail und die Schleife je
Verwaltung entfielen für ALLE. Der Test baut genau diesen Defekt (Verwaltung A
wirft) und verlangt: B wird trotzdem bedient, der Fehler wird gemeldet, der
Befehl endet mit Fehler (damit der Scheduler es sieht).

Wie in `test_scheduler_organisation` wird nirgends ein Mandantenkontext gesetzt.
"""
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from core.models import AktivitaetsLog
from core.services import automation

from ._isolation import MandantenFixture


class TageslaufIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _lauf(self, kaputt_fuer):
        original = automation._pendenzen_fuer_organisation

        def defekt(horizont, user):
            from core.tenancy import aktuelle_organisation
            if aktuelle_organisation().pk == kaputt_fuer.pk:
                raise RuntimeError('Daten dieser Verwaltung sind kaputt')
            return original(horizont, user)

        raus, fehler = StringIO(), StringIO()
        with mock.patch.object(automation, '_pendenzen_fuer_organisation', defekt), \
                mock.patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])):
            try:
                call_command('taeglicher_lauf', digest_weekday=-1, stdout=raus, stderr=fehler)
                ausnahme = None
            except CommandError as e:
                ausnahme = e
        return ausnahme, raus.getvalue(), fehler.getvalue()

    def test_defekte_verwaltung_stoppt_die_andere_nicht(self):
        ausnahme, raus, fehler = self._lauf(self.a.organisation)
        # B wurde bedient: ihr Aktivitätslog-Eintrag des Tageslaufs existiert.
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
            organisation=self.b.organisation, aktion='Täglicher Lauf (Scheduler)').exists(),
            'Verwaltung B wurde vom Fehler in A mitgerissen.')

    def test_fehler_wird_gemeldet_und_beendet_mit_fehler(self):
        ausnahme, raus, fehler = self._lauf(self.a.organisation)
        self.assertIsNotNone(ausnahme, 'Der Lauf meldete trotz Fehler Erfolg.')
        self.assertIn(str(self.a.organisation), str(ausnahme))
        self.assertIn('kaputt', fehler)

    def test_ohne_fehler_endet_der_lauf_sauber(self):
        raus, fehler = StringIO(), StringIO()
        with mock.patch('core.utils.market_data.fetch_market_rates', return_value=({}, [])):
            call_command('taeglicher_lauf', digest_weekday=-1, stdout=raus, stderr=fehler)
        self.assertNotIn('FEHLER', fehler.getvalue())
        for fx in (self.a, self.b):
            self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
                organisation=fx.organisation, aktion='Täglicher Lauf (Scheduler)').exists())
