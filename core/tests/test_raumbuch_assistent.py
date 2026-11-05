"""Raumbuch: Raumname getrennt vom Typ, Assistent aus der Zimmerzahl, Raum löschen.

Gegenproben:
* `NUMMERIERT = ()` (raumkatalog) -> `test_zimmer_werden_durchnummeriert` und der Assistent-Test rot (zweites Zimmer fehlt).
* in `fw_ausstattung_raum_loeschen` den Filter `raum=raum` entfernen -> `test_raum_loeschen_nur_dieser_raum` rot.
* in `vorschlag` `ganz - 1` durch `ganz` ersetzen -> `test_vorschlag_*` rot.
"""
from decimal import Decimal

from django.test import Client, TestCase

from core.services import raumbuch_assistent as ra
from portfolio.models import Ausstattung

from ._helfer import _basis_objekte, _team_user


def _raeume(einheit):
    return list(dict.fromkeys(Ausstattung.objects.filter(einheit=einheit).order_by('raum').values_list('raum', flat=True)))


class VorschlagTests(TestCase):
    def test_vorschlag_dreieinhalb_zimmer(self):
        v = ra.vorschlag(Decimal('3.5'))
        self.assertEqual((v['Wohnzimmer'], v['Schlafzimmer'], v['Zimmer']), (1, 2, 1))
        self.assertEqual(v['Gäste-WC'], 0)

    def test_vorschlag_ganze_zahl_und_grosse_wohnung(self):
        self.assertEqual(ra.vorschlag(4)['Schlafzimmer'], 3)
        self.assertEqual(ra.vorschlag(4)['Zimmer'], 0)
        self.assertEqual(ra.vorschlag('5')['Gäste-WC'], 1)

    def test_vorschlag_studio_ohne_schlafzimmer_und_ohne_angabe(self):
        self.assertEqual(ra.vorschlag(1)['Schlafzimmer'], 0)
        self.assertEqual(ra.vorschlag(None)['Schlafzimmer'], 2)     # ohne Angabe: 3 Zimmer

    def test_tabelle_fuer_die_seite_hat_jede_halbe_zimmerzahl(self):
        t = ra.vorschlaege_je_zimmerzahl()
        self.assertEqual(list(t)[:3], ['1', '1.5', '2'])
        self.assertIn('3.5', t)
        self.assertEqual(t['3.5'], ra.vorschlag(Decimal('3.5')))


class NamenTests(TestCase):
    def test_nummerierte_typen_zaehlen_weiter(self):
        self.assertEqual(ra.neue_namen('Schlafzimmer', 2, []), ['Schlafzimmer 1', 'Schlafzimmer 2'])
        self.assertEqual(ra.neue_namen('Schlafzimmer', 1, ['Schlafzimmer 1', 'Schlafzimmer 2']), ['Schlafzimmer 3'])
        self.assertEqual(ra.neue_namen('Zimmer', 1, ['Zimmer']), ['Zimmer 2'])      # «Zimmer» ohne Zahl zählt als 1

    def test_einmalige_typen_nur_einmal(self):
        self.assertEqual(ra.neue_namen('Küche', 1, []), ['Küche'])
        self.assertEqual(ra.neue_namen('Küche', 1, ['küche']), [])


class KatalogLadenTests(TestCase):
    def setUp(self):
        _lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.url = f'/neu/objekte/{self.e.id}/ausstattung/katalog/'

    def test_zimmer_werden_durchnummeriert(self):
        for _ in range(3):
            self.c.post(self.url, {'raumtyp': 'Zimmer'})
        self.assertEqual(_raeume(self.e), ['Zimmer 1', 'Zimmer 2', 'Zimmer 3'])

    def test_schlafzimmer_ist_ein_eigener_typ(self):
        self.c.post(self.url, {'raumtyp': 'Schlafzimmer'})
        self.c.post(self.url, {'raumtyp': 'Schlafzimmer'})
        self.assertEqual(_raeume(self.e), ['Schlafzimmer 1', 'Schlafzimmer 2'])
        self.assertTrue(Ausstattung.objects.filter(einheit=self.e, raum='Schlafzimmer 1', kategorie='Einbauschrank').exists())

    def test_eigener_name_gilt_woertlich(self):
        self.c.post(self.url, {'raumtyp': 'Zimmer', 'raumname': '  Büro  '})
        self.assertEqual(_raeume(self.e), ['Büro'])

    def test_gaeste_wc_und_kellerabteil_gibt_es(self):
        self.c.post(self.url, {'raumtyp': 'Gäste-WC'})
        self.c.post(self.url, {'raumtyp': 'Kellerabteil'})
        self.assertEqual(_raeume(self.e), ['Gäste-WC', 'Kellerabteil'])

    def test_einmaliger_typ_wird_nicht_verdoppelt(self):
        self.c.post(self.url, {'raumtyp': 'Küche'})
        n = Ausstattung.objects.filter(einheit=self.e).count()
        self.c.post(self.url, {'raumtyp': 'Küche'})
        self.assertEqual(Ausstattung.objects.filter(einheit=self.e).count(), n)


class AssistentTests(TestCase):
    def setUp(self):
        _lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.url = f'/neu/objekte/{self.e.id}/ausstattung/assistent/'

    def _formular(self, **anzahl):
        return {f'anzahl_{typ}': str(n) for typ, n in anzahl.items()}

    def test_dreieinhalb_zimmer_wohnung(self):
        plan = ra.vorschlag(Decimal('3.5'))
        r = self.c.post(self.url, {f'anzahl_{t}': str(n) for t, n in plan.items()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_raeume(self.e), sorted([
            'Küche', 'Wohnzimmer', 'Schlafzimmer 1', 'Schlafzimmer 2', 'Zimmer 1', 'Bad / WC',
            'Korridor / Entrée', 'Balkon / Terrasse', 'Kellerabteil']))
        # Standard-Ausstattung je Raum geladen, mit Lebensdauer
        herd = Ausstattung.objects.get(einheit=self.e, raum='Küche', kategorie='Kochherd / Glaskeramik')
        self.assertEqual(herd.lebensdauer_jahre, 15)

    def test_vorhandene_raeume_bleiben_und_werden_nicht_verdoppelt(self):
        self.c.post(f'/neu/objekte/{self.e.id}/ausstattung/katalog/', {'raumtyp': 'Küche'})
        n_kueche = Ausstattung.objects.filter(einheit=self.e, raum='Küche').count()
        self.c.post(self.url, self._formular(**{'Küche': 1, 'Schlafzimmer': 1}))
        self.assertEqual(Ausstattung.objects.filter(einheit=self.e, raum='Küche').count(), n_kueche)
        self.assertIn('Schlafzimmer 1', _raeume(self.e))

    def test_zweiter_lauf_ergaenzt_schlafzimmer_statt_zu_ueberschreiben(self):
        self.c.post(self.url, self._formular(Schlafzimmer=2))
        self.c.post(self.url, self._formular(Schlafzimmer=1))
        self.assertEqual(_raeume(self.e), ['Schlafzimmer 1', 'Schlafzimmer 2', 'Schlafzimmer 3'])

    def test_ohne_auswahl_und_mit_unsinn_wird_nichts_angelegt(self):
        self.c.post(self.url, {})
        self.c.post(self.url, {'anzahl_Zimmer': 'abc', 'anzahl_Unbekannt': '5', 'anzahl_Küche': '-1'})
        self.assertEqual(_raeume(self.e), [])

    def test_obergrenze_je_typ(self):
        self.c.post(self.url, {'anzahl_Zimmer': '99'})
        self.assertEqual(len(_raeume(self.e)), ra.MAX_JE_TYP)

    def test_get_legt_nichts_an(self):
        self.c.get(self.url)
        self.assertEqual(_raeume(self.e), [])


class RaumLoeschenTests(TestCase):
    def setUp(self):
        _lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.url = f'/neu/objekte/{self.e.id}/ausstattung/raum-loeschen/'
        for typ in ('Zimmer', 'Zimmer', 'Küche'):
            self.c.post(f'/neu/objekte/{self.e.id}/ausstattung/katalog/', {'raumtyp': typ})

    def test_raum_loeschen_nur_dieser_raum(self):
        self.assertEqual(_raeume(self.e), ['Küche', 'Zimmer 1', 'Zimmer 2'])
        r = self.c.post(self.url, {'raum': 'Zimmer 2'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_raeume(self.e), ['Küche', 'Zimmer 1'])
        self.assertGreater(Ausstattung.objects.filter(einheit=self.e, raum='Zimmer 1').count(), 5)

    def test_get_loescht_nichts(self):
        self.c.get(self.url + '?raum=Zimmer+1')
        self.assertEqual(len(_raeume(self.e)), 3)

    def test_unbekannter_raum_ist_harmlos(self):
        r = self.c.post(self.url, {'raum': 'Gibt es nicht'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(_raeume(self.e)), 3)

    def test_die_seite_zeigt_assistent_und_raum_loeschen(self):
        r = self.c.get(f'/neu/objekte/{self.e.id}/')
        self.assertContains(r, 'Raumbuch-Assistent')
        self.assertContains(r, 'ausstattung/raum-loeschen/')
        self.assertContains(r, 'anzahl_Schlafzimmer')
