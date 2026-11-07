"""Roadmap Nr. 9: Das Audit-Log ist nur anhängbar."""
import logging
from unittest import skipUnless

from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from core import log_schutz
from core.auth import log_aktion
from core.models import AktivitaetsLog
from crm.models import Organisation
from finance.db_schutz import ausnahme

NUR_POSTGRES = skipUnless(connection.vendor == 'postgresql', 'Trigger nur auf PostgreSQL')


class LogBasis(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(firma='Log AG', strasse='x', plz='8000', ort='Z')
        self.eintrag = AktivitaetsLog.alle_organisationen.create(
            organisation=self.org, aktion='Test', objekt='Max Muster', details='x')


class ModellSperreTests(LogBasis):
    def test_eintrag_aendern_ist_gesperrt(self):
        self.eintrag.details = 'anders'
        with self.assertRaises(PermissionError):
            self.eintrag.save()
        self.assertEqual(AktivitaetsLog.alle_organisationen.get(pk=self.eintrag.pk).details, 'x')

    def test_eintrag_loeschen_ist_gesperrt(self):
        with self.assertRaises(PermissionError):
            self.eintrag.delete()
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(pk=self.eintrag.pk).exists())

    def test_sammelaenderung_und_sammelloeschung_sind_gesperrt(self):
        with self.assertRaises(PermissionError):
            AktivitaetsLog.alle_organisationen.filter(pk=self.eintrag.pk).update(details='y')
        with self.assertRaises(PermissionError):
            AktivitaetsLog.alle_organisationen.filter(pk=self.eintrag.pk).delete()
        self.assertEqual(AktivitaetsLog.alle_organisationen.get(pk=self.eintrag.pk).details, 'x')

    def test_benannte_ausnahme_erlaubt_aenderung(self):
        with ausnahme('Test'):
            AktivitaetsLog.alle_organisationen.filter(pk=self.eintrag.pk).update(details='y')
        self.assertEqual(AktivitaetsLog.alle_organisationen.get(pk=self.eintrag.pk).details, 'y')

    def test_organisation_mit_protokoll_laesst_sich_nicht_loeschen(self):
        with self.assertRaises(ProtectedError):
            self.org.delete()
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(pk=self.eintrag.pk).exists())

    def test_neuer_eintrag_geht(self):
        n = AktivitaetsLog.alle_organisationen.count()
        AktivitaetsLog.alle_organisationen.create(organisation=self.org, aktion='Neu')
        self.assertEqual(AktivitaetsLog.alle_organisationen.count(), n + 1)


class FehlerNichtVerschluckt(LogBasis):
    def test_fehlschlag_wird_als_error_protokolliert(self):
        # Ohne Organisation und ohne Kontext kann der Eintrag nicht geschrieben werden.
        with self.assertLogs('core.auth', level=logging.ERROR) as erfasst:
            with _ohne_kontext():
                log_aktion(None, 'Etwas Wichtiges', 'Objekt')
        self.assertTrue(any('nicht geschrieben' in z for z in erfasst.output))


def _ohne_kontext():
    from unittest import mock
    return mock.patch('core.models.organisation_bestimmen', side_effect=RuntimeError('kein Kontext'))


@NUR_POSTGRES
class DatenbankTests(LogBasis):
    def test_trigger_ist_aktiv(self):
        self.assertTrue(log_schutz.trigger_vorhanden())

    def test_rohes_update_und_delete_scheitern(self):
        with connection.cursor() as cur:
            with self.assertRaises(Exception) as ctx, transaction.atomic():
                cur.execute('UPDATE core_aktivitaetslog SET details = %s WHERE id = %s', ['hack', self.eintrag.pk])
            self.assertIn('unveraenderlich', str(ctx.exception))
            with self.assertRaises(Exception) as ctx, transaction.atomic():
                cur.execute('DELETE FROM core_aktivitaetslog WHERE id = %s', [self.eintrag.pk])
            self.assertIn('nicht geloescht', str(ctx.exception))

    def test_benutzerbezug_leeren_bleibt_erlaubt(self):
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user('logger', password='x' * 12)
        e = AktivitaetsLog.alle_organisationen.create(organisation=self.org, aktion='Mit User', benutzer=u)
        u.delete()
        e.refresh_from_db()
        self.assertIsNone(e.benutzer_id)
