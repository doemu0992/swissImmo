"""Auf der Vertragsakte steht der Rückstand einmal, nicht zweimal.

Vorher gab es oben die Ansage «Rückstand …» mit den Knöpfen und im Tab «Finanzen» einen zweiten roten Balken
mit demselben Knopf «Zahlungsverzug 257d» und dem Pauschaltext «30-Tage-Frist» (bei Parkplätzen gilt 10 Tage).

Gegenprobe: den zweiten Balken (`fw-hinweis crit` mit «Offener Betrag») wieder in `vertrag_detail.html` einsetzen,
und der Test wird rot.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class RueckstandEinmalTests(TestCase):

    def setUp(self):
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        heute = date.today()
        DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.lg, einheit=self.e, titel='Miete & NK 08/2026',
            datum=heute - timedelta(days=40), faellig_am=heute - timedelta(days=35),
            betrag=Decimal('1700.00'), status='offen')
        self.c = Client()
        self.c.force_login(_team_user())

    def test_ein_rueckstandsbalken_mit_einem_verzugsknopf(self):
        html = self.c.get(f'/neu/vertraege/{self.v.id}/').content.decode()
        self.assertIn('Rückstand CHF', html, 'Die Ansage mit dem Rückstand fehlt.')
        knoepfe = re.findall(rf'<a href="/neu/vertraege/{self.v.id}/verzug/"\s+class="fw-btn[^"]*"', html)
        self.assertEqual(len(knoepfe), 1, 'Der Knopf «Zahlungsverzug 257d» steht mehr als einmal als Knopf auf der Seite.')
        self.assertNotIn('Offener Betrag: CHF', html)
        self.assertNotIn('30-Tage-Frist', html)
