"""Rollen- und Berechtigungstest (RBAC) über die Backend-Routen.

Zwei Verfahren, absichtlich nebeneinander:

1. **Benannte Angriffe** — die drei Szenarien aus dem Testauftrag, jeweils mit
   Nachweis, dass sich am Datenbestand nichts geändert hat (ein 403, der die
   Änderung trotzdem durchlässt, wäre wertlos).
2. **Sweep über ALLE Routen** — jede URL des Projekts wird mit jeder
   Nicht-Team-Rolle aufgerufen. Neue Views sind damit automatisch abgedeckt:
   Wer eine Route ohne `@rolle_erforderlich` baut, macht diesen Test rot, ohne
   dass jemand daran denken muss, ihn zu erweitern.

Rollen
------
- Verwalter          → Mitgliedschaft `Verwalter` (Referenz: darf alles)
- Mieter             → `Mieter.benutzer`, KEINE Mitgliedschaft
- Fremder Mieter     → zweiter Mieter, dessen Ticket angegriffen wird
- Hauswart           → Mitgliedschaft `Hauswart` (nur Schadensmeldungen)
- Eigentümer         → `Eigentuemer.benutzer`, KEINE Mitgliedschaft

Was 403 heisst und was nicht
----------------------------
Rollenprüfung (Team-Bereich `/neu/…`) → **403**. Objektprüfung im Portal
(`get_object_or_404(..., gemeldet_von=mieter)`) → **404**: Wer fremde Tickets
anfragt, soll nicht einmal erfahren, dass es sie gibt. Beides sperrt; die Tests
verlangen deshalb dort «403 oder 404, und der Bestand ist unverändert».
"""
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from core.auth import (HAUSWART_ROLLEN, TEAM_ROLLEN, TICKET_LESE_ROLLEN,
                       TICKET_SCHREIB_ROLLEN, ROLLE_HAUSWART, hat_rolle)
from core.tenancy import aktuelle_organisation, loesche_organisation, setze_organisation
from core.tests._helfer import _basis_objekte, _team_user, _test_organisation
from crm.models import Eigentuemer, Mieter, Mitgliedschaft
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung, TicketNachricht

User = get_user_model()

# ---------------------------------------------------------------------------
# Routen einsammeln
# ---------------------------------------------------------------------------
_KONVERTER = re.compile(r'<(?:(\w+):)?(\w+)>')


def _beispielwert(match):
    konverter = match.group(1)
    if konverter in (None, 'int'):
        return '1'
    if konverter == 'uuid':
        return '00000000-0000-0000-0000-000000000001'
    return 'x'


def alle_routen(patterns=None, praefix=''):
    """Alle URL-Pfade des Projekts, Parameter durch Beispielwerte ersetzt."""
    patterns = get_resolver().url_patterns if patterns is None else patterns
    for p in patterns:
        teil = praefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from alle_routen(p.url_patterns, teil)
        elif isinstance(p, URLPattern):
            if '(?P' in teil or teil.startswith('^') or '\\' in teil:
                continue  # Regex-Routen (statische Auslieferung) — kein Teamzugang
            yield '/' + _KONVERTER.sub(_beispielwert, teil)


#: Bewusst für Portal-Rollen/alle Angemeldeten erreichbar. Jede Zeile hier ist
#: eine Entscheidung; ein neuer Eintrag gehört begründet.
OFFEN_FUER_ANGEMELDETE = (
    '/',                      # Startseite
    '/nach-login/',           # Login-Weiche (leitet je Rolle weiter)
    '/logout/',
    '/version/', '/healthz/',
    '/portal/', '/mieter/',   # eigene Portale, Prüfung im View (Profil-Bezug)
    '/konto/',                # eigenes Konto / Zwei-Faktor
    '/anmeldung/',
    '/passwort/',
    '/portal/login/', '/login/',
    '/i18n/',
    '/api/',                  # Ninja: eigene Auth (auth_lesen), separat getestet
    '/admin/',                # Django-Admin: is_staff, separat getestet
    '/media/', '/static/',
    '/report/', '/schaden/melden/',        # öffentliche Schadenmeldung (QR am Aushang)
    '/bewerben/', '/bewerbung/', '/datenschutz/', '/aushang/',
    '/abnahme-sw.js',         # Service Worker der Vor-Ort-Abnahme: feste Skriptdatei ohne Mandantendaten
    '/webhooks/', '/docuseal/webhook/', '/fristen.ics',          # Token-/Secret-geschützt, eigene Tests
)


#: Weiterleitung auf eine geschützte Route: liefert selbst keine Daten.
NUR_WEITERLEITUNG = {'/neu/assets/': '/neu/ersatzplanung/'}


def _team_routen():
    """Alle Routen, die nur das Team sehen darf: jede Route des Projekts
    ausser den ausdrücklich offenen Pfaden (`OFFEN_FUER_ANGEMELDETE`)."""
    for r in sorted(set(alle_routen())):
        if r == '/' or r in NUR_WEITERLEITUNG:
            continue
        if any(r.startswith(p) for p in OFFEN_FUER_ANGEMELDETE if p != '/'):
            continue
        yield r


class RbacBasis(TestCase):
    """Zwei Mieter, ein Ticket des fremden Mieters, je ein Konto pro Rolle."""

    @classmethod
    def setUpClass(cls):
        # `_test_organisation()` setzt den Mandantenkontext. Auf Klassenebene
        # liegt er ausserhalb der Kopie, die der Testrunner je Test anlegt —
        # ohne Rückgabe liefe er in alle alphabetisch folgenden Module über
        # (test_tenant_manager & Co. wurden davon rot).
        cls._kontext_vorher = aktuelle_organisation()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls._kontext_vorher is None:
            loesche_organisation()
        else:
            setze_organisation(cls._kontext_vorher)

    def setUp(self):
        setze_organisation(self.org)

    @classmethod
    def setUpTestData(cls):
        cls.org = _test_organisation()
        cls.lg, cls.einheit, cls.mieter_fremd, cls.vertrag_fremd = _basis_objekte()

        # Eigene Wohnung des angreifenden Mieters
        cls.einheit_eigen = Einheit.objects.create(
            liegenschaft=cls.lg, bezeichnung='2.5 Zi', typ='whg',
            nettomiete_aktuell=Decimal('1200'), nebenkosten_aktuell=Decimal('150'))
        cls.mieter_eigen = Mieter.objects.create(
            typ='person', vorname='Eva', nachname='Eigen', email='eva@example.ch',
            strasse='Seeweg 4', plz='8000', ort='Zürich')
        Mietvertrag.objects.create(
            mieter=cls.mieter_eigen, einheit=cls.einheit_eigen, beginn=date(2024, 1, 1),
            netto_mietzins=Decimal('1200'), nebenkosten=Decimal('150'), status='aktiv')

        cls.u_verwalter = _team_user('Verwalter')
        cls.u_lesend = _team_user('Lesezugriff')

        cls.u_mieter = User.objects.create_user(username='rbac_mieter', password='x')
        cls.mieter_eigen.benutzer = cls.u_mieter
        cls.mieter_eigen.save()

        cls.u_hauswart = User.objects.create_user(username='rbac_hauswart', password='x')
        Mitgliedschaft.objects.create(benutzer=cls.u_hauswart, organisation=cls.org,
                                      rolle=ROLLE_HAUSWART)

        # Der Hauswart betreut nur `cls.lg`; die zweite Liegenschaft gehört ihm nicht.
        cls.lg.hauswarte.add(cls.u_hauswart)
        cls.lg_fremd = Liegenschaft.objects.create(
            strasse='Fremdweg 9', plz='8001', ort='Zürich', organisation=cls.org,
            versicherungswert=Decimal('500000'))

        cls.u_eigentuemer = User.objects.create_user(username='rbac_eigentuemer', password='x')
        cls.eigentuemer = Eigentuemer.objects.create(
            organisation=cls.org, firma_oder_name='Eigentümer AG', benutzer=cls.u_eigentuemer)

        # Das Ticket, das nicht dem angreifenden Mieter gehört
        cls.ticket = SchadenMeldung.objects.create(
            liegenschaft=cls.lg, betroffene_einheit=cls.einheit,
            gemeldet_von=cls.mieter_fremd, titel='Heizung fällt aus',
            beschreibung='Tropft seit Tagen', status='in_bearbeitung')

        cls.ticket_fremd = SchadenMeldung.objects.create(
            liegenschaft=cls.lg_fremd, titel='Dach undicht',
            beschreibung='Wasser im Estrich', status='in_bearbeitung')

    def nach_pruefen_unveraendert(self):
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'in_bearbeitung',
                         'Der Status des fremden Tickets wurde verändert.')


# ---------------------------------------------------------------------------
# Schritt 1: Rollen-Setup
# ---------------------------------------------------------------------------
class RollenSetupTests(RbacBasis):

    def test_jede_rolle_hat_den_erwarteten_zugang(self):
        self.assertTrue(hat_rolle(self.u_verwalter, TEAM_ROLLEN))
        self.assertTrue(hat_rolle(self.u_lesend, TEAM_ROLLEN))
        self.assertFalse(hat_rolle(self.u_mieter, TEAM_ROLLEN))
        self.assertFalse(hat_rolle(self.u_eigentuemer, TEAM_ROLLEN))
        self.assertFalse(hat_rolle(self.u_hauswart, TEAM_ROLLEN),
                         'Der Hauswart darf keine Team-Rolle sein.')
        self.assertTrue(hat_rolle(self.u_hauswart, HAUSWART_ROLLEN))

    def test_hauswart_ist_keine_verwaltungs_rolle(self):
        """Der Inhaber-Rückgriff in hat_rolle() darf den Hauswart nicht erfassen."""
        from core.auth import SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN
        self.assertFalse(hat_rolle(self.u_hauswart, SCHREIB_ROLLEN))
        self.assertFalse(hat_rolle(self.u_hauswart, VERWALTUNGS_ROLLEN))


# ---------------------------------------------------------------------------
# Schritt 2: Benannte Cross-Access-Angriffe
# ---------------------------------------------------------------------------
class MieterAngriffTests(RbacBasis):

    def test_mieter_setzt_fremdes_ticket_auf_erledigt_team_route(self):
        self.client.force_login(self.u_mieter)
        r = self.client.post(f'/neu/schaeden/{self.ticket.pk}/status/', {'status': 'erledigt'})
        self.assertEqual(r.status_code, 403)
        self.nach_pruefen_unveraendert()

    def test_mieter_setzt_ticket_ueber_alle_schreibrouten_nicht_um(self):
        """Nicht nur /status/: auch Auftrag, Antwort, Foto, Löschen."""
        self.client.force_login(self.u_mieter)
        for suffix in ('status/', 'antwort/', 'auftrag/', 'foto/', 'loeschen/', 'ausstattung/'):
            with self.subTest(route=suffix):
                r = self.client.post(f'/neu/schaeden/{self.ticket.pk}/{suffix}',
                                     {'status': 'erledigt'})
                self.assertEqual(r.status_code, 403)
        self.nach_pruefen_unveraendert()
        self.assertTrue(SchadenMeldung.objects.filter(pk=self.ticket.pk).exists())

    def test_mieter_portal_fremdes_ticket_nachricht_und_status(self):
        """Portal-Weg: Nachricht an ein fremdes Ticket → gesperrt, nichts geschrieben."""
        vorher = TicketNachricht.objects.filter(ticket=self.ticket).count()
        self.client.force_login(self.u_mieter)
        r = self.client.post(f'/mieter/ticket/{self.ticket.pk}/nachricht/',
                             {'text': 'Erledigt, danke'})
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(TicketNachricht.objects.filter(ticket=self.ticket).count(), vorher)
        self.nach_pruefen_unveraendert()

    def test_mieter_portal_fremdes_ticket_lesen(self):
        self.client.force_login(self.u_mieter)
        r = self.client.get(f'/mieter/ticket/{self.ticket.pk}/')
        self.assertIn(r.status_code, (403, 404))

    def test_mieter_get_auf_status_route_liefert_keinen_inhalt(self):
        self.client.force_login(self.u_mieter)
        self.assertEqual(self.client.get(f'/neu/schaeden/{self.ticket.pk}/').status_code, 403)
        self.assertEqual(self.client.get('/neu/schaeden/').status_code, 403)


class HauswartAngriffTests(RbacBasis):

    #: Finanz-Dashboards, Mietzinse und alles, was Geld zeigt.
    FINANZ_ROUTEN = (
        '/neu/finanzen/', '/neu/buchhaltung/', '/neu/buchhaltung/export/',
        '/neu/buchhaltung/pdf/', '/neu/debitoren/', '/neu/kreditoren/',
        '/neu/zahllauf/', '/neu/bankabgleich/', '/neu/mwst/', '/neu/kautionen/',
        '/neu/mieterspiegel/', '/neu/auswertung/', '/neu/berichte/',
        '/neu/berichte/betriebskostenspiegel/', '/neu/mieterkonten/',
        '/neu/lieferantenkonten/', '/neu/vertraege/', '/neu/dashboard/',
    )

    def test_hauswart_sieht_keine_finanzseiten(self):
        self.client.force_login(self.u_hauswart)
        for pfad in self.FINANZ_ROUTEN:
            with self.subTest(pfad=pfad):
                r = self.client.get(pfad)
                self.assertNotEqual(r.status_code, 200, f'{pfad} liefert dem Hauswart Inhalt')
                self.assertIn(r.status_code, (403, 404))

    def test_hauswart_sieht_keine_mietzinse_auf_objekt_und_vertrag(self):
        self.client.force_login(self.u_hauswart)
        for pfad in (f'/neu/vertraege/{self.vertrag_fremd.pk}/',
                     f'/neu/vertraege/{self.vertrag_fremd.pk}/bearbeiten/',
                     f'/neu/liegenschaften/{self.lg.pk}/',
                     f'/neu/objekte/{self.einheit.pk}/',
                     f'/neu/personen/{self.mieter_fremd.pk}/',
                     f'/neu/mieterkonten/{self.mieter_fremd.pk}/',
                     f'/neu/personen/{self.mieter_fremd.pk}/kontoauszug/'):
            with self.subTest(pfad=pfad):
                self.assertEqual(self.client.get(pfad).status_code, 403)

    def test_hauswart_kann_mietzins_nicht_aendern(self):
        self.client.force_login(self.u_hauswart)
        r = self.client.post(f'/neu/vertrag-mietzins/{self.vertrag_fremd.pk}/',
                             {'netto_mietzins': '1'})
        self.assertEqual(r.status_code, 403)
        self.vertrag_fremd.refresh_from_db()
        self.assertEqual(self.vertrag_fremd.netto_mietzins, Decimal('1500'))

    def test_hauswart_darf_seine_eigene_arbeit(self):
        """Gegenprobe: Die Sperre ist keine Vollsperre — Tickets bleiben offen."""
        self.client.force_login(self.u_hauswart)
        self.assertEqual(self.client.get('/neu/schaeden/').status_code, 200)
        self.assertEqual(self.client.get(f'/neu/schaeden/{self.ticket.pk}/').status_code, 200)
        r = self.client.post(f'/neu/schaeden/{self.ticket.pk}/status/', {'status': 'erledigt'})
        self.assertEqual(r.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'erledigt')

    def test_hauswart_landet_nach_login_bei_den_schaeden(self):
        self.client.force_login(self.u_hauswart)
        r = self.client.get('/nach-login/')
        self.assertRedirects(r, '/neu/schaeden/', fetch_redirect_response=False)

    def test_hauswart_darf_keine_tickets_loeschen_oder_beauftragen(self):
        self.client.force_login(self.u_hauswart)
        for suffix in ('loeschen/', 'auftrag/', 'antwort/'):
            with self.subTest(route=suffix):
                r = self.client.post(f'/neu/schaeden/{self.ticket.pk}/{suffix}')
                self.assertEqual(r.status_code, 403)
        self.assertTrue(SchadenMeldung.objects.filter(pk=self.ticket.pk).exists())


class HauswartLiegenschaftTests(RbacBasis):
    """Der Hauswart sieht nur die Schäden SEINER Liegenschaften."""

    def test_liste_zeigt_nur_eigene_liegenschaft(self):
        self.client.force_login(self.u_hauswart)
        r = self.client.get('/neu/schaeden/', {'sicht': ''})
        self.assertContains(r, 'Heizung fällt aus')
        self.assertNotContains(r, 'Dach undicht')

    def test_liste_mit_fremdem_lg_filter_zeigt_nichts_fremdes(self):
        self.client.force_login(self.u_hauswart)
        r = self.client.get('/neu/schaeden/', {'sicht': '', 'lg': self.lg_fremd.pk})
        self.assertNotContains(r, 'Dach undicht')

    def test_detail_fremder_liegenschaft_ist_403(self):
        self.client.force_login(self.u_hauswart)
        self.assertEqual(self.client.get(f'/neu/schaeden/{self.ticket_fremd.pk}/').status_code, 403)
        self.assertEqual(self.client.get(f'/neu/schaeden/{self.ticket.pk}/').status_code, 200)

    def test_status_fremder_liegenschaft_ist_403_und_unveraendert(self):
        self.client.force_login(self.u_hauswart)
        r = self.client.post(f'/neu/schaeden/{self.ticket_fremd.pk}/status/', {'status': 'erledigt'})
        self.assertEqual(r.status_code, 403)
        self.ticket_fremd.refresh_from_db()
        self.assertEqual(self.ticket_fremd.status, 'in_bearbeitung')

    def test_ohne_zuordnung_sieht_der_hauswart_nichts(self):
        self.lg.hauswarte.remove(self.u_hauswart)
        self.client.force_login(self.u_hauswart)
        r = self.client.get('/neu/schaeden/', {'sicht': ''})
        self.assertNotContains(r, 'Heizung fällt aus')
        self.assertNotContains(r, 'Dach undicht')
        self.assertEqual(self.client.get(f'/neu/schaeden/{self.ticket.pk}/').status_code, 403)

    def test_hauswart_sieht_kein_formular_neue_meldung(self):
        """Das Absenden wäre ohnehin 403 — die Sackgasse gar nicht erst zeigen."""
        self.client.force_login(self.u_hauswart)
        r = self.client.get('/neu/schaeden/', {'sicht': ''})
        self.assertNotContains(r, '/neu/schaeden/neu/')
        self.assertNotContains(r, 'id="neuschaden"')
        self.client.force_login(self.u_verwalter)
        r = self.client.get('/neu/schaeden/', {'sicht': ''})
        self.assertContains(r, 'id="neuschaden"')

    def test_team_sieht_weiterhin_alles(self):
        self.client.force_login(self.u_verwalter)
        r = self.client.get('/neu/schaeden/', {'sicht': ''})
        self.assertContains(r, 'Heizung fällt aus')
        self.assertContains(r, 'Dach undicht')

    def test_inhaber_ordnet_hauswart_liegenschaften_zu(self):
        inhaber = _team_user('Inhaber')
        self.client.force_login(inhaber)
        self.client.post(f'/neu/benutzer/{self.u_hauswart.pk}/bearbeiten/', {
            'rolle': 'Hauswart', 'is_active': 'on', 'hauswart_lg': [self.lg_fremd.pk]})
        self.assertEqual(set(self.u_hauswart.hauswart_liegenschaften.all()), {self.lg_fremd})

    def test_rollenwechsel_loescht_die_zuordnung(self):
        inhaber = _team_user('Inhaber')
        self.client.force_login(inhaber)
        self.client.post(f'/neu/benutzer/{self.u_hauswart.pk}/bearbeiten/', {
            'rolle': 'Lesezugriff', 'is_active': 'on', 'hauswart_lg': [self.lg.pk]})
        self.assertFalse(self.u_hauswart.hauswart_liegenschaften.exists())


class EigentuemerAngriffTests(RbacBasis):

    ADMIN_ROUTEN = (
        '/neu/einstellungen/', '/neu/benutzer/', '/neu/benutzer/neu/',
        '/neu/abonnement/', '/neu/postfaecher/', '/neu/mwst/einstellungen/',
        '/neu/integrationen/portal-token/', '/neu/logbuch/',
    )

    def test_eigentuemer_oeffnet_kein_admin_panel(self):
        self.client.force_login(self.u_eigentuemer)
        for pfad in self.ADMIN_ROUTEN:
            with self.subTest(pfad=pfad):
                self.assertEqual(self.client.get(pfad).status_code, 403)

    def test_eigentuemer_aendert_keine_systemeinstellungen(self):
        self.client.force_login(self.u_eigentuemer)
        firma_vorher = self.org.firma
        for pfad in ('/neu/einstellungen/', '/neu/mwst/einstellungen/',
                     '/neu/postfaecher/antworten/'):
            with self.subTest(pfad=pfad):
                r = self.client.post(pfad, {'firma': 'GEHACKT AG', 'name': 'GEHACKT AG'})
                self.assertEqual(r.status_code, 403)
        self.org.refresh_from_db()
        self.assertEqual(self.org.firma, firma_vorher)

    def test_eigentuemer_legt_keinen_benutzer_an_und_hebt_keine_rolle(self):
        self.client.force_login(self.u_eigentuemer)
        r = self.client.post('/neu/benutzer/neu/', {
            'username': 'eindringling', 'rolle': 'Inhaber', 'passwort': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(username='eindringling').exists())
        self.assertFalse(Mitgliedschaft.objects.filter(benutzer=self.u_eigentuemer).exists())

    def test_eigentuemer_kommt_nicht_ins_django_admin(self):
        self.client.force_login(self.u_eigentuemer)
        r = self.client.get('/admin/')
        self.assertNotEqual(r.status_code, 200)
        self.assertFalse(self.u_eigentuemer.is_staff)

    def test_hauswart_und_mieter_kommen_nicht_ins_django_admin(self):
        for u in (self.u_hauswart, self.u_mieter):
            self.client.force_login(u)
            self.assertNotEqual(self.client.get('/admin/').status_code, 200)

    def test_eigentuemer_api_ist_gesperrt(self):
        self.client.force_login(self.u_eigentuemer)
        r = self.client.get('/api/rentals/')
        self.assertIn(r.status_code, (401, 403, 404))


# ---------------------------------------------------------------------------
# Sweep: JEDE Team-Route gegen JEDE Nicht-Team-Rolle
# ---------------------------------------------------------------------------
class RoutenSweepTests(RbacBasis):
    """Findet Routen, die niemand abgesichert hat.

    Erwartung je Nicht-Team-Rolle und je Route unter `/neu/`: **403**, für GET
    und POST. Der Hauswart ist ausgenommen, wo er ausdrücklich zugelassen ist.
    """

    #: Routen, die der Hauswart bewusst öffnen darf (Rolle-Konstante nennt sie).
    HAUSWART_ERLAUBT_GET = re.compile(r'^/neu/schaeden/(\d+/(status/)?)?$')
    HAUSWART_ERLAUBT_POST = re.compile(r'^/neu/schaeden/(\d+/(status/)?)?$')

    def _sweep(self, benutzer, erlaubt_get=None, erlaubt_post=None):
        self.client.force_login(benutzer)
        luecken = []
        routen = list(_team_routen())
        self.assertGreater(len(routen), 250, 'Routen-Discovery findet zu wenig — Test wertlos')
        for pfad in routen:
            for methode in ('get', 'post'):
                erlaubt = erlaubt_get if methode == 'get' else erlaubt_post
                if erlaubt and erlaubt.match(pfad):
                    continue
                r = getattr(self.client, methode)(pfad)
                if r.status_code != 403:
                    luecken.append(f'{methode.upper()} {pfad} → {r.status_code}')
        return luecken

    def test_mieter_bekommt_ueberall_403(self):
        self.assertEqual(self._sweep(self.u_mieter), [])

    def test_eigentuemer_bekommt_ueberall_403(self):
        self.assertEqual(self._sweep(self.u_eigentuemer), [])

    def test_hauswart_bekommt_ausser_schaeden_ueberall_403(self):
        self.assertEqual(
            self._sweep(self.u_hauswart, self.HAUSWART_ERLAUBT_GET, self.HAUSWART_ERLAUBT_POST),
            [])

    def test_weiterleitungen_zeigen_auf_geschuetzte_routen(self):
        self.client.force_login(self.u_mieter)
        for quelle, ziel in NUR_WEITERLEITUNG.items():
            r = self.client.get(quelle)
            self.assertRedirects(r, ziel, fetch_redirect_response=False)
            self.assertEqual(self.client.get(ziel).status_code, 403)

    def test_ohne_anmeldung_kein_inhalt(self):
        """Anonym: Weiterleitung auf die Anmeldung, nie 200."""
        offen = []
        for pfad in _team_routen():
            r = self.client.get(pfad)
            if r.status_code == 200:
                offen.append(pfad)
        self.assertEqual(offen, [])

    def test_lesezugriff_darf_nicht_schreiben(self):
        """Lesezugriff → GET ja, POST auf Änderungs-Routen nein."""
        self.client.force_login(self.u_lesend)
        r = self.client.post(f'/neu/schaeden/{self.ticket.pk}/status/', {'status': 'erledigt'})
        self.assertEqual(r.status_code, 403)
        self.nach_pruefen_unveraendert()

    def test_konstanten_bleiben_konsistent(self):
        self.assertTrue(set(TEAM_ROLLEN) <= set(TICKET_LESE_ROLLEN))
        self.assertIn(ROLLE_HAUSWART, TICKET_SCHREIB_ROLLEN)
        self.assertNotIn(ROLLE_HAUSWART, TEAM_ROLLEN)
