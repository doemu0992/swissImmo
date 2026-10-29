"""Sollstellung in Teil-Transaktionen und Sperr-Wartezeit (Etappe 2, SICH-05/SICH-09).

Bis 28.10.2026 lief die Sollstellung einer Verwaltung in EINER Transaktion mit
Zeilensperre auf ALLEN aktiven Verträgen. Zwei Folgen: Ein Fehler bei einem
Vertrag rollte den ganzen Monat zurück, und die Sperren (samt der
Belegnummern-Sperre der Verwaltung) hielten, bis der letzte Vertrag fertig war.

Jetzt ist es eine Transaktion je Vertrag. Geprüft wird:
* ein defekter Vertrag stoppt die anderen nicht, hinterlässt keine halbe Rechnung,
  wird benannt, und ein zweiter Lauf holt ihn nach;
* zwei gleichzeitige Läufe stellen jeden Vertrag genau einmal (PostgreSQL, echte Threads);
* `lock_timeout`: wer eine Sperre nicht bekommt, erhält nach der Wartezeit einen klaren
  Fehler statt einer hängenden Anfrage (PostgreSQL).
"""
import threading
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection, transaction
from django.test import TransactionTestCase

from core.services import automation
from core.sperren import SperreBelegt, sperre
from core.tenancy import organisation_kontext
from core.tests._helfer import _basis_objekte, _test_organisation
from core.tests._parallel import NUR_POSTGRES, parallel


class SollstellungBasis(TransactionTestCase):
    def setUp(self):
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        self.org = _test_organisation(iban='CH9300762011623852957')
        self.lg, self.einheit, self.mieter, self.vertrag1 = _basis_objekte()
        e2 = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='4.5 Zi', typ='whg',
                                    nettomiete_aktuell=Decimal('1800'), nebenkosten_aktuell=Decimal('250'))
        m2 = Mieter.objects.create(typ='person', vorname='Eva', nachname='Beispiel',
                                   email='eva@example.ch', strasse='Seeweg 4', plz='8000', ort='Zürich')
        self.vertrag2 = Mietvertrag.objects.create(
            mieter=m2, einheit=e2, beginn=date(2024, 1, 1), netto_mietzins=Decimal('1800'),
            nebenkosten=Decimal('250'), status='aktiv')

    def rechnungen(self, vertrag):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.filter(vertrag=vertrag, titel='Miete & NK 03/2026')


class TeilfehlerTests(SollstellungBasis):

    def _defekt_fuer(self, vertrag):
        original = automation._konten_fuer

        def konten(v):
            if v.pk == vertrag.pk:
                raise ValueError('Konto fehlt')
            return original(v)
        return mock.patch.object(automation, '_konten_fuer', konten)

    def test_defekter_vertrag_stoppt_die_anderen_nicht(self):
        with self._defekt_fuer(self.vertrag1):
            with self.assertRaises(automation.SollstellungTeilfehler) as ctx:
                automation.run_sollstellung(2026, 3)
        self.assertEqual(ctx.exception.erstellt, 1)
        self.assertEqual([v for v, _ in ctx.exception.fehler], [self.vertrag1.pk])
        self.assertEqual(self.rechnungen(self.vertrag2).count(), 1)

    def test_defekter_vertrag_hinterlaesst_keine_halbe_rechnung(self):
        from finance.models import Buchung
        with self._defekt_fuer(self.vertrag1):
            with self.assertRaises(automation.SollstellungTeilfehler):
                automation.run_sollstellung(2026, 3)
        self.assertEqual(self.rechnungen(self.vertrag1).count(), 0,
                         'Die Rechnung des defekten Vertrags ist nicht zurückgerollt.')
        self.assertEqual(Buchung.objects.filter(debitoren_rechnung__vertrag=self.vertrag1).count(), 0)

    def test_zweiter_lauf_holt_den_fehlgeschlagenen_nach(self):
        with self._defekt_fuer(self.vertrag1):
            with self.assertRaises(automation.SollstellungTeilfehler):
                automation.run_sollstellung(2026, 3)
        self.assertEqual(automation.run_sollstellung(2026, 3), 1)
        self.assertEqual(self.rechnungen(self.vertrag1).count(), 1)
        self.assertEqual(self.rechnungen(self.vertrag2).count(), 1)
        self.assertEqual(automation.run_sollstellung(2026, 3), 0)

    def test_meldung_nennt_den_vertrag_und_ist_eine_runtimeerror(self):
        with self._defekt_fuer(self.vertrag1):
            with self.assertRaises(RuntimeError) as ctx:
                automation.run_sollstellung(2026, 3)
        self.assertIn(str(self.vertrag1.pk), str(ctx.exception))
        self.assertIn('Konto fehlt', str(ctx.exception))

    def test_monatslauf_endet_mit_fehler_und_stellt_die_uebrigen(self):
        from io import StringIO
        from django.core.management import CommandError, call_command
        with self._defekt_fuer(self.vertrag1):
            with self.assertRaises(CommandError):
                call_command('monatslauf', jahr=2026, monat=3, stdout=StringIO(), stderr=StringIO())
        self.assertEqual(self.rechnungen(self.vertrag2).count(), 1)


class ParallelTests(SollstellungBasis):

    @NUR_POSTGRES
    def test_zwei_gleichzeitige_laeufe_stellen_jeden_vertrag_einmal(self):
        def lauf(i):
            with organisation_kontext(self.org):
                return automation.run_sollstellung(2026, 3)
        ergebnisse = parallel(4, lauf)
        abstuerze = [e for e in ergebnisse if isinstance(e, BaseException)]
        self.assertEqual(abstuerze, [], abstuerze)
        self.assertEqual(sum(ergebnisse), 2, ergebnisse)
        self.assertEqual(self.rechnungen(self.vertrag1).count(), 1)
        self.assertEqual(self.rechnungen(self.vertrag2).count(), 1)


class SperrWartezeitTests(TransactionTestCase):

    @NUR_POSTGRES
    def test_belegte_sperre_endet_nach_der_wartezeit_mit_klarem_fehler(self):
        """Ein Thread hält die Sperre; der zweite wartet nicht ewig."""
        gehalten, freigeben = threading.Event(), threading.Event()

        def halter():
            try:
                with transaction.atomic():
                    sperre('test', 'wartezeit')
                    gehalten.set()
                    freigeben.wait(timeout=30)
            finally:
                connection.close()

        t = threading.Thread(target=halter)
        t.start()
        try:
            self.assertTrue(gehalten.wait(timeout=15))
            with mock.patch('core.sperren.LOCK_TIMEOUT_MS', 300):
                with self.assertRaises(SperreBelegt):
                    with transaction.atomic():
                        sperre('test', 'wartezeit')
        finally:
            freigeben.set()
            t.join(timeout=30)

    def test_lock_timeout_ausserhalb_einer_transaktion_ist_ein_programmfehler(self):
        from django.db.transaction import TransactionManagementError
        from core.sperren import lock_timeout_setzen
        with self.assertRaises(TransactionManagementError):
            lock_timeout_setzen()
