"""Buchungen sind nach dem Buchen unveränderlich — Mindesthärtung (Etappe 0:
FIN-15/SICH-06).

Vorher galt das nur für `Buchung.delete()` an der Instanz. `save()` auf eine
bestehende Buchung, `QuerySet.update()` und `QuerySet.delete()` änderten Betrag,
Konten und Datum spurlos, auch in einer gesperrten Periode.

Der DB-Trigger (PostgreSQL), der Basis-Manager und die Eindeutigkeiten stehen in
`test_buchung_db_schutz`. Auf SQLite bleibt rohes SQL ungeschützt;
`test_grenzen_sind_benannt` hält das fest, damit niemand mehr verspricht, als
gebaut ist.
"""
import logging
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _basis_objekte, _test_organisation


class UnveraenderlichBasis(TestCase):

    def setUp(self):
        from finance.booking import buche, ensure_kontenplan
        self.org = _test_organisation()
        ensure_kontenplan()
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.b = buche('1020', '3000', Decimal('1500.00'), 'Miete März', datum=date(2026, 3, 1),
                       liegenschaft=self.lg)

    def neu_lesen(self):
        from finance.models import Buchung
        return Buchung.objects.get(pk=self.b.pk)


class SammelaenderungTests(UnveraenderlichBasis):

    def test_update_von_betrag_konto_datum_text_ist_gesperrt(self):
        from finance.models import Buchung
        for feld, wert in (('betrag', Decimal('1.00')), ('datum', date(2026, 1, 1)),
                           ('beleg_text', 'anders'), ('beleg_nr', 99),
                           ('soll_konto_id', self.b.haben_konto_id), ('ist_storno', True),
                           ('liegenschaft', None)):
            with self.subTest(feld=feld), self.assertRaises(PermissionError):
                Buchung.objects.filter(pk=self.b.pk).update(**{feld: wert})
        b = self.neu_lesen()
        self.assertEqual((b.betrag, b.datum, b.beleg_text), (Decimal('1500.00'), date(2026, 3, 1), 'Miete März'))

    def test_delete_auf_dem_queryset_ist_gesperrt(self):
        from finance.models import Buchung
        with self.assertRaises(PermissionError):
            Buchung.objects.filter(pk=self.b.pk).delete()
        with self.assertRaises(PermissionError):
            Buchung.objects.all().delete()
        with self.assertRaises(PermissionError):
            Buchung.alle_organisationen.filter(pk=self.b.pk).delete()
        self.assertTrue(Buchung.objects.filter(pk=self.b.pk).exists())

    def test_delete_ueber_den_rueckbezug_ist_gesperrt(self):
        with self.assertRaises(PermissionError):
            self.lg.buchungen.all().delete()
        with self.assertRaises(PermissionError):
            self.lg.buchungen.update(betrag=Decimal('2.00'))

    def test_bulk_update_und_bulk_create_sind_gesperrt(self):
        from finance.models import Buchung
        b = self.neu_lesen()
        b.betrag = Decimal('2.00')
        with self.assertRaises(PermissionError):
            Buchung.objects.bulk_update([b], ['betrag'])
        with self.assertRaises(PermissionError):
            Buchung.objects.bulk_create([Buchung(datum=date(2026, 3, 1), beleg_text='x', soll_konto=b.soll_konto,
                                                 haben_konto=b.haben_konto, betrag=Decimal('1'))])
        self.assertEqual(self.neu_lesen().betrag, Decimal('1500.00'))

    def test_storno_marke_und_verknuepfung_duerfen_sammelweise_gesetzt_werden(self):
        from finance.models import Buchung, DebitorenRechnung
        r = DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='R', betrag=Decimal('10'),
                                             datum=date(2026, 3, 1), status='offen')
        self.assertEqual(Buchung.objects.filter(pk=self.b.pk).update(debitoren_rechnung=r), 1)
        jetzt = timezone.now()
        self.assertEqual(Buchung.objects.filter(pk=self.b.pk).update(storniert_am=jetzt), 1)
        b = self.neu_lesen()
        self.assertEqual(b.debitoren_rechnung_id, r.pk)
        self.assertIsNotNone(b.storniert_am)

    def test_verknuepfung_in_gesperrter_periode_nicht_aber_die_storno_marke(self):
        from finance.models import Buchung, DebitorenRechnung
        self.org.buchung_gesperrt_bis = date(2026, 12, 31)
        self.org.save()
        r = DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='R', betrag=Decimal('10'),
                                             datum=date(2026, 3, 1), status='offen')
        with self.assertRaises(PermissionError):
            Buchung.objects.filter(pk=self.b.pk).update(debitoren_rechnung=r)
        self.assertEqual(Buchung.objects.filter(pk=self.b.pk).update(storniert_am=timezone.now()), 1)

    def test_ausnahme_braucht_eine_begruendung_und_laesst_eine_spur(self):
        from finance.models import Buchung
        with self.assertRaises(ValueError):
            Buchung.objects.filter(pk=self.b.pk).ausnahme_aendern('', betrag=Decimal('3.00'))
        with self.assertLogs('finance.models', level=logging.WARNING) as protokoll:
            Buchung.objects.filter(pk=self.b.pk).ausnahme_aendern('Reparatur Import 28.10.', betrag=Decimal('3.00'))
        self.assertIn('Reparatur Import 28.10.', protokoll.output[0])
        self.assertEqual(self.neu_lesen().betrag, Decimal('3.00'))
        with self.assertRaises(ValueError):
            Buchung.objects.filter(pk=self.b.pk).ausnahme_loeschen('  ')
        with self.assertLogs('finance.models', level=logging.WARNING):
            Buchung.objects.filter(pk=self.b.pk).ausnahme_loeschen('Testaufbau')
        self.assertFalse(Buchung.objects.filter(pk=self.b.pk).exists())


class InstanzaenderungTests(UnveraenderlichBasis):

    def test_save_mit_geaendertem_betrag_wird_abgewiesen(self):
        b = self.neu_lesen()
        b.betrag = Decimal('1.00')
        with self.assertRaises(PermissionError):
            b.save()
        self.assertEqual(self.neu_lesen().betrag, Decimal('1500.00'))

    def test_save_mit_update_fields_auf_geschuetztes_feld_wird_abgewiesen(self):
        b = self.neu_lesen()
        b.beleg_text = 'umgeschrieben'
        with self.assertRaises(PermissionError):
            b.save(update_fields=['beleg_text'])
        b = self.neu_lesen()
        b.soll_konto = b.haben_konto
        with self.assertRaises(PermissionError):
            b.save()

    def test_unveraenderter_save_ist_erlaubt(self):
        b = self.neu_lesen()
        b.save()
        b.save(update_fields=['storniert_am'])
        self.assertEqual(self.neu_lesen().betrag, Decimal('1500.00'))

    def test_ein_noch_nicht_neu_gelesenes_objekt_wird_nicht_falsch_abgewiesen(self):
        """`datum` ist nach dem Anlegen unter Umständen noch ein datetime, `betrag` ein
        Decimal mit anderer Skala: gleich ist gleich."""
        from finance.models import Buchung
        frisch = Buchung.objects.create(
            datum=timezone.now(), beleg_text='frisch', soll_konto=self.b.soll_konto,
            haben_konto=self.b.haben_konto, betrag=Decimal('7'))
        frisch.save()
        frisch.betrag = Decimal('7.0')
        frisch.save()

    def test_storno_marke_darf_einmal_gesetzt_nicht_zurueckgenommen_werden(self):
        from finance.booking import storniere_buchung
        storniere_buchung(self.b)
        b = self.neu_lesen()
        self.assertIsNotNone(b.storniert_am)
        b.storniert_am = None
        with self.assertRaises(PermissionError):
            b.save(update_fields=['storniert_am'])
        self.assertIsNotNone(self.neu_lesen().storniert_am)

    def test_periodensperre_gilt_auch_fuer_aenderungen(self):
        """Neue Buchungen in gesperrter Periode wiesen schon immer ab; die Änderung
        einer bestehenden lief durch."""
        from finance.models import DebitorenRechnung
        self.org.buchung_gesperrt_bis = date(2026, 12, 31)
        self.org.save()
        r = DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='R', betrag=Decimal('10'),
                                             datum=date(2026, 3, 1), status='offen')
        b = self.neu_lesen()
        b.debitoren_rechnung = r
        with self.assertRaises(PermissionError) as ctx:
            b.save(update_fields=['debitoren_rechnung'])
        self.assertIn('gesperrt', str(ctx.exception))

    def test_storno_in_gesperrter_periode_bleibt_moeglich(self):
        """Das Storno bucht im OFFENEN Datum und markiert das Original — die Marke
        ändert weder Betrag noch Konten."""
        from finance.booking import storniere_buchung
        self.org.buchung_gesperrt_bis = date(2026, 3, 31)
        self.org.save()
        gegen = storniere_buchung(self.b, datum=date(2026, 4, 2))
        self.assertTrue(gegen.ist_storno)
        self.assertIsNotNone(self.neu_lesen().storniert_am)

    def test_verknuepfung_nachtragen_ist_ausserhalb_der_sperre_erlaubt(self):
        from finance.models import DebitorenRechnung
        r = DebitorenRechnung.objects.create(vertrag=self.vertrag, titel='R', betrag=Decimal('10'),
                                             datum=date(2026, 3, 1), status='offen')
        b = self.neu_lesen()
        b.debitoren_rechnung = r
        b.save(update_fields=['debitoren_rechnung'])
        self.assertEqual(self.neu_lesen().debitoren_rechnung_id, r.pk)

    def test_beleg_nr_ist_nicht_nachtraeglich_aenderbar(self):
        b = self.neu_lesen()
        b.beleg_nr = 77
        with self.assertRaises(PermissionError):
            b.save(update_fields=['beleg_nr'])

    def test_instanz_delete_bleibt_gesperrt(self):
        with self.assertRaises(PermissionError):
            self.neu_lesen().delete()


class KaskadeTests(UnveraenderlichBasis):
    """Was Django selbst über die Kaskade tut, geht am QuerySet vorbei und bleibt
    funktionsfähig: SET_NULL beim Löschen einer Zahlung."""

    def test_loeschen_einer_verknuepften_zahlung_loest_nur_die_verknuepfung(self):
        from finance.models import Buchung, Zahlungseingang
        z = Zahlungseingang.objects.create(vertrag=self.vertrag, betrag=Decimal('10'),
                                           datum_eingang=date(2026, 3, 1))
        Buchung.objects.filter(pk=self.b.pk).update(zahlungseingang=z)
        z.delete()
        b = self.neu_lesen()
        self.assertIsNone(b.zahlungseingang_id)
        self.assertEqual(b.betrag, Decimal('1500.00'))


class DatenresetTests(UnveraenderlichBasis):
    """Der Datenreset ist die benannte Ausnahme. Ohne sie lief `Buchung.objects.all()
    .delete()` in den Fehler, den der Reset schluckt (er meldet nur im Log), und
    das Journal samt Kontenplan blieb stehen — während die Maske «Alle Daten wurden
    gelöscht» sagte."""

    def test_reset_loescht_auch_die_buchungen(self):
        from django.test import Client

        from core.tests._helfer import _team_user
        from finance.models import Buchung, Buchungskonto
        self.assertTrue(Buchung.objects.exists())
        c = Client()
        c.force_login(_team_user(rolle='Inhaber'))
        from unittest.mock import patch

        from django.core.cache import cache
        cache.clear()
        # Seit SICH-03 verlangt der Reset Passwort und eine gelungene Sicherung (Stub, wie in
        # test_plattform.DatenResetTests: unter SQLite im Speicher kann `sicherung` nicht lesen).
        with patch('core.services.datenreset.sicherung_erstellen', return_value=''):
            antwort = c.post('/neu/datenreset/', {'bestaetigung': 'LÖSCHEN', 'passwort': 'x'}, secure=True)
        self.assertEqual(antwort.status_code, 302)
        self.assertFalse(Buchung.objects.exists())
        # Der Kontenplan wird danach frisch aufgesetzt, nicht als Altbestand mitgeschleppt.
        self.assertTrue(Buchungskonto.objects.filter(nummer='1020').exists())


class GrenzenTests(UnveraenderlichBasis):

    def test_grenzen_sind_benannt(self):
        """Ehrlichkeit statt Versprechen. Seit Etappe 2 ist der Basis-Manager gesperrt
        (siehe test_buchung_db_schutz); offen bleibt rohes SQL auf SQLite, wo es keinen
        Trigger gibt. Fällt dieser Test, ist eine Grenze gefallen: Doku und Bericht
        nachziehen, nicht den Test löschen."""
        from django.db import connection

        from finance.models import Buchung
        with self.assertRaises(PermissionError):
            Buchung._base_manager.filter(pk=self.b.pk).update(beleg_text='roh')
        if connection.vendor == 'sqlite':
            with connection.cursor() as cur:
                cur.execute('UPDATE core_buchung SET beleg_text = %s WHERE id = %s', ['roh', self.b.pk])
            self.assertEqual(self.neu_lesen().beleg_text, 'roh')
