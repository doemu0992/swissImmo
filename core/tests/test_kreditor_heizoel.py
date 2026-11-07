"""Heizöl-Menge an der Kreditorenrechnung (`KreditorenRechnung.menge_liter`).

Befund beim Entfernen der Django-Admin (07.11.2026): Der Wächter `test_felder_ohne_eingabe` fand das Feld ohne Eingabemaske.
Die Nebenkostenabrechnung liest es (Öl-Einkäufe in `core/utils/billing.py`, Chip im NK-Wizard), eingeben liess es sich nur
in der Admin. Jetzt steht es im Erfassen- und im Bearbeiten-Formular.

Gegenprobe: `menge_liter` aus `KreditorForm` oder aus den beiden Ansichten (`aktionen.py`) streichen -> `test_erfassen_*`
bzw. `test_bearbeiten_*` rot; die Eingabe im Template streichen -> `test_die_felder_stehen_in_beiden_formularen` rot.
"""
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class HeizoelMengeTests(TestCase):
    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _daten(self, **ueber):
        daten = {'lieferant': 'Oel AG', 'betrag': '1500.00', 'mwst_satz': '8.1',
                 'datum': '2026-09-01', 'liegenschaft_id': str(self.lg.id)}
        daten.update(ueber)
        return daten

    def test_erfassen_speichert_die_menge(self):
        from finance.models import KreditorenRechnung
        r = self.c.post('/neu/kreditoren/neu/', self._daten(menge_liter="2'500.50"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(KreditorenRechnung.objects.latest('pk').menge_liter, Decimal('2500.50'))

    def test_ohne_menge_bleibt_sie_leer(self):
        from finance.models import KreditorenRechnung
        self.c.post('/neu/kreditoren/neu/', self._daten())
        self.assertIsNone(KreditorenRechnung.objects.latest('pk').menge_liter)

    def test_unlesbare_oder_negative_menge_ist_ein_feldfehler(self):
        from finance.models import KreditorenRechnung
        vorher = KreditorenRechnung.objects.count()
        for roh in ('viel', '-5'):
            with self.subTest(menge=roh):
                r = self.c.post('/neu/kreditoren/neu/', self._daten(menge_liter=roh))
                self.assertEqual(r.status_code, 400)
                self.assertIn('id="kr-liter_fehler"', r.content.decode())
        self.assertEqual(KreditorenRechnung.objects.count(), vorher)

    def test_bearbeiten_setzt_und_leert_die_menge(self):
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Oel AG', betrag=Decimal('900'), status='neu')
        r = self.c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {'lieferant': 'Oel AG', 'betrag': '900',
                                                                 'menge_liter': '1200'})
        self.assertEqual(r.status_code, 302)
        k.refresh_from_db()
        self.assertEqual(k.menge_liter, Decimal('1200.00'))
        self.c.post(f'/neu/kreditoren/{k.id}/bearbeiten/', {'lieferant': 'Oel AG', 'betrag': '900', 'menge_liter': ''})
        k.refresh_from_db()
        self.assertIsNone(k.menge_liter)

    def test_bearbeiten_zeigt_die_gespeicherte_menge_an(self):
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Oel AG', betrag=Decimal('900'), status='neu',
                                              menge_liter=Decimal('1200.00'))
        body = self.c.get('/neu/kreditoren/').content.decode()
        self.assertIn(f'id="kc-liter-{k.id}"', body)
        self.assertIn('value="1200.00"', body)

    def test_die_felder_stehen_in_beiden_formularen(self):
        body = self.c.get('/neu/kreditoren/').content.decode()
        self.assertIn('id="kr-liter"', body)                  # Erfassen
        self.assertIn('name="menge_liter"', body)
