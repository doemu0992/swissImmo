"""Zielbild: Zeilenaktionen, Dialog und «Neu» tragen die Akzentfarbe. Seit dem Mix-Entwurf (21.11.2026) auch die Seitenknöpfe —
im Mockup sind alle Hauptknöpfe orange; die Regel steht im Modul «Mix-Entwurf» am Ende der Schicht und überschreibt das frühere Schwarz."""
import pathlib

from django.test import SimpleTestCase

SCHICHT = pathlib.Path(__file__).resolve().parents[1] / "templates" / "fw" / "_schicht.html"


class PrimaerknopfAkzentTest(SimpleTestCase):
    def setUp(self):
        self.css = SCHICHT.read_text(encoding="utf-8")

    def test_zeilenknopf_und_dialog_sind_akzent(self):
        self.assertIn(".fw-btn.fw-knapp.fw-primary,.fw-zdlg .fw-btn.fw-primary{background:var(--ds-brand)", self.css)

    def test_seitenknopf_ist_im_mix_akzent(self):
        mix = self.css[self.css.index("MODUL Mix-Entwurf"):]
        self.assertIn(".fw-btn.fw-primary{background:var(--ds-brand);color:var(--ds-auf-satt)", mix)

    def test_neu_in_der_kopfzeile_ist_akzent(self):
        zeile = next(z for z in self.css.splitlines() if ".fw-werkzeug-kapsel .fw-wz-neu{" in z)
        self.assertIn("background:var(--ds-brand)", zeile)
