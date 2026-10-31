"""Funktionsfreigabe: eine Prüfstelle, Sperrseite statt 403, Daten bleiben.

Jeder Sperrtest hat seine Gegenprobe im selben Test: dieselbe Anfrage mit
Freigabe muss durchgehen. Ein Test, der auch ohne Entitlement grün wäre,
prüfte nichts (bekannte-fallen, Punkt 12).
"""
import pathlib
import re
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import get_resolver

from abo import zugang
from abo.dienst import plan_wechseln
from abo.models import Abonnement
from core import funktionen as f
from core.tenancy import organisation_kontext
from core.tests._isolation import MandantenFixture

User = get_user_model()


def _strikt(organisation, stufe, **felder):
    """Macht die Verwaltung zu einer verwalteten: Stufe gesetzt, kein Bestandsschutz."""
    organisation.abo_plan = stufe
    organisation.save(update_fields=['abo_plan'])
    abo, _neu = Abonnement.alle_organisationen.update_or_create(
        organisation=organisation, defaults={'uneingeschraenkt': False, 'zusatzmodule': [], **felder})
    organisation.refresh_from_db()           # verwirft auch die zwischengespeicherte Abonnement-Zeile
    return abo


class Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Das Isolationsfixture legt je Verwaltung eine Abo-Rechnung an; diese Tests bauen ihre eigenen.
        from abo.models import AboRechnung
        AboRechnung.alle_organisationen.all().delete()

    def _client(self, bestand=None):
        bestand = bestand or self.a
        c = Client()
        c.force_login(bestand.benutzer)
        return c

    def _abo(self, stufe, bestand=None, **felder):
        bestand = bestand or self.a
        return _strikt(bestand.organisation, stufe, **felder)


class PruefstelleTests(Basis):
    """Eine Stelle entscheidet; der Merkmalsname zählt, nicht die Stufe."""

    def test_ohne_abonnement_bleibt_alles_wie_bisher(self):
        Abonnement.alle_organisationen.filter(organisation=self.a.organisation).delete()
        org = type(self.a.organisation).objects.get(pk=self.a.organisation.pk)
        self.assertTrue(f.hat_funktion(org, 'stweg'))
        self.assertTrue(f.hat_funktion(org, 'signatur'))
        self.assertTrue(f.darf_schreiben(org))
        self.assertIsNone(f.anlege_grenze(org, 'einheiten'))

    def test_stufe_start_sperrt_die_modulmerkmale_team_gibt_sie_frei(self):
        self._abo('start')
        org = self.a.organisation
        for schluessel in ('stweg', 'betreibung', 'datenimport', 'eigentuemerportal'):
            self.assertFalse(f.hat_funktion(org, schluessel), schluessel)
        self.assertTrue(f.hat_funktion(org, 'datenexport'))
        self.assertTrue(f.hat_funktion(org, 'monatslauf'))
        # Gegenprobe: dieselbe Frage nach dem Planwechsel.
        plan_wechseln(org, 'team', False)
        for schluessel in ('stweg', 'betreibung', 'datenimport', 'eigentuemerportal'):
            self.assertTrue(f.hat_funktion(org, schluessel), schluessel)

    def test_zubuchung_schaltet_einzelnes_merkmal_frei(self):
        self._abo('start', zusatzmodule=['stweg'])
        org = self.a.organisation
        self.assertTrue(f.hat_funktion(org, 'stweg'))
        self.assertFalse(f.hat_funktion(org, 'betreibung'))

    def test_module_nur_wenn_zugebucht(self):
        self._abo('professional')
        org = self.a.organisation
        for schluessel in f.MODULE:
            self.assertFalse(f.hat_funktion(org, schluessel), schluessel)
        self._abo('professional', zusatzmodule=['signatur'])
        self.assertTrue(f.hat_funktion(self.a.organisation, 'signatur'))
        self.assertFalse(f.hat_funktion(self.a.organisation, 'belegerkennung'))

    def test_bestandsschutz_oeffnet_alles_bis_zur_planwahl(self):
        self._abo('start', uneingeschraenkt=True)
        org = self.a.organisation
        self.assertTrue(f.hat_funktion(org, 'stweg'))
        self.assertTrue(f.hat_funktion(org, 'signatur'))
        self.assertIsNone(f.anlege_grenze(org, 'einheiten'))
        plan_wechseln(org, 'start', False)
        self.assertFalse(f.hat_funktion(org, 'stweg'))
        self.assertEqual(f.anlege_grenze(org, 'einheiten'), f.PREISE['start']['deckel'])

    def test_unbekanntes_merkmal_wirft(self):
        with self.assertRaises(f.UnbekannteFunktion):
            f.hat_funktion(self.a.organisation, 'stwegg')

    def test_kein_planvergleich_im_uebrigen_code(self):
        """Grep-Abnahme: Wer die Stufe vergleicht, statt ein Merkmal zu fragen, fällt hier auf."""
        wurzel = pathlib.Path(settings.BASE_DIR)
        muster = re.compile(r"""(abo_plan\s*(==|!=)\s*['"]|abo_plan\s+in\s*[\(\[\{]|stufe_von\([^)]*\)\s*(==|!=|in)\s)""")
        treffer = []
        for pfad in wurzel.rglob('*.py'):
            teile = pfad.relative_to(wurzel).parts
            if ('migrations' in teile or 'tests' in teile or pfad.name.startswith('test')
                    or pfad.name == 'funktionen.py' or teile[0] in ('node_modules', '.claude', 'venv', '.venv')):
                continue
            for nr, zeile in enumerate(pfad.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
                if muster.search(zeile):
                    treffer.append(f'{pfad.relative_to(wurzel)}:{nr}: {zeile.strip()}')
        self.assertEqual(treffer, [], 'Planvergleich ausserhalb core/funktionen.py — ein Merkmal abfragen.')

    def test_der_wachter_findet_einen_planvergleich(self):
        """Gegenprobe zum Grep: das Muster erkennt die Fehlerform wirklich."""
        muster = re.compile(r"""(abo_plan\s*(==|!=)\s*['"]|abo_plan\s+in\s*[\(\[\{]|stufe_von\([^)]*\)\s*(==|!=|in)\s)""")
        self.assertTrue(muster.search("if org.abo_plan == 'premium':"))
        self.assertTrue(muster.search("if stufe_von(org) in ('team', 'professional'):"))


class SperrseiteTests(Basis):
    """Gesperrt heisst: klare Seite, Daten lesbar, nichts gelöscht."""

    def test_stweg_start_liest_ja_schreibt_nein(self):
        self._abo('start')
        c = self._client()
        lesen = c.get('/neu/stweg/')
        self.assertNotEqual(lesen.status_code, 402, 'Lesen muss durchgehen')
        self.assertContains(lesen, 'nicht im Abonnement')            # Banner mit dem Weg zum Upgrade
        self.assertContains(lesen, '/neu/abonnement/')
        schreiben = c.post('/neu/stweg/1/aufgabe/neu/', {})
        self.assertEqual(schreiben.status_code, 402)
        self.assertContains(schreiben, 'nicht im Abonnement', status_code=402)
        self.assertContains(schreiben, '/neu/abonnement/', status_code=402)
        # Gegenprobe: mit Freigabe kommt die Anfrage bis zur View.
        plan_wechseln(self.a.organisation, 'team', False)
        self.assertNotEqual(c.post('/neu/stweg/1/aufgabe/neu/', {}).status_code, 402)

    def test_betreibung_start_liest_ja_schreibt_nein(self):
        self._abo('start')
        c = self._client()
        self.assertEqual(c.get('/neu/betreibungen/').status_code, 200)
        self.assertEqual(c.post(f'/neu/betreibungen/neu/{self.a.debitor.pk}/', {}).status_code, 402)
        plan_wechseln(self.a.organisation, 'team', False)
        self.assertNotEqual(c.post(f'/neu/betreibungen/neu/{self.a.debitor.pk}/', {}).status_code, 402)

    def test_datenimport_ist_ganz_gesperrt_export_bleibt_offen(self):
        self._abo('start')
        c = self._client()
        self.assertEqual(c.get('/neu/einstellungen/daten/import/').status_code, 402)
        self.assertEqual(c.get('/neu/einstellungen/daten/export/').status_code, 200)
        plan_wechseln(self.a.organisation, 'team', False)
        self.assertEqual(c.get('/neu/einstellungen/daten/import/').status_code, 200)

    def test_eigentuemerportal_gesperrt_zeigt_dem_eigentuemer_keinen_verkaufstext(self):
        konto = User.objects.create_user(username='eig_portal', password='x')
        with organisation_kontext(self.a.organisation):
            self.a.eigentuemer.benutzer = konto
            self.a.eigentuemer.save()
        self._abo('start')
        c = Client()
        c.force_login(konto)
        antwort = c.get('/portal/')
        self.assertEqual(antwort.status_code, 402)
        self.assertNotContains(antwort, '/neu/abonnement/', status_code=402)
        self.assertContains(antwort, 'nicht freigeschaltet', status_code=402)
        # Gegenprobe
        plan_wechseln(self.a.organisation, 'team', False)
        self.assertNotEqual(c.get('/portal/').status_code, 402)

    def test_anmeldung_des_portals_bleibt_erreichbar(self):
        self._abo('start')
        self.assertEqual(Client().get('/portal/login/').status_code, 200)

    def test_jeder_schreibweg_der_module_ist_gesperrt(self):
        """Vollständigkeit: ALLE Routen unter den lesenden Präfixen sperren das Schreiben.

        Ein Eintrag in der Tabelle schützt nur, was er trifft; dieser Lauf probiert jede
        registrierte Route aus, auch die, die erst ein späterer Auftrag dazubaut.
        """
        self._abo('start')
        c = self._client()
        geprueft = 0
        for route in _alle_routen():
            schluessel, lesen = zugang.modul_fuer_pfad(route)
            if not schluessel or schluessel in ('datenexport', 'mieterportal'):
                continue
            geprueft += 1
            with self.subTest(route=route):
                self.assertEqual(c.post(route, {}).status_code, 402, route)
        self.assertGreater(geprueft, 40, 'zu wenige Routen gefunden — Lauf prüft nichts')

    def test_navigation_kennzeichnet_gesperrte_eintraege(self):
        self._abo('start')
        c = self._client()
        self.assertContains(c.get('/neu/liegenschaften/'), 'fw-abo-schloss')
        plan_wechseln(self.a.organisation, 'team', False)
        self.assertNotContains(c.get('/neu/liegenschaften/'), 'fw-abo-schloss')

    def test_superuser_ist_nicht_gesperrt(self):
        self._abo('start')
        su = User.objects.create_superuser('root_abo', 'r@example.ch', 'x')
        from crm.models import Mitgliedschaft
        Mitgliedschaft.alle_organisationen.create(benutzer=su, organisation=self.a.organisation, rolle='Inhaber')
        c = Client()
        c.force_login(su)
        self.assertNotEqual(c.post('/neu/stweg/1/aufgabe/neu/', {}).status_code, 402)

    def test_dekorator_sperrt_und_merkt_sich_das_merkmal(self):
        @zugang.funktion_erforderlich('stweg')
        def ansicht(request):
            from django.http import HttpResponse
            return HttpResponse('ok')

        self.assertEqual(ansicht.benoetigtes_merkmal, 'stweg')
        from django.test import RequestFactory
        anfrage = RequestFactory().get('/x/')
        anfrage.user = self.a.benutzer
        self._abo('start')
        with organisation_kontext(self.a.organisation):
            self.assertEqual(ansicht(anfrage).status_code, 402)
        plan_wechseln(self.a.organisation, 'team', False)
        with organisation_kontext(self.a.organisation):
            self.assertEqual(ansicht(anfrage).status_code, 200)

    def test_dekorator_lehnt_tippfehler_beim_import_ab(self):
        with self.assertRaises(f.UnbekannteFunktion):
            zugang.funktion_erforderlich('stwegg')


def _alle_routen():
    """Alle Routen der URL-Konfiguration mit eingesetzten Platzhaltern (`1`)."""
    def gehe(patterns, vorne):
        for p in patterns:
            roh = vorne + str(p.pattern)
            if hasattr(p, 'url_patterns'):
                yield from gehe(p.url_patterns, roh)
            else:
                yield '/' + re.sub(r'<[^>]+>', '1', roh).replace('^', '').replace('$', '')
    return list(gehe(get_resolver().url_patterns, ''))


class ModulkarteTests(TestCase):
    def test_alle_schluessel_der_tabelle_stehen_im_katalog(self):
        for praefix, schluessel, _lesen in zugang.PFAD_MODULE:
            if schluessel is not None:
                with self.subTest(praefix=praefix):
                    self.assertFalse(f.hat_funktion(None, schluessel))     # wirft bei unbekanntem Schlüssel, sonst False

    def test_praefixe_stehen_in_der_richtigen_reihenfolge(self):
        """Die Ausnahme der Anmeldung muss VOR dem Portalpräfix stehen, sonst sperrt sie sich selbst."""
        praefixe = [p for p, _s, _l in zugang.PFAD_MODULE]
        self.assertLess(praefixe.index('/portal/login/'), praefixe.index('/portal/'))
        self.assertLess(praefixe.index('/portal/stweg/'), praefixe.index('/portal/'))


class PlanwechselTests(Basis):

    def test_downgrade_zeigt_folgen_und_aendert_erst_nach_bestaetigung(self):
        self._abo('team')
        c = self._client()
        antwort = c.post('/neu/abonnement/', {'plan': 'start'})
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Stockwerkeigentum')
        self.a.organisation.refresh_from_db()
        self.assertEqual(self.a.organisation.abo_plan, 'team')
        antwort = c.post('/neu/abonnement/', {'plan': 'start', 'bestaetigt': '1'})
        self.assertEqual(antwort.status_code, 302)
        self.a.organisation.refresh_from_db()
        self.assertEqual(self.a.organisation.abo_plan, 'start')

    def test_downgrade_schliesst_die_module_daten_bleiben(self):
        from portfolio.models import Einheit
        self._abo('team')
        c = self._client()
        vorher = Einheit.alle_organisationen.filter(organisation=self.a.organisation).count()
        self.assertNotEqual(c.post('/neu/stweg/1/aufgabe/neu/', {}).status_code, 402)
        c.post('/neu/abonnement/', {'plan': 'start', 'bestaetigt': '1'})
        self.assertEqual(c.post('/neu/stweg/1/aufgabe/neu/', {}).status_code, 402)
        self.assertEqual(Einheit.alle_organisationen.filter(organisation=self.a.organisation).count(), vorher)
        self.assertEqual(c.get('/neu/liegenschaften/').status_code, 200)
        self.assertEqual(c.get('/neu/stweg/').status_code, 200)

    def test_nur_intervall_umstellen_beendet_den_bestandsschutz_nicht(self):
        self._abo('team', uneingeschraenkt=True)
        c = self._client()
        c.post('/neu/abonnement/', {'plan': 'team', 'intervall_nur': '1', 'jaehrlich': 'on'})
        self.a.organisation.refresh_from_db()
        self.assertTrue(self.a.organisation.abo_jaehrlich)
        self.assertTrue(Abonnement.alle_organisationen.get(organisation=self.a.organisation).uneingeschraenkt)

    def test_plan_nur_inhaber(self):
        from core.tests._helfer import _team_user
        self._abo('team')
        c = Client()
        with organisation_kontext(self.a.organisation):
            u = _team_user('Sachbearbeiter')
        from crm.models import Mitgliedschaft
        Mitgliedschaft.alle_organisationen.filter(benutzer=u).exclude(organisation=self.a.organisation).delete()
        Mitgliedschaft.alle_organisationen.update_or_create(
            benutzer=u, defaults={'organisation': self.a.organisation, 'rolle': 'Sachbearbeiter'})
        c.force_login(u)
        c.post('/neu/abonnement/', {'plan': 'start', 'bestaetigt': '1'})
        self.a.organisation.refresh_from_db()
        self.assertEqual(self.a.organisation.abo_plan, 'team')


class GrenzenTests(Basis):
    """Die Grenze begrenzt das ANLEGEN, nie das Bestehende."""

    def _einheit(self, name):
        from portfolio.models import Einheit
        with organisation_kontext(self.a.organisation):
            return Einheit.objects.create(liegenschaft=self.a.liegenschaft, bezeichnung=name, typ='whg')

    def test_grenze_greift_beim_anlegen_nicht_beim_bestand(self):
        from portfolio.models import Einheit
        bestand = Einheit.alle_organisationen.filter(organisation=self.a.organisation).count()
        with mock.patch.dict(f.PREISE['start'], {'deckel': bestand}):
            self._abo('start')
            with self.assertRaises(f.GrenzeErreicht) as fehler:
                self._einheit('X1')
            self.assertEqual(fehler.exception.was, 'einheiten')
            # Bestehendes bleibt les- und änderbar.
            vorhanden = Einheit.alle_organisationen.filter(organisation=self.a.organisation).first()
            vorhanden.etage = 'EG'
            with organisation_kontext(self.a.organisation):
                vorhanden.save()
            self.assertEqual(self._client().get('/neu/liegenschaften/').status_code, 200)
            # Gegenprobe 1: Bestandsschutz hebt die Grenze auf.
            Abonnement.alle_organisationen.filter(organisation=self.a.organisation).update(uneingeschraenkt=True)
            self.assertTrue(self._einheit('X2').pk)
            # Gegenprobe 2: eine weitere Stufe ohne Grenze.
            Abonnement.alle_organisationen.filter(organisation=self.a.organisation).update(uneingeschraenkt=False)
            plan_wechseln(self.a.organisation, 'enterprise', False)
            self.assertTrue(self._einheit('X3').pk)

    def test_bestand_ueber_der_grenze_bleibt_vollstaendig_erreichbar(self):
        from portfolio.models import Einheit
        for i in range(3):
            self._einheit(f'Z{i}')
        anzahl = Einheit.alle_organisationen.filter(organisation=self.a.organisation).count()
        with mock.patch.dict(f.PREISE['start'], {'deckel': 1}):
            self._abo('start')
            self.assertEqual(Einheit.alle_organisationen.filter(organisation=self.a.organisation).count(), anzahl)
            c = self._client()
            self.assertEqual(c.get('/neu/liegenschaften/').status_code, 200)
            self.assertEqual(c.get('/neu/objekte/').status_code, 200)
            seite = c.get('/neu/abonnement/')
            self.assertContains(seite, 'über der Grenze')

    def test_nutzergrenze(self):
        from crm.models import Mitgliedschaft
        self._abo('start')                                    # 2 Nutzer
        u2 = User.objects.create_user(username='zweiter', password='x')
        u3 = User.objects.create_user(username='dritter', password='x')
        Mitgliedschaft.alle_organisationen.create(benutzer=u2, organisation=self.a.organisation, rolle='Verwalter')
        with self.assertRaises(f.GrenzeErreicht) as fehler:
            Mitgliedschaft.alle_organisationen.create(benutzer=u3, organisation=self.a.organisation, rolle='Verwalter')
        self.assertEqual(fehler.exception.was, 'nutzer')
        # Gegenprobe: andere Verwaltung mit Platz, gleiche Person.
        Mitgliedschaft.alle_organisationen.create(benutzer=u3, organisation=self.b.organisation, rolle='Verwalter')

    def test_view_zeigt_grenzseite_statt_fehler(self):
        """Die Ausnahme wird zur klaren Seite (Middleware), nicht zur 500."""
        from django.http import HttpResponse
        from django.test import RequestFactory
        from abo.middleware import AboMiddleware
        anfrage = RequestFactory().post('/x/')
        anfrage.user = self.a.benutzer
        antwort = AboMiddleware(lambda r: HttpResponse()).process_exception(anfrage, f.GrenzeErreicht('einheiten', 25))
        self.assertEqual(antwort.status_code, 402)
        self.assertIn('Grenze der Stufe', antwort.content.decode())

    def test_nutzungszaehler_auf_der_abo_seite(self):
        self._abo('start')
        seite = self._client().get('/neu/abonnement/')
        self.assertContains(seite, '<progress')
        self.assertEqual(seite.status_code, 200)


class ModulBindungTests(Basis):
    """Signatur und Belegerkennung: gesperrt heisst, es geht nichts an den Fremddienst."""

    def test_signatur_ohne_modul_sendet_nichts(self):
        from core.services.docuseal_service import docuseal_senden
        self._abo('professional')
        with override_settings(DOCUSEAL_API_KEY='x'), mock.patch('requests.post') as post:
            ok, meldung = docuseal_senden(self.a.vertrag)
        self.assertFalse(ok)
        self.assertIn('Abonnement', meldung)
        post.assert_not_called()
        # Gegenprobe: gebucht → der Dienst läuft weiter (scheitert hier erst an der Mieter-Mail oder am Versand).
        self._abo('professional', zusatzmodule=['signatur'])
        from rentals.models import Mietvertrag
        vertrag = Mietvertrag.alle_organisationen.get(pk=self.a.vertrag.pk)    # frisch: ohne alte Abo-Zeile im Speicher
        with override_settings(DOCUSEAL_API_KEY='x'), mock.patch('requests.post', side_effect=RuntimeError('kein Netz im Test')):
            ok, meldung = docuseal_senden(vertrag)
        self.assertNotIn('im Abonnement nicht enthalten', meldung)

    def test_belegerkennung_ohne_modul_ruft_die_ki_nicht(self):
        from finance import utils
        self._abo('professional')
        with organisation_kontext(self.a.organisation), mock.patch.object(utils, '_scan_basis') as scan, \
                mock.patch.object(utils, '_qr_rechnung_dekodieren', return_value=None):
            scan.return_value = utils._leer('ki', '')
            ergebnis = utils.scan_beleg('/tmp/gibt-es-nicht.pdf')
            self.assertEqual(ergebnis['methode'], 'gesperrt')
            scan.assert_not_called()
            # Gegenprobe: mit Modul läuft der Scan.
            self._abo('professional', zusatzmodule=['belegerkennung'])
            utils.scan_beleg('/tmp/gibt-es-nicht.pdf')
            scan.assert_called_once()


class MigrationTests(Basis):

    def test_bestehende_verwaltungen_bekommen_bestandsschutz(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module('abo.migrations.0002_bestandsschutz_bestehender_verwaltungen')
        Abonnement.alle_organisationen.all().delete()

        class _Apps:
            """Die Migration fragt `Modell.objects`; die echten Modelle brauchen dafür den benannten Weg."""
            def get_model(self, app, name):
                modell = apps.get_model(app, name)
                if name == 'Abonnement':
                    return type('Hist', (), {'objects': modell.alle_organisationen})
                return modell
        migration.vorwaerts(_Apps(), None)
        abo = Abonnement.alle_organisationen.get(organisation=self.a.organisation)
        self.assertTrue(abo.uneingeschraenkt)
        self.assertEqual(sorted(abo.zusatzmodule), sorted(f.MODULE))
        self.assertIsNone(abo.abrechnung_ab, 'es darf nichts ohne Entscheid des Betreibers abgerechnet werden')

    def test_onboarding_legt_abonnement_ohne_bestandsschutz_an(self):
        from core.services.onboarding import organisation_anlegen
        organisation_anlegen(firma='Neu AG', benutzername='neu_inhaber', email='n@example.ch', passwort='Sehr-geheim-123')
        from crm.models import Organisation
        neu = Organisation.objects.get(firma='Neu AG')
        abo = Abonnement.alle_organisationen.get(organisation=neu)
        self.assertFalse(abo.uneingeschraenkt)
        self.assertEqual(abo.zusatzmodule, [])
