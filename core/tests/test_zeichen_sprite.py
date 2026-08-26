"""Tabelle und Sprite müssen dieselben Zeichen führen.

DREI ORTE, EINE WAHRHEIT

    `docs/ZEICHEN.md`                  welche Zeichen es gibt, was sie bedeuten
    `core/templates/fw/_zeichen.html`  wie sie aussehen
    `core/templatetags/zeichen.py`     wie man sie einsetzt

Laufen sie auseinander, ist der Fehler **still**: Ein `<use>` auf ein Symbol,
das es nicht gibt, erzeugt ein leeres Bild. Die Seite sieht aus, als fehle
nichts — genau die Fehlerart, die in dieser Reihe schon dreimal aufgetreten
ist und jedes Mal nur durch Hinsehen gefunden wurde.

Der Baustein wirft im Entwicklungsbetrieb bei unbekanntem Namen. Das hilft
aber nur, wenn jemand die Seite aufruft. Dieser Test prüft die Übereinstimmung
ohne Aufruf.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
TABELLE = WURZEL / 'docs' / 'ZEICHEN.md'
SPRITE = WURZEL / 'core' / 'templates' / 'fw' / '_zeichen.html'


def _aus_tabelle():
    """Ueber den Baustein, damit es NICHT zwei Lesarten gibt.

    Die erste Fassung las hier selbst — mit einer Regex ueber den ganzen
    Text, waehrend `test_zeichensatz` bei der offenen Liste abschneidet.
    Ergebnis: 45 hier, 42 dort, und der Sprite richtete sich nach der
    falschen Zahl.
    """
    from core.templatetags.zeichen import erlaubte_zeichen

    return erlaubte_zeichen()


def _offene_zeichen():
    """Die Namen in der ERSTEN SPALTE der Liste »Noch ohne Bedeutung«.

    Nicht der ganze Abschnitt: Die Begruendungen dort verweisen auf
    entschiedene Zeichen (»`extern` passt nicht«, »weder `loeschen` noch
    `bearbeiten`«). Wer den Abschnitt als Ganzes durchsucht, haelt die
    fuer offen und meldet sie als unerlaubt.
    """
    from core.templatetags.zeichen import MARKE_OFFEN

    text = TABELLE.read_text(encoding='utf-8')
    abschnitt = text[text.index(MARKE_OFFEN):]
    namen = set()
    for zeile in abschnitt.splitlines():
        if not zeile.startswith('| `'):
            continue
        erste_spalte = zeile.split('|')[1]
        namen.update(re.findall(r'`([a-z][a-z-]*)`', erste_spalte))
    return namen


def _aus_sprite():
    return set(re.findall(r'<symbol id="z-([a-z]+)"',
                          SPRITE.read_text(encoding='utf-8')))


class TabelleUndSpriteTest(SimpleTestCase):

    def test_jedes_zeichen_der_tabelle_ist_gezeichnet(self):
        fehlend = sorted(_aus_tabelle() - _aus_sprite())
        self.assertEqual(
            fehlend, [],
            f'Diese Zeichen stehen in der Tabelle, aber nicht im Sprite: '
            f'{fehlend}. Wer sie einsetzt, bekommt ein LEERES Bild — die '
            f'Seite sieht aus, als fehle nichts.')

    def test_jedes_gezeichnete_zeichen_steht_in_der_tabelle(self):
        """Die andere Richtung ist ebenso wichtig.

        Ein Zeichen im Sprite ohne Eintrag in der Tabelle hat keine
        festgelegte Bedeutung. Der Baustein lässt es nicht durch — es wäre
        also totes Gewicht in jedem Seitenaufruf.
        """
        ueberzaehlig = sorted(_aus_sprite() - _aus_tabelle())
        self.assertEqual(
            ueberzaehlig, [],
            f'Diese Zeichen sind gezeichnet, stehen aber nicht in der '
            f'Tabelle: {ueberzaehlig}. Der Baustein lässt sie nicht durch.')

    def test_jedes_symbol_hat_einen_pfad(self):
        """Ein `<symbol>` ohne `<path>` ist ein leeres Bild mit Namen."""
        text = SPRITE.read_text(encoding='utf-8')
        ohne = [name for name in _aus_sprite()
                if not re.search(rf'<symbol id="z-{name}"[^>]*>.*?<path d="[^"]+"',
                                 text, re.S)]
        self.assertEqual(ohne, [], f'Symbole ohne Pfad: {sorted(ohne)}')

    def test_der_baustein_liest_dieselbe_tabelle(self):
        """Sonst prüfte er gegen eine andere Liste als dieser Test."""
        from core.templatetags.zeichen import erlaubte_zeichen

        self.assertEqual(
            erlaubte_zeichen(), _aus_tabelle(),
            'Der Baustein kennt andere Zeichen als die Tabelle.')

    def test_das_sprite_wird_ueberhaupt_eingebunden(self):
        """Ohne Einbindung zeigt jedes `<use>` ins Leere.

        Beide Hüllen müssen es laden — die Anwendung und die Aussenseiten.
        """
        for huelle in ('core/templates/fw/base.html',
                       'core/templates/core/_assets_aussen.html'):
            with self.subTest(huelle=huelle):
                self.assertIn(
                    "_zeichen.html", (WURZEL / huelle).read_text(encoding='utf-8'),
                    f'{huelle} bindet das Sprite nicht ein.')

    def test_die_pruefung_findet_ueberhaupt_zeichen(self):
        """Gegenprobe: Zwei leere Mengen wären trivial gleich."""
        self.assertGreater(len(_aus_tabelle()), 30)
        self.assertGreater(len(_aus_sprite()), 30)

    def test_die_unentschiedenen_sind_nicht_gezeichnet(self):
        """Ein Pfad macht aus einer offenen Frage eine Tatsache.

        `docs/ZEICHEN.md` führt sechs Zeichen unter »Noch ohne Bedeutung« —
        sie stehen dort, weil ihre Zuordnung eine Entscheidung braucht.
        `bell` etwa steht heute schon für zwei Dinge: eine Meldung und ein
        Klingelschild.

        Die erste Fassung dieser Etappe zeichnete drei davon (`stamp`,
        `bell`, `code`) und liess sie durch den Baustein. Damit hätte der
        Nächste die Bedeutung durch Benutzung festgelegt, und ein fertiger
        Pfad hätte sie amtlich aussehen lassen — genau das, was die Tabelle
        verhindern soll.

        Dass es diese drei waren, war zudem keine Wahl: Die damalige Regex
        traf `share, share-from-square` (Komma) und `rotate-left`
        (Bindestrich) nicht.
        """
        gezeichnet = _aus_sprite() & _offene_zeichen()
        self.assertEqual(
            sorted(gezeichnet), [],
            f'Diese Zeichen haben noch keine festgelegte Bedeutung, sind '
            f'aber gezeichnet: {sorted(gezeichnet)}. Erst eintragen, dann '
            f'zeichnen.')

    def test_der_baustein_laesst_die_unentschiedenen_nicht_durch(self):
        from core.templatetags.zeichen import erlaubte_zeichen

        durchgelassen = erlaubte_zeichen() & _offene_zeichen()
        self.assertEqual(sorted(durchgelassen), [])

    def test_die_offene_liste_wird_ueberhaupt_gefunden(self):
        """Gegenprobe: Eine leere Menge machte die zwei Prüfungen trivial."""
        self.assertGreaterEqual(len(_offene_zeichen()), 6)
