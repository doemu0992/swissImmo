"""Zahlteil und Empfangsschein gegen den offiziellen SIX Style Guide QR-Rechnung (DE) und die
Sprache des Empfängers (D11).

Geprüft wird das gezeichnete PDF (pdfplumber), nicht der Code. Was der Style Guide verlangt:

* Betrag mit BLANK als Tausendertrenner («1 590.00»), Punkt, zwei Nachkommastellen — nur im
  gedruckten Zahlteil. Der Datenteil des QR-Codes bleibt «1590.00».
* IBAN in 4er-Gruppen, QRR in 5er-Gruppen von rechts (erste Gruppe 2 Zeichen), SCOR in 4er-Gruppen.
* Zeilenabstände: Empfangsschein Überschrift/Wert 9 pt, Betrag 11 pt; Zahlteil 11 pt, Betrag 13 pt;
  zwischen den Blöcken eine Leerzeile.
* Zeilen über 90 Zeichen stehen mit «…» gekürzt da (Mitteilung), Namen und Adressen nie.
* Eckmarken der Leerfelder: 3 x 3 mm.
* Beschriftungen in DE/FR/IT/EN.
"""
import io
from datetime import date
from decimal import Decimal
from unittest import mock

import pdfplumber
from django.test import SimpleTestCase, TestCase
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.utils import qr_code
from core.utils.betrag import betrag_text, betrag_text_zahlteil
from core.utils.qr_code import draw_qr_bill, qrr_referenz

from ._isolation import MandantenFixture

QR_IBAN = 'CH44 3199 9123 0008 8901 2'
NORMAL_IBAN = 'CH93 0076 2011 6238 5295 7'
KURZ = {'name': 'Muster AG', 'line1': 'Bahnhofstrasse 1', 'line2': '8000 Zürich'}
SCHULDNER = {'name': 'Hans Muster', 'line1': 'Seestrasse 5', 'line2': '8002 Zürich'}
REF = qrr_referenz(1234, 202611)[0]


def pdf_von(iban=QR_IBAN, debtor=SCHULDNER, amount=1590.0, reason='Miete 11/2026', reference=REF, **kw):
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    draw_qr_bill(c, iban, KURZ, debtor, amount, reason, reference=reference, **kw)
    c.save()
    puffer.seek(0)
    return pdfplumber.open(puffer)


def zeilen(pdf, links):
    """Textzeilen (Text, Grundlinie in pt von unten, Schriftgrösse) des Empfangsscheins bzw. Zahlteils."""
    seite = pdf.pages[0]
    gruppiert = {}
    for ch in seite.chars:
        if 'Zapf' in ch['fontname'] or (ch['x0'] < 62 * mm) != links:
            continue
        # Zahlteil: nur die rechte Spalte (Angaben), nicht die Beschriftung unter dem QR-Code
        if not links and ch['x0'] < 118 * mm:
            continue
        gruppiert.setdefault(round(ch['matrix'][5], 1), []).append(ch)
    ergebnis = []
    for y, zeichen in gruppiert.items():
        zeichen.sort(key=lambda ch: ch['x0'])
        ergebnis.append((''.join(ch['text'] for ch in zeichen).strip(), y, round(zeichen[0]['size'], 1)))
    return sorted(ergebnis, key=lambda z: -z[1])


def volltext(pdf, links):
    seite = pdf.pages[0]
    rand = 62 * mm
    teil = seite.crop((0, 0, rand, seite.height)) if links else seite.crop((rand, 0, seite.width, seite.height))
    return teil.extract_text()


def abstand(zl, kopf, folge):
    """Abstand der Grundlinien zwischen der Zeile, die mit `kopf` beginnt, und der mit `folge` beginnt."""
    y_kopf = next(y for text, y, _g in zl if text.startswith(kopf))
    y_folge = next(y for text, y, _g in zl if text.startswith(folge))
    return round(y_kopf - y_folge, 1)


class BetragFormatTests(SimpleTestCase):
    def test_blank_als_tausendertrenner_im_zahlteil(self):
        self.assertEqual(betrag_text_zahlteil(Decimal('1590')), '1 590.00')
        self.assertEqual(betrag_text_zahlteil(Decimal('1234567.5')), '1 234 567.50')
        self.assertEqual(betrag_text_zahlteil(Decimal('85')), '85.00')
        # Alle übrigen Dokumente behalten den Apostroph
        self.assertEqual(betrag_text(Decimal('1590')), "1'590.00")

    def test_gedruckt_mit_blank_im_datenteil_ohne_trenner(self):
        pdf = pdf_von(amount=1590.0)
        for links in (True, False):
            self.assertIn('1 590.00', volltext(pdf, links))
            self.assertNotIn("1'590", volltext(pdf, links))
        erfasst = []
        echt = qr_code.segno.make

        def spion(daten, **kw):
            erfasst.append(daten)
            return echt(daten, **kw)

        with mock.patch.object(qr_code.segno, 'make', spion):
            pdf_von(amount=1590.0)
        self.assertIn('1590.00', erfasst[0].split('\n'))
        self.assertNotIn('1 590.00', erfasst[0])

    def test_zwei_nachkommastellen(self):
        self.assertIn('85.00', volltext(pdf_von(amount=85), False))


class GruppierungTests(SimpleTestCase):
    def test_iban_in_vierergruppen(self):
        self.assertEqual(qr_code.format_iban('CH4331999000001265789'), 'CH43 3199 9000 0012 6578 9')
        pdf = pdf_von()
        for links in (True, False):
            self.assertIn('CH44 3199 9123 0008 8901 2', volltext(pdf, links))

    def test_qrr_in_fuenfergruppen_von_rechts(self):
        self.assertEqual(qr_code.referenz_formatieren('QRR', '210000000003139471430009017'),
                         '21 00000 00003 13947 14300 09017')
        pdf = pdf_von()
        for links in (True, False):
            self.assertIn('00 00001 23400 00000 00020 26117', volltext(pdf, links))

    def test_scor_in_vierergruppen(self):
        self.assertEqual(qr_code.referenz_formatieren('SCOR', 'RF18539007547034'), 'RF18 5390 0754 7034')


class ZeilenabstandTests(SimpleTestCase):
    def test_empfangsschein(self):
        zl = zeilen(pdf_von(), True)
        self.assertEqual(abstand(zl, 'Konto', 'CH44'), 9.0)            # Überschrift → Wert: 9 pt
        self.assertEqual(abstand(zl, 'CH44', 'Muster AG'), 9.0)        # Werte: 9 pt
        self.assertEqual(abstand(zl, 'Muster AG', 'Bahnhofstrasse'), 9.0)
        self.assertEqual(abstand(zl, '8000', 'Referenz'), 18.0)         # eine Leerzeile dazwischen
        self.assertEqual(abstand(zl, 'Referenz', '00 00001'), 9.0)
        self.assertEqual(abstand(zl, '00 00001', 'Zahlbar durch'), 18.0)
        self.assertEqual(abstand(zl, 'Zahlbar durch', 'Hans Muster'), 9.0)
        self.assertEqual(abstand(zl, 'Währung', 'CHF'), 9.0)

    def test_zahlteil(self):
        zl = zeilen(pdf_von(), False)
        self.assertEqual(abstand(zl, 'Konto', 'CH44'), 11.0)
        self.assertEqual(abstand(zl, 'CH44', 'Muster AG'), 11.0)
        self.assertEqual(abstand(zl, '8000', 'Referenz'), 22.0)
        self.assertEqual(abstand(zl, '00 00001', 'Zusätzliche'), 22.0)
        self.assertEqual(abstand(zl, 'Zusätzliche', 'Miete'), 11.0)
        self.assertEqual(abstand(zl, 'Miete', 'Zahlbar durch'), 22.0)
        self.assertEqual(abstand(zl, 'Zahlbar durch', 'Hans Muster'), 11.0)

    def test_betragszeile_hat_ihre_eigene_schrift(self):
        # Betrag: Empfangsschein 8 pt, Zahlteil 10 pt (Überschrift 6 bzw. 8 pt fett)
        seite = pdf_von().pages[0]
        gr = {(ch['x0'] < 62 * mm): round(ch['size'], 1) for ch in seite.chars if ch['text'] == 'C' and ch['y0'] < 120}
        self.assertEqual(gr, {True: 8.0, False: 10.0})

    def test_weitere_informationen_7_pt_mit_8_pt_abstand(self):
        pdf = pdf_von(alternative_verfahren=['eBill/ABC;1', 'Zweites Verfahren'])
        zl = zeilen(pdf, False)
        self.assertEqual(abstand(zl, 'Weitere', 'eBill/ABC'), 8.0)
        self.assertEqual(abstand(zl, 'eBill/ABC', 'Zweites'), 8.0)
        self.assertEqual(next(g for t, _y, g in zl if t.startswith('eBill')), 7.0)

    def test_alternative_verfahren_stehen_im_datenteil(self):
        erfasst = []
        echt = qr_code.segno.make

        def spion(daten, **kw):
            erfasst.append(daten)
            return echt(daten, **kw)

        with mock.patch.object(qr_code.segno, 'make', spion):
            pdf_von(alternative_verfahren=['eBill/ABC;1'])
        zeilen_ = erfasst[0].split('\n')
        self.assertEqual(zeilen_[-2:], ['EPD', 'eBill/ABC;1'])


class KuerzenTests(SimpleTestCase):
    def test_mitteilung_ueber_90_zeichen_wird_mit_punkten_gekuerzt(self):
        lang = 'Akonto-Rechnung ' + 'x' * 120
        self.assertEqual(len(qr_code.zeile_kuerzen(lang)), 90)
        self.assertTrue(qr_code.zeile_kuerzen(lang).endswith('…'))
        self.assertEqual(qr_code.zeile_kuerzen('kurz'), 'kurz')
        self.assertIn('…', volltext(pdf_von(reason='Miete ' + 'abc ' * 40), False))

    def test_namen_werden_nie_gekuerzt(self):
        name = 'Erbengemeinschaft Hans und Margrit Müller-Schneider-Hugentobler und Kinder'
        pdf = pdf_von(debtor={'name': name, 'line1': 'Hauptstrasse 1', 'line2': '8002 Zürich'})
        text = volltext(pdf, True).replace('\n', ' ')
        self.assertNotIn('…', text)
        self.assertIn('Hugentobler', text)


class EckmarkenTests(SimpleTestCase):
    def test_eckmarken_sind_3_mal_3_mm(self):
        pdf = pdf_von(debtor={'name': '', 'line1': '', 'line2': ''}, amount=None)
        kurze = [ln for ln in pdf.pages[0].lines
                 if 0.5 * mm < max(abs(ln['x1'] - ln['x0']), abs(ln['bottom'] - ln['top'])) < 4 * mm]
        self.assertEqual(len(kurze), 32)
        for ln in kurze:
            self.assertAlmostEqual(max(abs(ln['x1'] - ln['x0']), abs(ln['bottom'] - ln['top'])), 3 * mm, delta=0.2)
            self.assertAlmostEqual(ln['linewidth'], 0.75, places=2)

    def test_leerfelder_haben_die_masse(self):
        pdf = pdf_von(debtor={'name': '', 'line1': '', 'line2': ''}, amount=None)
        seite = pdf.pages[0]
        kurze = [ln for ln in seite.lines if max(abs(ln['x1'] - ln['x0']), abs(ln['bottom'] - ln['top'])) < 4 * mm]
        # Die Aussenkanten der Eckmarken (x0 bzw. x1 in mm) sind die Feldgrenzen.
        kanten = {round(x / mm, 1) for ln in kurze for x in (ln['x0'], ln['x1'])}
        # Zahlteil: Zahlbar durch 118 → 183 (65 mm), Betrag 82 → 122 (40 mm)
        self.assertLessEqual({118.0, 183.0, 82.0, 122.0}, kanten)
        # Empfangsschein: Zahlbar durch 5 → 57 (52 mm), Betrag 17 → 47 (30 mm)
        self.assertLessEqual({5.0, 57.0, 17.0, 47.0}, kanten)


class SprachenTests(SimpleTestCase):
    ERWARTET = {
        'de': ('Zahlteil', 'Empfangsschein', 'Konto / Zahlbar an', 'Referenz', 'Zusätzliche Informationen',
               'Zahlbar durch', 'Währung', 'Betrag', 'Annahmestelle'),
        'fr': ('Section paiement', 'Récépissé', 'Compte / Payable à', 'Référence', 'Informations supplémentaires',
               'Payable par', 'Monnaie', 'Montant', 'Point de dépôt'),
        'it': ('Sezione pagamento', 'Ricevuta', 'Conto / Pagabile a', 'Riferimento', 'Informazioni supplementari',
               'Pagabile da', 'Valuta', 'Importo', 'Punto di accettazione'),
        'en': ('Payment part', 'Receipt', 'Account / Payable to', 'Reference', 'Additional information',
               'Payable by', 'Currency', 'Amount', 'Acceptance point'),
    }

    def test_alle_beschriftungen_je_sprache(self):
        for sprache, texte in self.ERWARTET.items():
            with self.subTest(sprache=sprache):
                pdf = pdf_von(sprache=sprache)
                titel_zt, titel_rs, konto, ref, info, durch, waehrung, betrag, annahme = texte
                links, rechts = volltext(pdf, True), volltext(pdf, False)
                self.assertIn(titel_rs, links)
                self.assertIn(titel_zt, rechts)
                for text in (konto, ref, durch, waehrung, betrag):
                    self.assertIn(text, links)
                    self.assertIn(text, rechts)
                self.assertIn(info, rechts)
                self.assertIn(annahme, links)
                # Keine deutsche Beschriftung in der fremden Sprache
                if sprache != 'de':
                    for deutsch in self.ERWARTET['de'][:2] + ('Konto / Zahlbar an', 'Annahmestelle'):
                        self.assertNotIn(deutsch, links + rechts)

    def test_leerfeld_beschriftung_je_sprache(self):
        leer = {'name': '', 'line1': '', 'line2': ''}
        for sprache, erwartet in (('de', 'Zahlbar durch (Name/Adresse)'), ('fr', 'Payable par (nom/adresse)'),
                                  ('it', 'Pagabile da (nome/indirizzo)'), ('en', 'Payable by (name/address)')):
            with self.subTest(sprache=sprache):
                self.assertIn(erwartet, volltext(pdf_von(debtor=leer, sprache=sprache), False))

    def test_weitere_informationen_je_sprache(self):
        for sprache, erwartet in (('de', 'Weitere Informationen'), ('fr', 'Informations additionnelles'),
                                  ('it', 'Informazioni aggiuntive'), ('en', 'Further information')):
            with self.subTest(sprache=sprache):
                pdf = pdf_von(sprache=sprache, alternative_verfahren=['eBill/ABC;1'])
                self.assertIn(erwartet, volltext(pdf, False))

    def test_unbekannte_oder_fehlende_sprache_ist_deutsch(self):
        for sprache in ('xx', '', None, 'rm'):
            with self.subTest(sprache=sprache):
                self.assertIn('Empfangsschein', volltext(pdf_von(sprache=sprache), True))

    def test_sprache_der_oberflaeche_ist_unerheblich(self):
        from django.utils import translation
        with translation.override('fr'):
            self.assertIn('Empfangsschein', volltext(pdf_von(), True))
            self.assertIn('Receipt', volltext(pdf_von(sprache='en'), True))


class AufruferGebenDieSpracheDesMietersWeiterTests(TestCase):
    """Alle Wege zum Zahlteil reichen `Mieter.sprache` an `draw_qr_bill` weiter."""
    IBAN = 'CH9300762011623852957'

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        lg = cls.a.liegenschaft
        lg.iban = cls.IBAN
        lg.save()
        cls.a.mieter.sprache = 'fr'
        cls.a.mieter.save()

    def sprache_der_aufrufe(self, ziel, aufruf):
        with mock.patch(ziel, wraps=draw_qr_bill) as zeichnen:
            aufruf()
        self.assertTrue(zeichnen.called, ziel)
        return {kw.get('sprache') for _args, kw in zeichnen.call_args_list}

    def test_debitor_qr(self):
        from core.services.debitor_qr import generate_debitor_qr_pdf
        sprachen = self.sprache_der_aufrufe('core.utils.qr_code.draw_qr_bill',
                                            lambda: generate_debitor_qr_pdf(self.a.debitor))
        self.assertEqual(sprachen, {'fr'})

    def test_mahnbrief(self):
        from core.services.mahnbrief import mahnbrief_pdf
        sprachen = self.sprache_der_aufrufe(
            'core.utils.qr_code.draw_qr_bill',
            lambda: mahnbrief_pdf(self.a.vertrag, self.a.organisation, stufe=1, monat='März 2026',
                                  betrag='1700.00', datum=date(2026, 3, 20), letzte_stufe=False))
        # Mahnungen bleiben wegen des Rechtstexts deutsch (core.services.dokumentsprache): Zahlteil und Brief
        # stehen in derselben Sprache.
        self.assertEqual(sprachen, {None})

    def test_mahnschreiben_257d_mit_gebuehr(self):
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        with mock.patch('core.views.email_views.draw_qr_bill', wraps=draw_qr_bill) as zeichnen:
            generate_mahnung_combined_pdf_bytes(
                self.a.vertrag, self.a.organisation, 'März 2026', '1700.00', date(2026, 3, 20),
                gebuehr=Decimal('20'))
        self.assertEqual({kw.get('sprache') for _a, kw in zeichnen.call_args_list}, {None})   # deutsch wie der Brief
        self.assertEqual(zeichnen.call_count, 2)

    def test_mietrechnung_view(self):
        self.client.force_login(self.a.benutzer)
        with mock.patch('core.views.billing.zahlteil_zeichnen', wraps=qr_code.zahlteil_zeichnen) as zeichnen:
            antwort = self.client.get(f'/vertrag/{self.a.vertrag.pk}/qr/')
        self.assertEqual(antwort.status_code, 200, antwort.content[:200])
        self.assertEqual(zeichnen.call_args.kwargs['sprache'], 'fr')

    def test_nk_einzelabrechnung(self):
        from core.views.email_views import generate_single_pdf_bytes
        zeile = {'typ': 'mieter', 'name': 'Mieter A', 'einheit': '3.5 Zi', 'kosten_anteil': Decimal('800'),
                 'akonto': Decimal('500'), 'saldo': Decimal('300'), 'nachzahlung': True}
        with mock.patch('core.views.email_views.draw_qr_bill', wraps=draw_qr_bill) as zeichnen:
            generate_single_pdf_bytes(self.a.periode, zeile, self.a.organisation,
                                      self.a.liegenschaft, self.a.vertrag)
        self.assertEqual({kw.get('sprache') for _a, kw in zeichnen.call_args_list}, {'fr'})

    def test_nk_sammelabrechnung_je_zeile(self):
        zeile = {'typ': 'mieter_akonto', 'vertrag_id': self.a.vertrag.pk, 'name': 'Mieter A', 'einheit': '3.5 Zi',
                 'kosten_anteil': Decimal('800'), 'akonto': Decimal('500'), 'saldo': Decimal('300'),
                 'nachzahlung': True}
        self.client.force_login(self.a.benutzer)
        with mock.patch('core.views.billing.hole_abrechnung', return_value={'abrechnungen': [zeile]}), \
                mock.patch('core.views.billing.draw_qr_bill', wraps=draw_qr_bill) as zeichnen:
            antwort = self.client.get(f'/abrechnung/{self.a.periode.pk}/pdf/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual({kw.get('sprache') for _a, kw in zeichnen.call_args_list}, {'fr'})

    def test_mieterqr_und_mahnung_pdf_im_qr_modul(self):
        from django.test import override_settings
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            sprachen = self.sprache_der_aufrufe(
                'core.utils.qr_code.draw_qr_bill',
                lambda: qr_code.generate_mieter_qr_pdf(self.a.mieter, self.a.vertrag, self.a.organisation))
            self.assertEqual(sprachen, {'fr'})
            sprachen = self.sprache_der_aufrufe(
                'core.utils.qr_code.draw_qr_bill',
                lambda: qr_code.generate_mahnung_pdf(self.a.vertrag, Decimal('100'), self.a.organisation))
            self.assertEqual(sprachen, {'fr'})
