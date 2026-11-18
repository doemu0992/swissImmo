"""Die Auflösung gibt das Sperrkonto in Höhe des BILANZIERTEN Betrags frei, nicht in Höhe des Vertragsfelds.

Audit 17.11.2026 (F6): Einbezahlt und bilanziert CHF 3'000; das Vertragsfeld stand später auf 4'500. Die Auflösung buchte
4'500 von 1015 und 2010 ab: Konto 1015 stand danach auf −1'500, die Bank auf +1'500.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user


class KautionAufloesungTests(TestCase):

    def setUp(self):
        from core.services.automation import buche_kaution_einzahlung
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        v = self.v
        v.kautions_art, v.kautions_einbezahlt_am, v.kautions_betrag = 'sperrkonto', date(2026, 1, 1), Decimal('3000.00')
        v.save()
        buche_kaution_einzahlung(v, date(2026, 1, 1))
        v.kautions_betrag = Decimal('4500.00')          # das Vertragsfeld wird später geändert
        v.save(update_fields=['kautions_betrag'])
        self.c = Client()
        self.c.force_login(_team_user())

    def _saldo(self, nummer):
        from django.db.models import Sum
        from finance.models import Buchung
        soll = Buchung.objects.filter(soll_konto__nummer=nummer).aggregate(t=Sum('betrag'))['t'] or Decimal('0')
        haben = Buchung.objects.filter(haben_konto__nummer=nummer).aggregate(t=Sum('betrag'))['t'] or Decimal('0')
        return soll - haben

    def test_sperrkonto_geht_auf_null_nicht_ins_minus(self):
        self.assertEqual(self._saldo('1015'), Decimal('3000.00'), 'Voraussetzung: 3000 sind bilanziert')
        self.c.post(f'/neu/vertraege/{self.v.pk}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '0', 'zurueckbezahlt_am': timezone.localdate().isoformat()})
        self.assertEqual(self._saldo('1015'), Decimal('0.00'), 'Das Sperrkonto steht nicht auf null')
        self.assertEqual(self._saldo('2010'), Decimal('0.00'))
