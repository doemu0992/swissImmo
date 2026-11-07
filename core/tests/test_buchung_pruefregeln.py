"""Prüfregeln und Erfassungszeitpunkt an Buchungen (Analysebericht 06.11.2026, Nr. 8).

Zwei Lücken für die Revision:

* Eine Buchung trug nur `datum`, das Buchungsdatum. Ob sie zeitnah oder nachträglich auf ein früheres Datum erfasst
  wurde, liess sich nicht belegen. Jetzt setzt der Server `erstellt_am` beim Anlegen; er ist unveränderlich.
* Nichts verhinderte eine Buchung mit Betrag 0 oder negativ oder mit demselben Konto auf Soll und Haben. Jetzt prüft das
  Modell neue Buchungen, und auf PostgreSQL stehen die Regeln als CHECK-Constraint in der Datenbank, soweit der
  Bestand sie zulässt.

Gegenproben: `_pruefe_neue_buchung()` aus `save()` nehmen -> `NeueBuchungTests` rot; `self.erstellt_am = timezone.now()`
entfernen -> `ErfassungszeitpunktTests` rot; die Regeln aus `PRUEFREGELN` streichen -> `DatenbankRegelnTests` rot (PostgreSQL).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from core.tests._parallel import NUR_POSTGRES
from core.tests.test_buchung_unveraenderlich import UnveraenderlichBasis


class NeueBuchungTests(UnveraenderlichBasis):
    def _neu(self, **ueber):
        from finance.models import Buchung
        werte = dict(datum=date(2026, 4, 1), beleg_text='Test', soll_konto=self.b.soll_konto,
                     haben_konto=self.b.haben_konto, betrag=Decimal('10.00'))
        werte.update(ueber)
        return Buchung.objects.create(**werte)

    def test_eine_gewoehnliche_buchung_geht_durch(self):
        self.assertIsNotNone(self._neu().pk)

    def test_betrag_null_oder_negativ_wird_abgewiesen(self):
        from finance.models import Buchung
        vorher = Buchung.objects.count()
        for betrag in (Decimal('0'), Decimal('-5.00')):
            with self.subTest(betrag=betrag), self.assertRaises(ValueError) as fehler:
                self._neu(betrag=betrag)
            self.assertIn('grösser als 0', str(fehler.exception))
        self.assertEqual(Buchung.objects.count(), vorher)

    def test_soll_und_haben_muessen_verschieden_sein(self):
        from finance.models import Buchung
        vorher = Buchung.objects.count()
        with self.assertRaises(ValueError) as fehler:
            self._neu(haben_konto=self.b.soll_konto)
        self.assertIn('verschieden', str(fehler.exception))
        self.assertEqual(Buchung.objects.count(), vorher)

    def test_buche_ueberspringt_null_wie_bisher_und_nimmt_positive(self):
        from finance.booking import buche
        self.assertIsNone(buche('1020', '3000', Decimal('0'), 'nichts'))
        self.assertIsNotNone(buche('1020', '3000', Decimal('1.00'), 'eins'))

    def test_ein_storno_bleibt_moeglich(self):
        """Das Storno vertauscht die Konten und trägt denselben (positiven) Betrag."""
        from finance.booking import storniere_buchung
        gegen = storniere_buchung(self.b)
        self.assertEqual((gegen.betrag, gegen.soll_konto_id, gegen.haben_konto_id),
                         (self.b.betrag, self.b.haben_konto_id, self.b.soll_konto_id))

    def test_eine_bestehende_buchung_wird_nicht_neu_geprueft(self):
        """Die Regeln gelten für das Anlegen; das Setzen der Storno-Marke an einer alten Buchung bleibt erlaubt."""
        self.assertEqual(type(self.b).objects.filter(pk=self.b.pk).update(storniert_am=timezone.now()), 1)


class ErfassungszeitpunktTests(UnveraenderlichBasis):
    def test_der_server_setzt_den_zeitpunkt(self):
        vor = timezone.now() - timedelta(seconds=2)
        self.assertIsNotNone(self.b.erstellt_am)
        self.assertGreaterEqual(self.b.erstellt_am, vor)
        self.assertLessEqual(self.b.erstellt_am, timezone.now() + timedelta(seconds=2))

    def test_er_kommt_nie_von_aussen(self):
        """Eine nachträglich erfasste Buchung auf ein altes Datum bekommt trotzdem den echten Erfassungszeitpunkt."""
        from finance.models import Buchung
        alt = timezone.now() - timedelta(days=400)
        b = Buchung.objects.create(datum=date(2025, 1, 1), beleg_text='nachträglich', soll_konto=self.b.soll_konto,
                                   haben_konto=self.b.haben_konto, betrag=Decimal('5.00'), erstellt_am=alt)
        self.assertGreater(b.erstellt_am, alt + timedelta(days=300))
        self.assertEqual(b.datum, date(2025, 1, 1))              # das Buchungsdatum bleibt, wie angegeben

    def test_er_ist_unveraenderlich(self):
        from finance.models import Buchung
        with self.assertRaises(PermissionError):
            Buchung.objects.filter(pk=self.b.pk).update(erstellt_am=timezone.now() - timedelta(days=30))
        b = Buchung.objects.get(pk=self.b.pk)
        b.erstellt_am = timezone.now() - timedelta(days=30)
        with self.assertRaises(PermissionError):
            b.save()

    def test_ein_storno_aendert_den_zeitpunkt_des_originals_nicht(self):
        from finance.booking import storniere_buchung
        from finance.models import Buchung
        vorher = Buchung.objects.get(pk=self.b.pk).erstellt_am
        storniere_buchung(self.b)
        self.assertEqual(Buchung.objects.get(pk=self.b.pk).erstellt_am, vorher)

    def test_das_feld_ist_keine_eingabe(self):
        from finance.models import Buchung
        self.assertFalse(Buchung._meta.get_field('erstellt_am').editable)


@NUR_POSTGRES
class DatenbankRegelnTests(UnveraenderlichBasis):
    """Die CHECK-Constraints in der Datenbank selbst (roher INSERT, am Modell vorbei)."""

    INSERT = ('INSERT INTO core_buchung (datum, beleg_text, soll_konto_id, haben_konto_id, betrag, ist_storno, '
              'organisation_id) VALUES (%s, %s, %s, %s, %s, false, %s)')

    def _roh(self, soll, haben, betrag):
        with connection.cursor() as cur, transaction.atomic():
            cur.execute(self.INSERT, [date(2026, 5, 1), 'roh', soll, haben, betrag, self.org.pk])

    def test_die_regeln_sind_angelegt(self):
        from finance import db_schutz
        self.assertEqual(db_schutz.pruefregeln_vorhanden(),
                         {name for name, *_ in db_schutz.PRUEFREGELN})

    def test_roher_insert_mit_betrag_null_oder_negativ_scheitert(self):
        for betrag in (Decimal('0'), Decimal('-1.00')):
            with self.subTest(betrag=betrag), self.assertRaises(IntegrityError):
                self._roh(self.b.soll_konto_id, self.b.haben_konto_id, betrag)

    def test_roher_insert_mit_gleichem_konto_scheitert(self):
        with self.assertRaises(IntegrityError):
            self._roh(self.b.soll_konto_id, self.b.soll_konto_id, Decimal('1.00'))

    def test_ein_gueltiger_roher_insert_geht(self):
        self._roh(self.b.soll_konto_id, self.b.haben_konto_id, Decimal('1.00'))

    def test_ein_bestand_mit_verstoss_blockiert_die_migration_nicht(self):
        """Der Altbestand: Die Regel wird übersprungen und gemeldet, nicht erzwungen."""
        from finance import db_schutz
        with connection.schema_editor() as editor:
            db_schutz.pruefregeln_entfernen(editor)
            with connection.cursor() as cur:
                cur.execute(self.INSERT, [date(2026, 5, 1), 'alt', self.b.soll_konto_id, self.b.haben_konto_id,
                                          Decimal('-3.00'), self.org.pk])
            with self.assertLogs('finance.db_schutz', level='ERROR'):
                uebersprungen = db_schutz.pruefregeln_nachziehen(editor)
        self.assertEqual([n for n, _ in uebersprungen], ['chk_buchung_betrag_positiv'])
        self.assertNotIn('chk_buchung_betrag_positiv', db_schutz.pruefregeln_vorhanden())
        self.assertIn('chk_buchung_soll_ungleich_haben', db_schutz.pruefregeln_vorhanden())


class BefehlTests(TestCase):
    def test_db_schutz_laeuft_durch(self):
        from io import StringIO

        from django.core.management import call_command
        aus = StringIO()
        call_command('db_schutz', stdout=aus)
        text = aus.getvalue()
        self.assertIn('Eindeutigkeiten', text)
        self.assertTrue('Prüfregeln' in text or 'keine CHECK-Constraints' in text, text)
