"""Sollstellung: sofort wie bisher, im Hintergrund nur bei vielen Verträgen UND aktivem Auftragsläufer."""
from django.core.cache import cache
from django.test import override_settings

from core.models import AktivitaetsLog, Auftrag
from core.services import auftraege
from faelle.lauf_models import Lauf
from faelle.test_monatsabschluss import HEUTE, _Basis
from finance.models import DebitorenRechnung

TITEL = f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}'


class SofortOderHintergrundTests(_Basis):
    def setUp(self):
        super().setUp()
        cache.delete(auftraege.PULS_SCHLUESSEL)
        self.addCleanup(cache.delete, auftraege.PULS_SCHLUESSEL)

    def test_ein_kleiner_lauf_laeuft_sofort_auch_wenn_der_laeufer_lebt(self):
        auftraege.puls_melden()
        self.sollstellung()
        self.assertTrue(DebitorenRechnung.objects.filter(titel=TITEL).exists())
        self.assertEqual(Auftrag.objects.count(), 0)

    @override_settings(SOLLSTELLUNG_SCHWELLE_HINTERGRUND=1)
    def test_ein_grosser_lauf_ohne_laeufer_laeuft_sofort(self):
        """Ohne Läufer bliebe der Auftrag liegen: dann lieber sofort, wie bisher."""
        self.sollstellung()
        self.assertTrue(DebitorenRechnung.objects.filter(titel=TITEL).exists())
        self.assertEqual(Auftrag.objects.count(), 0)
        self.assertEqual(self.lauf('sollstellung').status, Lauf.ABGESCHLOSSEN)

    @override_settings(SOLLSTELLUNG_SCHWELLE_HINTERGRUND=1)
    def test_ein_grosser_lauf_mit_laeufer_wird_zum_auftrag_und_stellt_erst_beim_abarbeiten(self):
        auftraege.puls_melden()
        antwort = self.sollstellung()
        self.assertContains(antwort, 'läuft im Hintergrund')
        self.assertFalse(DebitorenRechnung.objects.filter(titel=TITEL).exists())
        auftrag = Auftrag.objects.get()
        self.assertEqual((auftrag.art, auftrag.erstellt_von), ('sollstellung', self.verwalter))

        self.assertEqual(auftraege.abarbeiten(), 1)
        auftrag = Auftrag.alle_organisationen.get(pk=auftrag.pk)
        self.assertEqual(auftrag.zustand, Auftrag.ZUSTAND_FERTIG, auftrag.fehler)
        self.assertIn('1 Rechnung', auftrag.ergebnis)
        # Dasselbe Nachspiel wie beim Knopf: Rechnung, abgeschlossene Periode, Logbuch.
        self.assertTrue(DebitorenRechnung.objects.filter(titel=TITEL).exists())
        self.assertEqual(self.lauf('sollstellung').status, Lauf.ABGESCHLOSSEN)
        eintrag = AktivitaetsLog.objects.filter(aktion='Sollstellung ausgeführt').latest('pk')
        self.assertIn('Auftrag', eintrag.details)

    @override_settings(SOLLSTELLUNG_SCHWELLE_HINTERGRUND=1)
    def test_ein_zweiter_auftrag_stellt_nichts_doppelt(self):
        auftraege.puls_melden()
        self.sollstellung()
        auftraege.abarbeiten()
        auftraege.anlegen('sollstellung', {'jahr': HEUTE.year, 'monat': HEUTE.month}, organisation=self.org)
        auftraege.abarbeiten()
        self.assertEqual(DebitorenRechnung.objects.filter(titel=TITEL).count(), 1)


class LaeuferPulsTests(_Basis):
    def setUp(self):
        super().setUp()
        cache.delete(auftraege.PULS_SCHLUESSEL)
        self.addCleanup(cache.delete, auftraege.PULS_SCHLUESSEL)

    def test_ohne_puls_gilt_der_laeufer_als_nicht_aktiv(self):
        self.assertFalse(auftraege.laeufer_aktiv())
        auftraege.puls_melden()
        self.assertTrue(auftraege.laeufer_aktiv())

    def test_der_befehl_meldet_den_puls(self):
        from django.core.management import call_command
        call_command('auftraege_abarbeiten', '--einmal')
        self.assertTrue(auftraege.laeufer_aktiv())

    def test_die_seite_warnt_wenn_auftraege_warten_und_kein_laeufer_lebt(self):
        auftraege.anlegen('sollstellung', {'jahr': HEUTE.year, 'monat': HEUTE.month}, organisation=self.org)
        self.assertContains(self.c.get('/neu/auftraege/'), 'Auftragsläufer meldet sich nicht')
        auftraege.puls_melden()
        self.assertNotContains(self.c.get('/neu/auftraege/'), 'Auftragsläufer meldet sich nicht')
