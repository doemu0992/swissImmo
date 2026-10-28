"""ROUTE-01 / ROUTE-07 / ROUTE-18: Eine Vorschau (GET) schreibt nichts.

BEFUND (Audit 28.10.2026)
Das blosse Öffnen einer PDF-Vorschau — Mahnung (Art. 257d), Betreibungs-Datenblatt,
Kaution-Freigabe an die Bank — legte das Dokument in die Vertragsakte, und die
Akte war im Mieterportal standardmässig sichtbar. Der Mieter sah und lud so
Schreiben, die nie an ihn gegangen waren. Dazu schrieben `GET /neu/lebensdauer/`
(69 Zeilen), `GET /konto/zwei-faktor/einrichten/` (Geheimnis) und der GWR-Import.

Die Regel jetzt:
- GET legt nichts ab, hakt nichts ab, schreibt nichts (Wächter unten);
- abgelegt wird beim ausdrücklichen «Erstellen» (POST), nur für Schreib-Rollen;
- ein Dokument ist im Portal erst sichtbar, wenn es zugestellt oder freigegeben ist.

Gegenprobe: In `fw_betreibung_pdf` das `if request.method == 'POST':` entfernen
(Ablage bei jedem Aufruf) — der Wächter und der Betreibungstest werden rot.
"""
import importlib
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase

from core.models import AktivitaetsLog, Pendenz, ZweiterFaktor
from portfolio.models import Lebensdauer
from rentals.models import Dokument

from ._helfer import _basis_objekte, _team_user, _test_organisation
from .test_abnahme_kette import _protokoll


def _zaehler():
    """Was eine Vorschau NICHT verändern darf."""
    return {
        'dokument': Dokument.alle_organisationen.count(),
        'log': AktivitaetsLog.alle_organisationen.count(),
        'pendenz': Pendenz.alle_organisationen.filter(erledigt=True).count(),
        'lebensdauer': Lebensdauer.alle_organisationen.count(),
        'faktor': ZweiterFaktor.objects.count(),
    }


class VorschauSchreibtNichtTests(TestCase):

    def setUp(self):
        from finance.models import Betreibung, DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.lg.kanton = 'ZH'
        self.lg.iban = 'CH9300762011623852957'
        self.lg.save()
        self.v.kautions_art = 'sperrkonto'
        self.v.kautions_einbezahlt_am = date(2024, 1, 5)
        self.v.save()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal('1500.00'), status='offen')
        self.b = Betreibung.objects.create(
            debitoren_rechnung=self.r, vertrag=self.v, forderung=Decimal('1500.00'),
            begehren_am=date(2024, 6, 1))
        self.prot = _protokoll(self.v, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])
        self.prot.abgeschlossen = True
        self.prot.save()
        from rentals.models import Kuendigung
        self.k = Kuendigung.objects.create(vertrag=self.v, absender='vermieter',
                                           per_datum=date(2027, 3, 31))
        self.verwalter = Client()
        self.verwalter.force_login(_team_user('Verwalter'))
        self.lesend = Client()
        self.lesend.force_login(_team_user('Lesezugriff'))

    def _vorschauen(self):
        v = self.v.id
        return [
            f'/vertrag/{v}/pdf/',
            f'/vertrag/{v}/dokumente-zip/',
            f'/vertrag/{v}/dokument/hausordnung/',
            f'/vertrag/{v}/mahnung/',
            f'/vertrag/{v}/qr/',
            f'/neu/betreibungen/{self.b.id}/pdf/',
            f'/neu/vertraege/{v}/kaution-beleg/hinterlegung/',
            f'/neu/vertraege/{v}/kaution-beleg/freigabe/',
            f'/neu/debitoren/{self.r.id}/qr-pdf/',
            f'/neu/abnahme/{self.prot.id}/pdf/',
            f'/neu/kuendigung/{self.k.id}/formular/',
        ]

    def test_keine_vorschau_schreibt_in_die_ablage(self):
        """Jede PDF-Vorschau (GET), als Verwalter UND als Lesezugriff: Es ändert sich nichts."""
        for name, client in (('Verwalter', self.verwalter), ('Lesezugriff', self.lesend)):
            for adresse in self._vorschauen():
                with self.subTest(rolle=name, adresse=adresse):
                    vorher = _zaehler()
                    antwort = client.get(adresse)
                    # Der Lesezugriff darf manche Vorschauen gar nicht öffnen (403); wo er
                    # darf, kommt das PDF. In beiden Fällen bleibt die Ablage unberührt.
                    erlaubt = (200,) if name == 'Verwalter' else (200, 403)
                    self.assertIn(antwort.status_code, erlaubt, antwort.content[:200])
                    self.assertEqual(_zaehler(), vorher)

    def test_vorschauen_sind_keine_leeren_antworten(self):
        """Gegenprobe zum Wächter oben: Ein 200 ohne PDF würde ihn trivial bestehen lassen."""
        for adresse in self._vorschauen():
            with self.subTest(adresse=adresse):
                antwort = self.verwalter.get(adresse)
                self.assertTrue(antwort.content[:4] in (b'%PDF', b'PK\x03\x04'), adresse)

    def test_erstellen_per_post_legt_ab_und_der_mieter_sieht_es_nicht(self):
        """Das ausdrückliche «Erstellen» legt in der Akte ab — unsichtbar im Portal."""
        for adresse, titel in (
                (f'/neu/betreibungen/{self.b.id}/pdf/', 'Betreibungsbegehren'),
                (f'/neu/vertraege/{self.v.id}/kaution-beleg/freigabe/', 'Kaution-Freigabe'),
                (f'/neu/vertraege/{self.v.id}/kaution-beleg/hinterlegung/', 'Kaution-Bestätigung'),
                (f'/neu/debitoren/{self.r.id}/qr-pdf/', 'Rechnung:'),
                (f'/neu/kuendigung/{self.k.id}/formular/', 'Kündigung')):
            with self.subTest(adresse=adresse):
                antwort = self.verwalter.post(adresse)
                self.assertEqual(antwort.status_code, 200)
                self.assertTrue(antwort.content.startswith(b'%PDF'))
                d = Dokument.objects.filter(vertrag=self.v, bezeichnung__startswith=titel).first()
                self.assertIsNotNone(d, f'{titel} wurde nicht abgelegt')
                self.assertFalse(d.im_portal_sichtbar,
                                 f'{titel} ist im Mieterportal sichtbar, obwohl nicht zugestellt')

    def test_abgeschlossenes_abnahmeprotokoll_wird_beim_erstellen_abgelegt_und_ist_sichtbar(self):
        """Das unterschriebene Protokoll liegt dem Mieter vor — sichtbar, aber nur nach POST."""
        self.verwalter.get(f'/neu/abnahme/{self.prot.id}/pdf/')
        self.assertFalse(Dokument.objects.filter(vertrag=self.v, kategorie='protokoll').exists())
        self.verwalter.post(f'/neu/abnahme/{self.prot.id}/pdf/')
        d = Dokument.objects.get(vertrag=self.v, kategorie='protokoll')
        self.assertTrue(d.im_portal_sichtbar)

    def test_lesezugriff_darf_nicht_per_post_ablegen(self):
        """ROUTE-18: «Nur Lesen» schreibt nicht — auch nicht über das Erstellen (POST)."""
        vorher = _zaehler()
        for adresse in (f'/neu/vertraege/{self.v.id}/kaution-beleg/freigabe/',
                        f'/neu/debitoren/{self.r.id}/qr-pdf/',
                        f'/neu/abnahme/{self.prot.id}/pdf/',
                        f'/neu/kuendigung/{self.k.id}/formular/',
                        f'/neu/betreibungen/{self.b.id}/pdf/'):
            with self.subTest(adresse=adresse):
                self.assertEqual(self.lesend.post(adresse).status_code, 403)
        self.assertEqual(_zaehler(), vorher)

    def test_lebensdauer_und_zwei_faktor_schreiben_beim_oeffnen_nichts(self):
        vorher = _zaehler()
        self.assertEqual(self.verwalter.get('/neu/lebensdauer/').status_code, 200)
        self.assertEqual(self.verwalter.get('/konto/zwei-faktor/einrichten/').status_code, 200)
        self.assertEqual(_zaehler(), vorher)


class GwrImportNurPostTests(TestCase):
    """ROUTE-07: Der GWR-Import ruft die Bundesdienste auf und legt Objekte an — nur per POST."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.benutzer = _team_user('Verwalter')
        self.c = Client()
        self.c.force_login(self.benutzer)
        self.url = f'/neu/liegenschaften/{self.lg.id}/gwr-import/'

    def test_get_loest_keinen_import_aus(self):
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr') as sync:
            antwort = self.c.get(self.url)
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], f'/neu/liegenschaften/{self.lg.id}/')
        sync.assert_not_called()

    def test_post_loest_den_import_aus(self):
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr',
                        return_value={}) as sync:
            self.c.post(self.url)
        sync.assert_called_once()

    def test_post_ohne_csrf_token_wird_abgewiesen(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.benutzer)
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr') as sync:
            antwort = c.post(self.url)
        self.assertEqual(antwort.status_code, 403)
        sync.assert_not_called()


class PortalSichtbarkeitStandardTests(TestCase):
    """Ein neues Dokument ist im Mieterportal unsichtbar, bis es zugestellt oder freigegeben ist."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def test_modellstandard_ist_unsichtbar(self):
        self.assertFalse(Dokument._meta.get_field('im_portal_sichtbar').default)

    def test_ablegen_ohne_angabe_ist_unsichtbar_mit_angabe_sichtbar(self):
        from core.services.ablage import ablegen
        verborgen = ablegen(b'%PDF-1.4 a', 'Intern A', vertrag=self.v)
        sichtbar = ablegen(b'%PDF-1.4 b', 'Zugestellt B', vertrag=self.v, im_portal_sichtbar=True)
        self.assertFalse(verborgen.im_portal_sichtbar)
        self.assertTrue(sichtbar.im_portal_sichtbar)

    def test_mahnung_ist_erst_mit_dem_versand_sichtbar(self):
        from core.services.ablage import ablage_mahnung
        beleg = ablage_mahnung(self.v, stufe=1, datum=date(2026, 10, 1), pdf_bytes=b'%PDF-1.4 m')
        versandt = ablage_mahnung(self.v, stufe=2, datum=date(2026, 10, 1), pdf_bytes=b'%PDF-1.4 n',
                                  im_portal_sichtbar=True)
        self.assertFalse(beleg.im_portal_sichtbar)
        self.assertTrue(versandt.im_portal_sichtbar)

    def test_neue_fassung_erbt_die_sichtbarkeit(self):
        from core.services.ablage import ablegen
        d1 = ablegen(b'%PDF-1.4 eins', 'Brief', vertrag=self.v, dedup=True, im_portal_sichtbar=True)
        d2 = ablegen(b'%PDF-1.4 zwei, anders', 'Brief', vertrag=self.v, dedup=True)
        self.assertNotEqual(d1.pk, d2.pk)
        self.assertTrue(d2.im_portal_sichtbar)

    def test_unterzeichneter_vertrag_ist_sichtbar(self):
        from core.services.ablage import ablage_signierter_vertrag
        d = ablage_signierter_vertrag(self.v, pdf_bytes=b'%PDF-1.4 signiert')
        self.assertTrue(d.im_portal_sichtbar)

    def test_datenmigration_blendet_nur_interne_schreiben_aus(self):
        """Die Migration 0053 nimmt Betreibungs-Datenblatt und Bankschreiben aus dem Portal —
        sonst nichts (Mahnungen lassen sich aus den Daten nicht sicher beurteilen)."""
        from core.services.ablage import ablegen
        migration = importlib.import_module('rentals.migrations.0053_interne_dokumente_im_portal_ausblenden')
        titel = ['Betreibungsbegehren (Daten) #1', 'Kaution-Freigabe (Bank) Muster',
                 'Kaution-Bestätigung Muster', '2. Mahnung vom 01.10.2026']
        for t in titel:
            ablegen(b'%PDF-1.4 ' + t.encode(), t, vertrag=self.v, im_portal_sichtbar=True)

        class _Apps:                       # die historische Fassung hat einen schlichten `objects`
            @staticmethod
            def get_model(app, name):
                return type('M', (), {'objects': Dokument.alle_organisationen})
        migration.ausblenden(_Apps, None)
        sichtbar = set(Dokument.objects.filter(im_portal_sichtbar=True).values_list('bezeichnung', flat=True))
        self.assertEqual(sichtbar, {'Kaution-Bestätigung Muster', '2. Mahnung vom 01.10.2026'})


class LebensdauerBeiAnlageTests(TestCase):
    def test_die_anlage_einer_verwaltung_fuellt_die_lebensdauertabelle(self):
        from core.services.onboarding import organisation_anlegen
        organisation, _benutzer, _neu = organisation_anlegen(
            'Neue Verwaltung AG', 'neu-inhaber', 'neu@example.ch', passwort='geheim-12345')
        self.assertGreater(
            Lebensdauer.alle_organisationen.filter(organisation=organisation).count(), 60)
        self.assertTrue(Lebensdauer.alle_organisationen.filter(
            organisation=organisation, kategorie='Backofen').exists())
