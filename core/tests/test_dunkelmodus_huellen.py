"""Keine festen Farbwerte auf `body` — sonst friert eine Seite im hellen Modus ein.

WORUM ES GEHT

Der Dunkelmodus entsteht aus Tokens: `--ds-surface-2`, `--ds-ink` und die
übrigen `--ds-*` werden unter `prefers-color-scheme: dark` neu belegt. Wer
stattdessen `#f8fafc` schreibt, bekommt in beiden Modi denselben Wert. Die
Seite sieht aus wie immer — und genau deshalb fällt es niemandem auf.

WAS E2.48 GEFUNDEN HAT, UND WAS ES NICHT GEFUNDEN HAT

Die Etappe stellte `modern_base.html` um und nannte das «die letzten zwei
Tailwind-Farbklassen der Aussenseiten». Im Browser nachgemessen stimmte
davon die Hälfte, und die Zahl stimmte gar nicht:

  · `modern_base.html`: Der GRUND war nie eingefroren. `.fw-flaeche2` ist
    eine Klasse (0,1,0), `body` ein Element (0,0,1) — die Klasse gewinnt,
    `#f8fafc` war toter Code. Eingefroren war die SCHRIFT: `fw-flaeche2`
    setzt kein `color`, also galt `#1e293b` hell wie dunkel.

  · `public_bewerbung_geschlossen.html`: Grund `rgb(248,250,252)` in beiden
    Modi, Schrift im Dunkeln `rgb(228,237,238)`. Kontrast rund 1.06 — der
    Text war nicht schwer zu lesen, er war weg. Ohne Anmeldung erreichbar.

  · `public_ticket_form.html`: Grund `rgb(243,244,246)` in beiden Modi, dazu
    ein weisser Vollbild-Vorhang beim Laden. Das ist die Seite vom Aushang
    im Treppenhaus.

Drei Seiten, eine gefunden. Der Fund war richtig, die Suche war es nicht —
deshalb dieser Wächter: Er sucht, statt sich auf einen Blick zu verlassen.

WAS ER PRÜFT UND WAS NICHT

Er liest Vorlagentext, nicht gerechnete Stile — ein Browser läuft in dieser
Sammlung nicht. Damit findet er den Fehler an seiner Quelle: eine feste
Farbe in einer `body`-Regel. Ob die Regel am Ende greift, misst
`e2e/tests/dunkelmodus.spec.ts` im echten Browser; die zwei gehören
zusammen.

NUR DER SCHLICHTE SELEKTOR `body`

`html[data-theme="dark"] body { color:#e7eff2 }` in `fw/base.html` ist
ausdrücklich modusabhängig und richtig — eine Regel, die nur im Dunkeln
gilt, DARF einen festen Wert tragen. Geprüft wird deshalb nur `body` allein.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Ein `<style>`-Block. Findet auch Blöcke in JavaScript-Zeichenketten —
#: gewollt, denn auch dort steht Stil, der im Browser landet.
STIL = re.compile(r'<style[^>]*>(.*?)</style>', re.S | re.I)

#: CSS-Kommentare. Sie werden VOR der Suche entfernt — aus zwei Gründen:
#:
#:   · Ein Kommentar direkt über der Regel schob den Selektor aus der
#:     Reichweite des Musters. Die erste Fassung dieses Wächters war
#:     deswegen grün, während alle drei Vorlagen den Fehler trugen: In der
#:     Gegenprobe wurde der Hexwert zurückgesetzt, und nichts passierte.
#:     Der Kommentar, der die Korrektur erklärt, hätte den Wächter blind
#:     gemacht — die Erklärung hätte die Prüfung ausgeschaltet.
#:
#:   · Umgekehrt steht in diesen Kommentaren jetzt `#f8fafc` als Zitat.
#:     Ohne Entfernen wären sie selbst der Fund.
KOMMENTAR = re.compile(r'/\*.*?\*/', re.S)

#: Eine Regel mit dem schlichten Selektor `body` (nicht `X body`, nicht
#: `body.klasse`). Vorne muss der Selektor beginnen: Zeilenanfang oder eines
#: der Zeichen, die eine Regel abschliessen.
REGEL = re.compile(r'(?:^|[;{}])\s*body\s*\{([^}]*)\}', re.I | re.M)

#: Die Eigenschaften, die den Modus tragen.
DEKL = re.compile(r'(?:background-color|background|color)\s*:\s*([^;]+)', re.I)

#: Ein fester Farbwert — Hex, `rgb()`, `hsl()`. `var(--ds-ink)` faellt nicht
#: darunter, `currentColor`/`transparent`/`inherit` ebenfalls nicht.
FEST = re.compile(r'#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(')

#: Vorlagen, die einen festen Wert tragen DÜRFEN — mit Grund, nicht als
#: Sammelbecken. Wer hier etwas einträgt, schreibt dazu, warum der Modus
#: dort keine Rolle spielt.
AUSNAHMEN = {
    'core/templates/emails/base_email.html':
        'E-Mail. Mailprogramme kennen keine CSS-Variablen — ein Token käme '
        'dort als leerer Wert an, und der Brief hätte gar keine Farbe.',
    'core/templates/fw/kommunikation.html':
        'Druckfenster. Der Block steht in einer JavaScript-Zeichenkette und '
        'wird in ein `window.open` für den Briefdruck geschrieben. Papier '
        'hat keinen Dunkelmodus.',
}


def _fundstellen():
    """Jede `body`-Regel mit festem Farbwert. Ergibt `(pfad, wert)`.

    PDF-Vorlagen bleiben aussen vor: Ein Block mit `@page` geht an den
    PDF-Erzeuger, nicht an einen Browser.
    """
    for ordner in ('core/templates', 'templates'):
        verzeichnis = WURZEL / ordner
        if not verzeichnis.is_dir():
            continue
        for p in sorted(verzeichnis.rglob('*.html')):
            text = p.read_text(encoding='utf-8')
            for block in STIL.findall(text):
                if '@page' in block:
                    continue
                block = KOMMENTAR.sub(' ', block)
                for regel in REGEL.finditer(block):
                    for wert in DEKL.findall(regel.group(1)):
                        if FEST.search(wert):
                            yield p.relative_to(WURZEL).as_posix(), wert.strip()


class DunkelmodusHuellenTest(SimpleTestCase):

    def test_keine_huelle_verdrahtet_eine_farbe_auf_body(self):
        offen = [f'{pfad} → «{wert}»' for pfad, wert in _fundstellen()
                 if pfad not in AUSNAHMEN]
        self.assertEqual(
            offen, [],
            'Diese Vorlagen setzen eine feste Farbe auf `body` und frieren '
            'damit im hellen Modus ein. Token benutzen (`var(--ds-surface-2)`, '
            '`var(--ds-ink)`) oder in AUSNAHMEN eintragen — mit Grund: '
            f'{offen}')

    def test_die_suche_findet_ueberhaupt_body_regeln(self):
        """Gegenprobe: Ein Muster, das nie greift, ist immer grün.

        Ohne diese Prüfung wäre ein Tippfehler in `REGEL` oder `STIL` nicht
        von einem sauberen Bestand zu unterscheiden.
        """
        # Nach Dateien zählen, nicht nach Fundstellen: `base_email.html`
        # setzt Grund UND Schrift, ergibt also zwei Treffer in einer Datei.
        dateien = {pfad for pfad, _ in _fundstellen()}
        self.assertEqual(
            dateien, set(AUSNAHMEN),
            'Erwartet werden genau die benannten Ausnahmen, gefunden: '
            f'{sorted(dateien)}')

    def test_jede_ausnahme_existiert_und_greift_noch(self):
        """Eine Ausnahme für eine Datei, die sauber ist, verdeckt den nächsten Fehler."""
        gefunden = {pfad for pfad, _ in _fundstellen()}
        for pfad, grund in AUSNAHMEN.items():
            with self.subTest(pfad=pfad):
                self.assertTrue((WURZEL / pfad).is_file(), f'{pfad} gibt es nicht mehr')
                self.assertIn(
                    pfad, gefunden,
                    f'{pfad} trägt keinen festen Farbwert mehr — Ausnahme streichen.')
                self.assertGreater(len(grund), 40, f'{pfad}: Grund fehlt oder ist zu knapp')

    def test_ein_token_gilt_nicht_als_fester_wert(self):
        """Sonst wäre der Wächter nicht zu erfüllen."""
        self.assertIsNone(FEST.search('var(--ds-surface-2)'))
        self.assertIsNone(FEST.search('inherit'))
        self.assertIsNotNone(FEST.search('#f8fafc'))
        self.assertIsNotNone(FEST.search('rgb(248, 250, 252)'))

    def test_eine_modusabhaengige_regel_wird_nicht_bemaengelt(self):
        """`html[data-theme="dark"] body { … }` darf einen festen Wert tragen.

        Diese Regel gilt NUR im Dunkelmodus — sie friert nichts ein, sie ist
        der Dunkelmodus. Der Selektor ist deshalb auf `body` allein begrenzt.
        """
        block = 'html[data-theme="dark"] body { color:#e7eff2; }'
        self.assertEqual(list(REGEL.finditer(block)), [])

    def test_ein_kommentar_ueber_der_regel_macht_nicht_blind(self):
        """Die Falle, in die die erste Fassung dieses Wächters gelaufen ist.

        Ein CSS-Kommentar direkt über `body { … }` schob den Selektor aus der
        Reichweite des Musters. Ergebnis: grün, obwohl der Hexwert dastand.
        """
        block = '/* Warum das hier so ist, in mehreren\n   Zeilen erklärt. */\n' \
                'body { background-color: #f8fafc; }'
        ohne = KOMMENTAR.sub(' ', block)
        treffer = [t.group(1) for t in REGEL.finditer(ohne)]
        self.assertEqual(len(treffer), 1, f'Regel nicht gefunden in: {ohne!r}')
        self.assertTrue(FEST.search(treffer[0]))

    def test_ein_zitierter_hexwert_im_kommentar_ist_kein_fund(self):
        """Sonst wäre jede Erklärung «hier stand #f8fafc» selbst der Fehler."""
        block = '/* Hier stand #f8fafc. */\nbody { background-color: var(--ds-surface-2); }'
        ohne = KOMMENTAR.sub(' ', block)
        for regel in REGEL.finditer(ohne):
            for wert in DEKL.findall(regel.group(1)):
                self.assertIsNone(FEST.search(wert), f'falscher Fund: {wert}')
