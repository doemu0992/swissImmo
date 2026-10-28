"""MIET-09: Eine Staffelstufe wird nur mit belegter, rechtzeitiger Mitteilung verrechnet.

Seit 1.10.2025 verlangt Art. 269d Abs. 5 OR die schriftliche Mitteilung jeder Staffelerhöhung. Die
Sollstellung stellte die Stufe bisher nach `ab_datum` allein. Jetzt (konservative Lesart, Fachpunkt):
nur mit `mitteilung_versandt_am` vor dem Eintritt und im Fenster der Art. 19a VMWG; Stufen, die schon
vor dem 1.10.2025 eintraten, wirken wie bisher. Sonst bleibt der bisherige Mietzins, und eine Pendenz
«Staffelmitteilung fehlt» entsteht.

Gegenproben stehen im Bericht (Code zurückgebaut -> der genannte Test wird rot).
"""
import io
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.services import staffel_mitteilung as sm

from ._helfer import _basis_objekte, _seed_konten

D = Decimal


class _Stufe:
    """Minimale Stufe für die reinen Regeltests (ohne Datenbank)."""

    def __init__(self, ab, versandt=None, pk=1):
        self.ab_datum, self.mitteilung_versandt_am, self.pk = ab, versandt, pk


class StufeWirktTests(SimpleTestCase):

    def test_altstufe_vor_inkrafttreten_wirkt_ohne_mitteilung(self):
        self.assertTrue(sm.stufe_wirkt(_Stufe(date(2025, 9, 1))))
        self.assertTrue(sm.stufe_wirkt(_Stufe(date(2024, 1, 1))))

    def test_stufe_ab_1_10_2025_ohne_mitteilung_wirkt_nicht(self):
        self.assertFalse(sm.stufe_wirkt(_Stufe(date(2025, 10, 1))))
        self.assertFalse(sm.stufe_wirkt(_Stufe(date(2026, 6, 1))))

    def test_rechtzeitige_mitteilung_im_fenster_wirkt(self):
        self.assertTrue(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 3, 15))))
        # genau der erste Tag des Fensters (vier Monate vorher)
        self.assertTrue(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 2, 1))))
        # am Vortag des Eintritts
        self.assertTrue(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 5, 31))))

    def test_mitteilung_am_eintrittstag_oder_danach_ist_nicht_rechtzeitig(self):
        self.assertFalse(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 6, 1))))
        self.assertFalse(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 7, 15))))

    def test_zu_frueh_versandt_wirkt_nicht(self):
        """Vor dem Fenster der Art. 19a VMWG (hier ein Tag zu früh)."""
        self.assertFalse(sm.stufe_wirkt(_Stufe(date(2026, 6, 1), versandt=date(2026, 1, 31))))

    def test_wirksame_stufe_haelt_vor_der_ersten_unmitgeteilten_an(self):
        """Die Stufen bauen aufeinander auf: Ist Stufe 1 nie mitgeteilt, darf Stufe 2 nicht ihre Erhöhung mitverrechnen."""
        s1 = _Stufe(date(2026, 6, 1), pk=1)                                   # nie mitgeteilt
        s2 = _Stufe(date(2027, 6, 1), versandt=date(2027, 3, 1), pk=2)        # mitgeteilt
        self.assertIsNone(sm.wirksame_stufe([s1, s2], date(2027, 12, 1)))
        s1.mitteilung_versandt_am = date(2026, 3, 1)
        self.assertIs(sm.wirksame_stufe([s1, s2], date(2026, 12, 1)), s1)
        self.assertIs(sm.wirksame_stufe([s1, s2], date(2027, 12, 1)), s2)

    def test_altstufe_gefolgt_von_neuer_stufe_ohne_mitteilung(self):
        alt = _Stufe(date(2025, 6, 1), pk=1)
        neu = _Stufe(date(2026, 6, 1), pk=2)
        self.assertIs(sm.wirksame_stufe([alt, neu], date(2026, 12, 1)), alt)


def _staffelvertrag(stufen):
    """Staffelvertrag, Netto 1500 + NK 200, Beginn 1.11.2025; `stufen` = [(ab, erhoehung, versandt)]."""
    from rentals.models import Staffelstufe
    _seed_konten()
    lg, e, m, v = _basis_objekte()
    v.mietzins_modell = 'staffel'
    v.beginn = date(2025, 11, 1)
    v.ist_befristet = True
    v.ende = date(2031, 10, 31)
    v.save()
    for ab, erh, versandt in stufen:
        Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=D('0'), erhoehung_chf=D(erh),
                                    mitteilung_versandt_am=versandt)
    return v


class VerrechnungTests(TestCase):

    def test_stufe_ohne_mitteilung_wird_nicht_verrechnet(self):
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 5, 1)), D('1500.00'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), D('1500.00'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2027, 1, 1)), D('1500.00'))

    def test_stufe_mit_rechtzeitiger_mitteilung_wird_verrechnet(self):
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', date(2026, 3, 1))])
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 5, 1)), D('1500.00'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 6, 1)), D('1550.00'))

    def test_altvertrag_stufe_vor_1_10_2025_unveraendert(self):
        from rentals.models import Staffelstufe
        v = _staffelvertrag([])
        v.beginn = date(2024, 1, 1)
        v.save()
        Staffelstufe.objects.create(vertrag=v, ab_datum=date(2025, 6, 1), netto_mietzins=D('0'),
                                    erhoehung_chf=D('40.00'))
        self.assertEqual(v.effektiver_netto_mietzins(date(2025, 7, 1)), D('1540.00'))

    def test_sollstellung_stellt_den_bisherigen_mietzins_und_legt_eine_pendenz_an(self):
        from core.models import Pendenz
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        run_sollstellung(2026, 6)
        rechnung = DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 06/2026')
        self.assertEqual(rechnung.betrag, D('1700.00'), 'Netto 1500 + NK 200: die Stufe darf nicht drin sein')
        pendenzen = Pendenz.objects.filter(vertrag=v, quelle__startswith='staffelfehlt:')
        self.assertEqual(pendenzen.count(), 1)
        self.assertIn('Staffelmitteilung fehlt', pendenzen.first().titel)
        self.assertIn('Art. 269d Abs. 5', pendenzen.first().beschreibung)

    def test_die_pendenz_entsteht_nur_einmal(self):
        from core.models import Pendenz
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        self.assertEqual(sm.fehlende_mitteilung_pendenzen(v, date(2026, 6, 1)), 1)
        self.assertEqual(sm.fehlende_mitteilung_pendenzen(v, date(2026, 7, 1)), 0)
        self.assertEqual(Pendenz.objects.filter(vertrag=v, quelle__startswith='staffelfehlt:').count(), 1)

    def test_keine_pendenz_fuer_altstufen_und_nicht_eingetretene_stufen(self):
        v = _staffelvertrag([(date(2025, 8, 1), '30.00', None), (date(2027, 6, 1), '50.00', None)])
        v.beginn = date(2024, 1, 1)
        v.save()
        self.assertEqual(sm.fehlende_mitteilung_pendenzen(v, date(2026, 6, 1)), 0)

    def test_sollstellung_mit_mitteilung_stellt_die_stufe_und_erledigt_die_pendenz(self):
        from core.models import Pendenz
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        run_sollstellung(2026, 6)
        pendenz = Pendenz.objects.get(vertrag=v, quelle__startswith='staffelfehlt:')
        stufe = v.staffelstufen.get()
        # Die Verwaltung stellt fest, dass sie rechtzeitig versandt hatte, und trägt es nach.
        sm.als_versandt_markieren(stufe, date(2026, 5, 20), date(2026, 6, 10))
        pendenz.refresh_from_db()
        self.assertTrue(pendenz.erledigt)
        run_sollstellung(2026, 7)
        self.assertEqual(DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 07/2026').betrag, D('1750.00'))

    def test_verspaetete_mitteilung_laesst_die_pendenz_offen(self):
        from core.models import Pendenz
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        sm.fehlende_mitteilung_pendenzen(v, date(2026, 6, 1))
        stufe = v.staffelstufen.get()
        sm.als_versandt_markieren(stufe, date(2026, 6, 5), date(2026, 6, 10))   # nach dem Eintritt
        self.assertFalse(Pendenz.objects.get(vertrag=v, quelle__startswith='staffelfehlt:').erledigt)
        self.assertEqual(v.effektiver_netto_mietzins(date(2026, 7, 1)), D('1500.00'))

    def test_stand_der_stufe_in_der_akte(self):
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None)])
        s = sm.stufen_staende(v, date(2026, 7, 1))[0]
        self.assertTrue(s.verstrichen)
        self.assertFalse(s.wirkt)
        v.staffelstufen.update(mitteilung_versandt_am=date(2026, 6, 5))
        v.refresh_from_db()
        s2 = sm.stufen_staende(v, date(2026, 7, 1))[0]
        self.assertTrue(s2.verspaetet)
        self.assertFalse(s2.verstrichen)


class BestandsberichtTests(TestCase):

    def test_bericht_listet_nur_lesend_und_veraendert_nichts(self):
        from core.services.automation import run_sollstellung
        v = _staffelvertrag([(date(2026, 6, 1), '50.00', None), (date(2025, 8, 1), '20.00', None)])
        v.beginn = date(2025, 1, 1)
        v.save()
        run_sollstellung(2026, 6)
        vorher = list(v.staffelstufen.values_list('pk', 'netto_mietzins', 'mitteilung_versandt_am'))
        aus = io.StringIO()
        from django.utils import timezone
        from unittest import mock
        with mock.patch.object(timezone, 'localdate', return_value=date(2026, 8, 1)):
            call_command('staffel_mitteilung_bestand', '--json', stdout=aus)
        import json
        daten = json.loads(aus.getvalue())
        stufen = [s for o in daten['organisationen'] for s in o['stufen']]
        self.assertEqual([s['ab'] for s in stufen], ['01.06.2026'], 'Altstufe ab 1.8.2025 gehört nicht in den Bericht')
        self.assertEqual(stufen[0]['rechnungen_seit_eintritt'], 1)
        self.assertEqual(list(v.staffelstufen.values_list('pk', 'netto_mietzins', 'mitteilung_versandt_am')), vorher)
