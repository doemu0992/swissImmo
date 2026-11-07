"""Roadmap Nr. 11: Die Periodensperre lässt sich nur mit einer zweiten Person lockern."""
from datetime import date

from django.test import Client

from core.models import AktivitaetsLog
from crm.models import Organisation
from finance.models import SperreAenderung
from finance.periodensperre import SperreFehler, entscheiden, sperre_aendern

from ._rollen import RollenBasis


class SperreTests(RollenBasis):

    def setUp(self):
        Organisation.objects.filter(pk=self.org.pk).update(buchung_gesperrt_bis=date(2025, 12, 31))
        self.org.refresh_from_db()
        self.v1 = self.benutzer['verwalter']
        self.v2 = self.benutzer['verwalter2']

    def _sperre(self):
        return Organisation.objects.get(pk=self.org.pk).buchung_gesperrt_bis

    def test_mehr_sperren_geht_sofort(self):
        ergebnis, antrag = sperre_aendern(self.org, date(2026, 12, 31), self.v1)
        self.assertEqual((ergebnis, antrag), ('gesetzt', None))
        self.assertEqual(self._sperre(), date(2026, 12, 31))

    def test_lockern_wird_zum_antrag_und_aendert_nichts(self):
        ergebnis, antrag = sperre_aendern(self.org, date(2024, 12, 31), self.v1, 'Korrektur nötig')
        self.assertEqual(ergebnis, 'beantragt')
        self.assertEqual(antrag.status, 'offen')
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_lockern_ohne_begruendung_scheitert(self):
        with self.assertRaises(SperreFehler):
            sperre_aendern(self.org, None, self.v1, '  ')
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_dieselbe_person_darf_nicht_freigeben(self):
        _e, antrag = sperre_aendern(self.org, None, self.v1, 'Grund')
        with self.assertRaises(SperreFehler):
            entscheiden(antrag, self.v1, True)
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_zweite_person_gibt_frei(self):
        _e, antrag = sperre_aendern(self.org, None, self.v1, 'Grund')
        entscheiden(antrag, self.v2, True)
        self.assertIsNone(self._sperre())
        antrag.refresh_from_db()
        self.assertEqual((antrag.status, antrag.entschieden_von_id), ('freigegeben', self.v2.pk))

    def test_ablehnen_laesst_die_sperre_stehen(self):
        _e, antrag = sperre_aendern(self.org, None, self.v1, 'Grund')
        entscheiden(antrag, self.v2, False)
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_entschiedener_antrag_ist_nicht_noch_einmal_nutzbar(self):
        _e, antrag = sperre_aendern(self.org, None, self.v1, 'Grund')
        entscheiden(antrag, self.v2, False)
        with self.assertRaises(SperreFehler):
            entscheiden(antrag, self.v2, True)

    def test_direktes_zuruecksetzen_am_modell_ist_gesperrt(self):
        org = Organisation.objects.get(pk=self.org.pk)
        org.buchung_gesperrt_bis = date(2020, 12, 31)
        with self.assertRaises(PermissionError):
            org.save()
        org.buchung_gesperrt_bis = None
        with self.assertRaises(PermissionError):
            org.save(update_fields=['buchung_gesperrt_bis'])
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_speichern_anderer_felder_bleibt_moeglich(self):
        org = Organisation.objects.get(pk=self.org.pk)
        org.firma = 'Neuer Name AG'
        org.save()
        self.assertEqual(Organisation.objects.get(pk=self.org.pk).firma, 'Neuer Name AG')


class SperreSeiteTests(RollenBasis):

    def setUp(self):
        Organisation.objects.filter(pk=self.org.pk).update(buchung_gesperrt_bis=date(2025, 12, 31))

    def _sperre(self):
        return Organisation.objects.get(pk=self.org.pk).buchung_gesperrt_bis

    def test_aufheben_ueber_die_seite_stellt_nur_einen_antrag(self):
        c = self.client_von('verwalter')
        c.post('/neu/anlagen/', {'aktion': 'sperre_set', 'gesperrt_bis': '', 'grund': 'Fehler im Vorjahr'})
        self.assertEqual(self._sperre(), date(2025, 12, 31))
        self.assertEqual(SperreAenderung.alle_organisationen.filter(status='offen').count(), 1)
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
            aktion='Lockerung der Periodensperre beantragt').exists())

    def test_zweite_person_gibt_ueber_die_seite_frei(self):
        c1, c2 = self.client_von('verwalter'), self.client_von('verwalter2')
        c1.post('/neu/anlagen/', {'aktion': 'sperre_set', 'gesperrt_bis': '', 'grund': 'Fehler im Vorjahr'})
        antrag = SperreAenderung.alle_organisationen.get(status='offen')
        c1.post('/neu/anlagen/', {'aktion': 'sperre_freigeben', 'antrag_id': antrag.pk})
        self.assertEqual(self._sperre(), date(2025, 12, 31))        # selbe Person: nichts
        c2.post('/neu/anlagen/', {'aktion': 'sperre_freigeben', 'antrag_id': antrag.pk})
        self.assertIsNone(self._sperre())

    def test_buchhaltung_entscheidet_nicht(self):
        c1 = self.client_von('verwalter')
        c1.post('/neu/anlagen/', {'aktion': 'sperre_set', 'gesperrt_bis': '', 'grund': 'Grund'})
        antrag = SperreAenderung.alle_organisationen.get(status='offen')
        self.client_von('buchhaltung').post('/neu/anlagen/', {'aktion': 'sperre_freigeben', 'antrag_id': antrag.pk})
        self.assertEqual(self._sperre(), date(2025, 12, 31))

    def test_seite_zeigt_offenen_antrag(self):
        c = self.client_von('verwalter')
        c.post('/neu/anlagen/', {'aktion': 'sperre_set', 'gesperrt_bis': '', 'grund': 'Sichtbarer Grund'})
        antwort = self.client_von('verwalter2').get('/neu/anlagen/')
        self.assertContains(antwort, 'Sichtbarer Grund')
