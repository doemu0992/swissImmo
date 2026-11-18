"""Eingabe und Fehlerseiten (Audit B3, B5, B8): Unsinn in Formularen ergibt eine Meldung, nie einen Fehler 500.

B3  Reparaturkosten: Nachfreigabe vergleicht mit der FREIGEGEBENEN Schätzung; negative/ungültige Beträge werden
    abgewiesen statt gespeichert.
B5  Handwerker-Link: Betrag «NaN» oder «Infinity» ergibt eine Meldung statt Fehler 500.
B8  Datum «30.02.» ergibt eine Meldung statt Fehler 500; Schadenfotos werden wie überall am Inhalt geprüft.
"""
from datetime import date
from decimal import Decimal

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase

from core.utils.eingabe import datum_oder_none, endlicher_betrag, zeit_oder_none

from ._helfer import _basis_objekte, _team_user
from .test_direktkanal import _auftrag_einfach
from .test_portale_modul3 import PDF, HandwerkerBasis, _neu, _pdf


class EingabeHilfenTests(SimpleTestCase):

    def test_datum_oder_none(self):
        self.assertEqual(datum_oder_none('2026-02-28'), date(2026, 2, 28))
        self.assertIsNone(datum_oder_none('2026-02-30'))      # richtiges Format, gibt es nicht
        self.assertIsNone(datum_oder_none('morgen'))
        self.assertIsNone(datum_oder_none(''))
        self.assertIsNone(datum_oder_none(None))

    def test_zeit_oder_none(self):
        self.assertIsNotNone(zeit_oder_none('2026-02-28T09:30'))
        self.assertIsNone(zeit_oder_none('2026-02-30T09:30'))
        self.assertIsNone(zeit_oder_none('x'))

    def test_endlicher_betrag(self):
        self.assertEqual(endlicher_betrag('12.50'), Decimal('12.50'))
        self.assertIsNone(endlicher_betrag(''))
        for roh in ('NaN', 'Infinity', '-Infinity', 'abc'):
            with self.assertRaises(ValueError):
                endlicher_betrag(roh)


class HandwerkerBetragTests(HandwerkerBasis):

    def test_nan_und_infinity_ergeben_eine_meldung_keinen_fehler(self):
        for roh in ('NaN', 'Infinity', '-Infinity'):
            r = self.client.post(self.url, {'aktion': 'offerte', 'betrag': roh, 'datei': _pdf('o.pdf')})
            self.assertLess(r.status_code, 500, roh)
        self.assertIsNone(_neu(self.auftrag).kosten_geschaetzt)       # nichts gespeichert

    def test_gegenprobe_normaler_betrag_geht(self):
        r = self.client.post(self.url, {'aktion': 'offerte', 'betrag': '400', 'datei': _pdf('o.pdf')})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_neu(self.auftrag).kosten_geschaetzt, Decimal('400.00'))


class KostenNachfreigabeTests(TestCase):

    def setUp(self):
        self.t, self.a = _auftrag_einfach()
        self.a.kosten_geschaetzt = Decimal('500')
        self.a.freigabe_status = 'freigegeben'
        self.a.save()
        self.c = Client()
        self.c.force_login(_team_user())
        self.url = f'/neu/auftrag/{self.a.pk}/kosten/'

    def _frisch(self):
        self.a.refresh_from_db()
        return self.a

    def test_schaetzung_und_kosten_zugleich_anheben_umgeht_die_nachfreigabe_nicht(self):
        # Freigegeben war 500. Wer Schätzung UND Kosten auf 1100 setzt, liegt «innerhalb» der neuen Schätzung,
        # aber weit über der freigegebenen.
        self.c.post(self.url, {'kosten_geschaetzt': '1100', 'kosten_effektiv': '1100'})
        self.assertEqual(self._frisch().freigabe_status, 'ausstehend')

    def test_gegenprobe_innerhalb_der_toleranz_bleibt_freigegeben(self):
        self.c.post(self.url, {'kosten_geschaetzt': '500', 'kosten_effektiv': '590'})     # +18 %
        a = self._frisch()
        self.assertEqual(a.freigabe_status, 'freigegeben')
        self.assertEqual(a.kosten_effektiv, Decimal('590'))

    def test_negative_und_ungueltige_betraege_werden_abgewiesen(self):
        for roh in ('-100', 'NaN', 'Infinity', 'abc'):
            r = self.c.post(self.url, {'kosten_geschaetzt': '500', 'kosten_effektiv': roh}, follow=True)
            self.assertEqual(r.status_code, 200, roh)
            self.assertIsNone(self._frisch().kosten_effektiv, roh)
            self.assertContains(r, 'gültige Beträge')


class DatumUndFotosTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client(raise_request_exception=False)
        self.c.force_login(_team_user())

    def test_termin_mit_unmoeglichem_datum_ergibt_keinen_fehler(self):
        r = self.c.post('/neu/termine/neu/', {'titel': 'Begehung', 'beginn': '2026-02-30T09:00'})
        self.assertLess(r.status_code, 500)

    def test_abwesenheit_mit_unmoeglichem_datum_ergibt_keinen_fehler(self):
        r = self.c.post('/neu/abwesenheiten/neu/', {'von': '2026-02-30', 'bis': '2026-03-05'})
        self.assertLess(r.status_code, 500)

    def test_schadenfoto_ohne_bildinhalt_wird_nicht_gespeichert(self):
        from tickets.models import SchadenFoto
        falsch = SimpleUploadedFile('foto.jpg', b'%PDF-1.4 kein Bild', content_type='image/jpeg')
        r = self.c.post('/neu/schaeden/neu/', {'titel': 'Wasserschaden', 'liegenschaft_id': self.lg.pk,
                                               'fotos': falsch}, follow=True)
        self.assertLess(r.status_code, 500)
        self.assertEqual(SchadenFoto.objects.count(), 0)
        self.assertContains(r, 'nicht gespeichert')


class WaechterTests(SimpleTestCase):
    def test_views_parsen_daten_nur_ueber_die_sicheren_hilfen(self):
        """`parse_date`/`parse_datetime` werfen bei «2026-02-30» ValueError (Fehler 500): in den Ansichten nur
        `core.utils.eingabe.datum_oder_none` / `zeit_oder_none` verwenden."""
        import pathlib
        import re
        treffer = []
        for pfad in pathlib.Path('core/views').rglob('*.py'):
            text = pfad.read_text(encoding='utf-8')
            if re.search(r'^\s*from django\.utils\.dateparse import .*parse_date', text, re.M):
                treffer.append(str(pfad))
        self.assertEqual(treffer, [], 'Direkter parse_date-Import in Ansichten')
