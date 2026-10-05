"""Legal Health Check: Begründungsakt, Reglement und aktueller Gebäudeversicherungsnachweis."""
from datetime import timedelta
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg import compliance, dokumente as dok
from stweg.tests import neue_stweg

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


def datei(name='d.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


class HealthCheckTests(TestCase):
    def setUp(self):
        self.lg, _ = neue_stweg(status='aktiv')
        self.heute = timezone.localdate()

    def status(self):
        return {p['kategorie']: p['status'] for p in compliance.health_check(self.lg)['punkte']}

    def test_leer_ist_nicht_konform(self):
        h = compliance.health_check(self.lg)
        self.assertFalse(h['konform'])
        self.assertEqual(self.status(), {'begruendungsakt': 'fehlt', 'reglement': 'fehlt',
                                         'gebaeudeversicherung': 'fehlt'})
        self.assertEqual(len(h['gruende']), 3)

    def test_alle_drei_machen_konform_jedes_fehlende_nicht(self):
        for kat in ('begruendungsakt', 'reglement', 'gebaeudeversicherung'):
            self.assertFalse(compliance.health_check(self.lg)['konform'], kat)
            dok.hochladen(self.lg, kat, kat, datei(), gueltig_bis=self.heute + timedelta(days=200))
        h = compliance.health_check(self.lg)
        self.assertTrue(h['konform'])
        self.assertEqual(set(self.status().values()), {'ok'})

    def test_abgelaufene_versicherung_ist_nicht_konform_neue_fassung_heilt(self):
        dok.hochladen(self.lg, 'begruendungsakt', 'BA', datei())
        dok.hochladen(self.lg, 'reglement', 'R', datei())
        dok.hochladen(self.lg, 'gebaeudeversicherung', 'GV 2024', datei(), gueltig_ab=self.heute - timedelta(days=400),
                      gueltig_bis=self.heute - timedelta(days=1))
        h = compliance.health_check(self.lg)
        self.assertFalse(h['konform'])
        self.assertEqual(self.status()['gebaeudeversicherung'], 'abgelaufen')
        self.assertIn('abgelaufen', ' '.join(h['gruende']))
        dok.hochladen(self.lg, 'gebaeudeversicherung', 'GV 2026', datei(), gueltig_bis=self.heute + timedelta(days=300))
        self.assertTrue(compliance.health_check(self.lg)['konform'])

    def test_neuer_nachweis_ersetzt_den_alten(self):
        dok.hochladen(self.lg, 'gebaeudeversicherung', 'GV alt', datei(), gueltig_ab=self.heute - timedelta(days=200),
                      gueltig_bis=self.heute + timedelta(days=100))
        neu = dok.hochladen(self.lg, 'gebaeudeversicherung', 'GV neu', datei(), gueltig_ab=self.heute - timedelta(days=5),
                            gueltig_bis=self.heute + timedelta(days=360))
        self.assertEqual([d.pk for d in dok.aktuell(self.lg, 'gebaeudeversicherung')], [neu.pk])    # ersetzend
        self.assertEqual(compliance.health_check(self.lg)['punkte'][2]['dokument'], neu)

    def test_haftpflicht_ersetzt_den_gebaeudenachweis_nicht(self):
        dok.hochladen(self.lg, 'begruendungsakt', 'BA', datei())
        dok.hochladen(self.lg, 'reglement', 'R', datei())
        dok.hochladen(self.lg, 'versicherung', 'Haftpflicht', datei(), gueltig_bis=self.heute + timedelta(days=100))
        self.assertFalse(compliance.health_check(self.lg)['konform'])

    def test_erst_zukuenftig_gueltig_zaehlt_noch_nicht(self):
        dok.hochladen(self.lg, 'reglement', 'R 2030', datei(), gueltig_ab=self.heute + timedelta(days=30))
        self.assertEqual(self.status()['reglement'], 'noch_nicht_gueltig')
        self.assertIn('gilt erst ab', ' '.join(compliance.health_check(self.lg)['gruende']))
        dok.hochladen(self.lg, 'reglement', 'R alt', datei(), gueltig_ab=self.heute - timedelta(days=900),
                      gueltig_bis=self.heute - timedelta(days=10))
        self.assertEqual(self.status()['reglement'], 'abgelaufen')              # etwas war gültig, jetzt nicht mehr

    def test_dokumente_einer_anderen_gemeinschaft_zaehlen_nicht(self):
        lg2, _ = neue_stweg(name='Anders', status='aktiv')
        for kat in ('begruendungsakt', 'reglement', 'gebaeudeversicherung'):
            dok.hochladen(lg2, kat, kat, datei())
        self.assertFalse(compliance.health_check(self.lg)['konform'])
        self.assertTrue(compliance.health_check(lg2)['konform'])

    def test_fehlende_datei_im_speicher_ist_nicht_in_ordnung(self):
        for kat in ('begruendungsakt', 'reglement', 'gebaeudeversicherung'):
            d = dok.hochladen(self.lg, kat, kat, datei())
        d.datei.storage.delete(d.datei.name)                                      # die Datei ist weg, der Eintrag nicht
        h = compliance.health_check(self.lg)
        self.assertFalse(h['konform'])
        self.assertEqual(self.status()['gebaeudeversicherung'], 'datei_fehlt')
        self.assertIn('Datei fehlt', ' '.join(h['gruende']))

    def test_ohne_ablaufdatum_gilt_aber_mit_hinweis(self):
        for kat in ('begruendungsakt', 'reglement', 'gebaeudeversicherung'):
            dok.hochladen(self.lg, kat, kat, datei())
        h = compliance.health_check(self.lg)
        self.assertTrue(h['konform'])
        self.assertEqual([p['hinweis'] for p in h['punkte']], ['', '', 'kein Ablaufdatum erfasst'])

    def test_pendenz_fuer_den_fehlenden_nachweis(self):
        from core.models import Pendenz
        dok.aufgaben_nachziehen(self.lg)
        self.assertTrue(Pendenz.objects.filter(liegenschaft=self.lg, quelle='stweg:dokument:gebaeudeversicherung',
                                               erledigt=False).exists())


class OberflaecheTests(TestCase):
    def setUp(self):
        self.lg, _ = neue_stweg(status='aktiv')
        self.c = self.client_class()
        self.c.force_login(_team_user('Verwaltung'))

    def test_rote_warnung_dann_gruen(self):
        r = self.c.get(f'/neu/stweg/{self.lg.pk}/')
        self.assertContains(r, 'Nicht Compliance-Konform')
        self.assertContains(r, 'Gebäudeversicherungsnachweis')
        self.assertContains(r, '#c0392b')
        self.assertContains(self.c.get('/neu/stweg/'), 'Nicht Compliance-Konform')
        for kat in ('begruendungsakt', 'reglement', 'gebaeudeversicherung'):
            dok.hochladen(self.lg, kat, kat, datei())
        r = self.c.get(f'/neu/stweg/{self.lg.pk}/')
        self.assertNotContains(r, 'Nicht Compliance-Konform')
        self.assertContains(r, 'Compliance-konform')
        self.assertNotContains(self.c.get('/neu/stweg/'), 'Nicht Compliance-Konform')

    def test_audit_kommando_nennt_den_check(self):
        out = StringIO()
        call_command('stweg_audit', liegenschaft=self.lg.pk, stdout=out)
        self.assertIn('NICHT COMPLIANCE-KONFORM', out.getvalue())
        self.assertIn('[COMPLIANCE]', out.getvalue())

    def test_dokumentenseite_kennt_die_neue_kategorie(self):
        self.assertContains(self.c.get(f'/neu/stweg/{self.lg.pk}/dokumente/'), 'Gebäudeversicherungsnachweis')
