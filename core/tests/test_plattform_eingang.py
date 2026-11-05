"""Das Plattform-Postfach: ein Sammelpostfach per IMAP statt Brevo (`fetch_plattform_eingang`, 4.11.2026).

IMAP wird nicht berührt: `imaplib.IMAP4_SSL` ist durch eine kleine Fake-Klasse ersetzt, die Mails als Bytes liefert
(echte `EmailMessage`-Mails), Flags führt und `EXPUNGE` kennt. Alle Zeiten kommen als `jetzt` herein.

Jede Klasse nennt ihre GEGENPROBE im Docstring (Code temporär ändern -> der Test wird rot).
"""
import ast
import imaplib
import io
from datetime import datetime, timedelta, timezone as dtz
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.services import plattform_postfach as pp
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture
from .test_rechnungseingang import _logbuch, _pdf, _rechnungen
from .test_ticket_workflow import MAIL

DOMAIN = 'immoswiss.app'
IMAP = dict(PLATTFORM_IMAP_HOST='imap.example.ch', PLATTFORM_IMAP_PORT=993, PLATTFORM_IMAP_BENUTZER='eingang@x.ch',
            PLATTFORM_IMAP_PASSWORT='geheim', PLATTFORM_IMAP_ORDNER='INBOX', BREVO_WEBHOOK_SECRET=None,
            BREVO_API_KEY=None, GROQ_API_KEY=None)
WURZEL = Path(__file__).resolve().parents[2]


# --- Fake-IMAP -------------------------------------------------------------------------------------------------

class Zustand:
    """Der Inhalt des Fake-Postfachs und was mit ihm geschah."""

    def __init__(self):
        self.mails = []              # Dicts: roh, flags (set), datum
        self.holen = []              # Teile, die geholt wurden
        self.login_fehler = False
        self.verbindungsfehler = None
        self.store_fehler = False
        self.verbunden = []
        self.expunged = 0

    def hinein(self, roh, gelesen=False, datum=None):
        self.mails.append({'roh': roh, 'flags': {'\\Seen'} if gelesen else set(), 'datum': datum})
        return len(self.mails)

    def vorhanden(self):
        return [m['roh'] for m in self.mails]

    def gelesen(self, nummer):
        return '\\Seen' in self.mails[nummer - 1]['flags']


def _monat(text):
    return pp._MONATE.index(text[3:6]) + 1


class FakeIMAP:
    z = None

    def __init__(self, host, port=993, timeout=None):
        if self.z.verbindungsfehler:
            raise self.z.verbindungsfehler
        self.z.verbunden.append((host, port, timeout))

    def login(self, benutzer, passwort):
        if self.z.login_fehler:
            raise imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Invalid credentials')
        return 'OK', [b'ok']

    def select(self, ordner):
        return 'OK', [b'1']

    def search(self, _zeichensatz, *kriterien):
        if kriterien == ('UNSEEN',):
            return 'OK', [b' '.join(str(i + 1).encode() for i, m in enumerate(self.z.mails)
                                    if '\\Seen' not in m['flags'])]
        assert kriterien[:2] == ('SEEN', 'BEFORE'), kriterien
        tag, mon, jahr = kriterien[2].split('-')
        grenze = datetime(int(jahr), _monat(f"xxx{mon}"), int(tag), tzinfo=dtz.utc)
        return 'OK', [b' '.join(str(i + 1).encode() for i, m in enumerate(self.z.mails)
                                if '\\Seen' in m['flags'] and m['datum'] is not None and m['datum'] < grenze)]

    def fetch(self, nummer, teile):
        roh = self.z.mails[int(nummer) - 1]['roh']
        self.z.holen.append(teile)
        if teile == '(RFC822.SIZE)':
            return 'OK', [f'{nummer} (RFC822.SIZE {len(roh)})'.encode()]
        if teile == '(BODY.PEEK[])':
            return 'OK', [(f'{nummer} (BODY[] {{{len(roh)}}}'.encode(), roh), b')']
        if teile == '(BODY.PEEK[HEADER])':
            kopf = pp._kopfblock(roh) + b'\r\n\r\n'
            return 'OK', [(f'{nummer} (BODY[HEADER] {{{len(kopf)}}}'.encode(), kopf), b')']
        raise AssertionError(f'unerwartetes FETCH {teile}: nur BODY.PEEK und RFC822.SIZE sind erlaubt')

    def store(self, nummer, _op, flag):
        if self.z.store_fehler and flag == '\\Seen':
            raise imaplib.IMAP4.abort('store kaputt')
        self.z.mails[int(nummer) - 1]['flags'].add(flag)
        return 'OK', [b'ok']

    def expunge(self):
        self.z.expunged += 1
        self.z.mails = [m for m in self.z.mails if '\\Deleted' not in m['flags']]
        return 'OK', [b'ok']

    def close(self):
        return 'OK', [b'ok']

    def logout(self):
        return 'BYE', [b'ok']


def _fake(zustand):
    return mock.patch('imaplib.IMAP4_SSL', type('FakeGebunden', (FakeIMAP,), {'z': zustand}))


def _mail(an, betreff='Hallo', text='Dienstag passt.', von='hans@example.ch', mid='<m1@x.ch>', kopf=None,
          anhang=None, anhang_name='rechnung.pdf'):
    m = EmailMessage()
    m['From'] = f'Hans Muster <{von}>'
    if an:
        m['To'] = an
    m['Subject'] = betreff
    if mid:
        m['Message-ID'] = mid
    for name, wert in (kopf or {}).items():
        m[name] = wert
    m.set_content(text)
    if anhang is not None:
        m.add_attachment(anhang, maintype='application', subtype='pdf', filename=anhang_name)
    return m.as_bytes()


def _antwort(org):
    return f'{org.antwort_kennung}@{DOMAIN}'


def _rechnung(org):
    return f'{org.antwort_kennung}-rechnungen@{DOMAIN}'


def _nachrichten(ticket):
    from tickets.models import TicketNachricht
    return TicketNachricht.alle_organisationen.filter(ticket=ticket, typ='mail_antwort')


def _plattform_mails():
    from core.models import PlattformMail
    return {m.schluessel: m for m in PlattformMail.objects.all()}


JETZT = datetime(2026, 11, 4, 9, 0, tzinfo=dtz.utc)


class Basis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def lauf(self, z, jetzt=JETZT):
        with override_settings(**IMAP), _fake(z):
            return pp.abrufen(jetzt=jetzt)


@MAIL
class ZuordnungTests(Basis):
    """Gegenprobe: in `empfaenger_adressen` einen Kopf aus `EMPFAENGER_KOEPFE` streichen -> der Test dieses Kopfes rot;
    in `mail_verarbeiten` die Prüfung `len({o.pk ...}) > 1` entfernen -> `..._mehrdeutig` rot; die Verzweigung auf
    `ZWECK_RECHNUNGEN` entfernen -> die Rechnungstests rot; `ae.zuordnung_zu_adresse` durch `organisation_zu_adresse`
    ersetzen -> `..._rechnung_...` rot."""

    def _antwort_test(self, z, ticket):
        zahlen = self.lauf(z)
        n = _nachrichten(ticket)
        self.assertEqual(n.count(), 1, zahlen)
        self.assertEqual(n.get().nachricht, 'Dienstag passt.')
        self.assertTrue(z.gelesen(1))
        return zahlen

    def test_to_ordnet_die_antwort_der_richtigen_verwaltung_zu(self):
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Wasserhahn (Ticket #{self.a.schaden.pk})'))
        zahlen = self._antwort_test(z, self.a.schaden)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (1, 0))
        self.assertEqual(_nachrichten(self.b.schaden).count(), 0)

    def test_delivered_to_zaehlt_auch_wenn_to_auf_eine_fremde_adresse_zeigt(self):
        z = Zustand()
        z.hinein(_mail('info@fremd.ch', f'Re: Ticket #{self.a.schaden.pk}',
                       kopf={'Delivered-To': _antwort(self.a.organisation)}))
        self._antwort_test(z, self.a.schaden)

    def test_x_original_to_zaehlt(self):
        z = Zustand()
        z.hinein(_mail('eingang@x.ch', f'Re: Ticket #{self.a.schaden.pk}',
                       kopf={'X-Original-To': _antwort(self.a.organisation).upper()}))
        self._antwort_test(z, self.a.schaden)

    def test_cc_und_envelope_to_zaehlen(self):
        z = Zustand()
        z.hinein(_mail('info@fremd.ch', f'Re: Ticket #{self.a.schaden.pk}', mid='<c@x>',
                       kopf={'Cc': f'Kopie <{_antwort(self.a.organisation)}>'}))
        self._antwort_test(z, self.a.schaden)
        z = Zustand()
        z.hinein(_mail('info@fremd.ch', f'Re: Ticket #{self.b.schaden.pk}', mid='<e@x>',
                       kopf={'Envelope-To': _antwort(self.b.organisation)}))
        self._antwort_test(z, self.b.schaden)

    def test_rechnung_mit_pdf_landet_beim_richtigen_mandanten(self):
        z = Zustand()
        z.hinein(_mail(_rechnung(self.a.organisation), 'Rechnung 2026-042', anhang=_pdf()))
        zahlen = self.lauf(z)
        self.assertEqual(zahlen['verarbeitet'], 1)
        a, b = _rechnungen(self.a), _rechnungen(self.b)
        self.assertEqual(len(a), 1)
        self.assertEqual(b, [], 'Die Rechnung darf nicht bei der anderen Verwaltung landen.')
        self.assertEqual((a[0].status, str(a[0].betrag)), ('neu', '350.00'))
        self.assertIn('Per E-Mail von hans@example.ch', a[0].fehlermeldung)
        self.assertTrue(_logbuch(self.a, 'Rechnung per E-Mail eingegangen').exists())
        self.assertFalse(_logbuch(self.b, 'Rechnung per E-Mail eingegangen').exists())
        self.assertTrue(z.gelesen(1))

    def test_rechnungsmail_ohne_brauchbaren_anhang_steht_im_logbuch(self):
        z = Zustand()
        z.hinein(_mail(_rechnung(self.a.organisation), 'Rechnung', anhang=b'kein pdf', anhang_name='x.pdf'))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 1))
        self.assertEqual(_rechnungen(self.a), [])
        self.assertTrue(_logbuch(self.a, 'Rechnungsmail ohne Anhang abgerufen').exists())
        self.assertTrue(z.gelesen(1))

    def test_fremde_kennung_legt_nichts_an_und_verraet_nichts(self):
        """Das Ticket von B an die Adresse von A: nichts bei A, nichts bei B."""
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.b.schaden.pk}'))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 1))
        self.assertEqual(_nachrichten(self.b.schaden).count() + _nachrichten(self.a.schaden).count(), 0)
        self.assertTrue(z.gelesen(1))

    def test_unbekannte_adresse_spam_wird_ignoriert_und_als_gelesen_markiert(self):
        from tickets.models import EingegangeneMail, TicketNachricht
        vorher = TicketNachricht.alle_organisationen.count()
        z = Zustand()
        z.hinein(_mail(f'irgendwas-test@{DOMAIN}', f'Re: Ticket #{self.a.schaden.pk}', mid='<s1@x>'))
        z.hinein(_mail('jemand@fremd.ch', 'Hallo', mid='<s2@x>'))
        z.hinein(_mail(None, 'Ohne Empfänger', mid='<s3@x>'))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 3))
        self.assertTrue(all(z.gelesen(i) for i in (1, 2, 3)))
        self.assertEqual(TicketNachricht.alle_organisationen.count(), vorher)
        self.assertEqual(EingegangeneMail.alle_organisationen.count(), 0)
        self.assertEqual({m.ergebnis for m in _plattform_mails().values()}, {'fremd'})

    def test_spam_header_wird_ignoriert_aber_ein_sauberer_nicht(self):
        z = Zustand()
        an = _antwort(self.a.organisation)
        betreff = f'Re: Ticket #{self.a.schaden.pk}'
        z.hinein(_mail(an, betreff, mid='<sp1@x>', kopf={'X-Spam-Flag': 'YES'}))
        z.hinein(_mail(an, betreff, mid='<sp2@x>', kopf={'X-Spam-Status': 'Yes, score=9.1 required=5.0'}))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 2))
        self.assertEqual(_nachrichten(self.a.schaden).count(), 0)
        z = Zustand()
        z.hinein(_mail(an, betreff, mid='<sp3@x>', kopf={'X-Spam-Flag': 'NO', 'X-Spam-Status': 'No, score=0.1'}))
        self.assertEqual(self.lauf(z)['verarbeitet'], 1)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)

    def test_mail_an_zwei_verwaltungen_wird_verworfen(self):
        z = Zustand()
        z.hinein(_mail(f'{_antwort(self.a.organisation)}, {_antwort(self.b.organisation)}',
                       f'Re: Ticket #{self.a.schaden.pk}'))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 1))
        self.assertEqual(_nachrichten(self.a.schaden).count() + _nachrichten(self.b.schaden).count(), 0)
        self.assertEqual({m.ergebnis for m in _plattform_mails().values()}, {'mehrdeutig'})
        self.assertTrue(z.gelesen(1))

    def test_mail_an_beide_adressen_derselben_verwaltung_wird_verworfen(self):
        z = Zustand()
        z.hinein(_mail(f'{_antwort(self.a.organisation)}, {_rechnung(self.a.organisation)}', 'Rechnung',
                       anhang=_pdf()))
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 1))
        self.assertEqual(_rechnungen(self.a), [])

    def test_alte_kennung_gilt_nur_im_fenster(self):
        from core.services.antwort_eingang import kennung_erneuern
        org = self.a.organisation
        alt = _antwort(org)
        kennung_erneuern(org, jetzt=JETZT)
        betreff = f'Re: Ticket #{self.a.schaden.pk}'
        z = Zustand()
        z.hinein(_mail(alt, betreff, mid='<alt1@x>'))
        self.assertEqual(self.lauf(z, jetzt=JETZT + timedelta(days=29))['verarbeitet'], 1)
        z = Zustand()
        z.hinein(_mail(alt, betreff, mid='<alt2@x>'))
        self.assertEqual(self.lauf(z, jetzt=JETZT + timedelta(days=31))['verarbeitet'], 0)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)

    def test_lesemodus_verarbeitet_nichts_markiert_aber_als_gelesen(self):
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}'))
        with mock.patch('core.funktionen.hintergrund_erlaubt', return_value=False):
            zahlen = self.lauf(z)
        self.assertEqual((zahlen['verarbeitet'], zahlen['ignoriert']), (0, 1))
        self.assertEqual(_nachrichten(self.a.schaden).count(), 0)
        self.assertEqual({m.ergebnis for m in _plattform_mails().values()}, {'lesemodus'})

    def test_selbstantwort_an_die_rechnungsadresse_legt_keine_rechnung_an(self):
        z = Zustand()
        z.hinein(_mail(_rechnung(self.a.organisation), 'Abwesend', anhang=_pdf(),
                       kopf={'Auto-Submitted': 'auto-replied'}))
        self.lauf(z)
        self.assertEqual(_rechnungen(self.a), [])


@MAIL
class IdempotenzTests(Basis):
    """Gegenprobe: in `mail_verarbeiten` das `get_or_create` auf `EingegangeneMail` durch `create`-ohne-Prüfung
    ersetzen (`neu = True`) -> `..._zweimal_...` rot; in `_eine_mail` die Prüfung `eintrag.erledigt_am is not None`
    entfernen -> `..._seen_fehlt_...` bleibt grün (die zweite Sicherung), aber mit `neu = True` ebenfalls entfernt rot;
    `empfaenger_adressen` aus `schluessel_aus_roh` entfernen -> `..._bcc_kopien_...` rot."""

    def test_dieselbe_mail_zweimal_im_postfach_ergibt_eine_nachricht(self):
        z = Zustand()
        roh = _mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}')
        z.hinein(roh)
        z.hinein(roh)
        self.lauf(z)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)
        self.assertTrue(z.gelesen(1) and z.gelesen(2))

    def test_fehlendes_seen_fuehrt_nicht_zu_einer_zweiten_nachricht(self):
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}'))
        z.store_fehler = True
        self.lauf(z)
        self.assertFalse(z.gelesen(1))
        z.store_fehler = False
        zahlen = self.lauf(z)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)
        self.assertTrue(z.gelesen(1))
        self.assertEqual(zahlen['verarbeitet'], 0)

    def test_dieselbe_message_id_beim_webhook_und_im_postfach_wird_nur_einmal_verarbeitet(self):
        from tickets.models import EingegangeneMail
        with organisation_kontext(self.a.organisation):
            EingegangeneMail.objects.create(message_id='m-doppelt@x', zweck='antworten')
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}', mid='<m-doppelt@x>'))
        self.lauf(z)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 0)

    def test_bcc_kopien_derselben_mail_an_zwei_verwaltungen_gehen_beide_durch(self):
        """Gleiche Message-ID, verschiedener Empfänger: keine der beiden Kopien darf als Doppelte gelten."""
        z = Zustand()
        for org in (self.a.organisation, self.b.organisation):
            z.hinein(_mail('lieferant-liste@fremd.ch', 'Rechnung', mid='<bcc@x>', anhang=_pdf(),
                           kopf={'Delivered-To': _rechnung(org)}))
        zahlen = self.lauf(z)
        self.assertEqual(zahlen['verarbeitet'], 2)
        self.assertEqual((len(_rechnungen(self.a)), len(_rechnungen(self.b))), (1, 1))


@MAIL
class FehlerUndPoisonTests(Basis):
    """Gegenprobe: in `abrufen` das Zählen von `fehlgeschlagen` und in `_eine_mail` das `raise` entfernen (Fehler wird
    zu 'erledigt') -> `..._bleibt_ungelesen` rot; `MAX_VERSUCHE` auf 1000 -> `..._poison_...` rot; in `_eine_mail` die
    `PEEK`-Abfrage durch `RFC822` ersetzen -> das Fake wirft `AssertionError`, die Tests hier rot."""

    def _mail_a(self):
        return _mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}')

    def test_fehler_bei_der_verarbeitung_laesst_die_mail_ungelesen_und_der_naechste_lauf_wiederholt(self):
        z = Zustand()
        z.hinein(self._mail_a())
        with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten', side_effect=ValueError('x')):
            zahlen = self.lauf(z)
        self.assertEqual((zahlen['fehlgeschlagen'], zahlen['verarbeitet']), (1, 0))
        self.assertFalse(z.gelesen(1), 'Nach einem Fehler muss die Mail ungelesen bleiben.')
        self.assertEqual(_nachrichten(self.a.schaden).count(), 0)
        (eintrag,) = _plattform_mails().values()
        self.assertEqual((eintrag.versuche, eintrag.erledigt_am), (1, None))
        from tickets.models import EingegangeneMail
        self.assertEqual(EingegangeneMail.alle_organisationen.count(), 0,
                         'Die Transaktion muss den Idempotenz-Eintrag mit zurückrollen.')
        zahlen = self.lauf(z)
        self.assertEqual((zahlen['fehlgeschlagen'], zahlen['verarbeitet']), (0, 1))
        self.assertTrue(z.gelesen(1))
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)

    def test_status_nennt_den_fehler_ohne_servernamen(self):
        from core.models import PlattformEingangStatus
        z = Zustand()
        z.hinein(self._mail_a())
        with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten', side_effect=ValueError('x')):
            self.lauf(z)
        s = PlattformEingangStatus.holen()
        self.assertEqual(s.letzter_abruf, JETZT)
        self.assertIn('nicht verarbeiten', s.letzter_fehler)
        self.assertIsNone(s.letzter_erfolg)
        self.lauf(z)
        s.refresh_from_db()
        self.assertEqual((s.letzter_fehler, s.letzter_erfolg), ('', JETZT))

    def test_poison_mail_wird_nach_n_versuchen_als_erledigt_markiert_und_vermerkt(self):
        z = Zustand()
        z.hinein(self._mail_a())
        with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten', side_effect=ValueError('x')):
            for versuch in range(1, min(pp.MAX_VERSUCHE, 10)):
                zahlen = self.lauf(z)
                self.assertEqual(zahlen['fehlgeschlagen'], 1, versuch)
                self.assertFalse(z.gelesen(1), versuch)
            with self.assertLogs('core.services.plattform_postfach', 'ERROR') as protokoll:
                zahlen = self.lauf(z)
        self.assertEqual(pp.MAX_VERSUCHE, 5, 'Die Zahl der Versuche ist Teil der Zusage in der Anleitung.')
        self.assertEqual((zahlen['aufgegeben'], zahlen['fehlgeschlagen']), (1, 0))
        self.assertTrue(z.gelesen(1))
        (eintrag,) = _plattform_mails().values()
        self.assertEqual((eintrag.ergebnis, eintrag.versuche), ('aufgegeben', pp.MAX_VERSUCHE))
        self.assertTrue(any('aufgegeben' in zeile for zeile in protokoll.output))
        self.assertTrue(_logbuch(self.a, 'Eingegangene Mail nicht verarbeitet').exists())
        self.assertFalse(_logbuch(self.b, 'Eingegangene Mail nicht verarbeitet').exists())
        # und danach wird sie nicht mehr angefasst
        with mock.patch('core.services.antwort_eingang.eingehende_antwort_verarbeiten') as aufruf:
            self.lauf(z)
        aufruf.assert_not_called()

    def test_zu_grosse_mail_wird_nicht_geladen_und_ignoriert(self):
        z = Zustand()
        z.hinein(self._mail_a())
        with mock.patch.object(pp, 'MAX_MAIL_BYTES', 100):
            zahlen = self.lauf(z)
        self.assertEqual((zahlen['ignoriert'], zahlen['verarbeitet']), (1, 0))
        self.assertTrue(z.gelesen(1))
        self.assertNotIn('(BODY.PEEK[])', z.holen, 'Eine zu grosse Mail darf nicht geladen werden.')
        self.assertEqual(_nachrichten(self.a.schaden).count(), 0)

    def test_geholt_wird_nur_mit_peek(self):
        z = Zustand()
        z.hinein(self._mail_a())
        self.lauf(z)
        self.assertTrue(z.holen)
        self.assertTrue(all('PEEK' in t or 'SIZE' in t for t in z.holen), z.holen)

    def test_ein_fehler_stoppt_die_uebrigen_mails_nicht(self):
        z = Zustand()
        z.hinein(self._mail_a())
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}', mid='<zwei@x>'))
        echt = pp.mail_verarbeiten
        def erst_kaputt(roh, schluessel, jetzt=None):
            if b'<m1@x.ch>' in roh:
                raise ValueError('kaputt')
            return echt(roh, schluessel, jetzt)
        with mock.patch.object(pp, 'mail_verarbeiten', side_effect=erst_kaputt):
            zahlen = self.lauf(z)
        self.assertEqual((zahlen['fehlgeschlagen'], zahlen['verarbeitet']), (1, 1))
        self.assertEqual((z.gelesen(1), z.gelesen(2)), (False, True))

    def test_verbindungsfehler_und_abgelehnte_anmeldung_stehen_im_status_ohne_zugangsdaten(self):
        from core.models import PlattformEingangStatus
        from core.services.postfach_abruf import AbrufFehler
        z = Zustand()
        z.verbindungsfehler = OSError('Zeitüberschreitung bei imap.example.ch')
        with self.assertRaises(AbrufFehler):
            self.lauf(z)
        s = PlattformEingangStatus.holen()
        self.assertIn('Keine Verbindung', s.letzter_fehler)
        for text in ('imap.example.ch', 'eingang@x.ch', 'geheim'):
            self.assertNotIn(text, s.letzter_fehler)
        z = Zustand()
        z.login_fehler = True
        with self.assertRaises(AbrufFehler):
            self.lauf(z, jetzt=JETZT + timedelta(minutes=1))
        s.refresh_from_db()
        self.assertIn('Anmeldung', s.letzter_fehler)
        self.assertEqual(s.letzter_abruf, JETZT + timedelta(minutes=1))
        for text in ('imap.example.ch', 'eingang@x.ch', 'geheim'):
            self.assertNotIn(text, s.letzter_fehler)

    def test_verbindung_mit_zeitlimit_und_konfigurierten_werten(self):
        z = Zustand()
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_PORT': 1993}), _fake(z):
            pp.abrufen(jetzt=JETZT)
        self.assertEqual(z.verbunden, [('imap.example.ch', 1993, pp.ZEITLIMIT_SEKUNDEN)])


class AufraeumenTests(Basis):
    """Gegenprobe: in `aufraeumen` die Prüfung `PlattformMail.objects.filter(...).exists()` entfernen ->
    `..._eine_mail_die_der_abruf_nie_angefasst_hat_bleibt` rot; die Bedingung `erledigt_am__lte=grenze` entfernen ->
    `..._junger_vermerk_...` rot; `SEEN`/`BEFORE` in der Suche streichen -> das Fake lehnt die Suche ab, alle rot."""

    def test_geloescht_wird_nur_was_gelesen_alt_und_als_erledigt_vermerkt_ist(self):
        from core.models import PlattformMail
        alt = JETZT - timedelta(days=20)
        jung = JETZT - timedelta(days=2)
        z = Zustand()
        def mail(nr):
            return _mail(f'x{nr}@fremd.ch', f'Betreff {nr}', mid=f'<a{nr}@x>')
        z.hinein(mail(1), gelesen=True, datum=alt)       # bearbeitet, alt, Vermerk alt  -> wird gelöscht
        z.hinein(mail(2), gelesen=True, datum=alt)       # nie angefasst (im Webmail gelesen) -> bleibt
        z.hinein(mail(3), gelesen=True, datum=jung)      # Vermerk alt, aber Mail jung -> bleibt
        z.hinein(mail(4), gelesen=True, datum=alt)       # Mail alt, aber Vermerk jung -> bleibt
        z.hinein(mail(5), gelesen=False, datum=alt)      # ungelesen -> wird verarbeitet, aber nicht gelöscht (jung erledigt)
        for nr, tage in ((1, 20), (3, 20), (4, 1)):
            PlattformMail.objects.create(schluessel=pp.schluessel_aus_roh(z.mails[nr - 1]['roh']),
                                         ergebnis='fremd', erledigt_am=JETZT - timedelta(days=tage))
        zahlen = self.lauf(z)
        self.assertEqual(zahlen['geloescht'], 1)
        uebrig = [pp.message_id(__import__('email').message_from_bytes(r)) for r in z.vorhanden()]
        self.assertEqual(uebrig, ['a2@x', 'a3@x', 'a4@x', 'a5@x'])
        self.assertEqual(z.expunged, 1)

    def test_ohne_loeschbare_mails_wird_nicht_expunged(self):
        z = Zustand()
        z.hinein(_mail('x@fremd.ch', 'Hallo'), gelesen=True, datum=JETZT - timedelta(days=30))
        self.lauf(z)
        self.assertEqual((z.expunged, len(z.mails)), (0, 1))

    def test_protokollzeilen_werden_nach_langer_zeit_entfernt(self):
        from core.models import PlattformMail
        PlattformMail.objects.create(schluessel='sehr-alt', ergebnis='fremd',
                                     erledigt_am=JETZT - timedelta(days=pp.PROTOKOLL_TAGE + 1))
        PlattformMail.objects.create(schluessel='neuer', ergebnis='fremd', erledigt_am=JETZT - timedelta(days=30))
        self.lauf(Zustand())
        self.assertEqual(set(_plattform_mails()), {'neuer'})

    def test_fehler_beim_aufraeumen_kippt_den_lauf_nicht(self):
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}'))
        with mock.patch.object(pp, 'aufraeumen', side_effect=RuntimeError('boom')), self.assertLogs(
                'core.services.plattform_postfach', 'ERROR'):
            zahlen = self.lauf(z)
        self.assertEqual(zahlen['verarbeitet'], 1)


class CommandTests(Basis):
    """Gegenprobe: in `handle` die Prüfung `konfiguration() is None` entfernen -> `..._ohne_konfiguration_...` rot
    (Fake-Verbindung wird aufgebaut); `_warten` ignorieren (immer `False`) -> der Dauerlauf-Test hängt nicht, sondern
    bricht nach `MAX` ab; im Dauerlauf das `except Exception` entfernen -> `..._ueberlebt_einen_fehler` rot."""

    def _ausfuehren(self, *args, **einstellungen):
        aus = io.StringIO()
        with override_settings(**{**IMAP, **einstellungen}):
            call_command('fetch_plattform_eingang', *args, stdout=aus)
        return aus.getvalue()

    def test_ohne_konfiguration_endet_der_befehl_freundlich(self):
        with mock.patch('imaplib.IMAP4_SSL') as imap:
            ausgabe = self._ausfuehren('--einmal', PLATTFORM_IMAP_PASSWORT='')
        imap.assert_not_called()
        self.assertIn('nicht eingerichtet', ausgabe)
        self.assertIn('PLATTFORM_IMAP_PASSWORT', ausgabe)

    def test_einmal_verarbeitet_und_meldet_die_zahlen(self):
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}'))
        with _fake(z):
            ausgabe = self._ausfuehren('--einmal')
        self.assertIn('verarbeitet: 1', ausgabe)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)

    def test_durchlauf_stellt_gebuendelte_chat_nachrichten_zu(self):
        """Chat von Mieter/Handwerker: eine zweite Nachricht innerhalb von 5 Minuten wartet auf einen Lauf.
        Läuft nur der Plattform-Eingang (kein `fetch_replies`), muss er sie zustellen.
        Gegenprobe: in `durchlauf` den Aufruf `self.zustellen()` entfernen -> dieser Test rot."""
        z = Zustand()
        with _fake(z), mock.patch('tickets.direktkanal.ausstehende_zustellen') as zustellen:
            self._ausfuehren('--einmal')
        # je Verwaltung ein Aufruf (A und B)
        self.assertGreaterEqual(zustellen.call_count, 2)

    def test_zustellung_laeuft_auch_wenn_der_postfachabruf_scheitert(self):
        from core.services.postfach_abruf import AbrufFehler
        with mock.patch('core.services.plattform_postfach.abrufen', side_effect=AbrufFehler('weg')), \
                mock.patch('tickets.direktkanal.ausstehende_zustellen') as zustellen:
            ausgabe = self._ausfuehren('--einmal')
        self.assertIn('FEHLER', ausgabe)
        self.assertTrue(zustellen.called)

    def test_ohne_angabe_laeuft_ein_einzelner_durchlauf(self):
        z = Zustand()
        with _fake(z):
            ausgabe = self._ausfuehren()
        self.assertIn('verarbeitet: 0', ausgabe)

    def test_verbindungsfehler_ist_eine_meldung_kein_absturz(self):
        z = Zustand()
        z.login_fehler = True
        with _fake(z):
            ausgabe = self._ausfuehren('--einmal')
        self.assertIn('FEHLER', ausgabe)
        self.assertNotIn('geheim', ausgabe)

    def test_einmal_und_dauerlauf_schliessen_sich_aus(self):
        with self.assertRaises(CommandError):
            call_command('fetch_plattform_eingang', '--einmal', '--dauerlauf')

    def test_dauerlauf_ueberlebt_einen_fehler_und_endet_sauber(self):
        from core.management.commands import fetch_plattform_eingang as modul
        z = Zustand()
        z.hinein(_mail(_antwort(self.a.organisation), f'Re: Ticket #{self.a.schaden.pk}'))
        aufrufe = {'n': 0}
        echt = pp.abrufen

        def abrufen(**kw):
            aufrufe['n'] += 1
            if aufrufe['n'] == 1:
                raise RuntimeError('Datenbank weg')
            return echt(**kw)

        def warten(_self, _s):
            return aufrufe['n'] >= 3

        with _fake(z), mock.patch.object(pp, 'abrufen', side_effect=abrufen), \
                mock.patch.object(modul.Command, '_warten', warten), \
                mock.patch.object(modul.Command, '_signale_einrichten'), \
                mock.patch.object(modul, 'close_old_connections'), self.assertLogs(modul.logger, 'ERROR'):
            ausgabe = self._ausfuehren('--dauerlauf')
        self.assertEqual(aufrufe['n'], 3)
        self.assertIn('Fehler im Lauf', ausgabe)
        self.assertIn('beendet', ausgabe)
        self.assertEqual(_nachrichten(self.a.schaden).count(), 1)

    def test_signal_beendet_die_schleife_nach_dem_laufenden_durchlauf(self):
        import signal
        from core.management.commands import fetch_plattform_eingang as modul
        befehl = modul.Command(stdout=io.StringIO())
        befehl._stopp = modul.threading.Event()
        gesetzt = {}
        with mock.patch.object(modul.signal, 'signal', side_effect=lambda n, h: gesetzt.__setitem__(n, h)):
            befehl._signale_einrichten()
        self.assertEqual(set(gesetzt), {signal.SIGTERM, signal.SIGINT})
        self.assertFalse(befehl._stopp.is_set())
        gesetzt[signal.SIGTERM](signal.SIGTERM, None)
        self.assertTrue(befehl._stopp.is_set())
        self.assertTrue(befehl._warten(60), 'Nach dem Signal darf das Warten nicht blockieren.')


class StatusUndReplyToTests(Basis):
    """Gegenprobe: in `plattform_eingang_status` `or imap` aus `eingerichtet` entfernen -> `..._nur_imap_...` rot;
    `anhaenge_fehlen` ohne `not imap` -> `..._anhaenge_...` rot; in `reply_to` wieder `eingang_aktiv_alt`
    (nur BREVO_WEBHOOK_SECRET) nehmen -> `..._reply_to_mit_nur_imap_kanal` rot."""

    def test_status_kombinationen(self):
        s = pp.plattform_eingang_status
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_HOST': ''}):
            self.assertEqual(s(), {'brevo': False, 'imap': False, 'brevo_api': False, 'eingerichtet': False,
                                   'anhaenge_fehlen': False})
        with override_settings(**IMAP):
            self.assertEqual(s(), {'brevo': False, 'imap': True, 'brevo_api': False, 'eingerichtet': True,
                                   'anhaenge_fehlen': False})
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_PASSWORT': ''}):
            self.assertFalse(s()['imap'], 'Ohne Passwort ist der Kanal nicht eingerichtet.')
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_BENUTZER': ' '}):
            self.assertFalse(s()['imap'])

    def test_status_anhaenge_fehlen_nur_wenn_brevo_der_einzige_kanal_ist_und_der_schluessel_fehlt(self):
        s = pp.plattform_eingang_status
        brevo = {**IMAP, 'PLATTFORM_IMAP_PASSWORT': '', 'BREVO_WEBHOOK_SECRET': 'g'}
        with override_settings(**brevo):
            self.assertTrue(s()['anhaenge_fehlen'])
        with override_settings(**{**brevo, 'BREVO_API_KEY': 'bk'}):
            self.assertFalse(s()['anhaenge_fehlen'])
        with override_settings(**{**IMAP, 'BREVO_WEBHOOK_SECRET': 'g'}):
            self.assertFalse(s()['anhaenge_fehlen'], 'Beide Kanäle: die Anhänge kommen über das Postfach.')

    def test_port_ungueltig_faellt_auf_993(self):
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_PORT': 'abc'}):
            self.assertEqual(pp.konfiguration()['port'], 993)

    def test_reply_to_mit_nur_imap_kanal_ist_die_plattformadresse(self):
        from tickets.workflow import reply_to
        t = self.a.schaden
        with override_settings(**IMAP):
            self.assertEqual(reply_to(t), _antwort(t.organisation))
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_PASSWORT': ''}):
            self.assertIsNone(reply_to(t), 'Ohne jeden Kanal bleibt es beim bisherigen Reply-To.')
        with override_settings(**{**IMAP, 'PLATTFORM_IMAP_PASSWORT': '', 'BREVO_WEBHOOK_SECRET': 'g'}):
            self.assertEqual(reply_to(t), _antwort(t.organisation))


class SeiteTests(Basis):
    """Gegenprobe: in `_adresskarten` `anhaenge_ok` wieder auf `bool(api_schluessel())` stellen ->
    `..._nur_imap_...` rot; in `_plattform_status` die Rollenprüfung entfernen -> `..._nur_der_inhaber` rot;
    den Fehlertext durch `str(fehler)` mit Servername ersetzen -> `..._ohne_servernamen` rot."""

    def _seite(self, f, rolle=None, sprache=None, **einstellungen):
        from crm.models import Mitgliedschaft
        if rolle:
            Mitgliedschaft.alle_organisationen.filter(benutzer=f.benutzer).update(rolle=rolle)
        c = Client()
        c.force_login(f.benutzer)
        if sprache:
            c.cookies[settings.LANGUAGE_COOKIE_NAME] = sprache
        with override_settings(**einstellungen):
            return c.get(reverse('postfach_liste')).content.decode()

    def test_nur_imap_kanal_empfang_eingerichtet_und_keine_anhangswarnung(self):
        seite = self._seite(self.a, **IMAP)
        self.assertIn('Empfang eingerichtet. Rechnungen an diese Adresse landen in den Kreditoren.', seite)
        self.assertIn('Empfang über das Plattform-Postfach.', seite)
        self.assertNotIn('Anhänge lassen sich auf dem Server noch nicht laden', seite)
        self.assertNotIn('Der Empfang ist auf dem Server noch nicht eingerichtet', seite)

    def test_nur_brevo_ohne_api_schluessel_warnt_vor_den_anhaengen(self):
        seite = self._seite(self.a, **{**IMAP, 'PLATTFORM_IMAP_PASSWORT': '', 'BREVO_WEBHOOK_SECRET': 'g'})
        self.assertIn('Anhänge lassen sich auf dem Server noch nicht laden', seite)

    def test_beide_kanaele_werden_genannt(self):
        seite = self._seite(self.a, **{**IMAP, 'BREVO_WEBHOOK_SECRET': 'g'})
        self.assertIn('Empfang über das Plattform-Postfach und über Brevo.', seite)
        self.assertNotIn('Anhänge lassen sich auf dem Server noch nicht laden', seite)

    def test_ohne_kanal_ist_der_empfang_nicht_eingerichtet(self):
        seite = self._seite(self.a, **{**IMAP, 'PLATTFORM_IMAP_PASSWORT': ''})
        self.assertIn('Der Empfang ist auf dem Server noch nicht eingerichtet', seite)
        self.assertNotIn('Plattform-Postfach zuletzt abgerufen', seite)

    def test_betreiberzeile_nur_der_inhaber_und_ohne_servernamen(self):
        from core.models import PlattformEingangStatus
        s = PlattformEingangStatus.holen()
        s.letzter_abruf = JETZT
        s.letzter_fehler = 'Anmeldung am Plattform-Postfach abgelehnt. Benutzer und Passwort in der .env prüfen.'
        s.save()
        seite = self._seite(self.a, **IMAP)
        self.assertIn('Plattform-Postfach zuletzt abgerufen: 04.11.2026', seite)
        self.assertIn('Fehler: Anmeldung am Plattform-Postfach abgelehnt', seite)
        for text in ('imap.example.ch', 'eingang@x.ch', 'geheim'):
            self.assertNotIn(text, seite)
        seite = self._seite(self.a, rolle='Verwalter', **IMAP)
        self.assertNotIn('Plattform-Postfach zuletzt abgerufen', seite)
        self.assertNotIn('Anmeldung am Plattform-Postfach', seite)

    def test_betreiberzeile_noch_nie_abgerufen(self):
        seite = self._seite(self.a, **IMAP)
        self.assertIn('Plattform-Postfach noch nie abgerufen.', seite)

    def test_seite_in_fremdsprache_hat_die_neuen_texte_uebersetzt(self):
        seite = self._seite(self.a, sprache='fr', **IMAP)
        self.assertIn('Réception via la boîte aux lettres de la plateforme.', seite)
        self.assertNotIn('Empfang über das Plattform-Postfach.', seite)


class WaechterTests(SimpleTestCase):
    """Das Plattform-Postfach bringt keine neue Abhängigkeit: nur Standardbibliothek (imaplib, email), Django und
    das Projekt. Gegenprobe: `import chardet` in `plattform_postfach.py` einfügen -> rot."""

    DATEIEN = ('core/services/plattform_postfach.py', 'core/management/commands/fetch_plattform_eingang.py')
    ERLAUBT = {'django', 'core', 'tickets', 'crm', 'finance'}

    def _importe(self, text):
        namen = set()
        for k in ast.walk(ast.parse(text)):
            if isinstance(k, ast.Import):
                namen |= {a.name.split('.')[0] for a in k.names}
            elif isinstance(k, ast.ImportFrom) and k.level == 0 and k.module:
                namen.add(k.module.split('.')[0])
        return namen

    def test_nur_standardbibliothek_django_und_projekt(self):
        import sys
        for rel in self.DATEIEN:
            fremd = {n for n in self._importe((WURZEL / rel).read_text(encoding='utf-8'))
                     if n not in sys.stdlib_module_names and n not in self.ERLAUBT}
            self.assertEqual(fremd, set(), f'{rel} importiert Fremdpakete')

    def test_der_waechter_erkennt_einen_fremdimport(self):
        self.assertIn('chardet', self._importe('import chardet\nfrom email import policy'))
        self.assertEqual(self._importe('import imaplib\nfrom email import policy'), {'imaplib', 'email'})

    def test_die_zeitsteuerung_nimmt_keine_maschinenuhr(self):
        text = (WURZEL / 'core/services/plattform_postfach.py').read_text(encoding='utf-8')
        for muster in ('date.' + 'today()', 'datetime.' + 'now()', 'utc' + 'now()'):
            self.assertNotIn(muster, text)
