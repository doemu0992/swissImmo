"""Wächter gegen eingeschleustes Markup: Werte in `innerHTML`-Strings müssen maskiert sein.

ANLASS (Audit 15.11.2026): Der Vertragsassistent baute Auswahllisten und Zusammenfassung per Template-String in
`innerHTML`, mit Namen und Adressen ohne Maskierung. Über das öffentliche Bewerbungsformular konnte ein anonymer Besucher
dort Markup einschleusen, das in der Sitzung der Verwaltung lief. Djangos Autoescape schützt nur Vorlagen, nicht
Zeichenketten, die ein Skript im Browser zusammensetzt.

REGEL: `textContent`, `new Option(text, wert)` oder `createElement` verwenden. Wo ein HTML-String nötig ist, läuft jeder
Wert durch `fwEsc` (`static/js/fw-sicher.js`).
"""
import pathlib
import re

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
ZUWEISUNG = re.compile(r'\.innerHTML\s*\+?=(?!=)')

#: Zahl der `innerHTML`-Zuweisungen je Datei, Stand 15.11.2026 — jede einzeln durchgesehen. Die Zahl darf sinken. Steigt
#: sie oder kommt eine Datei dazu, schlägt der Test an: Die neue Stelle prüfen (stammt ein Wert aus einer Eingabe? ist er
#: maskiert?) und erst dann die Zahl hier nachführen.
STAND = {
    'core/templates/core/mieter_kuendigung.html': 1,
    'core/templates/fw/abnahme_vorort_neu.html': 3,
    'core/templates/fw/dashboard.html': 2,
    'core/templates/fw/debitoren.html': 1,
    'core/templates/fw/kommunikation.html': 3,
    'core/templates/fw/kreditoren.html': 1,
    'core/templates/fw/kuendigung_form.html': 5,
    'core/templates/fw/mietzins.html': 1,
    'core/templates/fw/mietzins_anpassung.html': 3,
    'core/templates/fw/schaeden_board.html': 1,
    'core/templates/fw/vertrag_neu.html': 8,
    'core/templates/fw/verzug_257d.html': 1,
    'core/templates/fw/vorlage_form.html': 1,
    'core/templates/fw/weiterverrechnung.html': 1,
    'static/js/fw-aktionen.js': 1,
    'static/js/fw-bausteine.js': 6,
    'static/js/fw-zahlungen.js': 2,
}


def _zaehlung():
    dateien = sorted(list(WURZEL.glob('*/templates/**/*.html')) + list((WURZEL / 'static' / 'js').glob('*.js')))
    gefunden = {}
    for pfad in dateien:
        rel = pfad.relative_to(WURZEL).as_posix()
        if '/emails/' in rel or pfad.name == 'fw-sicher.js':
            continue
        n = len(ZUWEISUNG.findall(pfad.read_text(encoding='utf-8')))
        if n:
            gefunden[rel] = n
    return gefunden


class InnerHtmlRatscheTests(SimpleTestCase):

    def test_keine_neue_innerhtml_stelle_ohne_durchsicht(self):
        mehr = {d: (n, STAND.get(d, 0)) for d, n in _zaehlung().items() if n > STAND.get(d, 0)}
        self.assertEqual(mehr, {}, 'Neue innerHTML-Zuweisung (Datei: gefunden, erlaubt). textContent oder fwEsc verwenden, '
                                    'die Stelle prüfen und dann STAND nachführen.')

    def test_der_stand_ist_nicht_veraltet(self):
        """Sinkt die Zahl, soll auch die Erlaubnis sinken — sonst wäre Platz für eine neue, ungeprüfte Stelle."""
        ist = _zaehlung()
        weniger = {d: (ist.get(d, 0), n) for d, n in STAND.items() if ist.get(d, 0) < n}
        self.assertEqual(weniger, {}, 'STAND nachführen (Datei: gefunden, eingetragen).')

    def test_der_waechter_erkennt_die_formen(self):
        for text in ("el.innerHTML = x", "a.innerHTML+='<b>'", "ziel.innerHTML  =  `…`"):
            self.assertTrue(ZUWEISUNG.search(text), text)
        for text in ("if (el.innerHTML == '')", "var v = el.innerHTML;", "el.textContent = x"):
            self.assertFalse(ZUWEISUNG.search(text), text)


class VertragsassistentTests(SimpleTestCase):
    """Die Stellen, über die der Angriff lief: Kein Wert aus Stammdaten oder Formular geht unmaskiert in einen HTML-String."""

    def setUp(self):
        self.quelle = (WURZEL / 'core' / 'templates' / 'fw' / 'vertrag_neu.html').read_text(encoding='utf-8')

    def test_stammdaten_sind_in_html_strings_maskiert(self):
        roh = re.findall(r'\$\{\s*(?:l|m|m2|o|vm)\.(?:strasse|ort|plz|name|bezeichnung|typ|etage|id)\s*\}', self.quelle)
        self.assertEqual(roh, [], 'Unmaskierter Wert in einem Template-String: E(…) verwenden.')

    def test_formularwerte_sind_in_html_strings_maskiert(self):
        # Als AUSGABE (`${val('x')}` oder `${val('x')||'—'}`), nicht als Bedingung (`${val('x')?…:…}`).
        self.assertNotRegex(self.quelle, r'\$\{\s*(?:val\([^)]*\)|zweiterName\(\))\s*(?:\}|\|\|)')

    def test_die_maskierung_ist_vor_dem_ersten_gebrauch_definiert(self):
        self.assertLess(self.quelle.index('const E = window.fwEsc;'), self.quelle.index('${E('))

    def test_die_tote_vorschau_ist_weg(self):
        self.assertNotIn("getElementById('pv').innerHTML", self.quelle)


class MaskierfunktionTests(SimpleTestCase):

    def test_fw_sicher_maskiert_die_fuenf_zeichen_und_ist_ueberall_geladen(self):
        skript = (WURZEL / 'static' / 'js' / 'fw-sicher.js').read_text(encoding='utf-8')
        for zeichen in ("'&': '&amp;'", "'<': '&lt;'", "'>': '&gt;'", "'\"': '&quot;'", '"\'": \'&#39;\''):
            self.assertIn(zeichen, skript)
        schicht = (WURZEL / 'core' / 'templates' / 'fw' / '_schicht_link.html').read_text(encoding='utf-8')
        self.assertLess(schicht.index('js/fw-sicher.js'), schicht.index('js/fw-bausteine.js'))


class BewerbungsformularTests(TestCase):
    """Zweite Schranke an der Quelle: Das öffentliche Formular nimmt kein Markup in Freitextfeldern an."""

    def setUp(self):
        from decimal import Decimal

        from django.core.cache import cache

        from core.tests._helfer import _test_organisation
        cache.clear()                    # die Bremse «5 Bewerbungen je Stunde» zählt sonst über Tests hinweg
        self.addCleanup(cache.clear)
        from portfolio.models import Einheit, Liegenschaft
        lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Inseratweg 3', plz='4500',
                                         ort='Solothurn')
        self.einheit = Einheit.objects.create(liegenschaft=lg, bezeichnung='2.5 Zi', typ='whg',
                                              nettomiete_aktuell=Decimal('1200'), zur_ausschreibung=True)

    def _post(self, **mehr):
        from core.tests.test_bewerbung_edoeb import _formular_daten
        return Client().post('/api/mietprozess/public/bewerben', _formular_daten(self.einheit, **mehr))

    def _anzahl(self):
        from mietprozess.models import Mietbewerbung
        return Mietbewerbung.alle_organisationen.filter(einheit=self.einheit).count()

    def test_markup_im_namen_wird_abgewiesen(self):
        antwort = self._post(vorname='<img src=x onerror=alert(1)>')
        self.assertEqual(antwort.status_code, 400)
        self.assertIn('Vorname', antwort.json()['error'])
        self.assertEqual(self._anzahl(), 0)

    def test_markup_in_der_adresse_und_ueberlaenge_werden_abgewiesen(self):
        self.assertEqual(self._post(adresse='Weg 1</option><script>').status_code, 400)
        self.assertEqual(self._post(nachname='M' * 81).status_code, 400)
        self.assertEqual(self._anzahl(), 0)

    def test_gewoehnliche_namen_gehen_durch(self):
        """Gegenprobe: Apostroph, Bindestrich, Umlaut und «&» sind in Namen und Adressen üblich."""
        antwort = self._post(vorname="Anne-Sophie", nachname="D'Agostino Müller", adresse='Rue de l’Église 3 & 5')
        self.assertEqual(antwort.status_code, 201, antwort.content)
        self.assertEqual(self._anzahl(), 1)
