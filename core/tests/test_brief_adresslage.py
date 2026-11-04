"""Adresslage und Zustellvermerk der Briefe mit Fenster (4.11.2026).

ANLASS: «Einschreiben» klebte direkt unter der Linie des Briefkopfs und über der Absenderzeile des Adressfensters
(Vermerk bei 41 mm von oben, Linie bei 38 mm, Absenderzeile bei 46 mm). Verlangt: ein freier Streifen mit
Abstand (mind. 4 mm) zur Linie UND zum Fenster, Schrift 10 pt fett, bündig mit der Anschrift; dazu ein kompakter
Briefkopf (Linie höchstens 30 mm von oben) und eine Absenderlinie, die nicht über den Textrand (190 mm) ragt.

Geprüft wird am ERZEUGTEN PDF (pdfplumber): Linie, Vermerk, Absenderzeile und Anschrift in mm von oben.
Was NICHT geprüft ist: ob das Fenster eines echten Umschlags dort liegt, wo `UMSCHLAGFENSTER` es annimmt — das
zeigt nur die Fensterprobe auf Papier (siehe `core/services/fensterprobe.py`).

Gegenproben (von Hand gemacht, rot gesehen, zurückgebaut):
* in `DokCanvas.brief` den Aufruf `self._kopf_fuer_brief()` entfernen -> `test_kopf_reicht_nicht_unter_30_mm`
  und `test_vermerk_hat_abstand_zu_linie_und_absenderzeile` sind rot;
* `VERMERK_GRUNDLINIE` auf `-4 * mm` (alte Lage: 4 mm UNTER der Oberkante) setzen -> `test_vermerk_hat_abstand_…` rot;
* in `fenster` die Linienlänge wieder auf `85 * mm` setzen -> `test_absenderlinie_endet_am_textrand` rot;
* in `fenster` die Zeilengrenze `[:ADRESS_ZEILEN_MAX]` entfernen -> `test_adresse_liegt_im_fenster` (sechs Zeilen) rot.
"""
import io
import os
import shutil
import tempfile
from datetime import date

import pdfplumber
from django.test import SimpleTestCase, TestCase
from PIL import Image
from reportlab.lib.units import mm

from core.services import dok_layout as dl
from core.services.dok_layout import DokCanvas, adressfeld_masse

from ._helfer import _basis_objekte, _test_organisation

MM = float(mm)


def _org(logo_pfad=None, **felder):
    """Eine Verwaltung ohne Datenbank — mit Telefon und E-Mail, wie der Fall, der den Vermerk an die Linie drückte."""
    from types import SimpleNamespace
    return SimpleNamespace(firma='Dominik Gerber Immobilien', strasse='Selzacherstrasse 4', plz='4512', ort='Bellach',
                           telefon='032 618 00 00', email='verwaltung@dgerber.example',
                           logo=SimpleNamespace(path=logo_pfad) if logo_pfad else None, briefkopf_farbe='',
                           briefkopf_fusszeile='', unterschrift_bild=None, **felder)


def _pdf(zeilen, einschreiben=False, logo=None, **felder):
    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=_org(logo, **felder), titel='Brief')
    c.brief(zeilen, 'Bellach, 04.11.2026', 'Betreff', einschreiben=einschreiben)
    c.showPage()
    c.save()
    return buf.getvalue()


def _logo(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    pfad = os.path.join(tmp, 'logo.png')
    Image.new('RGB', (600, 220), (30, 90, 140)).save(pfad)
    return pfad


def _lage(pdf):
    """Alles Wesentliche der ersten Seite in mm von oben: Linie des Briefkopfs, Vermerk, Absenderzeile,
    Absenderlinie, Anschriftwörter."""
    with pdfplumber.open(io.BytesIO(pdf)) as dok:
        seite = dok.pages[0]
        woerter = seite.extract_words(extra_attrs=['size', 'fontname'])
        linien = [(l['x0'] / MM, l['x1'] / MM, l['top'] / MM) for l in seite.lines if abs(l['top'] - l['bottom']) < 0.5]
    kopflinie = min((l for l in linien if (l[1] - l[0]) > 150), key=lambda l: l[2], default=None)
    vermerk = next((w for w in woerter if w['text'] == 'Einschreiben'), None)
    absender = [w for w in woerter if abs(w['size'] - dl.ABSENDER_SCHRIFT) < 0.2 and w['top'] / MM > 30]
    absenderlinie = next((l for l in linien if abs(l[0] - dl.FENSTER_X / MM) < 0.5), None)
    anschrift = [w for w in woerter if dl.ADRESS_SCHRIFT_MIN - 0.1 <= w['size'] <= dl.ADRESS_SCHRIFT + 0.1
                 and 44 <= w["top"] / MM <= 82 and w['x0'] / MM > 110]
    return {'kopflinie': kopflinie, 'vermerk': vermerk, 'absender': absender, 'absenderlinie': absenderlinie,
            'anschrift': anschrift}


class AdresslageTests(SimpleTestCase):

    def _faelle(self):
        logo = _logo(self)
        return {'ohne Logo': _pdf(['Behlül Piskin', 'Selzacherstrasse 4', '4512 Bellach'], einschreiben=True),
                'mit Logo': _pdf(['Behlül Piskin', 'Selzacherstrasse 4', '4512 Bellach'], einschreiben=True, logo=logo)}

    def test_vermerk_hat_abstand_zu_linie_und_absenderzeile(self):
        for name, pdf in self._faelle().items():
            with self.subTest(kopf=name):
                lage = _lage(pdf)
                v = lage['vermerk']
                self.assertIsNotNone(v, 'Der Vermerk fehlt.')
                zur_linie = v['top'] / MM - lage['kopflinie'][2]
                zum_fenster = min(w['top'] for w in lage['absender']) / MM - v['bottom'] / MM
                self.assertGreaterEqual(zur_linie, 4, f'Vermerk nur {zur_linie:.1f} mm unter der Linie des Briefkopfs')
                self.assertGreaterEqual(zum_fenster, 4, f'Vermerk nur {zum_fenster:.1f} mm über der Absenderzeile')

    def test_vermerk_schrift_ausrichtung_und_wortlaut(self):
        for name, pdf in self._faelle().items():
            with self.subTest(kopf=name):
                v = _lage(pdf)['vermerk']
                self.assertEqual(v['text'], 'Einschreiben', 'Nicht in Versalien: «Einschreiben».')
                self.assertAlmostEqual(v['size'], 10, delta=0.2)
                self.assertIn('Bold', v['fontname'])
                self.assertAlmostEqual(v['x0'] / MM, 118, delta=0.5, msg='bündig mit der Anschrift')

    def test_kopf_reicht_nicht_unter_30_mm(self):
        for name, pdf in self._faelle().items():
            with self.subTest(kopf=name):
                self.assertLessEqual(_lage(pdf)['kopflinie'][2], 30.0)

    def test_absenderlinie_endet_am_textrand(self):
        for name, pdf in self._faelle().items():
            with self.subTest(kopf=name):
                linie = _lage(pdf)['absenderlinie']
                self.assertAlmostEqual(linie[0], 118, delta=0.5)
                self.assertLessEqual(linie[1], 190.5, 'Die Linie ragt über den Textrand (190 mm).')
                self.assertGreater(linie[1] - linie[0], 60, 'Die Linie ist zu kurz geraten.')

    def test_adresse_liegt_im_fenster(self):
        """Auch sechs lange Zeilen (und eine siebte, die wegfällt) bleiben im Fenster mit 3 mm Rand."""
        links, oben, breite, hoehe = dl.UMSCHLAGFENSTER
        rand = dl.FENSTER_RAND_MIN / MM
        lang = ['Immobilien Treuhand Muster & Partner Aktiengesellschaft Zürich', 'z. H. Frau Dr. Maria Beispiel-Muster',
                'Abteilung Liegenschaftsverwaltung und Vermietung', 'Musterstrasse 123 b', 'Postfach 4567',
                '8000 Zürich', 'SIEBTE ZEILE']
        pdf = _pdf(lang)
        lage = _lage(pdf)
        woerter = lage['anschrift']
        self.assertNotIn('SIEBTE', [w['text'] for w in woerter], 'Mehr als sechs Zeilen passen nicht ins Fenster.')
        for w in woerter:
            self.assertGreaterEqual(w['x0'] / MM, links + rand)
            self.assertLessEqual(w['x1'] / MM, dl.RECHTS / MM + 0.5, f'«{w["text"]}» ragt über den Textrand')
            self.assertLessEqual(w['x1'] / MM, links + breite - rand)
            self.assertGreaterEqual(w['top'] / MM, oben + rand)
            self.assertLessEqual(w['bottom'] / MM, oben + hoehe - rand)
        # Das Mass-Modell rechnet dasselbe: Das Adressfeld mit sechs Zeilen liegt im Fenster.
        a_links, a_oben, a_rechts, a_unten = adressfeld_masse(6)
        self.assertGreaterEqual(a_links, links + rand)
        self.assertGreaterEqual(a_oben, oben + rand)
        self.assertLessEqual(a_rechts, links + breite - rand)
        self.assertLessEqual(a_unten, oben + hoehe - rand)

    def test_dokumente_ohne_adressblock_behalten_den_kopf(self):
        """Gegenprobe: Nur Briefe bekommen den kompakten Kopf; Berichte und Verträge bleiben, wie sie waren."""
        buf = io.BytesIO()
        c = DokCanvas(buf, organisation=_org(), titel='Bericht')
        # vier Kontaktzeilen (Strasse, Ort, Telefon, E-Mail): Höhe wie bisher, 46 pt + 7 pt unter 15 mm
        alt = c.hoehe - 15 * mm - max(20.0, len(c._rechts) * 11.5) - 7
        self.assertAlmostEqual(c.y_linie, alt, places=3)
        self.assertFalse(c._kompakt)


class EchteBriefeTests(TestCase):
    """Alle Briefe mit Adressfenster, so wie die Anwendung sie erzeugt."""

    def _briefe(self):
        from core.services import mietprozess_briefe as mp
        from core.services.herabsetzung_brief import antwortbrief_pdf
        from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
        from core.services.mahnbrief import mahnbrief_pdf
        lg, e, m, v = _basis_objekte()
        org = _test_organisation()
        kd = type('K', (), {'per_datum': date(2027, 3, 31), 'berechneter_termin': None, 'bemerkung': ''})()
        return {
            'kuendigung': (generate_kuendigung_mieter_pdf(v, kd, org), True),
            '257d': (mahnbrief_pdf(v, org, stufe=3, monat='Oktober 2026', betrag='1700.00', datum=date(2026, 11, 4),
                                   letzte_stufe=True), True),
            'zahlungserinnerung': (mahnbrief_pdf(v, org, stufe=1, monat='Oktober 2026', betrag='1700.00',
                                                 datum=date(2026, 11, 4)), False),
            'herabsetzung': (antwortbrief_pdf(v, 'ablehnung', date(2026, 11, 4)), False),
            'maengelruege': (mp.maengelruege_pdf(v, 'Wasserfleck'), False),
            'kaution': (mp.kaution_hinterlegung_pdf(v), False),
        }

    def test_alle_briefe_gleiche_hoehen(self):
        """Linie -> Vermerk -> Absenderzeile -> Anschrift stehen in jedem Brief auf derselben Höhe."""
        hoehen = {}
        for name, (pdf, mit_vermerk) in self._briefe().items():
            with self.subTest(brief=name):
                lage = _lage(pdf)
                self.assertLessEqual(lage['kopflinie'][2], 30.0)
                self.assertLessEqual(lage['absenderlinie'][1], 190.5)
                absender_top = min(w['top'] for w in lage['absender']) / MM
                anschrift_top = min(w['top'] for w in lage['anschrift']) / MM
                hoehen[name] = (round(absender_top, 1), round(anschrift_top, 1))
                if mit_vermerk:
                    v = lage['vermerk']
                    self.assertIsNotNone(v)
                    self.assertGreaterEqual(v['top'] / MM - lage['kopflinie'][2], 4)
                    self.assertGreaterEqual(absender_top - v['bottom'] / MM, 4)
                else:
                    self.assertIsNone(lage['vermerk'])
        self.assertEqual(len(set(hoehen.values())), 1, f'Absenderzeile/Anschrift nicht auf gleicher Höhe: {hoehen}')

    def test_einschreiben_wortlaut_der_257d_mahnung(self):
        """Die 257d-Mahnung hiess «EINSCHREIBEN» (Versalien); jetzt «Einschreiben» wie in der Kündigung."""
        pdf, _ = self._briefe()['257d']
        self.assertIsNotNone(_lage(pdf)['vermerk'])
        with pdfplumber.open(io.BytesIO(pdf)) as dok:
            self.assertNotIn('EINSCHREIBEN', dok.pages[0].extract_text())
