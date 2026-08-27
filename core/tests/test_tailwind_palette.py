"""Die Tailwind-Rampen müssen an den Konzept-Tokens hängen, nicht daneben.

WARUM ES DIESEN TEST GIBT

Am 20.08.2026 trugen **176 Vorlagen 7490 fest verdrahtete Farbklassen** —
4959 `slate`, 1250 `indigo`, dazu rose, emerald, amber. Die Aktenseiten waren
auf die Komponentenschicht umgestellt, alles andere nicht: Seitenleiste,
Topbar, Listen, Formulare, Berichte blieben indigoblau. Die Anwendung war
zweifarbig.

`KONZEPT-UI.md` 16.4 nennt zwei Wege: Klassen einzeln umstellen oder Tailwind
eine Petrol-Palette unterschieben. Gewählt ist der zweite — eine Änderung in
der Bau-Konfiguration statt 7490 verteilter.

WAS DIESER TEST HÄLT

Dass die Rampen **dieselben Werte** führen wie die Tokens, wo sie sich
treffen. Ohne das wären es wieder zwei Paletten, nur beide petrolfarben: Der
Knopf `bg-indigo-600` und die Komponente `var(--ds-brand)` stünden
nebeneinander in leicht verschiedenem Ton, und niemand fände den Grund.

Und dass die Helligkeitstreppe erhalten bleibt: Jede Stufe muss heller sein
als die nächsthöhere. Kippt die Ordnung, kippt jede bestehende Gestaltung —
`bg-slate-100` als Chip-Fläche muss hell bleiben, `text-slate-700` dunkel.
"""
import pathlib
import re

from django.test import TestCase

from core.tests.test_palette import kontrast, MINDESTKONTRAST, _block

BASE = pathlib.Path('core/templates/fw/base.html')
#: Seit E0.2 steht die Rampe in der Bau-Konfiguration statt in einem
#: <script>-Block, den das Tailwind-CDN zur Laufzeit im Browser las. Derselbe
#: Inhalt, nur zur Bauzeit — `npm run css` erzeugt daraus GEBAUT.
PALETTE = pathlib.Path('tailwind.palette.js')
#: Die gebaute Datei. Sie ist das, was der Browser wirklich bekommt; die
#: Konfiguration allein sagt nichts darueber, ob der Bau auch gelaufen ist.
GEBAUT = pathlib.Path('static/css/tailwind.css')
WURZEL = pathlib.Path('.')
#: Die Klasse, an der abgelesen wird, ob die Rampe im Bau angekommen ist.
#:
#: Sie muss zwei Bedingungen erfuellen: aus der Indigo-Rampe stammen (nur
#: dann unterscheiden sich die zwei Bauten) UND von echtem Code benutzt
#: werden (sonst baut Tailwind keine Regel dafuer). `text-indigo-600` steht
#: in `crm/admin.py` und `rentals/admin.py`.
#:
#: Vorher stand hier `bg-indigo-600` — die gab es im ganzen Bestand nur als
#: BEISPIEL in einem Waechter. Siehe
#: `test_die_sonde_wird_von_echtem_code_am_leben_gehalten`.
SONDE = 'text-indigo-600'
SONDE_HINWEIS = (f'Die Sonde ist `{SONDE}`; sie muss von echtem Code '
                 f'benutzt werden, sonst baut Tailwind sie nicht.')
#: Jede Huelle der Anwendung. Sie muessen den Stilbaustein mit der
#: Petrol-Palette einbinden. Die aussenstehenden Seiten (Portal, Bewerbung,
#: oeffentliche Formulare, Fehlerseiten) fehlen hier absichtlich — siehe
#: `HuellenTests.test_die_aussenseiten_sind_gezaehlt_statt_vergessen`.
HUELLEN = ('core/templates/fw/base.html',
           'core/templates/fw/base_embed.html',
           'core/templates/fw/_modal_done.html')
#: Der Baustein, den eine Huelle der Anwendung tragen muss.
BAUSTEIN = "{% include 'fw/_assets.html' %}"

#: Wo eine Tailwind-Stufe einen Konzept-Token trifft, muss derselbe Wert
#: stehen. Das ist die eigentliche Bindung — alles andere ist Zwischenton.
BINDUNGEN = (
    ('indigo', 600, '--ds-brand'),
    ('indigo', 700, '--ds-brand-600'),
    ('indigo', 100, '--ds-brand-soft'),
    ('slate', 200, '--ds-line'),
    ('slate', 500, '--ds-faint'),
    ('slate', 600, '--ds-muted'),
    ('slate', 900, '--ds-ink'),
    ('emerald', 600, '--ds-good'),
    ('emerald', 50, '--ds-good-soft'),
    ('amber', 600, '--ds-warn'),
    ('amber', 50, '--ds-warn-soft'),
    ('rose', 600, '--ds-crit'),
    ('rose', 50, '--ds-crit-soft'),
    ('sky', 600, '--ds-info'),
    ('sky', 50, '--ds-info-soft'),
)

#: Familien, die im Bestand gleichbedeutend benutzt werden und deshalb
#: dieselbe Rampe führen müssen — sonst stehen zwei Grautöne nebeneinander.
GLEICHLAUF = (('slate', 'gray'), ('emerald', 'green'),
              ('amber', 'orange'), ('rose', 'red'))


def ohne_kommentare(text):
    """CSS- und HTML-Kommentare entfernen.

    Notwendig, nicht kosmetisch: Der Erklärtext zur Palette nennt die alten
    Farbwerte, um zu sagen, was sie ersetzt. Eine Suche im Rohtext findet
    das Zitat und hält es für die Sache.
    """
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def rampen():
    """Die Farbrampen aus `tailwind.palette.js`.

    Gelesen wird der Text, nicht ausgeführtes JavaScript — der Test soll
    keine JS-Laufzeit brauchen. Eine erste Fassung übersetzte den Block nach
    JSON und war dabei zu clever: Sie zerbrach an den Kommentaren zwischen
    den Rampen. Jetzt werden die Paare `stufe: '#rrggbb'` direkt gelesen.

    Was das nicht kann: einen JavaScript-Syntaxfehler melden. Dagegen steht
    `test_es_gibt_ueberhaupt_rampen` — verschwindet eine Rampe aus dem
    Ergebnis, schlägt er an, statt dass alles still grün bleibt. Und seit
    E0.2 steht darueber `test_der_bau_traegt_die_rampe_auch_wirklich`: Eine
    fehlerhafte Konfiguration liefe im Bau auf die Nase, statt still eine
    alte Datei stehen zu lassen.
    """
    quelle = PALETTE.read_text(encoding='utf-8')
    block = ohne_kommentare(quelle[quelle.index('module.exports'):])
    farben = {}
    for m in re.finditer(r'(\w+):\s*\{([^{}]*)\}', block, re.S):
        paare = re.findall(r'(\d{2,3}):\s*\'(#[0-9a-f]{6})\'', m.group(2))
        if paare:
            farben[m.group(1)] = {int(s): w for s, w in paare}
    return farben


class TailwindPaletteTests(TestCase):
    def setUp(self):
        self.rampen = rampen()
        self.tokens = {k: v.strip() for k, v in _block('hell').items()}

    def test_es_gibt_ueberhaupt_rampen(self):
        """Sonst prüfen die Tests darunter nichts.

        Genau diese Blindheit hatte `AktenkopfTests` und der
        Kennzahlen-Test von 4b.5: eine Bedingung, die immer erfüllt ist,
        weil sie ins Leere greift.
        """
        self.assertIn('indigo', self.rampen)
        self.assertIn('slate', self.rampen)
        self.assertGreaterEqual(len(self.rampen), 10,
                                f'Nur {len(self.rampen)} Rampen gelesen — '
                                f'Aufbau von tailwind.palette.js geändert?')
        for name, stufen in self.rampen.items():
            with self.subTest(rampe=name):
                self.assertEqual(sorted(stufen), [50, 100, 200, 300, 400,
                                                  500, 600, 700, 800, 900])

    def test_die_rampen_haengen_an_den_tokens(self):
        for familie, stufe, token in BINDUNGEN:
            with self.subTest(farbe=f'{familie}-{stufe}', token=token):
                erwartet = self.tokens[token].lower()
                gesetzt = self.rampen[familie][stufe].lower()
                self.assertEqual(
                    gesetzt, erwartet,
                    f'{familie}-{stufe} ist {gesetzt}, {token} ist {erwartet}. '
                    f'Zwei Paletten nebeneinander — ein Knopf in Tailwind und '
                    f'eine Komponente daneben stünden in verschiedenem Ton.')

    def test_gleichbedeutende_familien_fuehren_dieselbe_rampe(self):
        for a, b in GLEICHLAUF:
            with self.subTest(paar=f'{a}/{b}'):
                self.assertEqual(self.rampen[a], self.rampen[b],
                                 f'`{a}` und `{b}` werden im Bestand gleich '
                                 f'benutzt, führen aber verschiedene Töne.')

    def test_die_helligkeitstreppe_bleibt(self):
        """50 ist die hellste Stufe, 900 die dunkelste — ohne Ausnahme.

        Kippt die Ordnung, kippt jede bestehende Gestaltung: `bg-slate-100`
        als Chip-Fläche wäre plötzlich dunkel, `text-slate-700` hell.
        """
        def helligkeit(hex_wert):
            r, g, b = (int(hex_wert[i:i + 2], 16) / 255 for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for familie, stufen in sorted(self.rampen.items()):
            werte = [helligkeit(stufen[s]) for s in sorted(stufen)]
            with self.subTest(rampe=familie):
                self.assertEqual(
                    werte, sorted(werte, reverse=True),
                    f'Die Rampe `{familie}` wird nicht durchgehend dunkler: '
                    f'{[f"{w:.2f}" for w in werte]}')

    def test_die_gebrauchten_textfarben_sind_lesbar(self):
        """Die Stufen, die im Bestand als Textfarbe auf Weiss stehen."""
        for familie, stufe in (('slate', 500), ('slate', 600), ('slate', 700),
                               ('slate', 900), ('indigo', 600), ('indigo', 700),
                               ('emerald', 600), ('amber', 600), ('rose', 600),
                               ('sky', 600)):
            with self.subTest(farbe=f'{familie}-{stufe}'):
                r = kontrast(self.rampen[familie][stufe], '#ffffff')
                self.assertGreaterEqual(
                    r, MINDESTKONTRAST,
                    f'text-{familie}-{stufe} erreicht auf Weiss nur {r:.2f}:1.')

    def test_zustandsfarben_bleiben_unterscheidbar(self):
        """Eine Warnung in Petrol wäre keine Warnung mehr.

        Die semantischen Familien werden an die Konzeptwerte angeglichen —
        aber Rot muss Rot bleiben und Grün Grün, sonst trägt die Farbe keine
        Bedeutung mehr.
        """
        def ton(hex_wert):
            r, g, b = (int(hex_wert[i:i + 2], 16) for i in (1, 3, 5))
            return r, g, b

        r, g, b = ton(self.rampen['rose'][600])
        self.assertGreater(r, g + 40, 'rose-600 ist nicht mehr rot.')
        r, g, b = ton(self.rampen['emerald'][600])
        self.assertGreater(g, r + 40, 'emerald-600 ist nicht mehr grün.')
        r, g, b = ton(self.rampen['indigo'][600])
        self.assertGreater(g, r + 40, 'indigo-600 ist nicht petrol.')

    def test_das_favicon_ist_nicht_mehr_indigo(self):
        """Es trug `#4f46e5` — die alte Markenfarbe, im Browsertab sichtbar.

        Kommentare zählen nicht als Vorkommen. Der Erklärtext zur Palette
        ZITIERT den alten Wert, um zu sagen, was er ersetzt; die erste
        Fassung dieses Tests fand das Zitat und war rot. Derselbe Fehler wie
        in `test_gestapelte_tabellen` am selben Tag — eine Prüfung, die die
        Erklärung eines Sachverhalts für den Sachverhalt hält.
        """
        text = BASE.read_text(encoding='utf-8')
        kopf = ohne_kommentare(text[:text.index('</head>')]).lower()
        self.assertNotIn('4f46e5', kopf,
                         'Das alte Indigo steht noch im Kopfbereich.')
        self.assertIn('%230f6f6a', kopf, 'Das Favicon führt nicht die Markenfarbe.')

    def test_kommentare_zaehlen_nicht_als_farbe(self):
        """Gegenprobe zu genau dem Fehler, den dieser Test selbst hatte."""
        zitat = '/* frueher #4f46e5 */ <!-- und #4f46e5 -->'
        self.assertNotIn('4f46e5', ohne_kommentare(zitat))
        self.assertIn('4f46e5', zitat)
        # Und der Bereiniger darf nicht einfach alles wegwerfen:
        self.assertIn('#0f6f6a', ohne_kommentare('/* x */ fill=#0f6f6a'))

    def test_die_messung_findet_einen_fehler_auch(self):
        """Gegenprobe: Ein kaputter Leser meldete überall nichts.

        Wenn `rampen()` bei einer Syntaxänderung nur noch ein leeres
        Wörterbuch liefert, müssen die Tests darüber scheitern statt still
        durchzulaufen — `test_es_gibt_ueberhaupt_rampen` deckt das ab. Hier
        die andere Richtung: Der Leser muss echte Werte liefern.
        """
        self.assertEqual(len(self.rampen['indigo']), 10)
        self.assertTrue(all(re.fullmatch(r'#[0-9a-f]{6}', w)
                            for w in self.rampen['indigo'].values()))


class HuellenTests(TestCase):
    """Jede Huelle der Anwendung muss die Petrol-Palette auch wirklich laden.

    WARUM

    Bis 4b.9 stand die Rampe nur in `base.html`, und dieser Test las nur
    `base.html`. Er bestaetigte damit die eine Stelle, an der aufgeraeumt
    worden war, und sah die zwei anderen Huellen nie an: `base_embed.html`
    und `_modal_done.html` luden dasselbe Tailwind, aber ohne die
    Umdefinition. Eingebettete Seiten und Modale — darunter die
    Wohnungsabnahme — rendern deshalb in Tailwinds Voreinstellung: blaugraues
    Slate, indigoblaue Akzente, mitten in einer petrolfarbenen Anwendung.

    WAS SICH MIT E0.2 GEAENDERT HAT

    Die Frage ist dieselbe geblieben, die Antwort liegt eine Ebene tiefer.
    Vorher: «Laedt die Huelle Tailwind vom CDN — und gleich daneben den
    Palette-Baustein?» Jetzt: «Bindet die Huelle den Stilbaustein ein — und
    zwar den mit der Petrol-Palette?» Es gibt kein CDN mehr, das man
    mitzaehlen koennte; die Farben stecken im Bau.

    Die Gefahr ist damit nicht kleiner, sondern anders: Wer eine neue Huelle
    baut und `core/_assets_aussen.html` einbindet (oder gar nichts), bekommt
    Tailwind in der Voreinstellung — dasselbe zweifarbige Ergebnis wie
    vorher, nur ueber einen anderen Weg.
    """

    def _huellen_im_dateisystem(self):
        """Alle Vorlagen, die einen Stilbaustein EINBINDEN.

        Gesucht wird die Einbindung, nicht das Wort. Seit E2.22 gibt es
        `fw/_schicht.html` und `fw/_schicht_link.html`; beide NENNEN
        `_assets.html` in ihrem Erklaertext, um zu sagen, wer sie laedt. Eine
        Suche nach der Zeichenkette zaehlte sie deshalb als Huellen ohne
        Palette — derselbe blinde Fleck wie in `test_keine_fremdquellen.py`
        und `test_farbklassen.py`: Erklaerung fuer Tatsache gehalten.
        """
        wurzel = pathlib.Path('core/templates')
        muster = re.compile(r"\{%\s*include\s+['\"][^'\"]*_assets[^'\"]*['\"]\s*%\}")
        return sorted(str(p) for p in wurzel.rglob('*.html')
                      if muster.search(p.read_text(encoding='utf-8'))
                      and not p.name.startswith('_assets'))

    def test_die_suche_findet_ueberhaupt_huellen(self):
        """Sonst pruefte der Test unten eine leere Liste."""
        gefunden = self._huellen_im_dateisystem()
        self.assertGreaterEqual(len(gefunden), 10, gefunden)
        for pfad in HUELLEN:
            self.assertIn(pfad, gefunden,
                          f'{pfad} bindet keinen Stilbaustein mehr ein — dann '
                          f'laedt sie weder Tailwind noch Schrift noch Icons.')

    def test_jede_huelle_der_anwendung_laedt_die_palette(self):
        for pfad in HUELLEN:
            with self.subTest(huelle=pfad):
                self.assertIn(
                    BAUSTEIN, pathlib.Path(pfad).read_text(encoding='utf-8'),
                    f'{pfad} laedt Tailwind ohne die Petrol-Rampe. Die Seite '
                    f'rendert dann in Tailwinds Voreinstellung.')

    def test_der_baustein_zeigt_auf_die_gebaute_datei(self):
        """Gegenprobe: Ein Baustein, der ins Leere zeigt, bestuende oben.

        Gelesen werden die <link>-Zeilen, nicht der Rohtext: Der Erklaerkopf
        des Bausteins NENNT `tailwind-aussen.css`, um zu sagen, warum es die
        zweite Datei gibt. Eine Suche im ganzen Text findet dieses Wort und
        haelt die Erklaerung fuer die Sache — derselbe Fehler, den
        `test_das_favicon_ist_nicht_mehr_indigo` schon einmal hatte.
        """
        text = pathlib.Path('core/templates/fw/_assets.html').read_text(encoding='utf-8')
        verweise = re.findall(r'<link[^>]*>', text)
        self.assertTrue(verweise, 'Der Baustein enthaelt keine <link>-Zeile.')
        zusammen = ' '.join(verweise)
        self.assertIn('css/tailwind.css', zusammen)
        self.assertNotIn(
            'tailwind-aussen.css', zusammen,
            'Die Anwendung wuerde Tailwind OHNE die Markenpalette laden.')

    def test_die_sonde_wird_von_echtem_code_am_leben_gehalten(self):
        """Die zwei Prüfungen darunter stehen und fallen mit dieser Klasse.

        WAS IN E2.49 PASSIERT IST

        Sie benutzten `bg-indigo-600` als Sonde. Diese Klasse stand im ganzen
        Bestand nur EINMAL: in `faelle/test_bereichsgestaltung.py`, wo sie als
        Beispiel für eine VERBOTENE Klasse dient. Tailwind las damals auch die
        Testdateien und baute brav eine Regel daraus — beide Prüfungen liefen
        also jahrelang gegen ein Artefakt ihrer eigenen Testsammlung.

        E2.49 nahm die Testdateien aus dem Bau. Die Regel verschwand, und
        beide Prüfungen schlugen fehl mit «wurde nicht gebaut» — obwohl der
        Bau in Ordnung war. Die Meldung zeigte in die falsche Richtung, was
        schlimmer ist als gar keine.

        Die Sonde ist jetzt `text-indigo-600`, und diese Prüfung hält fest,
        WARUM sie existiert: weil echter Code sie benutzt. Verschwindet sie
        dort, meldet sich diese Prüfung — mit dem richtigen Grund.
        """
        treffer = []
        for datei in WURZEL.rglob('*.py'):
            teile = datei.parts
            if ('node_modules' in teile or 'migrations' in teile
                    or 'tests' in teile or datei.name.startswith('test_')):
                continue
            if SONDE in datei.read_text(encoding='utf-8'):
                treffer.append(datei.relative_to(WURZEL).as_posix())
        for datei in (WURZEL / 'core/templates').rglob('*.html'):
            if SONDE in datei.read_text(encoding='utf-8'):
                treffer.append(datei.relative_to(WURZEL).as_posix())
        self.assertTrue(
            treffer,
            f'`{SONDE}` steht in keiner Datei ausserhalb der Testsammlung. '
            f'Damit baut Tailwind keine Regel dafür, und die zwei Prüfungen '
            f'darunter melden «nicht gebaut», obwohl der Bau stimmt. Eine '
            f'andere Klasse aus der Indigo-Rampe als SONDE wählen — eine, '
            f'die echter Code benutzt.')

    def test_der_bau_traegt_die_rampe_auch_wirklich(self):
        """Der Schritt, den es vorher nicht geben konnte.

        Frueher uebersetzte das CDN die Konfiguration bei jedem Seitenaufruf
        im Browser — Konfiguration und Ergebnis waren dasselbe. Jetzt liegt
        eine gebaute Datei dazwischen, und die kann veralten: Wer die Palette
        aendert und `npm run css` vergisst, hat eine richtige Konfiguration
        und eine falsche Anwendung. Genau diese Luecke schliesst dieser Test.
        """
        css = GEBAUT.read_text(encoding='utf-8')
        marke = rampen()['indigo'][600].lstrip('#')
        r, g, b = (int(marke[i:i + 2], 16) for i in (0, 2, 4))
        # `assertIn` mit der ganzen Datei als Heuhaufen wuerde im Fehlerfall
        # 67 KB CSS in den Bericht schreiben. Eine Fehlermeldung, die niemand
        # liest, ist so gut wie keine — deshalb erst suchen, dann urteilen.
        gefunden = re.search(rf'\.{SONDE}\{{[^}}]*?(\d+ \d+ \d+)', css)
        self.assertIsNotNone(
            gefunden,
            f'In {GEBAUT} gibt es keine Regel `.{SONDE}` — wurde die '
            f'Datei ueberhaupt gebaut? `npm run css` ausfuehren. '
            f'{SONDE_HINWEIS}')
        self.assertEqual(
            gefunden.group(1), f'{r} {g} {b}',
            f'`{SONDE}` steht in {GEBAUT} auf rgb({gefunden.group(1)}), '
            f'die Palette sagt #{marke} = rgb({r} {g} {b}). Die Palette wurde '
            f'geaendert, aber nicht neu gebaut — `npm run css` ausfuehren.')

    def test_die_aussen_datei_traegt_die_palette_bewusst_NICHT(self):
        """Gegenprobe zum Test darueber — sonst prueft er nur, dass zwei
        gleiche Dateien gleich sind.

        Waeren beide Dateien identisch gebaut, waere die Trennung sinnlos und
        die Aussenseiten waeren beim Umstellen nebenbei umgefaerbt worden.
        """
        aussen = pathlib.Path('static/css/tailwind-aussen.css').read_text(encoding='utf-8')
        gefunden = re.search(rf'\.{SONDE}\{{[^}}]*?(\d+ \d+ \d+)', aussen)
        self.assertIsNotNone(
            gefunden, f'tailwind-aussen.css wurde nicht gebaut. {SONDE_HINWEIS}')
        marke = rampen()['indigo'][600].lstrip('#')
        r, g, b = (int(marke[i:i + 2], 16) for i in (0, 2, 4))
        self.assertNotEqual(
            gefunden.group(1), f'{r} {g} {b}',
            'Die Aussen-Datei traegt die Markenpalette. Damit waeren '
            'Mieterportal, Bewerbungsformular und Fehlerseiten umgefaerbt — '
            'eine Gestaltungsentscheidung, die E0.2 nicht treffen sollte.')

    def test_die_aussenseiten_sind_gezaehlt_statt_vergessen(self):
        """Was Mieter und Bewerber sehen, ist NOCH nicht umgestellt.

        Das ist eine Entscheidung, keine Nachlaessigkeit: Die Palette dort
        einzuziehen aendert das Erscheinungsbild gegenueber Dritten. Dieser
        Test haelt die Zahl fest, damit die Luecke benannt bleibt und nicht
        stillschweigend waechst.
        """
        offen = [p for p in self._huellen_im_dateisystem() if p not in HUELLEN]
        self.assertGreater(len(offen), 0)
        self.assertLessEqual(
            len(offen), 15,
            f'Es sind mehr Huellen ohne Palette geworden ({len(offen)}): '
            f'{offen}. Neue Huellen der Anwendung binden `fw/_assets.html` ein.')
