"""Zustandsvergleich: das Raumbuch folgt der Abnahme, Vorzustand und Veränderung je Bauteil.

Gegenproben:
* in `abschluss_folgen` den Aufruf `raumbuch_aktualisieren` entfernen -> `test_abschluss_fuehrt_das_raumbuch_nach` rot;
* in `raumbuch_aktualisieren` die Zeile mit `raumbuch_zustand_vorher = ...` entfernen -> `test_...merkt_sich_den_alten_wert` rot;
* in `vergleich` `jetzt > vor['rang']` umdrehen -> `test_vergleich_...` rot.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from core.services import zustandsvergleich as zv
from portfolio.models import Ausstattung
from rentals.models import Abnahmeprotokoll

from ._helfer import _basis_objekte, _team_user, abschluss_daten


def _element(einheit, zustand='gut', kategorie='Teppich', raum='Wohnzimmer'):
    return Ausstattung.objects.create(einheit=einheit, raum=raum, kategorie=kategorie, zustand=zustand,
                                      einbau_datum=date(2020, 3, 1), lebensdauer_jahre=10, neuwert=Decimal('1000'))


class Basis(TestCase):
    def setUp(self):
        _lg, self.einheit, _m, self.vertrag = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def protokoll(self, typ):
        self.c.post(f'/neu/vertraege/{self.vertrag.id}/abnahme/vorort/', {'typ': typ, 'raum': ['Wohnzimmer']})
        return Abnahmeprotokoll.objects.filter(vertrag=self.vertrag, typ=typ).latest('id')

    def bewerten(self, prot, zustand, kategorie='Teppich'):
        pos = prot.positionen.get(bezeichnung=kategorie)
        self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/', {'position': pos.id, 'zustand': zustand})
        return pos

    def abschliessen(self, prot):
        r = self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', abschluss_daten())
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen, 'Abschluss nicht durchgegangen')
        return r


class RaumbuchFolgtDerAbnahmeTests(Basis):
    def test_abschluss_fuehrt_das_raumbuch_nach(self):
        el = _element(self.einheit)
        prot = self.protokoll('einzug')
        self.bewerten(prot, 'normal')
        self.assertEqual(Ausstattung.objects.get(pk=el.pk).zustand, 'gut')      # vor dem Abschluss unverändert
        self.abschliessen(prot)
        self.assertEqual(Ausstattung.objects.get(pk=el.pk).zustand, 'gebraucht')

    def test_zuordnung_der_drei_stufen(self):
        self.assertEqual(zv.ZUSTAND_NACH_RAUMBUCH, {'io': 'neuwertig', 'normal': 'gebraucht', 'uebermaessig': 'defekt'})

    def test_raumbuch_merkt_sich_den_alten_wert(self):
        el = _element(self.einheit, zustand='neuwertig')            # von Hand gepflegt
        prot = self.protokoll('einzug')
        pos = self.bewerten(prot, 'uebermaessig')
        self.abschliessen(prot)
        pos.refresh_from_db()
        self.assertEqual(pos.raumbuch_zustand_vorher, 'neuwertig')
        self.assertEqual(Ausstattung.objects.get(pk=el.pk).zustand, 'defekt')

    def test_unbewertetes_bauteil_aendert_das_raumbuch_nicht(self):
        el = _element(self.einheit, zustand='gut')
        prot = self.protokoll('einzug')                              # nichts bewertet
        self.abschliessen(prot)
        self.assertEqual(Ausstattung.objects.get(pk=el.pk).zustand, 'gut')
        self.assertEqual(prot.positionen.get(bezeichnung='Teppich').raumbuch_zustand_vorher, '')

    def test_zweiter_aufruf_aendert_nichts(self):
        el = _element(self.einheit)
        prot = self.protokoll('einzug')
        self.bewerten(prot, 'normal')
        self.abschliessen(prot)
        self.assertEqual(zv.raumbuch_aktualisieren(prot), 0)
        self.assertEqual(prot.positionen.get(bezeichnung='Teppich').raumbuch_zustand_vorher, 'gut')
        self.assertEqual(Ausstattung.objects.get(pk=el.pk).zustand, 'gebraucht')


class VergleichTests(Basis):
    def test_vergleich_gleich_schlechter_besser_mit_vorgaenger_protokoll(self):
        _element(self.einheit)
        einzug = self.protokoll('einzug')
        self.bewerten(einzug, 'normal')
        self.abschliessen(einzug)
        auszug = self.protokoll('auszug')
        pos = auszug.positionen.get(bezeichnung='Teppich')
        self.assertEqual(pos.vorgaenger_position.protokoll_id, einzug.id)
        for neu, erwartet in (('normal', 'gleich'), ('uebermaessig', 'schlechter'), ('io', 'besser')):
            self.bewerten(auszug, neu)
            pos.refresh_from_db()
            self.assertEqual(zv.vergleich(pos), erwartet, neu)
        v = zv.vorzustand(pos)
        self.assertEqual((v['quelle'], v['rang']), ('protokoll', 1))

    def test_ohne_vorgaenger_gilt_der_raumbuch_stand(self):
        _element(self.einheit, zustand='gut')
        prot = self.protokoll('einzug')
        pos = self.bewerten(prot, 'normal')
        pos.refresh_from_db()
        v = zv.vorzustand(pos)
        self.assertEqual(v['quelle'], 'raumbuch')
        self.assertIn('Gut', v['text'])
        self.assertEqual(zv.vergleich(pos), 'schlechter')           # gut (0) -> normale Abnutzung (1)
        self.abschliessen(prot)
        pos.refresh_from_db()
        self.assertEqual(zv.vorzustand(pos)['quelle'], 'raumbuch')   # bleibt: aus raumbuch_zustand_vorher, nicht aus dem neuen Stand
        self.assertIn('Gut', zv.vorzustand(pos)['text'])

    def test_nicht_bewertet_oder_ohne_element_gibt_keinen_vergleich(self):
        prot = self.protokoll('einzug')                              # ohne Raumbuch: Standardbauteile
        pos = prot.positionen.first()
        self.assertIsNone(zv.vergleich(pos))
        self.assertIsNone(zv.vorzustand(pos))


class AnzeigeTests(Basis):
    def test_detailseite_zeigt_vorzustand_und_veraenderung(self):
        _element(self.einheit)
        einzug = self.protokoll('einzug')
        self.bewerten(einzug, 'normal')
        self.abschliessen(einzug)
        auszug = self.protokoll('auszug')
        self.bewerten(auszug, 'uebermaessig')
        r = self.c.get(f'/neu/abnahme/{auszug.id}/')
        self.assertContains(r, 'Veränderung')
        self.assertContains(r, 'schlechter')

    def test_vorort_zeigt_raumbuch_zustand_ohne_vorgaenger(self):
        _element(self.einheit, zustand='gebraucht')
        prot = self.protokoll('einzug')
        r = self.c.get(f'/neu/abnahme/{prot.id}/vorort/')
        self.assertContains(r, 'Gebraucht')

    def test_pdf_wird_mit_vergleich_erzeugt(self):
        _element(self.einheit)
        einzug = self.protokoll('einzug')
        self.bewerten(einzug, 'normal')
        self.abschliessen(einzug)
        auszug = self.protokoll('auszug')
        self.bewerten(auszug, 'uebermaessig')
        r = self.c.get(f'/neu/abnahme/{auszug.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_raumbuch_zeigt_den_verlauf_je_element(self):
        el = _element(self.einheit)
        prot = self.protokoll('einzug')
        self.bewerten(prot, 'normal')
        self.abschliessen(prot)
        r = self.c.get(f'/neu/objekte/{self.einheit.id}/?tab=ausstattung')
        self.assertContains(r, '1 Abnahme')
        self.assertContains(r, 'Raumbuch vorher')
        self.assertEqual(len(zv.verlauf_je_element(self.einheit)[el.id]), 1)
