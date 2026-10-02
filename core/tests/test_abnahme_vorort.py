"""Abnahme vor Ort (Telefon): Ampel je Bauteil, Mangel und Zeitwert, Abschluss.

Die Ampel «Übermässige Abnutzung» ist der einzige Zustand, der etwas kostet:
Er erzeugt den Mangel, an dem die Zeitwert-Rechnung hängt (core/services/
zeitwert.py). «Normale Abnutzung» ist Vermietersache und bleibt bei 0.
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user
from ._isolation import MandantenFixture


def _element(einheit, einbau=date(2020, 3, 1), jahre=10, kategorie='Teppich', raum='Wohnzimmer'):
    from portfolio.models import Ausstattung
    return Ausstattung.objects.create(einheit=einheit, raum=raum, kategorie=kategorie,
                                      einbau_datum=einbau, lebensdauer_jahre=jahre,
                                      neuwert=Decimal('1000'))


class VorOrtTests(TestCase):

    def setUp(self):
        self.lg, self.einheit, _m, self.vertrag = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())

    def _start(self, typ='auszug'):
        return self.c.post(f'/neu/vertraege/{self.vertrag.id}/abnahme/vorort/', {'typ': typ})

    def _protokoll(self, typ='auszug'):
        from rentals.models import Abnahmeprotokoll
        self._start(typ)
        return Abnahmeprotokoll.objects.get(vertrag=self.vertrag, typ=typ)

    def _speichern(self, prot, pos, **daten):
        return self.c.post(f'/neu/abnahme/{prot.id}/vorort/position/',
                           {'position': pos.id, **daten})

    # --- Start -----------------------------------------------------------
    def test_start_legt_positionen_aus_dem_raumbuch_an(self):
        _element(self.einheit)
        _element(self.einheit, kategorie='Wände / Anstrich', jahre=8)
        prot = self._protokoll()
        self.assertEqual([p.bezeichnung for p in prot.positionen.all()],
                         ['Teppich', 'Wände / Anstrich'])
        self.assertEqual({p.zustand for p in prot.positionen.all()}, {''})

    def test_start_ohne_raumbuch_nimmt_standardbauteile(self):
        from core.views.fw.abnahme import VORORT_BAUTEILE, VORORT_STANDARDRAEUME
        prot = self._protokoll()
        self.assertEqual(prot.positionen.count(), len(VORORT_BAUTEILE) * len(VORORT_STANDARDRAEUME))

    def test_start_ist_nur_post_und_setzt_den_entwurf_fort(self):
        from rentals.models import Abnahmeprotokoll
        r = self.c.get(f'/neu/vertraege/{self.vertrag.id}/abnahme/vorort/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Abnahmeprotokoll.objects.count(), 0)     # GET legt nichts an
        self._start(); self._start()
        self.assertEqual(Abnahmeprotokoll.objects.count(), 1)     # zweiter Start: derselbe Entwurf

    def test_seite_rendert_raum_und_abschluss(self):
        _element(self.einheit)
        prot = self._protokoll()
        r = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=0')
        self.assertContains(r, 'Teppich')
        self.assertContains(r, 'Übermässige Abnutzung')
        r = self.c.get(f'/neu/abnahme/{prot.id}/vorort/?r=1')      # Abschluss
        self.assertContains(r, 'Abnahme abschliessen')
        self.assertContains(r, 'Noch nicht bewertet: 1')

    # --- Ampel → Mangel → Zeitwert --------------------------------------
    def test_uebermaessig_erzeugt_mangel_mit_zeitwert(self):
        # Teppich 10 J., Einbau 1.3.2020; Abnahme 1.3.2026 → 40 % von 1000
        el = _element(self.einheit)
        prot = self._protokoll()
        prot.datum = date(2026, 3, 1); prot.save()
        pos = prot.positionen.get()
        r = self._speichern(prot, pos, zustand='uebermaessig', kosten='1000', kommentar='Brandfleck')
        self.assertEqual(r.status_code, 200)
        pos.refresh_from_db()
        m = pos.mangel
        self.assertEqual((m.verursacher, m.ausstattung_id), ('mieter', el.id))
        self.assertEqual(m.beschreibung, 'Teppich: Brandfleck')
        self.assertEqual(m.mieteranteil, Decimal('400.00'))
        self.assertEqual(prot.kosten_mieter_total, Decimal('400.00'))

    def test_zurueck_auf_normal_entfernt_den_mangel(self):
        from rentals.models import AbnahmeMangel
        _element(self.einheit)
        prot = self._protokoll()
        pos = prot.positionen.get()
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        self.assertEqual(AbnahmeMangel.objects.count(), 1)
        self._speichern(prot, pos, zustand='normal')
        self.assertEqual(AbnahmeMangel.objects.count(), 0)
        pos.refresh_from_db()
        self.assertIsNone(pos.mangel)

    def test_normale_abnutzung_kostet_nichts(self):
        from rentals.models import AbnahmeMangel
        _element(self.einheit)
        prot = self._protokoll()
        self._speichern(prot, prot.positionen.get(), zustand='normal', kosten='500')
        self.assertEqual(AbnahmeMangel.objects.count(), 0)
        self.assertEqual(prot.kosten_mieter_total, Decimal('0.00'))

    def test_abgelaufene_lebensdauer_null_ausser_bei_absicht(self):
        _element(self.einheit, einbau=date(2010, 1, 1), jahre=8, kategorie='Wände / Anstrich')
        prot = self._protokoll()
        prot.datum = date(2026, 6, 30); prot.save()
        pos = prot.positionen.get()
        self._speichern(prot, pos, zustand='uebermaessig', kosten='1800')
        pos.refresh_from_db()
        self.assertEqual(pos.mangel.mieteranteil, Decimal('0.00'))
        self._speichern(prot, pos, vorsatz='1')
        pos.refresh_from_db()
        self.assertEqual(pos.mangel.mieteranteil, Decimal('1800.00'))

    def test_beim_einzug_ist_der_mangel_kein_mieterschaden(self):
        _element(self.einheit)
        prot = self._protokoll('einzug')
        pos = prot.positionen.get()
        self._speichern(prot, pos, zustand='uebermaessig', kosten='500')
        pos.refresh_from_db()
        self.assertEqual(pos.mangel.verursacher, 'vermieter')
        self.assertEqual(pos.mangel.mieteranteil, Decimal('0.00'))

    def test_ungueltiger_zustand_und_kosten_werden_abgelehnt(self):
        _element(self.einheit)
        prot = self._protokoll()
        pos = prot.positionen.get()
        self.assertEqual(self._speichern(prot, pos, zustand='rot').status_code, 400)
        self.assertEqual(self._speichern(prot, pos, kosten='viel').status_code, 400)
        pos.refresh_from_db()
        self.assertEqual(pos.zustand, '')

    def test_foto_wird_gespeichert_und_dem_mangel_mitgegeben(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        _element(self.einheit)
        prot = self._protokoll()
        pos = prot.positionen.get()
        buf = io.BytesIO(); Image.new('RGB', (4, 4), 'red').save(buf, 'JPEG')
        self._speichern(prot, pos, zustand='uebermaessig', kosten='100',
                        foto=SimpleUploadedFile('foto.jpg', buf.getvalue(), 'image/jpeg'))
        pos.refresh_from_db()
        self.assertIn('organisation/', pos.foto.name)         # Ablage je Verwaltung
        self.assertEqual(pos.mangel.foto.name, pos.foto.name)

    def test_position_eines_anderen_protokolls_derselben_verwaltung_ist_404(self):
        """Gleiche Verwaltung, anderes Protokoll: nur `protokoll=prot` im Lookup hält das auf."""
        _element(self.einheit)
        prot1 = self._protokoll('auszug')
        prot2 = self._protokoll('einzug')
        fremd = prot2.positionen.get()
        r = self._speichern(prot1, fremd, zustand='io')
        self.assertEqual(r.status_code, 404)
        fremd.refresh_from_db()
        self.assertEqual(fremd.zustand, '')

    # --- Abschluss -------------------------------------------------------
    def test_abschliessen_sperrt_das_protokoll(self):
        _element(self.einheit)
        prot = self._protokoll()
        pos = prot.positionen.get()
        r = self.c.post(f'/neu/abnahme/{prot.id}/vorort/abschliessen/',
                        {'zaehler_strom': '1234', 'schluessel_anzahl': '3',
                         'unterschrift_mieter': 'Hans Muster'})
        self.assertRedirects(r, f'/neu/abnahme/{prot.id}/', fetch_redirect_response=False)
        prot.refresh_from_db()
        self.assertTrue(prot.abgeschlossen)
        self.assertEqual((prot.zaehler_strom, prot.schluessel_anzahl), ('1234', 3))
        self.assertEqual(self._speichern(prot, pos, zustand='io').status_code, 409)
        self.assertEqual(self.c.get(f'/neu/abnahme/{prot.id}/vorort/').status_code, 302)


class VorOrtMandantenTests(TestCase):
    """Die Grenze wird aktiv verletzt: A greift auf das Protokoll von B."""

    @classmethod
    def setUpTestData(cls):
        from core.tenancy import organisation_kontext
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        from core.views.fw.abnahme import _vorort_positionen_anlegen
        from rentals.models import Abnahmeprotokoll
        with organisation_kontext(cls.b.organisation):
            cls.prot_b = Abnahmeprotokoll.objects.create(vertrag=cls.b.vertrag, typ='auszug',
                                                         datum=date(2026, 6, 30))
            _vorort_positionen_anlegen(cls.prot_b)
            cls.pos_b = cls.prot_b.positionen.first()

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def test_fremdes_protokoll_ist_404(self):
        self.assertEqual(self.c.get(f'/neu/abnahme/{self.prot_b.id}/vorort/').status_code, 404)

    def test_fremde_position_ist_404_und_bleibt_unveraendert(self):
        r = self.c.post(f'/neu/abnahme/{self.prot_b.id}/vorort/position/',
                        {'position': self.pos_b.id, 'zustand': 'uebermaessig'})
        self.assertEqual(r.status_code, 404)
        self.pos_b.refresh_from_db()
        self.assertEqual(self.pos_b.zustand, '')

    def test_fremdes_protokoll_abschliessen_ist_404(self):
        r = self.c.post(f'/neu/abnahme/{self.prot_b.id}/vorort/abschliessen/', {})
        self.assertEqual(r.status_code, 404)
        self.prot_b.refresh_from_db()
        self.assertFalse(self.prot_b.abgeschlossen)

    def test_fremden_vertrag_starten_ist_404(self):
        r = self.c.post(f'/neu/vertraege/{self.b.vertrag.id}/abnahme/vorort/', {'typ': 'auszug'})
        self.assertEqual(r.status_code, 404)


class VorOrtDetailTests(TestCase):
    def test_detailseite_zeigt_auch_unbeanstandete_bauteile(self):
        lg, einheit, _m, vertrag = _basis_objekte()
        _element(einheit)
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/vertraege/{vertrag.id}/abnahme/vorort/', {'typ': 'auszug'})
        from rentals.models import Abnahmeprotokoll
        prot = Abnahmeprotokoll.objects.get(vertrag=vertrag)
        pos = prot.positionen.get()
        c.post(f'/neu/abnahme/{prot.id}/vorort/position/', {'position': pos.id, 'zustand': 'io'})
        r = c.get(f'/neu/abnahme/{prot.id}/')
        self.assertContains(r, 'Bewertete Bauteile')
        self.assertContains(r, 'Neu i.O.')
