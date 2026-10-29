"""SICH-14 (öffentlicher Teil): Die Formulare ohne Anmeldung ergeben auf PostgreSQL nie eine 5xx-Seite.

`test_eingabegrenzen.PostgresSweepTests` ruft jede benannte POST-Adresse als angemeldeter Inhaber auf. Die
öffentlichen Formulare (Schadenmeldung, QR-Aushang, Bewerbung, Anmeldung, Passwort-Reset) erreicht dieser Lauf
nicht: Sie brauchen keine Anmeldung, haben teils Pfadparameter, die der Sweep nicht erfindet, und sie sind
die einzigen Schreibstellen, die ein Fremder mit einer einzigen Anfrage zum Absturz bringen könnte. Laut Audit
taten das `schaden_melden` (Titel 200 Zeichen) und `public_report` (`bigint`).

Läuft nur auf PostgreSQL (SQLite verschweigt Feldlängen und Wertebereiche); in der CI im Job `test-postgres`.

Gegenprobe: `EingabeFehlerMiddleware` aus `MIDDLEWARE` nehmen, und der PostgreSQL-Lauf wird rot.
"""
import unittest
from unittest import mock

from django.db import connection, transaction
from django.test import Client, TestCase
from django.urls import reverse
from portfolio.models import Einheit

from ._isolation import MandantenFixture
from .test_eingabegrenzen import _feldnamen

#: Eingaben, die auf SQLite durchgehen und auf PostgreSQL scheitern können.
LANG = 'Ä' * 700
GROSSER_BETRAG = '99999999999999.99'
ZWANZIGSTELLIG = '99999999999999999999'


@unittest.skipUnless(connection.vendor == 'postgresql',
                     'Textlängen und Wertebereiche erzwingt nur PostgreSQL (SQLite verschweigt sie)')
class OeffentlichePostgresTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        Einheit.alle_organisationen.filter(pk=cls.a.einheit.pk).update(zur_ausschreibung=True)
        cls.namen = _feldnamen()

    def _adressen(self):
        eid, lid = self.a.einheit.pk, self.a.liegenschaft.pk
        return [
            reverse('schaden_melden'),
            reverse('public_report', args=[lid]),
            reverse('public_bewerbung', args=[eid]),
            reverse('login'),
            reverse('password_reset'),
        ]

    def _post(self, daten):
        schlecht, geprueft = [], 0
        for pfad in self._adressen():
            client = Client(raise_request_exception=False)
            with mock.patch('requests.sessions.Session.request',
                            side_effect=__import__('requests').exceptions.ConnectionError('kein Netz im Test')):
                with transaction.atomic():
                    status = client.post(pfad, daten, HTTP_HOST='localhost').status_code
                    transaction.set_rollback(True)
            geprueft += 1
            if status >= 500:
                schlecht.append((pfad, status))
        self.assertEqual(geprueft, 5)
        self.assertEqual(schlecht, [], f'Öffentliche Adressen mit 5xx: {schlecht}')

    def test_ueberlange_texte(self):
        self._post({n: LANG for n in self.namen if not n.endswith(('_id', '_ids')) and n not in ('lg', 'jahr', 'monat')})

    def test_uebergrosse_betraege(self):
        self._post({n: GROSSER_BETRAG for n in self.namen})

    def test_zwanzigstellige_kennungen(self):
        self._post({n: ZWANZIGSTELLIG for n in self.namen})

    # --- Grenzfälle: genau am Limit speichert, eins darüber wird abgewiesen -----------------------
    #
    # Der Sweep oben findet nur, was abstürzt. Dass die Prüfgrenzen der Formulare zu den Spalten der Datenbank
    # passen, belegt erst ein Speichern GENAU am Limit: Steht eine Grenze höher als die Spalte, kippt es nur dort
    # auf PostgreSQL (500), und auf SQLite bleibt es unbemerkt.

    #: Grenzen aus `public_schaden_melden_view` (dort inline) — bei einer Änderung dort hier nachziehen.
    GRENZEN_SCHADEN = {'kategorie': 100, 'raum': 80, 'objekt': 80, 'vorname': 100, 'nachname': 100,
                       'telefon': 50, 'beschreibung': 5000}

    def _schaden_basis(self):
        return {'vorname': 'Max', 'nachname': 'Muster', 'email': 'melder@example.ch', 'telefon': '0791234567',
                'kategorie': 'wasser', 'raum': 'Bad', 'objekt': 'Hahn', 'beschreibung': 'tropft',
                'liegenschaft_id': str(self.a.liegenschaft.pk), 'erreichbarkeit': 'telefon'}

    def _absenden(self, pfad, daten):
        from django.core.cache import cache
        cache.clear()                                   # die Drossel (10 je IP und Stunde) soll nicht dazwischenfunken
        with mock.patch('requests.sessions.Session.request',
                        side_effect=__import__('requests').exceptions.ConnectionError('kein Netz im Test')):
            with transaction.atomic():
                antwort = Client(raise_request_exception=False).post(pfad, daten, HTTP_HOST='localhost')
                transaction.set_rollback(True)
        return antwort

    def test_schadenmeldung_am_limit_speichert_darueber_wird_abgewiesen(self):
        for feld, grenze in self.GRENZEN_SCHADEN.items():
            with self.subTest(feld=feld, lage='am Limit'):
                daten = {**self._schaden_basis(), feld: 'x' * grenze}
                antwort = self._absenden(reverse('schaden_melden'), daten)
                self.assertEqual(antwort.status_code, 200, f'{feld} mit {grenze} Zeichen: {antwort.status_code}')
                self.assertTrue(antwort.context['success'], f'{feld} mit {grenze} Zeichen wurde nicht gespeichert')
            with self.subTest(feld=feld, lage='darüber'):
                antwort = self._absenden(reverse('schaden_melden'), {**self._schaden_basis(), feld: 'x' * (grenze + 1)})
                self.assertEqual(antwort.status_code, 400, f'{feld} mit {grenze + 1} Zeichen')

    def test_schadenmeldung_alle_felder_gleichzeitig_am_limit(self):
        """Der Titel setzt sich aus Raum und Objekt zusammen: der ungünstigste Fall muss in die Spalte passen."""
        daten = {**self._schaden_basis(), **{f: 'x' * g for f, g in self.GRENZEN_SCHADEN.items()}}
        antwort = self._absenden(reverse('schaden_melden'), daten)
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.context['success'])

    def test_qr_aushang_am_limit_speichert_darueber_wird_abgewiesen(self):
        from tickets.services import GRENZEN_QR
        basis = {'titel': 'Wasserhahn', 'beschreibung': 'tropft', 'vorname': 'Max', 'nachname': 'Muster',
                 'email': 'melder@example.ch', 'telefon': '0791234567'}
        pfad = reverse('public_report', args=[self.a.liegenschaft.pk])
        for feld, grenze in GRENZEN_QR.items():
            if feld == 'email':
                continue                                  # eine gültige Adresse mit 254 Zeichen ist kein sinnvoller Fall
            with self.subTest(feld=feld, lage='am Limit'):
                antwort = self._absenden(pfad, {**basis, feld: 'x' * grenze})
                self.assertEqual(antwort.status_code, 200, f'{feld} mit {grenze} Zeichen: {antwort.status_code}')
                self.assertTrue(antwort.context.get('success'), f'{feld} mit {grenze} Zeichen wurde nicht gespeichert')
            with self.subTest(feld=feld, lage='darüber'):
                antwort = self._absenden(pfad, {**basis, feld: 'x' * (grenze + 1)})
                self.assertEqual(antwort.status_code, 400, f'{feld} mit {grenze + 1} Zeichen')

    def test_qr_aushang_alle_felder_gleichzeitig_am_limit(self):
        from tickets.services import GRENZEN_QR
        daten = {f: 'x' * g for f, g in GRENZEN_QR.items() if f != 'email'}
        daten['email'] = 'melder@example.ch'
        antwort = self._absenden(reverse('public_report', args=[self.a.liegenschaft.pk]), daten)
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.context.get('success'))

    def test_die_adressen_gibt_es(self):
        """Selbstprüfung (auch auf SQLite nicht übersprungen nötig, daher ohne Datenbankschranke prüfbar)."""
        self.assertEqual(len(self._adressen()), 5)
