"""Gemeinsames Layout der von Hand gezeichneten PDF-Dokumente (Welle 2, 3.11.2026).

Geprüft wird am ERZEUGTEN PDF (Text und Position je Seite, pdfplumber): Briefkopf der Verwaltung des
Datensatzes (Name, Logo), Seitenkopf ab Seite 2, Fusszeile «Seite x von y», Adressfenster rechts bei
Briefen (11.8 cm von links, 4.5 cm von oben, Schweizer C5/6), keines bei Berichten, keine Fusszeile auf der
Seite mit Einzahlungsschein, Zählung je Dokument im Sammel-PDF und zusammenhängende Blöcke.
Gegenproben (von Hand gemacht, rot gesehen, zurückgebaut):
* in `DokCanvas.brief` den Aufruf `self.fenster(...)` entfernen → `test_briefe_haben_das_adressfenster` rot
* in `serienbrief.py` `c.neues_dokument()` entfernen → `test_sammel_pdf_zaehlt_je_dokument` rot
* in `core/utils/qr_code.py` den Aufruf `c.ohne_fuss()` entfernen → `test_seite_mit_einzahlungsschein_ohne_fusszeile` rot
* in `DokCanvas.save` den Seitenkopf-Aufruf `self._seitenkopf()` entfernen → `test_seitenkopf_erst_ab_seite_2` rot
* in `mietprozess_briefe._brief` die Zeilenprüfung `if ty < c.UNTEN + 4 * mm` entfernen → `test_langer_absatz_laeuft_nicht_in_die_fusszeile` rot
* in `dok_base.html` den Block `seitenkopf_ref` leeren oder in `dok_hausordnung.html` den Block `seitenkopf_titel` entfernen → `test_beilagen_haben_seitenkopf_ab_seite_2` rot
"""
import io
import shutil
import tempfile
from datetime import date
from decimal import Decimal as D

import pdfplumber
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from reportlab.lib.units import mm

from core.services.dok_layout import DokCanvas
from core.utils.qr_code import sammelreferenz

from ._helfer import _basis_objekte, _test_organisation

MM = float(mm)


def seiten(pdf):
    """[(Text, Wörter, Bilder, Breite, Höhe)] je Seite; Wörter mit Koordinaten in pt (Ursprung oben links)."""
    with pdfplumber.open(io.BytesIO(pdf)) as dok:
        return [(s.extract_text() or '', s.extract_words(), len(s.images), float(s.width), float(s.height))
                for s in dok.pages]


def im_fenster(seite):
    """Wörter im Bereich des Adressfensters (rechte Seitenhälfte, 45 bis 80 mm von oben)."""
    _t, woerter, _b, _w, _h = seite
    return [w for w in woerter if w['x0'] >= 117 * MM and 44 * MM <= w['top'] <= 80 * MM]


class DokCanvasTests(SimpleTestCase):
    """Der Baustein selbst, ohne Datenbank."""

    def _pdf(self, seitenzahl=3, **kw):
        import io as _io
        buf = _io.BytesIO()
        c = DokCanvas(buf, absender=['Muster Immobilien AG', 'Bahnhofstrasse 10', '8001 Zürich'],
                      titel='Mieterkonto', ref='Hans Muster', **kw)
        for i in range(seitenzahl):
            c.setFont('Helvetica', 10)
            c.drawString(20 * mm, c.Y_INHALT if i == 0 else c.Y_FOLGE, f'Inhalt {i + 1}')
            c.showPage()
        c.save()
        return buf.getvalue()

    def test_briefkopf_nur_auf_seite_1_und_fusszeile_mit_seitenzahl_auf_jeder(self):
        s = seiten(self._pdf())
        self.assertEqual(len(s), 3)
        self.assertIn('Muster Immobilien AG', s[0][0].split('\n')[0])
        self.assertIn('Bahnhofstrasse 10', s[0][0])
        for nr, seite in enumerate(s, 1):
            self.assertIn(f'Seite {nr} von 3', seite[0])
            self.assertIn('erstellt am', seite[0])

    def test_seitenkopf_erst_ab_seite_2(self):
        s = seiten(self._pdf())
        self.assertNotIn('Mieterkonto', s[0][0])                         # Seite 1: Briefkopf, kein Seitenkopf
        for seite in s[1:]:
            kopf = [w['text'] for w in seite[1] if w['top'] < 16 * MM]
            self.assertIn('Mieterkonto', kopf)
            self.assertIn('Muster', kopf)                                # Referenz rechts

    def test_sammel_pdf_zaehlt_je_dokument(self):
        import io as _io
        buf = _io.BytesIO()
        c = DokCanvas(buf, absender=['Muster Immobilien AG', '', ''], titel='NK')
        for dok in range(2):
            if dok:
                c.neues_dokument()
            c.drawString(20 * mm, c.Y_INHALT, 'Abrechnung')
            c.showPage()
        c.save()
        s = seiten(buf.getvalue())
        self.assertEqual([('Seite 1 von 1' in t) for t, *_ in s], [True, True])
        # Der Briefkopf steht auf BEIDEN Seiten, weil jede ein eigenes Dokument beginnt.
        self.assertTrue(all('Muster Immobilien AG' in t for t, *_ in s))

    def test_seite_ohne_fusszeile(self):
        import io as _io
        buf = _io.BytesIO()
        c = DokCanvas(buf, absender=['Muster Immobilien AG', '', ''], titel='Rechnung')
        c.drawString(20 * mm, c.Y_INHALT, 'Brief')
        c.showPage()
        c.ohne_fuss()
        c.drawString(20 * mm, 150 * mm, 'Zahlteil')
        c.showPage()
        c.save()
        s = seiten(buf.getvalue())
        self.assertIn('Seite 1 von 2', s[0][0])
        self.assertNotIn('Seite', s[1][0])


class LayoutBasis(TestCase):
    """Dokumente mit Datenbank: Briefe, Abrechnungen, Berichte."""

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.org = _test_organisation()

    def frisch(self):
        return self.v.__class__.objects.get(pk=self.v.pk)

    def mit_logo(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bild = io.BytesIO()
        Image.new('RGB', (400, 120), (20, 110, 90)).save(bild, 'PNG')
        with override_settings(MEDIA_ROOT=self.tmp):
            self.org.logo.save('logo.png', ContentFile(bild.getvalue()))
        self.org.briefkopf_farbe = '#1d6b57'
        self.org.save()
        return override_settings(MEDIA_ROOT=self.tmp)

    # ---- Briefe ----

    def briefe(self):
        from core.services import mietprozess_briefe as mp
        from core.services.herabsetzung_brief import antwortbrief_pdf
        from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
        from core.services.mahnbrief import mahnbrief_pdf
        from core.services.serienbrief import generate_serienbrief_pdf
        kd = type('K', (), {'per_datum': date(2027, 3, 31), 'berechneter_termin': None, 'bemerkung': ''})()
        return {
            'kaution': lambda: mp.kaution_hinterlegung_pdf(self.frisch()),
            'kuendigung': lambda: generate_kuendigung_mieter_pdf(self.frisch(), kd, self.org),
            'mahnung': lambda: mahnbrief_pdf(self.frisch(), self.org, stufe=1, monat='Oktober 2026',
                                             betrag='1700.00', datum=date(2026, 11, 3)),
            '257d': lambda: mahnbrief_pdf(self.frisch(), self.org, stufe=3, monat='Oktober 2026', betrag='1700.00',
                                          datum=date(2026, 11, 3), letzte_stufe=True),
            'herabsetzung': lambda: antwortbrief_pdf(self.frisch(), 'ablehnung', date(2026, 11, 3)),
            'serienbrief': lambda: generate_serienbrief_pdf(
                {'firma': 'Testverwaltung AG', 'strasse': 'Teststrasse 1', 'plz': '8000', 'ort': 'Zürich'},
                'Information', 'Text', [{'name': 'Hans Muster', 'strasse': 'Seeweg 3', 'plz': '8000',
                                         'ort': 'Zürich'}]),
        }

    def test_briefe_haben_das_adressfenster(self):
        for name, erzeuger in self.briefe().items():
            with self.subTest(brief=name):
                seite = seiten(erzeuger())[0]
                text = ' '.join(w['text'] for w in im_fenster(seite))
                self.assertIn('Muster', text)                            # der Empfänger steht im Fenster
                self.assertRegex(seite[0], r' · \d{4} ')                 # darüber die kleine Absenderzeile
                # und zwar rechts, bei 11.8 cm
                links = min(w['x0'] for w in im_fenster(seite))
                self.assertAlmostEqual(links / MM, 118.0, delta=1.0)

    def test_briefkopf_der_verwaltung_und_fusszeile(self):
        for name, erzeuger in self.briefe().items():
            with self.subTest(brief=name):
                text, woerter, _b, _w, _h = seiten(erzeuger())[0]
                kopf = ' '.join(w['text'] for w in woerter if w['top'] < 40 * MM)
                if name == 'kuendigung':                                 # der Mieter schreibt: sein Name steht im Kopf
                    self.assertIn('Hans Muster', kopf)
                else:
                    self.assertIn('Testverwaltung AG', kopf)
                self.assertRegex(text, r'Seite 1 von \d')

    def test_logo_nur_wenn_hinterlegt(self):
        ohne = seiten(self.briefe()['kaution']())[0]
        self.assertEqual(ohne[2], 0)
        mit = self.mit_logo()
        with mit:
            seite = seiten(self.briefe()['kaution']())[0]
        self.assertEqual(seite[2], 1)
        # mit Logo steht die Anschrift rechts, der Name fett darüber; der Briefkopf bleibt über dem Fenster
        self.assertLess(max(w['bottom'] for w in seite[1] if w['top'] < 40 * MM), 42 * MM)

    def test_mehrseitiger_brief_hat_seitenkopf_und_zaehlung(self):
        from core.services import mietprozess_briefe as mp
        maengel = [{'raum': 'Bad', 'beschreibung': 'Spiegel zerbrochen ' * 10, 'betrag': 200}] * 12
        s = seiten(mp.rueckgabe_maengelruege_pdf(self.frisch(), maengel))
        self.assertGreaterEqual(len(s), 2)
        self.assertIn(f'Seite 2 von {len(s)}', s[1][0])
        self.assertTrue(any(w['text'].startswith('Mängelrüge') for w in s[1][1] if w['top'] < 16 * MM))

    # ---- Berichte: kein Fenster ----

    def test_berichte_haben_kein_adressfenster(self):
        from unittest import mock

        from core.services.auswertung_pdf import generate_auswertung_pdf
        from core.services.mieterkonto import generate_mieterkonto_pdf
        monate = [{'m': m, 'wert': D(m * 100)} for m in range(1, 13)]
        with mock.patch('core.services.mieterkonto.berechne_mieterkonto', return_value=([], D('0'))):
            pdfs = {'mieterkonto': generate_mieterkonto_pdf(self.m, verwaltung=self.org),
                    'auswertung': generate_auswertung_pdf('Erträge', 2026, 'Teststrasse 1', D('7800'), monate, [],
                                                           self.org)}
        for name, pdf in pdfs.items():
            with self.subTest(bericht=name):
                seite = seiten(pdf)[0]
                text = ' '.join(w['text'] for w in im_fenster(seite))
                self.assertNotIn('Hans', text)                           # kein Empfänger im Fenster
                self.assertNotIn('Teststrasse 1 · 8000', seite[0])       # und keine Absenderzeile des Fensters
                self.assertIn('Testverwaltung AG', seite[0])             # aber Briefkopf und Fusszeile
                self.assertRegex(seite[0], r'Seite 1 von \d')

    # ---- Einzahlungsschein ----

    def test_seite_mit_einzahlungsschein_ohne_fusszeile(self):
        from core.services.mahnbrief import mahnbrief_pdf
        self.lg.iban = 'CH4431999123000889012'           # QR-IBAN (Kennung 31999)
        self.lg.save()
        s = seiten(mahnbrief_pdf(self.frisch(), self.org, stufe=1, monat='Oktober 2026', betrag='1700.00',
                                 datum=date(2026, 11, 3),
                                 rechnung=type('R', (), {'qr_referenz': sammelreferenz(self.v.id),
                                                         'forderungsart': 'miete'})()))
        self.assertEqual(len(s), 2)
        self.assertIn('Seite 1 von 2', s[0][0])
        self.assertIn('Zahlteil', s[1][0])
        self.assertNotIn('Seite', s[1][0])                               # der Zahlteil füllt den Fuss der Seite
        self.assertNotIn('erstellt am', s[1][0])

    # ---- Zusammenhaltende Blöcke ----

    def test_nk_summenkasten_bleibt_ganz(self):
        from core.services.nk_abrechnung import generate_nk_pdf_einzeln
        for n in range(38, 52):                          # verschieden lange Listen schieben den Kasten an die Seitengrenze
            k = {'verwaltung': self.org, 'periode': '2025', 'adresse': ['Hans Muster', 'Seeweg 3', '8000 Zürich'],
                 'objekt': '3.5 Zi', 'positionen': [{'kategorie': f'Kosten {i}', 'schluessel': 'm2', 'betrag': D('10')}
                                                    for i in range(n)],
                 'total_kosten': D('100'), 'kosten_anteil': D('15'), 'akonto': D('10'), 'saldo': D('5'),
                 'nachzahlung': True}
            with self.subTest(positionen=n):
                s = seiten(generate_nk_pdf_einzeln(k))
                seite = [t for t, *_ in s if 'Ihre Abrechnung' in t]
                self.assertEqual(len(seite), 1)
                for wort in ('Ihr Kostenanteil', 'Bezahlte Akontozahlungen', 'Nachzahlung zu Ihren Lasten'):
                    self.assertIn(wort, seite[0])

    def test_schlussabrechnung_block_und_tabellenkopf(self):
        from core.services.schlussabrechnung import generate_schlussabrechnung_pdf
        zeilen = [{'text': f'Position {i}', 'betrag': D('10.00'), 'zulasten': True} for i in range(40)]
        daten = {'auszug_datum': date(2026, 12, 31), 'saldo': D('400.00'), 'nachzahlung': True,
                 'rueckzahlung': D('0'), 'zeilen': zeilen}
        for n in range(26, 40):
            daten['zeilen'] = zeilen[:n]
            with self.subTest(zeilen=n):
                s = seiten(generate_schlussabrechnung_pdf(self.frisch(), daten, self.org))
                mit_saldo = [t for t, *_ in s if 'Nachzahlung durch Mieter' in t]
                self.assertEqual(len(mit_saldo), 1)
                for wort in ('Freundliche Grüsse', 'Art. 267a OR'):     # Saldo, Gruss und Rechtshinweis zusammen
                    self.assertIn(wort, mit_saldo[0])
                for t, *_ in s:                                         # jede Seite mit Positionen trägt den Tabellenkopf
                    if 'Position ' in t:
                        self.assertIn('zulasten', t)

    # ---- Sammel-PDF ----

    def test_sammel_pdf_zaehlt_je_dokument(self):
        from core.services.serienbrief import generate_serienbrief_pdf
        emp = [{'name': f'Mieter {i}', 'strasse': 'Weg 1', 'plz': '8000', 'ort': 'Zürich'} for i in range(3)]
        s = seiten(generate_serienbrief_pdf(
            {'firma': 'Testverwaltung AG', 'strasse': 'Teststrasse 1', 'plz': '8000', 'ort': 'Zürich'},
            'Betreff', 'Text', emp))
        self.assertEqual(len(s), 3)
        self.assertTrue(all('Seite 1 von 1' in t for t, *_ in s))
        self.assertTrue(all('Testverwaltung AG' in t for t, *_ in s))

    # ---- HTML-Briefe und Verträge ----

    def test_html_briefe_haben_das_adressfenster_beilagen_nicht(self):
        from core.services.dokument_service import generate_dokument_pdf_bytes
        for typ in ('begleitbrief', 'begleitbrief-signiert', 'kuendigungsbestaetigung'):
            with self.subTest(brief=typ):
                seite = seiten(generate_dokument_pdf_bytes(self.frisch(), typ))[0]
                text = ' '.join(w['text'] for w in im_fenster(seite))
                self.assertIn('Muster', text)
        for typ in ('hausordnung', 'allgemeine-bedingungen', 'merkblatt-lueften', 'wohnungsausweis'):
            with self.subTest(beilage=typ):
                seite = seiten(generate_dokument_pdf_bytes(self.frisch(), typ))[0]
                self.assertEqual([w for w in im_fenster(seite) if w['top'] > 41 * MM and 'Muster' in w['text']], [])

    def test_langer_absatz_laeuft_nicht_in_die_fusszeile(self):
        from core.services import mietprozess_briefe as mp
        lang = [{'raum': 'Bad', 'beschreibung': 'Spiegel zerbrochen ' * 10, 'betrag': 200}] * 14   # ein einziger Absatz
        s = seiten(mp.rueckgabe_maengelruege_pdf(self.frisch(), lang))
        self.assertGreaterEqual(len(s), 2)
        for _t, woerter, _b, _w, hoehe in s:
            for w in woerter:
                self.assertTrue(w['bottom'] <= hoehe - 24 * MM or w['top'] >= hoehe - 22 * MM,
                                f"«{w['text']}» steht im unteren Rand")

    def test_beilagen_haben_seitenkopf_ab_seite_2(self):
        from core.services.dokument_service import generate_dokument_pdf_bytes
        for typ in ('hausordnung', 'allgemeine-bedingungen'):
            with self.subTest(beilage=typ):
                s = seiten(generate_dokument_pdf_bytes(self.frisch(), typ))
                self.assertGreaterEqual(len(s), 2)
                kopf = ' '.join(w['text'] for w in s[1][1] if w['top'] < 16 * MM)
                self.assertIn('Teststrasse 1', kopf)                          # Referenz
                self.assertTrue(kopf.startswith(('Hausordnung', 'Allgemeine')), kopf)   # und Titel

    def test_garagenvertrag_unterschriften_nie_allein(self):
        """Verschieden lange Staffeltabellen schieben den Schlussblock über die Seitengrenze: der letzte
        Absatz und die Unterschriften stehen immer zusammen auf einer Seite."""
        from core.services.pdf_service import generate_vertrag_pdf_bytes
        from portfolio.models import Sollmietzins
        self.e.typ = 'pp'
        self.e.save()
        gesehen = set()
        for n in range(0, 17):
            if n:
                Sollmietzins.objects.create(einheit=self.e, gueltig_ab=date(2024, 1, 1) if n == 1 else
                                            date(2024 + (n - 1) // 12, (n - 1) % 12 + 1, 1),
                                            netto_mietzins=D('150') + n, nebenkosten=D('0'))
            with self.subTest(zeilen=n):
                s = seiten(generate_vertrag_pdf_bytes(self.frisch()))
                gesehen.add(len(s))
                mit = [t for t, *_ in s if 'Unterschriften' in t.split('\n')]
                self.assertEqual(len(mit), 1)
                self.assertIn('Der Mietzins ist jeweils am 1. Tag', mit[0])
                self.assertIn('Seite 1 von', s[0][0])
        self.assertGreaterEqual(len(gesehen), 2)          # Gegenprobe der Reihe: sie geht wirklich über die Seitengrenze

    def test_garagenvertrag_grundlayout_und_docuseal_marken(self):
        """Briefkopf, Seitenkopf ab Seite 2, Fusszeile, kein Adressfenster; die DocuSeal-Marken bleiben
        je einmal im Text (Wortlaut unverändert), auch im Kontext der DocuSeal-Wege (ohne `briefkopf`)."""
        from django.template.loader import get_template

        from core.services.pdf_service import generate_vertrag_pdf_bytes
        from core.views.docuseal import link_callback
        self.e.typ = 'pp'
        self.e.save()
        marken = ('{{Unterschrift Mieter;role=Mieter;type=signature;required=true}}',
                  '{{Ort Mieter;role=Mieter;type=text;required=true}}',
                  '{{Datum Mieter;role=Mieter;type=date;required=true}}')
        s = seiten(generate_vertrag_pdf_bytes(self.frisch()))
        self.assertIn('Testverwaltung AG', s[0][0].split('\n')[0])
        self.assertIn('Mietvertrag für einen Parkplatz', s[1][0].split('\n')[0])          # Seitenkopf ab Seite 2
        self.assertNotRegex(s[0][0], r'Testverwaltung AG · Teststrasse 1 · 8000')        # keine Absenderzeile des Fensters
        text = ' '.join(' '.join(t.split()) for t, *_ in s)
        for marke in marken:
            self.assertEqual(text.count(marke), 1, marke)
        # DocuSeal-Weg: eigener Kontext ohne `briefkopf` und ohne Zeitplan
        from xhtml2pdf import pisa
        v = self.frisch()
        ctx = {'vertrag': v, 'mieter': v.mieter, 'einheit': v.einheit, 'liegenschaft': v.einheit.liegenschaft,
               'eigentuemer': None, 'verwaltung': v.einheit.liegenschaft.organisation,
               'heute': date(2026, 11, 3), 'miete_fmt': '1500.00', 'nk_fmt': '0.00', 'brutto_fmt': '1500.00',
               'kaution_fmt': '0.00', 'unterschrift_path': None}
        puffer = io.BytesIO()
        status = pisa.CreatePDF(get_template('core/mietvertrag_garage.html').render(ctx), dest=puffer,
                                link_callback=link_callback)
        self.assertFalse(status.err)
        text = ' '.join(' '.join(t.split()) for t, *_ in seiten(puffer.getvalue()))
        for marke in marken:
            self.assertEqual(text.count(marke), 1, marke)
        self.assertIn('Testverwaltung AG', text)
