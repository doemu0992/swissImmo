"""STWEG-PDF im gemeinsamen Layout (Welle 2): Titel stehen nie allein am Seitenende, jede Seite trägt
Briefkopf bzw. Seitenkopf und «Seite x von y».

Gegenprobe (von Hand gemacht, rot gesehen, zurückgebaut): in `stweg/pdf.py` `_Seite.zeile` die Bedingung
`self.y - (12 * self.mm if fett else 0) < self.c.UNTEN` auf `self.y < self.c.UNTEN` setzen →
`test_traktandum_titel_nie_allein_am_seitenende` rot.
"""
import io
import re
from datetime import timedelta

import pdfplumber
from django.test import TestCase
from django.utils import timezone

from stweg.models import Traktandum, Versammlung
from stweg.pdf import einladung_pdf, protokoll_pdf
from stweg.test_versammlung import sonnenblick


class StwegPdfLayout(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV 2026', ort='Saal', status='geplant',
                                            datum=timezone.now() + timedelta(days=30))
        for i in range(1, 25):
            Traktandum.objects.create(geschaeftsart='sonstiges', rechtsgrundlage='x', versammlung=self.v, nr=i,
                                      titel=f'Traktandum {i}', beschreibung='Beschreibung ' * 30,
                                      mehrheitsart='doppelt_aller')

    def seiten(self, pdf):
        with pdfplumber.open(io.BytesIO(pdf)) as dok:
            return [s.extract_text() or '' for s in dok.pages]

    def test_traktandum_titel_nie_allein_am_seitenende(self):
        for name, pdf in (('protokoll', protokoll_pdf(self.v)), ('einladung', einladung_pdf(self.v, self.eigs[0]))):
            seiten = self.seiten(pdf)
            self.assertGreaterEqual(len(seiten), 2, name)
            for nr, text in enumerate(seiten, 1):
                zeilen = [z for z in text.split('\n') if z.strip()][:-1]       # ohne Fusszeile
                self.assertFalse(re.fullmatch(r'\d+\. Traktandum \d+', zeilen[-1]),
                                 f'{name}, Seite {nr}: Titel allein am Seitenende: {zeilen[-1]}')

    def test_jede_seite_hat_kopf_und_seitenzahl(self):
        seiten = self.seiten(protokoll_pdf(self.v))
        for nr, text in enumerate(seiten, 1):
            self.assertIn(f'Seite {nr} von {len(seiten)}', text)
        self.assertIn('Protokoll OV 2026', seiten[1])                           # Seitenkopf ab Seite 2
