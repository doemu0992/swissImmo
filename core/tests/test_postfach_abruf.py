"""E-Mail-Eingang je Verwaltung — Abrufschicht und die beiden Befehle.

Die drei Zusagen, die hier geprüft werden:

1. **Keine Mail geht verloren.** Geholt wird mit `BODY.PEEK[]`, das
   Gelesen-Flag wird erst nach erfolgreicher Verarbeitung gesetzt.
2. **Kein stiller Rückfall.** Ohne eingerichtetes Postfach wird übersprungen —
   NICHT auf die alten Umgebungsvariablen zurückgefallen. Sonst holte
   Verwaltung B aus dem Postfach von A.
3. **Die Ticketnummer gilt nur im eigenen Bestand.** Eine Antwort mit
   «Ticket #7» darf das Ticket 7 einer FREMDEN Verwaltung nicht anfassen.

WARUM EIN NACHGEBAUTER IMAP-SERVER UND KEIN ECHTER

Ein Test gegen ein echtes Postfach bräuchte Zugangsdaten im Repository und
wäre je nach Netz rot. Der Nachbau hier antwortet auf genau die vier Aufrufe,
die der Bestand benutzt, und protokolliert sie — womit sich prüfen lässt, WAS
gefragt wurde (`BODY.PEEK[]` statt `RFC822`), nicht nur, was hinten herauskam.

GEGENPROBEN (durchgeführt 18.08.2026, jede einzeln zurückgenommen)

    postfach_abruf.py:  '(BODY.PEEK[])' → '(RFC822)'
      → test_geholt_wird_mit_peek                         FAIL

    postfach_abruf.py:  `store(… '\\Seen')` VOR `verarbeiten(roh)` gezogen
      → test_bei_fehler_bleibt_die_mail_ungelesen         FAIL
        test_flag_erst_nach_erfolgreicher_verarbeitung    FAIL

    fetch_replies.py:   `SchadenMeldung.objects` → `.alle_organisationen`
      → test_fremde_ticketnummer_wird_nicht_bedient       FAIL
        (1 != 0 : Die Antwort landete im Ticket der fremden Verwaltung.)

    fetch_replies.py:   `except Exception` je Verwaltung → `except ZeroDivisionError`
      → test_eine_kaputte_verwaltung_haelt_die_uebrigen_nicht_auf   ERROR
        (RuntimeError schlug bis nach oben durch)
"""
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import Postfach
from core.services.geheimnis import UMGEBUNGSNAME
from core.services.postfach_abruf import AbrufFehler, hole_ungelesene, verbinden
from crm.models import Organisation
from portfolio.models import Einheit, Liegenschaft
from tickets.models import SchadenMeldung, TicketNachricht

SCHLUESSEL = '8NJHVucA9G85uCfVM9egyKhlrIDS1sqoXRa0D9ghqCA='

MAIL_VORLAGE = (b'Subject: Re: Ticket #%(nr)s Wasserschaden\r\n'
                b'From: mieter@example.ch\r\n'
                b'Content-Type: text/plain; charset=utf-8\r\n\r\n'
                b'Der Hahn tropft immer noch.\r\n'
                b'Am 01.01.2026 schrieb ImmoSwiss: alter Text\r\n')


def mail_fuer(ticket_nr):
    return MAIL_VORLAGE % {b'nr': str(ticket_nr).encode()}


class FakeIMAP:
    """Nachbau der vier IMAP-Aufrufe, die der Bestand benutzt."""

    #: Wird von den Tests gesetzt, damit die Instanz im Patch erreichbar ist.
    letzte = None

    def __init__(self, mails=None, login_fehler=False, select_ok=True):
        self.mails = mails or {}
        self.login_fehler = login_fehler
        self.select_ok = select_ok
        self.aufrufe = []
        self.gesetzte_flags = []
        self.geschlossen = False
        FakeIMAP.letzte = self

    # -- die vom Bestand benutzten Methoden ----------------------------
    def login(self, benutzer, passwort):
        self.aufrufe.append(('login', benutzer, passwort))
        if self.login_fehler:
            import imaplib
            raise imaplib.IMAP4.error('AUTHENTICATIONFAILED')
        return 'OK', [b'']

    def select(self, ordner):
        self.aufrufe.append(('select', ordner))
        return ('OK' if self.select_ok else 'NO'), [b'']

    def search(self, charset, kriterium):
        self.aufrufe.append(('search', kriterium))
        return 'OK', [b' '.join(self.mails.keys())]

    def fetch(self, kennung, teil):
        self.aufrufe.append(('fetch', kennung, teil))
        return 'OK', [(b'1 (BODY[] {1})', self.mails[kennung])]

    def store(self, kennung, modus, flag):
        self.gesetzte_flags.append((kennung, flag))
        return 'OK', [b'']

    def close(self):
        self.geschlossen = True

    def logout(self):
        pass


def patch_imap(fake):
    """Ersetzt IMAP4_SSL dort, wo der Bestand es nachschlägt."""
    return mock.patch('core.services.postfach_abruf.imaplib.IMAP4_SSL',
                      return_value=fake)


def _organisation(firma):
    return Organisation.objects.create(firma=firma, strasse='Weg 1', plz='3000', ort='Bern')


def _postfach(organisation, zweck, benutzer):
    postfach = Postfach(organisation=organisation, zweck=zweck,
                        server='imap.example.ch', benutzer=benutzer)
    postfach.passwort = 'hunter2'
    postfach.save()
    return postfach


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class AbrufschichtTests(TestCase):

    def setUp(self):
        self.postfach = _postfach(_organisation('Verwaltung A'), 'antworten', 'a@example.ch')

    def test_geholt_wird_mit_peek(self):
        # DER Test dieser Datei. `RFC822` setzt das Gelesen-Flag als
        # Nebenwirkung des Holens — stürzt die Verarbeitung danach ab, ist die
        # Mail weg, ohne je angekommen zu sein.
        fake = FakeIMAP({b'1': mail_fuer(1)})
        with patch_imap(fake):
            hole_ungelesene(self.postfach, lambda roh: None)
        gefetcht = [a for a in fake.aufrufe if a[0] == 'fetch']
        self.assertEqual(gefetcht, [('fetch', b'1', '(BODY.PEEK[])')])

    def test_flag_erst_nach_erfolgreicher_verarbeitung(self):
        fake = FakeIMAP({b'1': mail_fuer(1)})
        with patch_imap(fake):
            verarbeitet, fehlgeschlagen = hole_ungelesene(self.postfach, lambda roh: None)
        self.assertEqual((verarbeitet, fehlgeschlagen), (1, 0))
        self.assertEqual(fake.gesetzte_flags, [(b'1', '\\Seen')])

    def test_bei_fehler_bleibt_die_mail_ungelesen(self):
        # Damit sie beim nächsten Lauf wiederkommt, statt still zu verschwinden.
        fake = FakeIMAP({b'1': mail_fuer(1)})

        def kaputt(roh):
            raise ValueError('Import gescheitert')

        with patch_imap(fake):
            verarbeitet, fehlgeschlagen = hole_ungelesene(self.postfach, kaputt)
        self.assertEqual((verarbeitet, fehlgeschlagen), (0, 1))
        self.assertEqual(fake.gesetzte_flags, [])

    def test_eine_kaputte_mail_haelt_die_uebrigen_nicht_auf(self):
        fake = FakeIMAP({b'1': mail_fuer(1), b'2': mail_fuer(2), b'3': mail_fuer(3)})
        gesehen = []

        def manchmal(roh):
            gesehen.append(roh)
            if len(gesehen) == 2:
                raise ValueError('diese nicht')

        with patch_imap(fake):
            verarbeitet, fehlgeschlagen = hole_ungelesene(self.postfach, manchmal)
        self.assertEqual((verarbeitet, fehlgeschlagen), (2, 1))
        self.assertEqual(len(gesehen), 3, 'nach dem Fehler wurde abgebrochen')

    def test_verbindung_wird_auch_bei_fehler_geschlossen(self):
        fake = FakeIMAP({b'1': mail_fuer(1)})
        fake.search = mock.Mock(side_effect=OSError('Netz weg'))
        with patch_imap(fake):
            with self.assertRaises(OSError):
                hole_ungelesene(self.postfach, lambda roh: None)
        self.assertTrue(fake.geschlossen, 'Verbindung blieb offen')

    def test_abgelehnte_anmeldung_nennt_den_wahrscheinlichen_grund(self):
        fake = FakeIMAP(login_fehler=True)
        with patch_imap(fake):
            with self.assertRaises(AbrufFehler) as fall:
                verbinden(self.postfach)
        # Der häufigste Fall im Betrieb — und der, bei dem eine generische
        # Meldung am meisten Zeit kostet.
        self.assertIn('App-Passwort', str(fall.exception))

    def test_oauth2_faellt_nicht_auf_das_passwort_zurueck(self):
        self.postfach.verfahren = Postfach.VERFAHREN_OAUTH2
        self.postfach.mandant_id = 'm'
        self.postfach.anwendung_id = 'a'
        self.postfach.refresh_token = 'tok'
        self.postfach.save()
        with patch_imap(FakeIMAP()) as gepatcht:
            with self.assertRaises(AbrufFehler):
                verbinden(self.postfach)
        gepatcht.assert_not_called()

    def test_unvollstaendiges_postfach_versucht_gar_nicht_erst(self):
        self.postfach.server = ''
        self.postfach.save()
        with patch_imap(FakeIMAP()) as gepatcht:
            with self.assertRaises(AbrufFehler):
                verbinden(self.postfach)
        gepatcht.assert_not_called()

    def test_fehlender_schluessel_wird_zu_einem_abruffehler(self):
        # Nicht die rohe SchluesselFehlt: Der Aufrufer schreibt die Meldung ins
        # Fehlerfeld des Postfachs, und dort soll ein Satz stehen, kein
        # Ausnahmename.
        with override_settings(**{UMGEBUNGSNAME: ''}):
            with patch_imap(FakeIMAP()) as gepatcht:
                with self.assertRaises(AbrufFehler) as fall:
                    verbinden(self.postfach)
        self.assertIn(UMGEBUNGSNAME, str(fall.exception))
        gepatcht.assert_not_called()


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class AntwortenZweiVerwaltungenTests(TestCase):
    """Der Kern des Umbaus: Die Ticketnummer gilt nur im eigenen Bestand.

    GEGENPROBE (durchgeführt 18.08.2026)

        core/management/commands/fetch_replies.py:
            SchadenMeldung.objects.filter(pk=nummer)
          → SchadenMeldung.alle_organisationen.filter(pk=nummer)

        → test_fremde_ticketnummer_wird_nicht_bedient   FAIL
            AssertionError: 1 != 0 : Die Antwort landete im Ticket der
            fremden Verwaltung.

        Rückgängig gemacht, danach wieder grün.
    """

    def setUp(self):
        self.a = _organisation('Verwaltung A')
        self.b = _organisation('Verwaltung B')
        self.ticket_a = self._ticket(self.a, 'Schaden A')
        self.ticket_b = self._ticket(self.b, 'Schaden B')
        self.postfach_a = _postfach(self.a, 'antworten', 'a@example.ch')

    @staticmethod
    def _ticket(organisation, titel):
        liegenschaft = Liegenschaft.objects.create(
            strasse=f'{titel} 1', plz='3000', ort='Bern', organisation=organisation)
        einheit = Einheit.objects.create(liegenschaft=liegenschaft, bezeichnung='EG',
                                         typ='whg')
        return SchadenMeldung.objects.create(
            liegenschaft=liegenschaft, betroffene_einheit=einheit,
            titel=titel, beschreibung='…')

    def test_eigene_ticketnummer_wird_bedient(self):
        # Erst die Gegenrichtung: Ohne sie bewiese der Test unten nur, dass
        # nichts ankommt — was auch ein kaputter Abruf leisten würde.
        fake = FakeIMAP({b'1': mail_fuer(self.ticket_a.pk)})
        with patch_imap(fake):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.assertEqual(
            TicketNachricht.alle_organisationen.filter(ticket=self.ticket_a).count(), 1)

    def test_fremde_ticketnummer_wird_nicht_bedient(self):
        # Postfach A bekommt eine Mail, die auf die Ticketnummer von B zeigt.
        fake = FakeIMAP({b'1': mail_fuer(self.ticket_b.pk)})
        with patch_imap(fake):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.assertEqual(
            TicketNachricht.alle_organisationen.filter(ticket=self.ticket_b).count(), 0,
            'Die Antwort landete im Ticket der fremden Verwaltung.')

    def test_jede_verwaltung_aus_ihrem_eigenen_postfach(self):
        _postfach(self.b, 'antworten', 'b@example.ch')
        angemeldet = []

        class Merkend(FakeIMAP):
            def login(self, benutzer, passwort):
                angemeldet.append(benutzer)
                return super().login(benutzer, passwort)

        with mock.patch('core.services.postfach_abruf.imaplib.IMAP4_SSL',
                        side_effect=lambda *a, **k: Merkend({})):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.assertEqual(sorted(angemeldet), ['a@example.ch', 'b@example.ch'])

    def test_eine_kaputte_verwaltung_haelt_die_uebrigen_nicht_auf(self):
        """Dieselbe Zusage wie `je_organisation` — hier von Hand eingelöst.

        Ohne sie bliebe eine Verwaltung, die nach einer fehlerhaften vorne in
        der Reihe steht, wochenlang ohne Abruf, und der Grund stünde in einer
        Zeile ganz oben im Protokoll.
        """
        _postfach(self.b, 'antworten', 'b@example.ch')
        angemeldet = []

        class MitAusfall(FakeIMAP):
            def login(self, benutzer, passwort):
                angemeldet.append(benutzer)
                if benutzer == 'a@example.ch':
                    raise RuntimeError('etwas Unerwartetes, kein AbrufFehler')
                return super().login(benutzer, passwort)

        with mock.patch('core.services.postfach_abruf.imaplib.IMAP4_SSL',
                        side_effect=lambda *a, **k: MitAusfall({})):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.assertIn('b@example.ch', angemeldet,
                      'Nach dem Fehler bei A wurde B gar nicht mehr versucht.')

    def test_zitat_wird_abgeschnitten(self):
        fake = FakeIMAP({b'1': mail_fuer(self.ticket_a.pk)})
        with patch_imap(fake):
            call_command('fetch_replies', '--einmal', verbosity=0)
        nachricht = TicketNachricht.alle_organisationen.get(ticket=self.ticket_a)
        self.assertIn('Der Hahn tropft', nachricht.nachricht)
        self.assertNotIn('alter Text', nachricht.nachricht)

    def test_erfolg_wird_am_postfach_vermerkt(self):
        with patch_imap(FakeIMAP({})):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.postfach_a.refresh_from_db()
        self.assertIsNotNone(self.postfach_a.letzter_abruf)

    def test_verbindungsfehler_landet_im_fehlerfeld(self):
        # Damit die Verwalterin den Grund in ihren Einstellungen sieht, statt
        # dass er nur in einem Serverprotokoll steht, das niemand aufmacht.
        with patch_imap(FakeIMAP(login_fehler=True)):
            call_command('fetch_replies', '--einmal', verbosity=0)
        self.postfach_a.refresh_from_db()
        self.assertIn('abgelehnt', self.postfach_a.letzter_fehler)
        self.assertIsNotNone(self.postfach_a.letzter_fehler_am)


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class KeinStillerRueckfallTests(TestCase):
    """Ohne Postfach wird übersprungen — nicht aus der Umgebung geholt.

    Der gefährlichste denkbare Ausgang dieses Umbaus: Eine Verwaltung ohne
    eigenes Postfach fällt auf die alten Umgebungsvariablen zurück und holt
    damit aus dem Postfach einer anderen.
    """

    def setUp(self):
        self.organisation = _organisation('Verwaltung ohne Postfach')

    def test_replies_ohne_postfach_verbindet_nicht(self):
        with mock.patch.dict('os.environ', {'EMAIL_REPLY_USER': 'alt@example.ch',
                                            'EMAIL_REPLY_PASSWORD': 'geheim'}):
            with patch_imap(FakeIMAP()) as gepatcht:
                call_command('fetch_replies', '--einmal', verbosity=0)
        gepatcht.assert_not_called()

    def test_rechnungen_ohne_postfach_verbindet_nicht(self):
        with mock.patch.dict('os.environ', {'RECHNUNGS_IMAP_USER': 'alt@example.ch',
                                            'RECHNUNGS_IMAP_PASSWORD': 'geheim',
                                            'RECHNUNGS_IMAP_HOST': 'alt.example.ch'}):
            with patch_imap(FakeIMAP()) as gepatcht:
                call_command('fetch_rechnungen', '--einmal', verbosity=0)
        gepatcht.assert_not_called()

    def test_abgeschaltetes_postfach_wird_uebersprungen(self):
        postfach = _postfach(self.organisation, 'antworten', 'a@example.ch')
        postfach.aktiv = False
        postfach.save()
        with patch_imap(FakeIMAP()) as gepatcht:
            call_command('fetch_replies', '--einmal', verbosity=0)
        gepatcht.assert_not_called()

    def test_der_alte_feste_server_steht_nirgends_mehr(self):
        """Kein fest verdrahteter IMAP-Server mehr — im CODE, nicht im Text.

        Bis 18.08.2026 stand er in `fetch_replies.py:104`. Ein Test dagegen,
        weil ein zurückkopierter Server für ALLE Verwaltungen gälte und beim
        Lesen eines Diffs leicht durchgeht.

        ERSTE FASSUNG WAR ZU GROB und wurde prompt rot: Sie suchte den Namen
        zeilenweise im Quelltext und fand ihn in der Datei-Doku, die den alten
        Zustand BESCHREIBT. Ein Test, der die Erklärung mit der Sache
        verwechselt, zwingt dazu, die Erklärung zu löschen — also genau das
        Falsche. Jetzt wird der Syntaxbaum gelesen und werden die Doku-Texte
        vorher entfernt.
        """
        import ast
        from pathlib import Path

        from django.conf import settings

        def ohne_doku(quelle):
            baum = ast.parse(quelle)
            for knoten in ast.walk(baum):
                if not isinstance(knoten, (ast.Module, ast.ClassDef,
                                           ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                erster = knoten.body[0] if knoten.body else None
                if (isinstance(erster, ast.Expr)
                        and isinstance(erster.value, ast.Constant)
                        and isinstance(erster.value.value, str)):
                    knoten.body.pop(0)
                    if not knoten.body:
                        knoten.body.append(ast.Pass())
            return ast.unparse(ast.fix_missing_locations(baum))

        for name in ('fetch_replies.py', 'fetch_rechnungen.py'):
            pfad = Path(settings.BASE_DIR) / 'core' / 'management' / 'commands' / name
            self.assertNotIn('lx37.hoststar.hosting', ohne_doku(pfad.read_text(encoding='utf-8')),
                             f'{name} verdrahtet wieder einen festen Server.')


@override_settings(**{UMGEBUNGSNAME: SCHLUESSEL})
class RechnungenTests(TestCase):

    def setUp(self):
        self.a = _organisation('Verwaltung A')
        self.postfach = _postfach(self.a, 'rechnungen', 'r@a.ch')

    def test_import_laeuft_im_kontext_der_verwaltung(self):
        # Der Beleg-Import legt eine Kreditorenrechnung an; ohne gesetzten
        # Kontext wirft dabei jeder Zugriff auf `objects`. Geprüft wird
        # deshalb, welche Organisation während des Imports gesetzt ist.
        from core.tenancy import aktuelle_organisation

        gesehen = []

        def merken(roh):
            gesehen.append(aktuelle_organisation())
            return []

        with patch_imap(FakeIMAP({b'1': mail_fuer(1)})):
            with mock.patch('core.services.belegimport.importiere_rechnungsmail_bytes',
                            side_effect=merken):
                call_command('fetch_rechnungen', '--einmal', verbosity=0)
        self.assertEqual(gesehen, [self.a])

    def test_nur_eine_verwaltung_auf_wunsch(self):
        zweite = _organisation('Verwaltung B')
        _postfach(zweite, 'rechnungen', 'r@b.ch')
        angemeldet = []

        class Merkend(FakeIMAP):
            def login(self, benutzer, passwort):
                angemeldet.append(benutzer)
                return super().login(benutzer, passwort)

        with mock.patch('core.services.postfach_abruf.imaplib.IMAP4_SSL',
                        side_effect=lambda *a, **k: Merkend({})):
            call_command('fetch_rechnungen', '--einmal',
                         '--verwaltung', str(zweite.pk), verbosity=0)
        self.assertEqual(angemeldet, ['r@b.ch'])
