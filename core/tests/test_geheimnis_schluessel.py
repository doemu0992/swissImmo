"""Schlüsselverwaltung für verschlüsselte Werte: neuer Name, mehrere Schlüssel, Schlüsseldatei, Wechsel ohne Verlust."""
import os
import tempfile
from io import StringIO
from unittest import mock

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from core.services import geheimnis

A, B = Fernet.generate_key().decode(), Fernet.generate_key().decode()


class NamenUndQuellenTests(SimpleTestCase):

    @override_settings(GEHEIMNIS_SCHLUESSEL=A, IMAP_SCHLUESSEL='')
    def test_neuer_name_funktioniert(self):
        self.assertEqual(geheimnis.entschluesseln(geheimnis.verschluesseln('geheim')), 'geheim')

    @override_settings(IMAP_SCHLUESSEL=A)
    def test_alter_name_gilt_weiter(self):
        self.assertEqual(geheimnis.entschluesseln(geheimnis.verschluesseln('geheim')), 'geheim')

    @override_settings(GEHEIMNIS_SCHLUESSEL=A, IMAP_SCHLUESSEL=B)
    def test_neuer_name_geht_vor(self):
        token = geheimnis.verschluesseln('x')
        self.assertTrue(geheimnis.mit_erstem_schluessel_lesbar(token))
        with override_settings(GEHEIMNIS_SCHLUESSEL='', IMAP_SCHLUESSEL=B):
            with self.assertRaises(geheimnis.GeheimtextKaputt):      # mit B allein nicht lesbar: A hat verschlüsselt
                geheimnis.entschluesseln(token)

    @override_settings(GEHEIMNIS_SCHLUESSEL='', IMAP_SCHLUESSEL='')
    def test_schluesseldatei(self):
        with tempfile.NamedTemporaryFile('w', suffix='.key', delete=False) as f:
            f.write(A + '\n')
        self.addCleanup(os.unlink, f.name)
        with mock.patch.dict(os.environ, {geheimnis.DATEINAME: f.name}, clear=False):
            os.environ.pop(geheimnis.NEUER_NAME, None)
            os.environ.pop(geheimnis.UMGEBUNGSNAME, None)
            self.assertTrue(geheimnis.schluessel_vorhanden())
            self.assertEqual(geheimnis.entschluesseln(geheimnis.verschluesseln('aus datei')), 'aus datei')

    @override_settings(GEHEIMNIS_SCHLUESSEL='', IMAP_SCHLUESSEL='')
    def test_fehlende_schluesseldatei_meldet_klar(self):
        with mock.patch.dict(os.environ, {geheimnis.DATEINAME: '/gibt/es/nicht.key'}, clear=False):
            os.environ.pop(geheimnis.NEUER_NAME, None)
            os.environ.pop(geheimnis.UMGEBUNGSNAME, None)
            with self.assertRaises(geheimnis.SchluesselFehlt) as fall:
                geheimnis.schluessel_vorhanden()
        self.assertIn(geheimnis.DATEINAME, str(fall.exception))


class SchluesselwechselTests(SimpleTestCase):

    def test_mehrere_schluessel_erster_verschluesselt_alle_lesen(self):
        with override_settings(GEHEIMNIS_SCHLUESSEL=A):
            alt = geheimnis.verschluesseln('alter wert')
        with override_settings(GEHEIMNIS_SCHLUESSEL=f'{B},{A}'):
            self.assertEqual(geheimnis.entschluesseln(alt), 'alter wert')       # alter Schlüssel liest weiter
            neu = geheimnis.verschluesseln('neuer wert')
            self.assertTrue(geheimnis.mit_erstem_schluessel_lesbar(neu))
            self.assertFalse(geheimnis.mit_erstem_schluessel_lesbar(alt))
        with override_settings(GEHEIMNIS_SCHLUESSEL=B):
            self.assertEqual(geheimnis.entschluesseln(neu), 'neuer wert')       # neuer allein genügt für Neues
            with self.assertRaises(geheimnis.GeheimtextKaputt):
                geheimnis.entschluesseln(alt)                                    # Altes ohne alten Schlüssel nicht

    def test_neu_verschluesseln_wechselt_auf_den_ersten(self):
        with override_settings(GEHEIMNIS_SCHLUESSEL=A):
            alt = geheimnis.verschluesseln('x')
        with override_settings(GEHEIMNIS_SCHLUESSEL=f'{B}\n{A}'):               # Zeilenumbruch trennt auch
            neu = geheimnis.neu_verschluesseln(alt)
            self.assertTrue(geheimnis.mit_erstem_schluessel_lesbar(neu))
            self.assertEqual(geheimnis.entschluesseln(neu), 'x')

    @override_settings(GEHEIMNIS_SCHLUESSEL=f'{A},kein-schluessel')
    def test_ungueltiger_schluessel_in_der_liste_wird_benannt(self):
        with self.assertRaises(geheimnis.SchluesselFehlt) as fall:
            geheimnis.verschluesseln('x')
        self.assertIn('Schlüssel 2', str(fall.exception))


class WechselBefehlTests(TestCase):

    def _mieter(self):
        from core.tests._helfer import _basis_objekte
        _lg, _e, mieter, _v = _basis_objekte()
        return mieter

    def _roh(self, mieter):
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(f'SELECT ahv_nummer FROM {type(mieter)._meta.db_table} WHERE id = %s', [mieter.pk])
            return cur.fetchone()[0]

    def _befehl(self, *args):
        aus = StringIO()
        call_command('schluessel_wechseln', *args, stdout=aus, stderr=aus)
        return aus.getvalue()

    def test_ablauf_alt_neu_ohne_verlust(self):
        mieter = self._mieter()
        with override_settings(GEHEIMNIS_SCHLUESSEL=A):
            mieter.ahv_nummer = '756.1234.5678.97'
            mieter.save()
            roh_alt = self._roh(mieter)
        with override_settings(GEHEIMNIS_SCHLUESSEL=f'{B},{A}'):
            ausgabe = self._befehl()
            self.assertIn('umzuschreiben: 1', ausgabe)
            self.assertEqual(self._roh(mieter), roh_alt, 'ohne --ausfuehren wird nichts geändert')
            ausgabe = self._befehl('--ausfuehren')
            self.assertIn('alles liegt auf dem aktuellen Schlüssel', ausgabe)
            self.assertNotEqual(self._roh(mieter), roh_alt)
            self.assertIn('schon auf dem aktuellen Schlüssel: 1', self._befehl())
        with override_settings(GEHEIMNIS_SCHLUESSEL=B):                          # der alte Schlüssel darf weg
            mieter.refresh_from_db()
            self.assertEqual(mieter.ahv_nummer, '756.1234.5678.97')

    def test_unlesbare_werte_werden_gemeldet_und_nicht_zerstoert(self):
        mieter = self._mieter()
        with override_settings(GEHEIMNIS_SCHLUESSEL=A):
            mieter.ahv_nummer = '756.1234.5678.97'
            mieter.save()
            roh_alt = self._roh(mieter)
        with override_settings(GEHEIMNIS_SCHLUESSEL=B):                          # alter Schlüssel fehlt in der Liste
            with self.assertRaises(CommandError):
                self._befehl('--ausfuehren')
            self.assertEqual(self._roh(mieter), roh_alt)

    @override_settings(GEHEIMNIS_SCHLUESSEL='', IMAP_SCHLUESSEL='')
    def test_ohne_schluessel_bricht_der_befehl_ab(self):
        with self.assertRaises(CommandError):
            self._befehl()
