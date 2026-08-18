"""Postfach je Verwaltung — Verschlüsselung, Eindeutigkeit, Mandantenbezug.

Was hier geprüft wird, ist die Zusage, die mit dem Umbau «ein Postfach je
Verwaltung» gegeben wurde: Zugangsdaten wandern aus Umgebungsvariablen in die
Datenbank — und stehen dort NICHT im Klartext.

DIE WICHTIGSTE PRÜFUNG STEHT ZUERST

`test_kein_klartext_in_der_datenbank` liest die Spalte mit rohem SQL, nicht
über das Modell. Über das Modell gelesen käme immer Klartext zurück — der
Getter entschlüsselt ja. Ein Test, der das prüft, prüft nur, dass ein Getter
existiert, und wäre auch dann grün, wenn `verschluesseln` schlicht
`return klartext` machte.

GEGENPROBE (durchgeführt, nicht behauptet — 18.08.2026)

    core/services/geheimnis.py, verschluesseln():
        if not klartext:
            return ''
    +   return klartext                      # ← Verschlüsselung ausgehängt
        return _fernet().encrypt(...)

    → test_kein_klartext_in_der_datenbank   FAIL
        AssertionError: 'hunter2-sehr-geheim' unexpectedly found in
        'hunter2-sehr-geheim' : Das Passwort steht im Klartext in der Spalte
        passwort_geheim.
      test_kein_klartext_beim_refresh_token  FAIL (gleiche Ursache)

    Rückgängig gemacht, danach wieder grün.
"""
from unittest import mock

from django.core.checks import WARNING
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings

from core.models import Postfach
from core.services.geheimnis import (UMGEBUNGSNAME, GeheimtextKaputt, SchluesselFehlt,
                                     entschluesseln, schluessel_vorhanden, verschluesseln)
from core.tenancy import organisation_kontext
from crm.models import Organisation

#: Zwei gültige Fernet-Schlüssel, hier erzeugt und nur hier gültig.
#: KEINE Betriebsschlüssel — Testwerte gehören in den Test, nicht in die `.env`.
SCHLUESSEL_A = '8NJHVucA9G85uCfVM9egyKhlrIDS1sqoXRa0D9ghqCA='
SCHLUESSEL_B = 'Mskic1QfP_lVSszXeGp8gPg35rPiV1JyatrWKRiZxJ8='


def _organisation(firma='Verwaltung A'):
    return Organisation.objects.create(firma=firma, strasse='Weg 1', plz='3000', ort='Bern')


def _rohwert(postfach, spalte):
    """Die Spalte lesen, wie sie auf der Platte steht — am Modell vorbei."""
    with connection.cursor() as zeiger:
        zeiger.execute(f'SELECT {spalte} FROM core_postfach WHERE id = %s', [postfach.pk])
        return zeiger.fetchone()[0]


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
class GeheimnisTests(TestCase):
    """Das Verschlüsselungsmodul für sich allein."""

    def test_hin_und_zurueck(self):
        self.assertEqual(entschluesseln(verschluesseln('hunter2')), 'hunter2')

    def test_zweimal_dasselbe_ergibt_verschiedene_geheimtexte(self):
        # Fernet setzt einen Zufallswert und einen Zeitstempel davor. Wäre der
        # Geheimtext deterministisch, verriete ein Datenbankauszug, welche zwei
        # Verwaltungen dasselbe Passwort benutzen.
        self.assertNotEqual(verschluesseln('gleich'), verschluesseln('gleich'))

    def test_leer_bleibt_leer(self):
        # Sonst wäre «kein Passwort gesetzt» nicht mehr von «Passwort ist der
        # leere String» zu unterscheiden — und ein leeres Formularfeld legte
        # ein Geheimnis an, das wie eines aussieht.
        self.assertEqual(verschluesseln(''), '')
        self.assertEqual(entschluesseln(''), '')

    def test_umlaute_und_sonderzeichen(self):
        wert = 'Grüezi!ß—«»@#$%^&*()_+ 漢字'
        self.assertEqual(entschluesseln(verschluesseln(wert)), wert)

    def test_fremder_schluessel_meldet_klar(self):
        geheim = verschluesseln('hunter2')
        with override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_B}):
            with self.assertRaises(GeheimtextKaputt) as fall:
                entschluesseln(geheim)
        # Die Meldung muss den Grund nennen — «InvalidToken» hilft im Betrieb
        # niemandem weiter.
        self.assertIn('gewechselt', str(fall.exception))

    def test_beschaedigter_geheimtext_meldet_klar(self):
        with self.assertRaises(GeheimtextKaputt):
            entschluesseln('das ist kein Fernet-Token')


class OhneSchluesselTests(TestCase):
    """Fehlt der Schlüssel, muss es klar krachen — nicht still danebengehen."""

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_fehlender_schluessel_wirft_eigene_ausnahme(self):
        with self.assertRaises(SchluesselFehlt) as fall:
            verschluesseln('hunter2')
        text = str(fall.exception)
        # Die Meldung soll dem Betreiber sagen, WAS zu tun ist. Ein blosses
        # «SchluesselFehlt» im Log kostet eine halbe Stunde Suche.
        self.assertIn(UMGEBUNGSNAME, text)
        self.assertIn('Fernet.generate_key', text)

    @override_settings(**{UMGEBUNGSNAME: 'das-ist-kein-fernet-schluessel'})
    def test_unbrauchbarer_schluessel_ist_kein_datenfehler(self):
        # Bewusst SchluesselFehlt und nicht GeheimtextKaputt: Der Fehler liegt
        # in der Konfiguration, nicht in den Daten. Wer die beiden verwechselt,
        # gibt im Betrieb Zugangsdaten neu ein, obwohl bloss die `.env` klemmt.
        with self.assertRaises(SchluesselFehlt) as fall:
            verschluesseln('hunter2')
        self.assertIn('44 Zeichen', str(fall.exception))

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_schluessel_vorhanden_wirft_nicht(self):
        # Für Startchecks und die Oberfläche: dort will man die Antwort, nicht
        # eine Ausnahme, die eine Seite abbricht.
        self.assertFalse(schluessel_vorhanden())

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_schluessel_vorhanden_erkennt_ihn(self):
        self.assertTrue(schluessel_vorhanden())


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
class PostfachGeheimnisTests(TestCase):

    def setUp(self):
        self.organisation = _organisation()

    def test_kein_klartext_in_der_datenbank(self):
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='rechnungen@example.ch')
        postfach.passwort = 'hunter2-sehr-geheim'
        postfach.save()

        roh = _rohwert(postfach, 'passwort_geheim')
        self.assertNotIn('hunter2-sehr-geheim', roh,
                         'Das Passwort steht im Klartext in der Spalte passwort_geheim.')
        self.assertTrue(roh.startswith('gAAAAA'), 'Das sieht nicht nach Fernet aus.')
        # Und es ist auch wirklich noch lesbar — sonst wäre «kein Klartext»
        # trivial dadurch zu erreichen, dass gar nichts gespeichert wird.
        self.assertEqual(Postfach.alle_organisationen.get(pk=postfach.pk).passwort,
                         'hunter2-sehr-geheim')

    def test_kein_klartext_beim_refresh_token(self):
        # Ein Refresh-Token ist genauso wertvoll wie ein Passwort: Damit liest
        # jemand das Postfach, bis es widerrufen wird.
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_ANTWORTEN,
                            verfahren=Postfach.VERFAHREN_OAUTH2,
                            benutzer='antworten@example.ch',
                            mandant_id='m-1', anwendung_id='a-1')
        postfach.refresh_token = '0.AXoA-geheimes-token'
        postfach.save()

        roh = _rohwert(postfach, 'refresh_token_geheim')
        self.assertNotIn('0.AXoA-geheimes-token', roh)
        self.assertEqual(Postfach.alle_organisationen.get(pk=postfach.pk).refresh_token,
                         '0.AXoA-geheimes-token')

    def test_ohne_passwort_bleibt_die_spalte_leer(self):
        postfach = Postfach.objects.create(
            organisation=self.organisation, zweck=Postfach.ZWECK_RECHNUNGEN,
            server='imap.example.ch', benutzer='x@example.ch')
        self.assertEqual(_rohwert(postfach, 'passwort_geheim'), '')
        self.assertEqual(postfach.passwort, '')

    def test_schluesselwechsel_meldet_beim_lesen(self):
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='x@example.ch')
        postfach.passwort = 'hunter2'
        postfach.save()

        with override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_B}):
            frisch = Postfach.alle_organisationen.get(pk=postfach.pk)
            with self.assertRaises(GeheimtextKaputt):
                frisch.passwort


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
class PostfachRegelnTests(TestCase):

    def setUp(self):
        self.organisation = _organisation()

    def test_zwei_postfaecher_gleichen_zwecks_gehen_nicht(self):
        # Sonst könnte niemand mehr sagen, aus welchem geholt wird — und der
        # Abruf entschiede es zufällig über die Sortierung.
        Postfach.objects.create(organisation=self.organisation,
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='a@example.ch')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Postfach.objects.create(organisation=self.organisation,
                                        zweck=Postfach.ZWECK_RECHNUNGEN,
                                        benutzer='b@example.ch')

    def test_zwei_zwecke_nebeneinander_gehen_sehr_wohl(self):
        Postfach.objects.create(organisation=self.organisation,
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
        Postfach.objects.create(organisation=self.organisation,
                                zweck=Postfach.ZWECK_ANTWORTEN, benutzer='a@example.ch')
        with organisation_kontext(self.organisation):
            self.assertEqual(Postfach.objects.count(), 2)

    def test_dieselbe_adresse_in_zwei_verwaltungen_geht(self):
        # Die Sperre gilt je Verwaltung, nicht global: Zwei Verwaltungen dürfen
        # denselben Anbieter und sogar dieselbe Adresse benutzen — das zu
        # verbieten wäre eine Regel, die niemand aufgestellt hat.
        zweite = _organisation('Verwaltung B')
        Postfach.objects.create(organisation=self.organisation,
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
        Postfach.objects.create(organisation=zweite,
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
        self.assertEqual(Postfach.alle_organisationen.count(), 2)

    def test_einsatzbereit_verlangt_alles_beim_passwortverfahren(self):
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='r@example.ch')
        self.assertFalse(postfach.ist_einsatzbereit, 'ohne Passwort einsatzbereit?')
        postfach.passwort = 'hunter2'
        self.assertTrue(postfach.ist_einsatzbereit)

        postfach.server = ''
        self.assertFalse(postfach.ist_einsatzbereit, 'ohne Server einsatzbereit?')

    def test_einsatzbereit_verlangt_beim_oauth2_andere_felder(self):
        # Beim OAuth2-Verfahren gibt es kein Passwort — ein Test, der nur das
        # Passwort prüfte, hielte jedes M365-Postfach für unbrauchbar.
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_ANTWORTEN,
                            verfahren=Postfach.VERFAHREN_OAUTH2,
                            benutzer='a@example.ch', mandant_id='m-1')
        self.assertFalse(postfach.ist_einsatzbereit, 'ohne Anwendungs-ID einsatzbereit?')
        postfach.anwendung_id = 'a-1'
        self.assertFalse(postfach.ist_einsatzbereit, 'ohne Refresh-Token einsatzbereit?')
        postfach.refresh_token = 'tok'
        self.assertTrue(postfach.ist_einsatzbereit)

    def test_abgeschaltetes_postfach_ist_nie_einsatzbereit(self):
        postfach = Postfach(organisation=self.organisation,
                            zweck=Postfach.ZWECK_RECHNUNGEN,
                            server='imap.example.ch', benutzer='r@example.ch', aktiv=False)
        postfach.passwort = 'hunter2'
        self.assertFalse(postfach.ist_einsatzbereit)

    def test_fehler_und_erfolg_werden_vermerkt(self):
        postfach = Postfach.objects.create(
            organisation=self.organisation, zweck=Postfach.ZWECK_RECHNUNGEN,
            server='imap.example.ch', benutzer='r@example.ch')
        postfach.fehler_vermerken('AUTHENTICATIONFAILED')
        postfach.refresh_from_db()
        self.assertEqual(postfach.letzter_fehler, 'AUTHENTICATIONFAILED')
        self.assertIsNotNone(postfach.letzter_fehler_am)

        postfach.erfolg_vermerken()
        postfach.refresh_from_db()
        # Der alte Fehler MUSS weg sein. Bliebe er stehen, zeigte die
        # Oberfläche einen Fehler an einem Postfach, das längst wieder läuft.
        self.assertEqual(postfach.letzter_fehler, '')
        self.assertIsNone(postfach.letzter_fehler_am)
        self.assertIsNotNone(postfach.letzter_abruf)

    def test_langer_fehlertext_wird_gekuerzt(self):
        postfach = Postfach.objects.create(
            organisation=self.organisation, zweck=Postfach.ZWECK_RECHNUNGEN,
            benutzer='r@example.ch')
        postfach.fehler_vermerken('x' * 5000)
        postfach.refresh_from_db()
        self.assertEqual(len(postfach.letzter_fehler), 2000)


class StartpruefungTests(TestCase):
    """Die Warnung beim Hochfahren — sie soll dann kommen, wenn sie stimmt.

    Die eigentliche Gefahr bei einer solchen Prüfung ist nicht, dass sie
    schweigt, sondern dass sie IMMER redet: Eine Warnung, die auf jeder
    Installation erscheint, wird nach zwei Wochen überlesen — auch dort, wo sie
    zutrifft. Deshalb wird hier beides geprüft.

    GEGENPROBE (durchgeführt 18.08.2026)

        core/checks.py:  `if not betroffen:` → `if False:`   (warnt immer)
          → test_ohne_postfaecher_schweigt_sie                FAIL
            test_ohne_hinterlegte_geheimnisse_schweigt_sie    FAIL

        core/checks.py:  `if schluessel_vorhanden():` → `if True:`  (schweigt immer)
          → test_hinterlegte_geheimnisse_ohne_schluessel_warnen  FAIL (0 != 1)

        Beides rückgängig gemacht, danach wieder grün.
    """

    def _lauf(self):
        from core.checks import postfaecher_brauchen_einen_schluessel
        return postfaecher_brauchen_einen_schluessel(None)

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_ohne_postfaecher_schweigt_sie(self):
        self.assertEqual(self._lauf(), [])

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_ohne_hinterlegte_geheimnisse_schweigt_sie(self):
        # Ein angelegtes, aber noch nicht ausgefülltes Postfach ist kein
        # Anlass: Es ist noch niemandes Zugang darin.
        Postfach.objects.create(organisation=_organisation(),
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
        self.assertEqual(self._lauf(), [])

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_mit_schluessel_schweigt_sie(self):
        postfach = Postfach(organisation=_organisation(),
                            zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
        postfach.passwort = 'hunter2'
        postfach.save()
        self.assertEqual(self._lauf(), [])

    def test_hinterlegte_geheimnisse_ohne_schluessel_warnen(self):
        with override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A}):
            postfach = Postfach(organisation=_organisation(),
                                zweck=Postfach.ZWECK_RECHNUNGEN, benutzer='r@example.ch')
            postfach.passwort = 'hunter2'
            postfach.save()

        with override_settings(**{UMGEBUNGSNAME: ''}):
            meldungen = self._lauf()
        self.assertEqual(len(meldungen), 1)
        self.assertEqual(meldungen[0].id, 'core.W001')
        # Warnung, nicht Fehler: Ein Fehler bräche `migrate` im Deploy ab und
        # nähme die ganze Anwendung vom Netz — wegen eines Postfachs.
        self.assertEqual(meldungen[0].level, WARNING)


class UebernahmeTests(TestCase):
    """Die Übernahme der alten Umgebungsvariablen — wiederholbar, nie werfend.

    Der Punkt, an dem es sonst klemmt: Die Migration läuft **einmal**. War der
    Schlüssel zu dem Zeitpunkt nicht gesetzt, wäre die Übernahme endgültig
    verpasst — ein zweites `migrate` führt sie nicht erneut aus. Deshalb liegt
    die Arbeit in einer Funktion, die auch als Befehl aufrufbar ist.

    GEGENPROBE (durchgeführt 18.08.2026)

        postfach_uebernahme.py:  `if Postfach.objects.filter(…).exists():`
                                 → `if False:`   (Schutz gegen Überschreiben weg)
          → test_bestehendes_postfach_wird_nicht_ueberschrieben   ERROR
            test_zweiter_lauf_aendert_nichts                      ERROR
            (beide am UniqueConstraint — genau der Doppeleintrag, den der
             Schutz verhindert)

        Rückgängig gemacht, danach wieder grün.
    """

    ALT = {'RECHNUNGS_IMAP_USER': 'r@alt.ch', 'RECHNUNGS_IMAP_PASSWORD': 'geheim-r',
           'RECHNUNGS_IMAP_HOST': 'imap.alt.ch',
           'EMAIL_REPLY_USER': 'a@alt.ch', 'EMAIL_REPLY_PASSWORD': 'geheim-a'}

    def setUp(self):
        self.organisation = _organisation()

    def _lauf(self):
        from core.services.postfach_uebernahme import uebernehmen

        class OhneFilter:
            objects = Postfach.alle_organisationen

        return uebernehmen(OhneFilter, Organisation, melden=lambda text: None)

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_beide_quellen_werden_uebernommen(self):
        # Zwei Quellen, nicht eine — der Auftrag nannte nur RECHNUNGS_IMAP_*.
        # Der Antwort-Zugang stand unter EMAIL_REPLY_*, sein Server sogar fest
        # im Code.
        with mock.patch.dict('os.environ', self.ALT):
            self.assertEqual(self._lauf(), 2)
        zwecke = set(Postfach.alle_organisationen.values_list('zweck', flat=True))
        self.assertEqual(zwecke, {'rechnungen', 'antworten'})

        antworten = Postfach.alle_organisationen.get(zweck='antworten')
        self.assertEqual(antworten.server, 'lx37.hoststar.hosting',
                         'Der bisher fest verdrahtete Server ging verloren.')
        self.assertEqual(antworten.passwort, 'geheim-a')

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_zweiter_lauf_aendert_nichts(self):
        with mock.patch.dict('os.environ', self.ALT):
            self._lauf()
            self.assertEqual(self._lauf(), 0)
        self.assertEqual(Postfach.alle_organisationen.count(), 2)

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_bestehendes_postfach_wird_nicht_ueberschrieben(self):
        # Sonst überschriebe ein nachgeholter Lauf die von Hand eingerichteten
        # Zugangsdaten mit den alten aus der Umgebung.
        eigenes = Postfach(organisation=self.organisation, zweck='rechnungen',
                           server='imap.neu.ch', benutzer='neu@example.ch')
        eigenes.passwort = 'neues-passwort'
        eigenes.save()
        with mock.patch.dict('os.environ', self.ALT):
            self._lauf()
        eigenes.refresh_from_db()
        self.assertEqual(eigenes.benutzer, 'neu@example.ch')
        self.assertEqual(eigenes.passwort, 'neues-passwort')

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_ohne_schluessel_wird_uebersprungen_statt_geworfen(self):
        # DER Grund, warum die Migration nie scheitert: Ein abgebrochenes
        # `migrate` im Deploy nimmt die ganze Anwendung vom Netz.
        with mock.patch.dict('os.environ', self.ALT):
            self.assertEqual(self._lauf(), 0)
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_ohne_umgebungsvariablen_passiert_nichts(self):
        # Die Variablen ausdrücklich LEEREN und nicht bloss darauf bauen, dass
        # sie in der Testumgebung ohnehin fehlen: Sonst wäre der Test grün,
        # ohne je etwas geprüft zu haben — und auf einem Entwicklungsrechner,
        # der sie gesetzt hat, plötzlich rot.
        with mock.patch.dict('os.environ', {name: '' for name in self.ALT}):
            self.assertEqual(self._lauf(), 0)
        self.assertEqual(Postfach.alle_organisationen.count(), 0)

    @override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
    def test_der_befehl_holt_die_uebernahme_nach(self):
        from io import StringIO

        from django.core.management import call_command

        with mock.patch.dict('os.environ', self.ALT):
            call_command('postfaecher_uebernehmen', stdout=StringIO())
        self.assertEqual(Postfach.alle_organisationen.count(), 2)

    @override_settings(**{UMGEBUNGSNAME: ''})
    def test_der_befehl_endet_mit_fehlercode_ohne_schluessel(self):
        from io import StringIO

        from django.core.management import call_command

        # Nicht bloss eine Zeile Text: Ein Scheduler soll den Fehlschlag am
        # Exitcode sehen und nicht in einer beruhigenden Ausgabe suchen.
        with mock.patch.dict('os.environ', self.ALT):
            with self.assertRaises(SystemExit):
                call_command('postfaecher_uebernehmen', stdout=StringIO(), stderr=StringIO())


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL_A})
class PostfachMandantTests(TestCase):
    """Der Mandantenbezug — dieselbe Prüfung wie für jedes andere Fachmodell.

    Sie steht zusätzlich hier, weil ein Postfach ein besonders teurer Irrtum
    wäre: Wer das Postfach einer fremden Verwaltung sieht, sieht deren
    Serveradresse und Benutzernamen — und mit einem Formular auch deren Post.
    """

    def setUp(self):
        self.a = _organisation('Verwaltung A')
        self.b = _organisation('Verwaltung B')
        with organisation_kontext(self.a):
            self.postfach_a = Postfach.objects.create(
                organisation=self.a, zweck=Postfach.ZWECK_RECHNUNGEN,
                server='imap.a.ch', benutzer='r@a.ch')
        with organisation_kontext(self.b):
            self.postfach_b = Postfach.objects.create(
                organisation=self.b, zweck=Postfach.ZWECK_RECHNUNGEN,
                server='imap.b.ch', benutzer='r@b.ch')

    def test_a_sieht_b_nicht(self):
        with organisation_kontext(self.a):
            sichtbar = set(Postfach.objects.values_list('pk', flat=True))
        self.assertEqual(sichtbar, {self.postfach_a.pk})

    def test_der_uebergreifende_manager_sieht_beide(self):
        # Den brauchen die Scheduler-Befehle, die über alle Verwaltungen
        # laufen — ohne ihn gäbe es keinen Abruf für die zweite.
        self.assertEqual(Postfach.alle_organisationen.count(), 2)

    def test_ohne_kontext_wirft_der_manager(self):
        from core.tenancy import OrganisationsFehler

        with self.assertRaises(OrganisationsFehler):
            list(Postfach.objects.all())
