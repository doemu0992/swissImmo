"""Hash-Kette im Audit-Log (Roadmap 2.3): fortlaufend, prüfbar, Manipulation fällt auf.

Gegenproben: In `AktivitaetsLog._siegeln_und_speichern` den Hash des Vorgängers weglassen -> `test_kette_ist_verkettet` rot;
in `log_kette.pruefen` die Lückenprüfung entfernen -> `test_geloeschter_eintrag_faellt_auf` rot; die Freitexte (`details`) in den
Hash aufnehmen -> `test_anonymisierung_bricht_die_kette_nicht` rot.
"""
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core import log_kette
from core.tenancy import organisation_kontext
from core.tests._parallel import NUR_POSTGRES
from core.tests._isolation import MandantenFixture


def _schreibe(org, n, aktion='Test'):
    from core.models import AktivitaetsLog
    with organisation_kontext(org):
        return [AktivitaetsLog.objects.create(aktion=f'{aktion} {i}', objekt='X', details='Name Muster', kategorie='sonstiges')
                for i in range(n)]


def _aendern(org, pk, **felder):
    """Eine Änderung am Eintrag, wie sie nur am Schutz vorbei möglich ist (Trigger/Modell); deshalb unter der benannten Ausnahme."""
    from core.models import AktivitaetsLog
    from finance.db_schutz import ausnahme
    with ausnahme('Test: Manipulation simulieren'):
        AktivitaetsLog.alle_organisationen.filter(pk=pk).update(**felder)


class KetteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import AktivitaetsLog
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        AktivitaetsLog.alle_organisationen.all()          # Fixture schreibt evtl. eigene Einträge: die Kette gilt für alle

    def test_nummern_laufen_je_verwaltung_fortlaufend(self):
        a = _schreibe(self.a.organisation, 3)
        b = _schreibe(self.b.organisation, 2)
        nr_a = [e.kette_nr for e in a]
        self.assertEqual(nr_a, list(range(nr_a[0], nr_a[0] + 3)))
        self.assertEqual(b[1].kette_nr, b[0].kette_nr + 1)

    def test_kette_ist_verkettet(self):
        e1, e2 = _schreibe(self.a.organisation, 2)
        self.assertEqual(e2.kette_hash, log_kette.kettenhash(e2, e1.kette_hash))
        self.assertNotEqual(e2.kette_hash, log_kette.kettenhash(e2, log_kette.NULLHASH))
        self.assertEqual(len(e2.kette_hash), 64)

    def test_unveraenderte_kette_ist_in_ordnung(self):
        _schreibe(self.a.organisation, 4)
        _schreibe(self.b.organisation, 2)
        geprueft, befunde, koepfe = log_kette.pruefen()
        self.assertEqual(befunde, [])
        self.assertGreaterEqual(geprueft, 6)
        self.assertIn(self.a.organisation.pk, koepfe)

    def test_geaenderte_aktion_faellt_auf(self):
        e = _schreibe(self.a.organisation, 3)[1]
        _aendern(self.a.organisation, e.pk, aktion='Gefälscht')
        befunde = log_kette.pruefen()[1]
        self.assertTrue(any(f'#{e.pk}' in b and 'Hash' in b for b in befunde), befunde)

    def test_geaenderter_zeitpunkt_faellt_auf(self):
        e = _schreibe(self.a.organisation, 3)[1]
        _aendern(self.a.organisation, e.pk, zeitpunkt=e.zeitpunkt - timedelta(days=30))
        self.assertTrue(log_kette.pruefen()[1])

    def test_geloeschter_eintrag_faellt_auf(self):
        from core.models import AktivitaetsLog
        from finance.db_schutz import ausnahme
        e = _schreibe(self.a.organisation, 4)[1]
        with ausnahme('Test: Löschung simulieren'):
            AktivitaetsLog.alle_organisationen.filter(pk=e.pk).delete()
        befunde = log_kette.pruefen()[1]
        self.assertTrue(any('Lücke' in b for b in befunde), befunde)

    def test_eingeschleuster_eintrag_ohne_kettenglied_faellt_auf(self):
        from core.models import AktivitaetsLog
        from finance.db_schutz import ausnahme
        _schreibe(self.a.organisation, 2)
        with ausnahme('Test: Einschleusen simulieren'):
            AktivitaetsLog.alle_organisationen.bulk_create([AktivitaetsLog(
                organisation=self.a.organisation, aktion='Eingeschleust', zeitpunkt=timezone.now() + timedelta(seconds=1))])
        befunde = log_kette.pruefen()[1]
        self.assertTrue(any('ausserhalb der Kette' in b for b in befunde), befunde)

    def test_anonymisierung_bricht_die_kette_nicht(self):
        """Die DSG-Anonymisierung schwärzt Objekt und Details: Sie sind nicht im Hash, die Kette bleibt gültig."""
        e = _schreibe(self.a.organisation, 3)[1]
        _aendern(self.a.organisation, e.pk, details='[anonymisiert]', objekt='[anonymisiert]')
        self.assertEqual(log_kette.pruefen()[1], [])

    def test_konto_loeschen_leert_den_benutzer_ohne_die_kette_zu_brechen(self):
        from core.models import AktivitaetsLog
        from core.tests._helfer import _team_user
        u = _team_user('Verwaltung')
        with organisation_kontext(self.a.organisation):
            AktivitaetsLog.objects.create(aktion='Mit Benutzer', benutzer=u)
        u.delete()
        self.assertEqual(log_kette.pruefen()[1], [])

    def test_zeitpunkt_ueberlebt_den_weg_durch_die_datenbank(self):
        """Der Hash wird aus dem gespeicherten Zeitpunkt wieder gerechnet: Mikrosekunden und Zeitzone müssen stimmen."""
        from core.models import AktivitaetsLog
        e = _schreibe(self.a.organisation, 1)[0]
        neu = AktivitaetsLog.alle_organisationen.get(pk=e.pk)
        self.assertEqual(neu.zeitpunkt, e.zeitpunkt)
        self.assertEqual(log_kette.pruefen()[1], [])


class BestandSiegelnTests(TestCase):
    """Die Migration gibt dem Altbestand (Einträge ohne Kettenglied) Nummer und Hash, je Verwaltung nach Zeitpunkt."""

    def test_altbestand_wird_gesiegelt_und_die_kette_ist_danach_gueltig(self):
        import importlib

        from django.apps import apps

        from core.models import AktivitaetsLog
        from finance.db_schutz import ausnahme
        a = MandantenFixture('A', '8000', 'Zürich')
        jetzt = timezone.now()
        with ausnahme('Test: Altbestand ohne Kette'):
            AktivitaetsLog.alle_organisationen.filter(organisation=a.organisation).update(kette_nr=None, kette_hash='')
            AktivitaetsLog.alle_organisationen.bulk_create([
                AktivitaetsLog(organisation=a.organisation, aktion=f'Alt {i}', zeitpunkt=jetzt - timedelta(days=10 - i))
                for i in range(5)])
        modul = importlib.import_module('core.migrations.0022_audit_log_hash_kette')

        class _Editor:
            connection = connection
        modul._bestand_siegeln(apps, _Editor)
        eintraege = list(AktivitaetsLog.alle_organisationen.filter(organisation=a.organisation).order_by('kette_nr'))
        self.assertEqual([e.kette_nr for e in eintraege], list(range(1, len(eintraege) + 1)))
        self.assertEqual(log_kette.pruefen()[1], [])
        alt = [e for e in eintraege if e.aktion.startswith('Alt ')]
        self.assertEqual([e.aktion for e in alt], [f'Alt {i}' for i in range(5)])         # Reihenfolge nach Zeitpunkt


class PruefbefehlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_befehl_meldet_ordnung_und_fehler(self):
        e = _schreibe(self.a.organisation, 3)[1]
        out = io.StringIO()
        call_command('log_kette_pruefen', stdout=out)
        self.assertIn('Hash-Kette in Ordnung', out.getvalue())
        _aendern(self.a.organisation, e.pk, aktion='Gefälscht')
        with self.assertRaises(CommandError):
            call_command('log_kette_pruefen', stdout=io.StringIO(), stderr=io.StringIO())

    def test_anker_entdeckt_eine_neu_berechnete_kette(self):
        """Wer die ganze Kette konsistent neu rechnet, besteht die einfache Prüfung, aber nicht den Abgleich mit dem Anker."""
        from core.models import AktivitaetsLog
        e = _schreibe(self.a.organisation, 3)
        with tempfile.TemporaryDirectory() as ordner:
            call_command('log_kette_anker', ziel=ordner, stdout=io.StringIO())
            datei = next(Path(ordner).glob('anker-*.jsonl'))
            call_command('log_kette_pruefen', anker=str(datei), stdout=io.StringIO())          # unverändert: in Ordnung
            # Angreifer ändert die Aktion von Nr. 2 UND rechnet alle folgenden Hashes neu
            _aendern(self.a.organisation, e[1].pk, aktion='Gefälscht')
            vorher = e[0].kette_hash
            for eintrag in AktivitaetsLog.alle_organisationen.filter(organisation=self.a.organisation,
                                                                      kette_nr__gte=e[1].kette_nr).order_by('kette_nr'):
                h = log_kette.kettenhash(eintrag, vorher)
                _aendern(self.a.organisation, eintrag.pk, kette_hash=h)
                vorher = h
            self.assertEqual(log_kette.pruefen()[1], [])                                       # einfache Prüfung getäuscht
            with self.assertRaises(CommandError):
                call_command('log_kette_pruefen', anker=str(datei), stdout=io.StringIO(), stderr=io.StringIO())

    def test_anker_wird_bei_gebrochener_kette_nicht_abgelegt(self):
        e = _schreibe(self.a.organisation, 3)[1]
        _aendern(self.a.organisation, e.pk, aktion='Gefälscht')
        with tempfile.TemporaryDirectory() as ordner, self.assertRaises(CommandError):
            call_command('log_kette_anker', ziel=ordner, stdout=io.StringIO(), stderr=io.StringIO())

    def test_anker_datei_enthaelt_kopf_je_verwaltung(self):
        _schreibe(self.a.organisation, 2)
        with tempfile.TemporaryDirectory() as ordner:
            call_command('log_kette_anker', ziel=ordner, stdout=io.StringIO())
            datei = next(Path(ordner).glob('anker-*.jsonl'))
            zeilen = [json.loads(z) for z in datei.read_text().splitlines()]
        self.assertTrue(any(z['organisation'] == self.a.organisation.pk for z in zeilen))
        self.assertTrue(all(len(z['kette_hash']) == 64 for z in zeilen))


class ParallelKetteTests(TransactionTestCase):
    """Gleichzeitige Einträge derselben Verwaltung ergeben eine lückenlose, gültige Kette (echte Threads, nur PostgreSQL)."""

    @NUR_POSTGRES
    def test_parallele_eintraege_bleiben_eine_kette(self):
        from core.models import AktivitaetsLog
        from core.tests._parallel import parallel
        a = MandantenFixture('C', '8000', 'Zürich')
        org = a.organisation

        def schreiben(i):
            with organisation_kontext(org):
                for k in range(5):
                    AktivitaetsLog.objects.create(aktion=f'Parallel {i}-{k}', kategorie='sonstiges')
            return True
        ergebnisse = parallel(4, schreiben)
        abstuerze = [e for e in ergebnisse if isinstance(e, BaseException)]
        self.assertEqual(abstuerze, [], abstuerze)
        nummern = sorted(AktivitaetsLog.alle_organisationen.filter(organisation=org, aktion__startswith='Parallel')
                         .values_list('kette_nr', flat=True))
        self.assertEqual(len(nummern), 20)
        self.assertEqual(len(set(nummern)), 20)                      # keine doppelte Nummer
        self.assertEqual(log_kette.pruefen(org.pk)[1], [])          # und die Kette stimmt
