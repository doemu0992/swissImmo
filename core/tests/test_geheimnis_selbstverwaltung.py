"""Schlüssel und Verschlüsselung ohne Terminal: Schlüssel entsteht von selbst, Altbestand wird nachgeholt,
Erneuern per Knopf, Seite nur für den Betreiber."""
import os
import tempfile
import threading
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.models import AktivitaetsLog
from core.services import geheimnis, geheimnis_pflege

from ._helfer import _basis_objekte, _team_user

LEER = {'GEHEIMNIS_SCHLUESSEL': '', 'IMAP_SCHLUESSEL': ''}


def _ohne_umgebung():
    return mock.patch.dict(os.environ, {}, clear=False)


class AutoSchluesselTests(SimpleTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = Path(self.tmp.name) / '.geheimnis_schluessel'
        for n in (geheimnis.NEUER_NAME, geheimnis.UMGEBUNGSNAME, geheimnis.DATEINAME):
            patcher = mock.patch.dict(os.environ)
            patcher.start()
            self.addCleanup(patcher.stop)
            os.environ.pop(n, None)

    def _einst(self, **extra):
        return override_settings(GEHEIMNIS_AUTOSCHLUESSEL=True, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(self.pfad),
                                 **{**LEER, **extra})

    def test_schluessel_entsteht_von_selbst_mit_rechten_600(self):
        with self._einst():
            self.assertFalse(self.pfad.exists())
            self.assertTrue(geheimnis.schluessel_vorhanden())
            self.assertTrue(self.pfad.exists())
            self.assertEqual(self.pfad.stat().st_mode & 0o777, 0o600)
            self.assertEqual(geheimnis.entschluesseln(geheimnis.verschluesseln('geheim')), 'geheim')
            self.assertEqual(geheimnis.schluessel_quelle(), 'automatisch')

    def test_derselbe_schluessel_beim_naechsten_start(self):
        with self._einst():
            token = geheimnis.verschluesseln('wert')
            Fernet(self.pfad.read_text().strip().encode())          # gültiger Schlüssel
        with self._einst():                                          # „neuer Prozess“: liest die Datei
            self.assertEqual(geheimnis.entschluesseln(token), 'wert')

    def test_gleichzeitiger_start_ergibt_genau_einen_schluessel(self):
        gelesen = []
        def lauf():
            with self._einst():
                gelesen.append(geheimnis._roh_schluessel())
        threads = [threading.Thread(target=lauf) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(set(gelesen)), 1)
        self.assertEqual(gelesen[0], self.pfad.read_text().strip())

    def test_ausdrueckliche_angabe_hat_vorrang_und_legt_keine_datei_an(self):
        with self._einst(GEHEIMNIS_SCHLUESSEL=Fernet.generate_key().decode()):
            self.assertEqual(geheimnis.schluessel_quelle(), 'einstellung')
        self.assertFalse(self.pfad.exists())

    def test_abgeschaltet_bleibt_es_ein_fehler(self):
        with override_settings(GEHEIMNIS_AUTOSCHLUESSEL=False, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(self.pfad), **LEER):
            self.assertFalse(geheimnis.schluessel_vorhanden())
            with self.assertRaises(geheimnis.SchluesselFehlt):
                geheimnis.verschluesseln('x')
        self.assertFalse(self.pfad.exists())

    def test_nicht_beschreibbar_ist_ein_klarer_fehler_kein_fluechtiger_schluessel(self):
        nicht_da = Path(self.tmp.name) / 'gibt' / 'es' / 'nicht' / '.key'
        with override_settings(GEHEIMNIS_AUTOSCHLUESSEL=True, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(nicht_da), **LEER):
            self.assertFalse(geheimnis.schluessel_vorhanden())


class PflegeTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = Path(self.tmp.name) / '.geheimnis_schluessel'
        for n in (geheimnis.NEUER_NAME, geheimnis.UMGEBUNGSNAME, geheimnis.DATEINAME):
            patcher = mock.patch.dict(os.environ)
            patcher.start()
            self.addCleanup(patcher.stop)
            os.environ.pop(n, None)
        ueberschreiben = override_settings(GEHEIMNIS_AUTOSCHLUESSEL=True, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(self.pfad), **LEER)
        ueberschreiben.enable()
        self.addCleanup(ueberschreiben.disable)
        _lg, _e, self.mieter, _v = _basis_objekte()

    def _roh(self):
        with connection.cursor() as cur:
            cur.execute(f'SELECT ahv_nummer FROM {type(self.mieter)._meta.db_table} WHERE id = %s', [self.mieter.pk])
            return cur.fetchone()[0]

    def _klartext_setzen(self, wert='756.1234.5678.97'):
        with connection.cursor() as cur:
            cur.execute(f'UPDATE {type(self.mieter)._meta.db_table} SET ahv_nummer = %s WHERE id = %s', [wert, self.mieter.pk])

    def test_altbestand_im_klartext_wird_nachgeholt(self):
        self._klartext_setzen()
        z = geheimnis_pflege.zustand()
        self.assertEqual((z.klartext, z.aktuell), (1, 0))
        self.assertEqual(geheimnis_pflege.nachholen(), 1)
        self.assertNotIn('756.', self._roh())      # mit Punkt: «756» allein kann zufällig im Geheimtext (Base64) stehen
        self.assertEqual(geheimnis_pflege.zustand().aktuell, 1)
        self.assertEqual(geheimnis_pflege.nachholen(), 0)                  # wiederholbar
        self.mieter.refresh_from_db()
        self.assertEqual(self.mieter.ahv_nummer, '756.1234.5678.97')

    def test_nach_migration_holt_nach_ohne_dass_jemand_etwas_tut(self):
        self._klartext_setzen()
        geheimnis_pflege.nach_migration()
        self.assertNotIn('756.', self._roh())      # mit Punkt: «756» allein kann zufällig im Geheimtext (Base64) stehen

    def test_nach_migration_stoert_das_deploy_nie(self):
        with mock.patch.object(geheimnis_pflege, 'nachholen', side_effect=RuntimeError('kaputt')) as m, \
                self.assertLogs(geheimnis_pflege.logger, level='WARNING') as erfasst:
            geheimnis_pflege.nach_migration()                              # wirft nicht
        m.assert_called_once()
        self.assertIn('nicht möglich', erfasst.output[0])                  # …aber der Fehler steht im Log

    def test_erneuern_stellt_um_und_entfernt_den_alten_schluessel(self):
        self.mieter.ahv_nummer = '756.1234.5678.97'
        self.mieter.save()
        alt_schluessel = self.pfad.read_text().strip()
        roh_alt = self._roh()
        n, unlesbar = geheimnis_pflege.erneuern()
        self.assertEqual((n, unlesbar), (1, []))
        neu_schluessel = self.pfad.read_text().strip()
        self.assertNotEqual(neu_schluessel, alt_schluessel)
        self.assertEqual(len(neu_schluessel.split()), 1, 'der alte Schlüssel ist aus der Datei entfernt')
        self.assertNotEqual(self._roh(), roh_alt)
        self.mieter.refresh_from_db()
        self.assertEqual(self.mieter.ahv_nummer, '756.1234.5678.97')

    def test_erneuern_behaelt_den_alten_schluessel_wenn_etwas_unlesbar_bleibt(self):
        self.mieter.ahv_nummer = '756.1234.5678.97'
        self.mieter.save()
        geheimnis.schluessel_vorhanden()
        with connection.cursor() as cur:                                   # ein fremd verschlüsselter Wert
            fremd = Fernet(Fernet.generate_key()).encrypt(b'x').decode()
            cur.execute(f'UPDATE {type(self.mieter)._meta.db_table} SET ahv_nummer = %s WHERE id = %s', [fremd, self.mieter.pk])
        n, unlesbar = geheimnis_pflege.erneuern()
        self.assertEqual(len(unlesbar), 1)
        self.assertEqual(len(self.pfad.read_text().split()), 2, 'beide Schlüssel bleiben in der Datei')

    def test_erneuern_nur_fuer_den_selbst_angelegten_schluessel(self):
        with override_settings(GEHEIMNIS_SCHLUESSEL=Fernet.generate_key().decode()):
            with self.assertRaises(geheimnis_pflege.ErneuernNichtMoeglich):
                geheimnis_pflege.erneuern()


class SeiteTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = Path(self.tmp.name) / '.geheimnis_schluessel'
        ueberschreiben = override_settings(GEHEIMNIS_AUTOSCHLUESSEL=True, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(self.pfad), **LEER)
        ueberschreiben.enable()
        self.addCleanup(ueberschreiben.disable)
        _basis_objekte()
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)

    def test_nur_der_betreiber_sieht_die_seite(self):
        team = Client()
        team.force_login(_team_user())
        self.assertEqual(team.get('/betreiber/sicherheit/').status_code, 403)
        self.assertEqual(team.post('/betreiber/sicherheit/', {'aktion': 'kopie'}).status_code, 403)
        self.assertEqual(Client().get('/betreiber/sicherheit/').status_code, 302)

    def test_seite_zeigt_den_zustand(self):
        antwort = self.c.get('/betreiber/sicherheit/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'von der Anwendung selbst angelegt')

    def test_karte_in_den_einstellungen_nur_fuer_den_betreiber(self):
        self.assertContains(self.c.get('/neu/einstellungen/'), 'href="/betreiber/"')
        team = Client()
        team.force_login(_team_user())
        self.assertNotContains(team.get('/neu/einstellungen/'), 'href="/betreiber/"')

    def test_kopie_herunterladen_ist_nicht_gecacht_und_im_logbuch(self):
        antwort = self.c.post('/betreiber/sicherheit/', {'aktion': 'kopie'})
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('attachment', antwort['Content-Disposition'])
        self.assertIn('no-store', antwort['Cache-Control'])
        schluessel = antwort.content.decode().strip()
        Fernet(schluessel.encode())
        eintrag = AktivitaetsLog.alle_organisationen.filter(aktion='Schlüsselkopie heruntergeladen').first()
        self.assertIsNotNone(eintrag)
        self.assertNotIn(schluessel, f'{eintrag.details}{eintrag.objekt}')      # nie der Schlüssel im Log

    def test_erneuern_per_knopf(self):
        geheimnis.schluessel_vorhanden()
        vorher = self.pfad.read_text()
        antwort = self.c.post('/betreiber/sicherheit/', {'aktion': 'erneuern'}, follow=True)
        self.assertNotEqual(self.pfad.read_text(), vorher)
        self.assertContains(antwort, 'Neuer Schlüssel gesetzt')
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(aktion='Schlüssel erneuert').exists())

    def test_nachholen_per_knopf(self):
        antwort = self.c.post('/betreiber/sicherheit/', {'aktion': 'nachholen'}, follow=True)
        self.assertContains(antwort, 'Werte verschlüsselt')
