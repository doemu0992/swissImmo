"""Audit Phase 2 — die Einstiegspunkte OHNE Anmeldung.

WARUM DIESE LÜCKE ENTSTAND, und warum sie erst jetzt auffiel

Etappe 6.2 hängt den `TenantManager` an alle Modelle: ausserhalb einer
angemeldeten Anfrage wirft `Model.objects`. Für Scheduler-Befehle wurde das
gefunden und behoben (6.6). Übersehen wurde die zweite Sorte kontextloser
Aufrufe — die, die von AUSSEN kommen: Webhooks, öffentliche Formulare,
Token-Feeds. Dort gibt es keine Anmeldung, aus der die Middleware eine
Verwaltung ableiten könnte, und trotzdem ist eindeutig, um wessen Daten es
geht: Der Aufruf nennt einen Datensatz, und der trägt seine Organisation.

Kein Test fand das, und der Grund ist derselbe wie bei den Scheduler-Befehlen:
`core/tests/_helfer._test_organisation()` ruft `setze_organisation()`. Jeder
Test mit dem klassischen Helfer läuft mit gesetztem Kontext — auch der Test
eines anonymen Endpunkts. Geprüft wurde damit eine Welt, in der der Webhook
angemeldet ist.

DARAUS FOLGT DIE REGEL FÜR DIESE DATEI: `MandantenFixture`, und NIRGENDS ein
Kontext. Wer hier `_test_organisation()` einbaut, prüft wieder die falsche
Welt.
"""
import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from ._isolation import MandantenFixture


#: Alle Pflichtfelder des öffentlichen Formulars — aus `mietprozess/api.py`
#: abgelesen. Ninja lehnt sonst mit 422 ab, bevor die View überhaupt läuft,
#: und der Test prüfte dann die Formularvalidierung statt der Isolation.
PFLICHTFELDER = {
    'vorname': 'Anna', 'nachname': 'Muster', 'geburtsdatum': '1990-01-01',
    'geschlecht': 'w', 'nationalitaet': 'CH', 'mobilnummer': '079 000 00 00',
    'email': 'a@example.ch', 'adresse': 'Testweg 1', 'plz': '8000',
    'ort': 'Zürich', 'aktueller_vermieter': 'Vermietung AG',
    'kontaktperson_vermieter': 'Frau Muster', 'telefon_vermieter': '044 000 00 00',
    'erwerbsstatus': 'angestellt', 'beruf': 'Fachperson',
    'einkommen_jahr': '80000-100000', 'arbeitgeber': 'Firma AG',
    'angestellt_seit': '2020-01-01', 'kontaktperson_arbeitgeber': 'HR',
    'telefon_arbeitgeber': '044 111 11 11', 'gewuenschter_bezugstermin': '2026-10-01',
}


class OhneKontext(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        self.client = Client(raise_request_exception=False)


class BewerbungsformularTests(OhneKontext):
    """Das öffentliche Bewerbungsformular nimmt wieder Bewerbungen an."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for fixture in (cls.a, cls.b):
            fixture.einheit.zur_ausschreibung = True
            fixture.einheit.save(update_fields=['zur_ausschreibung'])

    def test_anonyme_bewerbung_wird_angenommen(self):
        # Über `Einheit.objects` fand der Endpunkt seit 6.2 gar nichts mehr:
        # Jede Bewerbung endete im Fehler. Für eine Verwaltung, die über das
        # Formular vermietet, heisst das: keine Bewerbungen mehr, ohne dass
        # irgendwo etwas rot geworden wäre.
        from mietprozess.models import Mietbewerbung

        antwort = self.client.post(
            '/api/mietprozess/public/bewerben',
            {**PFLICHTFELDER, 'einheit_id': self.b.einheit.pk})
        self.assertIn(antwort.status_code, (200, 201),
                      f'Bewerbung abgelehnt: {antwort.content[:200]}')

        neu = Mietbewerbung.alle_organisationen.filter(nachname='Muster').first()
        self.assertIsNotNone(neu, 'Die Bewerbung wurde nicht gespeichert.')
        self.assertEqual(neu.organisation_id, self.b.organisation.pk,
                         'Die Bewerbung landete in der falschen Verwaltung.')

    def test_gegenprobe_nicht_ausgeschriebenes_objekt_wird_abgelehnt(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass die Absicherung
        # `zur_ausschreibung` ist und nicht der Manager.
        self.a.einheit.zur_ausschreibung = False
        self.a.einheit.save(update_fields=['zur_ausschreibung'])
        antwort = self.client.post(
            '/api/mietprozess/public/bewerben',
            {**PFLICHTFELDER, 'einheit_id': self.a.einheit.pk})
        self.assertEqual(antwort.status_code, 400)


class DocusealWebhookTests(OhneKontext):
    """Ein unterschriebener Vertrag wird abgelegt — auch ohne Anmeldung."""

    def test_event_findet_den_vertrag(self):
        # Vorher warf die Suche, die Ausnahme wurde vom Aufrufer geschluckt,
        # und der Webhook meldete 200 OK. Ein unterschriebener Vertrag wurde
        # damit NIE abgelegt, ohne dass irgendwo ein Fehler erschien — die
        # unangenehmste Sorte Defekt.
        from rentals.services import verarbeite_docuseal_event

        with patch('core.services.docuseal_service.download_url_erlaubt',
                   return_value=False) as erlaubt:
            verarbeite_docuseal_event({
                'event_type': 'form.completed',
                'data': {'status': 'completed',
                         'name': f'Mietvertrag {self.b.vertrag.pk}',
                         'combined_document_url': 'https://example.invalid/x.pdf'}})

        # Der Download wird bewusst abgelehnt (kein Netz im Test). Dass die
        # Prüfung überhaupt erreicht wird, belegt: der Vertrag WURDE gefunden.
        self.assertTrue(erlaubt.called,
                        'Der Vertrag wurde nicht gefunden — der Lauf brach vorher ab.')

    def test_unbekannte_vertragsnummer_bleibt_folgenlos(self):
        from rentals.services import verarbeite_docuseal_event
        self.assertFalse(verarbeite_docuseal_event({
            'event_type': 'form.completed',
            'data': {'status': 'completed', 'name': 'Mietvertrag 999999'}}))


class BrevoWebhookTests(OhneKontext):
    """Eine Mail-Antwort auf ein Ticket geht nicht verloren.

    ZWEI DEFEKTE ÜBEREINANDER, gefunden am 18.08.2026. Der erste: `objects`
    statt `alle_organisationen` — der Webhook warf ohne Mandantenkontext. Der
    zweite fiel erst beim Test dafür auf: Die View war in **keiner** URL-Zeile
    eingetragen. Sie war von aussen gar nicht erreichbar, eingehende Antworten
    landeten also ohnehin nirgends.

    Beides behoben, die Route ist seit dem 18.08.2026 scharfgeschaltet. Dieser
    Testsatz ruft sie deshalb über HTTP auf, nicht mehr direkt — vorher stand
    hier ein Wächter, der festhielt, dass es die Route NICHT gibt.
    """

    def _senden(self, betreff, text='Handwerker kommt Dienstag.', secret='geheim',
                mitgeben='geheim'):
        kopf = {'HTTP_X_WEBHOOK_SECRET': mitgeben} if mitgeben else {}
        with self.settings(BREVO_WEBHOOK_SECRET=secret):
            return self.client.post(
                reverse('brevo_inbound_webhook'),
                json.dumps({'Subject': betreff, 'RawTextBody': text,
                            'From': 'mieter@example.ch'}),
                content_type='application/json', **kopf)

    def test_antwort_landet_am_ticket_der_richtigen_verwaltung(self):
        from tickets.models import TicketNachricht

        antwort = self._senden(f'Re: Schaden #{self.b.schaden.pk}')
        self.assertEqual(antwort.status_code, 200, antwort.content[:200])

        nachricht = TicketNachricht.alle_organisationen.filter(
            nachricht__contains='Dienstag').first()
        self.assertIsNotNone(nachricht, 'Die Mail-Antwort wurde nicht gespeichert.')
        self.assertEqual(nachricht.ticket_id, self.b.schaden.pk)
        self.assertEqual(nachricht.organisation_id, self.b.organisation.pk,
                         'Die Nachricht landete in der falschen Verwaltung.')

    def test_ohne_secret_wird_abgewiesen(self):
        # Die Route ist jetzt öffentlich erreichbar — ohne diese Prüfung könnte
        # jeder Nachrichten in fremde Ticketverläufe schreiben.
        self.assertEqual(self._senden('Re: Schaden #1', mitgeben=None).status_code, 403)

    def test_mit_falschem_secret_wird_abgewiesen(self):
        self.assertEqual(
            self._senden('Re: Schaden #1', mitgeben='falsch').status_code, 403)

    def test_ohne_konfiguriertes_secret_wird_abgewiesen(self):
        # Fail-closed: Ist auf dem Server kein Secret gesetzt, ist der Endpunkt
        # zu — nicht offen. Sonst wäre eine vergessene Variable eine offene Tür.
        self.assertEqual(
            self._senden('Re: Schaden #1', secret=None, mitgeben='egal').status_code, 403)


class IcalFeedTests(OhneKontext):
    """Der Fristen-Feed liefert die Fristen SEINER Verwaltung — und nur die."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from datetime import date, timedelta

        from core.models import Pendenz
        from core.tenancy import organisation_kontext
        for fixture in (cls.a, cls.b):
            with organisation_kontext(fixture.organisation):
                Pendenz.objects.create(
                    titel=f'Frist {fixture.kuerzel}', erledigt=False,
                    faellig_am=date.today() + timedelta(days=3))

    def _feed(self, organisation):
        from core.services.ical import feed_token
        return self.client.get('/fristen.ics', {'token': feed_token(organisation)})

    def test_feed_zeigt_die_eigenen_fristen(self):
        antwort = self._feed(self.b.organisation)
        self.assertEqual(antwort.status_code, 200, antwort.content[:200])
        self.assertIn('Frist B', antwort.content.decode('utf-8'))

    def test_feed_zeigt_die_fremden_nicht(self):
        # Der Token signierte vorher die Konstante 'fristen' — derselbe Token
        # galt damit für JEDE Verwaltung. In den Fristen stehen Mieternamen.
        inhalt = self._feed(self.b.organisation).content.decode('utf-8')
        self.assertNotIn('Frist A', inhalt)

    def test_gegenprobe_der_andere_token_zeigt_die_andere(self):
        inhalt = self._feed(self.a.organisation).content.decode('utf-8')
        self.assertIn('Frist A', inhalt)
        self.assertNotIn('Frist B', inhalt)

    def test_ohne_token_bleibt_es_bei_403(self):
        self.assertEqual(self.client.get('/fristen.ics').status_code, 403)

    def test_erfundener_token_wird_abgewiesen(self):
        self.assertEqual(
            self.client.get('/fristen.ics', {'token': 'fristen:1:erfunden'}).status_code, 403)


class VorlagenSeedTests(OhneKontext):
    """Der Seed erzeugt keine Duplikate — auch nicht aus einer Anfrage heraus."""

    def test_zweiter_lauf_im_kontext_legt_nichts_an(self):
        # Der bestehende Test prüfte nur den KONTEXTLOSEN Lauf und blieb grün.
        # Aus der Oberfläche ist ein Kontext gesetzt; `Vorlage.save()` trug ihn
        # seit Etappe 6.4 ein, die Vorhandenseins-Prüfung sucht aber nach
        # `organisation IS NULL` — und sah die eigene Anlage darum nie.
        # Gemessen vor der Behebung: 9 + 9 = 20 Vorlagen.
        from core.services.vorlagen_defaults import seed_standard_vorlagen
        from core.tenancy import organisation_kontext
        from crm.models import Vorlage

        with organisation_kontext(self.a.organisation):
            erste = seed_standard_vorlagen()
            zweite = seed_standard_vorlagen()

        self.assertGreater(erste, 0, 'Es wurde gar nichts angelegt — Test prüft nichts.')
        self.assertEqual(zweite, 0, f'Der zweite Lauf hat {zweite} Duplikate erzeugt.')

    def test_die_angelegten_gehoeren_niemandem(self):
        from core.services.vorlagen_defaults import seed_standard_vorlagen
        from core.tenancy import organisation_kontext
        from crm.models import Vorlage

        with organisation_kontext(self.a.organisation):
            seed_standard_vorlagen()

        # Nur die GESEEDETEN prüfen — das Fixture legt je Verwaltung eine
        # eigene Vorlage an, die selbstverständlich eine Organisation trägt.
        from core.services.vorlagen_defaults import STANDARD_VORLAGEN
        namen = [d['name'] for d in STANDARD_VORLAGEN]
        zugeschlagen = Vorlage.alle_organisationen.filter(
            name__in=namen, organisation__isnull=False)
        self.assertEqual(
            list(zugeschlagen.values_list('name', flat=True)), [],
            'Eine mitgelieferte Vorlage wurde der aufrufenden Verwaltung '
            'zugeschlagen — die anderen sähen sie nicht.')


class MarktdatenBedeutungTests(OhneKontext):
    """`None` heisst nicht mehr „alle" — „alle" muss man sagen."""

    DATEN = {'ref_zins': '1.50', 'lik': '108.0'}

    def test_ohne_angabe_ist_ein_fehler_keine_stille_ausweitung(self):
        # Zwei Aufrufer übergaben `aktuelle_organisation()`. Ist der Kontext
        # leer, wird daraus None — und None bedeutete „alle Verwaltungen".
        # Aus „schreibe meinen Zinssatz" wurde damit „schreibe in jede fremde".
        from core.utils.market_data import update_verwaltung_rates
        with self.assertRaises(ValueError):
            update_verwaltung_rates(None)

    def test_mit_alle_true_geht_es_weiterhin(self):
        from decimal import Decimal

        from core.utils.market_data import update_verwaltung_rates
        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=({'ref_zins': Decimal('1.50'),
                                  'lik': Decimal('108.0')}, [])):
            update_verwaltung_rates(alle=True)
        for fixture in (self.a, self.b):
            fixture.organisation.refresh_from_db()
            self.assertEqual(fixture.organisation.aktueller_referenzzinssatz,
                             Decimal('1.50'))

    def test_eine_verwaltung_laesst_die_andere_unberuehrt(self):
        from decimal import Decimal

        from core.utils.market_data import update_verwaltung_rates
        with patch('core.utils.market_data.fetch_market_rates',
                   return_value=({'ref_zins': Decimal('1.50'),
                                  'lik': Decimal('108.0')}, [])):
            update_verwaltung_rates(self.b.organisation)
        self.a.organisation.refresh_from_db()
        self.assertIsNone(self.a.organisation.letztes_update_marktdaten,
                          'Der Frischestempel von A wurde fremd gesetzt.')


class GeteiltesKontoTests(OhneKontext):
    """Ein Mensch in zwei Verwaltungen wird nicht von einer ganz gelöscht."""

    def setUp(self):
        super().setUp()
        from crm.models import Mitgliedschaft
        # Der Benutzer von B ist zusätzlich Mitglied bei A — eine Treuhänderin.
        Mitgliedschaft.alle_organisationen.create(
            benutzer=self.b.benutzer, organisation=self.a.organisation,
            rolle=Mitgliedschaft.ROLLE_VERWALTER)
        self.client.force_login(self.a.benutzer)

    def test_loeschen_entfernt_nur_die_eigene_mitgliedschaft(self):
        # `ziel.delete()` hätte das Konto überall entfernt: Verwaltung A hätte
        # den Zugang von Verwaltung B gelöscht, samt deren Logbucheinträgen und
        # im schlimmsten Fall deren letztem Administrator.
        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        self.client.post(reverse('fw_benutzer_loeschen', args=[self.b.benutzer.pk]))

        self.assertTrue(Benutzer.objects.filter(pk=self.b.benutzer.pk).exists(),
                        'Das geteilte Konto wurde ganz gelöscht.')
        self.assertFalse(
            Mitgliedschaft.alle_organisationen.filter(
                benutzer=self.b.benutzer, organisation=self.a.organisation).exists(),
            'Die Mitgliedschaft bei A wurde nicht entfernt.')
        self.assertTrue(
            Mitgliedschaft.alle_organisationen.filter(
                benutzer=self.b.benutzer, organisation=self.b.organisation).exists(),
            'Die Mitgliedschaft bei B wurde mitgelöscht.')

    def test_gegenprobe_das_letzte_mitglied_wird_ganz_geloescht(self):
        # Ohne diese Gegenprobe wäre nicht belegt, dass überhaupt noch gelöscht
        # wird — sonst bliebe jedes Konto ewig bestehen.
        from benutzer.models import Benutzer
        from crm.models import Mitgliedschaft

        Mitgliedschaft.alle_organisationen.filter(
            benutzer=self.b.benutzer, organisation=self.b.organisation).delete()
        self.client.post(reverse('fw_benutzer_loeschen', args=[self.b.benutzer.pk]))
        self.assertFalse(Benutzer.objects.filter(pk=self.b.benutzer.pk).exists())
