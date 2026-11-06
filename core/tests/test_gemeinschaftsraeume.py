"""Gemeinschaftsräume: das Raumbuch der LIEGENSCHAFT (Waschküche, Trockenraum, Veloraum …).

Gegenproben:
* `CheckConstraint ..._genau_ein_bezug` aus `Ausstattung.Meta` entfernen -> `test_genau_ein_bezug` rot;
* in `_ausstattung_katalog` die Beschränkung auf `GEMEINSCHAFT_TYPEN` entfernen -> `test_wohnungstypen_gehen_nicht_ins_haus` rot;
* in `berechne_ersatzplanung` den Zweig `| Q(liegenschaft=aktive_lg)` entfernen -> `test_ersatzplanung_...` rot;
* in `fw_lg_gemeinschaft_anlegen` den Fremdschlüssel-Zweig `bezug()` auf `einheit` umbiegen -> `AnsichtTests` rot.
"""
from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from core.services import raumbuch_assistent as ra
from core.services.raumkatalog import GEMEINSCHAFT_TYPEN, RAUM_KATALOG, RAUMTYPEN
from portfolio.models import Ausstattung

from ._helfer import _basis_objekte, _team_user
from ._isolation import MandantenFixture


def _raeume(lg):
    return sorted(set(Ausstattung.objects.filter(liegenschaft=lg).values_list('raum', flat=True)))


class ModellTests(TestCase):
    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()

    def test_genau_ein_bezug(self):
        for kw in ({}, {'einheit': self.e, 'liegenschaft': self.lg}):
            with self.subTest(kw=kw), self.assertRaises(IntegrityError), transaction.atomic():
                Ausstattung.objects.create(raum='X', kategorie='Y', **kw)
        Ausstattung.objects.create(raum='X', kategorie='Y', einheit=self.e)
        Ausstattung.objects.create(raum='Waschküche', kategorie='Waschmaschine', liegenschaft=self.lg)

    def test_katalog_trennt_wohnung_und_haus(self):
        for typ in ('Trockenraum', 'Veloraum', 'Treppenhaus / Eingang', 'Gemeinschaftsraum', 'Einstellhalle'):
            self.assertNotIn(typ, RAUMTYPEN)                          # nicht in der Wohnungs-Auswahl
            self.assertIn(typ, GEMEINSCHAFT_TYPEN)
            self.assertIn(typ, RAUM_KATALOG)
        self.assertIn('Waschküche', RAUMTYPEN)                        # eigene Waschküche in der Wohnung gibt es weiter
        self.assertIn('Waschküche', GEMEINSCHAFT_TYPEN)


class DienstTests(TestCase):
    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()

    def test_gemeinschaft_anlegen_je_typ_einmal(self):
        angelegt, uebersprungen = ra.gemeinschaft_anlegen(self.lg, {'Waschküche', 'Veloraum', 'Unbekannt'})
        self.assertEqual(sorted(angelegt), ['Veloraum', 'Waschküche'])
        self.assertEqual(uebersprungen, [])
        angelegt, uebersprungen = ra.gemeinschaft_anlegen(self.lg, {'Waschküche', 'Trockenraum'})
        self.assertEqual((angelegt, uebersprungen), (['Trockenraum'], ['Waschküche']))
        self.assertEqual(_raeume(self.lg), ['Trockenraum', 'Veloraum', 'Waschküche'])
        self.assertTrue(Ausstattung.objects.filter(liegenschaft=self.lg, raum='Waschküche', kategorie='Waschmaschine').exists())

    def test_wohnung_und_haus_bleiben_getrennt(self):
        ra.gemeinschaft_anlegen(self.lg, {'Waschküche'})
        ra.anlegen(self.e, {'Küche': 1})
        self.assertFalse(Ausstattung.objects.filter(einheit=self.e, raum='Waschküche').exists())
        self.assertFalse(Ausstattung.objects.filter(liegenschaft=self.lg, raum='Küche').exists())


class AnsichtTests(TestCase):
    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.basis = f'/neu/liegenschaften/{self.lg.id}/ausstattung/'

    def test_gemeinschaftsraeume_anlegen_und_anzeigen(self):
        r = self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche', 'Veloraum']})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_raeume(self.lg), ['Veloraum', 'Waschküche'])
        html = self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode()
        self.assertIn('Gemeinschaftsräume', html)
        self.assertIn('Waschküche', html)
        self.assertIn(f'action="/neu/liegenschaften/{self.lg.id}/ausstattung/raum-loeschen/"', html)

    def test_ohne_raeume_ist_der_block_offen(self):
        import re
        self.assertRegex(self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode(),
                         r'id="gemeinschaft-hinzufuegen"[^>]* open')
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche']})
        self.assertIsNone(re.search(r'id="gemeinschaft-hinzufuegen"[^>]* open',
                                    self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode()))

    def test_einzelraum_und_eigener_name(self):
        self.c.post(self.basis + 'katalog/', {'raumtyp': 'Waschküche', 'raumname': 'Waschküche Haus B'})
        self.assertEqual(_raeume(self.lg), ['Waschküche Haus B'])

    def test_wohnungstypen_gehen_nicht_ins_haus(self):
        self.c.post(self.basis + 'katalog/', {'raumtyp': 'Schlafzimmer'})
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Küche']})
        self.assertEqual(_raeume(self.lg), [])

    def test_element_im_raum_hinzufuegen_bearbeiten_loeschen(self):
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche']})
        r = self.c.post(self.basis, {'raum': 'Waschküche', 'kategorie': 'Wäschespinne', 'marke': 'Leifheit', 'neuwert': '120'})
        self.assertEqual(r.status_code, 302)
        a = Ausstattung.objects.get(liegenschaft=self.lg, kategorie='Wäschespinne')
        self.assertIsNone(a.einheit_id)
        r = self.c.post(f'/neu/ausstattung/{a.id}/bearbeiten/', {'raum': 'Waschküche', 'kategorie': 'Wäschespinne', 'marke': 'Brabantia'})
        self.assertRedirects(r, f'/neu/liegenschaften/{self.lg.id}/#gemeinschaft', fetch_redirect_response=False)
        a.refresh_from_db()
        self.assertEqual(a.marke, 'Brabantia')
        r = self.c.post(f'/neu/ausstattung/{a.id}/loeschen/')
        self.assertRedirects(r, f'/neu/liegenschaften/{self.lg.id}/#gemeinschaft', fetch_redirect_response=False)
        self.assertFalse(Ausstattung.objects.filter(pk=a.pk).exists())

    def test_raum_loeschen_nur_dieses_haus_und_dieser_raum(self):
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche', 'Veloraum']})
        ra.anlegen(self.e, {'Küche': 1})
        self.c.post(self.basis + 'raum-loeschen/', {'raum': 'Waschküche'})
        self.assertEqual(_raeume(self.lg), ['Veloraum'])
        self.assertTrue(Ausstattung.objects.filter(einheit=self.e, raum='Küche').exists())

    def test_get_aendert_nichts(self):
        self.c.get(self.basis + 'gemeinschaft/?typ=Waschküche')
        self.assertEqual(_raeume(self.lg), [])

    def test_wohnungsabnahme_enthaelt_keine_gemeinschaftsraeume(self):
        from rentals.models import Abnahmeprotokoll
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche']})
        self.c.post(f'/neu/vertraege/{_v_id(self)}/abnahme/vorort/', {'typ': 'einzug', 'raum': ['Wohnzimmer']})
        prot = Abnahmeprotokoll.objects.latest('id')
        self.assertFalse(prot.positionen.filter(ausstattung__liegenschaft=self.lg).exists())

    def test_ersatzplanung_nimmt_die_gemeinschaftsraeume_mit(self):
        from core.services.ersatzplanung import berechne_ersatzplanung
        self.c.post(self.basis + 'gemeinschaft/', {'typ': ['Waschküche']})
        ergebnis = berechne_ersatzplanung(aktive_lg=self.lg)
        zeilen = [z for z in ergebnis['rows'] if z.get('art') == 'raumbuch' and z['a'].liegenschaft_id == self.lg.id]
        self.assertTrue(zeilen)
        self.assertIn('Gemeinschaftsräume', zeilen[0]['standort'])
        self.assertIn('#gemeinschaft', zeilen[0]['ziel_url'])


def _v_id(test):
    from rentals.models import Mietvertrag
    return Mietvertrag.objects.filter(einheit=test.e).first().id


class FremdeVerwaltungTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_fremdes_haus_ist_404(self):
        c = Client()
        c.force_login(self.b.benutzer)
        for url, daten in ((f'/neu/liegenschaften/{self.a.liegenschaft.id}/ausstattung/gemeinschaft/', {'typ': ['Waschküche']}),
                           (f'/neu/liegenschaften/{self.a.liegenschaft.id}/ausstattung/katalog/', {'raumtyp': 'Waschküche'}),
                           (f'/neu/liegenschaften/{self.a.liegenschaft.id}/ausstattung/', {'raum': 'R', 'kategorie': 'K'}),
                           (f'/neu/liegenschaften/{self.a.liegenschaft.id}/ausstattung/raum-loeschen/', {'raum': 'R'})):
            with self.subTest(url=url):
                self.assertEqual(c.post(url, daten).status_code, 404)
        self.assertFalse(Ausstattung.alle_organisationen.filter(liegenschaft=self.a.liegenschaft).exists())
