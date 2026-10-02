"""Bauteile je Raumtyp: Eine Küche hat Schränke, Arbeitsplatte, Backofen, Kühlschrank.

Die Zahlen stammen aus einem Abnahme-/Übergabeprotokoll der Praxis
(Turmstrasse 5/7, Bellach); sie halten fest, dass kein Raumtyp wieder auf eine
einheitliche Mindestliste zurückfällt.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, SimpleTestCase, TestCase

from core.services.abnahme_bauteile import BAUTEILE, bauteile_fuer_raum, raumtyp

from ._helfer import _basis_objekte, _team_user


class RaumtypTests(SimpleTestCase):

    def test_freie_namen_werden_erkannt(self):
        faelle = {
            'Küche': 'kueche', 'Küche Turmstrasse (saniert)': 'kueche', 'Kueche': 'kueche',
            'Waschküche': 'waschkueche', 'Reduit': 'waschkueche',          # nicht «Küche»
            'Bad': 'bad', 'Bad/WC': 'bad', 'Bad Turmstrasse (saniert)': 'bad', 'Dusche': 'bad',
            'WC': 'wc', 'Gäste-WC': 'wc', 'Toilette': 'wc',                # kein «Bad»
            'Wohnzimmer': 'wohnzimmer', 'Wohnen/Essen': 'wohnzimmer', 'Esszimmer': 'wohnzimmer',
            'Zimmer 1': 'zimmer', 'Schlafzimmer': 'zimmer', 'Büro 1': 'zimmer', 'Kinderzimmer': 'zimmer',
            'Eingang/Korridor': 'korridor', 'Korridor Turmstrasse ( saniert )': 'korridor', 'Entrée': 'korridor',
            'Balkon/Terrasse': 'balkon', 'Loggia': 'balkon',
            'Keller': 'keller', 'Estrich': 'keller', 'Abstellraum': 'keller',
            'Heizung / Technik': 'technik', 'Garage': 'garage', 'Parkplatz Nr. 13': 'garage',
            'Hobbyraum': 'allgemein', '': 'allgemein',
        }
        for name, erwartet in faelle.items():
            self.assertEqual(raumtyp(name), erwartet, name)

    def test_anzahl_je_raumtyp_wie_im_praxisprotokoll(self):
        erwartet = {'kueche': 22, 'bad': 25, 'wohnzimmer': 13, 'zimmer': 10,
                    'korridor': 6, 'balkon': 7, 'keller': 5}
        for typ, n in erwartet.items():
            self.assertEqual(len(BAUTEILE[typ]), n, typ)

    def test_kueche_hat_die_kuechenbauteile(self):
        for bauteil in ('Küchenschränke unten', 'Küchenschränke oben', 'Küchenabdeckung (Arbeitsplatte)',
                        'Backofen', 'Kochherd', 'Kühlschrank/Gefrierfach', 'Geschirrspüler',
                        'Dampfabzug/Filter', 'Spülbecken', 'Boden', 'Decke', 'Wände'):
            self.assertIn(bauteil, BAUTEILE['kueche'])

    def test_bad_hat_sanitaer_und_der_keller_nicht(self):
        for bauteil in ('Lavabo', 'WC/Bidet', 'Badewanne/Dusche', 'Spiegelschrank', 'Handtuchstange'):
            self.assertIn(bauteil, BAUTEILE['bad'])
            self.assertNotIn(bauteil, BAUTEILE['keller'])
        self.assertNotIn('Backofen', BAUTEILE['bad'])

    def test_listen_sind_eindeutig_und_nicht_leer(self):
        for typ, liste in BAUTEILE.items():
            self.assertTrue(liste, typ)
            self.assertEqual(len(liste), len(set(liste)), f'{typ}: doppelte Bauteile')
            self.assertTrue(all(len(b) <= 120 for b in liste), typ)

    def test_ohne_raumbuch_gilt_der_standard_des_raumtyps(self):
        zeilen = bauteile_fuer_raum('Küche')
        self.assertEqual([b for b, _ in zeilen], BAUTEILE['kueche'])
        self.assertTrue(all(e is None for _, e in zeilen))


class _Element:
    def __init__(self, kategorie, bezeichnung=''):
        self.kategorie, self.bezeichnung = kategorie, bezeichnung


class RaumbuchAbgleichTests(SimpleTestCase):

    def test_passendes_element_ersetzt_den_standardeintrag_der_rest_bleibt(self):
        backofen = _Element('Backofen', 'Bosch HBA')
        zeilen = dict(bauteile_fuer_raum('Küche', [backofen]))
        self.assertIs(zeilen['Backofen – Bosch HBA'], backofen)
        self.assertNotIn('Backofen', zeilen)                  # nicht doppelt
        self.assertIn('Küchenschränke unten', zeilen)          # Raum nicht auf den Backofen verkleinert
        self.assertEqual(len(zeilen), len(BAUTEILE['kueche']))

    def test_element_ohne_entsprechung_kommt_dazu(self):
        zeilen = bauteile_fuer_raum('Wohnzimmer', [_Element('Teppich')])
        self.assertEqual(zeilen[-1][0], 'Teppich')
        self.assertEqual(len(zeilen), len(BAUTEILE['wohnzimmer']) + 1)

    def test_aehnliche_namen_werden_zusammengefuehrt(self):
        e1, e2 = _Element('Wände / Anstrich'), _Element('Bodenbelag')
        zeilen = dict(bauteile_fuer_raum('Zimmer 1', [e1, e2]))
        self.assertIs(zeilen['Wände'], e1)
        self.assertIs(zeilen['Boden'], e2)
        self.assertEqual(len(zeilen), len(BAUTEILE['zimmer']))

    def test_ein_element_wird_nur_einmal_verwendet(self):
        e = _Element('Fenster')
        zeilen = bauteile_fuer_raum('Zimmer 1', [e])
        self.assertEqual(sum(1 for _, el in zeilen if el is e), 1)

    def test_zu_kurze_namen_matchen_nicht_zufaellig(self):
        zeilen = dict(bauteile_fuer_raum('Zimmer 1', [_Element('TV')]))
        self.assertIsNone(zeilen['Boden'])
        self.assertEqual(len(zeilen), len(BAUTEILE['zimmer']) + 1)


class AbnahmeStartTests(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()
        self.c = Client(); self.c.force_login(_team_user())

    def _positionen(self, raeume):
        from rentals.models import Abnahmeprotokoll
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/', {'typ': 'auszug', 'raum': raeume})
        return Abnahmeprotokoll.objects.get().positionen

    def test_jeder_raum_bekommt_seine_bauteile(self):
        pos = self._positionen(['Küche', 'Bad/WC', 'Keller'])
        kueche = [p.bezeichnung for p in pos.filter(raum='Küche')]
        self.assertEqual(kueche, BAUTEILE['kueche'])
        self.assertIn('Küchenabdeckung (Arbeitsplatte)', kueche)
        self.assertEqual([p.bezeichnung for p in pos.filter(raum='Bad/WC')], BAUTEILE['bad'])
        self.assertEqual([p.bezeichnung for p in pos.filter(raum='Keller')], BAUTEILE['keller'])

    def test_kueche_im_assistenten_zeigt_backofen_und_kuehlschrank_am_telefon(self):
        self._positionen(['Küche'])
        from rentals.models import Abnahmeprotokoll
        prot = Abnahmeprotokoll.objects.get()
        seite = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=0')
        for text in ('Backofen', 'Kühlschrank/Gefrierfach', 'Küchenschränke oben', 'Küchenabdeckung'):
            self.assertContains(seite, text)

    def test_raumbuch_und_standard_werden_gemischt_mit_zeitwertbezug(self):
        from portfolio.models import Ausstattung
        ofen = Ausstattung.objects.create(einheit=self.einheit, raum='Küche', kategorie='Backofen',
                                          einbau_datum=date(2020, 3, 1), lebensdauer_jahre=10,
                                          neuwert=Decimal('1000'))
        pos = self._positionen(['Küche'])
        self.assertEqual(pos.filter(raum='Küche').count(), len(BAUTEILE['kueche']))
        self.assertEqual(pos.get(bezeichnung='Backofen').ausstattung_id, ofen.id)
        self.assertEqual(pos.filter(bezeichnung='Backofen').count(), 1)
        self.assertIsNone(pos.get(bezeichnung='Kochherd').ausstattung_id)
