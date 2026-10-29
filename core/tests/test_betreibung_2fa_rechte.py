"""Betreibung und Zwei-Faktor-Pflicht: nur Verwalter und Inhaber (Etappe 2).

SICH-11: Das Rollenkonzept (`docs/KONZEPT-UI.md` §8) sagt «Mahnlauf und
Betreibung: Inhaber, Verwalter». Im Bestand durfte jede Schreibrolle ein
Betreibungsbegehren einleiten, nachführen und Kosten belasten.

SICH-10: Den Pflichtschalter der Zwei-Faktor-Anmeldung durfte jede Schreibrolle
umlegen, auch der Sachbearbeiter; wer sein Konto übernahm, hob die einzige
organisationsweite Sicherheitsrichtlinie auf. Zudem war der Faktor nur Pflicht,
wenn die Verwaltung den Schalter gesetzt hatte: Rollen, die Zahlungen auslösen
und Betreibungen einleiten, konnten ohne ihn arbeiten.

Gegenprobe je Test: die Dekoratoren/Prüfungen auf den alten Stand (SCHREIB_ROLLEN)
zurückstellen, dann sind die Sperrprüfungen rot.
"""
from django.test import override_settings
from django.urls import reverse

from core.models import ZweiterFaktor
from core.services import totp

from ._rollen import RollenBasis


class BetreibungNurVerwaltungTests(RollenBasis):

    def _urls(self):
        b = self.a.betreibung
        return {
            'neu': f'/neu/betreibungen/neu/{self.a.debitor.pk}/',
            'bearbeiten': f'/neu/betreibungen/{b.pk}/',
            'kosten': f'/neu/betreibungen/{b.pk}/kosten/',
        }

    def test_ohne_verwaltungsrolle_ist_jede_betreibungshandlung_gesperrt(self):
        for rolle in ('sachbearbeiter', 'buchhaltung', 'lesezugriff', 'hauswart'):
            c = self.client_von(rolle)
            for name, url in self._urls().items():
                with self.subTest(rolle=rolle, aktion=name, methode='GET'):
                    self.assertEqual(c.get(url).status_code, 403)
                with self.subTest(rolle=rolle, aktion=name, methode='POST'):
                    self.assertEqual(c.post(url, {}).status_code, 403)

    def test_gesperrte_handlung_aendert_nichts(self):
        from core.tenancy import organisation_kontext
        from finance.models import Betreibung
        b = self.a.betreibung
        with organisation_kontext(self.org):
            vorher = (Betreibung.objects.count(), b.status)
        self.client_von('sachbearbeiter').post(
            f'/neu/betreibungen/{b.pk}/', {'status': 'verlustschein'})
        self.client_von('sachbearbeiter').post(f'/neu/betreibungen/{b.pk}/kosten/', {})
        with organisation_kontext(self.org):
            b.refresh_from_db()
            self.assertEqual((Betreibung.objects.count(), b.status), vorher)

    def test_gegenprobe_verwaltung_erreicht_die_handlungen(self):
        for rolle in ('verwalter', 'inhaber'):
            c = self.client_von(rolle)
            for name, url in self._urls().items():
                if name == 'kosten':
                    continue        # POST-only: Sperre allein prüft die Rolle, nicht den Ablauf
                with self.subTest(rolle=rolle, aktion=name):
                    self.assertNotEqual(c.get(url).status_code, 403)

    def test_datenblatt_vorschau_fuer_die_schreibrolle_ablegen_nur_verwaltung(self):
        """GET (Vorschau) bleibt der Schreibrolle; POST legt das Blatt in der Akte ab: Verwaltung."""
        from core.tenancy import organisation_kontext
        from rentals.models import Dokument
        url = f'/neu/betreibungen/{self.a.betreibung.pk}/pdf/'
        self.assertEqual(self.client_von('sachbearbeiter').get(url).status_code, 200)
        with organisation_kontext(self.org):
            vorher = Dokument.objects.count()
        self.assertEqual(self.client_von('sachbearbeiter').post(url).status_code, 403)
        with organisation_kontext(self.org):
            self.assertEqual(Dokument.objects.count(), vorher)
        self.assertEqual(self.client_von('verwalter').post(url).status_code, 200)
        with organisation_kontext(self.org):
            self.assertEqual(Dokument.objects.count(), vorher + 1)

    def test_die_liste_bleibt_dem_team_lesbar(self):
        for rolle in ('sachbearbeiter', 'lesezugriff', 'verwalter'):
            with self.subTest(rolle=rolle):
                self.assertEqual(self.client_von(rolle).get('/neu/betreibungen/').status_code, 200)

    def test_knopf_betreibung_einleiten_fehlt_ohne_recht(self):
        """Der Knopf im Vertrag/Mahnwesen folgt dem Dekorator (`|darf`), keine tote Aktion."""
        from core.auth import darf_oeffnen, eigene_rollen
        from core.tenancy import organisation_kontext
        pfad = '/neu/betreibungen/neu/1/'
        with organisation_kontext(self.org):
            for rolle, soll in (('sachbearbeiter', False), ('buchhaltung', False),
                                ('verwalter', True), ('inhaber', True)):
                u = self.benutzer[rolle]
                with self.subTest(rolle=rolle):
                    self.assertEqual(darf_oeffnen(u, pfad, eigene_rollen(u)), soll)


class ZweifaktorSchalterTests(RollenBasis):

    def _faktor(self, benutzer):
        from django.utils import timezone
        return ZweiterFaktor.objects.create(
            benutzer=benutzer, geheimnis=totp.geheimnis_erzeugen(), bestaetigt_am=timezone.now())

    def _setze(self, rolle, wert):
        c = self.client_von(rolle)
        return c.post(reverse('zweifaktor_pflicht_setzen'), {'pflicht': wert})

    def _pflicht(self):
        self.org.refresh_from_db()
        return self.org.zweifaktor_pflicht

    def test_sachbearbeiter_hebt_die_pflicht_nicht_auf(self):
        self.org.zweifaktor_pflicht = True
        self.org.save(update_fields=['zweifaktor_pflicht'])
        self._faktor(self.benutzer['sachbearbeiter'])
        self._setze('sachbearbeiter', 'aus')
        self.assertTrue(self._pflicht())

    def test_sachbearbeiter_setzt_die_pflicht_nicht(self):
        self._faktor(self.benutzer['sachbearbeiter'])
        self._setze('sachbearbeiter', 'an')
        self.assertFalse(self._pflicht())

    def test_buchhaltung_und_lesezugriff_stellen_den_schalter_nicht(self):
        for rolle in ('buchhaltung', 'lesezugriff', 'hauswart'):
            self._faktor(self.benutzer[rolle])
            with self.subTest(rolle=rolle):
                self._setze(rolle, 'an')
                self.assertFalse(self._pflicht())

    def test_gegenprobe_verwalter_und_inhaber_stellen_den_schalter(self):
        for rolle in ('verwalter', 'inhaber'):
            self._faktor(self.benutzer[rolle])
            with self.subTest(rolle=rolle):
                self._setze(rolle, 'an')
                self.assertTrue(self._pflicht())
                self._setze(rolle, 'aus')
                self.assertFalse(self._pflicht())

    def test_aenderung_steht_im_protokoll(self):
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext
        self._faktor(self.benutzer['verwalter'])
        self._setze('verwalter', 'an')
        with organisation_kontext(self.org):
            eintrag = AktivitaetsLog.objects.filter(aktion__startswith='Zwei-Faktor-Pflicht').first()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.benutzer, self.benutzer['verwalter'])

    def test_uebersicht_zeigt_den_schalter_nur_der_verwaltung(self):
        for rolle, soll in (('sachbearbeiter', False), ('verwalter', True), ('inhaber', True)):
            with self.subTest(rolle=rolle):
                antwort = self.client_von(rolle).get(reverse('zweifaktor_uebersicht'))
                self.assertEqual(antwort.status_code, 200)
                self.assertEqual(bool(antwort.context['darf_verwalten']), soll)


@override_settings(ZWEIFAKTOR_ROLLENPFLICHT=True)
class ZweifaktorPflichtNachRolleTests(RollenBasis):
    """Wer Zahlungen auslöst oder Betreibungen einleitet, braucht den zweiten Faktor,
    auch wenn die Verwaltung den Schalter nie gesetzt hat."""

    def _faktor(self, benutzer):
        from django.utils import timezone
        return ZweiterFaktor.objects.create(
            benutzer=benutzer, geheimnis=totp.geheimnis_erzeugen(), bestaetigt_am=timezone.now())

    def test_finanz_und_betreibungsrollen_werden_zur_einrichtung_geleitet(self):
        for rolle in ('inhaber', 'verwalter', 'buchhaltung'):
            with self.subTest(rolle=rolle):
                antwort = self.client_von(rolle).get('/neu/finanzen/')
                self.assertEqual(antwort.status_code, 302)
                self.assertEqual(antwort['Location'], reverse('zweifaktor_einrichten'))

    def test_gegenprobe_sachbearbeiter_und_lesezugriff_nicht_ohne_schalter(self):
        for rolle in ('sachbearbeiter', 'lesezugriff'):
            with self.subTest(rolle=rolle):
                antwort = self.client_von(rolle).get('/neu/finanzen/')
                self.assertNotEqual(antwort.get('Location', ''), reverse('zweifaktor_einrichten'))

    def test_mit_aktivem_faktor_geht_es_weiter(self):
        for rolle in ('inhaber', 'verwalter', 'buchhaltung'):
            self._faktor(self.benutzer[rolle])
            with self.subTest(rolle=rolle):
                antwort = self.client_von(rolle).get('/neu/finanzen/')
                self.assertEqual(antwort.status_code, 200)

    def test_der_faktor_laesst_sich_in_diesen_rollen_nicht_abschalten(self):
        from django.test import Client
        u = self.benutzer['buchhaltung']
        u.set_password('geheim-123')
        u.save()
        self._faktor(u)
        c = Client()
        c.force_login(u)
        c.post(reverse('zweifaktor_aus'), {'password': 'geheim-123'})
        self.assertTrue(ZweiterFaktor.objects.filter(benutzer=u).exists())

    def test_pflicht_gilt_ueber_die_organisation_hinaus_fuer_das_konto(self):
        """Eine Person mit Finanzrolle in B und Sachbearbeiter in A bleibt pflichtig."""
        from core.views.zweifaktor import _pflicht_fuer
        from crm.models import Mitgliedschaft
        u = self.benutzer['sachbearbeiter']
        self.assertFalse(_pflicht_fuer(u))
        Mitgliedschaft.alle_organisationen.create(
            benutzer=u, organisation=self.b.organisation, rolle='Verwalter')
        self.assertTrue(_pflicht_fuer(u))

    @override_settings(ZWEIFAKTOR_ROLLENPFLICHT=False)
    def test_schalter_in_der_konfiguration_nimmt_die_rollenpflicht_weg(self):
        """Notausgang für den Betrieb (Einführung, Test); die Organisationspflicht bleibt."""
        antwort = self.client_von('verwalter').get('/neu/finanzen/')
        self.assertEqual(antwort.status_code, 200)
        self.org.zweifaktor_pflicht = True
        self.org.save(update_fields=['zweifaktor_pflicht'])
        antwort = self.client_von('verwalter').get('/neu/finanzen/')
        self.assertEqual(antwort['Location'], reverse('zweifaktor_einrichten'))
