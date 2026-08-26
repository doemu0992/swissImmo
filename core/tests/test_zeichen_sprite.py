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
        # Drei seit E2.40: `stamp`, `rotate-left` und `bell` sind
        # entschieden und aus der Liste gestrichen.
        self.assertGreaterEqual(len(_offene_zeichen()), 3)

    def test_kein_zeichen_steht_in_beiden_listen(self):
        """Entschieden UND offen zugleich geht nicht.

        E2.40 entschied `stamp`, `rotate-left` und `bell` (zu `freigeben`,
        `storno`, `meldung`), liess ihre Einträge unter »Noch ohne
        Bedeutung« aber stehen — samt der Begründung, warum die Bedeutung
        noch fehle. Das Dokument behauptete und widerlegte dieselbe Sache.

        Die bestehenden Prüfungen blieben grün: Die eine fragt, ob jeder
        Name irgendwo im Dokument vorkommt, die andere liest nur bis zur
        offenen Liste. Keine sieht, dass ein Name in beiden steht.
        """
        doppelt = _aus_tabelle() & _offene_zeichen()
        self.assertEqual(
            sorted(doppelt), [],
            f'Diese Zeichen stehen als entschieden UND als offen in '
            f'docs/ZEICHEN.md: {sorted(doppelt)}. Wer entscheidet, streicht '
            f'den alten Eintrag.')


class SchliessenKnoepfeTest(SimpleTestCase):
    """Ein Knopf zum Schliessen darf nicht aussehen wie etwas anderes.

    DER BEFUND

    Die Umstellung in E2.39 setzte `xmark` auf vier Schliessen-Knöpfen auf
    `mehr` (»Weitere Handlungen«), und E2.38 hatte »Menü schliessen« in
    `base.html` auf `loeschen` gesetzt — einen Papierkorb. Ein Knopf, der
    aussieht, als lösche er etwas, ist schlimmer als gar kein Zeichen: Er
    wird gelesen, bevor der Text daneben gelesen wird, und hier steht oft
    gar kein Text daneben.

    `mehr` hätte damit an zwei Orten Verschiedenes geheissen — genau der
    Fehler, gegen den `docs/ZEICHEN.md` geschrieben ist.

    WARUM AM MARKUP UND NICHT AM QUELLTEXT

    Geprüft wird die Beschriftung neben dem Zeichen (`title`, `aria-label`),
    nicht ein Vorkommen im Code. Wer einen neuen Schliessen-Knopf baut und
    das falsche Zeichen wählt, wird hier rot — unabhängig davon, wie die
    Zeile sonst aussieht.
    """

    #: Zeichen, die auf einem Schliessen-Knopf nichts zu suchen haben.
    FALSCH = ('mehr', 'loeschen', 'zurueck')

    def _knoepfe(self):
        for ordner in ('core/templates', 'templates'):
            for pfad in sorted((WURZEL / ordner).rglob('*.html')):
                for nr, zeile in enumerate(
                        pfad.read_text(encoding='utf-8').splitlines(), 1):
                    beschr = re.findall(r'(?:title|aria-label)="([^"]*)"', zeile)
                    if any('schliess' in b.lower() for b in beschr):
                        yield pfad, nr, zeile

    def test_kein_schliessen_knopf_traegt_ein_fremdes_zeichen(self):
        funde = []
        for pfad, nr, zeile in self._knoepfe():
            for name in re.findall(r"zeichen '([a-z]+)'", zeile):
                if name in self.FALSCH:
                    funde.append(f'{pfad.name}:{nr} → «{name}»')
        self.assertEqual(
            funde, [],
            f'Diese Schliessen-Knöpfe tragen ein fremdes Zeichen: {funde}. '
            f'Zum Wegklicken gibt es `schliessen`.')

    def test_die_pruefung_findet_ueberhaupt_knoepfe(self):
        """Gegenprobe: Ohne Fundstellen wäre die Prüfung oben trivial grün."""
        self.assertGreaterEqual(len(list(self._knoepfe())), 4)
