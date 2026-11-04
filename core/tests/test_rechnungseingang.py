"""Eingehende Rechnungen über die zweite Plattformadresse `<kennung>-rechnungen@<ANTWORT_DOMAIN>` (4.11.2026).

Der Brevo-Webhook ordnet die Mail über die EMPFÄNGERADRESSE einer Verwaltung zu, lädt die Anhänge (hier:
`anhang_laden` ersetzt, es gibt kein Netz im Test) und legt sie über den gemeinsamen Beleg-Import als
Kreditorenrechnung an. Dazu: `reply_to` bei unlesbarem Postfach und die Oberfläche «E-Mail-Eingang».

Jede Klasse nennt ihre GEGENPROBE im Docstring (Code temporär ändern -> der Test wird rot).
"""
import io
import json
from unittest import mock

from cryptography.fernet import Fernet
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture
from .test_ticket_workflow import MAIL

DOMAIN = 'immoswiss.app'
SECRET = 'geheim'
ANHANG = 'core.services.rechnungseingang.anhang_laden'
PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 64


def _pdf():
    from reportlab.pdfgen import canvas
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer)
    c.drawString(72, 800, 'Muster Sanitaer AG')
    c.drawString(72, 780, 'Rechnung Nr. 2026-042 vom 15.03.2026')
    c.drawString(72, 760, 'Total CHF 350.00')
    c.drawString(72, 740, 'IBAN CH93 0076 2011 6238 5295 7')
    c.save()
    return puffer.getvalue()


def _rechnungs(org):
    return f'{org.antwort_kennung}-rechnungen@{DOMAIN}'


def _anhang(token='t1', name='rechnung.pdf', typ='application/pdf', groesse=50000, cid=None):
    return {'Name': name, 'ContentType': typ, 'ContentLength': groesse, 'ContentID': cid, 'DownloadToken': token}


def _mail(an, anhaenge=None, mid='<m1@x>', betreff='Rechnung 2026-042', von='hans@sanitaer-muster.ch', spam=None,
          empfaenger=None):
    item = {'From': {'Name': 'Hans', 'Address': von}, 'To': [{'Address': a} for a in (empfaenger or [an])],
            'Subject': betreff, 'RawTextBody': 'Anbei die Rechnung.', 'MessageId': mid,
            'Attachments': anhaenge if anhaenge is not None else [_anhang()]}
    if spam is not None:
        item['Spam'] = {'Score': spam}
    return {'items': [item]}


def _senden(nutzlast, api_key='bk', secret=SECRET):
    with override_settings(BREVO_WEBHOOK_SECRET=secret, BREVO_API_KEY=api_key, GROQ_API_KEY=None):
        return Client(raise_request_exception=False).post(
            reverse('brevo_inbound_webhook'), json.dumps(nutzlast), content_type='application/json',
            HTTP_X_WEBHOOK_SECRET=secret)


def _rechnungen(f):
    from finance.models import KreditorenRechnung
    with organisation_kontext(f.organisation):
        # Das Fixture bringt eigene Rechnungen mit; per Mail entstandene tragen die Herkunft «Per E-Mail von».
        return list(KreditorenRechnung.objects.filter(fehlermeldung__startswith='Per E-Mail von'))


def _logbuch(f, aktion):
    from core.models import AktivitaetsLog
    return AktivitaetsLog.alle_organisationen.filter(organisation=f.organisation, aktion=aktion)


class AdressenTests(TestCase):
    """Gegenprobe: in `zuordnung_zu_adresse` den Zweig `endswith(RECHNUNGS_ZUSATZ)` entfernen -> `..._ordnet_rechnungen_zu`
    rot; `_organisation_zu_kennung` ohne `alte_kennung_gilt` -> `..._30_tage_auch_fuer_rechnungen` rot; in `neue_kennung`
    die Zeile `if zufall == ...: continue` entfernen und den Zufall auf 'rechnungen' zwingen -> `..._nie_der_zusatz` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_adresse_und_zuordnung_ordnet_rechnungen_zu(self):
        from core.services import antwort_eingang as ae
        org = self.a.organisation
        self.assertEqual(ae.rechnungs_adresse(org), f'{org.antwort_kennung}-rechnungen@{DOMAIN}')
        self.assertEqual(ae.zuordnung_zu_adresse(ae.rechnungs_adresse(org)), (org, 'rechnungen'))
        self.assertEqual(ae.zuordnung_zu_adresse(ae.antwort_adresse(org)), (org, 'antworten'))
        self.assertEqual(ae.zuordnung_zu_adresse(ae.rechnungs_adresse(self.b.organisation))[0].pk, self.b.organisation.pk)

    def test_die_antwortzuordnung_nimmt_keine_rechnungsadresse(self):
        from core.services import antwort_eingang as ae
        self.assertIsNone(ae.organisation_zu_adresse(ae.rechnungs_adresse(self.a.organisation)))

    def test_unbekannte_kennung_oder_zusatz_allein_ergibt_nichts(self):
        from core.services import antwort_eingang as ae
        self.assertIsNone(ae.zuordnung_zu_adresse(f'unbekannt-abcdefghjk-rechnungen@{DOMAIN}'))
        self.assertIsNone(ae.zuordnung_zu_adresse(f'-rechnungen@{DOMAIN}'))
        self.assertIsNone(ae.zuordnung_zu_adresse(f'{self.a.organisation.antwort_kennung}-rechnung@{DOMAIN}'))
        self.assertIsNone(ae.zuordnung_zu_adresse(f'{self.a.organisation.antwort_kennung}-rechnungen@example.ch'))

    def test_erneuern_aendert_beide_adressen_und_alte_gilt_30_tage_auch_fuer_rechnungen(self):
        from datetime import timedelta
        from core.services import antwort_eingang as ae
        org = self.a.organisation
        alt = ae.rechnungs_adresse(org)
        jetzt = timezone.now()
        ae.kennung_erneuern(org, jetzt=jetzt)
        neu = ae.rechnungs_adresse(org)
        self.assertNotEqual(alt, neu)
        self.assertEqual(ae.zuordnung_zu_adresse(alt, jetzt=jetzt + timedelta(days=29)), (org, 'rechnungen'))
        self.assertIsNone(ae.zuordnung_zu_adresse(alt, jetzt=jetzt + timedelta(days=30, minutes=1)))
        self.assertEqual(ae.zuordnung_zu_adresse(neu, jetzt=jetzt + timedelta(days=90)), (org, 'rechnungen'))

    def test_eine_kennung_endet_nie_auf_den_zusatz(self):
        from core.services import antwort_eingang as ae
        folge = iter(list('rechnungen') + list('abcdefghjk'))
        # Der Zufall liefert zuerst genau «rechnungen» (Zeichen für Zeichen), dann etwas anderes.
        with mock.patch.object(ae.secrets, 'choice', side_effect=lambda _z: next(folge)):
            kennung = ae.neue_kennung('Muster')
        self.assertEqual(kennung, 'muster-abcdefghjk')


@MAIL
class WebhookRechnungTests(TestCase):
    """Gegenprobe: in `_eine_mail` die Verzweigung `if zweck == ae.ZWECK_RECHNUNGEN` entfernen -> alle Tests hier rot;
    in `rechnungsmail_verarbeiten` den Aufruf von `anhang_importieren` entfernen -> `..._landet_bei_der_richtigen_...`
    rot; in `auswahl_anhaenge` je eine Prüfung (Typ / Grösse / Logo / Anzahl) streichen -> der zugehörige Test rot;
    `magic_passt` auf `True` setzen -> `..._magic_bytes` rot; die Spam-Prüfung entfernen -> `..._spam` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_pdf_anhang_landet_bei_der_richtigen_verwaltung_mit_herkunft(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(self.a.organisation)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok, 1 invoice(s)')
        laden.assert_called_once_with('t1')
        a, b = _rechnungen(self.a), _rechnungen(self.b)
        self.assertEqual(len(a), 1)
        self.assertEqual(b, [], 'Die Rechnung darf nicht bei der anderen Verwaltung landen.')
        k = a[0]
        self.assertEqual(k.status, 'neu')
        self.assertEqual(str(k.betrag), '350.00')
        self.assertIn('Per E-Mail von hans@sanitaer-muster.ch', k.fehlermeldung)
        self.assertIn('Rechnung 2026-042', k.fehlermeldung)
        self.assertIn(f'eingegangen {timezone.localdate():%d.%m.%Y}', k.fehlermeldung)
        self.assertTrue(_logbuch(self.a, 'Rechnung per E-Mail eingegangen').exists())
        self.assertFalse(_logbuch(self.b, 'Rechnung per E-Mail eingegangen').exists())

    def test_die_andere_verwaltung_bekommt_ihre_eigene(self):
        with mock.patch(ANHANG, return_value=_pdf()):
            _senden(_mail(_rechnungs(self.b.organisation)))
        self.assertEqual((len(_rechnungen(self.a)), len(_rechnungen(self.b))), (0, 1))

    def test_fremde_oder_unbekannte_kennung_legt_nichts_an_und_laedt_nichts(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(f'xxxxxx-abcdefghjk-rechnungen@{DOMAIN}'))
            r2 = _senden(_mail(f'{self.a.organisation.antwort_kennung}-rechnungen@example.ch', mid='<m2>'))
        self.assertEqual((r.status_code, r.json()['status']), (200, 'ignored'))
        self.assertEqual(r2.status_code, 200)
        laden.assert_not_called()
        self.assertEqual((_rechnungen(self.a), _rechnungen(self.b)), ([], []))

    def test_mail_an_beide_adressen_der_verwaltung_ist_mehrdeutig_und_wird_verworfen(self):
        org = self.a.organisation
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(org), empfaenger=[_rechnungs(org), f'{org.antwort_kennung}@{DOMAIN}']))
        self.assertEqual(r.json()['status'], 'ignored')
        laden.assert_not_called()

    def test_falscher_typ_zu_gross_und_signaturlogos_werden_uebergangen(self):
        anhaenge = [
            _anhang('t_html', 'seite.html', 'text/html'),
            _anhang('t_gross', 'gross.pdf', groesse=15 * 1024 * 1024 + 1),
            _anhang('t_logo', 'logo.png', 'image/png', groesse=4000),
            _anhang('t_cid', 'image001', 'image/png', groesse=90000, cid='cid:image001'),
            _anhang('t_exe', 'virus.exe', 'application/x-msdownload'),
        ]
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(self.a.organisation), anhaenge))
        self.assertEqual(r.json()['status'], 'no attachment')
        laden.assert_not_called()
        self.assertEqual(_rechnungen(self.a), [])
        self.assertTrue(_logbuch(self.a, 'Rechnungsmail ohne Anhang abgerufen').exists())

    def test_ein_foto_mit_dateiendung_und_normaler_groesse_zaehlt(self):
        with mock.patch(ANHANG, return_value=PNG) as laden, \
                mock.patch('core.services.belegimport.beleg_importieren') as imp:
            imp.return_value = (mock.Mock(lieferant='x', betrag=0, id=1), {'methode': 'x'})
            _senden(_mail(_rechnungs(self.a.organisation), [_anhang('t_png', 'quittung.PNG', 'image/png', 90000)]))
        laden.assert_called_once_with('t_png')
        imp.assert_called_once()

    def test_octet_stream_zaehlt_nur_mit_passender_endung(self):
        anhaenge = [_anhang('t_a', 'rechnung.pdf', 'application/octet-stream'),
                    _anhang('t_b', 'rechnung', 'application/octet-stream')]
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            _senden(_mail(_rechnungs(self.a.organisation), anhaenge))
        laden.assert_called_once_with('t_a')

    def test_magic_bytes_muessen_zum_typ_passen(self):
        """Der Absender behauptet PDF, geliefert wird ein Programm."""
        with mock.patch(ANHANG, return_value=b'MZ\x90\x00 kein pdf'):
            r = _senden(_mail(_rechnungs(self.a.organisation)))
        self.assertEqual(_rechnungen(self.a), [])
        self.assertEqual(r.status_code, 200)
        eintrag = _logbuch(self.a, 'Rechnungsmail ohne Anhang abgerufen').get()
        self.assertIn('passt nicht zum Typ', eintrag.details)

    def test_hoechstens_zehn_anhaenge_je_mail(self):
        anhaenge = [_anhang(f't{i}', f'r{i}.pdf') for i in range(12)]
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(self.a.organisation), anhaenge))
        self.assertEqual(laden.call_count, 10)
        self.assertEqual(r.json()['status'], 'ok, 10 invoice(s)')

    def test_ohne_api_schluessel_kein_absturz_und_die_mail_steht_im_logbuch(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(self.a.organisation)), api_key=None)
        self.assertEqual((r.status_code, r.json()['status']), (200, 'attachments not loaded'))
        laden.assert_not_called()
        self.assertEqual(_rechnungen(self.a), [])
        eintrag = _logbuch(self.a, 'Rechnungsmail ohne Anhang abgerufen').get()
        self.assertIn('Brevo-API-Schlüssel fehlt', eintrag.details)
        self.assertIn('hans@sanitaer-muster.ch', eintrag.objekt)
        self.assertIn('Rechnung 2026-042', eintrag.objekt)
        self.assertFalse(_logbuch(self.b, 'Rechnungsmail ohne Anhang abgerufen').exists())

    def test_dieselbe_message_id_wird_nur_einmal_verarbeitet(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r1 = _senden(_mail(_rechnungs(self.a.organisation)))
            r2 = _senden(_mail(_rechnungs(self.a.organisation)))
        self.assertEqual(r1.json()['status'], 'ok, 1 invoice(s)')
        self.assertEqual(r2.json()['status'], 'duplicate')
        self.assertEqual(laden.call_count, 1)
        self.assertEqual(len(_rechnungen(self.a)), 1)

    def test_spam_wird_nicht_verarbeitet_normale_mail_schon(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(_rechnungs(self.a.organisation), spam=9.5))
            self.assertEqual(r.json()['status'], 'spam')
            laden.assert_not_called()
            r = _senden(_mail(_rechnungs(self.a.organisation), mid='<m2>', spam=1.2))
        self.assertEqual(r.json()['status'], 'ok, 1 invoice(s)')
        self.assertEqual(len(_rechnungen(self.a)), 1)

    def test_voruebergehender_ladefehler_gibt_500_und_nichts_bleibt_haengen(self):
        """Brevo wiederholt; die Wiederholung findet keine halbe Verarbeitung vor."""
        from core.services.rechnungseingang import AnhangFehler
        from tickets.models import EingegangeneMail
        anhaenge = [_anhang('t1'), _anhang('t2', 'zwei.pdf')]
        with mock.patch(ANHANG, side_effect=[_pdf(), AnhangFehler('Brevo antwortet mit 503', dauerhaft=False)]):
            r = _senden(_mail(_rechnungs(self.a.organisation), anhaenge))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(_rechnungen(self.a), [])
        self.assertFalse(EingegangeneMail.alle_organisationen.filter(organisation=self.a.organisation).exists())
        with mock.patch(ANHANG, return_value=_pdf()):
            r = _senden(_mail(_rechnungs(self.a.organisation), anhaenge))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(_rechnungen(self.a)), 2)

    def test_dauerhafter_ladefehler_ist_200_und_steht_im_logbuch(self):
        from core.services.rechnungseingang import AnhangFehler
        with mock.patch(ANHANG, side_effect=AnhangFehler('Brevo antwortet mit 404', dauerhaft=True)):
            r = _senden(_mail(_rechnungs(self.a.organisation)))
        self.assertEqual(r.status_code, 200)
        self.assertIn('404', _logbuch(self.a, 'Rechnungsmail ohne Anhang abgerufen').get().details)

    def test_ohne_secret_403_und_nichts_wird_geladen(self):
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            with override_settings(BREVO_WEBHOOK_SECRET=SECRET, BREVO_API_KEY='bk'):
                r = Client().post(reverse('brevo_inbound_webhook'),
                                  json.dumps(_mail(_rechnungs(self.a.organisation))), content_type='application/json')
        self.assertEqual(r.status_code, 403)
        laden.assert_not_called()

    def test_antwort_an_die_antwortadresse_bleibt_unberuehrt(self):
        """Eine Mail mit Anhang an die ANTWORTadresse wird weiterhin nur als Antwort behandelt."""
        with mock.patch(ANHANG, return_value=_pdf()) as laden:
            r = _senden(_mail(f'{self.a.organisation.antwort_kennung}@{DOMAIN}'))
        laden.assert_not_called()
        self.assertEqual(_rechnungen(self.a), [])
        self.assertEqual(r.status_code, 200)


class AnhangLadenTests(TestCase):
    """Gegenprobe: in `anhang_laden` `allow_redirects=False` auf True stellen -> `..._umleitung_...` rot; die Host-Prüfung
    entfernen -> `..._umleitung_ins_ausland` rot; die Grössenprüfung beim Lesen entfernen -> `..._ueberlanger_...` rot."""

    def _antwort(self, status=200, inhalt=b'%PDF-x', ort=None, stuecke=None):
        r = mock.Mock()
        r.status_code = status
        r.headers = {'Location': ort} if ort else {}
        r.iter_content.return_value = iter(stuecke if stuecke is not None else [inhalt])
        return r

    @override_settings(BREVO_API_KEY='bk')
    def test_laedt_von_brevo_mit_schluessel_und_zeitlimit(self):
        from core.services import rechnungseingang as re_
        with mock.patch.object(re_.requests, 'get', return_value=self._antwort()) as get:
            self.assertEqual(re_.anhang_laden('tok/en'), b'%PDF-x')
        url = get.call_args.args[0]
        self.assertTrue(url.startswith('https://api.brevo.com/v3/inbound/attachments/'))
        self.assertIn('tok%2Fen', url)
        self.assertEqual(get.call_args.kwargs['headers']['api-key'], 'bk')
        self.assertIsNotNone(get.call_args.kwargs['timeout'])
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)

    @override_settings(BREVO_API_KEY='bk')
    def test_umleitung_ins_ausland_wird_nicht_verfolgt(self):
        from core.services import rechnungseingang as re_
        with mock.patch.object(re_.requests, 'get',
                               return_value=self._antwort(302, ort='https://evil.example/x')) as get:
            with self.assertRaises(re_.AnhangFehler) as ctx:
                re_.anhang_laden('t')
        self.assertEqual(get.call_count, 1, 'Das Ziel ausserhalb von api.brevo.com darf nicht abgerufen werden.')
        self.assertTrue(ctx.exception.dauerhaft)

    @override_settings(BREVO_API_KEY='bk')
    def test_umleitung_innerhalb_von_brevo_wird_verfolgt_http_nicht(self):
        from core.services import rechnungseingang as re_
        with mock.patch.object(re_.requests, 'get', side_effect=[
                self._antwort(302, ort='/v3/inbound/anders'), self._antwort()]) as get:
            self.assertEqual(re_.anhang_laden('t'), b'%PDF-x')
        self.assertEqual(get.call_args.args[0], 'https://api.brevo.com/v3/inbound/anders')
        with mock.patch.object(re_.requests, 'get', return_value=self._antwort(302, ort='http://api.brevo.com/x')):
            with self.assertRaises(re_.AnhangFehler):
                re_.anhang_laden('t')

    @override_settings(BREVO_API_KEY='bk')
    def test_ueberlanger_inhalt_wird_abgebrochen(self):
        from core.services import rechnungseingang as re_
        gross = [b'x' * (1024 * 1024)] * 16
        with mock.patch.object(re_.requests, 'get', return_value=self._antwort(stuecke=gross)):
            with self.assertRaises(re_.AnhangFehler) as ctx:
                re_.anhang_laden('t')
        self.assertTrue(ctx.exception.dauerhaft)

    @override_settings(BREVO_API_KEY='bk')
    def test_statuscodes_voruebergehend_oder_dauerhaft(self):
        from core.services import rechnungseingang as re_
        for status, dauerhaft in ((404, True), (401, True), (500, False), (429, False)):
            with mock.patch.object(re_.requests, 'get', return_value=self._antwort(status)):
                with self.assertRaises(re_.AnhangFehler) as ctx:
                    re_.anhang_laden('t')
            self.assertEqual(ctx.exception.dauerhaft, dauerhaft, status)
        with mock.patch.object(re_.requests, 'get', side_effect=re_.requests.Timeout('zu langsam')):
            with self.assertRaises(re_.AnhangFehler) as ctx:
                re_.anhang_laden('t')
        self.assertFalse(ctx.exception.dauerhaft)

    @override_settings(BREVO_API_KEY=None)
    def test_ohne_schluessel_wird_gar_nicht_erst_angefragt(self):
        from core.services import rechnungseingang as re_
        with mock.patch.object(re_.requests, 'get') as get:
            with self.assertRaises(re_.AnhangFehler):
                re_.anhang_laden('t')
        get.assert_not_called()


@MAIL
class ReplyToUnlesbaresPostfachTests(TestCase):
    """Gegenprobe: in `tickets.workflow.reply_to` `and pf.zugang_lesbar` entfernen -> `..._unlesbar_...` rot;
    in `Postfach.zugang_lesbar` immer `True` liefern -> dasselbe."""

    def _postfach(self, org, schluessel):
        from core.models import Postfach
        with override_settings(IMAP_SCHLUESSEL=schluessel):
            pf = Postfach(organisation=org, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
                          benutzer='eigen@muster.ch', server='imap.example.ch')
            pf.passwort = 'geheim'
            pf.save()
        return pf

    def test_postfach_mit_unlesbaren_zugangsdaten_gilt_nicht_dann_springt_die_plattformadresse_ein(self):
        from tickets.workflow import reply_to
        from .test_direktkanal import _auftrag_einfach
        t, _a = _auftrag_einfach()
        org = t.organisation
        alt, neu = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with organisation_kontext(org):
            pf = self._postfach(org, alt)
            with override_settings(BREVO_WEBHOOK_SECRET=SECRET, IMAP_SCHLUESSEL=alt):
                self.assertTrue(pf.zugang_lesbar)
                self.assertEqual(reply_to(t), 'eigen@muster.ch')
            with override_settings(BREVO_WEBHOOK_SECRET=SECRET, IMAP_SCHLUESSEL=neu):
                self.assertFalse(pf.zugang_lesbar)
                self.assertEqual(reply_to(t), f'{org.antwort_kennung}@{DOMAIN}')
            with override_settings(BREVO_WEBHOOK_SECRET=SECRET, IMAP_SCHLUESSEL=''):
                self.assertEqual(reply_to(t), f'{org.antwort_kennung}@{DOMAIN}')
            with override_settings(BREVO_WEBHOOK_SECRET=None, IMAP_SCHLUESSEL=neu):
                self.assertIsNone(reply_to(t), 'Ohne Empfang auf dem Server bleibt es beim bisherigen Verhalten.')


class EinstellungenRechnungTests(TestCase):
    """Gegenprobe: in `_adresskarten` die Rechnungsadresse durch die einer anderen Verwaltung ersetzen
    -> `..._nur_die_eigenen_adressen` rot; in `kennung_erneuern` nichts ändern, aber in der View nur
    `antwort_adresse` zeigen -> `..._erneuern_...` rot; `_letzter_eingang` ohne `zweck`-Filter -> `..._letzter_eingang` rot."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _client(self, f):
        c = Client()
        c.force_login(f.benutzer)
        return c

    def test_beide_karten_zeigen_nur_die_eigenen_adressen(self):
        a, b = self.a.organisation, self.b.organisation
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET, BREVO_API_KEY='bk'):
            seite = self._client(self.a).get(reverse('postfach_liste')).content.decode()
        self.assertIn(f'{a.antwort_kennung}@{DOMAIN}', seite)
        self.assertIn(f'{a.antwort_kennung}-rechnungen@{DOMAIN}', seite)
        self.assertNotIn(b.antwort_kennung, seite)
        self.assertIn('Empfang eingerichtet. Rechnungen an diese Adresse landen in den Kreditoren.', seite)
        for text in ('Gmail', 'Outlook / Microsoft 365', 'Hoststar / Webmail', 'Erweitert: eigenes Postfach'):
            self.assertIn(text, seite)

    def test_status_ohne_secret_und_ohne_api_schluessel(self):
        url = reverse('postfach_liste')
        with override_settings(BREVO_WEBHOOK_SECRET=None, BREVO_API_KEY=None):
            seite = self._client(self.a).get(url).content.decode()
        self.assertIn('Rechnungen an diese Adresse kommen noch nicht an', seite)
        with override_settings(BREVO_WEBHOOK_SECRET=SECRET, BREVO_API_KEY=None):
            seite = self._client(self.a).get(url).content.decode()
        self.assertIn('Anhänge lassen sich auf dem Server noch nicht laden', seite)

    def test_letzter_eingang_je_verwaltung_und_zweck(self):
        from tickets.models import EingegangeneMail
        with organisation_kontext(self.a.organisation):
            EingegangeneMail.objects.create(message_id='r1', zweck='rechnungen')
        with organisation_kontext(self.b.organisation):
            EingegangeneMail.objects.create(message_id='r2', zweck='rechnungen')
            EingegangeneMail.objects.create(message_id='r3', zweck='antworten')
        a = self._client(self.a).get(reverse('postfach_liste')).content.decode()
        teil_rechnung = a[a.index('id="rechnungsadresse"'):]
        teil_antwort = a[a.index('id="antwortadresse"'):a.index('id="rechnungsadresse"')]
        self.assertIn('Letzter Eingang:', teil_rechnung)
        self.assertIn('Noch nichts eingegangen.', teil_antwort, 'Die Rechnungsmail zählt nicht als Antwort.')
        b = self._client(self.b).get(reverse('postfach_liste')).content.decode()
        self.assertNotIn('Noch nichts eingegangen.', b)

    def test_erneuern_erneuert_beide_adressen(self):
        alt = self.a.organisation.antwort_kennung
        r = self._client(self.a).post(reverse('antwortadresse_erneuern'))
        self.assertEqual(r.status_code, 302)
        self.a.organisation.refresh_from_db()
        neu = self.a.organisation.antwort_kennung
        self.assertNotEqual(alt, neu)
        seite = self._client(self.a).get(reverse('postfach_liste')).content.decode()
        self.assertIn(f'{neu}-rechnungen@{DOMAIN}', seite)
        self.assertNotIn(f'{alt}-rechnungen@{DOMAIN}', seite)

    def test_unlesbares_postfach_zeigt_hinweis_neu_eingeben_und_loeschen(self):
        from core.models import Postfach
        alt, neu = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(IMAP_SCHLUESSEL=alt):
            # Das Fixture legt das Rechnungs-Postfach schon an (ohne Passwort).
            pf = Postfach.alle_organisationen.get(organisation=self.a.organisation, zweck=Postfach.ZWECK_RECHNUNGEN)
            pf.passwort = 'geheim'
            pf.save()
        with override_settings(IMAP_SCHLUESSEL=neu):
            seite = self._client(self.a).get(reverse('postfach_liste')).content.decode()
            self.assertIn('Die Zugangsdaten lassen sich nicht lesen.', seite)
            self.assertIn('Neu eingeben', seite)
            self.assertIn('/neu/postfaecher/rechnungen/loeschen/', seite)
            self.assertNotIn('geheim', seite)
            # Speichern ohne neues Passwort darf den unlesbaren Zustand nicht als «unverändert» durchwinken.
            r = self._client(self.a).post(reverse('postfach_form', args=['rechnungen']), {
                'verfahren': 'passwort', 'benutzer': 'r@muster.ch', 'server': 'imap.example.ch', 'port': '993',
                'ordner': 'INBOX', 'aktiv': 'an'})
            self.assertEqual(r.status_code, 200)
            r = self._client(self.a).post(reverse('postfach_form', args=['rechnungen']), {
                'verfahren': 'passwort', 'benutzer': 'r@muster.ch', 'server': 'imap.example.ch', 'port': '993',
                'ordner': 'INBOX', 'aktiv': 'an', 'passwort': 'neu-geheim'})
            self.assertEqual(r.status_code, 302)
            pf = Postfach.alle_organisationen.get(pk=pf.pk)
            self.assertTrue(pf.zugang_lesbar)
            self.assertEqual(pf.passwort, 'neu-geheim')

    def test_die_antwortkarte_nennt_ein_unlesbares_postfach_nicht_als_gueltig(self):
        from core.models import Postfach
        alt, neu = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(IMAP_SCHLUESSEL=alt):
            pf = Postfach(organisation=self.b.organisation, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
                          benutzer='eigen@muster.ch', server='imap.example.ch')
            pf.passwort = 'x'
            pf.save()
        with override_settings(IMAP_SCHLUESSEL=neu, BREVO_WEBHOOK_SECRET=SECRET):
            seite = self._client(self.b).get(reverse('postfach_liste')).content.decode()
        self.assertNotIn('Es gilt Ihr eigenes Postfach', seite)
        self.assertIn('Empfang eingerichtet. Es gilt diese Adresse', seite)
        self.assertIn('Zugangsdaten lassen sich nicht lesen. Deshalb gilt diese Adresse', seite)
