"""Simulation: eine Rate wird verspätet und in Teilzahlungen bezahlt. Beweis, dass jede Zahlung zuerst die Kosten, dann
den Zins und erst zuletzt das Kapital tilgt (Art. 85 Abs. 1 OR) — und dass das Hauptbuch dabei auf den Rappen aufgeht."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from stweg import hauptbuch, inkasso, integritaet, vorgaben
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget

D = Decimal


def offen(stand, art):
    return [c['offen'] for c in stand if c['art'] == art]


class VerspaeteteTeilzahlung(TestCase):
    def test_die_zahlung_tilgt_zuerst_kosten_dann_zins_dann_kapital(self):
        lg, e, _ = haus_mit_eigentuemern(iban='CH9300762011623852957')
        bruno = e[1]                                                  # 200/1000: Rate 1000.00 am 1.1. und 1.4.
        jahr_budget(lg, 2026, total=20000)
        vorgaben.speichern(lg, {'verzugszins_prozent': '5', 'mahngebuehr_chf': '20', 'mahngebuehr_ab_stufe': '2'},
                           bestaetigen=True)

        # 1.2.: 1. Mahnung, gebührenfrei, 31 Tage Zins: 1000 × 5 % × 31/365 = 4.25
        m1 = inkasso.mahnung_erstellen(bruno, heute=date(2026, 2, 1))
        m1.versendet_am, m1.kanal = timezone.now(), 'email'
        m1.save()
        self.assertEqual(m1.betrag, D('1004.25'))
        # 2.3.: 2. Mahnung mit Gebühr 20.00; Zins 60 Tage = 8.22  →  1000 + 8.22 + 20
        m2 = inkasso.mahnung_erstellen(bruno, heute=date(2026, 3, 2))
        self.assertEqual(m2.betrag, D('1028.22'))
        # 10.3.: Betreibung eingeleitet, Kostenvorschuss 150.00
        fall = m2.fall
        inkasso.kostenvorschuss_erfassen(fall, D('150'), date(2026, 3, 10), amt='Betreibungsamt Zürich 1')

        # 12.3.: Teilzahlung 100 — weniger als die Kosten (20 + 150): alles geht an die Kosten, nichts an Zins/Kapital
        z1 = hauptbuch.zahlung_erfassen(bruno, D('100'), date(2026, 3, 12))
        self.assertEqual((z1.an_kosten, z1.an_zins, z1.kapital), (D('100.00'), D('0.00'), D('0.00')))
        stand = inkasso.forderungen(bruno, date(2026, 3, 12))
        self.assertEqual(offen(stand, 'mahnspesen') + offen(stand, 'betreibungskosten'), [D('0.00'), D('70.00')])
        self.assertEqual(offen(stand, 'akonto'), [D('1000.00')])                 # Kapital unangetastet

        # 20.3.: Teilzahlung 600 — Rest der Kosten 70.00, dann Zins 78 Tage = 10.68, erst dann Kapital 519.32
        z2 = hauptbuch.zahlung_erfassen(bruno, D('600'), date(2026, 3, 20))
        self.assertEqual((z2.an_kosten, z2.an_zins, z2.kapital), (D('70.00'), D('10.68'), D('519.32')))
        stand = inkasso.forderungen(bruno, date(2026, 3, 20))
        self.assertEqual(offen(stand, 'akonto'), [D('480.68')])
        self.assertEqual(offen(stand, 'zins'), [D('0.00')])

        # 1.4.: Der Zins läuft weiter, aber nur auf das offene Kapital (12 Tage auf 480.68 = 0.79), nicht auf Zins/Kosten
        stand = inkasso.forderungen(bruno, date(2026, 4, 1))
        zins = [c for c in stand if c['art'] == 'zins']
        self.assertEqual((zins[0]['betrag'], zins[0]['offen']), (D('11.47'), D('0.79')))   # 10.68 + 0.79
        z3 = hauptbuch.zahlung_erfassen(bruno, D('481.47'), date(2026, 4, 1))
        self.assertEqual((z3.an_kosten, z3.an_zins, z3.kapital), (D('0.00'), D('0.79'), D('480.68')))

        # Die erste Rate ist samt Zins und Kosten bezahlt; offen bleibt nur die neue Rate vom 1.4.
        stand = inkasso.forderungen(bruno, date(2026, 4, 1))
        self.assertEqual([c['offen'] for c in stand if c['datum'] == date(2026, 1, 1)], [D('0.00'), D('0.00')])
        self.assertEqual(inkasso.offener_betrag(bruno, date(2026, 4, 1)), D('1000.00'))
        # Alles, was bezahlt wurde, ist angerechnet: 1181.47 = Kosten 170.00 + Zins 11.47 + Kapital 1000.00
        gezahlt = z1.betrag + z2.betrag + z3.betrag
        self.assertEqual(gezahlt, D('1181.47'))
        self.assertEqual(sum((z.an_kosten for z in (z1, z2, z3)), D('0')), D('170.00'))
        self.assertEqual(sum((z.an_zins for z in (z1, z2, z3)), D('0')), D('11.47'))
        self.assertEqual(sum((z.kapital for z in (z1, z2, z3)), D('0')), D('1000.00'))

        # Hauptbuch: Gebühr = Ertrag 3110, Zins = Ertrag 3120, Vorschuss = Auslage; alles stimmt auf den Rappen
        ab = integritaet.abstimmung_hauptbuch(lg)
        self.assertTrue(all(v['differenz'] == 0 for v in ab.values()), ab)
        self.assertEqual(integritaet._saldo(lg, '3110'), D('-20.00'))
        self.assertEqual(integritaet._saldo(lg, '3120'), D('-11.47'))
        # Die Pfandsumme enthält nie Zins oder Kosten — auch wenn sie noch offen wären
        p = inkasso.pfandberechtigt(bruno, date(2026, 4, 1))
        self.assertEqual(p['pfandberechtigt'], D('1000.00'))
