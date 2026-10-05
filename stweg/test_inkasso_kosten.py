"""Mahngebühren (Sollstellung), Kostenvorschuss für die Betreibung und ihr Platz im Wasserfall (Art. 85 OR)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.tests._helfer import _team_user
from stweg import hauptbuch, inkasso, integritaet, vorgaben, zins
from stweg.models import StwegInkassoFall, StwegInkassoPosition
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget

D = Decimal


def gesendet(m):
    m.versendet_am, m.kanal = timezone.now(), 'email'
    m.save(update_fields=['versendet_am', 'kanal'])
    return m


class MahngebuehrTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)                       # Rate 1000.00 am 1.1.
        vorgaben.speichern(self.lg, {'mahngebuehr_chf': '20', 'mahngebuehr_ab_stufe': '2'}, bestaetigen=True)

    def test_ab_der_zweiten_mahnung_entsteht_eine_buchhalterische_forderung(self):
        m1 = gesendet(inkasso.mahnung_erstellen(self.b, heute=date(2026, 2, 1)))
        self.assertFalse(StwegInkassoPosition.objects.exists())              # 1. Mahnung: gebührenfrei
        self.assertEqual(m1.betrag, D('1000.00'))
        m2 = inkasso.mahnung_erstellen(self.b, heute=date(2026, 3, 1))
        pos = StwegInkassoPosition.objects.get()
        self.assertEqual((pos.art, pos.betrag, pos.mahnung), ('mahnspesen', D('20.00'), m2))
        self.assertEqual((pos.buchung.soll_konto.nummer, pos.buchung.haben_konto.nummer), ('1110', '3110'))
        self.assertEqual(m2.betrag, D('1020.00'))                            # die Gebühr ist Teil des Totals
        self.assertEqual(inkasso.offener_betrag(self.b, date(2026, 3, 1)), D('1020.00'))
        self.assertIn('Mahngebühr 2. Mahnung  CHF 20.00', '\n'.join(inkasso.mahntext(m2)).replace('  CHF', '  CHF'))
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))

    def test_die_gebuehr_steht_nicht_in_der_pfandsumme(self):
        gesendet(inkasso.mahnung_erstellen(self.b, heute=date(2026, 2, 1)))
        inkasso.mahnung_erstellen(self.b, heute=date(2026, 3, 1))
        p = inkasso.pfandberechtigt(self.b, date(2026, 3, 1))
        self.assertEqual((p['pfandberechtigt'], p['zinsen_kosten']), (D('1000.00'), D('20.00')))

    def test_ohne_bestaetigung_oder_ohne_vorgabe_keine_gebuehr(self):
        vorgaben.speichern(self.lg, {'mahngebuehr_chf': '25', 'mahngebuehr_ab_stufe': '2'})   # geändert → unbestätigt
        self.assertIsNone(inkasso.mahngebuehr(self.lg, 3))
        vorgaben.speichern(self.lg, {'mahngebuehr_chf': ''}, bestaetigen=True)
        self.assertIsNone(inkasso.mahngebuehr(self.lg, 3))

    def test_stufe_unter_dem_schwellenwert(self):
        self.assertIsNone(inkasso.mahngebuehr(self.lg, 1))
        self.assertEqual(inkasso.mahngebuehr(self.lg, 2), D('20'))
        self.assertEqual(inkasso.mahngebuehr(self.lg, 3), D('20'))
        vorgaben.speichern(self.lg, {'mahngebuehr_chf': '20', 'mahngebuehr_ab_stufe': ''}, bestaetigen=True)
        self.assertIsNone(inkasso.mahngebuehr(self.lg, 1))                  # leer = ab der 2. Mahnung
        self.assertEqual(inkasso.mahngebuehr(self.lg, 2), D('20'))

    def test_ungueltige_stufe(self):
        with self.assertRaises(vorgaben.VorgabenFehler):
            vorgaben.speichern(self.lg, {'mahngebuehr_chf': '20', 'mahngebuehr_ab_stufe': '4'})

    def test_gesperrte_periode_verhindert_die_mahnung_ganz(self):
        gesendet(inkasso.mahnung_erstellen(self.b, heute=date(2026, 2, 1)))
        org = self.lg.organisation
        org.buchung_gesperrt_bis = date(2026, 12, 31)
        org.save()
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.mahnung_erstellen(self.b, heute=date(2026, 3, 1))
        self.assertEqual(self.b.stweg_inkassofaelle.get().mahnungen.count(), 1)      # nichts halb angelegt


class WasserfallMitKostenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5', 'mahngebuehr_chf': '20',
                                     'mahngebuehr_ab_stufe': '2'}, bestaetigen=True)
        gesendet(inkasso.mahnung_erstellen(self.b, heute=date(2026, 2, 1)))
        inkasso.mahnung_erstellen(self.b, heute=date(2026, 3, 2))               # Gebühr 20; Zins bis 2.3.: 8.22

    def test_kosten_vor_zins_vor_kapital(self):
        z = hauptbuch.zahlung_erfassen(self.b, D('15'), date(2026, 3, 2))        # weniger als die Gebühr
        self.assertEqual((z.an_kosten, z.an_zins, z.kapital), (D('15.00'), D('0.00'), D('0.00')))
        z2 = hauptbuch.zahlung_erfassen(self.b, D('30'), date(2026, 3, 3))       # Rest Gebühr 5, Zins bis 3.3. 8.36
        self.assertEqual((z2.an_kosten, z2.an_zins, z2.kapital), (D('5.00'), D('8.36'), D('16.64')))
        stand = inkasso.forderungen(self.b, date(2026, 3, 3))
        self.assertEqual([c['offen'] for c in stand if c['art'] == 'mahnspesen'], [D('0.00')])
        self.assertEqual([c['offen'] for c in stand if c['art'] == 'zins'], [D('0.00')])
        self.assertEqual([c['offen'] for c in stand if c['art'] == 'akonto'], [D('1000.00') - D('16.64')])
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))

    def test_die_gewuenschte_andere_reihenfolge_zins_vor_kosten(self):
        stufen = ('zins', 'kosten', 'kapital')
        self.assertEqual(zins.zuordnen(self.b, D('15'), date(2026, 3, 2), reihenfolge=stufen),
                         (D('6.78'), D('8.22'), D('0.00')))                      # zuerst 8.22 Zins, dann 6.78 Gebühr
        self.assertEqual(zins.zuordnen(self.b, D('15'), date(2026, 3, 2)), (D('15.00'), D('0.00'), D('0.00')))

    def test_zahlung_stornieren_gibt_kosten_und_zins_wieder_frei(self):
        z = hauptbuch.zahlung_erfassen(self.b, D('30'), date(2026, 3, 3))
        hauptbuch.zahlung_stornieren(z)
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))


class KostenvorschussTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern(iban='CH9300762011623852957')
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)
        self.fall = StwegInkassoFall.objects.create(einheit=self.b, eroeffnet_am=date(2026, 3, 1))

    def test_vorschuss_kommt_zur_gesamtschuld_nicht_zur_pfandsumme(self):
        p = inkasso.kostenvorschuss_erfassen(self.fall, D('180'), date(2026, 5, 4), amt='Betreibungsamt Zürich 1')
        self.assertEqual((p.art, p.betrag), ('betreibungskosten', D('180.00')))
        self.assertEqual((p.buchung.soll_konto.nummer, p.buchung.haben_konto.nummer), ('1110', '1020'))   # Auslage
        self.fall.refresh_from_db()
        self.assertEqual((self.fall.betreibung_eingeleitet_am, self.fall.betreibungsamt),
                         (date(2026, 5, 4), 'Betreibungsamt Zürich 1'))
        stichtag = date(2026, 5, 4)
        kapital = sum((c['offen'] for c in inkasso.forderungen(self.b, stichtag) if c['art'] in zins.KAPITAL_ARTEN),
                      D('0'))
        self.assertEqual(inkasso.offener_betrag(self.b, stichtag), kapital + D('180.00'))
        self.assertEqual(inkasso.pfandberechtigt(self.b, stichtag)['pfandberechtigt'], kapital)
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))

    def test_zahlung_tilgt_zuerst_den_vorschuss(self):
        inkasso.kostenvorschuss_erfassen(self.fall, D('180'), date(2026, 5, 4))
        z = hauptbuch.zahlung_erfassen(self.b, D('200'), date(2026, 5, 5))
        self.assertEqual((z.an_kosten, z.kapital), (D('180.00'), D('20.00')))

    def test_fall_bleibt_offen_solange_der_vorschuss_nicht_bezahlt_ist(self):
        from stweg.models import StwegVorschreibung
        for v in StwegVorschreibung.objects.filter(einheit=self.b, faellig_am__lte=date(2026, 5, 4)):
            hauptbuch.zahlung_erfassen(self.b, v.betrag, date(2026, 5, 4), vorschreibung=v)
        inkasso.kostenvorschuss_erfassen(self.fall, D('180'), date(2026, 5, 4))
        inkasso.fall_pruefen(self.b, date(2026, 5, 4))
        self.fall.refresh_from_db()
        self.assertEqual(self.fall.status, 'offen')
        hauptbuch.zahlung_erfassen(self.b, D('180'), date(2026, 5, 6))
        inkasso.fall_pruefen(self.b, date(2026, 5, 6))
        self.fall.refresh_from_db()
        self.assertEqual(self.fall.status, 'erledigt')

    def test_ungueltig(self):
        for betrag in (D('0'), D('-5')):
            with self.assertRaises(inkasso.InkassoFehler):
                inkasso.kostenvorschuss_erfassen(self.fall, betrag)
        self.fall.status = 'erledigt'
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.kostenvorschuss_erfassen(self.fall, D('10'))
        self.assertFalse(StwegInkassoPosition.objects.exists())

    def test_storno_nimmt_die_forderung_zurueck(self):
        p = inkasso.kostenvorschuss_erfassen(self.fall, D('180'), date(2026, 5, 4))
        vorher = inkasso.offener_betrag(self.b, date(2026, 5, 4))
        inkasso.position_stornieren(p)
        self.assertEqual(inkasso.offener_betrag(self.b, date(2026, 5, 4)), vorher - D('180.00'))
        self.assertFalse([c for c in inkasso.forderungen(self.b, date(2026, 5, 4)) if c['art'] == 'betreibungskosten'])
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.position_stornieren(p)


class KostenOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2025)
        self.fall = StwegInkassoFall.objects.create(einheit=self.b)
        self.client.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/stweg/{self.lg.pk}/inkasso/'

    def test_vorschuss_ueber_die_seite_und_storno(self):
        r = self.client.post(self.url + 'kostenvorschuss/', {'einheit': self.b.pk, 'betrag': "1'80.50".replace("'", ''),
                                                             'datum': '2026-05-04', 'amt': 'BA Zürich'}, follow=True)
        self.assertContains(r, 'Kostenvorschuss erfasst')
        p = StwegInkassoPosition.objects.get()
        self.assertEqual(p.betrag, D('180.50'))
        self.assertContains(self.client.get(self.url), 'Kostenvorschuss Betreibung')
        r = self.client.post(self.url + f'position/{p.pk}/storno/', follow=True)
        self.assertContains(r, 'storniert')
        p.refresh_from_db()
        self.assertIsNotNone(p.storniert_am)

    def test_lesende_und_fremde(self):
        c = self.client_class()
        c.force_login(_team_user('Lesend'))
        c.post(self.url + 'kostenvorschuss/', {'einheit': self.b.pk, 'betrag': '10'})
        self.assertFalse(StwegInkassoPosition.objects.exists())
        _, ae, _ = haus_mit_eigentuemern()
        self.client.post(self.url + 'kostenvorschuss/', {'einheit': ae[1].pk, 'betrag': '10'})
        self.assertFalse(StwegInkassoPosition.objects.exists())

    def test_storno_einer_fremden_position_ist_404(self):
        lg2, e2, _ = haus_mit_eigentuemern()
        f2 = StwegInkassoFall.objects.create(einheit=e2[1])
        fremd = inkasso.kostenvorschuss_erfassen(f2, D('10'))
        r = self.client.post(self.url + f'position/{fremd.pk}/storno/')
        self.assertEqual(r.status_code, 404)

    def test_vorgabenseite_speichert_gebuehr(self):
        self.client.post(f'/neu/stweg/{self.lg.pk}/vorgaben/speichern/',
                         {'mahngebuehr_chf': '20', 'mahngebuehr_ab_stufe': '2', 'bestaetigt': '1'})
        v = vorgaben.vorgaben_von(self.lg)
        self.assertEqual((v.mahngebuehr_chf, v.mahngebuehr_ab_stufe, bool(v.bestaetigt_am)), (D('20'), 2, True))
