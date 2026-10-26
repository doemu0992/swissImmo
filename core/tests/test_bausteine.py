"""Bausteine V11: Assistent, Prozessleiste, In-App-Hilfe (UI-Analyse 26.10.2026).

Geprüft wird, was die Bausteine versprechen:
- Jeder `{% hilfe 'x' %}`, den eine Vorlage nennt, steht im Katalog — ein
  Tippfehler zeichnet sonst still nichts. Jeder Eintrag ist übersetzt.
- Die Prozessleiste der Nebenkosten leitet ihre Zustände aus den Werten der
  Detailansicht ab und zeigt auf Seiten, die es gibt.
- Die Assistenten sind reine Darstellung: Ohne JavaScript ist es dasselbe
  Formular mit denselben Feldnamen, und Speichern legt an wie vorher.
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.template import Context, Template
from django.test import Client, SimpleTestCase, TestCase
from django.urls import resolve
from django.utils import translation

from core.hilfe import HILFE
from core.tests._helfer import _basis_objekte, _seed_konten, _team_user, _test_organisation

VORLAGEN = Path(__file__).resolve().parents[1] / 'templates'
HILFE_TAG = re.compile(r"""{%\s*hilfe\s+['"]([^'"]+)['"]\s*%}""")


class HilfeKatalogTests(SimpleTestCase):
    def test_jeder_schluessel_einer_vorlage_steht_im_katalog(self):
        genutzt = {}
        for datei in VORLAGEN.rglob('*.html'):
            for schluessel in HILFE_TAG.findall(datei.read_text(encoding='utf-8')):
                genutzt.setdefault(schluessel, datei.name)
        self.assertGreater(len(genutzt), 20, 'Die Suche findet die Hilfe-Tags nicht mehr.')
        fehlend = {k: v for k, v in genutzt.items() if k not in HILFE}
        self.assertEqual(fehlend, {}, 'Hilfe-Schlüssel ohne Katalogeintrag.')

    def test_jede_vorlage_mit_hilfe_laedt_den_tag(self):
        for datei in VORLAGEN.rglob('*.html'):
            text = datei.read_text(encoding='utf-8')
            if HILFE_TAG.search(text):
                with self.subTest(vorlage=datei.name):
                    self.assertRegex(text, r'{%\s*load[^%]*\bhilfe\b')

    def test_jeder_eintrag_ist_in_allen_sprachen_uebersetzt(self):
        for sprache in ('fr', 'it', 'en'):
            with translation.override(sprache):
                for schluessel, (titel, text) in HILFE.items():
                    with self.subTest(sprache=sprache, schluessel=schluessel):
                        with translation.override('de'):
                            titel_de, text_de = str(titel), str(text)
                        # Titel wie «pain.001» oder «EGID / EWID» heissen überall gleich.
                        if not re.fullmatch(r'[A-Za-z0-9./ -]+', titel_de):
                            self.assertNotEqual(str(titel), titel_de)
                        self.assertNotEqual(str(text), text_de)

    def test_tag_zeichnet_knopf_und_text(self):
        html = Template("{% load hilfe %}{% hilfe 'akonto' %}").render(Context())
        self.assertIn('class="fw-hilfe-knopf"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('class="fw-hilfe-text"', html)
        self.assertIn(str(HILFE['akonto'][1])[:30], html)

    def test_unbekannter_schluessel_zeichnet_nichts(self):
        with self.assertLogs('core.templatetags.hilfe', level='WARNING'):
            html = Template("{% load hilfe %}{% hilfe 'gibt_es_nicht' %}").render(Context())
        self.assertEqual(html, '')


class _Periode:
    """Ersatz mit genau den Feldern, die `schritte` liest."""
    def __init__(self, lg, abgeschlossen=False, versendet_am=None):
        self.id, self.liegenschaft = 7, lg
        self.start_datum, self.ende_datum = date(2025, 1, 1), date(2025, 12, 31)
        self.abgeschlossen, self.versendet_am = abgeschlossen, versendet_am


class _Lg:
    id = 3


class NkProzessTests(SimpleTestCase):
    def schritte(self, p, **kw):
        from core.services.nk_prozess import schritte
        werte = dict(total_kosten=Decimal('1000'), warnungen=[], akonto_vorschlaege=[],
                     hkvo_aktiv=False, hkvo_angewendet=False)
        werte.update(kw)
        return schritte(p, **werte)

    def zustaende(self, s):
        return [x['zustand'] for x in s]

    def test_ohne_kosten_ist_kosten_der_naechste_schritt_und_der_rest_gesperrt(self):
        s = self.schritte(_Periode(_Lg()), total_kosten=Decimal('0'))
        self.assertEqual(self.zustaende(s),
                         ['erledigt', 'offen', 'entfaellt', 'gesperrt', 'gesperrt', 'gesperrt', 'gesperrt'])
        self.assertEqual([x['hier'] for x in s].index(True), 1)

    def test_hinweise_und_akonto_werden_zu_warnungen(self):
        s = self.schritte(_Periode(_Lg()), warnungen=['Fläche fehlt'], akonto_vorschlaege=[1])
        self.assertEqual(self.zustaende(s)[3:6], ['warnung', 'warnung', 'offen'])
        self.assertTrue(s[3]['hier'])

    def test_hkvo_aktiv_verlangt_zaehlerstaende(self):
        s = self.schritte(_Periode(_Lg()), hkvo_aktiv=True)
        self.assertEqual(s[2]['zustand'], 'warnung')
        self.assertTrue(s[2]['hier'])
        s = self.schritte(_Periode(_Lg()), hkvo_aktiv=True, hkvo_angewendet=True)
        self.assertEqual(s[2]['zustand'], 'erledigt')

    def test_verbucht_und_zugestellt_ist_alles_erledigt(self):
        s = self.schritte(_Periode(_Lg(), abgeschlossen=True, versendet_am=date(2026, 3, 1)))
        self.assertEqual(set(self.zustaende(s)), {'erledigt', 'entfaellt'})
        self.assertFalse(any(x['hier'] for x in s))
        self.assertIn('01.03.2026', s[-1]['info'])

    def test_verbucht_ohne_zustellung_zeigt_auf_die_zustellung(self):
        s = self.schritte(_Periode(_Lg(), abgeschlossen=True))
        self.assertEqual(s[-1]['zustand'], 'offen')
        self.assertTrue(s[-1]['hier'])
        self.assertEqual(s[-1]['url'], '/neu/nebenkosten/7/zustellung/')

    def test_jeder_link_fuehrt_auf_eine_bestehende_seite(self):
        for kw in ({}, {'hkvo_aktiv': True}):
            for p in (_Periode(_Lg()), _Periode(_Lg(), abgeschlossen=True)):
                for x in self.schritte(p, **kw):
                    with self.subTest(schritt=x['titel']):
                        resolve(x['url'].split('?')[0].split('#')[0])


class AssistentSeitenTests(TestCase):
    def setUp(self):
        _seed_konten()
        _test_organisation()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def seite(self, url):
        r = self.c.get(url, secure=True)
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode()

    def test_neue_akten_kommen_als_assistent(self):
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        k = KreditorenRechnung.objects.create(lieferant='Sanitär AG', betrag=Decimal('200.00'), status='bezahlt',
                                              liegenschaft=self.lg, konto=konto('4000'))
        for url, mindestens in (('/neu/personen/neu/', 5), ('/neu/liegenschaften/neu/', 4),
                                (f'/neu/vertraege/{self.v.id}/kuendigen/', 3),
                                (f'/neu/kreditoren/{k.id}/weiterverrechnen/', 2),
                                ('/neu/nebenkosten/', 1)):
            with self.subTest(url=url):
                html = self.seite(url)
                self.assertIn('data-assistent ', html)
                self.assertGreaterEqual(html.count('data-schritt="'), mindestens)
                self.assertIn('fw-bausteine.js', html)

    def test_bearbeiten_bleibt_eine_seite(self):
        for url in (f'/neu/personen/{self.m.id}/bearbeiten/', f'/neu/liegenschaften/{self.lg.id}/bearbeiten/'):
            with self.subTest(url=url):
                html = self.seite(url)
                self.assertNotIn('data-assistent ', html)
                self.assertIn('fw-formseite', html)

    def test_person_assistent_speichert_mit_den_bisherigen_feldnamen(self):
        from crm.models import Mieter
        html = self.seite('/neu/personen/neu/')
        # Kein Feld der Vorlage geht im Umbau verloren (Bedingungen, falsche Schrittgrenzen).
        namen = set(re.findall(r'name="([a-z_0-9]+)"', (VORLAGEN / 'fw' / 'person_form.html').read_text(encoding='utf-8')))
        self.assertGreater(len(namen), 40)
        for name in sorted(namen - {'dublette_ok'}):
            self.assertIn(f'name="{name}"', html)
        r = self.c.post('/neu/personen/neu/', {'typ': 'person', 'vorname': 'Ada', 'nachname': 'Assistent',
                                               'plz': '8000', 'ort': 'Zürich'}, secure=True)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Mieter.objects.filter(nachname='Assistent', ort='Zürich').exists())

    def test_nebenkosten_detail_zeigt_die_prozessleiste(self):
        from finance.models import AbrechnungsPeriode
        p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                              start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        html = self.seite(f'/neu/nebenkosten/{p.id}/')
        self.assertIn('class="fw-prozess"', html)
        self.assertIn('Kosten &amp; Belege', html)
