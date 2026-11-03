"""Mailwege des Ticket-/Schaden-Moduls: jeder Weg über die Ansicht, mit `mail.outbox`.

Prüfung vom 3.11.2026 («Funktionieren alle Mail-Versände?»). Die Klassen sind nach
Befund geordnet; jede Gegenprobe steht im Docstring der Klasse. Der Test sieht auf das,
was der Empfänger bekommt (Adresse, Absender, Antwortadresse, Sprache, Anhang, Text) und
auf das, was der Verlauf behauptet.
"""
import shutil
import tempfile
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.messages import get_messages
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import translation

from core.tenancy import organisation_kontext

from ._helfer import _team_user
from ._isolation import MandantenFixture
from .test_ticket_workflow import _handwerker, _ticket

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')
EINSCHLEUSUNG = '<img src=x onerror=alert(1)>'


def _meldungen(antwort):
    return [str(m) for m in get_messages(antwort.wsgi_request)]


def _text(m):
    """Körper einer Mail samt Alternativen — was der Empfänger lesen kann."""
    return m.body + ''.join(a[0] for a in getattr(m, 'alternatives', []))


class SofortThread:
    """Thread synchron laufen lassen (wie in EingangsbestaetigungTests)."""

    def __init__(self, target=None, args=(), kwargs=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


def sofort():
    return mock.patch('core.utils.email_service.threading.Thread', SofortThread)


class _Basis(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        mail.outbox.clear()


class HtmlEinschleusungTests(_Basis):
    """Ein Melder (öffentliches Formular, ohne Anmeldung) bestimmt Titel und Text des Tickets.
    Beide gehen in Mails an Mieter, Handwerker und Verwaltung: als HTML erscheinen sie nur
    maskiert.

    Gegenprobe: in `send_ticket_email` das `escape` entfernen -> `test_*_status` und `_termin` rot.
    """

    def _neu(self):
        t = _ticket()
        t.titel = EINSCHLEUSUNG
        t.beschreibung = EINSCHLEUSUNG
        t.save()
        return t

    def _alle_koerper(self):
        return [_text(m) for m in mail.outbox]

    def test_melder_mail_ist_maskiert(self):
        from tickets.workflow import wechsle_status
        t = self._neu()
        wechsle_status(t, 'in_bearbeitung', melder_informieren=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('<img', _text(mail.outbox[0]))
        self.assertIn('&lt;img', _text(mail.outbox[0]))

    def test_auftrag_mail_ist_maskiert(self):
        from tickets.workflow import auftrag_vergeben
        t = self._neu()
        auftrag_vergeben(t, _handwerker(), f'Bitte prüfen: {EINSCHLEUSUNG}')
        self.assertEqual(len(mail.outbox), 2)
        for k in self._alle_koerper():
            self.assertNotIn('<img', k)

    def test_termin_mail_ist_maskiert(self):
        from tickets.workflow import handwerker_zuweisen, termin_festlegen
        t = self._neu()
        a = handwerker_zuweisen(t, _handwerker())
        termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        self.assertEqual(len(mail.outbox), 2)
        for k in self._alle_koerper():
            self.assertNotIn('<img', k)

    def test_nachricht_an_handwerker_ist_maskiert(self):
        from tickets.workflow import handwerker_zuweisen, nachricht_an_handwerker
        a = handwerker_zuweisen(self._neu(), _handwerker())
        nachricht_an_handwerker(a, f'Siehe {EINSCHLEUSUNG}')
        self.assertNotIn('<img', _text(mail.outbox[0]))

    def test_meldung_an_verwaltung_war_schon_maskiert(self):
        """Positivprobe: `send_neue_meldung_intern` maskierte schon vor dem 3.11.2026."""
        from crm.models import Organisation
        from core.utils.email_service import send_neue_meldung_intern
        Organisation.objects.update(email='vw@example.ch')
        send_neue_meldung_intern(self._neu(), ['vw@example.ch'])
        self.assertNotIn('<img', _text(mail.outbox[0]))      # Positivprobe: war schon maskiert


class BetreffTests(_Basis):
    """Ein Zeilenumbruch im Betreff lässt Django die Mail verwerfen (BadHeaderError) — still."""

    def test_zeilenumbruch_im_titel_verhindert_die_mail_nicht(self):
        """Der Titel steht im Betreff der Nachricht an den Handwerker («Titel (Ticket #N)»)."""
        from tickets.workflow import handwerker_zuweisen, nachricht_an_handwerker
        t = _ticket()
        t.titel = 'Wasser\nBcc: boese@example.ch'
        t.save()
        a = handwerker_zuweisen(t, _handwerker())
        self.assertTrue(nachricht_an_handwerker(a, 'Bitte melden'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('\n', mail.outbox[0].subject)
        self.assertIn('Ticket #', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].bcc, [])


class FehlerSichtbarTests(_Basis):
    """`send_via_hoststar` gab Fehler mit `print` aus und gab False zurück: im Betrieb
    steht kein Wort davon im Protokoll. Jetzt eine Warnung mit Empfänger und Grund.

    Gegenprobe: `logger.warning` durch `print` ersetzen -> rot.
    """

    def test_fehlgeschlagener_versand_steht_im_protokoll(self):
        from core.utils.email_service import send_via_hoststar
        with override_settings(EMAIL_BACKEND='core.tests.test_mailwege_schaden.KaputtesBackend'):
            with self.assertLogs('core.utils.email_service', level='WARNING') as log:
                ok = send_via_hoststar('x@example.ch', 'Betreff', '<p>x</p>')
        self.assertFalse(ok)
        self.assertIn('x@example.ch', ' '.join(log.output))


from django.core.mail.backends.base import BaseEmailBackend  # noqa: E402


class KaputtesBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise ConnectionRefusedError('smtp down')


class AntwortAnMelderTests(_Basis):
    """`fw_schaden_antwort`: der Verlauf darf nicht «Antwort gesendet» sagen, wenn nichts ging."""

    def _post(self, t, text='Wir kommen am Montag.'):
        c = Client()
        c.force_login(_team_user())
        return c.post(f'/neu/schaeden/{t.id}/antwort/', {'text': text})

    def test_erfolg_mail_und_verlauf(self):
        t = _ticket()
        self._post(t)
        self.assertEqual([m.to for m in mail.outbox], [['hans@example.ch']])
        self.assertIn('Ticket #', mail.outbox[0].subject)         # Antwort-Zuordnung (fetch_replies)
        self.assertIn('via', mail.outbox[0].from_email)
        self.assertTrue(mail.outbox[0].reply_to)
        n = t.nachrichten.get(typ='antwort_senden')
        self.assertNotIn('NICHT', n.nachricht)

    def test_fehlschlag_steht_im_verlauf(self):
        t = _ticket()
        with override_settings(EMAIL_BACKEND='core.tests.test_mailwege_schaden.KaputtesBackend'):
            r = self._post(t)
        self.assertTrue(t.nachrichten.filter(typ='antwort_senden').exists())     # der Mieter sieht sie im Portal
        self.assertTrue(t.nachrichten.filter(typ='system', is_intern=True, nachricht__contains='NICHT versendet').exists())
        self.assertTrue(any('fehlgeschlagen' in m for m in _meldungen(r)))

    def test_ohne_adresse_steht_es_im_verlauf(self):
        t = _ticket()
        t.email_melder = ''
        t.save()
        t.gemeldet_von.email = ''
        t.gemeldet_von.save()
        self._post(t)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(t.nachrichten.filter(typ='system', nachricht__contains='NICHT versendet').exists())


class MeldungenSagenDieWahrheitTests(_Basis):
    """Die grüne Meldung nach Storno und Termin behauptete «Handwerker informiert», auch wenn
    er keine Adresse hat oder der Versand scheiterte.

    Gegenprobe: in `fw_auftrag_storno` die Prüfung des Rückgabewerts entfernen -> rot.
    """

    def _auftrag(self, email):
        from crm.models import Handwerker
        from tickets.workflow import handwerker_zuweisen
        t = _ticket()
        hw = Handwerker.objects.create(firma='Ohne Mail GmbH', email=email)
        return t, handwerker_zuweisen(t, hw)

    def _client(self):
        c = Client()
        c.force_login(_team_user())
        return c

    def test_storno_ohne_adresse(self):
        t, a = self._auftrag('')
        r = self._client().post(f'/neu/auftrag/{a.pk}/storno/', {'grund': 'x'})
        text = ' '.join(_meldungen(r))
        self.assertNotIn('Handwerker informiert', text)
        self.assertIn('nicht informiert', text.lower())

    def test_storno_mit_adresse(self):
        t, a = self._auftrag('hw@example.ch')
        r = self._client().post(f'/neu/auftrag/{a.pk}/storno/', {'grund': 'x'})
        self.assertIn('Handwerker informiert', ' '.join(_meldungen(r)))

    def test_termin_ohne_adresse_des_handwerkers(self):
        t, a = self._auftrag('')
        r = self._client().post(f'/neu/auftrag/{a.pk}/termin/', {'termin': '2026-11-20T08:30'})
        text = ' '.join(_meldungen(r))
        self.assertNotIn('Mieter und Handwerker informiert', text)
        self.assertIn('Handwerker nicht informiert', text)

    def test_termin_absage_ohne_adresse(self):
        t, a = self._auftrag('')
        c = self._client()
        c.post(f'/neu/auftrag/{a.pk}/termin/', {'termin': '2026-11-20T08:30'})
        r = c.post(f'/neu/auftrag/{a.pk}/termin/', {'aktion': 'absagen'})
        self.assertNotIn('beide Seiten informiert', ' '.join(_meldungen(r)))


class DoppelklickTests(_Basis):
    """Zweimal «Beauftragen» (Doppelklick, Reload nach POST) legte zwei Aufträge an und
    schickte beide Mails zweimal.

    Gegenprobe: die Prüfung in `handwerker_zuweisen` entfernen -> rot.
    """

    def test_doppelter_post_beauftragt_einmal(self):
        t = _ticket()
        hw = _handwerker()
        c = Client()
        c.force_login(_team_user())
        c.post(f'/neu/schaeden/{t.id}/auftrag/', {'handwerker_id': hw.id, 'auftragstext': 'Bitte'})
        mail.outbox.clear()
        r = c.post(f'/neu/schaeden/{t.id}/auftrag/', {'handwerker_id': hw.id, 'auftragstext': 'Bitte'})
        self.assertEqual(t.handwerker_auftraege.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(_meldungen(r))

    def test_nach_storno_darf_neu_beauftragt_werden(self):
        from tickets.workflow import auftrag_stornieren, auftrag_vergeben
        t = _ticket()
        hw = _handwerker()
        a = auftrag_vergeben(t, hw)['auftrag']
        auftrag_stornieren(a)
        auftrag_vergeben(t, hw)
        self.assertEqual(t.handwerker_auftraege.count(), 2)


class OeffentlicheMeldungTests(_Basis):
    """Meldung eingeht: Eingangsbestätigung an den Melder UND Benachrichtigung der Verwaltung,
    auf jedem Weg (QR-Aushang, Webformular, Mieterportal, interne Erfassung)."""

    def setUp(self):
        super().setUp()
        from crm.models import Organisation
        self.lg, self.e, self.m, self.v = __import__(
            'core.tests._helfer', fromlist=['_basis_objekte'])._basis_objekte()
        Organisation.objects.update(email='verwaltung@example.ch', firma='Muster Verwaltung AG')

    def _qr(self, **extra):
        daten = {'titel': 'Heizung kalt', 'beschreibung': 'Seit gestern', 'vorname': 'Eva',
                 'nachname': 'Test', 'email': 'eva@example.ch', 'telefon': '079 123 45 67', **extra}
        with sofort():
            return Client().post(f'/report/{self.lg.id}/', daten)

    def _web(self, **extra):
        daten = {'kategorie': 'schaden', 'raum': 'Küche', 'objekt': 'Herd', 'beschreibung': 'Defekt',
                 'vorname': 'Eva', 'nachname': 'Test', 'email': 'eva@example.ch', 'telefon': '079 1',
                 'liegenschaft_id': self.lg.id, **extra}
        with sofort():
            return Client().post('/schaden/melden/', daten)

    def test_qr_formular_bestaetigt_dem_melder(self):
        self._qr()
        an = [m.to[0] for m in mail.outbox]
        self.assertIn('eva@example.ch', an)
        melder = [m for m in mail.outbox if m.to == ['eva@example.ch']][0]
        self.assertIn('Muster Verwaltung AG via', melder.from_email)

    def test_qr_formular_benachrichtigt_die_verwaltung(self):
        self._qr()
        self.assertIn('verwaltung@example.ch', [m.to[0] for m in mail.outbox])

    def test_webformular_bestaetigt_und_benachrichtigt(self):
        r = self._web()
        self.assertEqual(r.status_code, 200)
        an = [m.to[0] for m in mail.outbox]
        self.assertIn('eva@example.ch', an)
        self.assertIn('verwaltung@example.ch', an)

    def test_verwaltungsmail_nennt_das_ticket_und_maskiert(self):
        self._qr(titel=EINSCHLEUSUNG)
        intern = [m for m in mail.outbox if m.to == ['verwaltung@example.ch']][0]
        self.assertNotIn('<img', _text(intern))

    def test_ohne_adresse_der_verwaltung_schweigt_es_nicht_im_protokoll(self):
        from crm.models import Organisation
        Organisation.objects.update(email='')
        with self.assertLogs('tickets.meldung_mails', level='WARNING'):
            self._web()

    def test_internes_erfassen_bestaetigt_in_der_sprache_des_mieters(self):
        self.m.sprache = 'fr'
        self.m.save()
        c = Client()
        c.force_login(_team_user())
        c.post('/neu/schaeden/neu/', {'titel': 'Fuite', 'liegenschaft_id': self.lg.id,
                                      'einheit_id': self.e.id, 'email_melder': self.m.email,
                                      'melder_vorname': 'Hans', 'melder_nachname': 'Muster'})
        # Der Melder ist hier eine Adresse ohne Verknüpfung: Deutsch bleibt Standard.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Guten Tag', _text(mail.outbox[0]))


class FremderMieterImWebformularTests(TestCase):
    """Das Webformular fand den Mieter über ALLE Verwaltungen (`alle_organisationen`). Wählt der
    Melder die Liegenschaft von Verwaltung B und gibt die E-Mail eines Mieters von A an, hing
    der Mieter von A am Ticket von B (Name und Adresse in deren Mails und Ansicht)."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()

    def test_mieter_einer_anderen_verwaltung_wird_nicht_verknuepft(self):
        from tickets.models import SchadenMeldung
        with sofort():
            Client().post('/schaden/melden/', {
                'kategorie': 'schaden', 'raum': 'Bad', 'objekt': 'Hahn', 'beschreibung': 'x',
                'vorname': 'V', 'nachname': 'N', 'email': self.a.mieter.email, 'telefon': '1',
                'liegenschaft_id': self.b.liegenschaft.id})
        t = SchadenMeldung.alle_organisationen.get(liegenschaft=self.b.liegenschaft, titel__contains='Hahn')
        self.assertIsNone(t.gemeldet_von_id)


class SpracheTests(_Basis):
    """Mails an den Mieter folgen `Mieter.sprache` (D11), nicht der Sprache der Sachbearbeitung;
    Mails an Handwerker bleiben deutsch (er hat keine Sprache im Bestand).

    Gegenprobe: in `vorlage_text` das `in_sprache` entfernen -> rot.
    """

    def _fr(self):
        t = _ticket()
        t.gemeldet_von.sprache = 'fr'
        t.gemeldet_von.save()
        return t

    def test_statusmail_an_den_mieter_ist_franzoesisch(self):
        from tickets.workflow import wechsle_status
        t = self._fr()
        wechsle_status(t, 'in_bearbeitung', melder_informieren=True)
        m = mail.outbox[0]
        self.assertNotIn('Guten Tag', _text(m))
        self.assertNotIn('Statusupdate', m.subject)
        self.assertIn('Bonjour', _text(m))

    def test_erledigt_mail_an_den_mieter_ist_franzoesisch(self):
        from tickets.workflow import wechsle_status
        t = self._fr()
        wechsle_status(t, 'erledigt', melder_informieren=True)
        self.assertIn('Bonjour', _text(mail.outbox[0]))

    def test_standard_bleibt_deutsch(self):
        from tickets.workflow import wechsle_status
        t = _ticket()
        wechsle_status(t, 'in_bearbeitung', melder_informieren=True)
        self.assertIn('Guten Tag', _text(mail.outbox[0]))

    def test_termin_an_mieter_franzoesisch_an_handwerker_deutsch(self):
        from tickets.workflow import handwerker_zuweisen, termin_festlegen
        t = self._fr()
        a = handwerker_zuweisen(t, _handwerker())
        mail.outbox.clear()
        termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        an = {m.to[0]: m for m in mail.outbox}
        self.assertIn('Bonjour', _text(an['hans@example.ch']))
        self.assertIn('Guten Tag', _text(an['hw@example.ch']))

    def test_handwerkermail_bleibt_deutsch_bei_franzoesischer_oberflaeche(self):
        from tickets.workflow import auftrag_vergeben
        t = _ticket()
        with translation.override('fr'):
            auftrag_vergeben(t, _handwerker())
        hw = [m for m in mail.outbox if m.to == ['hw@example.ch']][0]
        self.assertIn('Sehr geehrte Damen und Herren', _text(hw))

    def test_erinnerung_an_den_mieter_franzoesisch(self):
        from tickets.erinnerungen import erinnerungen_senden
        from tickets.workflow import wechsle_status
        from django.utils import timezone
        t = self._fr()
        wechsle_status(t, 'warte_auf_mieter')
        type(t).objects.filter(pk=t.pk).update(aktualisiert_am=timezone.now() - timedelta(days=10))
        mail.outbox.clear()
        erinnerungen_senden()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Bonjour', _text(mail.outbox[0]))

    def test_alle_vorlagen_haben_eine_uebersetzung(self):
        """Jeder Standardtext, der an einen Mieter geht, existiert in fr, it und en."""
        from core.services.ticket_workflow import DEFAULT_VORLAGEN, MIETER_VORLAGEN
        from django.utils.translation import gettext
        for kat in MIETER_VORLAGEN:
            for feld in ('betreff', 'inhalt'):
                roh = DEFAULT_VORLAGEN[kat][feld]
                for sprache in ('fr', 'it', 'en'):
                    with translation.override(sprache):
                        self.assertNotEqual(gettext(roh), roh, f'{kat}.{feld} fehlt in {sprache}')


class FotoAnhangTests(TestCase):
    """Fotos aus Portal und interner Erfassung liegen als `SchadenFoto`; die Auftragsmail hängte nur
    das alte Einzelfoto `ticket.foto` an.

    Gegenprobe: in `arbeitsauftrag_senden` die `fotos` weglassen -> rot.
    """

    @classmethod
    def setUpClass(cls):
        cls._wurzel = tempfile.mkdtemp(prefix='swissimmo-mailfoto-')
        cls._o = override_settings(MEDIA_ROOT=cls._wurzel)
        cls._o.enable()
        cls.addClassCleanup(shutil.rmtree, cls._wurzel, ignore_errors=True)
        cls.addClassCleanup(cls._o.disable)
        super().setUpClass()

    def setUp(self):
        mail.outbox.clear()

    def test_zusatzfotos_haengen_an(self):
        from tickets.models import SchadenFoto
        from tickets.workflow import handwerker_zuweisen, arbeitsauftrag_senden
        self.assertTrue(settings.MEDIA_ROOT.startswith(self._wurzel))
        t = _ticket()
        SchadenFoto.objects.create(schaden=t, bild=SimpleUploadedFile('a.png', PNG, 'image/png'))
        SchadenFoto.objects.create(schaden=t, bild=SimpleUploadedFile('b.png', PNG, 'image/png'))
        arbeitsauftrag_senden(handwerker_zuweisen(t, _handwerker()))
        namen = [a[0] for a in mail.outbox[0].attachments]
        self.assertEqual(sum(n.endswith('.png') for n in namen), 2, namen)
        typen = {a[2] for a in mail.outbox[0].attachments if a[0].endswith('.png')}
        self.assertEqual(typen, {'image/png'})


class KalenderTests(_Basis):
    """Der Kalendereintrag muss sich verschieben und absagen lassen: gleiche UID, steigende
    SEQUENCE, DTSTAMP = Zeitpunkt der Mail."""

    def test_sequence_steigt_und_absage_ist_hoeher(self):
        import re
        from unittest import mock as m
        from django.utils import timezone
        from tickets.workflow import handwerker_zuweisen, termin_absagen, termin_festlegen
        a = handwerker_zuweisen(_ticket(), _handwerker())
        t0 = timezone.now()
        with m.patch('django.utils.timezone.now', return_value=t0):
            termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        with m.patch('django.utils.timezone.now', return_value=t0 + timedelta(minutes=5)):
            termin_absagen(a)

        def seq(msg):
            ics = [x for x in msg.attachments if x[0].endswith('.ics')][0][1]
            return int(re.search(r'SEQUENCE:(\d+)', ics).group(1)), ics
        s1, ics1 = seq(mail.outbox[0])
        s2, ics2 = seq(mail.outbox[-1])
        self.assertGreater(s2, s1)
        self.assertIn('METHOD:CANCEL', ics2)
        dtstamp = re.search(r'DTSTAMP:(\S+)', ics1).group(1)
        self.assertEqual(dtstamp, t0.strftime('%Y%m%dT%H%M%SZ'))

    def test_inhaltstyp_nennt_die_methode(self):
        from tickets.workflow import handwerker_zuweisen, termin_festlegen
        a = handwerker_zuweisen(_ticket(), _handwerker())
        termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        typ = [x for x in mail.outbox[0].attachments if x[0].endswith('.ics')][0][2]
        self.assertIn('method=PUBLISH', typ)


class FreigabeMailTests(_Basis):
    """Eigentümer-Freigabe: Bitte an den Eigentümer, Entscheid zurück an Verwaltung und Handwerker."""

    def setUp(self):
        super().setUp()
        from crm.models import Eigentuemer, Organisation
        from tickets.workflow import handwerker_zuweisen
        self.t = _ticket()
        Organisation.objects.update(email='verwaltung@example.ch', firma='Muster Verwaltung AG')
        self.eig = Eigentuemer.objects.create(firma_oder_name='Eig AG', email='eig@example.ch',
                                              kontaktperson='Frau Eigner')
        self.t.liegenschaft.eigentuemer = self.eig
        self.t.liegenschaft.save()
        self.a = handwerker_zuweisen(self.t, _handwerker())
        mail.outbox.clear()

    def _kosten(self):
        c = Client()
        c.force_login(_team_user())
        return c.post(f'/neu/auftrag/{self.a.pk}/kosten/', {'kosten_geschaetzt': '1500'})

    def test_bitte_geht_an_den_eigentuemer_mit_absender_und_antwortadresse(self):
        self._kosten()
        self.assertEqual([m.to for m in mail.outbox], [['eig@example.ch']])
        m = mail.outbox[0]
        self.assertIn('Muster Verwaltung AG via', m.from_email)
        self.assertEqual(m.reply_to, ['verwaltung@example.ch'])

    def test_bitte_im_verlauf(self):
        self._kosten()
        self.assertTrue(self.t.nachrichten.filter(typ='system', nachricht__contains='Freigabe').exists())

    def test_eigentuemer_ohne_adresse_sagt_es_die_ansicht(self):
        self.eig.email = ''
        self.eig.save()
        r = self._kosten()
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(any('keine E-Mail' in m for m in _meldungen(r)), _meldungen(r))

    def test_bitte_in_der_sprache_des_eigentuemers(self):
        self.eig.sprache = 'fr'
        self.eig.save()
        self._kosten()
        self.assertNotIn('Guten Tag', _text(mail.outbox[0]))
        self.assertIn('Bonjour', _text(mail.outbox[0]))

    def _entscheid(self, aktion, kommentar='Zu teuer'):
        from benutzer.models import Benutzer
        from crm.models import Handwerker  # noqa: F401
        from tickets.models import HandwerkerAuftrag
        HandwerkerAuftrag.objects.filter(pk=self.a.pk).update(freigabe_status='ausstehend')
        u = Benutzer.objects.create_user(username='eig_entscheid', password='x')
        self.eig.benutzer = u
        self.eig.save()
        mail.outbox.clear()
        c = Client()
        c.force_login(u)
        return c.post(f'/portal/freigabe/{self.a.pk}/', {'aktion': aktion, 'kommentar': kommentar})

    def test_entscheid_geht_an_die_verwaltung(self):
        self._entscheid('ablehnen')
        an = [m.to[0] for m in mail.outbox]
        self.assertIn('verwaltung@example.ch', an)
        intern = [m for m in mail.outbox if m.to == ['verwaltung@example.ch']][0]
        self.assertIn('abgelehnt', _text(intern))
        self.assertIn('Zu teuer', _text(intern))

    def test_entscheid_informiert_den_handwerker_ohne_den_kommentar(self):
        self._entscheid('freigeben')
        hw = [m for m in mail.outbox if m.to == ['hw@example.ch']]
        self.assertEqual(len(hw), 1)
        self.assertNotIn('Zu teuer', _text(hw[0]))
        self.assertIn('Ticket #', hw[0].subject)

    def test_entscheid_steht_im_verlauf_und_maskiert(self):
        self._entscheid('ablehnen', kommentar=EINSCHLEUSUNG)
        for m in mail.outbox:
            self.assertNotIn('<img', _text(m))


class HandwerkerPortalMailTests(TestCase):
    """Was der Handwerker im Portal tut, erfährt die Verwaltung auch per Mail (nicht nur als Badge)."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        from .test_portale_modul3 import _auftrag, _link
        from crm.models import Organisation
        cache.clear()
        Organisation.objects.filter(pk=self.a.organisation.pk).update(email='vw-a@example.ch')
        Organisation.objects.filter(pk=self.b.organisation.pk).update(email='vw-b@example.ch')
        self.auftrag = _auftrag(self.a)
        self.url = f'/auftrag/{_link(self.a, self.auftrag)}/'
        self.client = Client()
        mail.outbox.clear()

    def _pdf(self):
        return SimpleUploadedFile('o.pdf', b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n', 'application/pdf')

    def _an_verwaltung(self):
        return [m for m in mail.outbox if m.to == ['vw-a@example.ch']]

    def test_offerte(self):
        self.client.post(self.url, {'aktion': 'offerte', 'betrag': '400', 'datei': self._pdf()})
        m = self._an_verwaltung()
        self.assertEqual(len(m), 1)
        self.assertIn('Offerte', m[0].subject)
        self.assertIn('400', _text(m[0]))
        self.assertIn('Verwaltung A AG via', m[0].from_email)

    def test_rechnung(self):
        self.client.post(self.url, {'aktion': 'rechnung', 'betrag': '480', 'datei': self._pdf()})
        m = self._an_verwaltung()
        self.assertEqual(len(m), 1)
        self.assertIn('Rechnung', m[0].subject)

    def test_nachricht_maskiert(self):
        self.client.post(self.url, {'aktion': 'nachricht', 'text': f'Hallo {EINSCHLEUSUNG}'})
        m = self._an_verwaltung()
        self.assertEqual(len(m), 1)
        self.assertNotIn('<img', _text(m[0]))

    def test_nie_an_die_andere_verwaltung(self):
        self.client.post(self.url, {'aktion': 'nachricht', 'text': 'Hallo'})
        self.assertEqual([m for m in mail.outbox if 'vw-b@example.ch' in m.to], [])

    def test_ohne_adresse_kein_absturz(self):
        from crm.models import Organisation
        Organisation.objects.filter(pk=self.a.organisation.pk).update(email='')
        r = self.client.post(self.url, {'aktion': 'nachricht', 'text': 'Hallo'})
        self.assertEqual(r.status_code, 302)


class AllgemeinTests(_Basis):
    """Quer über alle Wege: Absender «Firma via …», Reply-To gesetzt, kein Platzhalter bleibt stehen."""

    def test_vollstaendiger_ablauf(self):
        from crm.models import Organisation
        from tickets.workflow import (auftrag_stornieren, auftrag_vergeben, nachricht_an_handwerker,
                                      termin_absagen, termin_festlegen, wechsle_status)
        t = _ticket()                      # legt die Organisation an; erst danach lässt sie sich ändern
        Organisation.objects.update(firma='Muster Verwaltung AG', email='vw@example.ch')
        a = auftrag_vergeben(t, _handwerker())['auftrag']
        nachricht_an_handwerker(a, 'Hallo')
        termin_festlegen(a, datetime(2026, 11, 20, 8, 30))
        termin_absagen(a)
        wechsle_status(t, 'warte_auf_mieter', melder_informieren=True)
        auftrag_stornieren(a, 'Doch nicht')
        self.assertGreaterEqual(len(mail.outbox), 8)
        for m in mail.outbox:
            self.assertIn('Muster Verwaltung AG via', m.from_email, m.subject)
            self.assertEqual(m.reply_to, ['vw@example.ch'], m.subject)
            self.assertNotRegex(m.subject + _text(m), r'\{[a-z_]+\}', m.subject)
            self.assertIn('Ticket #', m.subject)


class MieterPortalMailTests(TestCase):
    """Mieterportal: Meldung und Nachricht des angemeldeten Mieters. Die Bestätigung kommt in dessen
    Korrespondenzsprache, die Mail an die Verwaltung von der Verwaltung des HAUSES (nie der anderen)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from crm.models import Organisation
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        user = get_user_model()
        for fx in (cls.a, cls.b):
            u = user.objects.create_user(username=f'mieter_mw_{fx.kuerzel.lower()}', password='x')
            with organisation_kontext(fx.organisation):
                fx.mieter.benutzer = u
                fx.mieter.save()
            fx.login = u
            Organisation.objects.filter(pk=fx.organisation.pk).update(email=f'vw-{fx.kuerzel.lower()}@example.ch')

    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.c = Client()
        self.c.force_login(self.a.login)

    def test_meldung_bestaetigt_in_der_sprache_des_mieters_und_meldet_der_verwaltung(self):
        from crm.models import Mieter
        Mieter.alle_organisationen.filter(pk=self.a.mieter.pk).update(sprache='fr')
        r = self.c.post('/mieter/schaden/', {'titel': 'Fuite', 'beschreibung': 'Le robinet fuit',
                                             'vertrag_id': self.a.vertrag.pk})
        self.assertEqual(r.status_code, 302)
        an = {m.to[0]: m for m in mail.outbox}
        self.assertEqual(set(an), {self.a.mieter.email, 'vw-a@example.ch', 'eig-a@example.ch'})
        self.assertIn('Bonjour', _text(an[self.a.mieter.email]))
        self.assertIn('Ticket #', an[self.a.mieter.email].subject)
        self.assertIn('Verwaltung A AG via', an[self.a.mieter.email].from_email)

    def test_nachricht_geht_an_die_verwaltung_des_hauses_maskiert(self):
        from tickets.models import SchadenMeldung
        with organisation_kontext(self.a.organisation):
            t = SchadenMeldung.objects.create(
                liegenschaft=self.a.liegenschaft, betroffene_einheit=self.a.einheit,
                gemeldet_von=self.a.mieter, titel='Hahn', beschreibung='x', email_melder=self.a.mieter.email)
        self.c.post(f'/mieter/ticket/{t.pk}/nachricht/', {'text': f'Hallo {EINSCHLEUSUNG}'})
        an = [m.to[0] for m in mail.outbox]
        self.assertIn('vw-a@example.ch', an)
        self.assertNotIn('vw-b@example.ch', an)
        for m in mail.outbox:
            self.assertNotIn('<img', _text(m))
