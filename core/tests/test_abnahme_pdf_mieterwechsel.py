"""PDF der Abnahme (Bauteile, Vorzustand) und Mieterwechsel (Assistent, Entwürfe).

Der Mieterwechsel zählte jedes Protokoll als «Abnahme erfolgt» — auch einen Entwurf.
Mit dem Assistenten entsteht der Entwurf schon beim Einrichten, die Zeile wäre
sofort auf «Rücknahme erfolgt» gesprungen.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user
from .test_abnahme_kette import _protokoll, _vertrag_nachher


def _pdf_text(prot):
    import pdfplumber
    from core.services.abnahme_pdf import generate_abnahme_pdf
    pdf = generate_abnahme_pdf(prot)
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        return [(seite.extract_text() or '') for seite in d.pages]


class PdfTests(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()

    def test_pdf_zeigt_bauteile_mit_zustand_und_kommentar(self):
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [
            ('Küche', 'Backofen', 'uebermaessig', 'Brandfleck'), ('Küche', 'Boden', 'normal', ''),
            ('Bad', 'Dusche', 'io', ''), ('Bad', 'Lavabo', '', '')])
        text = '\n'.join(_pdf_text(prot))
        self.assertIn('Bewertete Bauteile', text)
        self.assertIn('Backofen', text)
        self.assertIn('Übermässig', text)
        self.assertIn('Brandfleck', text)
        self.assertIn('Neu i.O.', text)
        self.assertIn('offen', text)
        self.assertNotIn('Vorzustand', text)           # ohne Vorgänger keine Spalte
        self.assertNotIn('Baut auf', text)

    def test_pdf_zeigt_vorzustand_und_vorbestand_entscheid(self):
        einzug = _protokoll(self.v1, 'einzug', date(2021, 3, 1),
                            [('Küche', 'Backofen', 'uebermaessig', 'Brandfleck links')])
        auszug = _protokoll(self.v1, 'auszug', date(2026, 6, 30),
                            [('Küche', 'Backofen', 'uebermaessig', 'Brandfleck')])
        auszug.vorgaenger = einzug
        auszug.save()
        pos = auszug.positionen.get()
        pos.vorgaenger_position = einzug.positionen.get()
        pos.vorbestand_entscheid = 'vorbestehend'
        pos.save()
        text = '\n'.join(_pdf_text(auszug))
        self.assertIn('Baut auf: Einzug / Übergabe vom 01.03.2021', text)
        self.assertIn('Vorzustand', text)
        self.assertIn('[vorbestehend]', text)

    def test_langer_kommentar_bricht_um_statt_abgeschnitten_zu_werden(self):
        lang = 'Brandfleck neben dem Herd, ca. zwölf Zentimeter, Glaskeramik gesprungen'
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Herd', 'uebermaessig', lang)])
        text = ' '.join('\n'.join(_pdf_text(prot)).split())
        self.assertIn('Brandfleck neben dem Herd,', text)
        self.assertIn('Glaskeramik', text)               # steht in der zweiten Zeile, nicht abgeschnitten

    def test_klassisches_protokoll_ohne_bauteile_unveraendert(self):
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [])
        text = '\n'.join(_pdf_text(prot))
        self.assertNotIn('Bewertete Bauteile', text)
        self.assertIn('Festgestellte Mängel', text)

    def test_viele_bauteile_laufen_ueber_mehrere_seiten_und_die_unterschrift_bleibt_lesbar(self):
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30),
                          [('Raum', f'Bauteil {i:03d}', 'io', '') for i in range(120)])
        seiten = _pdf_text(prot)
        self.assertGreater(len(seiten), 1)
        text = '\n'.join(seiten)
        for i in (0, 59, 119):
            self.assertIn(f'Bauteil {i:03d}', text)
        self.assertEqual(text.count('Bauteil 0'), 100)      # 000–099 genau einmal je Zeile
        self.assertIn('Verwaltung', seiten[-1])             # Unterschriftszeile auf der letzten Seite

    def test_pdf_ueber_die_view_und_ablage_funktioniert_weiter(self):
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Küche', 'Boden', 'io', '')])
        c = Client(); c.force_login(_team_user())
        r = c.get(f'/neu/abnahme/{prot.id}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')


class DurchgefuehrtTests(TestCase):
    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()

    def test_entwurf_mit_bauteilen_zaehlt_nicht_klassisches_und_abgeschlossenes_schon(self):
        from core.services.abnahme_vorgaenger import durchgefuehrt
        entwurf = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('K', 'B', '', '')], abgeschlossen=False)
        self.assertEqual(durchgefuehrt(self.v1.abnahmen.all()).count(), 0)
        klassisch = _protokoll(self.v1, 'auszug', date(2026, 6, 1), [], abgeschlossen=False)  # altes Formular
        self.assertEqual({p.id for p in durchgefuehrt(self.v1.abnahmen.all())}, {klassisch.id})
        entwurf.abgeschlossen = True
        entwurf.save()
        self.assertEqual({p.id for p in durchgefuehrt(self.v1.abnahmen.all())}, {klassisch.id, entwurf.id})

    def test_keine_doppelten_zeilen_durch_den_join(self):
        from core.services.abnahme_vorgaenger import durchgefuehrt
        _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('K', f'B{i}', 'io', '') for i in range(5)])
        self.assertEqual(durchgefuehrt(self.v1.abnahmen.all()).count(), 1)

    def test_rueckgabedatum_der_nutzungsentschaedigung_ignoriert_entwuerfe(self):
        from core.services.nutzungsentschaedigung import rueckgabe_datum
        _protokoll(self.v1, 'auszug', date(2026, 7, 15), [('K', 'B', '', '')], abgeschlossen=False)
        self.assertIsNone(rueckgabe_datum(self.v1))
        _protokoll(self.v1, 'auszug', date(2026, 7, 31), [('K', 'B', 'io', '')])
        self.assertEqual(rueckgabe_datum(self.v1), date(2026, 7, 31))


class MieterwechselTests(TestCase):
    def setUp(self):
        from rentals.models import Kuendigung
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()
        Kuendigung.objects.create(vertrag=self.v1, status='erfasst', absender='mieter',
                                  per_datum=date.today() + timedelta(days=20))
        self.c = Client(); self.c.force_login(_team_user())

    def _seite(self):
        return self.c.get('/neu/mieterwechsel/').content.decode()

    def test_ruecknahme_fuehrt_in_den_assistenten(self):
        html = self._seite()
        self.assertIn(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/?typ=auszug', html)
        self.assertNotIn('abnahme/neu/?typ=auszug', html)

    def test_mit_nachmieter_ist_aus_und_einzug_vorbelegt_und_uebergabe_im_assistenten(self):
        v2 = _vertrag_nachher(self.einheit, beginn=date.today() + timedelta(days=21))
        html = self._seite()
        self.assertIn(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/?typ=beides', html)
        self.assertIn(f'/neu/vertraege/{v2.id}/abnahme/vorort/?typ=einzug', html)
        self.assertNotIn('abnahme/neu/?typ=einzug', html)

    def test_entwurf_laesst_die_zeile_offen_abschluss_schliesst_sie(self):
        self.c.post(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/', {'typ': 'auszug', 'raum': ['Küche']})
        self.assertIn('Rücknahme starten', self._seite())           # Entwurf: noch keine Rücknahme
        self.assertNotIn('Rücknahme erfolgt', self._seite())
        from rentals.models import Abnahmeprotokoll
        prot = Abnahmeprotokoll.objects.get()
        self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/', {})
        html = self._seite()
        self.assertNotIn(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/?typ=auszug', html)   # Knopf weg

    def test_klassisches_protokoll_zaehlt_weiter_als_erfolgt(self):
        _protokoll(self.v1, 'auszug', date.today(), [], abgeschlossen=False)
        self.assertNotIn(f'/neu/vertraege/{self.v1.id}/abnahme/vorort/?typ=auszug', self._seite())
