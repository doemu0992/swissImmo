"""Etappe 1 aus docs/AUDIT-SAAS-NIVEAU.md: fertige Funktionen ohne Einstieg.

Jede dieser Funktionen war gebaut und getestet — aber für einen Menschen nicht
auffindbar. Die Tests halten den EINSTIEG fest, nicht die Funktion selbst; die
hat ihre eigenen Tests.
"""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, Client, override_settings

from ._helfer import _team_user, _basis_objekte


def _pdf_text(inhalt):
    """Der Seitentext eines PDF — die Streams sind komprimiert, ein Suchen in
    den Rohbytes fände nichts."""
    import io
    from pypdf import PdfReader
    return ''.join(s.extract_text() for s in PdfReader(io.BytesIO(inhalt)).pages)


@override_settings(PORTAL_BASE_URL='https://app.beispiel.ch/')
class Bewerbungslink(TestCase):
    """F1: Das öffentliche Bewerbungsformular hatte keinen Weg in die Welt."""

    def setUp(self):
        _lg, self.e, _m, _v = _basis_objekte()
        self.e.zur_ausschreibung = True
        self.e.save()
        self.c = Client()
        self.c.force_login(_team_user())

    def test_vermarktung_zeigt_link_und_qr(self):
        body = self.c.get('/neu/vermarktung/').content.decode()
        link = f'https://app.beispiel.ch/bewerben/{self.e.id}/'
        self.assertIn(f'value="{link}"', body)
        qr = body[body.index('QR-Code anzeigen'):]
        self.assertIn('<svg', qr)
        # Weisser Grund IM SVG: sonst stünde der schwarze Code im Dunkelmodus
        # auf dunkler Fläche und wäre kaum scannbar.
        self.assertIn('<path fill="#fff"', qr[:qr.index('</svg>')])

    def test_link_fuehrt_auf_das_offene_formular(self):
        r = Client().get(f'/bewerben/{self.e.id}/')
        self.assertEqual(r.status_code, 200)

    def test_expose_nur_mit_qr_solange_ausgeschrieben(self):
        from core.services.expose import generate_expose_pdf
        mit = generate_expose_pdf(self.e, None, bewerbung_url='https://app.beispiel.ch/bewerben/1/')
        ohne = generate_expose_pdf(self.e, None)
        self.assertIn('Online bewerben', _pdf_text(mit))
        self.assertNotIn('Online bewerben', _pdf_text(ohne))

    def test_expose_ansicht_haengt_qr_an(self):
        r = self.c.get(f'/neu/vermarktung/{self.e.id}/expose/')
        self.assertIn('Online bewerben', _pdf_text(r.content))
        self.e.zur_ausschreibung = False
        self.e.save()
        r = self.c.get(f'/neu/vermarktung/{self.e.id}/expose/')
        self.assertNotIn('Online bewerben', _pdf_text(r.content))


class RuegeKnopf(TestCase):
    """F2: Die Mängelrüge nach Art. 267a OR hatte keinen Knopf."""

    def _protokoll(self, typ, verursacher):
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, _e, _m, v = _basis_objekte()
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ=typ, datum=date.today())
        AbnahmeMangel.objects.create(protokoll=prot, raum='Küche', beschreibung='Kochfeld',
                                     verursacher=verursacher, kostenschaetzung=Decimal('400'))
        c = Client(); c.force_login(_team_user())
        return prot, c.get(f'/neu/abnahme/{prot.id}/').content.decode()

    def test_auszug_mit_mietermangel_zeigt_knopf(self):
        prot, body = self._protokoll('auszug', 'mieter')
        self.assertIn(f'action="/neu/abnahme/{prot.id}/ruege-267a/"', body)

    def test_ohne_mietermangel_kein_knopf(self):
        prot, body = self._protokoll('auszug', 'abnutzung')
        self.assertNotIn('ruege-267a', body)

    def test_einzug_kein_knopf(self):
        prot, body = self._protokoll('einzug', 'mieter')
        self.assertNotIn('ruege-267a', body)


class Einstiege(TestCase):

    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()
        self.c = Client()
        self.user = _team_user()
        self.c.force_login(self.user)

    def test_lebensdauer_aus_einstellungen_und_ersatzplanung(self):
        """F3."""
        for seite in ('/neu/einstellungen/', '/neu/ersatzplanung/'):
            self.assertIn('href="/neu/lebensdauer/"', self.c.get(seite).content.decode(), seite)

    def test_hausaushang_fuer_team_ohne_staff(self):
        """F4: Vorher `staff_member_required` — ein Verwalter landete im Admin-Login."""
        self.assertFalse(self.user.is_staff)
        body = self.c.get(f'/neu/liegenschaften/{self.lg.id}/').content.decode()
        self.assertIn(f'href="/liegenschaft/{self.lg.id}/poster/"', body)
        r = self.c.get(f'/liegenschaft/{self.lg.id}/poster/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_hausaushang_nicht_ohne_anmeldung(self):
        r = Client().get(f'/liegenschaft/{self.lg.id}/poster/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])


class FallAkte(TestCase):
    """Die Fallakte nannte ihre Akte nur als Text."""

    def test_jeder_zulaessige_aktentyp_hat_ein_ziel(self):
        from faelle.models import Fall
        from core.views.fw.arbeit import AKTE_PFADE
        self.assertEqual(set(AKTE_PFADE), set(Fall.AKTENTYPEN))

    def test_fallakte_verlinkt_ihre_akte(self):
        from faelle.models import Fall, Fallart, SchrittVorlage
        _lg, _e, _m, v = _basis_objekte()
        art = Fallart(organisation=v.organisation, schluessel='test', bezeichnung='Prüfung')
        art.save()
        SchrittVorlage(fallart=art, nr=1, etappe_nr=1, etappe='E', bezeichnung='S').save()
        fall = Fall(organisation=v.organisation, fallart=art, akte=v, betreff='Test')
        fall.save()
        c = Client(); c.force_login(_team_user())
        body = c.get(f'/neu/faelle/{fall.id}/').content.decode()
        self.assertIn(f'href="/neu/vertraege/{v.id}/"', body)
