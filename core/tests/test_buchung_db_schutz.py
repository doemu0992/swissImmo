"""Buchungen sind auch für die Datenbank unveränderlich (Etappe 2: FIN-15/SICH-06).

Etappe 0 schloss die Wege durch Django (Instanz, QuerySet). Offen blieben
`_base_manager`, rohes SQL, fremde Skripte und die Kaskade einer Organisation.
Jetzt gilt:

* `Buchung._base_manager` trägt dieselben Sperren wie `objects` (überall).
* Auf PostgreSQL verweigert ein Trigger UPDATE/DELETE ausser den drei erlaubten
  Nachträgen; die benannte Ausnahme öffnet ihn nur für ihre Transaktion.
* Teilindizes: ein Original wird nur einmal storniert, eine Bank-Transaktion nur
  einmal verbucht (überall, auch SQLite).

Gegenprobe (28.10.2026, Schlussbericht): Trigger entfernt -> die `Trigger`-Tests
werden rot; `base_manager_name` entfernt -> `test_basis_manager_*` rot;
Indizes entfernt -> `EindeutigkeitTests` rot.
"""
from datetime import date
from decimal import Decimal
from unittest import skipUnless

from django.db import IntegrityError, connection, transaction
from django.db.models import QuerySet
from django.db.utils import DatabaseError
from django.test import TestCase

from core.tests._parallel import NUR_POSTGRES
from core.tests.test_buchung_unveraenderlich import UnveraenderlichBasis

TABELLE = 'core_buchung'


def _sql(anweisung, params=()):
    with connection.cursor() as cur:
        cur.execute(anweisung, params)
        return cur.rowcount


class BasisManagerTests(UnveraenderlichBasis):
    """`_base_manager` war ein gewöhnlicher Manager: update/delete liefen ungeprüft durch."""

    def test_basis_manager_update_und_delete_sind_gesperrt(self):
        from finance.models import Buchung
        with self.assertRaises(PermissionError):
            Buchung._base_manager.filter(pk=self.b.pk).update(betrag=Decimal('1.00'))
        with self.assertRaises(PermissionError):
            Buchung._base_manager.filter(pk=self.b.pk).delete()
        with self.assertRaises(PermissionError):
            Buchung._base_manager.all().bulk_create([])
        self.assertEqual(self.neu_lesen().betrag, Decimal('1500.00'))

    def test_der_basis_manager_ist_weiter_ungefiltert(self):
        """Django braucht ihn für Rückbezüge und `refresh_from_db`: ohne Mandantenkontext lesbar."""
        from finance.models import Buchung
        self.assertTrue(Buchung._base_manager.filter(pk=self.b.pk).exists())


@NUR_POSTGRES
class TriggerTests(UnveraenderlichBasis):
    """Rohes SQL, wie es ein Skript oder eine fremde Verbindung schickt."""

    def test_trigger_ist_installiert(self):
        from finance.db_schutz import trigger_vorhanden
        self.assertTrue(trigger_vorhanden())

    def _abgewiesen(self, anweisung, params=()):
        with self.assertRaises(DatabaseError), transaction.atomic():
            _sql(anweisung, params)

    def test_sql_update_der_geschuetzten_spalten_wird_abgewiesen(self):
        for spalte, wert in (('betrag', '1.00'), ('beleg_text', 'anders'), ('datum', '2020-01-01'),
                             ('ist_storno', True), ('beleg_nr', 9999)):
            with self.subTest(spalte=spalte):
                self._abgewiesen(f'UPDATE {TABELLE} SET {spalte} = %s WHERE id = %s', [wert, self.b.pk])
        self._abgewiesen(f'UPDATE {TABELLE} SET soll_konto_id = haben_konto_id WHERE id = %s', [self.b.pk])
        b = self.neu_lesen()
        self.assertEqual((b.betrag, b.beleg_text, b.datum), (Decimal('1500.00'), 'Miete März', date(2026, 3, 1)))

    def test_sql_delete_wird_abgewiesen(self):
        self._abgewiesen(f'DELETE FROM {TABELLE} WHERE id = %s', [self.b.pk])
        self._abgewiesen(f'DELETE FROM {TABELLE}')
        self.assertEqual(self.neu_lesen().pk, self.b.pk)

    def test_der_trigger_haelt_auch_den_basis_manager_am_orm_vorbei(self):
        """Django-Interna (`_update` des Speicherns, Kollektor der Kaskade) laufen am
        QuerySet-Schutz vorbei; der Trigger fängt sie."""
        from finance.models import Buchung
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuerySet.update(Buchung._base_manager.filter(pk=self.b.pk), betrag=Decimal('1'))
        with self.assertRaises(DatabaseError), transaction.atomic():
            Buchung._base_manager.filter(pk=self.b.pk)._raw_delete(using='default')
        self.assertEqual(self.neu_lesen().betrag, Decimal('1500.00'))

    def test_erlaubte_nachtraege_gehen_durch(self):
        """Storno-Marke einmal setzen, Verknüpfungen nachtragen, Ersteller bei Kontolöschung leeren."""
        from finance.models import DebitorenRechnung
        r = DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='R', betrag=Decimal('10'),
                                             datum=date(2026, 3, 1), status='offen')
        self.assertEqual(_sql(f'UPDATE {TABELLE} SET debitoren_rechnung_id = %s WHERE id = %s', [r.pk, self.b.pk]), 1)
        self.assertEqual(_sql(f'UPDATE {TABELLE} SET storniert_am = now() WHERE id = %s', [self.b.pk]), 1)
        self.assertEqual(self.neu_lesen().debitoren_rechnung_id, r.pk)

    def test_storno_marke_laesst_sich_nicht_zuruecknehmen_oder_aendern(self):
        _sql(f'UPDATE {TABELLE} SET storniert_am = now() WHERE id = %s', [self.b.pk])
        self._abgewiesen(f'UPDATE {TABELLE} SET storniert_am = NULL WHERE id = %s', [self.b.pk])
        self._abgewiesen(f"UPDATE {TABELLE} SET storniert_am = now() + interval '1 day' WHERE id = %s", [self.b.pk])

    def test_ersteller_nur_auf_null_nie_umschreiben(self):
        from core.tests._helfer import _team_user
        u1, u2 = _team_user('Verwaltung'), _team_user('Inhaber')
        # Einen Ersteller gibt es erst mit der Ausnahme (Testaufbau); danach gilt die Regel.
        from finance.models import Buchung
        Buchung.objects.filter(pk=self.b.pk).ausnahme_aendern('Testaufbau Ersteller', erstellt_von=u1)
        self._abgewiesen(f'UPDATE {TABELLE} SET erstellt_von_id = %s WHERE id = %s', [u2.pk, self.b.pk])
        self.assertEqual(_sql(f'UPDATE {TABELLE} SET erstellt_von_id = NULL WHERE id = %s', [self.b.pk]), 1)
        self._abgewiesen(f'UPDATE {TABELLE} SET erstellt_von_id = %s WHERE id = %s', [u1.pk, self.b.pk])

    def test_konto_loeschen_leert_den_ersteller_ohne_ausnahme(self):
        """`on_delete=SET_NULL` am Ersteller: das Löschen des Kontos darf nicht am Trigger scheitern."""
        from core.tests._helfer import _team_user
        from finance.models import Buchung
        u = _team_user('Verwaltung')
        Buchung.objects.filter(pk=self.b.pk).ausnahme_aendern('Testaufbau Ersteller', erstellt_von=u)
        u.delete()
        self.assertIsNone(self.neu_lesen().erstellt_von_id)

    def test_ausnahme_oeffnet_nur_fuer_ihre_transaktion_und_schliesst_wieder(self):
        """Der Test läuft selbst in EINER Transaktion: nach der Ausnahme muss der Schutz
        sofort wieder gelten, nicht erst nach deren Ende."""
        from finance.models import Buchung
        Buchung.objects.filter(pk=self.b.pk).ausnahme_aendern('Reparatur Import', betrag=Decimal('3.00'))
        self.assertEqual(self.neu_lesen().betrag, Decimal('3.00'))
        self._abgewiesen(f'UPDATE {TABELLE} SET betrag = 4 WHERE id = %s', [self.b.pk])
        self._abgewiesen(f'DELETE FROM {TABELLE} WHERE id = %s', [self.b.pk])
        with connection.cursor() as cur:
            cur.execute("SELECT current_setting('swissimmo.buchung_ausnahme', true)")
            self.assertIn(cur.fetchone()[0], (None, ''))

    def test_ausnahme_loeschen_und_force_gehen_durch_den_trigger(self):
        from finance.booking import buche
        from finance.models import Buchung
        zweite = buche('1020', '3000', Decimal('5.00'), 'Zweite', datum=date(2026, 3, 2))
        Buchung.objects.filter(pk=self.b.pk).ausnahme_loeschen('Testaufbau')
        self.assertFalse(Buchung.objects.filter(pk=self.b.pk).exists())
        zweite.delete(force='Testaufbau force')
        self.assertFalse(Buchung._base_manager.filter(pk=zweite.pk).exists())

    def test_eine_fehlgeschlagene_ausnahme_laesst_nichts_offen(self):
        """Wirft der Block, rollt auch die Variable zurück."""
        from finance.db_schutz import ausnahme
        with self.assertRaises(RuntimeError), ausnahme('Probe'):
            raise RuntimeError('Abbruch')
        self._abgewiesen(f'DELETE FROM {TABELLE} WHERE id = %s', [self.b.pk])

    def test_gesamte_zeile_wird_verglichen_auch_nach_ausbau_per_json(self):
        """Der Trigger nimmt nur die erlaubten Spalten aus: eine künftige Spalte wäre gesperrt."""
        with connection.cursor() as cur:
            cur.execute("SELECT prosrc FROM pg_proc WHERE proname = 'swissimmo_buchung_schutz'")
            quelltext = cur.fetchone()[0]
        self.assertIn('to_jsonb(NEW) - erlaubt', quelltext)


class EindeutigkeitTests(UnveraenderlichBasis):

    def _storno_zu(self, original):
        from finance.models import Buchung
        return Buchung.objects.create(
            datum=date(2026, 4, 1), beleg_text='Storno', soll_konto=original.haben_konto,
            haben_konto=original.soll_konto, betrag=original.betrag, ist_storno=True, storno_von=original)

    def test_ein_original_hat_hoechstens_ein_storno(self):
        self._storno_zu(self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._storno_zu(self.b)

    def test_stornos_verschiedener_originale_sind_unabhaengig(self):
        from finance.booking import buche
        zweite = buche('1020', '3000', Decimal('5.00'), 'Zweite', datum=date(2026, 3, 2))
        self._storno_zu(self.b)
        self._storno_zu(zweite)

    def test_bankreferenz_nur_einmal_je_organisation(self):
        from finance.models import Zahlungseingang
        Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'), datum_eingang=date(2026, 3, 1),
                                       bank_referenz='TX-1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                           datum_eingang=date(2026, 3, 1), bank_referenz='TX-1')

    def test_leere_und_stornierte_bankreferenz_zaehlt_nicht(self):
        from finance.models import Zahlungseingang
        for _ in range(2):
            Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                           datum_eingang=date(2026, 3, 1), bank_referenz='')
        alt = Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                             datum_eingang=date(2026, 3, 1), bank_referenz='TX-2',
                                             status='storniert')
        Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                       datum_eingang=date(2026, 3, 1), bank_referenz='TX-2')
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='TX-2').count(), 2)
        self.assertEqual(alt.status, 'storniert')


@NUR_POSTGRES
class NachziehenTests(UnveraenderlichBasis):
    """Ein Altbestand mit Dubletten darf die Migration nicht brechen."""

    def test_bestand_mit_dubletten_ueberspringt_den_index_und_meldet_ihn(self):
        from finance.db_schutz import eindeutigkeiten_nachziehen
        from finance.models import Zahlungseingang
        with connection.cursor() as cur:
            cur.execute('DROP INDEX uniq_bankreferenz_je_organisation')
        for _ in range(2):
            Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                           datum_eingang=date(2026, 3, 1), bank_referenz='ALT-1')
        with connection.schema_editor() as editor, self.assertLogs('finance.db_schutz', level='ERROR'):
            uebersprungen = eindeutigkeiten_nachziehen(editor)
        self.assertEqual([n for n, _d in uebersprungen], ['uniq_bankreferenz_je_organisation'])
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'uniq_bankreferenz_je_organisation'")
            self.assertIsNone(cur.fetchone())

    def test_sauberer_bestand_bekommt_den_index_zurueck(self):
        from finance.db_schutz import eindeutigkeiten_nachziehen
        with connection.cursor() as cur:
            cur.execute('SET CONSTRAINTS ALL IMMEDIATE')       # sonst «pending trigger events» beim CREATE INDEX
            cur.execute('DROP INDEX uniq_storno_je_original')
        with connection.schema_editor() as editor:
            self.assertEqual(eindeutigkeiten_nachziehen(editor), [])
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'uniq_storno_je_original'")
            self.assertIsNotNone(cur.fetchone())


class SqliteBleibtManagerSchutzTests(TestCase):
    @skipUnless(connection.vendor == 'sqlite', 'nur SQLite')
    def test_ohne_postgresql_gibt_es_keinen_trigger(self):
        from finance.db_schutz import trigger_vorhanden
        self.assertFalse(trigger_vorhanden())
