"""Beträge einlesen und eingeben (DESIGN-28).

Das Audit vom 28.10.2026: Der Mietvertrags-Assistent lehnte «1'450.50» ab (`type="number"`), und
mehr als fünf eigene Parser nahmen je einen anderen Teil der üblichen Schreibweisen.

* `UmwandlungTests`: die Regeln von `core.utils.betrag`, als Tabelle.
* `EinParserTests`: Jeder der früheren Sonderparser nimmt jetzt «1'450.50».
* `JsGleichZuPythonTests`: Das Skript des Betragsfeldes (`fwZahl`) liest dieselbe Tabelle gleich.
* `FormularTests`: Die Seiten bieten Textfelder an, und der Server nimmt die Schweizer Schreibweise.
* `VorlagenWaechterTests`: Kein `type="number"` für einen Geldbetrag.
"""
import json
import pathlib
import re
import shutil
import subprocess
from decimal import Decimal

from django.conf import settings
from django.test import SimpleTestCase

from ._rollen import RollenBasis

from core.utils.betrag import betrag_normalisieren, betrag_oder_none, betrag_parsen, betrag_text

#: (Eingabe, erwarteter Wert)
GUELTIG = [
    ("1'450.50", '1450.50'), ("1’450.50", '1450.50'), ("1ʼ450.50", '1450.50'),
    ('1 450.50', '1450.50'), ('1 450.50', '1450.50'), ('1 450.50', '1450.50'),
    ('1450,5', '1450.5'), ('1450.50', '1450.50'), ('1450', '1450'),
    ("CHF 1'450.50", '1450.50'), ("chf1'450.50", '1450.50'), ("1'450.50 CHF", '1450.50'), ('Fr. 12', '12'),
    ('1.450,50', '1450.50'), ('1,450.50', '1450.50'),
    ('1.234.567', '1234567'), ('1,234,567', '1234567'),
    ("-1'450.50", '-1450.50'), ('−5', '-5'), ('+7', '7'), ('.5', '0.5'), ('0', '0'), ('  12.5  ', '12.5'),
    # Ein einzelnes Trennzeichen ist ein Dezimaltrenner (Vorrang des Bestands).
    ('1,450', '1.450'), ('1.450', '1.450'),
]
UNGUELTIG = ['', '   ', 'abc', '12abc', '--5', '1e5', "1'2'a", 'CHF', ',', '.', None]


class UmwandlungTests(SimpleTestCase):
    def test_gueltige_schreibweisen(self):
        for roh, erwartet in GUELTIG:
            with self.subTest(roh=roh):
                self.assertEqual(betrag_parsen(roh), Decimal(erwartet))

    def test_ungueltiges_wirft_value_error_und_oder_none_gibt_none(self):
        for roh in UNGUELTIG:
            with self.subTest(roh=roh):
                with self.assertRaises(ValueError):
                    betrag_parsen(roh)
                self.assertIsNone(betrag_oder_none(roh))

    def test_normalisieren_veraendert_leeres_nicht_in_null(self):
        self.assertEqual(betrag_normalisieren(None), '')
        self.assertEqual(betrag_normalisieren('  '), '')

    def test_anzeige_und_einlesen_sind_umkehrbar(self):
        for wert in (Decimal('0'), Decimal('12.5'), Decimal('1450.5'), Decimal('1234567.89'), Decimal('-1450.50')):
            with self.subTest(wert=wert):
                self.assertEqual(betrag_parsen(betrag_text(wert)), wert.quantize(Decimal('0.01')))
        self.assertEqual(betrag_text(Decimal('1450.5')), "1'450.50")
        self.assertEqual(betrag_text(None), '')
        self.assertEqual(betrag_text('kein Betrag'), '')


class EinParserTests(SimpleTestCase):
    """Die früheren Sonderparser: Jeder nimmt jetzt «1'450.50» (vorher scheiterte mindestens einer)."""

    def test_mahnstufen(self):
        from core.views.fw.mahnstufen import _betrag
        self.assertEqual(_betrag("1'450.50"), Decimal('1450.50'))
        self.assertEqual(_betrag('1450,5'), Decimal('1450.50'))
        self.assertEqual(_betrag(''), Decimal('0.00'))
        self.assertIsNone(_betrag('abc'))
        self.assertIsNone(_betrag('-5'))

    def test_kuendigung(self):
        from core.views.fw.kuendigung import _num_oder_leer
        self.assertEqual(_num_oder_leer("1'450.50"), '1450.50')
        self.assertEqual(_num_oder_leer('1 450,5'), '1450.5')
        self.assertEqual(_num_oder_leer(None), '')

    def test_zahlungsklaerung(self):
        from core.services.zahlungsklaerung import betrag_aus
        self.assertEqual(betrag_aus("1'410.50"), Decimal('1410.50'))
        self.assertEqual(betrag_aus('1410,5'), Decimal('1410.50'))
        self.assertIsNone(betrag_aus(''))
        self.assertIsNone(betrag_aus('x'))

    def test_abnahme_schluessel(self):
        from core.services.abnahme_schluessel import _betrag
        self.assertEqual(_betrag("1'450.50"), Decimal('1450.50'))
        self.assertIsNone(_betrag('100000'))      # Feldgrösse 99'999.99
        self.assertIsNone(_betrag('-1'))

    def test_mietzinsmodell(self):
        from core.services.mietzinsmodell import _dec
        self.assertEqual(_dec("1'450.50"), Decimal('1450.50'))
        self.assertEqual(_dec('1450,5'), Decimal('1450.5'))
        self.assertIsNone(_dec(''))
        self.assertIsNone(_dec('x'))

    def test_handwerker_portal(self):
        from core.views.handwerker_portal import _betrag
        self.assertEqual(_betrag("1'450.50"), Decimal('1450.50'))
        self.assertIsNone(_betrag('0'))
        self.assertIsNone(_betrag(''))

    def test_stweg(self):
        from stweg.views import _betrag, _quote
        self.assertEqual(_betrag("1'234.50"), Decimal('1234.50'))
        self.assertEqual(_quote('12,5'), Decimal('12.50'))
        self.assertIsNone(_quote('abc'))

    def test_num_der_formulare(self):
        from core.views.fw._basis import _num
        self.assertEqual(_num("CHF 12'500.00"), '12500.00')
        self.assertEqual(_num('1.450,50'), '1450.50')
        self.assertEqual(_num(None), '')


class JsGleichZuPythonTests(SimpleTestCase):
    """Das Betragsfeld im Browser (`fwZahl`) liest dieselbe Tabelle wie der Server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = shutil.which('node')

    def test_fwzahl_liest_wie_python(self):
        if not self.node:
            self.skipTest('node nicht installiert')
        skript = pathlib.Path(settings.BASE_DIR) / 'static' / 'js' / 'fw-bausteine.js'
        fälle = [roh for roh, _ in GUELTIG] + [roh for roh in UNGUELTIG if roh is not None]
        programm = (
            "const vm=require('vm'),fs=require('fs');"
            "const ctx={window:{addEventListener(){}},document:{readyState:'complete',querySelectorAll:()=>[],addEventListener(){}},"
            "console};ctx.window.window=ctx.window;vm.createContext(ctx);"
            "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);"
            "const faelle=JSON.parse(process.argv[2]);"
            "console.log(JSON.stringify(faelle.map(f=>ctx.window.fwZahl(f))));"
        )
        ergebnis = subprocess.run([self.node, '-e', programm, str(skript), json.dumps(fälle)],
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
        js = json.loads(ergebnis.stdout)
        for roh, zahl in zip(fälle, js):
            with self.subTest(roh=roh):
                python = betrag_oder_none(roh)
                self.assertEqual(zahl, float(python) if python is not None else 0)


class FormularTests(RollenBasis):
    """Seiten und Server zusammen: Die Eingabe «1'450.50» kommt an."""

    def test_der_vertragsassistent_bietet_textfelder_an_statt_number(self):
        seite = self.client_von('verwalter').get('/neu/vertraege/neu/').content.decode()
        for feld in ('s_netto', 's_nk', 's_kaution'):
            with self.subTest(feld=feld):
                tag = re.search(r'<input[^>]*id="%s"[^>]*>' % feld, seite).group(0)
                self.assertIn('type="text"', tag)
                self.assertIn('data-chf', tag)
                self.assertNotIn('type="number"', tag)

    def test_freigabelimit_nimmt_die_schweizer_schreibweise(self):
        antwort = self.client_von('inhaber').post(
            '/neu/einstellungen/zahlungsfreigabe/speichern/', {'freigabelimit': "15'000.50"})
        self.assertEqual(antwort.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.freigabelimit_kreditoren, Decimal('15000.50'))

    def test_freigabelimit_lehnt_unsinn_ab_ohne_zu_speichern(self):
        self.org.freigabelimit_kreditoren = Decimal('1000.00')
        self.org.save(update_fields=['freigabelimit_kreditoren'])
        self.client_von('inhaber').post('/neu/einstellungen/zahlungsfreigabe/speichern/', {'freigabelimit': "abc"})
        self.org.refresh_from_db()
        self.assertEqual(self.org.freigabelimit_kreditoren, Decimal('1000.00'))

    def test_der_feld_baustein_setzt_das_betragsattribut(self):
        from django import forms
        from django.template.loader import render_to_string

        class F(forms.Form):
            preis = forms.CharField()

        html = render_to_string('fw/_feld.html', {'f': F(initial={'preis': '1450.5'})['preis'], 'label': 'Preis',
                                                  'betrag': True})
        self.assertIn('data-chf', html)
        self.assertIn('inputmode="decimal"', html)
        self.assertNotIn('type="number"', html)


def _tags(text, name):
    return re.findall(r'<%s\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>' % name, text, flags=re.IGNORECASE)


class VorlagenWaechterTests(SimpleTestCase):
    """Ein Geldbetrag ist kein `type="number"`: Der Browser verwirft «1'450.50» und zeigt Komma oder Punkt je
    nach Sprache. Beträge sind Textfelder mit `data-chf` (Skript in `static/js/fw-bausteine.js`)."""

    GELD = re.compile(r'betrag|mietzins|nebenkosten|kaution|gebuehr|preis|miete|rabatt|netto|brutto|honorar_chf|'
                      r'summe|saldo|forderung|kosten|zuschlag|limit|wert\b|stand\b', re.IGNORECASE)
    #: (Vorlage, Feldname): Zählerstände und Mengen sind keine Beträge.
    AUSNAHMEN = {
        ('fw/liegenschaft_detail.html', 'aktueller_stand'): 'Zählerstand, keine Geldmenge',
        ('fw/objekt_detail.html', 'aktueller_stand'): 'Zählerstand, keine Geldmenge',
        ('fw/nk/schritt_heizung.html', 'hkvo_grundkosten_prozent'): 'ganze Prozent (HKVO), kein Betrag',
    }

    def test_kein_number_feld_fuer_einen_geldbetrag(self):
        wurzel = pathlib.Path(settings.BASE_DIR)
        zu_finden, gefunden = [], 0
        for pfad in sorted(wurzel.glob('*/templates/**/*.html')):
            rel = pfad.relative_to(wurzel)
            if 'node_modules' in rel.parts:
                continue
            text = pfad.read_text(encoding='utf-8')
            ort = pathlib.PurePosixPath(*rel.parts[2:]).as_posix()
            for tag in _tags(text, 'input'):
                if not re.search(r'type\s*=\s*["\']number["\']', tag, re.IGNORECASE):
                    continue
                gefunden += 1
                name = re.search(r'\bname\s*=\s*["\']([^"\']*)', tag)
                name = name.group(1) if name else ''
                if self.GELD.search(name) and (ort, name) not in self.AUSNAHMEN:
                    zu_finden.append(f'{ort}: {name}')
        self.assertGreater(gefunden, 15, 'auffällig wenige number-Felder gefunden: Suchmuster prüfen')
        self.assertEqual(zu_finden, [], 'Geldbeträge als type="number" (stattdessen data-chf)')

    def test_betragsfelder_tragen_data_betrag_und_eine_meldung(self):
        wurzel = pathlib.Path(settings.BASE_DIR)
        felder = 0
        for pfad in sorted(wurzel.glob('*/templates/**/*.html')):
            if pfad.name == '_feld.html':                       # der Baustein setzt das Attribut bedingt
                continue
            text = pfad.read_text(encoding='utf-8')
            for tag in _tags(text, 'input'):
                if re.search(r'\bdata-(chf|dezimal)\b', tag):
                    felder += 1
                    self.assertIn('inputmode="decimal"', tag, tag)
                    self.assertRegex(tag, r'type\s*=\s*["\']text["\']', tag)
                    self.assertIn('data-fehler=', tag, f'{tag[:80]}…: ohne Meldung für eine ungültige Eingabe')
        self.assertGreaterEqual(felder, 13)

    def test_kein_neuer_eigener_parser_im_programm(self):
        """Wer «1'450.50» einlesen will, ruft `core.utils.betrag` auf. Die Reste unten lesen keine Eingaben."""
        erlaubt = {
            'stweg/vorgaben.py': 'Prozentwerte der Versammlungsvorgaben, ganzzahlig oder Prozent',
            'core/services/formular_fill.py': 'füllt amtliche Formulare aus gespeicherten Werten',
            'core/services/lik.py': 'liest die LIK-Tabelle (CSV des BFS)',
            'core/services/nk_wizard.py': 'Import-Spalten mit eigener Erkennung',
            'core/services/mahnbrief.py': 'rechnet einen schon gespeicherten Betrag um',
            'core/utils/market_data.py': 'liest Daten des Bundes',
            'core/utils/betrag.py': 'der Parser selbst',
        }
        wurzel = pathlib.Path(settings.BASE_DIR)
        verdaechtig = []
        for app in ('core', 'stweg', 'faelle', 'portfolio', 'crm', 'finance', 'rentals', 'tickets', 'mietprozess'):
            for pfad in (wurzel / app).rglob('*.py'):
                rel = pfad.relative_to(wurzel).as_posix()
                if 'migrations' in pfad.parts or 'tests' in pfad.parts or pfad.name.startswith('test'):
                    continue
                if rel in erlaubt:
                    continue
                if re.search(r"""\.replace\(\s*['"],['"]\s*,\s*['"]\.['"]\s*\)""", pfad.read_text(encoding='utf-8')):
                    verdaechtig.append(rel)
        self.assertEqual(verdaechtig, [], 'eigener Betrags-Parser (stattdessen core.utils.betrag)')
