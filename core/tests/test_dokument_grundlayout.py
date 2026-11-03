"""Grundlayout der PDF-Dokumente und der neu gesetzte Mietvertrag (Welle 1, 3.11.2026).

Geprüft wird am ERZEUGTEN PDF (Text und Position je Seite, pdfplumber), nicht am HTML: Dass der
Unterschriftsblock nicht allein auf einer Seite steht, lässt sich nur dort sehen — `page-break-inside`
wirkt in xhtml2pdf auf <div> nicht (belegt), gehalten wird mit einer einzelnen Tabellenzelle.

Gegenproben (von Hand gemacht, Ergebnis im Bericht): Tabellenzelle `table.halten` entfernt → der
Längentest wird rot (Unterschriften ohne Artikel auf eigener Seite); DocuSeal-Marke im Mieter-Block
umbenannt → der Markentest wird rot; Artikelnummern entfernt → der Nummerntest wird rot.
"""
import io
import re
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pdfplumber
from django.core.files.base import ContentFile
from django.template import engines
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from reportlab.platypus.doctemplate import LayoutError

from core.services.briefkopf import briefkopf_kontext
from core.services import pdf_service
from core.services.pdf_service import generate_vertrag_pdf_bytes, render_vertrag_html
from crm.models import Organisation
from rentals.models import Mietvertrag

from ._helfer import Mieter, _basis_objekte, _test_organisation

MARKE_UNTERSCHRIFT = '{{Unterschrift Mieter;role=Mieter;type=signature;required=true}}'
MARKE_ORT = '{{Ort Mieter;role=Mieter;type=text;required=true}}'
MARKE_DATUM = '{{Datum Mieter;role=Mieter;type=date;required=true}}'


def seiten(pdf):
    """[(Text, Wörter)] je Seite."""
    with pdfplumber.open(io.BytesIO(pdf)) as dok:
        return [(s.extract_text() or '', s.extract_words(), float(s.width)) for s in dok.pages]


def _frisch(v):
    """Den Vertrag neu laden: Beziehungen (Organisation, Objekt) stehen sonst veraltet im Zwischenspeicher."""
    return Mietvertrag.objects.get(pk=v.pk)


class MietvertragLayout(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()

    def pdf(self, v=None):
        return generate_vertrag_pdf_bytes(_frisch(v or self.v))

    def mit_mitmieter(self):
        m2 = Mieter.objects.create(typ='person', vorname='Anna', nachname='Muster', strasse='Seeweg 3',
                                   plz='8000', ort='Zürich')
        self.v.mitmieter = m2
        self.v.save()

    # ---- Gliederung ----

    def test_artikel_sind_durchnummeriert(self):
        text = '\n'.join(t for t, _w, _b in seiten(self.pdf()))
        for nummer, titel in (('1', 'Vertragsparteien'), ('2', 'Mietsache'), ('3', 'Mietdauer und Kündigung'),
                              ('4', 'Mietzins'), ('5', 'Allgemeine Bedingungen und Hausordnung'),
                              ('6', 'Datenschutz & anwendbares Recht')):
            self.assertRegex(text, rf'(?m)^{nummer}\s+{re.escape(titel)}$')
        for klausel in ('1.1', '1.2', '2.1', '2.2', '3.1', '3.2', '4.1', '4.2', '4.3', '4.4', '4.5'):
            self.assertRegex(text, rf'(?m)^{re.escape(klausel)}\s+\S')
        # Gegenprobe: keine Nummer ohne Klausel (ohne Familienwohnung gibt es 1.4 nicht)
        self.assertNotRegex(text, r'(?m)^1\.4\s')

    def test_nummern_folgen_den_vorbehalten(self):
        """Mit Vorbehalten rücken die letzten Artikel um eins nach unten — wie vor dem Umbau."""
        ohne = '\n'.join(t for t, _w, _b in seiten(self.pdf()))
        self.assertRegex(ohne, r'(?m)^5\s+Allgemeine Bedingungen')
        self.assertNotRegex(ohne, r'(?m)^5\s+Vorbehalte')
        self.v.weitere_vorbehalte = 'Vorbehalt nach Art. 270 OR.'
        self.v.besondere_vereinbarungen = 'Keine Haustiere.'
        self.v.save()
        mit = '\n'.join(t for t, _w, _b in seiten(self.pdf()))
        self.assertRegex(mit, r'(?m)^5\s+Vorbehalte und besondere Vereinbarungen')
        self.assertRegex(mit, r'(?m)^5\.1\s+Mietzinsvorbehalte')
        self.assertRegex(mit, r'(?m)^5\.2\s+Besondere Bestimmungen')
        self.assertRegex(mit, r'(?m)^6\s+Allgemeine Bedingungen')
        self.assertRegex(mit, r'(?m)^7\s+Datenschutz')

    def test_bedingte_klauseln_unveraendert(self):
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertIn('Mahn- und Umtriebsgebühren', html)           # mahngebuehr_vereinbart (Standard: ja)
        self.assertNotIn('Familienwohnung', html)
        self.assertNotIn('Referenzmiete', html)                     # kein Zeitplan
        self.assertIn('Massgebliche Gesetzesgrundlagen (OR)', html)
        self.assertIn('(Wohnräume Art. 266c)', html)
        self.v.mahngebuehr_vereinbart = False
        self.v.familienwohnung = True
        self.v.save()
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertNotIn('Mahn- und Umtriebsgebühren', html)
        self.assertIn('Eine Kündigung durch den Vermieter ist beiden Ehegatten separat', html)
        self.e.typ = 'gew'
        self.e.save()
        self.v.zweckbestimmung = 'Anwaltskanzlei'
        self.v.save()
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertIn('<b>Anwaltskanzlei</b>', html)
        self.assertIn('(Geschäftsräume Art. 266d)', html)

    # ---- DocuSeal ----

    def test_docuseal_marken_stehen_im_pdf_text_im_mieter_block(self):
        seitenliste = seiten(self.pdf())
        text = ' '.join(' '.join(t.split()) for t, _w, _b in seitenliste)
        for marke in (MARKE_UNTERSCHRIFT, MARKE_ORT, MARKE_DATUM):
            self.assertEqual(text.count(marke), 1, marke)
        # Ort und Datum stehen in einer Zeile (nicht zerbrochen): so findet DocuSeal sie sicher.
        zeilen = '\n'.join(t for t, _w, _b in seitenliste)
        self.assertIn(MARKE_ORT, zeilen)
        self.assertIn(MARKE_DATUM, zeilen)
        # Mieter-Block = rechte Spalte, Vermieter links (Gegenprobe: «Ort: Zürich» des Vermieters liegt links).
        letzte = seitenliste[-1]
        marke = next(w for w in letzte[1] if w['text'] == '{{Ort')
        ort_felder = sorted(w['x0'] for w in letzte[1] if w['text'] == 'Ort:')
        self.assertGreater(marke['x0'], letzte[2] / 2)
        self.assertEqual(len(ort_felder), 2)                    # Vermieter und Mieter, gleich aufgebaut
        self.assertLess(ort_felder[0], letzte[2] / 2)

    def test_marken_auch_im_kontext_der_docuseal_wege(self):
        """Die DocuSeal-Wege bauen ihren Kontext von Hand (ohne `briefkopf`, ohne `mietzins_zeitplan`)."""
        from django.template.loader import get_template
        v = _frisch(self.v)
        ctx = {'vertrag': v, 'mieter': v.mieter, 'einheit': v.einheit, 'liegenschaft': v.einheit.liegenschaft,
               'eigentuemer': None, 'verwaltung': v.einheit.liegenschaft.organisation,
               'heute': date(2026, 11, 3), 'miete_fmt': '1500.00', 'nk_fmt': '200.00', 'brutto_fmt': '1700.00',
               'kaution_fmt': '4500.00', 'unterschrift_path': None}
        html = get_template('core/mietvertrag_pdf.html').render(ctx)
        for marke in (MARKE_UNTERSCHRIFT, MARKE_ORT, MARKE_DATUM):
            self.assertIn(marke, html)
        self.assertIn('Testverwaltung AG', html)      # Briefkopf auch ohne `briefkopf` im Kontext

    # ---- Seiten ----

    def _block_bleibt_zusammen(self, pdf):
        """Die Seite mit den Unterschriften trägt auch den letzten Artikel und die Beilagenliste."""
        gefunden = 0
        for text, _w, _b in seiten(pdf):
            zeilen = text.split('\n')
            if 'Unterschriften' in zeilen:
                gefunden += 1
                self.assertTrue(any(z.endswith('Datenschutz & anwendbares Recht') for z in zeilen), text)
                self.assertTrue(any(z.startswith('Beilagen zu diesem Vertrag') for z in zeilen), text)
                self.assertIn('Hausordnung', text)
        self.assertEqual(gefunden, 1)

    def test_unterschriften_nie_allein_auf_einer_seite(self):
        """Verschieden lange Vorbehalte schieben den Schlussblock an verschiedene Seitenstellen.

        Ohne den Zusammenhalt landet er bei einigen Längen geteilt oder allein hinter dem Seitenumbruch.
        Ein Durchlauf mit Mitmieter (höherer Block) gehört dazu."""
        for mitmieter in (False, True):
            if mitmieter:
                self.mit_mitmieter()
            for wiederholungen in (0, 4, 8, 12, 16, 20, 24, 28, 32, 40):
                with self.subTest(mitmieter=mitmieter, wiederholungen=wiederholungen):
                    self.v.besondere_vereinbarungen = ' '.join(['Haustiere nur mit Zustimmung des Vermieters.'] * wiederholungen)
                    self.v.save()
                    self._block_bleibt_zusammen(self.pdf())

    def test_seitenzahl_paraphen_und_seitenkopf(self):
        self.mit_mitmieter()
        seitenliste = seiten(self.pdf())
        n = len(seitenliste)
        self.assertGreater(n, 1)
        for i, (text, _w, _b) in enumerate(seitenliste, start=1):
            self.assertIn(f'Seite {i} von {n}', text)
            self.assertIn('Visum', text)
            self.assertIn('Mieter 2', text)          # Paraphen-Zeile kennt beide Mieter
            kopf = text.split('\n')[0]
            if i == 1:
                self.assertNotIn('Hans Muster', kopf)     # Seite 1: Briefkopf, kein Seitenkopf
            else:
                self.assertIn('Mietvertrag für Wohnräume', kopf)
                self.assertIn('Hans Muster', kopf)
        self.assertNotIn('Seite 1 von 1', ' '.join(t for t, _w, _b in seitenliste))

    def test_beilagen_und_kein_empfaengerblock(self):
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertIn('Allgemeine Bedingungen zum Mietvertrag · Hausordnung', html)
        self.assertNotIn('empfaengerInhalt', html)     # zum Vertrag gehört immer ein Begleitbrief

    def test_zeitplan_tabelle_bleibt(self):
        from rentals.models import VertragMietzins
        VertragMietzins.objects.create(vertrag=self.v, gueltig_ab=date(2024, 1, 1), netto_mietzins=Decimal('1500'),
                                       nebenkosten=Decimal('200'), rabatt_netto=Decimal('1500'), notiz='Gratismonat')
        VertragMietzins.objects.create(vertrag=self.v, gueltig_ab=date(2024, 2, 1), netto_mietzins=Decimal('1500'),
                                       nebenkosten=Decimal('200'))
        text = '\n'.join(t for t, _w, _b in seiten(self.pdf()))
        self.assertIn('Gestaffelter Mietzins / Gratismonate', text)
        self.assertIn('Referenzmiete', text)
        self.assertIn('mietzinsfrei', text)

    def test_zu_hoher_schlussblock_faellt_auf_normalen_satz_zurueck(self):
        """Wird der unteilbare Block höher als eine Seite, wirft reportlab LayoutError: dann ohne Zusammenhalt."""
        echt = pdf_service._pdf_aus_html
        aufrufe = []

        def erster_wirft(html):
            aufrufe.append(html)
            if len(aufrufe) == 1:
                raise LayoutError('zu hoch')
            return echt(html)

        with patch('core.services.pdf_service._pdf_aus_html', side_effect=erster_wirft):
            pdf = generate_vertrag_pdf_bytes(_frisch(self.v))
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(len(aufrufe), 2)
        self.assertIn('class="halten"', aufrufe[0])
        self.assertNotIn('class="halten"', aufrufe[1])


class BriefkopfLayout(TestCase):
    """Briefkopf je Organisation: Logo im Seitenverhältnis, Akzentfarbe und Fusszeile nur wenn vorhanden."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.org = _test_organisation()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)

    def test_ohne_felder_bleibt_neutral(self):
        pdf = generate_vertrag_pdf_bytes(_frisch(self.v))
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertNotIn('#1f6f5c', html)
        self.assertNotIn('CHE-123', '\n'.join(t for t, _w, _b in seiten(pdf)))

    def test_farbe_und_fusszeile_der_organisation(self):
        self.org.briefkopf_farbe = '#1f6f5c'
        self.org.briefkopf_fusszeile = 'CHE-123.456.789 MWST'
        self.org.save()
        pdf = generate_vertrag_pdf_bytes(_frisch(self.v))
        html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
        self.assertIn('#1f6f5c', html)
        for text, _w, _b in seiten(pdf):
            self.assertIn('CHE-123.456.789 MWST', text)      # auf jeder Seite

    def test_logo_im_seitenverhaeltnis(self):
        bild = io.BytesIO()
        Image.new('RGB', (400, 120), (31, 111, 92)).save(bild, 'PNG')
        with override_settings(MEDIA_ROOT=self.media):
            self.org.logo.save('logo.png', ContentFile(bild.getvalue()))
            bk = briefkopf_kontext(Organisation.objects.get(pk=self.org.pk))
            self.assertTrue(bk['logo_pfad'])
            self.assertAlmostEqual(bk['logo_breite'] / bk['logo_hoehe'], 400 / 120, places=1)
            self.assertLessEqual(bk['logo_hoehe'], 40.0)
            html = render_vertrag_html(_frisch(self.v), mit_unterschrift=False)
            self.assertIn('<img src="' + bk['logo_pfad'] + '" width="', html)
            self.assertTrue(generate_vertrag_pdf_bytes(_frisch(self.v)).startswith(b'%PDF'))
        # Gegenprobe: ohne Logo keine Masse, kein Bild
        bk = briefkopf_kontext(Organisation(firma='X'))
        self.assertEqual((bk['logo_breite'], bk['logo_hoehe']), (0, 0))

    def test_kaputtes_logo_bricht_das_dokument_nicht(self):
        with override_settings(MEDIA_ROOT=self.media):
            self.org.logo.save('kaputt.png', ContentFile(b'kein bild'))
            bk = briefkopf_kontext(Organisation.objects.get(pk=self.org.pk))
            self.assertEqual((bk['logo_breite'], bk['logo_hoehe']), (0, 0))


class AdressfensterBaustein(TestCase):
    """Der Baustein für Briefe (Welle 2): Empfängerfeld rechts; im Vertrag gibt es ihn nicht."""

    VORLAGE = ('{% extends "core/dok_base.html" %}{% block inhalt %}'
               '{% include "core/_dok_adressfenster.html" with zeilen=zeilen %}<p>Brieftext</p>{% endblock %}')

    def render_pdf(self, **kontext):
        from xhtml2pdf import pisa

        from core.services.pdf_service import link_callback
        _basis_objekte()
        org = _test_organisation()
        html = engines['django'].from_string(self.VORLAGE).render({
            'zeilen': ['Frau Anna Muster', 'Seeweg 3', '8000 Zürich'], 'verwaltung': org,
            'heute': date(2026, 11, 3), **kontext})
        puffer = io.BytesIO()
        pisa.CreatePDF(html, dest=puffer, link_callback=link_callback, encoding='utf-8')
        return puffer.getvalue()

    def test_empfaenger_steht_rechts_und_text_darunter(self):
        text, woerter, breite = seiten(self.render_pdf(adressfenster=True))[0]
        frau = next(w for w in woerter if w['text'] == 'Frau')
        brief = next(w for w in woerter if w['text'] == 'Brieftext')
        self.assertGreater(frau['x0'], 11.5 / 2.54 * 72)          # Fenster rechts: ab 11.8 cm
        self.assertGreater(brief['top'], frau['top'] + 40)         # Brieftext beginnt unterhalb des Feldes
        self.assertIn('Seite 1 von 1', text)

    def test_ohne_schalter_kein_feld(self):
        text, woerter, _b = seiten(self.render_pdf())[0]
        self.assertNotIn('Frau', text)                             # Gegenprobe: ohne Schalter wird nichts gezeichnet


class GrundlayoutBegleitdokumente(TestCase):
    """Die übrigen Dokumente auf dok_base.html laufen weiter und tragen den gemeinsamen Kopf und Fuss."""

    def test_alle_dokumente_erzeugen_ein_pdf_mit_seitenfuss(self):
        from core.services.dokument_service import DOKUMENT_TYPEN, NUR_MIT_KONTEXT, generate_dokument_pdf_bytes
        _l, _e, _m, v = _basis_objekte()
        v = _frisch(v)
        for typ in DOKUMENT_TYPEN:
            if typ in NUR_MIT_KONTEXT:
                continue
            with self.subTest(typ=typ):
                text, _w, _b = seiten(generate_dokument_pdf_bytes(v, typ))[0]
                self.assertRegex(text, r'Seite 1 von \d')
                self.assertIn('Testverwaltung AG', text)          # Briefkopf der Organisation des Objekts


class Schriftart(SimpleTestCase):
    def test_stylesheet_nennt_nur_helvetica(self):
        """Keine Fremdschrift: Helvetica ist eine PDF-Standardschrift, es wird nichts geladen oder eingebettet."""
        from django.template.loader import get_template
        stil = get_template('core/_dok_stil.html').render({})
        schriften = set(re.findall(r'font-family\s*:\s*([^;]+);', stil))
        self.assertEqual(schriften, {'Helvetica, sans-serif'})
        self.assertNotIn('@font-face', stil)
