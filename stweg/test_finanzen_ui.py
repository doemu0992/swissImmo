"""Verteilschlüssel, Budget, Dokumente und E-Voting über die Oberfläche."""
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg import budget as bd
from stweg import dokumente as dok
from stweg.models import (StwegBudget, StwegDokument, StwegKostenzuordnung, StwegSchluessel,
                          StwegVorschreibung, Traktandum, Versammlung)
from stweg.schluessel import standard_schluessel
from stweg.test_budget import budget_2026, haus_mit_eigentuemern
from stweg.test_schluessel import konto

User = get_user_model()
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


class SchluesselOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.client.force_login(_team_user('Verwaltung'))
        self.base = f'/neu/stweg/{self.lg.pk}'

    def test_seite_und_lift_ohne_eg_anlegen(self):
        self.assertEqual(self.client.get(f'{self.base}/schluessel/').status_code, 200)
        r = self.client.post(f'{self.base}/schluessel/neu/', {'name': 'Lift', 'art': 'manuell', 'ohne_eg': '1'})
        self.assertEqual(r.status_code, 302)
        s = StwegSchluessel.objects.get(name='Lift')
        self.assertEqual(dict(s.anteile.values_list('einheit__bezeichnung', 'anteil'))['Whg EG'], 0)
        self.assertContains(self.client.get(f'{self.base}/schluessel/'), 'Lift')

    def test_doppelter_name_wird_gemeldet_nicht_abgestuerzt(self):
        self.client.post(f'{self.base}/schluessel/neu/', {'name': 'Heizung', 'art': 'flaeche'})
        r = self.client.post(f'{self.base}/schluessel/neu/', {'name': 'Heizung', 'art': 'flaeche'}, follow=True)
        self.assertContains(r, 'gibt es schon')
        self.assertEqual(StwegSchluessel.objects.filter(name='Heizung').count(), 1)

    def test_anteile_speichern_und_negative_ablehnen(self):
        self.client.post(f'{self.base}/schluessel/neu/', {'name': 'Garten', 'art': 'manuell'})
        s = StwegSchluessel.objects.get(name='Garten')
        daten = {f'anteil_{e.pk}': '1' for e in self.e}
        self.client.post(f'/neu/stweg/schluessel/{s.pk}/anteile/', daten)
        self.assertEqual(s.anteile.count(), 5)
        daten[f'anteil_{self.e[0].pk}'] = '-3'
        r = self.client.post(f'/neu/stweg/schluessel/{s.pk}/anteile/', daten, follow=True)
        self.assertContains(r, 'negativ')
        self.assertEqual(s.anteile.get(einheit=self.e[0]).anteil, 1)

    def test_kostenart_zuordnen_und_entfernen_und_loeschen_gesperrt(self):
        k = konto('4200', 'Lift')
        self.client.post(f'{self.base}/schluessel/neu/', {'name': 'Lift', 'art': 'manuell', 'ohne_eg': '1'})
        s = StwegSchluessel.objects.get(name='Lift')
        self.client.post(f'{self.base}/kostenart/', {'konto': k.pk, 'schluessel': s.pk})
        self.assertEqual(StwegKostenzuordnung.objects.get().schluessel, s)
        r = self.client.post(f'/neu/stweg/schluessel/{s.pk}/loeschen/', follow=True)
        self.assertContains(r, 'wird noch verwendet')
        self.assertTrue(StwegSchluessel.objects.filter(pk=s.pk).exists())
        self.client.post(f'{self.base}/kostenart/', {'konto': k.pk, 'schluessel': ''})
        self.assertFalse(StwegKostenzuordnung.objects.exists())
        self.client.post(f'/neu/stweg/schluessel/{s.pk}/loeschen/')
        self.assertFalse(StwegSchluessel.objects.filter(pk=s.pk).exists())

    def test_standardschluessel_nicht_loeschbar(self):
        s = standard_schluessel(self.lg)
        self.client.post(f'/neu/stweg/schluessel/{s.pk}/loeschen/')
        self.assertTrue(StwegSchluessel.objects.filter(pk=s.pk).exists())

    def test_benutzer_ohne_rolle_darf_nicht_schreiben(self):
        c = Client()
        c.force_login(User.objects.create_user('ohne_rolle', password='x'))
        self.assertIn(c.post(f'{self.base}/schluessel/neu/', {'name': 'X', 'art': 'flaeche'}).status_code,
                      (302, 403, 404))
        self.assertFalse(StwegSchluessel.objects.filter(name='X').exists())


class BudgetOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.client.force_login(_team_user('Verwaltung'))
        self.base = f'/neu/stweg/{self.lg.pk}'

    def test_von_der_idee_bis_zu_den_akonto_rechnungen(self):
        self.client.post(f'{self.base}/budget/neu/', {'jahr': '2026', 'raten': '4', 'erste_faelligkeit': '2026-01-01'})
        b = StwegBudget.objects.get()
        self.assertTrue(self.lg.stweg_schluessel.filter(ist_standard=True).exists())
        self.client.post(f'/neu/stweg/budget/{b.pk}/position/neu/',
                         {'bezeichnung': 'Versicherung', 'schluessel': standard_schluessel(self.lg).pk,
                          'betrag': "1'000.00"})
        self.assertContains(self.client.get(f'/neu/stweg/budget/{b.pk}/'), 'Versicherung')
        self.client.post(f'/neu/stweg/budget/{b.pk}/vorlegen/')
        v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', datum=timezone.now() + timedelta(days=20))
        t = Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='Reglement (Test)', versammlung=v, nr=1, titel='Budget', mehrheitsart='doppelt_aller')
        self.client.post(f'/neu/stweg/budget/{b.pk}/traktandum/', {'traktandum': t.pk})
        t.refresh_from_db()
        self.assertEqual(t.budget_id, b.pk)
        self.assertFalse(StwegVorschreibung.objects.exists())      # erst der Beschluss schreibt vor

    def test_position_loeschen_setzt_zurueck_auf_entwurf(self):
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        p = b.positionen.first()
        self.client.post(f'/neu/stweg/budget/{b.pk}/position/loeschen/', {'position': p.pk})
        b.refresh_from_db()
        self.assertEqual((b.status, b.positionen.count()), ('entwurf', 1))

    def test_genehmigtes_budget_laesst_sich_nicht_aendern(self):
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        p = b.positionen.first()
        self.client.post(f'/neu/stweg/budget/{b.pk}/position/loeschen/', {'position': p.pk})
        self.assertEqual(b.positionen.count(), 2)

    def test_ratenzahl_wird_geprueft(self):
        self.client.post(f'{self.base}/budget/neu/', {'jahr': '2026', 'raten': '5'})
        self.assertFalse(StwegBudget.objects.exists())

    def test_pdf_und_versand(self):
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        r = self.client.get(f'/neu/stweg/budget/{b.pk}/pdf/?eigentuemer={self.eigs[1].pk}')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(self.client.get(f'/neu/stweg/budget/{b.pk}/pdf/?eigentuemer=999999').status_code, 404)
        from unittest import mock
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True):
            r = self.client.post(f'/neu/stweg/budget/{b.pk}/versenden/', follow=True)
        self.assertContains(r, '5 gesendet')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DokumenteTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.client.force_login(_team_user('Verwaltung'))

    def datei(self, name='r.pdf', inhalt=PDF):
        return SimpleUploadedFile(name, inhalt, content_type='application/pdf')

    def test_pflichtkategorien_fehlen_dann_ok(self):
        namen = {p['kategorie']: p['status'] for p in dok.pruefen(self.lg)}
        self.assertEqual(namen, {'begruendungsakt': 'fehlt', 'reglement': 'fehlt', 'nutzungsordnung': 'fehlt',
                                 'gebaeudeversicherung': 'fehlt', 'jahresrechnung': 'automatisch'})
        for kat in ('begruendungsakt', 'reglement', 'nutzungsordnung', 'gebaeudeversicherung'):
            dok.hochladen(self.lg, kat, kat, self.datei())
        self.assertEqual(dok.luecken(self.lg), [])

    def test_aufgaben_entstehen_und_verschwinden(self):
        from core.models import Pendenz
        self.assertEqual(dok.aufgaben_nachziehen(self.lg), (4, 0))
        self.assertEqual(dok.aufgaben_nachziehen(self.lg), (0, 0))                   # idempotent
        dok.hochladen(self.lg, 'reglement', 'Reglement', self.datei())
        self.assertEqual(dok.aufgaben_nachziehen(self.lg), (0, 1))
        self.assertEqual(Pendenz.objects.filter(liegenschaft=self.lg, quelle__startswith='stweg:dokument:',
                                                erledigt=False).count(), 3)

    def test_neue_fassung_ersetzt_die_alte_und_police_laeuft_ab(self):
        heute = timezone.localdate()
        alt = dok.hochladen(self.lg, 'reglement', 'Reglement 2015', self.datei(), gueltig_ab=heute - timedelta(days=900))
        neu = dok.hochladen(self.lg, 'reglement', 'Reglement 2024', self.datei(), gueltig_ab=heute - timedelta(days=5))
        self.assertEqual([d.pk for d in dok.aktuell(self.lg, 'reglement')], [neu.pk])
        zukunft = dok.hochladen(self.lg, 'reglement', 'Reglement 2030', self.datei(), gueltig_ab=heute + timedelta(days=30))
        self.assertEqual([d.pk for d in dok.aktuell(self.lg, 'reglement')], [neu.pk])      # noch nicht gültig
        dok.hochladen(self.lg, 'gebaeudeversicherung', 'Gebäude', self.datei(), gueltig_ab=heute - timedelta(days=400),
                      gueltig_bis=heute - timedelta(days=1))
        self.assertEqual({p['kategorie']: p['status'] for p in dok.pruefen(self.lg)}['gebaeudeversicherung'],
                         'abgelaufen')
        dok.hochladen(self.lg, 'versicherung', 'Haftpflicht', self.datei(), gueltig_bis=heute + timedelta(days=100))
        dok.hochladen(self.lg, 'versicherung', 'Gebäude neu', self.datei(), gueltig_bis=heute + timedelta(days=300))
        self.assertEqual(len(dok.aktuell(self.lg, 'versicherung')), 2)                     # parallel

    def test_upload_prueft_den_inhalt(self):
        with self.assertRaises(dok.DokumentFehler):
            dok.hochladen(self.lg, 'reglement', 'x', self.datei('bild.pdf', b'<html><script>alert(1)</script>'))
        with self.assertRaises(dok.DokumentFehler):
            dok.hochladen(self.lg, 'reglement', 'x', self.datei('x.exe', PDF))
        with self.assertRaises(dok.DokumentFehler):
            dok.hochladen(self.lg, 'unbekannt', 'x', self.datei())
        with self.assertRaises(dok.DokumentFehler):
            dok.hochladen(self.lg, 'reglement', '  ', self.datei())
        self.assertFalse(StwegDokument.objects.exists())

    def test_hochladen_ueber_die_oberflaeche_und_download(self):
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/dokumente/neu/',
                             {'kategorie': 'reglement', 'titel': 'Reglement', 'datei': self.datei(), 'sichtbar': '1'})
        self.assertEqual(r.status_code, 302)
        d = StwegDokument.objects.get()
        self.assertTrue(d.sichtbar)
        self.assertTrue(d.datei.name.startswith(f'organisation/{self.lg.organisation_id}/dokumente/'))
        r = self.client.get(f'/neu/stweg/dokument/{d.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), PDF)
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/dokumente/'), 'Reglement')

    def test_media_url_liefert_nichts_an_anonyme(self):
        d = dok.hochladen(self.lg, 'reglement', 'R', self.datei())
        self.client.logout()
        self.assertIn(self.client.get(f'/media/{d.datei.name}').status_code, (302, 403, 404))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DokumenteZugriffTests(TestCase):
    """Wer ein Dokument sehen darf: die eigene Verwaltung und die Eigentümer — sonst niemand."""

    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.frei = dok.hochladen(self.lg, 'reglement', 'Reglement',
                                  SimpleUploadedFile('a.pdf', PDF), sichtbar=True)
        self.intern = dok.hochladen(self.lg, 'sonstiges', 'Intern',
                                    SimpleUploadedFile('b.pdf', PDF), sichtbar=False)
        self.nachbar_lg, _, self.nachbar_eigs = haus_mit_eigentuemern()
        self.clients = {}
        for name, eig in (('anna', self.eigs[0]), ('nachbar', self.nachbar_eigs[0])):
            u = User.objects.create_user(username=name, password='x')
            eig.benutzer = u
            eig.save()
            c = Client()
            c.force_login(u)
            self.clients[name] = c

    def test_eigentuemer_sieht_freigegebenes_und_nur_das(self):
        c = self.clients['anna']
        r = c.get(f'/portal/stweg/dokument/{self.frei.pk}/')
        self.assertEqual((r.status_code, b''.join(r.streaming_content)), (200, PDF))
        self.assertEqual(c.get(f'/portal/stweg/dokument/{self.intern.pk}/').status_code, 404)
        s = c.get('/portal/stweg/')
        self.assertContains(s, 'Reglement')
        self.assertNotContains(s, 'Intern')

    def test_eigentuemer_einer_anderen_gemeinschaft_bekommt_404(self):
        self.assertEqual(self.clients['nachbar'].get(f'/portal/stweg/dokument/{self.frei.pk}/').status_code, 404)

    def test_miteigentuemer_darf_lesen(self):
        from crm.models import Eigentuemer
        mit = Eigentuemer.objects.create(firma_oder_name='Mit', email='m@x.ch')
        self.e[0].miteigentuemer.add(mit)
        u = User.objects.create_user(username='mit', password='x')
        mit.benutzer = u
        mit.save()
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/portal/stweg/dokument/{self.frei.pk}/').status_code, 200)

    def test_anonym_und_ohne_eigentuemerprofil(self):
        self.assertEqual(Client().get(f'/portal/stweg/dokument/{self.frei.pk}/').status_code, 302)
        u = User.objects.create_user(username='niemand', password='x')
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/portal/stweg/dokument/{self.frei.pk}/').status_code, 404)

    def test_fremde_verwaltung_bekommt_404(self):
        from crm.models import Mitgliedschaft, Organisation
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        u = _team_user('Verwaltung')
        Mitgliedschaft.objects.filter(benutzer=u).update(organisation=fremd)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/neu/stweg/dokument/{self.frei.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/neu/stweg/dokument/{self.frei.pk}/loeschen/').status_code, 404)
        self.assertTrue(StwegDokument.objects.filter(pk=self.frei.pk).exists())


class PortalEVotingTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', datum=timezone.now() + timedelta(days=20),
                                            status='durchgefuehrt', evoting=True)
        self.t = Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='Reglement (Test)', versammlung=self.v, nr=1, titel='Budget', antrag='Genehmigen?',
                                           mehrheitsart='doppelt_anwesende')
        self.cl = {}
        for eig in self.eigs:
            u = User.objects.create_user(username=f'u_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            c = Client()
            c.force_login(u)
            self.cl[eig.firma_oder_name] = c

    def test_anzeige_teilnahme_und_stimme(self):
        c = self.cl['Anna']
        s = c.get('/portal/stweg/')
        self.assertContains(s, 'Digital teilnehmen')
        self.assertNotContains(s, 'name="stimme_')
        c.post(f'/portal/stweg/teilnehmen/{self.v.pk}/')
        s = c.get('/portal/stweg/')
        self.assertContains(s, f'name="stimme_{self.t.pk}_{self.e[0].pk}"')
        r = c.post(f'/portal/stweg/evoting/{self.v.pk}/', {f'stimme_{self.t.pk}_{self.e[0].pk}': 'ja'}, follow=True)
        self.assertContains(r, 'Ihre Stimme wurde gespeichert')
        from stweg.models import Stimme
        self.assertEqual(Stimme.objects.get().kanal, 'portal')

    def test_fremde_einheit_und_manipulierte_felder(self):
        c = self.cl['Anna']
        c.post(f'/portal/stweg/teilnehmen/{self.v.pk}/')
        r = c.post(f'/portal/stweg/evoting/{self.v.pk}/', {f'stimme_{self.t.pk}_{self.e[1].pk}': 'ja'}, follow=True)
        self.assertContains(r, 'Ungültige Abstimmung')
        for muell in ('stimme_x_y', 'stimme_1', 'stimme_1_2_3'):
            self.assertEqual(c.post(f'/portal/stweg/evoting/{self.v.pk}/', {muell: 'ja'}).status_code, 302)
        from stweg.models import Stimme
        self.assertFalse(Stimme.objects.exists())

    def test_nachbargemeinschaft_404(self):
        n_lg, _, n_eigs = haus_mit_eigentuemern()
        u = User.objects.create_user(username='nb', password='x')
        n_eigs[0].benutzer = u
        n_eigs[0].save()
        c = Client()
        c.force_login(u)
        self.assertEqual(c.post(f'/portal/stweg/teilnehmen/{self.v.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/portal/stweg/evoting/{self.v.pk}/', {'stimme_1_1': 'ja'}).status_code, 404)

    def test_geschlossenes_evoting_zeigt_kein_formular(self):
        self.v.evoting_bis = timezone.now() - timedelta(minutes=1)
        self.v.save()
        self.assertNotContains(self.cl['Anna'].get('/portal/stweg/'), 'Digital teilnehmen')

    def test_verwaltung_schaltet_evoting(self):
        self.v.evoting = False
        self.v.save()
        c = Client()
        c.force_login(_team_user('Verwaltung'))
        c.post(f'/neu/stweg/versammlung/{self.v.pk}/evoting/', {'evoting': '1'})
        self.v.refresh_from_db()
        self.assertTrue(self.v.evoting)
        c.post(f'/neu/stweg/versammlung/{self.v.pk}/evoting/', {})
        self.v.refresh_from_db()
        self.assertFalse(self.v.evoting)

    def test_kontokorrent_und_fonds_im_portal(self):
        from stweg.fonds import jahreseinlage_belasten
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        jahreseinlage_belasten(self.lg, 2026, Decimal('10000'))
        s = self.cl['Anna'].get('/portal/stweg/')
        self.assertContains(s, 'Kontokorrent')
        self.assertContains(s, 'Akonto 2026, Rate 1/4')
        self.assertContains(s, 'Bestand CHF 10')
        self.assertContains(s, f'/portal/stweg/akonto/{b.pk}/')
        r = self.cl['Anna'].get(f'/portal/stweg/akonto/{b.pk}/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        # Ein Eigentümer einer ANDEREN Gemeinschaft bekommt die Akonto-Rechnung nicht.
        n_lg, _, n_eigs = haus_mit_eigentuemern()
        u = User.objects.create_user(username='nachbar', password='x')
        n_eigs[0].benutzer = u
        n_eigs[0].save()
        fremd = Client()
        fremd.force_login(u)
        self.assertEqual(fremd.get(f'/portal/stweg/akonto/{b.pk}/').status_code, 404)
        # Der Eigentümer einer anderen Einheit sieht Annas Kontokorrent nicht.
        self.assertNotContains(self.cl['Bruno'].get('/portal/stweg/'), 'Whg EG')
