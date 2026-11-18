"""Row-Level-Security: die Probe (jede Datenbank) und die Regeln samt Sitzungsvariable (nur PostgreSQL)."""
from decimal import Decimal
from unittest import skipUnless

from django.core.cache import cache
from django.db import connection, transaction
from django.db.models.signals import post_init
from django.test import TestCase, override_settings

from core import rls
from core.models import SicherheitsEreignis
from core.tenancy import organisation_kontext
from finance.models import Buchungskonto

from crm.models import Organisation

NUR_POSTGRES = skipUnless(connection.vendor == 'postgresql', 'Row-Level-Security gibt es nur auf PostgreSQL.')


def _sofort():
    """Im Test laufen alle Schritte in EINER Transaktion: Aufgeschobene Fremdschlüssel-Prüfungen der eben angelegten
    Zeilen müssen durch sein, bevor PostgreSQL ein `ALTER TABLE` zulässt. Im Betrieb läuft der Befehl für sich."""
    with connection.cursor() as c:
        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        c.execute('SET CONSTRAINTS ALL DEFERRED')


def _einrichten():
    _sofort()
    return rls.einrichten()


def _entfernen():
    _sofort()
    return rls.entfernen()


def _konto(org, nummer='1020'):
    with organisation_kontext(org):
        return Buchungskonto.objects.create(nummer=nummer, bezeichnung=f'Konto {org.firma}', typ='aktiv')


class GrundlagenTests(TestCase):
    def test_alle_finanzmodelle_mit_organisation_sind_erfasst(self):
        tabellen = rls.tabellen()
        self.assertIn('core_buchung', tabellen)
        self.assertGreaterEqual(len(tabellen), 20)
        self.assertEqual(len(tabellen), len(set(tabellen)))

    def test_vorgabe_ist_aus_und_ein_unsinniger_wert_auch(self):
        self.assertEqual(rls.modus(), 'aus')
        with override_settings(RLS_MODUS='quatsch'):
            self.assertEqual(rls.modus(), 'aus')

    def test_die_befehle_erlauben_das_schreiben_ausdruecklich(self):
        """Ohne eigene Regeln je Schreibbefehl wiese PostgreSQL bei eingeschalteter RLS jedes Schreiben ab."""
        befehle = ' '.join(rls.sql_einrichten('core_buchung'))
        for teil in ('FOR SELECT', 'FOR INSERT', 'FOR UPDATE', 'FOR DELETE', 'FORCE ROW LEVEL SECURITY'):
            self.assertIn(teil, befehle)


class ProbeTests(TestCase):
    def setUp(self):
        self.a = Organisation.objects.create(firma='A AG')
        self.b = Organisation.objects.create(firma='B AG')
        self.konto_b = _konto(self.b)
        cache.clear()
        post_init.connect(rls._probe, sender=Buchungskonto, dispatch_uid='rls_probe_test')
        self.addCleanup(post_init.disconnect, rls._probe, sender=Buchungskonto, dispatch_uid='rls_probe_test')

    def test_eine_fremde_zeile_im_kontext_wird_protokolliert(self):
        with organisation_kontext(self.a):
            Buchungskonto.alle_organisationen.get(pk=self.konto_b.pk)
        ereignis = SicherheitsEreignis.objects.get(aktion=rls.AKTION_PROBE)
        self.assertEqual(ereignis.objekt, 'finance.Buchungskonto')
        self.assertIn(f'Verwaltung {self.b.pk}', ereignis.details)
        self.assertIn('test_rls.py', ereignis.details)          # die Stelle im eigenen Code steht dabei

    def test_die_eigene_zeile_und_ein_lauf_ohne_kontext_sind_kein_befund(self):
        with organisation_kontext(self.b):
            Buchungskonto.objects.get(pk=self.konto_b.pk)
        Buchungskonto.alle_organisationen.get(pk=self.konto_b.pk)      # ohne Kontext: Systemlauf
        self.assertFalse(SicherheitsEreignis.objects.filter(aktion=rls.AKTION_PROBE).exists())

    def test_dieselbe_stelle_meldet_nur_einmal(self):
        with organisation_kontext(self.a):
            for _i in range(3):
                Buchungskonto.alle_organisationen.get(pk=self.konto_b.pk)
        self.assertEqual(SicherheitsEreignis.objects.filter(aktion=rls.AKTION_PROBE).count(), 1)
        self.assertEqual(rls.befunde_seit(), 1)

    def test_die_probe_stoert_das_laden_nie(self):
        from unittest import mock
        with mock.patch('core.models.SicherheitsEreignis.objects') as m:
            m.create.side_effect = RuntimeError('db weg')
            with organisation_kontext(self.a):
                konto = Buchungskonto.alle_organisationen.get(pk=self.konto_b.pk)
        self.assertEqual(konto.pk, self.konto_b.pk)

    def test_der_betreiber_sieht_die_zahl_im_probemodus(self):
        from core.services import datenpflege
        from django.utils import timezone
        with organisation_kontext(self.a):
            Buchungskonto.alle_organisationen.get(pk=self.konto_b.pk)
        with override_settings(RLS_MODUS='probe'):
            self.assertTrue(any('RLS-Probe: 1 Befund' in a for a in datenpflege.faellig(timezone.localdate())))
        self.assertFalse(any('RLS-Probe' in a for a in datenpflege.faellig(timezone.localdate())))


@NUR_POSTGRES
class RegelTests(TestCase):
    """Die Regeln wirken nur für eine Rolle ohne Superuser-Recht: Der Test wechselt in eine solche (`SET ROLE`)."""
    ROLLE = 'rls_test_rolle'

    def setUp(self):
        self.a = Organisation.objects.create(firma='A AG')
        self.b = Organisation.objects.create(firma='B AG')
        self.konto_a = _konto(self.a, '1020')
        self.konto_b = _konto(self.b, '1021')
        _einrichten()
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [self.ROLLE])
            if c.fetchone() is None:
                c.execute(f'CREATE ROLE {self.ROLLE} NOLOGIN')
            c.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {self.ROLLE}')
            c.execute(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {self.ROLLE}')

    def _sichtbar(self, organisation_id):
        """Die Konten-IDs, die die eingeschränkte Rolle mit dieser Sitzungsvariable sieht."""
        with transaction.atomic(), connection.cursor() as c:
            c.execute(f'SET LOCAL ROLE {self.ROLLE}')
            c.execute('SELECT set_config(%s, %s, true)', [rls.VARIABLE, organisation_id])
            c.execute('SELECT id FROM core_buchungskonto ORDER BY id')
            return [z[0] for z in c.fetchall()]

    def test_mit_gesetzter_verwaltung_sind_nur_die_eigenen_zeilen_sichtbar(self):
        self.assertEqual(self._sichtbar(str(self.a.pk)), [self.konto_a.pk])
        self.assertEqual(self._sichtbar(str(self.b.pk)), [self.konto_b.pk])

    def test_ohne_gesetzte_verwaltung_ist_alles_sichtbar(self):
        """Systemläufe, Migrationen, Sicherungen: bewusst offen."""
        self.assertEqual(self._sichtbar(''), sorted([self.konto_a.pk, self.konto_b.pk]))

    def test_schreiben_bleibt_moeglich(self):
        with transaction.atomic(), connection.cursor() as c:
            c.execute(f'SET LOCAL ROLE {self.ROLLE}')
            c.execute('SELECT set_config(%s, %s, true)', [rls.VARIABLE, str(self.a.pk)])
            c.execute('UPDATE core_buchungskonto SET bezeichnung = %s WHERE id = %s', ['neu', self.konto_a.pk])
            self.assertEqual(c.rowcount, 1)
            # Eine fremde Zeile ist für das UPDATE unsichtbar: nichts geändert, kein Fehler.
            c.execute('UPDATE core_buchungskonto SET bezeichnung = %s WHERE id = %s', ['x', self.konto_b.pk])
            self.assertEqual(c.rowcount, 0)

    def test_status_und_entfernen(self):
        s = rls.status()
        self.assertTrue(all(t['ein'] and t['erzwungen'] and t['regeln'] == 4 for t in s['tabellen']))
        _entfernen()
        s = rls.status()
        self.assertFalse(any(t['ein'] or t['regeln'] for t in s['tabellen']))
        self.assertEqual(self._sichtbar(str(self.a.pk)), sorted([self.konto_a.pk, self.konto_b.pk]))

    def test_einrichten_ist_wiederholbar(self):
        _einrichten()
        self.assertEqual(self._sichtbar(str(self.a.pk)), [self.konto_a.pk])


@NUR_POSTGRES
class AbgleichTests(TestCase):
    """Die Sitzungsvariable folgt dem Mandantenkontext — auch über zurückgerollte Sicherungspunkte hinweg."""

    def setUp(self):
        self.a = Organisation.objects.create(firma='A AG')
        self.b = Organisation.objects.create(firma='B AG')
        self.abgleich = rls._Abgleich(connection)
        connection.execute_wrappers.append(self.abgleich)
        self.addCleanup(connection.execute_wrappers.remove, self.abgleich)

    def _variable(self):
        with connection.cursor() as c:
            c.execute('SELECT current_setting(%s, true)', [rls.VARIABLE])
            return c.fetchone()[0] or ''

    def test_die_variable_folgt_dem_kontext_und_wird_wieder_leer(self):
        with organisation_kontext(self.a):
            self.assertEqual(self._variable(), str(self.a.pk))
            with organisation_kontext(self.b):
                self.assertEqual(self._variable(), str(self.b.pk))
            self.assertEqual(self._variable(), str(self.a.pk))
        self.assertEqual(self._variable(), '')

    def test_ein_zurueckgerollter_sicherungspunkt_laesst_keinen_falschen_stand_zurueck(self):
        with organisation_kontext(self.a):
            self.assertEqual(self._variable(), str(self.a.pk))
            try:
                with transaction.atomic():
                    with organisation_kontext(self.b):
                        self.assertEqual(self._variable(), str(self.b.pk))
                    raise RuntimeError('zurückrollen')
            except RuntimeError:
                pass
            self.assertEqual(self._variable(), str(self.a.pk))

    def test_ohne_aenderung_wird_nicht_erneut_gesendet(self):
        from unittest import mock
        with organisation_kontext(self.a):
            self._variable()
            stand = self.abgleich.stand
            with mock.patch.object(rls._Abgleich, '__call__', wraps=self.abgleich.__call__):
                Buchungskonto.objects.count()
            self.assertEqual(self.abgleich.stand, stand)

    def test_zusammenspiel_die_orm_abfrage_sieht_mit_regeln_nur_die_eigene_verwaltung(self):
        """Regeln + Abgleich + eingeschränkte Rolle: Selbst der Weg an der Isolation vorbei liest nur Eigenes."""
        konto_a, konto_b = _konto(self.a, '1020'), _konto(self.b, '1021')
        _einrichten()
        rolle = RegelTests.ROLLE
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [rolle])
            if c.fetchone() is None:
                c.execute(f'CREATE ROLE {rolle} NOLOGIN')
            c.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {rolle}')
        with transaction.atomic():
            with connection.cursor() as c:
                c.execute(f'SET LOCAL ROLE {rolle}')
            with organisation_kontext(self.a):
                gesehen = set(Buchungskonto.alle_organisationen.values_list('pk', flat=True))
            ohne = set(Buchungskonto.alle_organisationen.values_list('pk', flat=True))
        self.assertEqual(gesehen, {konto_a.pk})
        self.assertEqual(ohne, {konto_a.pk, konto_b.pk})
