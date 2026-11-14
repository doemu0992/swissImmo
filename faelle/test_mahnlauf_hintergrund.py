"""Mahnlauf: sofort wie bisher, im Hintergrund nur bei vielen offenen Rechnungen UND aktivem Auftragsläufer."""
from django.core.cache import cache
from django.test import override_settings

from core.models import AktivitaetsLog, Auftrag
from core.services import auftraege
from faelle.lauf_models import Lauf
from faelle.test_monatsabschluss import _Basis


class SofortOderHintergrundTests(_Basis):
    def setUp(self):
        super().setUp()
        cache.delete(auftraege.PULS_SCHLUESSEL)
        self.addCleanup(cache.delete, auftraege.PULS_SCHLUESSEL)
        self.sollstellung()                                   # eine offene Rechnung

    def _lauf(self):
        return self.c.post('/neu/mahnwesen/lauf/', {'kein_versand': 'on'}, follow=True)

    def test_ein_kleiner_lauf_laeuft_sofort_auch_wenn_der_laeufer_lebt(self):
        auftraege.puls_melden()
        self._lauf()
        self.assertEqual(Auftrag.objects.count(), 0)
        self.assertEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)

    @override_settings(MAHNLAUF_SCHWELLE_HINTERGRUND=1)
    def test_ein_grosser_lauf_ohne_laeufer_laeuft_sofort(self):
        self._lauf()
        self.assertEqual(Auftrag.objects.count(), 0)
        self.assertEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)

    @override_settings(MAHNLAUF_SCHWELLE_HINTERGRUND=1)
    def test_ein_grosser_lauf_mit_laeufer_wird_zum_auftrag_mit_demselben_nachspiel(self):
        auftraege.puls_melden()
        antwort = self._lauf()
        self.assertContains(antwort, 'läuft im Hintergrund')
        auftrag = Auftrag.objects.get()
        self.assertEqual(auftrag.art, 'mahnlauf')
        self.assertEqual(auftrag.parameter['send_email'], False)   # «kein Versand» reist mit
        self.assertNotEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)

        self.assertEqual(auftraege.abarbeiten(), 1)
        auftrag = Auftrag.alle_organisationen.get(pk=auftrag.pk)
        self.assertEqual(auftrag.zustand, Auftrag.ZUSTAND_FERTIG, auftrag.fehler)
        self.assertIn('Mahnung(en)', auftrag.ergebnis)
        self.assertEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)
        self.assertIn('Auftrag', AktivitaetsLog.objects.filter(aktion='Mahnlauf ausgeführt').latest('pk').details)

    @override_settings(MAHNLAUF_SCHWELLE_HINTERGRUND=1)
    def test_ein_erzwungener_auftrag_schliesst_den_monatslauf_nicht_ab(self):
        auftraege.puls_melden()
        self.c.post('/neu/mahnwesen/lauf/', {'kein_versand': 'on', 'erzwingen': '1'})
        auftraege.abarbeiten()
        self.assertEqual(Auftrag.objects.get().zustand, Auftrag.ZUSTAND_FERTIG)
        self.assertNotEqual(self.lauf('mahnlauf').status, Lauf.ABGESCHLOSSEN)
        self.assertTrue(AktivitaetsLog.objects.filter(aktion='Mahnlauf erzwungen').exists())
