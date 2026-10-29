"""Jedes Formularfeld hat einen zugänglichen Namen (DESIGN-27).

Das Audit vom 28.10.2026 fand 357 von 994 Feldern ohne Namen: Die Beschriftung stand neben dem Feld,
ohne mit ihm verbunden zu sein. Ein Screenreader las «Auswahl» statt «Jahr».

DREI EBENEN

1. Die Umwandlung (`core.utils.feldnamen`) als Funktion: Muster, die sie verbindet, und Muster, die
   sie in Ruhe lässt.
2. Der Anschluss (`FeldnamenMiddleware`): Nur HTML-Seiten, sonst nichts.
3. Der Wächter: Alle Team-Seiten, die sich ohne Zustand abrufen lassen, haben nach der Auslieferung
   KEIN Feld ohne Namen. Was die Umwandlung nicht lösen kann (Feld ohne Label und ohne Platzhalter),
   gehört mit einem `aria-label` in die Vorlage — dieser Test nennt die Stelle.
"""
import pathlib
import re

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import NoReverseMatch, get_resolver, reverse

from core.middleware_feldnamen import FeldnamenMiddleware
from core.utils.feldnamen import feldnamen_ergaenzen

from ._felder import felder_ohne_namen
from ._isolation import KEINE_OBJEKT_ID, MandantenFixture


class UmwandlungTests(SimpleTestCase):
    def test_label_und_folgendes_feld_werden_verbunden(self):
        roh = '<div class="fw-feldblock"><label class="fw-label">Jahr</label>\n  <select name="jahr"><option>1</option></select></div>'
        neu = feldnamen_ergaenzen(roh)
        self.assertIn('<label class="fw-label" for="fn-1">', neu)
        self.assertIn('<select name="jahr" id="fn-1">', neu)
        self.assertEqual(felder_ohne_namen(roh)[0].__len__(), 1)
        self.assertEqual(felder_ohne_namen(neu)[0], [])

    def test_ids_sind_je_antwort_eindeutig_auch_in_schleifen(self):
        zeile = '<div><label>Betrag</label><input name="b"></div>'
        neu = feldnamen_ergaenzen(zeile * 3)
        self.assertEqual(sorted(re.findall(r'id="(fn-\d+)"', neu)), ['fn-1', 'fn-2', 'fn-3'])
        self.assertEqual(sorted(re.findall(r'for="(fn-\d+)"', neu)), ['fn-1', 'fn-2', 'fn-3'])

    def test_vorhandene_id_wird_benutzt_nicht_ersetzt(self):
        neu = feldnamen_ergaenzen('<label>Ort</label><input id="ort" name="ort">')
        self.assertIn('for="ort"', neu)
        self.assertEqual(neu.count('id="'), 1)

    def test_pflichtmarke_und_doppelpunkt_gehoeren_nicht_zum_namen(self):
        roh = '<template x-for="r in rows"><div><label class="fw-label">Betrag <span class="fw-pflicht">*</span>:</label><input name="b"></div></template>'
        neu = feldnamen_ergaenzen(roh)
        self.assertIn('aria-label="Betrag"', neu)

    def test_in_einem_template_steht_aria_label_statt_einer_id(self):
        """Alpine klont das Markup: Eine `id` stünde danach mehrfach auf der Seite."""
        roh = '<template x-for="r in rows"><label>Menge</label><input name="m"></template>'
        neu = feldnamen_ergaenzen(roh)
        self.assertIn('aria-label="Menge"', neu)
        self.assertNotIn(' id="', neu)
        self.assertNotIn(' for="', neu)

    def test_was_schon_einen_namen_hat_bleibt_unveraendert(self):
        for roh in (
            '<label for="a">A</label><input id="a">',
            '<label>A <input name="a"></label>',
            '<label>A</label><input aria-label="Eigen" name="a">',
            '<label>A</label><input title="Eigen" name="a">',
            '<input type="hidden" name="x"><label>A</label><input type="submit" value="OK">',
        ):
            with self.subTest(roh=roh):
                self.assertEqual(feldnamen_ergaenzen(roh), roh)

    def test_nicht_benachbartes_label_wird_nicht_geraten(self):
        roh = '<label>Logo</label><div><input type="file" name="logo"></div>'
        self.assertEqual(feldnamen_ergaenzen(roh), roh)

    def test_platzhalter_wird_zum_namen_wenn_kein_label_da_ist(self):
        neu = feldnamen_ergaenzen('<label>x</label><span>Zeile</span><input name="t" placeholder="Bezeichnung">')
        self.assertIn('aria-label="Bezeichnung"', neu)

    def test_data_id_und_skripte_taeuschen_nicht(self):
        roh = ('<script>var s = "<label>X</label><input name=y>";</script>'
               '<label>Name</label><input data-id="7" name="n" x-show="a > b">')
        neu = feldnamen_ergaenzen(roh)
        self.assertIn('for="fn-1"', neu)
        self.assertEqual(neu.count('fn-1'), 2)
        self.assertIn('<script>var s = "<label>X</label><input name=y>";</script>', neu)

    def test_zweimal_angewendet_aendert_nichts_mehr(self):
        einmal = feldnamen_ergaenzen('<div><label>A</label><input name="a"></div>')
        self.assertEqual(feldnamen_ergaenzen(einmal), einmal)

    def test_seite_ohne_label_und_ohne_platzhalter_kommt_unveraendert_zurueck(self):
        roh = '<form><input name="q"></form>'
        self.assertIs(feldnamen_ergaenzen(roh), roh)

    def test_seite_nur_mit_platzhalter_wird_ergaenzt(self):
        self.assertIn('aria-label="Suche"', feldnamen_ergaenzen('<form><input name="q" placeholder="Suche"></form>'))


class MiddlewareTests(SimpleTestCase):
    def _lauf(self, antwort):
        return FeldnamenMiddleware(lambda request: antwort)(RequestFactory().get('/'))

    def test_html_wird_ergaenzt_und_die_laenge_stimmt(self):
        antwort = HttpResponse('<label>A</label><input name="a">', content_type='text/html; charset=utf-8')
        antwort['Content-Length'] = str(len(antwort.content))
        ergebnis = self._lauf(antwort)
        self.assertIn(b'for="fn-1"', ergebnis.content)
        self.assertEqual(ergebnis['Content-Length'], str(len(ergebnis.content)))

    def test_andere_inhalte_laufen_unveraendert_durch(self):
        for antwort in (JsonResponse({'a': '<label>A</label><input name="a">'}),
                        HttpResponse('<label>A</label><input name="a">', content_type='text/plain'),
                        HttpResponse('<label>A</label><input name="a">', content_type='text/html', status=404)):
            with self.subTest(typ=antwort['Content-Type'], status=antwort.status_code):
                vorher = antwort.content
                self.assertEqual(self._lauf(antwort).content, vorher)

    def test_umlaute_bleiben_erhalten(self):
        antwort = HttpResponse('<label>Fälligkeit</label><input name="a">', content_type='text/html; charset=utf-8')
        self.assertIn('Fälligkeit'.encode(), self._lauf(antwort).content)

    def test_die_middleware_ist_eingebunden(self):
        from django.conf import settings
        self.assertIn('core.middleware_feldnamen.FeldnamenMiddleware', settings.MIDDLEWARE)


def _team_seiten(client, a):
    """Alle Team-Seiten (`/neu/`, `/konto/`) mit höchstens einem Parameter, als Inhaber abgerufen."""
    for name, eintrag in sorted(get_resolver().reverse_dict.items(), key=lambda x: str(x[0])):
        if not isinstance(name, str):
            continue
        for pfad, params in eintrag[0]:
            if not pfad.startswith(('neu/', 'konto/')) or len(params) > 1:
                break
            try:
                if not params:
                    url = reverse(name)
                elif params[0] in KEINE_OBJEKT_ID:
                    break
                else:
                    url = reverse(name, args=[a.objekt_fuer(params[0], name).pk])
            except (NoReverseMatch, LookupError):
                break
            antwort = client.get(url)
            if antwort.status_code == 200 and 'text/html' in antwort.get('Content-Type', ''):
                yield url, antwort.content.decode('utf-8', 'replace')
            break


class WaechterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_kein_feld_der_team_seiten_ist_ohne_namen(self):
        c = Client(raise_request_exception=False)
        c.force_login(self.a.benutzer)
        ohne, seiten, felder = [], 0, 0
        for url, text in _team_seiten(c, self.a):
            fehlend, alle = felder_ohne_namen(text)
            seiten += 1
            felder += alle
            ohne += [f'{url}:{f["zeile"]} <{f["tag"]} name="{f["name"]}" type={f["typ"]}>' for f in fehlend]
        self.assertGreater(seiten, 150, 'auffällig wenige Seiten geprüft')
        self.assertGreater(felder, 1500, 'auffällig wenige Felder geprüft')
        self.maxDiff = None
        self.assertEqual(ohne, [], 'Felder ohne zugänglichen Namen (aria-label oder Label in die Vorlage)')

    def test_ohne_die_middleware_waeren_es_hunderte(self):
        """Gegenprobe im Test selbst: Der Wächter prüft die ausgelieferte Seite, und die Umwandlung wirkt."""
        with override_settings(MIDDLEWARE=[m for m in __import__('django.conf', fromlist=['x']).settings.MIDDLEWARE
                                           if 'feldnamen' not in m]):
            c = Client(raise_request_exception=False)
            c.force_login(self.a.benutzer)
            ohne = sum(len(felder_ohne_namen(text)[0]) for _url, text in _team_seiten(c, self.a))
        self.assertGreater(ohne, 150)


#: Felder, die die Quelltext-Prüfung unten fälschlich meldet, mit Grund. Sie wächst nur mit einem Grund.
#: Schlüssel: (Vorlage ab `templates/`, Feldname); Feldname '' gilt für die ganze Vorlage.
QUELLTEXT_AUSNAHMEN = {
    # `{% if gesperrt %}<div>…</div>{% else %}<select>…{% endif %}` zwischen Label und Feld: Die
    # Prüfung entfernt die Django-Tags und sieht den Text-Zweig dazwischen. Gerendert stehen Label und
    # Feld nebeneinander (der Seitenlauf oben prüft es mit echten Seiten).
    ('fw/vertrag_bearbeiten.html', ''): 'if/else zwischen Label und Feld',
    ('fw/vertrag_detail.html', ''): 'if/else zwischen Label und Feld',
    # `{% trans a.titel %}` (Variable) kann die Prüfung nicht auflösen.
    ('fw/abnahme_texte.html', 'text_V'): 'aria-label aus einer Variable',
    # Öffentliche Formulare: werden im Auftrag «öffentliche Formulare» (Etappe 3) neu gebaut.
    ('core/public_bewerbung_form.html', ''): 'öffentliches Formular, wird neu gebaut',
    ('core/public_ticket_form.html', ''): 'öffentliches Formular, wird neu gebaut',
}


def _quelltext_ohne_django(text):
    text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', text, flags=re.S)
    text = re.sub(r'\{#.*?#\}', '', text, flags=re.S)
    text = re.sub(r'\{%\s*trans\s+["\']([^"\']*)["\'][^%]*%\}', r'\1', text)
    text = re.sub(r'\{\{[^}]*\}\}', 'V', text)
    return re.sub(r'\{%[^%]*%\}', '', text)


class QuelltextWaechterTests(SimpleTestCase):
    """Auch Zustände, die der Seitenlauf nicht herstellt (leere Tabelle, freigegebene Rechnung …)."""

    def test_kein_feld_in_den_vorlagen_ist_ohne_namen(self):
        wurzel = pathlib.Path(settings.BASE_DIR)
        ohne, vorlagen = [], 0
        for pfad in sorted(wurzel.glob('*/templates/**/*.html')):
            rel = pfad.relative_to(wurzel)
            if rel.parts[0] in ('node_modules',) or 'admin' in rel.parts:
                continue
            vorlagen += 1
            text = _quelltext_ohne_django(pfad.read_text(encoding='utf-8'))
            fehlend, _alle = felder_ohne_namen(feldnamen_ergaenzen(text))
            ort = pathlib.PurePosixPath(*rel.parts[2:]).as_posix()
            for f in fehlend:
                if (ort, f['name']) in QUELLTEXT_AUSNAHMEN or (ort, '') in QUELLTEXT_AUSNAHMEN:
                    continue
                ohne.append(f'{ort}:{f["zeile"]} <{f["tag"]} name="{f["name"]}" type={f["typ"]}>')
        self.assertGreater(vorlagen, 200, 'auffällig wenige Vorlagen geprüft')
        self.maxDiff = None
        self.assertEqual(ohne, [], 'Felder ohne zugänglichen Namen in den Vorlagen (aria-label setzen)')
