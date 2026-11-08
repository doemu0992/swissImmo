"""Das TOTP-Geheimnis steht verschlüsselt in der Datenbank; Altbestand im Klartext wird nachgeholt."""
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings

from core.models import ZweiterFaktor
from core.services import geheimnis, geheimnis_pflege, totp

from ._helfer import _team_user

LEER = {'GEHEIMNIS_SCHLUESSEL': '', 'IMAP_SCHLUESSEL': ''}


class ZweiterFaktorGeheimnisTests(TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pfad = Path(tmp.name) / '.geheimnis_schluessel'
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for n in (geheimnis.NEUER_NAME, geheimnis.UMGEBUNGSNAME, geheimnis.DATEINAME):
            os.environ.pop(n, None)
        ue = override_settings(GEHEIMNIS_AUTOSCHLUESSEL=True, GEHEIMNIS_AUTOSCHLUESSEL_DATEI=str(pfad), **LEER)
        ue.enable()
        self.addCleanup(ue.disable)
        self.klar = totp.geheimnis_erzeugen()
        self.faktor = ZweiterFaktor.objects.create(benutzer=_team_user(), geheimnis=self.klar)

    def _roh(self):
        with connection.cursor() as cur:
            cur.execute(f'SELECT geheimnis FROM {ZweiterFaktor._meta.db_table} WHERE id = %s', [self.faktor.pk])
            return cur.fetchone()[0]

    def test_in_der_datenbank_steht_kein_klartext_und_das_modell_liest_ihn_zurueck(self):
        self.assertNotIn(self.klar, self._roh())
        self.faktor.refresh_from_db()
        self.assertEqual(self.faktor.geheimnis, self.klar)
        self.assertTrue(self.faktor.pruefen(totp.code(self.klar)))        # der Code stimmt weiterhin

    def test_altbestand_im_klartext_wird_nachgeholt_und_bleibt_nutzbar(self):
        with connection.cursor() as cur:
            cur.execute(f'UPDATE {ZweiterFaktor._meta.db_table} SET geheimnis = %s WHERE id = %s',
                        [self.klar, self.faktor.pk])
        self.assertEqual(self._roh(), self.klar)
        geheimnis_pflege.nachholen()
        self.assertNotIn(self.klar, self._roh())
        self.faktor.refresh_from_db()
        self.assertEqual(self.faktor.geheimnis, self.klar)
