"""Fensterprobe und Versatz der Adresslage (4.11.2026).

Die Probe ist ein Hilfsmittel, mit dem die Verwaltung selbst prüft, ob die Adresse im Fenster ihres Umschlags
steht (Masse und Herkunft: `core/services/dok_layout.py`; NICHT gegen einen echten Umschlag geprüft). Der Versatz
(`Organisation.adress_versatz_x_mm/_y_mm`, Vorgabe 0 = Verhalten unverändert) verschiebt Absenderzeile, Linie,
Anschrift und Zustellvermerk gemeinsam; das Umschlagfenster der Probe bleibt stehen.

Gegenproben (von Hand gemacht, rot gesehen, zurückgebaut):
* in `fensterprobe._umrisse` die Falzmarken-Schleife entfernen -> `test_probe_hat_falzmarken_fenster_und_massstab` rot;
* in `DokCanvas.adressfeld_links` den Versatz weglassen -> `test_versatz_verschiebt_den_ganzen_adressblock` rot;
* in `fw_fensterprobe` `aktuelle_organisation()` durch `Organisation.objects.order_by('pk').first()` ersetzen
  -> `test_probe_traegt_nur_den_versatz_der_eigenen_verwaltung` rot;
* in `fw_account` den Bereich «Adresslage» entfernen -> `test_versatz_wird_gespeichert_und_geprueft` rot.
"""
import io
from decimal import Decimal
from types import SimpleNamespace

import pdfplumber
from django.test import Client, SimpleTestCase, TestCase
from reportlab.lib.units import mm

from core.services import dok_layout as dl
from core.services.dok_layout import DokCanvas
from core.services.fensterprobe import FALZMARKEN_MM, MASSSTAB_MM, fensterprobe_pdf
from core.tests._isolation import MandantenFixture

MM = float(mm)


def _org(**felder):
    return SimpleNamespace(firma='Dominik Gerber Immobilien', strasse='Selzacherstrasse 4', plz='4512', ort='Bellach',
                           telefon='', email='', logo=None, briefkopf_farbe='', briefkopf_fusszeile='',
                           unterschrift_bild=None, **felder)


def _seiten(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as dok:
        return [(s.extract_text() or '', s.extract_words(extra_attrs=['size']), list(s.lines), list(s.rects))
                for s in dok.pages]


class ProbeInhaltTests(SimpleTestCase):

    def test_probe_hat_falzmarken_fenster_und_massstab(self):
        seiten = _seiten(fensterprobe_pdf(_org()))
        self.assertEqual(len(seiten), 2)
        text, woerter, linien, rechtecke = seiten[0]
        flach = ' '.join(text.split())
        for erwartet in ('Fensterprobe', 'Falzmarke 99 mm', 'Falzmarke 198 mm', 'Massstab-Kontrolle',
                         'Die Adresse muss im Fenster stehen', 'Umschlagfenster (Annahme'):
            self.assertIn(erwartet, flach)
        # Falzmarken: kurze waagrechte Striche am Rand, bei 99 und 198 mm von oben (A4 in drei gleiche Teile)
        for y_mm in FALZMARKEN_MM:
            marken = [l for l in linien if abs(l['top'] / MM - y_mm) < 0.3 and l['x0'] < 1 and (l['x1'] - l['x0']) / MM < 10]
            self.assertTrue(marken, f'Falzmarke bei {y_mm} mm fehlt.')
        self.assertEqual(FALZMARKEN_MM, (99, 198))
        # Massstabsstrecke: genau 100 mm lang
        strecken = [l for l in linien if abs((l['x1'] - l['x0']) / MM - MASSSTAB_MM) < 0.2 and abs(l['top'] - l['bottom']) < 0.5]
        self.assertTrue(strecken, 'Die 100-mm-Strecke fehlt oder hat die falsche Länge.')
        # Fensterumriss: das Rechteck der Annahme (links, oben, Breite, Höhe)
        links, oben, breite, hoehe = dl.UMSCHLAGFENSTER
        fenster = [r for r in rechtecke if abs(r['x0'] / MM - links) < 0.3 and abs(r['top'] / MM - oben) < 0.3
                   and abs((r['x1'] - r['x0']) / MM - breite) < 0.3 and abs((r['bottom'] - r['top']) / MM - hoehe) < 0.3]
        self.assertTrue(fenster, 'Der Fensterumriss fehlt oder liegt anderswo als UMSCHLAGFENSTER.')

    def test_anschrift_der_probe_liegt_im_umriss(self):
        links, oben, breite, hoehe = dl.UMSCHLAGFENSTER
        rand = dl.FENSTER_RAND_MIN / MM
        for nr, (_t, woerter, _l, _r) in enumerate(_seiten(fensterprobe_pdf(_org())), 1):
            anschrift = [w for w in woerter if dl.ADRESS_SCHRIFT_MIN - 0.1 <= w['size'] <= dl.ADRESS_SCHRIFT + 0.1
                         and 44 <= w['top'] / MM <= 82 and w['x0'] / MM > 110]
            self.assertTrue(anschrift)
            for w in anschrift:
                with self.subTest(seite=nr, wort=w['text']):
                    self.assertGreaterEqual(w['x0'] / MM, links + rand)
                    self.assertLessEqual(w['x1'] / MM, links + breite - rand)
                    self.assertGreaterEqual(w['top'] / MM, oben + rand)
                    self.assertLessEqual(w['bottom'] / MM, oben + hoehe - rand)


class VersatzTests(SimpleTestCase):

    def _lage(self, **felder):
        buf = io.BytesIO()
        c = DokCanvas(buf, organisation=_org(**felder), titel='Brief')
        c.brief(['Behlül Piskin', 'Selzacherstrasse 4', '4512 Bellach'], 'Bellach, 04.11.2026', 'Betreff',
                einschreiben=True)
        c.showPage()
        c.save()
        _t, woerter, linien, _r = _seiten(buf.getvalue())[0]
        ein = next(w for w in woerter if w['text'] == 'Einschreiben')
        name = next(w for w in woerter if w['text'] == 'Behlül')
        absender = next(w for w in woerter if abs(w['size'] - dl.ABSENDER_SCHRIFT) < 0.2 and w['top'] / MM > 30)
        linie = next(l for l in linien if abs(l['top'] / MM - absender['bottom'] / MM) < 2.5 and l['x1'] - l['x0'] > 100)
        return {'ein': ein, 'name': name, 'absender': absender, 'linie': linie}

    def test_ohne_versatz_bleibt_alles_wie_bisher(self):
        a = self._lage()
        self.assertAlmostEqual(a['name']['x0'] / MM, 118, delta=0.5)
        self.assertAlmostEqual(a['absender']['x0'] / MM, 118, delta=0.5)
        # Gegenprobe: ein nicht lesbarer Wert zählt als 0 (kein Fehler beim Briefdruck)
        b = self._lage(adress_versatz_x_mm='abc')
        self.assertAlmostEqual(b['name']['x0'], a['name']['x0'], places=3)

    def test_versatz_verschiebt_den_ganzen_adressblock(self):
        a = self._lage()
        b = self._lage(adress_versatz_x_mm=Decimal('5.0'), adress_versatz_y_mm=Decimal('-3.5'))
        for teil in ('ein', 'name', 'absender'):
            with self.subTest(teil=teil):
                self.assertAlmostEqual((b[teil]['x0'] - a[teil]['x0']) / MM, 5.0, delta=0.05)
                self.assertAlmostEqual((b[teil]['top'] - a[teil]['top']) / MM, -3.5, delta=0.05)
        self.assertAlmostEqual((b['linie']['x0'] - a['linie']['x0']) / MM, 5.0, delta=0.05)


class ProbeAnsichtTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _client(self, fixture):
        c = Client()
        c.force_login(fixture.benutzer)
        return c

    def test_probe_ist_ein_pdf_fuer_angemeldete(self):
        antwort = self._client(self.a).get('/neu/account/fensterprobe/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        self.assertTrue(antwort.content.startswith(b'%PDF'))
        # Gegenprobe: ohne Anmeldung kein PDF
        anonym = Client().get('/neu/account/fensterprobe/')
        self.assertNotEqual(anonym.status_code, 200)
        self.assertNotEqual(anonym.get('Content-Type'), 'application/pdf')

    def test_probe_traegt_nur_den_versatz_der_eigenen_verwaltung(self):
        from crm.models import Organisation
        # B hat einen Versatz von 7 mm, A keinen. A bekommt die Probe ohne Versatz.
        Organisation.objects.filter(pk=self.b.organisation.pk).update(adress_versatz_x_mm=Decimal('7.0'))
        text = ' '.join(_seiten(self._client(self.a).get('/neu/account/fensterprobe/').content)[0][0].split())
        self.assertIn('Versatz x = 0 mm', text)
        self.assertNotIn('Versatz x = 7 mm', text)
        # Gegenprobe: B sieht seinen eigenen Versatz.
        text_b = ' '.join(_seiten(self._client(self.b).get('/neu/account/fensterprobe/').content)[0][0].split())
        self.assertIn('Versatz x = 7 mm', text_b)

    def test_versatz_wird_gespeichert_und_geprueft(self):
        org = self.a.organisation
        c = self._client(self.a)
        basis = {'firma': org.firma, 'strasse': org.strasse, 'plz': org.plz, 'ort': org.ort}
        c.post('/neu/account/', {**basis, 'adress_versatz_x_mm': '2,5', 'adress_versatz_y_mm': '-3'})
        org.refresh_from_db()
        self.assertEqual((org.adress_versatz_x_mm, org.adress_versatz_y_mm), (Decimal('2.5'), Decimal('-3.0')))
        # ungültig oder ausser Reichweite: unverändert
        for schlecht in ('15', '-10.5', 'abc'):
            with self.subTest(wert=schlecht):
                c.post('/neu/account/', {**basis, 'adress_versatz_x_mm': schlecht, 'adress_versatz_y_mm': '1'})
                org.refresh_from_db()
                self.assertEqual(org.adress_versatz_x_mm, Decimal('2.5'))
                self.assertEqual(org.adress_versatz_y_mm, Decimal('1.0'))   # der gültige Nachbarwert wird übernommen
        # Das Marktdaten-Formular schickt die Felder nicht mit: nichts geht verloren.
        c.post('/neu/account/', {**basis, 'aktueller_referenzzinssatz': '1.25'})
        org.refresh_from_db()
        self.assertEqual((org.adress_versatz_x_mm, org.adress_versatz_y_mm), (Decimal('2.5'), Decimal('1.0')))
        # Die Einstellungsseite zeigt die Felder und den Link zur Probe.
        html = c.get('/neu/account/').content.decode()
        self.assertIn('name="adress_versatz_x_mm"', html)
        self.assertIn('/neu/account/fensterprobe/', html)
        # Fremde Verwaltung bleibt unberührt.
        self.b.organisation.refresh_from_db()
        self.assertEqual(self.b.organisation.adress_versatz_x_mm, Decimal('0.0'))


class ProbeSpracheTests(SimpleTestCase):
    """Die Probe spricht die Sprache der Verwaltung (fr/it/en in locale/*/django.po).

    Gegenprobe: den Eintrag «Falzmarke %(mm)s mm» aus locale/fr/LC_MESSAGES/django.po entfernen (und .mo neu bauen)
    -> der Test ist rot."""

    def test_falzmarke_und_hinweis_in_den_drei_sprachen(self):
        from django.utils import translation
        erwartet = {'fr': ('Repère de pliage 99 mm', "l'adresse doit apparaître dans la fenêtre"),
                    'it': ('Segno di piegatura 99 mm', "l'indirizzo deve apparire nella finestra"),
                    'en': ('Fold mark 99 mm', 'the address must appear in the window')}
        for sprache, (marke, hinweis) in erwartet.items():
            with self.subTest(sprache=sprache), translation.override(sprache):
                text = ' '.join(_seiten(fensterprobe_pdf(_org()))[0][0].split())
                self.assertIn(marke, text)
                self.assertIn(hinweis, text)
                self.assertNotIn('Falzmarke', text)
