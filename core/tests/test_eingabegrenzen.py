"""ROUTE-05/06, SICH-14: Eingaben, die nicht in ihr Feld passen, ergeben nie eine 500-Seite.

BEFUND (Audit 28.10.2026)
- `?lg=abc` an jede `/neu/`-Seite: HTTP 500 auf 136 von 166 Seiten; `jahr=99999`, `monate=…`,
  `edit=abc`, `abnahme=abc` ebenso.
- 35 Endpunkte antworteten auf PostgreSQL mit 500: zu lange Texte (`DataError`), zu grosse Beträge
  (`ValueError` aus dem Betragsprüfer), 20-stellige Kennungen (`smallint out of range`,
  `OverflowError`). SQLite verschweigt das — die Suite blieb grün (5 018 Tests).

Dieser Wächter ruft JEDE benannte POST-Adresse des Projekts mit überlangen Texten, übergrossen
Beträgen und 20-stelligen Kennungen auf und verlangt: kein 5xx. Der Teil mit der Datenbank
läuft nur auf PostgreSQL (dort entstehen die Fehler); in der CI läuft er im Job `test-postgres`.

Gegenprobe: `EingabeFehlerMiddleware` aus `MIDDLEWARE` nehmen — der PostgreSQL-Lauf wird mit
einer langen Liste roter Adressen rot; die Einheitstests der Schicht schlagen auf SQLite fehl.
"""
import json
import os
import re
import unittest
from datetime import date
from unittest import mock

from django.db import connection, transaction
from django.db.utils import DataError, IntegrityError
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import URLResolver, get_resolver, reverse

from core.middleware_eingabe import EingabeFehlerMiddleware, _meldung
from core.utils.parameter import id_param, int_param, jahr_param, jahr_streng
from finance.models import BetragFehler

from ._helfer import _team_user
from .test_rbac import RbacBasis


class ParameterTests(SimpleTestCase):
    def test_int_param(self):
        for roh in (None, '', 'abc', '1e3', '5.0', ' ', '--1', '١٢', '9' * 25, 'NaN'):
            with self.subTest(roh=roh):
                self.assertEqual(int_param(roh, 7), 7)
        self.assertEqual(int_param('42', 7), 42)
        self.assertEqual(int_param(' 42 ', 7), 42)
        self.assertEqual(int_param('-3', 7), -3)
        self.assertEqual(int_param('5', 7, minimum=6), 7)
        self.assertEqual(int_param('50', 7, maximum=10), 7)

    def test_id_param_kennt_die_grenze_von_bigint(self):
        self.assertEqual(id_param('9223372036854775807'), 2 ** 63 - 1)
        self.assertIsNone(id_param('9223372036854775808'))
        self.assertIsNone(id_param('0'))
        self.assertIsNone(id_param('-1'))
        self.assertIsNone(id_param('99999999999999999999'))

    def test_jahr(self):
        self.assertEqual(jahr_param('2026'), 2026)
        self.assertEqual(jahr_param('99999', 2026), 2026)
        self.assertEqual(jahr_param('0', 2026), 2026)
        with self.assertRaises(ValueError):
            jahr_streng('99999')
        self.assertEqual(jahr_streng('2024'), 2024)


class BetragFehlerTests(SimpleTestCase):
    def test_ist_validationerror_und_valueerror(self):
        from django.core.exceptions import ValidationError
        from finance.models import KreditorenRechnung
        with self.assertRaises(ValidationError):
            from finance.models import pruefe_dezimalfelder
            pruefe_dezimalfelder(KreditorenRechnung(betrag='999999999999.99'))
        with self.assertRaises(ValueError):
            pruefe_dezimalfelder(KreditorenRechnung(betrag='999999999999.99'))

    def test_text_ist_lesbar(self):
        from finance.models import KreditorenRechnung, pruefe_dezimalfelder
        try:
            pruefe_dezimalfelder(KreditorenRechnung(betrag='999999999999.99'))
        except BetragFehler as fehler:
            self.assertIn('zu gross', str(fehler))
            self.assertNotIn('[', str(fehler))      # kein Listen-Repr einer ValidationError


class MeldungTests(SimpleTestCase):
    """Welche Ausnahmen die Schicht abfängt — und welche ausdrücklich NICHT."""

    def test_abgefangen(self):
        faelle = [
            (DataError('value too long for type character varying(200)'), '200 Zeichen'),
            (DataError('smallint out of range'), 'zu gross'),
            (DataError('bigint out of range'), 'zu gross'),
            (OverflowError('Python int too large to convert to C long'), 'zu gross'),
            (BetragFehler('Stundensatz (CHF): Betrag zu gross (maximal 1\'000\'000).'), 'Stundensatz'),
            (ValueError("Field 'id' expected a number but got 'abc'."), 'ungültige Kennung'),
            (IntegrityError('CHECK constraint failed: menge'), 'negative Menge'),
            (IntegrityError('new row for relation "x" violates check constraint "menge_check"'),
             'negative Menge'),
        ]
        for ausnahme, enthaelt in faelle:
            with self.subTest(ausnahme=ausnahme):
                self.assertIn(enthaelt, _meldung(ausnahme))

    def test_echte_fehler_bleiben_sichtbar(self):
        """Gegenprobe: Was die Schicht nicht benennen kann, ist ein Fehler und bleibt eine 500."""
        for ausnahme in (ValueError('irgendwas'), DataError('invalid input syntax'),
                         IntegrityError('UNIQUE constraint failed: crm_mieter.email'),
                         IntegrityError('insert or update violates foreign key constraint'),
                         KeyError('x'), RuntimeError('kaputt'), ZeroDivisionError()):
            with self.subTest(ausnahme=ausnahme):
                self.assertIsNone(_meldung(ausnahme))


class MiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.mw = EingabeFehlerMiddleware(lambda r: None)
        self.rf = RequestFactory()

    def _anfrage(self, methode='post', **extra):
        r = getattr(self.rf, methode)('/neu/pendenzen/neu/', **extra)
        r.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        r._messages = FallbackStorage(r)
        return r

    def test_post_mit_rueckkehrseite_zeigt_meldung_dort(self):
        r = self._anfrage(HTTP_REFERER='http://testserver/neu/pendenzen/')
        antwort = self.mw.process_exception(r, DataError('value too long for type character varying(200)'))
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], 'http://testserver/neu/pendenzen/')
        meldungen = [str(m) for m in r._messages]
        self.assertEqual(len(meldungen), 1)
        self.assertIn('nicht gespeichert', meldungen[0])
        self.assertIn('200 Zeichen', meldungen[0])

    def test_fremde_rueckkehrseite_wird_nicht_angesprungen(self):
        r = self._anfrage(HTTP_REFERER='https://boese.example/x')
        antwort = self.mw.process_exception(r, OverflowError('Python int too large to convert to C int'))
        self.assertEqual(antwort.status_code, 400)

    def test_ohne_rueckkehrseite_und_bei_get_eine_gestaltete_400er_seite(self):
        for r in (self._anfrage(), self._anfrage('get')):
            antwort = self.mw.process_exception(r, BetragFehler('Betrag zu gross (maximal 1\'000).'))
            self.assertEqual(antwort.status_code, 400)
            self.assertIn('Betrag zu gross', antwort.content.decode())
            self.assertIn('Ungültige Eingabe', antwort.content.decode())

    def test_json_bekommt_json(self):
        r = self._anfrage(HTTP_ACCEPT='application/json')
        antwort = self.mw.process_exception(r, OverflowError('Python int too large to convert to C long'))
        self.assertEqual(antwort.status_code, 400)
        self.assertIn('fehler', json.loads(antwort.content))

    def test_echter_fehler_wird_durchgereicht(self):
        r = self._anfrage()
        self.assertIsNone(self.mw.process_exception(r, RuntimeError('kaputt')))


class UngueltigeParameterTests(RbacBasis):
    """ROUTE-05: Ein ungültiger Abfrageparameter gilt als nicht angegeben."""

    SEITEN = ('/neu/', '/neu/vertraege/', '/neu/liegenschaften/', '/neu/personen/', '/neu/schaeden/',
              '/neu/debitoren/', '/neu/buchhaltung/', '/neu/auswertung/', '/neu/mwst/',
              '/neu/sollstellung/', '/neu/kontenplan/', '/neu/berichte/betriebskostenspiegel/',
              '/neu/schaeden/kosten/', '/neu/berichte/leerstand-verlauf/', '/neu/vertraege/neu/')

    def test_lg_abc_und_riesige_kennung(self):
        c = Client()
        c.force_login(self.u_verwalter)
        for adresse in self.SEITEN:
            for wert in ('abc', '99999999999999999999', '-1', '0', ''):
                with self.subTest(adresse=adresse, lg=wert):
                    antwort = c.get(adresse, {'lg': wert})
                    # Eine ganz normale Seite (oder ihre Weiterleitung) — weder 500 noch die
                    # 400er-Meldung der Eingabe-Schicht: Der Parameter gilt als nicht angegeben.
                    self.assertIn(antwort.status_code, (200, 302), adresse)

    def test_lg_abc_zeigt_den_ganzen_bestand(self):
        """Gegenprobe: «Nicht angegeben» heisst kein Filter — nicht ein anderer Filter."""
        c = Client()
        c.force_login(self.u_verwalter)
        ohne = c.get('/neu/liegenschaften/').content.decode()
        mit = c.get('/neu/liegenschaften/', {'lg': 'abc'}).content.decode()
        self.assertIn('Teststrasse 1', ohne)
        self.assertIn('Teststrasse 1', mit)
        self.assertIn('Fremdweg 9', mit)

    def test_negative_menge_ergibt_eine_meldung(self):
        """ROUTE-06(b): `Ausstattung.menge` ist nicht negativ; ein «-1» war ein IntegrityError."""
        c = Client()
        c.force_login(self.u_verwalter)
        antwort = c.post(f'/neu/objekte/{self.einheit.pk}/ausstattung/',
                         {'raum': 'Küche', 'kategorie': 'Backofen', 'menge': '-1'},
                         HTTP_REFERER='http://testserver/neu/objekte/')
        self.assertLess(antwort.status_code, 500)

    def test_jahr_und_monate_ausserhalb_des_bereichs(self):
        c = Client()
        c.force_login(self.u_verwalter)
        for adresse, parameter in (
                ('/neu/auswertung/', {'jahr': '99999'}), ('/neu/mwst/', {'jahr': '99999'}),
                ('/neu/buchhaltung/', {'jahr': '99999'}), ('/neu/kontenplan/', {'jahr': '99999'}),
                ('/neu/buchhaltung/konto/1100/', {'jahr': '99999'}),
                ('/neu/sollstellung/', {'jahr': '99999', 'monat': '13'}),
                ('/neu/schaeden/kosten/', {'jahr': '99999'}),
                ('/neu/berichte/betriebskostenspiegel/', {'jahr': '99999'}),
                (f'/neu/mandate/{self.eigentuemer.pk}/abrechnung/', {'jahr': '99999'}),
                (f'/neu/mandate/{self.eigentuemer.pk}/kontokorrent/', {'jahr': '99999'}),
                ('/neu/jahr/', {}),
                ('/neu/mieterwechsel/', {'monate': '999999'}),
                ('/neu/berichte/leerstand-verlauf/', {'monate': '999999999999'}),
                ('/neu/vertraege/neu/', {'edit': 'abc'}),
                (f'/neu/vertraege/{self.vertrag_fremd.pk}/schlussabrechnung/', {'abnahme': 'abc'})):
            with self.subTest(adresse=adresse, parameter=parameter):
                antwort = c.get(adresse, parameter)
                self.assertNotIn(antwort.status_code, (500, 502, 503), adresse)


# ---------------------------------------------------------------------------
# Der Sweep auf PostgreSQL
# ---------------------------------------------------------------------------

#: Adressen, die der Sweep nicht aufruft, mit Grund. Jede Zeile ist eine Entscheidung.
AUSGELASSEN = {
    'logout': 'beendet die Sitzung des Testclients',
    'fw_datenreset': 'löscht den Bestand',
    'fw_benutzer_loeschen': 'löscht den angemeldeten Benutzer',
    'fw_liegenschaft_gwr': 'ruft die Bundesdienste auf (Netz)',
    # Geldpfade, die ein anderer Auftrag bearbeitet (Etappe 0, Auftrag B): `redirect(request.POST['next'])`
    # mit Nicht-URL → NoReverseMatch. Sobald dort `sicheres_ziel` steht, die Zeilen streichen.
    'fw_zahlung_stornieren': 'Geldpfad (Auftrag B): ungeprüftes `next`',
    'fw_kreditor_zahlung_stornieren': 'Geldpfad (Auftrag B): ungeprüftes `next`',
}

#: Namen der Formularfelder, die Zahlen/Kennungen/Auswahlwerte sind und deshalb
#: im Textlängen-Lauf nicht mit Buchstaben gefüllt werden.
_NUMERISCH = re.compile(r'(_id$|_ids$|^lg$|^id$|^pk$|^monat$|^jahr$|^seite$|^embed$|^weiter$|^next$|'
                        r'^zurueck$|^aktion$|^art$|^typ$|^status$|^stufe$|^plan$|^rolle$|^sprache$)')


def _feldnamen():
    """Alle Formularfelder, die die Views aus `request.POST` lesen (aus dem Quelltext)."""
    wurzel = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    namen = set()
    muster = re.compile(r"(?:POST|\bP|post_data|data)(?:\.get|\.getlist)?\(\s*['\"]([a-z_0-9]+)['\"]"
                        r"|(?:POST|\bP)\[\s*['\"]([a-z_0-9]+)['\"]\s*\]")
    for ordner, unterordner, dateien in os.walk(wurzel):
        unterordner[:] = [u for u in unterordner if u not in (
            'node_modules', '.claude', '.git', 'migrations', 'tests', '__pycache__', 'static', 'e2e', 'locale')]
        for datei in dateien:
            if not datei.endswith('.py') or not ('views' in ordner or datei.startswith('views')
                                                 or 'services' in ordner or datei in (
                                                     'services.py', 'forms.py', 'workflow.py')):
                continue
            with open(os.path.join(ordner, datei), encoding='utf-8', errors='ignore') as f:
                for treffer in muster.finditer(f.read()):
                    namen.add(treffer.group(1) or treffer.group(2))
    return namen


def _benannte_adressen():
    """(Name, Parameternamen) jeder benannten Adresse des Projekts."""
    ergebnis = []
    for name, eintrag in get_resolver().reverse_dict.items():
        if isinstance(name, str):
            for _muster, parameter in eintrag[0]:
                ergebnis.append((name, list(parameter)))
                break
    return sorted(ergebnis)


@unittest.skipUnless(connection.vendor == 'postgresql',
                     'Textlängen und Wertebereiche erzwingt nur PostgreSQL (SQLite verschweigt sie)')
class PostgresSweepTests(TestCase):
    """Jede POST-Adresse mit überlangen Texten, übergrossen Beträgen und 20-stelligen Kennungen."""

    @classmethod
    def setUpTestData(cls):
        from ._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.namen = _feldnamen()

    def _sweep(self, daten):
        client = Client(raise_request_exception=False)
        client.force_login(self.a.benutzer)
        schlecht = []
        geprueft = 0
        for name, parameter in _benannte_adressen():
            if name in AUSGELASSEN:
                continue
            try:
                args = []
                for p in parameter:
                    if p in ('uidb64', 'token', 'pfad', 'nummer', 'zweck', 'art', 'doc_type', 'nr',
                             'content_type_id', 'object_id'):
                        raise LookupError(p)
                    args.append(self.a.objekt_fuer(p, name).pk)
                pfad = reverse(name, args=args)
            except Exception:
                continue
            if pfad.startswith(('/admin/', '/i18n', '/static/', '/media/')):
                continue
            with mock.patch('requests.sessions.Session.request',
                            side_effect=__import__('requests').exceptions.ConnectionError('kein Netz im Test')):
                with transaction.atomic():
                    antwort = client.post(pfad, daten)
                    status = antwort.status_code
                    transaction.set_rollback(True)       # der Lauf ändert nichts
            geprueft += 1
            if status >= 500:
                schlecht.append((name, pfad, status))
        self.assertGreater(geprueft, 300, 'Der Sweep hat kaum Adressen erreicht — Aufbau kaputt?')
        self.assertEqual(schlecht, [], 'Adressen mit 5xx: %s' % schlecht)

    def test_ueberlange_texte(self):
        fremd = {'liegenschaft_id': self.a.liegenschaft.pk, 'lg': self.a.liegenschaft.pk,
                 'einheit_id': self.a.einheit.pk, 'vertrag_id': self.a.vertrag.pk,
                 'mieter_id': self.a.mieter.pk}
        daten = {n: 'Ä' * 700 for n in self.namen if not _NUMERISCH.search(n)}
        daten.update(fremd)
        for k in ('betrag', 'netto_mietzins', 'nebenkosten', 'kaution'):
            daten[k] = '100.00'
        self._sweep(daten)

    def test_uebergrosse_betraege(self):
        self._sweep({n: '99999999999999.99' for n in self.namen if not _NUMERISCH.search(n)})

    def test_zwanzigstellige_kennungen(self):
        self._sweep({n: '99999999999999999999' for n in self.namen})
