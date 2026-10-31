"""Zahlungsausfall: Mahnung, Lesemodus, Hintergrundläufe stehen, Wiedereinschalten, nie löschen."""
import io
import pathlib
import re
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase

from abo import dienst
from abo.models import AboRechnung, Abonnement
from core import funktionen as f
from core.tenancy import organisation_kontext
from core.tests._isolation import MandantenFixture

User = get_user_model()
HEUTE = date(2026, 11, 20)


def _abo(bestand, **felder):
    organisation = bestand.organisation
    abo, _neu = Abonnement.alle_organisationen.update_or_create(
        organisation=organisation, defaults={'uneingeschraenkt': False, 'zusatzmodule': [], **felder})
    return abo


def _ueberfaellig(bestand, tage, status='offen'):
    """Eine Abo-Rechnung, die vor `tage` Tagen (gemessen an HEUTE) fällig wurde."""
    return AboRechnung.alle_organisationen.create(
        organisation=bestand.organisation, periode_von=HEUTE - timedelta(days=tage + 60),
        periode_bis=HEUTE - timedelta(days=tage + 30), stufe='team', intervall='monatlich', einheiten=1,
        netto='119.00', brutto='119.00', rechnungsdatum=HEUTE - timedelta(days=tage + 30),
        faellig_am=HEUTE - timedelta(days=tage), status=status)


class Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        # Das Isolationsfixture legt je Verwaltung eine Abo-Rechnung an; diese Tests bauen ihre eigenen.
        from abo.models import AboRechnung
        AboRechnung.alle_organisationen.all().delete()

    def _client(self, bestand=None):
        c = Client()
        c.force_login((bestand or self.a).benutzer)
        return c

    def _lesemodus(self, bestand=None):
        bestand = bestand or self.a
        _abo(bestand)
        _ueberfaellig(bestand, settings.ABO_LESEMODUS_NACH_TAGEN + 3)
        return dienst.zustand_aktualisieren(bestand.organisation, HEUTE)


class ZustandTests(Basis):

    def test_zustand_folgt_der_ueberfaelligkeit(self):
        _abo(self.a)
        org = self.a.organisation
        self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE), ('aktiv', 'aktiv'))
        r = _ueberfaellig(self.a, 0)                                    # heute fällig: noch nicht überfällig
        self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE)[1], 'aktiv')
        r.faellig_am = HEUTE - timedelta(days=settings.ABO_MAHNUNG_NACH_TAGEN)
        r.save()
        self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE)[1], 'mahnung')
        r.faellig_am = HEUTE - timedelta(days=settings.ABO_LESEMODUS_NACH_TAGEN - 1)
        r.save()
        self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE)[1], 'mahnung')
        r.faellig_am = HEUTE - timedelta(days=settings.ABO_LESEMODUS_NACH_TAGEN)
        r.save()
        self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE)[1], 'lesemodus')

    def test_zahlung_oeffnet_wieder_und_nichts_ist_verloren(self):
        from portfolio.models import Einheit
        alt, neu = self._lesemodus()
        self.assertEqual(neu, 'lesemodus')
        vorher = Einheit.alle_organisationen.filter(organisation=self.a.organisation).count()
        rechnung = AboRechnung.alle_organisationen.get(organisation=self.a.organisation)
        dienst.als_bezahlt(rechnung, HEUTE)
        self.assertEqual(Abonnement.alle_organisationen.get(organisation=self.a.organisation).zustand, 'aktiv')
        self.assertEqual(Einheit.alle_organisationen.filter(organisation=self.a.organisation).count(), vorher)
        self.assertTrue(f.darf_schreiben(type(self.a.organisation).objects.get(pk=self.a.organisation.pk)))

    def test_storno_hebt_die_sperre_auf(self):
        self._lesemodus()
        dienst.stornieren(AboRechnung.alle_organisationen.get(organisation=self.a.organisation))
        self.assertEqual(Abonnement.alle_organisationen.get(organisation=self.a.organisation).zustand, 'aktiv')

    def test_zustand_einer_verwaltung_beruehrt_die_andere_nicht(self):
        _abo(self.b)
        self._lesemodus(self.a)
        self.assertEqual(Abonnement.alle_organisationen.get(organisation=self.b.organisation).zustand, 'aktiv')

    def test_erinnerung_geht_einmal_beim_uebergang_raus(self):
        _abo(self.a)
        type(self.a.organisation).objects.filter(pk=self.a.organisation.pk).update(email='verwaltung-a@example.ch')
        _ueberfaellig(self.a, settings.ABO_MAHNUNG_NACH_TAGEN)
        mail.outbox.clear()
        self.a.organisation.refresh_from_db()
        bericht = dienst.abrechnen(self.a.organisation, heute=HEUTE)
        self.assertEqual(bericht['zustand'], 'mahnung')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['verwaltung-a@example.ch'])
        dienst.abrechnen(self.a.organisation, heute=HEUTE)              # zweiter Lauf am selben Tag
        self.assertEqual(len(mail.outbox), 1, 'keine zweite Mail ohne Zustandswechsel')


class LesemodusWebTests(Basis):

    def test_lesemodus_sperrt_schreibwege_lesen_und_export_bleiben(self):
        self._lesemodus()
        c = self._client()
        # Schreiben gesperrt, mit Erklärung statt 403:
        sperre = c.post('/neu/personen/neu/', {'nachname': 'X'})
        self.assertEqual(sperre.status_code, 402)
        self.assertContains(sperre, 'schreibgeschützt', status_code=402)
        # Lesen und Export gehen:
        self.assertEqual(c.get('/neu/personen/').status_code, 200)
        self.assertEqual(c.get('/neu/liegenschaften/').status_code, 200)
        self.assertEqual(c.get('/neu/einstellungen/daten/export/').status_code, 200)
        # Die Abo-Seite bleibt bedienbar (Rechnung ansehen), das Banner sagt es:
        seite = c.get('/neu/abonnement/')
        self.assertContains(seite, 'schreibgeschützt')

    def test_gegenprobe_aktiv_schreibt_normal(self):
        _abo(self.a)
        c = self._client()
        self.assertNotEqual(c.post('/neu/personen/neu/', {'nachname': 'X'}).status_code, 402)

    def test_jede_schreibende_route_unter_neu_ist_im_lesemodus_gesperrt(self):
        """Nicht nur ein Beispiel: alle POST-Routen der Oberfläche, ausser den offenen Pfaden."""
        from abo.test_freigabe import _alle_routen
        from abo import zugang
        self._lesemodus()
        c = self._client()
        geprueft, durchgelassen = 0, []
        for route in _alle_routen():
            if not route.startswith('/neu/') or zugang.lesemodus_offen(route):
                continue
            geprueft += 1
            if c.post(route, {}).status_code != 402:
                durchgelassen.append(route)
        self.assertGreater(geprueft, 150)
        self.assertEqual(durchgelassen, [])

    def test_banner_bei_mahnung_mit_datum_des_lesemodus(self):
        _abo(self.a)
        _ueberfaellig(self.a, settings.ABO_MAHNUNG_NACH_TAGEN)
        dienst.zustand_aktualisieren(self.a.organisation, HEUTE)
        seite = self._client().get('/neu/abonnement/')
        self.assertContains(seite, 'überfällig')

    def test_portalnutzer_buesst_nicht_fuer_den_verzug_der_verwaltung(self):
        """Der Lesemodus sperrt Mitglieder der Verwaltung, nicht Mieter und Eigentümer."""
        self._lesemodus()
        mieterkonto = User.objects.create_user(username='mieter_a', password='x')
        with organisation_kontext(self.a.organisation):
            self.a.mieter.benutzer = mieterkonto
            self.a.mieter.save()
        c = Client()
        c.force_login(mieterkonto)
        self.assertNotEqual(c.post('/mieter/passwort/', {}).status_code, 402)

    def test_superuser_wird_nicht_ausgesperrt(self):
        self._lesemodus()
        su = User.objects.create_superuser('root_zahl', 'r@example.ch', 'x')
        from crm.models import Mitgliedschaft
        Mitgliedschaft.alle_organisationen.create(benutzer=su, organisation=self.a.organisation, rolle='Inhaber')
        c = Client()
        c.force_login(su)
        self.assertNotEqual(c.post('/neu/personen/neu/', {'nachname': 'X'}).status_code, 402)


class HintergrundTests(Basis):
    """Belegt statt angenommen: im Lesemodus läuft für diese Verwaltung nichts mehr."""

    def _sollstellung(self, bestand):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.alle_organisationen.filter(
            organisation=bestand.organisation, titel=f'Miete & NK 03/2027').count()

    def test_monatslauf_laeuft_fuer_aktive_nicht_fuer_lesemodus(self):
        _abo(self.a)
        self._lesemodus(self.b)
        call_command('monatslauf', jahr=2027, monat=3, stdout=io.StringIO(), stderr=io.StringIO())
        self.assertGreater(self._sollstellung(self.a), 0, 'Gegenprobe: die aktive Verwaltung wird gestellt')
        self.assertEqual(self._sollstellung(self.b), 0, 'Lesemodus: keine Sollstellung im Namen dieser Verwaltung')

    def test_nach_der_zahlung_laeuft_der_monatslauf_wieder(self):
        self._lesemodus(self.b)
        dienst.als_bezahlt(AboRechnung.alle_organisationen.get(organisation=self.b.organisation), HEUTE)
        call_command('monatslauf', jahr=2027, monat=3, stdout=io.StringIO(), stderr=io.StringIO())
        self.assertGreater(self._sollstellung(self.b), 0)

    def test_der_lauf_nennt_die_uebersprungene_verwaltung(self):
        from core.tenancy import je_organisation
        self._lesemodus(self.b)
        ausgabe = io.StringIO()
        gelaufen = []
        je_organisation(lambda org: gelaufen.append(org.pk), ausgabe=ausgabe)
        self.assertIn(self.a.organisation.pk, gelaufen)
        self.assertNotIn(self.b.organisation.pk, gelaufen)
        self.assertIn('ÜBERSPRUNGEN', ausgabe.getvalue())

    def test_abrechnungslauf_selbst_laeuft_auch_im_lesemodus(self):
        """Er ist es, der wieder öffnet: er darf nicht am eigenen Lesemodus scheitern."""
        from core.tenancy import je_organisation
        self._lesemodus(self.b)
        ergebnisse, fehler = je_organisation(lambda org: org.pk, abo_pruefen=False)
        self.assertIn(self.b.organisation.pk, ergebnisse)

    def test_andere_schleifen_ueberspringen_den_lesemodus(self):
        """Die Läufe mit eigener Schleife: Pendenzen, Fristen-Mail, Laufplanung."""
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        aufgerufen = []
        with mock.patch('core.services.automation._pendenzen_fuer_organisation',
                        side_effect=lambda h, u: aufgerufen.append(1) or 0):
            self._lesemodus(self.b)
            generate_auto_pendenzen(organisation=self.b.organisation.pk)
            self.assertEqual(aufgerufen, [], 'Lesemodus: keine Auto-Pendenzen')
            generate_auto_pendenzen(organisation=self.a.organisation.pk)
            self.assertEqual(aufgerufen, [1], 'Gegenprobe: ohne Lesemodus läuft es')
        del Pendenz

    def test_jeder_befehl_mit_verwaltungsschleife_kennt_den_lesemodus(self):
        """Vollständigkeit: ein neuer Lauf ohne Prüfung fällt hier auf (Management-Commands und Signals)."""
        wurzel = pathlib.Path(settings.BASE_DIR)
        # Einmalige Werkzeuge des Betreibers, keine wiederkehrenden Läufe im Namen einer Verwaltung.
        einmalig = {
            'seed_e2e', 'seed_e2e_mandanten', 'seed_e2e_mietzins', 'organisation_anlegen', 'mandat_exportieren',
            'daten_importieren', 'kreditor_adressen_nachtragen', 'mietzinsmodell_bestand',
            'staffel_mitteilung_bestand', 'fallarten_anlegen', 'regelwerk_grundsatz', 'abo_abrechnung',
            'abo_einstellen',
            # Nur lesend (Prüfbericht, schreibt nichts, versendet nichts): Lesen bleibt im Lesemodus erlaubt.
            'stweg_audit',
            'seed_e2e_abo',
            # Gesetzliche Pflicht (DSG), läuft auch im Lesemodus (abo_pruefen=False, begründet im Befehl).
            'dsg_anonymisieren', 'bewerbungen_bereinigen',
        }
        ohne = []
        for pfad in list(wurzel.glob('*/management/commands/*.py')):
            name = pfad.stem
            quelle = pfad.read_text(encoding='utf-8')
            schleife = re.search(r'organisation_kontext\(|je_organisation\(|Organisation\.objects', quelle)
            if not schleife or name in einmalig or name.startswith('_'):
                continue
            # Der AUFRUF zählt, nicht der Name: ein Import ohne Prüfung schützt nichts.
            if 'not hintergrund_erlaubt(' in quelle or ('je_organisation(' in quelle and 'abo_pruefen=False' not in quelle):
                continue
            ohne.append(f'{pfad.relative_to(wurzel)}')
        self.assertEqual(ohne, [], 'Befehl mit Verwaltungsschleife ohne Lesemodus-Prüfung '
                                   '(hintergrund_erlaubt / je_organisation) und ohne begründete Ausnahme.')

    def test_dsg_laeufe_sind_ausdruecklich_ausgenommen(self):
        """Die Ausnahme ist benannt, nicht zufällig: beide Befehle sagen `abo_pruefen=False`."""
        wurzel = pathlib.Path(settings.BASE_DIR)
        for name in ('dsg_anonymisieren', 'bewerbungen_bereinigen'):
            quelle = (wurzel / 'core' / 'management' / 'commands' / f'{name}.py').read_text(encoding='utf-8')
            self.assertIn('abo_pruefen=False', quelle, name)
