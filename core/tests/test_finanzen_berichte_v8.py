"""Finanzen und Berichte nach konzept-v8 (#finanzen, #berichte), Tranche C.

Geprüft wird, was die Oberfläche BEHAUPTET:

* «Übernehmen» im Bankabgleich schickt dasselbe Formular wie «Zuordnen» auf
  der Bankabgleich-Seite — und nur, wenn der Vorschlag belegbar ist (genau
  eine offene Rechnung mit demselben offenen Betrag). Zwei gleich grosse
  Rechnungen sind kein Vorschlag, sondern ein Rätsel.
* «Ausstände nach Alter» zeigt dieselben Summen wie die Aging-Seite.
* Die Zahlungsquote zeichnet nur gemessene Monate.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _basis_objekte, _seed_konten, _team_user


def _rechnung(v, betrag, tage_ueberfaellig, titel='Miete'):
    from finance.models import DebitorenRechnung
    heute = timezone.localdate()
    return DebitorenRechnung.objects.create(
        vertrag=v, titel=titel, betrag=Decimal(betrag), status='offen',
        datum=heute - timedelta(days=tage_ueberfaellig + 10),
        faellig_am=heute - timedelta(days=tage_ueberfaellig))


def _geparkt(betrag):
    from finance.models import Buchungskonto, Zahlungseingang
    k = Buchungskonto.objects.get_or_create(
        nummer='1190', defaults={'bezeichnung': 'Durchlaufkonto', 'typ': 'bilanz'})[0]
    return Zahlungseingang.objects.create(
        betrag=Decimal(betrag), datum_eingang=timezone.localdate(), konto=k,
        status='verbucht', bemerkung='UNGEKLÄRT: MUSTER HANS Miete')


class FinanzenV8Tests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_eindeutiger_betrag_gibt_vorschlag_mit_derselben_aktion(self):
        r = _rechnung(self.v, '1700.00', 45)
        z = _geparkt('1700.00')
        antwort = self.c.get('/neu/finanzen/')
        g = antwort.context['gutschriften'][0]
        self.assertEqual(g['vorschlag'].id, r.id)
        self.assertEqual(g['grund'], 'name')     # «MUSTER» steht im Absender
        self.assertContains(antwort, 'action="/neu/bankabgleich/zuordnen/"')
        self.assertContains(antwort, f'name="zahlung_id" value="{z.id}"')
        self.assertContains(antwort, f'name="rechnung_id" value="{r.id}"')

    def test_zwei_gleiche_betraege_sind_kein_vorschlag(self):
        _rechnung(self.v, '1700.00', 45)
        _rechnung(self.v, '1700.00', 15, titel='Miete 2')
        _geparkt('1700.00')
        antwort = self.c.get('/neu/finanzen/')
        self.assertIsNone(antwort.context['gutschriften'][0]['vorschlag'])
        self.assertNotContains(antwort, 'action="/neu/bankabgleich/zuordnen/"')
        self.assertContains(antwort, 'Betrag passt zu keinem offenen Posten')

    def test_uebernehmen_bucht_wie_im_bankabgleich(self):
        r = _rechnung(self.v, '1700.00', 45)
        z = _geparkt('1700.00')
        self.c.post('/neu/bankabgleich/zuordnen/', {'zahlung_id': z.id, 'rechnung_id': r.id})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(self.c.get('/neu/finanzen/').context['gutschriften'], [])

    def test_ausstaende_wie_aging_seite(self):
        _rechnung(self.v, '100.00', 10)
        _rechnung(self.v, '200.00', 45)
        _rechnung(self.v, '300.00', 120)
        f = self.c.get('/neu/finanzen/').context
        a = self.c.get('/neu/mahnwesen/aging/').context
        self.assertEqual(len(f['ausstaende']), 1)
        zeile = f['ausstaende'][0]
        for b in ('d30', 'd60', 'd90', 'd90plus'):
            self.assertEqual(zeile[b], a['total'][b], b)
        self.assertEqual(f['ueber30_chf'], Decimal('500.00'))
        self.assertEqual(f['ueber30_n'], 1)
        self.assertEqual(zeile['url'], f'/neu/vertraege/{self.v.id}/')

    def test_leer_sagt_was_ist(self):
        antwort = self.c.get('/neu/finanzen/')
        self.assertContains(antwort, 'Abgeglichen.')
        self.assertContains(antwort, 'Keine überfälligen Forderungen.')


class BerichteV8Tests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_ohne_sollstellung_keine_linie(self):
        antwort = self.c.get('/neu/berichte/')
        self.assertTrue(all(w is None for w in antwort.context['quote_werte']))
        self.assertNotContains(antwort, 'class="fw-kurve"')
        self.assertContains(antwort, 'Noch zu wenig Sollstellung')

    def test_linie_und_balken_aus_den_daten(self):
        from finance.models import DebitorenRechnung
        heute = timezone.localdate()
        for monate_zurueck, status in ((0, 'offen'), (1, 'bezahlt'), (2, 'bezahlt')):
            tag = (heute.replace(day=1) - timedelta(days=31 * monate_zurueck)).replace(day=1)
            DebitorenRechnung.objects.create(vertrag=self.v, titel='Miete', betrag=Decimal('1000'),
                                             status=status, datum=tag, faellig_am=tag)
        from crm.models import Eigentuemer
        self.lg.eigentuemer = Eigentuemer.objects.create(firma_oder_name='Muster AG')
        self.lg.save()
        antwort = self.c.get('/neu/berichte/')
        self.assertContains(antwort, 'class="fw-kurve"')
        self.assertContains(antwort, 'class="fw-hbar"')
        zeile = antwort.context['mandat_zeilen'][0]
        self.assertEqual(zeile['lgs'], 1)
        self.assertEqual(zeile['soll'], Decimal('1700.00'))
        # Der Katalog bleibt vollständig.
        self.assertContains(antwort, '/neu/mahnwesen/aging/')
        self.assertContains(antwort, 'Betriebskostenspiegel')
