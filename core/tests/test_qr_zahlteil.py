"""Zahlteil und Empfangsschein nach dem Style Guide QR-Rechnung (SIX).

Befund des Prüf-Agenten: Bei QRR stand die Referenz nur im QR-Code, der Empfangsschein hatte
keine Annahmestelle, lange Namen liefen in den Zahlteil, die Schriftgrössen waren falsch.
Geprüft wird das gezeichnete PDF (pdfplumber), nicht der Code.

Nicht geprüft und nicht verändert: der Datenteil des QR-Codes (eigene Tests: Betrag, Referenz,
Payload in den bestehenden Modulen).
"""
import io
import pathlib
from unittest import mock

import pdfplumber
from django.conf import settings
from django.test import SimpleTestCase
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.utils import qr_code
from core.utils.qr_code import draw_qr_bill, qrr_referenz, referenz_formatieren

QR_IBAN = 'CH44 3199 9123 0008 8901 2'
NORMAL_IBAN = 'CH93 0076 2011 6238 5295 7'
KURZ = {'name': 'Muster AG', 'line1': 'Bahnhofstrasse 1', 'line2': '8000 Zürich'}
LANG = {'name': 'Stockwerkeigentümergemeinschaft Sonnenblickweg 1',
        'line1': 'c/o Immobilienverwaltung Mustermann & Partner Treuhand', 'line2': '3000 Bern'}
SCHULDNER = {'name': 'Hans Muster', 'line1': 'Seestrasse 5', 'line2': '8002 Zürich'}
OHNE = {'name': '', 'line1': '', 'line2': ''}
REF = qrr_referenz(1234, 202611)[0]
REF_GRUPPIERT = '00 00001 23400 00000 00020 26117'


def zahlteil_pdf(iban=QR_IBAN, creditor=KURZ, debtor=SCHULDNER, amount=1450.5, reason='Miete 11/2026',
                 reference=REF, **kw):
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    draw_qr_bill(c, iban, creditor, debtor, amount, reason, reference=reference, **kw)
    c.save()
    puffer.seek(0)
    return pdfplumber.open(puffer)


def zeichen(pdf):
    """(Zeichen der Seite, Y-Grenze der Zahlteil-Zone von oben) ohne das Scherensymbol."""
    seite = pdf.pages[0]
    return [ch for ch in seite.chars if 'Zapf' not in ch['fontname']]


def woerter(pdf):
    seite = pdf.pages[0]
    return seite.extract_words(extra_attrs=['size', 'fontname'], keep_blank_chars=False)


def empfangsschein(ch):
    return ch['x0'] < 62 * mm


def text_links(pdf):
    return ' '.join(w['text'] for w in woerter(pdf) if w['x0'] < 62 * mm)


def text_rechts(pdf):
    return ' '.join(w['text'] for w in woerter(pdf) if w['x0'] >= 62 * mm)


class ReferenzZeileTests(SimpleTestCase):
    def test_gruppierung(self):
        self.assertEqual(referenz_formatieren('QRR', REF), REF_GRUPPIERT)
        self.assertEqual(referenz_formatieren('QRR', REF_GRUPPIERT), REF_GRUPPIERT)
        self.assertEqual(referenz_formatieren('SCOR', 'RF18539007547034'), 'RF18 5390 0754 7034')
        self.assertEqual(referenz_formatieren('SCOR', 'RF1234567890'), 'RF12 3456 7890')
        self.assertEqual(referenz_formatieren('NON', ''), '')

    def test_qrr_steht_als_text_in_zahlteil_und_empfangsschein(self):
        pdf = zahlteil_pdf()
        self.assertIn(REF_GRUPPIERT, text_links(pdf))
        self.assertIn(REF_GRUPPIERT, text_rechts(pdf))
        for seite in (text_links(pdf), text_rechts(pdf)):
            self.assertEqual(seite.count('Referenz'), 1)

    def test_ohne_referenz_keine_zeile(self):
        pdf = zahlteil_pdf(iban=NORMAL_IBAN, reference=None)
        self.assertNotIn('Referenz', text_links(pdf) + text_rechts(pdf))


class AnnahmestelleTests(SimpleTestCase):
    def test_annahmestelle_steht_rechtsbuendig_auf_dem_empfangsschein(self):
        pdf = zahlteil_pdf()
        treffer = [w for w in woerter(pdf) if w['text'] == 'Annahmestelle']
        self.assertEqual(len(treffer), 1)
        self.assertLess(treffer[0]['x1'], 62 * mm)
        self.assertAlmostEqual(treffer[0]['x1'], 57 * mm, delta=0.5)
        self.assertIn('Bold', treffer[0]['fontname'])
        self.assertAlmostEqual(treffer[0]['size'], 6, places=1)

    def test_sprachen(self):
        for sprache, text in (('fr', 'Point de dépôt'), ('it', 'Punto di accettazione'), ('en', 'Acceptance point')):
            with self.subTest(sprache=sprache):
                pdf = zahlteil_pdf(sprache=sprache)
                self.assertIn(text, text_links(pdf))
        self.assertIn('Annahmestelle', text_links(zahlteil_pdf()))


class SchriftgroessenTests(SimpleTestCase):
    def groesse(self, pdf, text, links):
        treffer = [w for w in woerter(pdf)
                   if w['text'] == text and (w['x0'] < 62 * mm) == links]
        self.assertTrue(treffer, text)
        return round(treffer[0]['size'], 1), 'Bold' in treffer[0]['fontname']

    def test_empfangsschein(self):
        pdf = zahlteil_pdf()
        self.assertEqual(self.groesse(pdf, 'Empfangsschein', True), (11.0, True))
        self.assertEqual(self.groesse(pdf, 'Konto', True), (6.0, True))
        self.assertEqual(self.groesse(pdf, 'Referenz', True), (6.0, True))
        self.assertEqual(self.groesse(pdf, 'Muster', True), (8.0, False))
        self.assertEqual(self.groesse(pdf, '1\'450.50', True), (8.0, False))      # Betrag 8 pt
        self.assertEqual(self.groesse(pdf, 'Währung', True), (6.0, True))

    def test_zahlteil(self):
        pdf = zahlteil_pdf()
        self.assertEqual(self.groesse(pdf, 'Zahlteil', False), (11.0, True))
        self.assertEqual(self.groesse(pdf, 'Konto', False), (8.0, True))
        self.assertEqual(self.groesse(pdf, 'Zusätzliche', False), (8.0, True))
        self.assertEqual(self.groesse(pdf, 'Muster', False), (10.0, False))
        self.assertEqual(self.groesse(pdf, '1\'450.50', False), (10.0, False))
        self.assertEqual(self.groesse(pdf, 'Währung', False), (8.0, True))

    def test_reihenfolge_im_zahlteil(self):
        """Konto, Referenz, Zusätzliche Informationen, Zahlbar durch — von oben nach unten."""
        pdf = zahlteil_pdf()
        rechts = {w['text']: w['top'] for w in woerter(pdf) if w['x0'] >= 118 * mm}
        self.assertLess(rechts['Konto'], rechts['Referenz'])
        self.assertLess(rechts['Referenz'], rechts['Zusätzliche'])
        self.assertLess(rechts['Zusätzliche'], rechts['Zahlbar'])


class BreiteTests(SimpleTestCase):
    def test_langer_name_laeuft_nicht_in_den_zahlteil(self):
        pdf = zahlteil_pdf(creditor=LANG, debtor={
            'name': 'Erbengemeinschaft Hans und Margrit Müller-Schneider',
            'line1': 'Hauptstrasse 123a', 'line2': '8002 Zürich'})
        for ch in zeichen(pdf):
            if empfangsschein(ch):
                self.assertLessEqual(ch['x1'], 57 * mm + 0.5, f"{ch['text']!r} ragt über den Textrand (52 mm)")
        # Nichts ging verloren: der Name steht vollständig, auf mehrere Zeilen verteilt
        self.assertIn('Stockwerkeigentümergemeinschaft', text_links(pdf))
        self.assertIn('Sonnenblickweg', text_links(pdf))

    def test_langes_wort_wird_getrennt(self):
        zeilen = qr_code.text_umbrechen('X' * 80, 'Helvetica', 8, 52)
        self.assertGreater(len(zeilen), 1)
        self.assertEqual(''.join(zeilen), 'X' * 80)

    def test_zahlteil_bleibt_im_rand(self):
        pdf = zahlteil_pdf(creditor=LANG, reason='Akonto-Rechnung 2. Quartal 2026 ' * 4)
        for ch in zeichen(pdf):
            if not empfangsschein(ch):
                self.assertLessEqual(ch['x1'], 205 * mm + 0.5)


class FelderTests(SimpleTestCase):
    def test_ohne_betrag_und_schuldner_stehen_rahmen(self):
        pdf = zahlteil_pdf(debtor=OHNE, amount=None)
        links, rechts = text_links(pdf), text_rechts(pdf)
        self.assertIn('Zahlbar durch (Name/Adresse)', links)
        self.assertIn('Zahlbar durch (Name/Adresse)', rechts)
        self.assertNotIn('0.00', links + rechts)
        self.assertNotIn('CHF 0', links + rechts)
        # Eckmarken: vier Felder (Schuldner und Betrag, je Empfangsschein und Zahlteil), je 8 Linien
        kurze = [ln for ln in pdf.pages[0].lines
                 if max(abs(ln['x1'] - ln['x0']), abs(ln['bottom'] - ln['top'])) < 4 * mm]
        self.assertGreaterEqual(len(kurze), 32)

    def test_mit_betrag_keine_betragsrahmen(self):
        pdf = zahlteil_pdf()
        kurze = [ln for ln in pdf.pages[0].lines
                 if max(abs(ln['x1'] - ln['x0']), abs(ln['bottom'] - ln['top'])) < 4 * mm]
        self.assertEqual(len(kurze), 0)

    def test_schuldner_und_betrag_in_beiden_teilen(self):
        pdf = zahlteil_pdf()
        for text in (text_links(pdf), text_rechts(pdf)):
            self.assertIn('Zahlbar durch', text)
            self.assertIn('Hans Muster', text)
            self.assertIn("1'450.50", text)

    def test_perforation_senkrecht_zwischen_den_teilen(self):
        pdf = zahlteil_pdf()
        senkrecht = [ln for ln in pdf.pages[0].lines
                     if abs(ln['x0'] - 62 * mm) < 0.5 and abs(ln['x1'] - 62 * mm) < 0.5]
        self.assertTrue(senkrecht)


class DatenteilUnveraendertTests(SimpleTestCase):
    def test_qr_payload_wird_nur_abgebildet(self):
        """Der Datenteil trägt weiter Referenz, Betrag und Mitteilung — die Darstellung ändert ihn nicht."""
        erfasst = []
        echt = qr_code.segno.make

        def spion(daten, **kw):
            erfasst.append(daten)
            return echt(daten, **kw)

        with mock.patch.object(qr_code.segno, 'make', spion):
            zahlteil_pdf()
        zeilen = erfasst[0].split('\n')
        self.assertEqual(zeilen[:4], ['SPC', '0200', '1', QR_IBAN.replace(' ', '')])
        self.assertIn('1450.50', zeilen)
        self.assertIn('QRR', zeilen)
        self.assertIn(REF, zeilen)
        self.assertIn('Miete 11/2026', zeilen)


class EineStelleTests(SimpleTestCase):
    def test_kein_zweiter_zahlteil_von_hand(self):
        """`/billing/…/qr-rechnung` zeichnete einen eigenen Zahlteil — an zwei Stellen korrigiert man
        nicht, man vergisst eine. Die Überschrift «Konto / Zahlbar an» wird nur in qr_code.py gezeichnet."""
        wurzel = pathlib.Path(settings.BASE_DIR)
        fundorte = []
        for pfad in wurzel.rglob('*.py'):
            teile = pfad.relative_to(wurzel).parts
            if ('tests' in teile or pfad.name.startswith('test_') or '.claude' in teile
                    or 'node_modules' in teile or pfad.name == 'qr_code.py'):
                continue
            if 'drawString' in (text := pfad.read_text(encoding='utf-8', errors='ignore')) and \
                    '"Konto / Zahlbar an"' in text:
                fundorte.append(str(pfad.relative_to(wurzel)))
        self.assertEqual(fundorte, [])
