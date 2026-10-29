"""Druck, PDF und Mail tragen Ember (Etappe 3, DESIGN-16).

Bis hierher standen auf Dokumenten und in Mails Indigo `#4F46E5` (sechs PDF-Erzeuger), `#4338CA`
(Steuerauszug, Nebenkostenabrechnung, Mail), Marineblau (Mieterkonto, Portfolio-Report, Mail) und ein
helles Blau (Treppenhaus-Poster) — drei Blautöne und kein Ember. Die Marke steht jetzt an einer Stelle
(`core/services/druckfarben.py`), und diese Datei sichert drei Dinge:

  1. Die Werte sind die der Oberfläche (`--ds-brand` & Co. in `_schicht.html`), sie können nicht abdriften.
  2. Kein Erzeuger enthält die alten Farben mehr (Quelltextsuche über alle Dienste, Ansichten, Mails).
  3. Ein erzeugtes PDF und die gerenderte Mail tragen Ember — gemessen am Ergebnis, nicht am Quelltext.

Gegenproben (29.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * `EMBER` in druckfarben.py auf `#4F46E5` ändern         → `test_die_werte_sind_die_der_oberflaeche` rot
  * im Poster wieder `setFillColorRGB(0.1, 0.4, 0.8)`        → `test_keine_alten_farben…` und `test_das_poster…` rot
  * in `base_email.html` `#b04416` auf `#4f46e5` zurück      → `test_die_mailvorlage…` rot
  * in `email_service.py` einen `{EMBER}` durch `#4338ca`     → `test_keine_alten_farben…` rot
"""
import io
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from core.services import druckfarben

from ._isolation import MandantenFixture

WURZEL = Path(__file__).resolve().parents[2]

#: Die Farben, die es nicht mehr geben darf — als Quelltext, wie sie in Erzeugern standen.
ALT = (
    r'#4F46E5', r'#4338CA', r'#1E3A8A',                       # Indigo und Marine als Hexwert
    r'0\.26,\s*0\.22,\s*0\.79',                             # = #4338CA als reportlab-RGB
    r'0\.12,\s*0\.23,\s*0\.54',                             # = #1E3A8A
    r'0\.1,\s*0\.4,\s*0\.8\)',                              # das hellblaue Poster
)
ALT_RE = re.compile('|'.join(ALT), re.I)

#: Wo gedruckt oder gemailt wird. Der Django-Admin (`*/admin.py`) ist eine eigene Oberfläche.
SUCHE = [
    *sorted((WURZEL / 'core' / 'services').glob('*.py')),
    *sorted((WURZEL / 'core' / 'views').rglob('*.py')),
    *sorted((WURZEL / 'core' / 'utils').glob('*.py')),
    *sorted((WURZEL / 'core' / 'management').rglob('*.py')),
    *sorted((WURZEL / 'tickets').glob('*.py')),
    *sorted((WURZEL / 'stweg').glob('*.py')),
    *sorted((WURZEL / 'core' / 'templates' / 'emails').glob('*.html')),
    *sorted((WURZEL / 'core' / 'templates' / 'core').glob('dok_*.html')),
    *sorted((WURZEL / 'core' / 'templates' / 'core').glob('mietvertrag_*.html')),
]
# druckfarben.py selbst nennt die alten Werte in seinem Erklärtext — das ist kein Gebrauch.
SUCHE = [p for p in SUCHE if not p.name.startswith(('test_', 'tests')) and p.name != 'druckfarben.py']


class EmberWerteTests(SimpleTestCase):
    def test_die_werte_sind_die_der_oberflaeche(self):
        schicht = (WURZEL / 'core' / 'templates' / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        hell = schicht[schicht.index(':root{'):]
        hell = hell[:hell.index('@media (prefers-color-scheme:dark)')]
        self.assertIn(f'--ds-brand:{druckfarben.EMBER.lower()};', hell)
        self.assertIn(f'--ds-brand-600:{druckfarben.EMBER_TIEF.lower()};', hell)
        self.assertIn(f'--ds-brand-soft:{druckfarben.EMBER_FLAECHE.lower()};', hell)

    def test_rgb_ist_dasselbe_in_0_bis_1(self):
        r, g, b = druckfarben.EMBER_RGB
        self.assertEqual((round(r * 255), round(g * 255), round(b * 255)), (0xB0, 0x44, 0x16))

    def test_weisse_schrift_auf_ember_erreicht_aa(self):
        def hell(rgb):
            k = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
            return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2]
        kontrast = 1.05 / (hell(druckfarben.EMBER_RGB) + 0.05)
        self.assertGreaterEqual(kontrast, 4.5, f'{kontrast:.2f}:1')


class KeineAltenFarbenTests(SimpleTestCase):
    def test_die_suche_findet_ueberhaupt_dateien(self):
        """Sonst wäre der Wächter darunter trivial grün."""
        self.assertGreater(len(SUCHE), 100)

    def test_keine_alten_farben_in_erzeugern_und_mails(self):
        treffer = []
        for pfad in SUCHE:
            text = pfad.read_text(encoding='utf-8')
            # Erklärtexte, die die alten Werte nennen (dieses Modul, druckfarben.py), sind kein Gebrauch.
            for m in ALT_RE.finditer(text):
                zeile = text.count('\n', 0, m.start()) + 1
                treffer.append(f'{pfad.relative_to(WURZEL)}:{zeile}: {m.group(0)}')
        self.assertEqual(treffer, [], 'Alte Blautöne auf Dokument oder Mail — Ember aus core/services/druckfarben.py nehmen')


class ErgebnisTraegtEmberTests(TestCase):
    """Gemessen am erzeugten Dokument: Die Farbbefehle der reportlab-Canvas, die es wirklich gab."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _farben(self, erzeuger):
        """Alle Füllfarben als (r, g, b) auf 0..255 gerundet, die der Erzeuger gesetzt hat."""
        from reportlab.pdfgen.canvas import Canvas
        gesehen = []
        rgb = Canvas.setFillColorRGB
        farbe = Canvas.setFillColor

        def merke_rgb(self, r, g, b, alpha=None):
            gesehen.append((round(r * 255), round(g * 255), round(b * 255)))
            return rgb(self, r, g, b, alpha)

        def merke_farbe(self, aColor, alpha=None):
            if hasattr(aColor, 'red'):
                gesehen.append((round(aColor.red * 255), round(aColor.green * 255), round(aColor.blue * 255)))
            return farbe(self, aColor, alpha)

        with patch.object(Canvas, 'setFillColorRGB', merke_rgb), patch.object(Canvas, 'setFillColor', merke_farbe):
            erzeuger()
        return gesehen

    def test_das_poster_traegt_ember_nicht_blau(self):
        from tickets.services import generate_qr_poster
        farben = self._farben(lambda: generate_qr_poster(self.a.liegenschaft, 'immoswiss.example'))
        self.assertIn((0xB0, 0x44, 0x16), farben)
        self.assertNotIn((26, 102, 204), farben)

    def test_die_auswertung_traegt_ember_nicht_indigo(self):
        from core.services.auswertung_pdf import generate_auswertung_pdf
        monate = [{'m': m, 'wert': Decimal(m * 100)} for m in range(1, 13)]
        farben = self._farben(lambda: generate_auswertung_pdf(
            'Erträge', 2026, 'Testweg 1', Decimal('7800'), monate, []))
        self.assertIn((0xB0, 0x44, 0x16), farben)
        self.assertNotIn((0x4F, 0x46, 0xE5), farben)


class MailTraegtEmberTests(TestCase):
    def test_die_mailvorlage_traegt_ember(self):
        html = render_to_string('emails/base_email.html', {'firma_name': 'Test AG'}).lower()
        self.assertIn('#b04416', html)
        self.assertNotIn('#4f46e5', html)
        self.assertNotIn('#4338ca', html)

    def test_die_zugangsmails_tragen_ember(self):
        from core.utils import email_service
        for senden in (email_service.send_mieter_portal_zugang, email_service.send_eigentuemer_portal_zugang):
            with self.subTest(funktion=senden.__name__), \
                    patch.object(email_service, 'send_via_hoststar', return_value=True) as raus:
                senden('x@example.ch', 'Frau Muster', 'benutzer', 'Geheim-1', 'https://example.ch/login/')
            html = raus.call_args.args[2].lower()
            self.assertIn(druckfarben.EMBER.lower(), html)
            self.assertNotIn('#4338ca', html)
            self.assertNotIn('#1e3a8a', html)
