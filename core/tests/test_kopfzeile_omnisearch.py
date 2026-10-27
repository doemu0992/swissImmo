"""Die Kopfzeile hat zwei Zeilen und eine Omnisearch (27.10.2026).

WAS SICH GEÄNDERT HAT

Vorher: oben die Hauptnavigation, darunter eine eigene Zeile `fw-top` mit
Bestandsfilter und breitem Suchfeld, darunter die Reiter des Bereichs (im
Inhalt), dazu die ⌘K-Palette als Fenster. Jetzt:

  Zeile 1  Marke, Bereiche, rechtsbündig die Omnisearch, Werkzeuge
  Zeile 2  das Menüband des Bereichs, rechts der Bestandsfilter `lg` als Chip

WAS DIESE DATEI HÄLT

Die STRUKTUR (wo was steht) und die Bindungen zwischen den Teilen, die kein
Browsertest einzeln sieht: Jede Klasse, die das Skript erzeugt, hat eine Regel
in der Schicht; jedes Zeichen, das es zeichnet, steht in `docs/ZEICHEN.md`;
jeder Text, den es holt, steht im `<template>`. Wie es aussieht und sich
anfühlt (Breiten, Tastatur, Telefon), misst `e2e/tests/omnisearch.spec.ts` —
ein Test, der die Zeichenkette liest, merkt, wenn eine Regel verschwindet,
aber nicht, ob sie wirkt.

GEGENPROBEN stehen im Schlussbericht der Etappe und im jeweiligen Test.
"""
import pathlib
import re
from html.parser import HTMLParser

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from ._helfer import _basis_objekte, _team_user

WURZEL = pathlib.Path(settings.BASE_DIR)
SCHICHT = WURZEL / 'core' / 'templates' / 'fw' / '_schicht.html'
SKRIPT = WURZEL / 'static' / 'js' / 'fw-omnisearch.js'
PARTIAL = WURZEL / 'core' / 'templates' / 'fw' / '_omnisearch.html'
BASIS = WURZEL / 'core' / 'templates' / 'fw' / 'base.html'

_LEER = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Knoten:
    def __init__(self, tag, attrs, eltern):
        self.tag, self.attrs, self.eltern, self.kinder = tag, dict(attrs), eltern, []
        self.klassen = set((self.attrs.get('class') or '').split())

    def alle(self):
        for k in self.kinder:
            yield k
            yield from k.alle()

    def vorfahren(self):
        k = self.eltern
        while k is not None:
            yield k
            k = k.eltern

    def hat_vorfahr(self, klasse=None, tag=None):
        return any((klasse is None or klasse in v.klassen) and (tag is None or v.tag == tag) for v in self.vorfahren())


class _Baum(HTMLParser):
    """Ein kleiner DOM-Baum aus dem gerenderten HTML (nur die Struktur zählt)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.wurzel = Knoten('#wurzel', [], None)
        self.offen = self.wurzel

    def handle_starttag(self, tag, attrs):
        k = Knoten(tag, attrs, self.offen)
        self.offen.kinder.append(k)
        if tag not in _LEER:
            self.offen = k

    def handle_startendtag(self, tag, attrs):
        self.offen.kinder.append(Knoten(tag, attrs, self.offen))

    def handle_endtag(self, tag):
        k = self.offen
        while k is not None and k.tag != tag:
            k = k.eltern
        if k is not None and k.eltern is not None:
            self.offen = k.eltern


def baum(html):
    b = _Baum()
    b.feed(html)
    return b.wurzel


def finde(wurzel, klasse=None, id=None, tag=None):
    return [k for k in wurzel.alle()
            if (klasse is None or klasse in k.klassen) and (id is None or k.attrs.get('id') == id)
            and (tag is None or k.tag == tag)]


def eines(wurzel, **kw):
    gefunden = finde(wurzel, **kw)
    assert len(gefunden) == 1, f'{kw}: {len(gefunden)} Treffer statt einem'
    return gefunden[0]


class KopfzeileStrukturTests(TestCase):
    """Wo was in der Kopfzeile steht — am gerenderten HTML einer Seite mit Menüband."""

    @classmethod
    def setUpTestData(cls):
        cls.nutzer = _team_user()
        cls.lg = _basis_objekte()[0]

    def _seite(self, pfad='/neu/liegenschaften/'):
        c = Client()
        c.force_login(self.nutzer)
        r = c.get(pfad)
        self.assertEqual(r.status_code, 200, pfad)
        return r.content.decode('utf-8')

    def test_zeile_1_hat_die_suche_zeile_2_das_menueband_darunter(self):
        wurzel = baum(self._seite())
        kopf = eines(wurzel, id='fwKopf')
        z1 = eines(kopf, klasse='fw-kopf-z1')
        z2 = eines(kopf, klasse='fw-kopf-z2')

        # Beide Zeilen sind die zwei Kinder der Kopfzeile, in dieser Reihenfolge
        self.assertEqual([k for k in kopf.kinder if k.tag == 'div'], [z1, z2])

        # Zeile 1: Marke, Bereiche, Omnisearch, Werkzeuge — in genau dieser Reihenfolge
        reihenfolge = [k.klassen & {'fw-logo-kapsel', 'fw-hauptnav', 'fw-os', 'fw-werkzeug-kapsel'} for k in z1.kinder]
        reihenfolge = [next(iter(r)) for r in reihenfolge if r]
        self.assertEqual(reihenfolge, ['fw-logo-kapsel', 'fw-hauptnav', 'fw-os', 'fw-werkzeug-kapsel'])

        # Zeile 2: das Menüband des aktiven Bereichs, rechts davon der Bestandsfilter
        band = eines(wurzel, klasse='fw-bereichsreiter')
        self.assertIn(band, z2.kinder)
        self.assertEqual(band.attrs['id'], 'navsub-akten')
        bestand = eines(wurzel, klasse='fw-bestand')
        self.assertEqual([k for k in z2.kinder if k in (band, bestand)], [band, bestand])
        self.assertTrue(band.hat_vorfahr(tag='header'), 'Das Menüband steht nicht in der Kopfzeile')
        self.assertFalse(band.hat_vorfahr(tag='main'), 'Das Menüband steht noch im Inhalt')

    def test_die_alte_zeile_und_das_fenster_sind_weg(self):
        html = self._seite()
        for alt in ('class="fw-top"', 'id="fwTop"', 'class="fw-suche"', 'class="fw-bereich"',
                    'id="fwPalette"', 'fwPaletteOpen', 'fw-palette-box', 'fw-pal-item'):
            with self.subTest(alt=alt):
                self.assertNotIn(alt, html)
        # Nur ein Suchfeld in der ganzen Seite (nicht zwei nebeneinander)
        self.assertEqual(len(finde(baum(html), tag='input', id='fwOsEingabe')), 1)
        self.assertEqual(html.count('name="q"'), 1)

    def test_ohne_javascript_ist_die_suche_ein_formular(self):
        wurzel = baum(self._seite())
        form = eines(wurzel, id='fwOsForm')
        self.assertEqual(form.attrs['action'], '/neu/suche/')
        self.assertEqual(form.attrs['method'], 'get')
        eingabe = eines(wurzel, id='fwOsEingabe')
        self.assertEqual(eingabe.attrs['name'], 'q')
        self.assertTrue(eingabe.hat_vorfahr(tag='form'))

    def test_aria_der_kombination_aus_feld_und_liste(self):
        wurzel = baum(self._seite())
        eingabe = eines(wurzel, id='fwOsEingabe')
        self.assertEqual(eingabe.attrs['role'], 'combobox')
        self.assertEqual(eingabe.attrs['aria-controls'], 'fwOsListe')
        self.assertIn('aria-expanded', eingabe.attrs)
        liste = eines(wurzel, id='fwOsListe')
        self.assertEqual(liste.attrs['role'], 'listbox')

    def test_bestandsfilter_ist_derselbe_mechanismus_lg(self):
        wurzel = baum(self._seite())
        bestand = eines(wurzel, klasse='fw-bestand')
        auswahl = [k for k in bestand.alle() if k.tag == 'select']
        self.assertEqual(len(auswahl), 1)
        self.assertEqual(auswahl[0].attrs['name'], 'lg')
        self.assertIn('submit', auswahl[0].attrs['onchange'])
        werte = [k.attrs.get('value') for k in auswahl[0].alle() if k.tag == 'option']
        self.assertEqual(werte[0], '', 'Die erste Wahl ist «Ganzer Bestand»')
        self.assertIn(str(self.lg.id), werte)
        self.assertNotIn('aktiv', bestand.klassen)

    def test_aktiver_bestandsfilter_ist_markiert(self):
        html = self._seite(f'/neu/liegenschaften/?lg={self.lg.id}')
        bestand = eines(baum(html), klasse='fw-bestand')
        self.assertIn('aktiv', bestand.klassen)
        gewaehlt = [k for k in bestand.alle() if k.tag == 'option' and 'selected' in k.attrs]
        self.assertEqual([k.attrs['value'] for k in gewaehlt], [str(self.lg.id)])

    def test_startseite_hat_den_filter_aber_kein_menueband(self):
        """«Heute» zeigt kein Band (die Seite hat eigene Reiter) — der Filter bleibt erreichbar."""
        wurzel = baum(self._seite('/neu/'))
        self.assertEqual(finde(wurzel, klasse='fw-bereichsreiter'), [])
        self.assertEqual(len(finde(wurzel, klasse='fw-bestand')), 1)
        self.assertEqual(len(finde(wurzel, id='fwOs')), 1)

    def test_die_daten_der_palette_bleiben_als_gruppe_der_suche(self):
        html = self._seite()
        self.assertIn('id="fw-palette-data"', html)
        self.assertIn('js/fw-omnisearch.js', html)
        self.assertIn('data-palette-url="/neu/palette/"', html)

    def test_ohne_team_rolle_gibt_es_keine_suche(self):
        """Die Rollenprüfung bleibt beim Endpunkt; die Oberfläche bietet sie ohne Rolle gar nicht an."""
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user(username='ohne_rolle', password='x')
        c = Client()
        c.force_login(u)
        r = c.get('/neu/palette/', {'q': 'Muster'})
        self.assertEqual(r.status_code, 403)


class SchichtOhneAltesTests(SimpleTestCase):
    """Was entfernt wurde, bleibt entfernt — und der Portal-Kopf trägt sich selbst."""

    def test_die_schicht_kennt_fw_top_und_die_palette_nicht_mehr(self):
        quelle = SCHICHT.read_text(encoding='utf-8')
        css = quelle[quelle.index('<style>'):]
        css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
        for alt in (r'\.fw-top\b(?!-)', r'\.fw-bereich\b(?!s)', r'\.fw-suche\b(?!f)', r'\.fw-palette', r'\.fw-pal-'):
            with self.subTest(selektor=alt):
                self.assertIsNone(re.search(alt, css), f'Eine Regel für {alt} steht noch in der Schicht.')

    def test_das_portal_braucht_fw_top_nicht(self):
        portal = (WURZEL / 'core' / 'templates' / 'core' / 'portal_base.html').read_text(encoding='utf-8')
        self.assertIn('class="fw-portal-top"', portal)
        self.assertNotIn('fw-top ', portal)
        css = SCHICHT.read_text(encoding='utf-8')
        self.assertRegex(css, r'\.fw-portal-top\{position:relative;')

    def test_der_modulblock_steht_am_ende_der_schicht(self):
        quelle = SCHICHT.read_text(encoding='utf-8')
        marke = '/* ===== MODUL Kopfzeile und Omnisearch (27.10.2026) ===== */'
        self.assertEqual(quelle.count(marke), 1)
        ende = '/* ===== Ende MODUL Kopfzeile und Omnisearch ===== */'
        self.assertGreater(quelle.index(ende), quelle.index(marke))
        # Hinter dem Block steht nur noch das Ende des Stilblocks
        self.assertEqual(quelle[quelle.index(ende) + len(ende):].strip(), '</style>')


class SkriptBindungenTests(SimpleTestCase):
    """Skript, Vorlage und Schicht müssen zusammenpassen — still, wenn sie es nicht tun."""

    def _skript(self):
        return SKRIPT.read_text(encoding='utf-8')

    def test_jede_klasse_des_skripts_hat_eine_regel(self):
        regeln = set(re.findall(r'\.((?:[\w-]|\\.)+)', SCHICHT.read_text(encoding='utf-8')))
        klassen = set()
        for m in re.finditer(r"'class':\s*'([^']*)'", self._skript()):
            klassen.update(w for w in m.group(1).split() if w.startswith('fw-') and not w.endswith('-'))
        # Töne werden zusammengesetzt (`'fw-' + ton`): die vier erlaubten einzeln prüfen
        toene = re.search(r'TOENE = \{([^}]*)\}', self._skript()).group(1)
        klassen.update('fw-' + t for t in re.findall(r'(\w+):\s*1', toene))
        self.assertGreater(len(klassen), 15, 'Das Ablesen der Klassen aus dem Skript greift ins Leere.')
        fehlt = sorted(k for k in klassen if k not in regeln)
        self.assertEqual(fehlt, [], f'Das Skript erzeugt Klassen ohne Regel in der Schicht: {fehlt}')

    def test_der_ablesetest_findet_eine_fehlende_regel(self):
        """Gegenprobe zum Test darüber: ohne diese Zeile könnte er immer grün sein."""
        regeln = set(re.findall(r'\.((?:[\w-]|\\.)+)', SCHICHT.read_text(encoding='utf-8')))
        self.assertNotIn('fw-os-gibtesnicht', regeln)
        self.assertIn('fw-os-chip', regeln)

    def test_jedes_gezeichnete_zeichen_steht_in_der_zeichentabelle(self):
        tabelle = (WURZEL / 'docs' / 'ZEICHEN.md').read_text(encoding='utf-8')
        tabelle = tabelle[:tabelle.index('## Noch ohne Bedeutung')]
        erlaubt = set(re.findall(r'^\| `([a-z]+)` \|', tabelle, re.M))
        block = re.search(r'var ZEICHEN = \{(.*?)\};', self._skript(), re.S).group(1)
        benutzt = set(re.findall(r"\w+:\s*'([a-z]+)'", block))
        self.assertGreaterEqual(len(benutzt), 7)
        self.assertEqual(sorted(benutzt - erlaubt), [], 'Das Skript zeichnet Zeichen, die ZEICHEN.md nicht kennt.')
        sprite = (WURZEL / 'core' / 'templates' / 'fw' / '_zeichen.html').read_text(encoding='utf-8')
        gezeichnet = set(re.findall(r'id="z-([a-z]+)"', sprite))
        self.assertEqual(sorted(benutzt - gezeichnet), [], 'Das Sprite kennt Zeichen des Skripts nicht.')

    def test_jeder_text_des_skripts_steht_im_template(self):
        """`t('schluessel')` ohne Eintrag zeigte den Schlüssel selbst auf der Seite."""
        skript = self._skript()
        template = PARTIAL.read_text(encoding='utf-8')
        im_template = set(re.findall(r'data-k="([a-z_0-9]+)"', template))
        benutzt = set(re.findall(r"\bt\('([a-z_0-9]+)'[,)]", skript))
        # zusammengesetzte Schlüssel: Kapseln (`t(k)`), Gruppenköpfe (`t('g_' + g)`)
        gruppen = ['personen', 'immobilien', 'vertraege', 'buchhaltung', 'tickets', 'dokumente']
        benutzt |= {'alle'} | set(gruppen) | {'g_' + g for g in gruppen} | {'g_seiten'}
        self.assertGreater(len(benutzt), 15)
        self.assertEqual(sorted(benutzt - im_template), [], 'Texte fehlen im <template id="fwOsTexte">.')
        self.assertEqual(sorted(im_template - benutzt), [], 'Texte im <template> werden nicht benutzt.')
        # Jeder davon läuft durch `trans`
        for s in re.findall(r'<span data-k="[a-z_0-9]+">(.*?)</span>', template):
            self.assertRegex(s, r'^\{% trans ".*" %\}$')

    def test_das_skript_baut_treffer_nicht_als_html(self):
        """Treffertexte kommen aus Daten; als HTML-Zeichenkette eingesetzt wären sie eine Lücke."""
        skript = self._skript()
        self.assertNotIn('innerHTML', skript)
        self.assertNotIn('insertAdjacentHTML', skript)
        self.assertNotIn('document.write', skript)

    def test_verweise_der_treffer_bleiben_in_der_anwendung(self):
        skript = self._skript()
        self.assertGreaterEqual(skript.count("charAt(0) !== '/'"), 2, 'Beide Quellen (Endpunkt, Seiten) prüfen die Adresse.')
