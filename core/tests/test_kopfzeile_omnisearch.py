"""Die Kopfzeile hat zwei Zeilen und eine Omnisearch (27.10.2026, Kopfzeile v2).

WAS SICH GEÄNDERT HAT

Vorher: oben die Hauptnavigation, darunter eine eigene Zeile `fw-top` mit
Bestandsfilter und breitem Suchfeld, darunter die Reiter des Bereichs (im
Inhalt), dazu die ⌘K-Palette als Fenster. Dann (erste Fassung): Bestandsfilter
rechts in Zeile 2. Jetzt (v2):

  Zeile 1  Marke, Bestandsfilter `lg` (Kontext-Chip), Bereiche, rechtsbündig
           die Omnisearch, Werkzeuge
  Zeile 2  das Menüband des Bereichs über die ganze Breite; was nicht passt,
           läuft in «Mehr» über (`static/js/fw-menueband.js`)

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
BAND_SKRIPT = WURZEL / 'static' / 'js' / 'fw-menueband.js'
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

    @classmethod
    def tearDownClass(cls):
        # `_basis_objekte()` setzt den Mandantenkontext des Prozesses; ohne diese
        # Zeile liefe er in die nächste Testklasse (test_vorlagen_isolation prüft
        # gerade das Fehlen des Kontexts und wurde davon rot).
        from core.tenancy import loesche_organisation
        loesche_organisation()
        super().tearDownClass()

    def _seite(self, pfad='/neu/liegenschaften/'):
        c = Client()
        c.force_login(self.nutzer)
        r = c.get(pfad)
        self.assertEqual(r.status_code, 200, pfad)
        return r.content.decode('utf-8')

    def test_zeile_1_hat_marke_bestand_bereiche_suche_werkzeuge_zeile_2_das_menueband(self):
        wurzel = baum(self._seite())
        kopf = eines(wurzel, id='fwKopf')
        z1 = eines(kopf, klasse='fw-kopf-z1')
        z2 = eines(kopf, klasse='fw-kopf-z2')

        # Beide Zeilen sind die zwei Kinder der Kopfzeile, in dieser Reihenfolge
        self.assertEqual([k for k in kopf.kinder if k.tag == 'div'], [z1, z2])

        # Zeile 1: Marke, Bestand, Bereiche, Omnisearch, Werkzeuge — in genau dieser Reihenfolge
        teile = {'fw-logo-kapsel', 'fw-bestand', 'fw-hauptnav', 'fw-os', 'fw-werkzeug-kapsel'}
        reihenfolge = [next(iter(k.klassen & teile)) for k in z1.kinder if k.klassen & teile]
        self.assertEqual(reihenfolge, ['fw-logo-kapsel', 'fw-bestand', 'fw-hauptnav', 'fw-os', 'fw-werkzeug-kapsel'])

        # Der Bestand steht in Zeile 1 und NICHT in Zeile 2
        bestand = eines(wurzel, klasse='fw-bestand')
        self.assertIn(bestand, z1.kinder)
        self.assertEqual(finde(z2, klasse='fw-bestand'), [], 'Der Bestandsfilter steht noch in Zeile 2')
        self.assertEqual(finde(z2, tag='select'), [], 'Eine Auswahl steht noch in Zeile 2')

        # Zeile 2: das Menüband des aktiven Bereichs, sonst nichts als sein Überlauf
        band = eines(wurzel, klasse='fw-bereichsreiter')
        self.assertIn(band, z2.kinder)
        self.assertEqual(band.attrs['id'], 'navsub-akten')
        self.assertTrue(band.hat_vorfahr(tag='header'), 'Das Menüband steht nicht in der Kopfzeile')
        self.assertFalse(band.hat_vorfahr(tag='main'), 'Das Menüband steht noch im Inhalt')
        self.assertEqual([k.attrs.get('id') for k in z2.kinder], ['navsub-akten', 'fwMehrPop'])

    def test_mehr_ist_ein_unsichtbarer_knopf_mit_aria_im_band(self):
        """Ohne Skript bleibt «Mehr» unsichtbar (das Band scrollt); mit Skript meldet es seinen Zustand."""
        wurzel = baum(self._seite())
        band = eines(wurzel, klasse='fw-bereichsreiter')
        mehr = eines(wurzel, id='fwMehr')
        pop = eines(wurzel, id='fwMehrPop')
        self.assertTrue(mehr.hat_vorfahr(klasse='fw-bereichsreiter'))
        self.assertEqual(mehr.tag, 'button')
        self.assertEqual(mehr.attrs['type'], 'button')
        self.assertIn('hidden', mehr.attrs, '«Mehr» ist ohne Skript sichtbar, aber leer')
        self.assertEqual(mehr.attrs['aria-expanded'], 'false')
        self.assertEqual(mehr.attrs['aria-controls'], 'fwMehrPop')
        self.assertIn('hidden', pop.attrs)
        self.assertEqual(pop.tag, 'nav')
        self.assertTrue(pop.attrs.get('aria-label'))
        self.assertNotIn(pop, band.kinder, 'Der Überlauf liegt im Band und würde mit ihm abgeschnitten')

    def test_gruppen_beginn_traegt_den_abschnittsnamen_fuer_den_ueberlauf(self):
        """Die Überschrift «Vorgänge» im Überlauf kommt aus `data-abschnitt` am ersten Punkt der Gruppe."""
        wurzel = baum(self._seite())
        band = eines(wurzel, klasse='fw-bereichsreiter')
        mit = [k for k in band.kinder if k.tag == 'a' and 'data-abschnitt' in k.attrs]
        self.assertEqual(len(mit), 1, 'Akten hat genau eine benannte Gruppe')
        self.assertEqual(mit[0].attrs['data-abschnitt'], 'Vorgänge')
        self.assertEqual(mit[0].attrs['href'].split('?')[0], '/neu/schaeden/')
        # Davor steht der Trenner, der im Überlauf wegfällt
        i = band.kinder.index(mit[0])
        self.assertIn('fw-bereichsreiter-trenner', band.kinder[i - 1].klassen)

    def test_profilmenue_traegt_neuer_fall_und_den_menueknopf(self):
        """Bis 1023 px hat Zeile 1 dafür keinen Platz: Beide dürfen nicht unerreichbar werden."""
        wurzel = baum(self._seite())
        profil = eines(wurzel, id='fwProfil')
        schnell = eines(profil, klasse='fw-profil-schnell')
        neu = [k for k in schnell.alle() if k.tag == 'a' and k.attrs.get('href') == '/neu/faelle/neu/']
        self.assertEqual(len(neu), 1)
        self.assertIn('fwModalOpen', neu[0].attrs['onclick'])
        menue = [k for k in schnell.alle() if k.tag == 'button' and 'fwOpenMobileNav' in k.attrs.get('onclick', '')]
        self.assertEqual(len(menue), 1)
        # Die Schublade, die der Knopf öffnet, gibt es
        self.assertEqual(len(finde(wurzel, id='fwSidebar')), 1)

    def test_werkzeuge_tragen_einstellungen_aber_keinen_menueknopf(self):
        wurzel = baum(self._seite())
        werk = eines(wurzel, klasse='fw-werkzeug-kapsel')
        ziele = [k.attrs.get('href') for k in werk.alle() if k.tag == 'a']
        self.assertTrue(any(z.startswith('/neu/einstellungen/') for z in ziele), 'Der Einstellungsknopf gehört in Zeile 1')
        self.assertIn('/neu/faelle/neu/', ziele)
        self.assertEqual([k for k in werk.alle() if 'fwOpenMobileNav' in k.attrs.get('onclick', '')], [],
                         'Der Menüknopf steht nicht mehr in Zeile 1 (er ist im Profilmenü)')

    def test_logo_ist_immer_ausgeschrieben_mit_kreuz(self):
        wurzel = baum(self._seite())
        logo = eines(wurzel, klasse='fw-logo-kapsel')
        wortmarke = [k for k in logo.kinder if k.tag == 'b']
        self.assertEqual(len(wortmarke), 1)
        self.assertEqual(len(finde(wortmarke[0], klasse='fw-logo-kreuz')), 1, 'Das Schweizerkreuz steht an der Wortmarke')
        css = SCHICHT.read_text(encoding='utf-8')
        # Keine Breite blendet die Wortmarke aus
        self.assertIsNone(re.search(r'\.fw-logo-kapsel b\{[^}]*display:\s*none', css), 'Eine Regel blendet die Wortmarke aus')

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
        self.assertEqual(finde(wurzel, klasse='fw-kopf-z2'), [], 'Eine leere Zeile 2 schöbe den Inhalt nach unten')
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

    def test_die_regeln_der_ersten_fassung_sind_weg(self):
        """Der Bestand steht nicht mehr rechts in Zeile 2, und die Bereiche sind nicht mehr mittig."""
        quelle = SCHICHT.read_text(encoding='utf-8')
        css = re.sub(r'/\*.*?\*/', ' ', quelle[quelle.index('<style>'):], flags=re.S)
        # `margin-left:auto` am Bestand schob ihn in Zeile 2 nach rechts; `margin-inline:auto` zentrierte die Bereiche
        regeln = re.findall(r'\.fw-bestand\{([^}]*)\}', css)
        self.assertTrue(regeln, 'Die Regel für den Bestand-Chip fehlt')
        for regel in regeln:
            self.assertNotIn('margin-left:auto', regel)
        regeln = re.findall(r'\.fw-hauptnav\{([^}]*)\}', css)      # mehrere: Ember-Block und Kopfzeilen-Block
        self.assertGreaterEqual(len(regeln), 2)
        for regel in regeln:
            self.assertNotIn('margin-inline:auto', regel)
        self.assertNotIn('margin-inline:0 auto', css)
        self.assertNotIn('1fr auto 1fr', css, 'Die Bereiche werden nicht mathematisch zentriert')
        # Die frühen Regeln für die kleinen Logos (Wortmarke weg unter 370 px) und «nur weit» sind entfernt
        self.assertNotIn('.fw-nur-weit', css)
        self.assertNotIn('fw-logo-kapsel b{display:none}', css)

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


class OmnisearchJeRolleTests(TestCase):
    """Was die Kopfzeile jeder Rolle zeigt: dem Team die ganze Suche, der Hauswartung
    ihre eingeschränkte, allen anderen nichts.

    Die Gruppen nennt der Such-Dienst (`palette_suche.sicht_von`), die Kopfzeile
    gibt sie nur weiter — hier steht deshalb keine zweite Rollenliste, und diese
    Tests prüfen, dass das Markup zu dem passt, was der Endpunkt liefert.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        from ._helfer import _test_organisation
        cls.org = _test_organisation()
        cls.lg, _e, cls.mieter, _v = _basis_objekte()
        cls.team = _team_user('Verwalter')
        User = get_user_model()
        cls.hauswart = User.objects.create_user(username='kz_hauswart', password='x')
        Mitgliedschaft.objects.create(benutzer=cls.hauswart, organisation=cls.org,
                                      rolle=Mitgliedschaft.ROLLE_HAUSWART)
        cls.lg.hauswarte.add(cls.hauswart)
        cls.keine = User.objects.create_user(username='kz_keine', password='x')

    @classmethod
    def tearDownClass(cls):
        from core.tenancy import loesche_organisation
        loesche_organisation()
        super().tearDownClass()

    def _seite(self, benutzer, pfad):
        c = Client()
        c.force_login(benutzer)
        r = c.get(pfad)
        self.assertEqual(r.status_code, 200, pfad)
        return r.content.decode('utf-8')

    @staticmethod
    def _daten(html):
        import json
        m = re.search(r'<script id="fw-palette-data" type="application/json">(.*?)</script>', html, re.S)
        assert m, 'fw-palette-data fehlt'
        return json.loads(m.group(1))

    def test_das_team_sieht_alle_sechs_gruppen_und_die_ausfuehrliche_suche(self):
        wurzel = baum(self._seite(self.team, '/neu/liegenschaften/'))
        os_ = eines(wurzel, id='fwOs')
        self.assertEqual(os_.attrs['data-gruppen'],
                         'personen,immobilien,vertraege,buchhaltung,tickets,dokumente')
        self.assertEqual(os_.attrs['data-suche-url'], '/neu/suche/')
        self.assertEqual(eines(wurzel, id='fwOsForm').attrs['action'], '/neu/suche/')
        self.assertEqual(eines(wurzel, id='fwOsAlle').attrs['href'], '/neu/suche/')

    def test_die_hauswartung_bekommt_die_suche_nur_fuer_schaeden(self):
        html = self._seite(self.hauswart, '/neu/schaeden/')
        wurzel = baum(html)
        os_ = eines(wurzel, id='fwOs')
        self.assertEqual(os_.attrs['data-gruppen'], 'tickets')
        # `/neu/suche/` ist ihr gesperrt: Formular ohne JavaScript und «Alle Ergebnisse»
        # führen auf die Schadenliste, die dasselbe `?q=` kennt.
        self.assertEqual(os_.attrs['data-suche-url'], '/neu/schaeden/')
        self.assertEqual(eines(wurzel, id='fwOsForm').attrs['action'], '/neu/schaeden/')
        self.assertEqual(eines(wurzel, id='fwOsAlle').attrs['href'], '/neu/schaeden/')
        self.assertEqual(eines(wurzel, id='fwOsEingabe').attrs['name'], 'q')
        self.assertIn('js/fw-omnisearch.js', html)
        # Keine Bereiche, also auch keine leere Kapsel dafür (am Telefon eine volle
        # leere Zeile unter der Kopfzeile). Gegenprobe: Das Team hat sie.
        self.assertEqual(finde(wurzel, id='fwHauptnav'), [])
        self.assertEqual(len(finde(baum(self._seite(self.team, '/neu/liegenschaften/')),
                                   id='fwHauptnav')), 1)
        c = Client()
        c.force_login(self.hauswart)
        self.assertEqual(c.get('/neu/suche/').status_code, 403)

    def test_die_seiten_der_hauswartung_sind_nur_ihre(self):
        """Das ⌘K-Verzeichnis («Seiten & Aktionen») führt nirgends in eine Absage."""
        daten = self._daten(self._seite(self.hauswart, '/neu/schaeden/'))
        self.assertTrue(daten, 'Die Hauswartung hat keine Seiten in der Suche.')
        c = Client()
        c.force_login(self.hauswart)
        for eintrag in daten:
            with self.subTest(seite=eintrag['url']):
                self.assertTrue(eintrag['url'].startswith('/neu/schaeden/'), eintrag)
                self.assertEqual(c.get(eintrag['url']).status_code, 200)
        # Gegenprobe: Das Team hat viel mehr Seiten, darunter solche, die der Hauswartung gesperrt sind.
        team = self._daten(self._seite(self.team, '/neu/liegenschaften/'))
        self.assertGreater(len(team), 30)
        self.assertIn('/neu/liegenschaften/', {e['url'] for e in team})

    def test_ohne_team_oder_hauswart_rolle_gibt_es_gar_keine_suche(self):
        """Die Kopfzeile bietet nichts an, was der Endpunkt mit 403 beantwortet."""
        from django.test import RequestFactory
        from core.navigation import fw_navigation
        from crm.models import Eigentuemer, Mieter
        from django.contrib.auth import get_user_model
        User = get_user_model()
        mieter_konto = User.objects.create_user(username='kz_mieter', password='x')
        Mieter.objects.filter(pk=self.mieter.pk).update(benutzer=mieter_konto)
        eig_konto = User.objects.create_user(username='kz_eigentuemer', password='x')
        Eigentuemer.objects.create(organisation=self.org, firma_oder_name='Eig AG', benutzer=eig_konto)
        for name, u in (('ohne Rolle', self.keine), ('Mieter-Portal', mieter_konto),
                        ('Eigentümer-Portal', eig_konto)):
            with self.subTest(konto=name):
                r = RequestFactory().get('/neu/')
                r.user = u
                # Keine Suche, keine Palette — nur das Zeichen für die reduzierte Kopfzeile ohne die
                # Team-Ziele (DESIGN-01): Logo → Login-Weiche, kein «+», keine Glocke, kein Zahnrad.
                self.assertEqual(fw_navigation(r), {'fw_kopf_reduziert': True, 'fw_kopf_start': '/nach-login/'})
        # Gegenprobe: Team und Hauswartung bekommen etwas.
        for u in (self.team, self.hauswart):
            r = RequestFactory().get('/neu/')
            r.user = u
            self.assertIn('fw_suche_gruppen', fw_navigation(r))

    def test_die_hauswartung_bekommt_keine_bereichsnavigation(self):
        """Nur die Suche — die Bereiche (Akten, Finanzen …) bleiben ihr verborgen wie bisher."""
        from django.test import RequestFactory
        from core.navigation import fw_navigation
        r = RequestFactory().get('/neu/')
        r.user = self.hauswart
        kontext = fw_navigation(r)
        self.assertEqual(set(kontext), {'fw_palette', 'fw_suche_gruppen', 'fw_suche_ziel',
                                        'fw_kopf_reduziert', 'fw_kopf_start'})
        self.assertEqual(kontext['fw_kopf_start'], '/neu/schaeden/')      # eigene Startseite, nicht /neu/ (403)
        self.assertNotIn('fw_nav_gruppen', kontext)

    def test_das_markup_nennt_genau_die_gruppen_des_endpunkts(self):
        """Was `data-gruppen` verspricht, liefert `/neu/palette/` (und nur das)."""
        import json
        for benutzer, pfad in ((self.team, '/neu/liegenschaften/'), (self.hauswart, '/neu/schaeden/')):
            with self.subTest(benutzer=benutzer.username):
                versprochen = eines(baum(self._seite(benutzer, pfad)), id='fwOs').attrs['data-gruppen']
                c = Client()
                c.force_login(benutzer)
                geliefert = json.loads(c.get('/neu/palette/', {'q': 'Muster'}).content)
                self.assertEqual(','.join(geliefert['zahlen']), versprochen)


class SkriptGruppenTests(SimpleTestCase):
    """Das Skript zeigt nur Kapseln und Gruppen, die der Server nennt (`data-gruppen`)."""

    def test_das_skript_liest_die_gruppen_vom_server(self):
        skript = SKRIPT.read_text(encoding='utf-8')
        self.assertIn("getAttribute('data-gruppen')", skript)
        # Die Kapseln folgen den erlaubten Gruppen, «Alle» bleibt
        self.assertIn("k === 'alle' || GRUPPEN.indexOf(k) >= 0", skript)
        # Eine Gruppe, die der Server nicht nennt, darf das Aufbereiten nicht stören
        self.assertIn('!proGruppe[g]', skript)


class MenuebandSkriptTests(SimpleTestCase):
    """`static/js/fw-menueband.js` ↔ Vorlage ↔ Schicht: still, wenn sie auseinanderlaufen."""

    def _js(self):
        return BAND_SKRIPT.read_text(encoding='utf-8')

    def test_die_vorlage_laedt_das_skript_als_eigene_datei(self):
        basis = BASIS.read_text(encoding='utf-8')
        self.assertIn("{% statisch 'js/fw-menueband.js' %}", basis)
        # nicht inline: die Messung steht nicht in der Vorlage
        self.assertNotIn('getBoundingClientRect().width', basis)

    def test_jede_id_des_skripts_steht_in_der_vorlage(self):
        basis = BASIS.read_text(encoding='utf-8')
        ids = set(re.findall(r"getElementById\('([\w-]+)'\)", self._js()))
        self.assertEqual(ids, {'fwMehr', 'fwMehrPop'})
        for i in ids:
            self.assertIn(f'id="{i}"', basis)

    def test_jede_klasse_des_skripts_hat_eine_regel_und_kommt_in_der_vorlage_vor(self):
        regeln = set(re.findall(r'\.((?:[\w-]|\\.)+)', SCHICHT.read_text(encoding='utf-8')))
        js = self._js()
        klassen = set(re.findall(r"'(fw-[\w-]+)'", js)) | set(re.findall(r"querySelector(?:All)?\('[^']*?\.(fw-[\w-]+)", js))
        self.assertGreaterEqual(len(klassen), 5, 'Das Ablesen der Klassen aus dem Skript greift ins Leere.')
        self.assertEqual(sorted(k for k in klassen if k not in regeln), [], 'Das Skript benutzt Klassen ohne Regel in der Schicht.')
        basis = BASIS.read_text(encoding='utf-8')
        # `fw-band-js` setzt das Skript selbst; alles andere muss die Vorlage liefern
        self.assertEqual(sorted(k for k in klassen if k not in basis and k not in ('fw-band-js', 'fw-mehr-kopf')), [])

    def test_das_skript_baut_den_ueberlauf_nicht_als_html(self):
        js = self._js()
        for verboten in ('innerHTML', 'insertAdjacentHTML', 'document.write', 'outerHTML'):
            self.assertNotIn(verboten, js)

    def test_tastatur_und_aria_des_ueberlaufs(self):
        js = self._js()
        for muss in ("'aria-expanded'", "'Escape'", "'ArrowDown'", "'ArrowUp'", "'Home'", "'End'", 'mehr.focus()'):
            self.assertIn(muss, js)

    def test_der_aktive_punkt_wird_nie_versteckt(self):
        """Die Zeile, die ihn aufnimmt, steht an genau einer Stelle: `sicht[aktiv] = true`."""
        self.assertEqual(self._js().count('sicht[aktiv] = true'), 1)

    def test_die_suche_misst_den_freien_platz_und_die_schicht_liest_ihn(self):
        self.assertIn("setProperty('--fw-os-extra'", SKRIPT.read_text(encoding='utf-8'))
        self.assertIn('var(--fw-os-extra', SCHICHT.read_text(encoding='utf-8'))
