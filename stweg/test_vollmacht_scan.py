"""Vollmacht: optional der unterschriebene Scan, geschützt ausgeliefert."""
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg import vollmacht as vm
from stweg.models import Versammlung
from stweg.test_budget import haus_mit_eigentuemern

User = get_user_model()
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VollmachtScanTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV', status='eingeladen',
                                            datum=timezone.now() + timedelta(days=20))
        self.verwaltung = Client()
        self.verwaltung.force_login(_team_user('Verwaltung'))
        self.clients = {}
        for eig in self.eigs[:2]:
            u = User.objects.create_user(username=f'u_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            c = Client()
            c.force_login(u)
            self.clients[eig.firma_oder_name] = c

    def scan(self, inhalt=PDF, name='vollmacht.pdf'):
        return SimpleUploadedFile(name, inhalt, content_type='application/pdf')

    def test_erteilen_mit_scan_und_ohne(self):
        a = vm.erteilen(self.v, self.e[0], 'Frau X', dokument=self.scan())
        self.assertTrue(a.dokument.name.startswith(f'organisation/{self.lg.organisation_id}/dokumente/'))
        b = vm.erteilen(self.v, self.e[1], 'Herr Y')
        self.assertFalse(b.dokument)

    def test_abgelehnte_datei_aendert_nichts(self):
        alt = vm.erteilen(self.v, self.e[0], 'Frau X')
        with self.assertRaises(vm.VollmachtFehler):
            vm.erteilen(self.v, self.e[0], 'Herr Z', dokument=self.scan(b'<script>alert(1)</script>'))
        alt.refresh_from_db()
        self.assertIsNone(alt.widerrufen_am)                       # die alte Vollmacht gilt weiter

    def test_nachtraeglich_anhaengen_und_ersetzen(self):
        v = vm.erteilen(self.v, self.e[0], 'Frau X')
        vm.dokument_anhaengen(v, self.scan())
        erster = v.dokument.name
        vm.dokument_anhaengen(v, self.scan(name='neu.pdf'))
        v.refresh_from_db()
        self.assertNotEqual(v.dokument.name, erster)
        vm.widerrufen(v)
        with self.assertRaises(vm.VollmachtFehler):
            vm.dokument_anhaengen(v, self.scan())

    def test_verwaltung_laedt_hoch_und_herunter(self):
        v = vm.erteilen(self.v, self.e[0], 'Frau X')
        r = self.verwaltung.post(f'/neu/stweg/vollmacht/{v.pk}/dokument/', {'dokument': self.scan()})
        self.assertEqual(r.status_code, 302)
        r = self.verwaltung.get(f'/neu/stweg/vollmacht/{v.pk}/datei/')
        self.assertEqual(b''.join(r.streaming_content), PDF)
        self.assertContains(self.verwaltung.get(f'/neu/stweg/versammlung/{self.v.pk}/'), 'Scan öffnen')

    def test_ohne_datei_404(self):
        v = vm.erteilen(self.v, self.e[0], 'Frau X')
        self.assertEqual(self.verwaltung.get(f'/neu/stweg/vollmacht/{v.pk}/datei/').status_code, 404)

    def test_portal_erteilen_mit_scan_und_nur_der_eigentuemer_sieht_ihn(self):
        r = self.clients['Anna'].post(f'/portal/stweg/vollmacht/{self.v.pk}/erteilen/',
                                      {'einheit': self.e[0].pk, 'bevollmaechtigter': 'Frau X',
                                       'dokument': self.scan()})
        self.assertEqual(r.status_code, 302)
        v = self.v.vollmachten.get()
        self.assertTrue(v.dokument)
        self.assertEqual(self.clients['Anna'].get(f'/portal/stweg/scan/{v.pk}/').status_code, 200)
        self.assertEqual(self.clients['Bruno'].get(f'/portal/stweg/scan/{v.pk}/').status_code, 404)
        self.assertEqual(Client().get(f'/portal/stweg/scan/{v.pk}/').status_code, 302)
        # Die Vollmacht-Seite des Eigentümers verlinkt den Scan.
        self.assertContains(self.clients['Anna'].get('/portal/stweg/'), f'/portal/stweg/scan/{v.pk}/')

    def test_fremde_verwaltung_404_und_kein_media_zugriff(self):
        from crm.models import Mitgliedschaft, Organisation
        v = vm.erteilen(self.v, self.e[0], 'Frau X', dokument=self.scan())
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        u = User.objects.get(username='team_Verwaltung')           # in setUp angelegt
        Mitgliedschaft.objects.filter(benutzer=u).update(organisation=fremd)
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get(f'/neu/stweg/vollmacht/{v.pk}/datei/').status_code, 404)
        self.assertEqual(c.post(f'/neu/stweg/vollmacht/{v.pk}/dokument/', {'dokument': self.scan()}).status_code, 404)
        self.assertIn(Client().get(f'/media/{v.dokument.name}').status_code, (302, 403, 404))
