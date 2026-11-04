"""Antwortadresse der Plattform je Verwaltung (4.11.2026).

Jede Verwaltung hat automatisch `<kennung>@<ANTWORT_DOMAIN>`; Ticket- und Chat-Mails tragen sie als Reply-To,
der Brevo-Webhook ordnet die Antwort über die EMPFÄNGERADRESSE der Verwaltung zu. Ein eigenes Postfach geht vor.

Jede Klasse nennt ihre GEGENPROBE im Docstring (Code temporär ändern -> der Test wird rot).
"""
import importlib
import json
import re
from datetime import timedelta

from django.apps import apps
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tenancy import organisation_kontext

from ._helfer import _test_organisation
from ._isolation import MandantenFixture
from .test_direktkanal import HANDWERKER, MIETER, _auftrag_einfach
from .test_ticket_workflow import MAIL

DOMAIN = 'immoswiss.app'
SECRET = 'geheim'


def _brevo(an, betreff, text='Dienstag passt.', von=MIETER, kopf=None, mid=None, html=None, extracted=None,
           empfaenger=None):
    """Eine Mail im Format von Brevo Inbound Parsing (`items[]`)."""
    item = {
        'From': {'Name': 'Hans Muster', 'Address': von},
        'To': [{'Name': None, 'Address': an}],
        'Subject': betreff,
        'RawTextBody': text,
        'Headers': kopf or {},
    }
    if empfaenger is not None:
        item['Recipients'] = [{'Address': a} for a in empfaenger]
    if mid:
        item['MessageId'] = mid
    if html is not None:
        item['RawHtmlBody'] = html
    if extracted is not None:
        item['ExtractedMarkdownMessage'] = extracted
    return {'items': [item]}


def _senden(nutzlast, secret=SECRET, mitgeben=SECRET):
    kopf = {'HTTP_X_WEBHOOK_SECRET': mitgeben} if mitgeben else {}
    with override_settings(BREVO_WEBHOOK_SECRET=secret):
        return Client(raise_request_exception=False).post(
            reverse('brevo_inbound_webhook'), json.dumps(nutzlast), content_type='application/json', **kopf)


def _adresse(org):
    return f'{org.antwort_kennung}@{DOMAIN}'


class KennungTests(TestCase):
    """Gegenprobe: in `Organisation.save` das Vergeben entfernen -> `test_neue_verwaltung...` rot (Unique-
    Verletzung beim zweiten Anlegen); in `neue_kennung` den Zufall durch eine feste Zeichenfolge ersetzen
    -> `test_kennung_ist_nicht_erratbar` rot; in 0062 den Aufruf von `update` entfernen -> `test_datenmigration...` rot."""

    def test_neue_verwaltung_bekommt_automatisch_eine_eindeutige_kennung(self):
        from crm.models import Organisation
        a = Organisation.objects.create(firma='Müller & Söhne Immobilien AG', strasse='x', plz='8000', ort='Z')
        b = Organisation.objects.create(firma='Müller & Söhne Immobilien AG', strasse='x', plz='8000', ort='Z')
        for org in (a, b):
            self.assertRegex(org.antwort_kennung, r'^[a-z0-9]{1,12}-[a-z0-9]{10}$')
        self.assertNotEqual(a.antwort_kennung, b.antwort_kennung)
        self.assertTrue(a.antwort_kennung.startswith('mullersohnei'))
        self.assertLessEqual(len(_adresse(a)), 254)

    def test_kennung_ist_nicht_erratbar(self):
        from core.services.antwort_eingang import neue_kennung
        zufall = {neue_kennung('Muster AG').split('-')[1] for _ in range(50)}
        self.assertEqual(len(zufall), 50)

    def test_firma_ohne_verwertbare_zeichen_hat_trotzdem_ein_praefix(self):
        from core.services.antwort_eingang import neue_kennung
        self.assertRegex(neue_kennung('***'), r'^verwaltung-[a-z0-9]{10}$')

    def test_datenmigration_vergibt_fehlende_kennungen_fuer_den_bestand(self):
        modul = importlib.import_module('crm.migrations.0062_antwort_kennung_vergeben')
        from crm.models import Organisation
        a = _test_organisation()
        b = Organisation.objects.create(firma='Zweite AG', strasse='x', plz='3000', ort='Bern')
        vorher_b = b.antwort_kennung
        Organisation.objects.filter(pk=a.pk).update(antwort_kennung='')
        modul.kennung_vergeben(apps, None)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertRegex(a.antwort_kennung, r'^[a-z0-9]+-[a-z0-9]{10}$')
        self.assertEqual(b.antwort_kennung, vorher_b, 'Eine vorhandene Kennung darf nicht überschrieben werden.')


class ErneuernTests(TestCase):
    """Gegenprobe: in `organisation_zu_adresse` die Prüfung `alte_kennung_gilt` entfernen -> `..._nach_30_tagen...`
    rot; in `kennung_erneuern` das Setzen von `antwort_kennung_alt` entfernen -> `..._bleibt_im_fenster...` rot."""

    def test_alte_adresse_bleibt_im_fenster_gueltig_danach_nicht(self):
        from core.services.antwort_eingang import kennung_erneuern, organisation_zu_adresse
        org = _test_organisation()
        alt = _adresse(org)
        jetzt = timezone.now()
        neu = kennung_erneuern(org, jetzt=jetzt)
        self.assertNotEqual(alt, neu)
        self.assertEqual(organisation_zu_adresse(neu, jetzt=jetzt).pk, org.pk)
        self.assertEqual(organisation_zu_adresse(alt, jetzt=jetzt + timedelta(days=29)).pk, org.pk)
        self.assertIsNone(organisation_zu_adresse(alt, jetzt=jetzt + timedelta(days=30, minutes=1)))
        self.assertEqual(organisation_zu_adresse(neu, jetzt=jetzt + timedelta(days=90)).pk, org.pk)

    def test_adresse_ist_case_insensitiv_und_nur_auf_der_antwortdomain(self):
        from core.services.antwort_eingang import organisation_zu_adresse
        org = _test_organisation()
        self.assertEqual(organisation_zu_adresse(f'Hans <{org.antwort_kennung.upper()}@IMMOSWISS.APP>').pk, org.pk)
        self.assertIsNone(organisation_zu_adresse(f'{org.antwort_kennung}@example.ch'))
        with override_settings(ANTWORT_DOMAIN='antwort.immoswiss.app'):
            self.assertIsNone(organisation_zu_adresse(f'{org.antwort_kennung}@immoswiss.app'))
            self.assertEqual(organisation_zu_adresse(f'{org.antwort_kennung}@antwort.immoswiss.app').pk, org.pk)

    def test_kennungen_zweier_verwaltungen_verwechseln_sich_nicht(self):
        from core.services.antwort_eingang import organisation_zu_adresse
        a, b = MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
        self.assertEqual(organisation_zu_adresse(_adresse(a.organisation)).pk, a.organisation.pk)
        self.assertEqual(organisation_zu_adresse(_adresse(b.organisation)).pk, b.organisation.pk)


@MAIL
class ReplyToTests(TestCase):
    """Gegenprobe: in `reply_to` den Zweig «Plattformadresse» entfernen -> `..._plattformadresse` rot;
    die Postfach-Abfrage hinter den Plattformzweig stellen -> `..._eigenes_postfach_geht_vor` rot;
    `isinstance(..., SchadenMeldung)` entfernen -> `..._andere_objekte_...` rot."""

    def test_ohne_postfach_gilt_die_plattformadresse(self):
        from tickets.workflow import reply_to
        t, _a = _auftrag_einfach()
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            self.assertEqual(reply_to(t), _adresse(t.organisation))

    def test_eigenes_aktives_postfach_geht_vor(self):
        from core.models import Postfach
        from tickets.workflow import reply_to
        t, _a = _auftrag_einfach()
        pf = Postfach.alle_organisationen.create(
            organisation=t.organisation, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
            benutzer='antworten@eigen.ch', server='imap.example.ch')
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            self.assertEqual(reply_to(t), 'antworten@eigen.ch')
            pf.aktiv = False
            pf.save()
            self.assertEqual(reply_to(t), _adresse(t.organisation), 'Ein abgeschaltetes Postfach gilt nicht.')

    def test_ohne_empfang_auf_dem_server_bleibt_alles_wie_bisher(self):
        from tickets.workflow import reply_to
        t, _a = _auftrag_einfach()
        with override_settings(BREVO_WEBHOOK_SECRET=None):
            self.assertIsNone(reply_to(t))

    def test_andere_objekte_als_tickets_behalten_ihr_bisheriges_verhalten(self):
        """Mahnung, Zirkular, Budget: eine Antwort hätte kein Ticket und ginge am Eingang verloren."""
        from types import SimpleNamespace

        from tickets.workflow import reply_to
        t, _a = _auftrag_einfach()
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            self.assertIsNone(reply_to(SimpleNamespace(organisation_id=t.organisation_id)))

    def test_ausgehende_mail_traegt_die_adresse_im_reply_to_header(self):
        from tickets import direktkanal
        t, a = _auftrag_einfach()
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            direktkanal.schreiben(a, 'mieter', 'Hallo')
        m = mail.outbox[0]
        self.assertEqual(m.reply_to, [_adresse(t.organisation)])
        self.assertRegex(m.message()['Reply-To'], r'^[a-z0-9-]+@immoswiss\.app$')
        self.assertIn('via', m.from_email)                       # «<Name> via immoswiss» bleibt


@MAIL
class WebhookEingangTests(TestCase):
    """Gegenprobe: in `_eine_mail` die Auswertung von `Recipients`/`To` entfernen -> Zuordnungstests rot; `items`
    nicht mehr lesen -> `test_items_format...` rot; das Flachformat streichen -> `test_altes_flaches_format...` rot;
    `hintergrund_erlaubt`/Idempotenz-Anspruch entfernen -> `test_gleiche_message_id...` rot."""

    def test_items_format_ordnet_ueber_die_empfaengeradresse_zu(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        r = _senden(_brevo(_adresse(t.organisation), f'Re: Wasserhahn tropft (Ticket #{t.pk})'))
        self.assertEqual((r.status_code, r.json()['status']), (200, 'ok, saved'))
        n = TicketNachricht.alle_organisationen.get(ticket=t, typ='mail_antwort')
        self.assertEqual(n.nachricht, 'Dienstag passt.')
        self.assertIn('hans@example.ch', n.absender_name)
        self.assertEqual(n.organisation_id, t.organisation_id)

    def test_recipients_gelten_vor_to_und_gross_klein_ist_egal(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo('irgendwer@example.ch', f'Re: Ticket #{t.pk}',
                          empfaenger=[_adresse(t.organisation).upper()])
        self.assertEqual(_senden(nutzlast).json()['status'], 'ok, saved')
        self.assertEqual(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').count(), 1)

    def test_altes_flaches_format_funktioniert_weiter(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        r = _senden({'Subject': f'Re: Schaden #{t.pk}', 'RawTextBody': 'Alt.', 'From': MIETER})
        self.assertEqual((r.status_code, r.json()['status']), (200, 'ok, saved'))
        self.assertTrue(TicketNachricht.alle_organisationen.filter(ticket=t, nachricht='Alt.').exists())

    def test_altes_globales_reply_mit_ticketnummer_bleibt_der_rueckfall(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        r = _senden(_brevo(f'reply@{DOMAIN}', f'Re: Ticket #{t.pk}'))
        self.assertEqual(r.json()['status'], 'ok, saved')
        self.assertTrue(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').exists())

    def test_nur_der_textteil_html_wird_nie_uebernommen(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', text='',
                          html='<p>Hallo <b>Welt</b></p><script>alert(1)</script><p>Am 01.01. schrieb X:</p>')
        _senden(nutzlast)
        n = TicketNachricht.alle_organisationen.get(ticket=t, typ='mail_antwort')
        self.assertEqual(n.nachricht, 'Hallo Welt')
        self.assertNotIn('<', n.nachricht)

    def test_extrahierter_antworttext_wird_bevorzugt_und_gekuerzt(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        lang = 'x' * 50000
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', text='Zitat und Signatur',
                          extracted=lang)
        _senden(nutzlast)
        n = TicketNachricht.alle_organisationen.get(ticket=t, typ='mail_antwort')
        self.assertEqual(len(n.nachricht), 10000)

    def test_antworttext_kuerzt_jede_quelle_selbst(self):
        from core.services.antwort_eingang import TEXT_MAX, antworttext
        lang = 'x' * (TEXT_MAX + 500)
        for item in ({'ExtractedMarkdownMessage': lang}, {'RawTextBody': lang}, {'RawHtmlBody': f'<p>{lang}</p>'}):
            self.assertEqual(len(antworttext(item)), TEXT_MAX, item.keys())
        self.assertEqual(antworttext({'ExtractedMarkdownMessage': 'Neu.', 'RawTextBody': 'Alt.'}), 'Neu.')
        self.assertEqual(antworttext({'RawTextBody': 'Ja.\n\nAm 01.11.2026 um 10:00 schrieb X:\n> Zitat'}), 'Ja.')

    def test_secret_fehlt_oder_falsch_ergibt_403_und_legt_nichts_an(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}')
        self.assertEqual(_senden(nutzlast, mitgeben=None).status_code, 403)
        self.assertEqual(_senden(nutzlast, mitgeben='falsch').status_code, 403)
        self.assertEqual(_senden(nutzlast, secret=None, mitgeben='egal').status_code, 403)
        self.assertFalse(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').exists())

    def test_unbekannte_kennung_auf_der_antwortdomain_wird_verworfen_nicht_geraten(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        r = _senden(_brevo(f'erfunden-abcdefghij@{DOMAIN}', f'Re: Ticket #{t.pk}'))
        self.assertEqual((r.status_code, r.json()['status']), (200, 'ignored'))
        self.assertFalse(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').exists())

    def test_mail_an_zwei_verwaltungen_wird_verworfen(self):
        from tickets.models import TicketNachricht
        a, b = MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
        nutzlast = _brevo(_adresse(a.organisation), f'Re: Ticket #{a.schaden.pk}',
                          empfaenger=[_adresse(a.organisation), _adresse(b.organisation)])
        self.assertEqual(_senden(nutzlast).json()['status'], 'ignored')
        self.assertFalse(TicketNachricht.alle_organisationen.filter(typ='mail_antwort').exists())

    def test_ungueltiges_json_und_leere_items(self):
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            c = Client(raise_request_exception=False)
            url = reverse('brevo_inbound_webhook')
            self.assertEqual(c.post(url, 'kein json', content_type='application/json',
                                    HTTP_X_WEBHOOK_SECRET=SECRET).status_code, 400)
            self.assertEqual(c.post(url, '{"items": []}', content_type='application/json',
                                    HTTP_X_WEBHOOK_SECRET=SECRET).status_code, 400)
            self.assertEqual(c.get(url).status_code, 405)

    def test_mehrere_items_werden_alle_verarbeitet(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        eins = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', text='Eins.', mid='m-1')['items'][0]
        zwei = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', text='Zwei.', mid='m-2')['items'][0]
        r = _senden({'items': [eins, zwei]})
        self.assertEqual(r.json()['items'], ['ok, saved', 'ok, saved'])
        self.assertEqual(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').count(), 2)


@MAIL
class WebhookIsolationTests(TestCase):
    """Mail an die Adresse von A mit der Ticketnummer von B: nichts entsteht, und die Antwort ist dieselbe wie bei
    einer Nummer, die es nirgends gibt.

    Gegenprobe: in `eingehende_antwort_verarbeiten` `SchadenMeldung.objects` durch `.alle_organisationen` ersetzen
    -> `test_ticket_einer_anderen_verwaltung...` rot (die Nachricht landet bei B)."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_ticket_einer_anderen_verwaltung_legt_nichts_an_und_verraet_nichts(self):
        from tickets.models import TicketNachricht
        vorher = TicketNachricht.alle_organisationen.count()
        an_a = _adresse(self.a.organisation)
        fremd = _senden(_brevo(an_a, f'Re: Ticket #{self.b.schaden.pk}'))
        nirgends = _senden(_brevo(an_a, 'Re: Ticket #999999'))
        self.assertEqual((fremd.status_code, fremd.json()), (nirgends.status_code, nirgends.json()))
        self.assertEqual(fremd.status_code, 200)
        self.assertEqual(TicketNachricht.alle_organisationen.count(), vorher)

    def test_ticket_einer_anderen_verwaltung_ueber_die_marke_ebenfalls_nicht(self):
        from tickets.models import TicketNachricht
        vorher = TicketNachricht.alle_organisationen.count()
        betreff = f'Re: Ticket #{self.b.schaden.pk} [A{self.b.auftrag.pk}]' if hasattr(self.b, 'auftrag') \
            else f'Re: Ticket #{self.b.schaden.pk} [A1]'
        _senden(_brevo(_adresse(self.a.organisation), betreff))
        self.assertEqual(TicketNachricht.alle_organisationen.count(), vorher)

    def test_eigenes_ticket_landet_bei_der_richtigen_verwaltung(self):
        from tickets.models import TicketNachricht
        r = _senden(_brevo(_adresse(self.b.organisation), f'Re: Ticket #{self.b.schaden.pk}'))
        self.assertEqual(r.json()['status'], 'ok, saved')
        n = TicketNachricht.alle_organisationen.get(typ='mail_antwort')
        self.assertEqual((n.ticket_id, n.organisation_id), (self.b.schaden.pk, self.b.organisation.pk))


@MAIL
class WebhookIdempotenzTests(TestCase):
    """Gegenprobe: in `_eine_mail` den `get_or_create` der Message-ID entfernen -> der Test wird rot (zwei Einträge)."""

    def test_gleiche_message_id_wird_nicht_doppelt_verarbeitet(self):
        from tickets.models import EingegangeneMail, TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', mid='<abc@mail.example>')
        self.assertEqual(_senden(nutzlast).json()['status'], 'ok, saved')
        self.assertEqual(_senden(nutzlast).json()['status'], 'duplicate')
        self.assertEqual(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').count(), 1)
        self.assertEqual(EingegangeneMail.alle_organisationen.count(), 1)

    def test_message_id_im_kopf_zaehlt_auch(self):
        from tickets.models import TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', kopf={'Message-ID': '<kopf@x>'})
        _senden(nutzlast)
        _senden(nutzlast)
        self.assertEqual(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').count(), 1)

    def test_scheitert_die_verarbeitung_wird_die_id_nicht_vermerkt(self):
        """Brevo wiederholt bei 500; die Wiederholung muss die Antwort nachholen können."""
        from unittest import mock

        from tickets.models import EingegangeneMail, TicketNachricht
        t, _a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk}', mid='retry-1')
        with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten', side_effect=RuntimeError('x')):
            self.assertEqual(_senden(nutzlast).status_code, 500)
        self.assertEqual(EingegangeneMail.alle_organisationen.count(), 0)
        self.assertEqual(_senden(nutzlast).json()['status'], 'ok, saved')
        self.assertEqual(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').count(), 1)

    def test_dieselbe_id_in_zwei_verwaltungen_ist_zwei_verschiedene_mails(self):
        a, b = MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
        for f in (a, b):
            r = _senden(_brevo(_adresse(f.organisation), f'Re: Ticket #{f.schaden.pk}', mid='gleich'))
            self.assertEqual(r.json()['status'], 'ok, saved')


@MAIL
class WebhookDirektkanalTests(TestCase):
    """Die Brücke Mieter <-> Handwerker über den neuen Eingang.

    Gegenprobe: in `antwort_zuordnen` den Aufruf `direktkanal.aus_mail` entfernen -> `test_mieter_antwort...` rot;
    in `direktkanal.automatisch` die Prüfung auf `Auto-Submitted` entfernen -> `test_autoreply...` rot."""

    def test_mieter_antwort_landet_im_chat_und_der_handwerker_bekommt_eine_mail(self):
        t, a = _auftrag_einfach()
        nutzlast = _brevo(_adresse(t.organisation), f'Re: Termin (Ticket #{t.pk}) [A{a.pk}]',
                          text='Gern am Donnerstag.', mid='chat-1')
        r = _senden(nutzlast)
        self.assertEqual(r.json()['status'], 'ok, chat')
        self.assertEqual(a.direktnachrichten.get().nachricht, 'Gern am Donnerstag.')
        self.assertEqual([m.to for m in mail.outbox], [[HANDWERKER]])
        self.assertEqual(mail.outbox[0].reply_to, [_adresse(t.organisation)])

    def test_handwerker_antwort_geht_an_den_mieter(self):
        t, a = _auftrag_einfach()
        _senden(_brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk} [A{a.pk}]', von=HANDWERKER, text='Ich komme.'))
        self.assertEqual([m.to for m in mail.outbox], [[MIETER]])

    def test_autoreply_wird_nicht_weitergeleitet(self):
        t, a = _auftrag_einfach()
        for kopf in ({'Auto-Submitted': 'auto-replied'}, {'X-Immoswiss-Bridge': '1'}, ['Precedence: bulk'],
                     'Auto-Submitted: auto-generated\nMessage-ID: <x@y>'):
            _senden(_brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk} [A{a.pk}]', text='Urlaub.', kopf=kopf))
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_fremder_absender_geht_in_den_verlauf_und_wird_nicht_weitergeleitet(self):
        from tickets.models import TicketNachricht
        t, a = _auftrag_einfach()
        _senden(_brevo(_adresse(t.organisation), f'Re: Ticket #{t.pk} [A{a.pk}]', von='fremd@example.org'))
        self.assertEqual(a.direktnachrichten.count(), 0)
        self.assertEqual(mail.outbox, [])
        self.assertTrue(TicketNachricht.alle_organisationen.filter(ticket=t, typ='mail_antwort').exists())


class ImapUndWebhookTeilenDieZuordnungTests(TestCase):
    """Gegenprobe: in `fetch_replies.verarbeite_mail` die Ticketsuche wieder über `alle_organisationen` -> rot."""

    def test_fetch_replies_ruft_die_gemeinsame_verarbeitung(self):
        from email.message import EmailMessage
        from unittest import mock

        from core.management.commands.fetch_replies import Command
        t, _a = _auftrag_einfach()
        m = EmailMessage()
        m['Subject'] = f'Re: Wasserhahn (Ticket #{t.pk})'
        m['From'] = 'Hans <hans@example.ch>'
        m.set_content('Danke.')
        with organisation_kontext(t.organisation):
            with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten',
                            return_value='melder') as f:
                Command().verarbeite_mail(m.as_bytes())
        self.assertEqual(f.call_args.args[0].pk, t.organisation_id)
        self.assertEqual(f.call_args.args[3], 'Danke.')

    def test_fremde_nummer_findet_im_imap_weg_ebenfalls_nichts(self):
        from email.message import EmailMessage

        from core.management.commands.fetch_replies import Command
        from tickets.models import TicketNachricht
        a, b = MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
        m = EmailMessage()
        m['Subject'] = f'Re: (Ticket #{b.schaden.pk})'
        m['From'] = 'x@example.ch'
        m.set_content('Hallo.')
        with organisation_kontext(a.organisation):
            Command().verarbeite_mail(m.as_bytes())
        self.assertFalse(TicketNachricht.alle_organisationen.filter(typ='mail_antwort').exists())


class EinstellungenTests(TestCase):
    """Die Karte «Ihre Antwortadresse».

    Gegenprobe: in `_antwortadresse_karte` `request.organisation.pk` durch `Organisation.objects.first().pk` ersetzen
    -> `test_nur_die_eigene_adresse...` rot; `@rolle_erforderlich(*INHABER_ROLLEN)` durch `TEAM_ROLLEN` ersetzen
    -> `test_nur_der_inhaber...` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _client(self, f, rolle=None):
        from crm.models import Mitgliedschaft
        if rolle:
            Mitgliedschaft.alle_organisationen.filter(benutzer=f.benutzer).update(rolle=rolle)
        c = Client()
        c.force_login(f.benutzer)
        return c

    def test_nur_die_eigene_adresse_wird_gezeigt(self):
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            seite = self._client(self.a).get(reverse('postfach_liste')).content.decode()
        self.assertIn(_adresse(self.a.organisation), seite)
        self.assertNotIn(self.b.organisation.antwort_kennung, seite)
        self.assertIn('Adresse erneuern', seite)

    def test_status_nennt_eigenes_postfach_oder_plattform_oder_fehlenden_empfang(self):
        from core.models import Postfach
        url = reverse('postfach_liste')
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET):
            self.assertIn('Es gilt diese Adresse', self._client(self.a).get(url).content.decode())
            Postfach.alle_organisationen.create(
                organisation=self.a.organisation, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
                benutzer='eigen@muster.ch', server='imap.example.ch')
            seite = self._client(self.a).get(url).content.decode()
            self.assertIn('Es gilt Ihr eigenes Postfach: eigen@muster.ch', seite)
        with override_settings(BREVO_WEBHOOK_SECRET=None):
            self.assertIn('noch nicht eingerichtet', self._client(self.b).get(url).content.decode())

    def test_inhaber_erneuert_die_adresse_und_es_wird_protokolliert(self):
        from core.models import AktivitaetsLog
        alt = self.a.organisation.antwort_kennung
        r = self._client(self.a).post(reverse('antwortadresse_erneuern'))
        self.assertEqual(r.status_code, 302)
        self.a.organisation.refresh_from_db()
        self.b.organisation.refresh_from_db()
        self.assertNotEqual(self.a.organisation.antwort_kennung, alt)
        self.assertEqual(self.a.organisation.antwort_kennung_alt, alt)
        self.assertIsNotNone(self.a.organisation.antwort_kennung_alt_bis)
        self.assertNotEqual(self.b.organisation.antwort_kennung_alt, alt)
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(
            aktion='Antwortadresse erneuert', organisation=self.a.organisation).exists())

    def test_nur_der_inhaber_darf_erneuern_und_nur_per_post(self):
        from crm.models import Mitgliedschaft
        alt = self.a.organisation.antwort_kennung
        c = self._client(self.a, rolle=Mitgliedschaft.ROLLE_VERWALTER)
        self.assertEqual(c.post(reverse('antwortadresse_erneuern')).status_code, 403)
        self.assertNotIn('Adresse erneuern', c.get(reverse('postfach_liste')).content.decode())
        c = self._client(self.a, rolle=Mitgliedschaft.ROLLE_INHABER)
        self.assertEqual(c.get(reverse('antwortadresse_erneuern')).status_code, 405)
        self.a.organisation.refresh_from_db()
        self.assertEqual(self.a.organisation.antwort_kennung, alt)

    def test_lesezugriff_sieht_die_adresse(self):
        from crm.models import Mitgliedschaft
        c = self._client(self.a, rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        seite = c.get(reverse('postfach_liste')).content.decode()
        self.assertIn(_adresse(self.a.organisation), seite)
        self.assertNotIn('Adresse erneuern', seite)

    def test_adresse_in_der_seite_hat_keine_unerlaubten_zeichen(self):
        self.assertRegex(self.a.organisation.antwort_kennung, re.compile(r'^[a-z0-9-]+$'))
