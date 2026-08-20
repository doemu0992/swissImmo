"""Die Tailwind-Rampen müssen an den Konzept-Tokens hängen, nicht daneben.

WARUM ES DIESEN TEST GIBT

Am 20.08.2026 trugen **176 Vorlagen 7490 fest verdrahtete Farbklassen** —
4959 `slate`, 1250 `indigo`, dazu rose, emerald, amber. Die Aktenseiten waren
auf die Komponentenschicht umgestellt, alles andere nicht: Seitenleiste,
Topbar, Listen, Formulare, Berichte blieben indigoblau. Die Anwendung war
zweifarbig.

`KONZEPT-UI.md` 16.4 nennt zwei Wege: Klassen einzeln umstellen oder Tailwind
eine Petrol-Palette unterschieben. Gewählt ist der zweite — eine Änderung in
`base.html` statt 7490 verteilter.

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
    """Die Farbrampen aus `tailwind.config` in base.html.

    Gelesen wird der Text, nicht ausgeführtes JavaScript — der Test soll
    keine JS-Laufzeit brauchen. Eine erste Fassung übersetzte den Block nach
    JSON und war dabei zu clever: Sie zerbrach an den Kommentaren zwischen
    den Rampen. Jetzt werden die Paare `stufe: '#rrggbb'` direkt gelesen.

    Was das nicht kann: einen JavaScript-Syntaxfehler melden. Dagegen steht
    `test_es_gibt_ueberhaupt_rampen` — verschwindet eine Rampe aus dem
    Ergebnis, schlägt er an, statt dass alles still grün bleibt.
    """
    quelle = BASE.read_text(encoding='utf-8')
    anfang = quelle.index('tailwind.config')
    block = quelle[anfang:quelle.index('</script>', anfang)]
    block = ohne_kommentare(block)
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
                                f'Aufbau von tailwind.config geändert?')
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
        kopf = ohne_kommentare(
            BASE.read_text(encoding='utf-8')[:BASE.read_text(
                encoding='utf-8').index('</head>')]).lower()
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
