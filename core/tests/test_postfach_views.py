"""Die Postfach-Oberfläche — Rollen, Geheimnisse, Verbindungstest.

DREI ZUSAGEN, DIE HIER GEPRÜFT WERDEN

1. **Das gespeicherte Geheimnis erscheint nie im HTML.** Weder als `value`,
   noch als Sternchenkette, noch als Länge. Geprüft wird gegen den
   Antwort-Rumpf, nicht gegen die Absicht.
2. **Ein leeres Passwortfeld heisst «unverändert».** Sonst löscht jemand beim
   Ändern der Portnummer den Zugang, und der Ausfall fällt erst nachts auf.
3. **Ändern dürfen nur Inhaber und Verwalter.** Sachbearbeitung und
   Lesezugriff sehen den Zustand, ändern aber nichts.

GEGENPROBEN (durchgeführt 18.08.2026, jede einzeln zurückgenommen)

    postfach.py, _speichern():  `if neues_passwort:` → immer setzen
      → test_leeres_passwortfeld_laesst_das_geheimnis_stehen   FAIL

    postfach.py:  `_nur_aenderer` in postfach_form entfernt
      → test_sachbearbeitung_darf_nicht_aendern                FAIL

    postfach_form.html:  value="…" am Passwortfeld ergänzt
      → test_das_geheimnis_steht_nie_im_formular               FAIL

WAS DIESE TESTS NICHT GESEHEN HABEN (18.08.2026)

Alle 22 waren beim ersten Lauf grün — und die Rollenprüfung war trotzdem
falsch gebaut. Die erste Fassung hatte **alle** Views auf
`@rolle_erforderlich(*TEAM_ROLLEN)` und prüfte im Rumpf nach. Verhalten
richtig, Deklaration falsch: `darf_oeffnen` und jeder Prüflauf lesen die
Rollen am Dekorator ab, nicht im Rumpf.

Gefunden hat es nicht dieser Testsatz, sondern der Registrylauf in
`core/tests/test_sicherheit.py`:

    - ['postfach_form (core/views/postfach.py)']
    + [] : Für ALLE Team-Rollen schreibbar, auch «Lesend»

Der Grund, warum es hier durchrutschte: Diese Tests fragen «wird jemand
abgewiesen?». Der Registrylauf fragt «steht es auch dran?». Ein Test sieht
nur, wonach er fragt — und das Verhalten allein zu prüfen, reichte nicht.
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Postfach
from core.services.geheimnis import UMGEBUNGSNAME
from core.tests._helfer import _team_user, _test_organisation

SCHLUESSEL = '8NJHVucA9G85uCfVM9egyKhlrIDS1sqoXRa0D9ghqCA='
GEHEIM = 'streng-geheimes-postfachpasswort'


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class PostfachOberflaecheTests(TestCase):

    def setUp(self):
        self.organisation = _test_organisation()
        self.verwalter = _team_user('Verwaltung')
        self.client.force_login(self.verwalter)

    def _anlegen(self, **felder):
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='r@example.ch',
                            **felder)
        postfach.passwort = GEHEIM
        postfach.save()
        return postfach

    # -- Anzeige -------------------------------------------------------

    def test_liste_zeigt_beide_zwecke_auch_ohne_postfach(self):
        # Ein Zweck, den es noch nicht gibt, ist der häufigere Zustand — und
        # der, den jemand sucht. Eine leere Liste beantwortete die Frage
        # «wo richte ich den Rechnungseingang ein?» nicht.
        antwort = self.client.get(reverse('postfach_liste'))
        self.assertEqual(antwort.status_code, 200)
        inhalt = antwort.content.decode()
        self.assertIn('Antworten auf Ticket-Mails', inhalt)
        self.assertIn('Eingehende Kreditorenrechnungen', inhalt)

    def test_das_geheimnis_steht_nie_im_formular(self):
        self._anlegen()
        antwort = self.client.get(reverse('postfach_form', args=['rechnungen']))
        inhalt = antwort.content.decode()
        self.assertNotIn(GEHEIM, inhalt, 'Das Passwort steht im HTML.')
        # Auch nicht der Geheimtext: Er ist zwar unlesbar, aber ihn
        # herauszugeben wäre eine unnötige Preisgabe.
        self.assertNotIn(Postfach.alle_organisationen.get().passwort_geheim, inhalt)
        self.assertIn('unverändert', inhalt)

    def test_letzter_fehler_steht_in_der_liste(self):
        # Damit die Verwalterin den Grund dort sieht, wo sie ohnehin
        # hinschaut — nicht in einem Serverprotokoll.
        postfach = self._anlegen()
        postfach.fehler_vermerken('Anmeldung als r@example.ch abgelehnt')
        antwort = self.client.get(reverse('postfach_liste'))
        self.assertIn('abgelehnt', antwort.content.decode())

    # -- Speichern -----------------------------------------------------

    def test_anlegen_ueber_das_formular(self):
        antwort = self.client.post(reverse('postfach_form', args=['antworten']), {
            'verfahren': 'passwort', 'benutzer': 'a@example.ch',
            'server': 'imap.example.ch', 'port': '993', 'ordner': 'INBOX',
            'passwort': GEHEIM, 'aktiv': 'an'})
        self.assertRedirects(antwort, reverse('postfach_liste'))
        postfach = Postfach.alle_organisationen.get(zweck='antworten')
        self.assertEqual(postfach.benutzer, 'a@example.ch')
        self.assertEqual(postfach.passwort, GEHEIM)
        self.assertEqual(postfach.organisation, self.organisation)

    def test_leeres_passwortfeld_laesst_das_geheimnis_stehen(self):
        """DER Test dieser Datei.

        Der Fehler, den er verhindert, ist leise: Jemand ändert die
        Portnummer, das Passwortfeld bleibt leer — und der Zugang ist weg.
        Auffallen würde es erst beim nächsten nächtlichen Abruf.
        """
        self._anlegen()
        self.client.post(reverse('postfach_form', args=['rechnungen']), {
            'verfahren': 'passwort', 'benutzer': 'r@example.ch',
            'server': 'imap.example.ch', 'port': '143', 'ordner': 'INBOX',
            'passwort': '', 'aktiv': 'an'})
        postfach = Postfach.alle_organisationen.get(zweck='rechnungen')
        self.assertEqual(postfach.port, 143, 'Die Änderung kam nicht an.')
        self.assertEqual(postfach.passwort, GEHEIM, 'Das Passwort ging verloren.')

    def test_neues_passwort_ersetzt_das_alte(self):
        # Die Gegenrichtung: Ohne sie bewiese der Test oben nur, dass das Feld
        # gar nichts tut.
        self._anlegen()
        self.client.post(reverse('postfach_form', args=['rechnungen']), {
            'verfahren': 'passwort', 'benutzer': 'r@example.ch',
            'server': 'imap.example.ch', 'port': '993', 'ordner': 'INBOX',
            'passwort': 'ein-neues', 'aktiv': 'an'})
        self.assertEqual(Postfach.alle_organisationen.get().passwort, 'ein-neues')

    def test_ohne_passwort_laesst_sich_nichts_anlegen(self):
        antwort = self.client.post(reverse('postfach_form', args=['antworten']), {
            'verfahren': 'passwort', 'benutzer': 'a@example.ch',
            'server': 'imap.example.ch', 'port': '993', 'passwort': '', 'aktiv': 'an'})
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Passwort fehlt')
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    def test_unsinniger_port_wird_abgewiesen(self):
        antwort = self.client.post(reverse('postfach_form', args=['antworten']), {
            'verfahren': 'passwort', 'benutzer': 'a@example.ch',
            'server': 'imap.example.ch', 'port': '99999', 'passwort': GEHEIM})
        self.assertContains(antwort, 'zwischen 1 und 65535')
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    def test_eingabe_bleibt_nach_einem_fehler_stehen(self):
        # Sonst tippt die Verwalterin alles noch einmal — und gibt beim
        # zweiten Anlauf erfahrungsgemäss weniger Sorgfalt hinein.
        antwort = self.client.post(reverse('postfach_form', args=['antworten']), {
            'verfahren': 'passwort', 'benutzer': 'merk-mich@example.ch',
            'server': '', 'port': '993', 'passwort': GEHEIM})
        self.assertContains(antwort, 'merk-mich@example.ch')

    def test_abschalten_statt_loeschen(self):
        self._anlegen()
        self.client.post(reverse('postfach_form', args=['rechnungen']), {
            'verfahren': 'passwort', 'benutzer': 'r@example.ch',
            'server': 'imap.example.ch', 'port': '993', 'ordner': 'INBOX'})
        postfach = Postfach.alle_organisationen.get()
        self.assertFalse(postfach.aktiv)
        self.assertEqual(postfach.passwort, GEHEIM, 'Abschalten darf nichts löschen.')

    def test_loeschen_entfernt_das_postfach(self):
        self._anlegen()
        antwort = self.client.post(reverse('postfach_loeschen', args=['rechnungen']))
        self.assertRedirects(antwort, reverse('postfach_liste'))
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_ohne_schluessel_wird_nicht_gespeichert(self):
        # Und zwar mit einer Meldung auf der Seite, nicht mit einem Traceback:
        # Die Ursache liegt beim Betreiber, nicht bei der Verwalterin.
        antwort = self.client.post(reverse('postfach_form', args=['antworten']), {
            'verfahren': 'passwort', 'benutzer': 'a@example.ch',
            'server': 'imap.example.ch', 'port': '993', 'passwort': GEHEIM})
        self.assertContains(antwort, UMGEBUNGSNAME)
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    # -- Verbindungstest -----------------------------------------------

    def test_verbindungstest_meldet_erfolg_und_merkt_ihn(self):
        postfach = self._anlegen()
        with mock.patch('core.services.postfach_abruf.verbinden') as verbinden:
            verbinden.return_value = mock.Mock()
            antwort = self.client.post(reverse('postfach_test', args=['rechnungen']),
                                       follow=True)
        self.assertContains(antwort, 'steht')
        postfach.refresh_from_db()
        self.assertIsNotNone(postfach.letzter_test)

    def test_verbindungstest_zeigt_die_sprechende_meldung(self):
        from core.services.postfach_abruf import AbrufFehler

        postfach = self._anlegen()
        with mock.patch('core.services.postfach_abruf.verbinden',
                        side_effect=AbrufFehler('Bei Gmail wird ein App-Passwort gebraucht.')):
            antwort = self.client.post(reverse('postfach_test', args=['rechnungen']),
                                       follow=True)
        self.assertContains(antwort, 'App-Passwort')
        postfach.refresh_from_db()
        # Auch im Fehlerfeld — der Test ist oft ein anderer Mensch als der,
        # der später auf die Liste schaut.
        self.assertIn('App-Passwort', postfach.letzter_fehler)

    def test_geglueckter_test_raeumt_den_alten_fehler_weg(self):
        postfach = self._anlegen()
        postfach.fehler_vermerken('alter Fehler')
        with mock.patch('core.services.postfach_abruf.verbinden') as verbinden:
            verbinden.return_value = mock.Mock()
            self.client.post(reverse('postfach_test', args=['rechnungen']))
        postfach.refresh_from_db()
        self.assertEqual(postfach.letzter_fehler, '')
        self.assertIsNone(postfach.letzter_fehler_am)


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class PostfachRollenTests(TestCase):
    """Sehen dürfen alle vier, ändern nur Inhaber und Verwalter.

    Ein Postfachzugang ist der Schlüssel zur gesamten Geschäftskorrespondenz
    einer Verwaltung — das ist keine Sachbearbeitungsaufgabe.
    """

    def setUp(self):
        self.organisation = _test_organisation()
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='r@example.ch')
        postfach.passwort = GEHEIM
        postfach.save()

    def _als(self, rolle):
        self.client.force_login(_team_user(rolle))

    def test_lesezugriff_sieht_die_liste(self):
        self._als('Lesend')
        self.assertEqual(self.client.get(reverse('postfach_liste')).status_code, 200)

    def test_lesezugriff_bekommt_keine_knoepfe(self):
        self._als('Lesend')
        inhalt = self.client.get(reverse('postfach_liste')).content.decode()
        self.assertNotIn('Verbindung prüfen', inhalt)
        self.assertIn('Inhaber und Verwalter', inhalt)

    def test_sachbearbeitung_darf_nicht_aendern(self):
        self._als('Sachbearbeitung')
        self.assertEqual(
            self.client.get(reverse('postfach_form', args=['rechnungen'])).status_code, 403)

    def test_lesezugriff_darf_nicht_loeschen(self):
        self._als('Lesend')
        antwort = self.client.post(reverse('postfach_loeschen', args=['rechnungen']))
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(Postfach.alle_organisationen.count(), 1)

    def test_lesezugriff_darf_nicht_testen(self):
        self._als('Lesend')
        self.assertEqual(
            self.client.post(reverse('postfach_test', args=['rechnungen'])).status_code, 403)

    def test_verwalter_darf_aendern(self):
        # Die Gegenrichtung — ohne sie bewiesen die Absagen oben nur, dass die
        # Seite für alle kaputt ist.
        self._als('Verwaltung')
        self.assertEqual(
            self.client.get(reverse('postfach_form', args=['rechnungen'])).status_code, 200)

    def test_ohne_anmeldung_gar_nichts(self):
        antwort = self.client.get(reverse('postfach_liste'))
        self.assertEqual(antwort.status_code, 302)
        self.assertIn('/login/', antwort['Location'])
