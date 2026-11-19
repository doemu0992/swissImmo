"""Zielbild: Zeilenaktionen, Dialog und «Neu» tragen die Akzentfarbe, Seitenknöpfe bleiben schwarz."""
import pathlib

from django.test import SimpleTestCase

SCHICHT = pathlib.Path(__file__).resolve().parents[1] / "templates" / "fw" / "_schicht.html"


class PrimaerknopfAkzentTest(SimpleTestCase):
    def setUp(self):
        self.css = SCHICHT.read_text(encoding="utf-8")

    def test_zeilenknopf_und_dialog_sind_akzent(self):
        self.assertIn(".fw-btn.fw-knapp.fw-primary,.fw-zdlg .fw-btn.fw-primary{background:var(--ds-brand)", self.css)

    def test_seitenknopf_bleibt_schwarz(self):
        self.assertIn(".fw-btn.fw-primary{background:var(--ds-ink)", self.css)

    def test_neu_in_der_kopfzeile_ist_akzent(self):
        zeile = next(z for z in self.css.splitlines() if ".fw-werkzeug-kapsel .fw-wz-neu{" in z)
        self.assertIn("background:var(--ds-brand)", zeile)
