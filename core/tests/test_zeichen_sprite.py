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
        # KEINE feste Zahl mehr.
        #
        # Hier stand `>= 3`. Die Liste soll aber SCHRUMPFEN — jede
        # Entscheidung macht sie kuerzer, und der Test wurde rot, als
        # `code` in E2.42 entschieden wurde. Er meldete damit Fortschritt
        # als Fehler; dieselbe Lehre wie bei `assertIn('fa-plug', …)`.
        #
        # Geprueft wird jetzt die Sache: Solange es offene Fragen gibt, muss
        # die Suche sie finden. Sind alle entschieden, darf dieser Test weg —
        # und sagt es.
        offen = _offene_zeichen()
        if offen:
            self.assertGreaterEqual(len(offen), 1)
        else:
            self.skipTest('Keine offenen Zeichen mehr — dieser Test und die '
                          'Liste in docs/ZEICHEN.md duerfen entfallen.')

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


class KeineVerschachtelungTest(SimpleTestCase):
    """Ein Django-Baustein im Klassenwert eines Bausteins geht nicht auf.

    DERSELBE FEHLER, ZWEIMAL

    In E2.39 und E2.41 hat die Umstellung eine Bedingung in den
    `klasse='…'`-Wert geschrieben:

        {% zeichen 'recht' klasse='{% if differenz %}fw-warnton{% endif %}' %}

    Die Anführungszeichen verschachteln sich, und die Vorlage ist unlesbar —
    beim ersten Mal fielen 27 Tests aus, beim zweiten 39. Behoben wird es,
    indem die Bedingung in ein umschliessendes `<span>` wandert.

    Dieser Test fängt es, bevor ein Testlauf es tut. Der Unterschied ist
    nicht die Erkennung, sondern die MELDUNG: 39 Fehler in fremden Modulen
    sagen nicht, was zu tun ist; diese Zeile schon.
    """

    def test_kein_django_baustein_im_klassenwert(self):
        muster = re.compile(r"\{% zeichen(?:_wert)? [^%]*klasse='[^']*\{%")
        funde = []
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            for treffer in muster.findall(p.read_text(encoding='utf-8')):
                funde.append(f'{p.name}: {treffer[:60]}')
        self.assertEqual(
            funde, [],
            'Hier steht eine Django-Bedingung im `klasse`-Wert:\n  '
            + '\n  '.join(funde)
            + '\n\nDie Anführungszeichen verschachteln sich — die Vorlage '
              'wird unlesbar. Die Bedingung gehört in ein umschliessendes '
              '<span>:\n'
              '  <span class="{% if … %}…{% endif %}">{% zeichen \'name\' %}</span>')

    def test_die_pruefung_wuerde_einen_fall_erkennen(self):
        """Gegenprobe: Das Muster muss den Fall auch treffen."""
        muster = re.compile(r"\{% zeichen(?:_wert)? [^%]*klasse='[^']*\{%")
        self.assertTrue(muster.search(
            "{% zeichen 'recht' klasse='{% if x %}a{% endif %}' %}"))
        self.assertIsNone(muster.search("{% zeichen 'recht' klasse='fw-gut' %}"))


class KeinFontAwesomeMehrTest(SimpleTestCase):
    """Die Anwendung lädt kein Icon-Schriftpaket mehr.

    WAS ES GEKOSTET HAT

    87 KB CSS und 144 KB Schriften bei jedem Erstaufruf — über 230 KB.
    Zuletzt hingen daran **drei** Vorkommen: zwei `fa-spin`-Spinner und ein
    `fa-code`. Nach der Umstellung von 1136 auf 11 wurde das Gewicht praktisch
    nur noch für zwei drehende Kreise getragen.

    Alle drei stehen jetzt im eigenen Sprite; die Drehung macht die Schicht
    mit acht Zeilen CSS.

    DIE »AUSNAHME« IST KEINE — SIE IST EIN ALTER STILLER FEHLER

    `templates/admin/dashboard_stats.html` trägt noch sieben `fa-`-Klassen.
    Die Etappe nennt sie eine bewusste Ausnahme, die »an Djangos eigener
    Hülle hängt«. Nachgemessen: Die beiden `<link>`-Zeilen standen
    ausschliesslich in `fw/_assets.html` und `core/_assets_aussen.html`, und
    Djangos Admin bindet keine von beiden ein. Die sieben Zeichen waren also
    schon vor E2.42 leer.

    Dazu liegt in `core/templates/admin/` eine zweite Datei desselben
    Namens. `DIRS` wird vor `APP_DIRS` durchsucht, also gewinnt die unter
    `templates/`; die andere rendert nie — steht aber weiter in der
    Sperrklinke der Farbklassen.

    Beides gehört behoben und braucht das Sprite in der Admin-Hülle. Bis
    dahin bleiben die Font-Awesome-Dateien im Repo.
    """

    #: Die Hüllen der Anwendung. Djangos Admin hat eine eigene.
    HUELLEN = ('core/templates/fw/_assets.html',
               'core/templates/core/_assets_aussen.html')

    def test_keine_huelle_laedt_fontawesome(self):
        funde = []
        for h in self.HUELLEN:
            text = (WURZEL / h).read_text(encoding='utf-8')
            # Der Erklärtext nennt es — geprüft wird die Ladezeile.
            for zeile in text.split('\n'):
                if 'fontawesome' in zeile.lower() and '<link' in zeile:
                    funde.append(f'{h}: {zeile.strip()[:60]}')
        self.assertEqual(
            funde, [],
            'Font Awesome wird wieder geladen:\n  ' + '\n  '.join(funde)
            + '\n\nDas sind 87 KB CSS und 144 KB Schriften bei jedem '
              'Erstaufruf. Wer ein Zeichen braucht, trägt es in '
              'docs/ZEICHEN.md ein und zeichnet es ins Sprite.')

    def test_keine_vorlage_ausser_dem_admin_benutzt_es(self):
        """Sonst wäre die Anwendung kaputt statt leicht.

        Ein `<i class="fa-solid …">` ohne geladene Schrift zeigt NICHTS — und
        zwar lautlos. Das ist schlimmer als das Gewicht.
        """
        muster = re.compile(r'<i class="fa-(?:solid|regular|brands) ')
        funde = []
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            if muster.search(p.read_text(encoding='utf-8')):
                funde.append(p.relative_to(WURZEL).as_posix())
        self.assertEqual(
            funde, [],
            f'Diese Vorlagen benutzen Font Awesome, das nicht mehr geladen '
            f'wird — die Zeichen bleiben LEER: {funde}')

    def test_das_drehende_zeichen_gibt_es(self):
        """`laedt` ist der Ersatz für die zwei Spinner."""
        self.assertIn('laedt', _aus_sprite())
        schicht = (WURZEL / 'core' / 'templates' / 'fw' / '_schicht.html'
                   ).read_text(encoding='utf-8')
        self.assertIn('fw-dreht', schicht, 'Die Drehung fehlt in der Schicht.')
        self.assertIn(
            'prefers-reduced-motion', schicht,
            'Wer Bewegung abgestellt hat, bekommt sie trotzdem — das ist '
            'keine Kleinigkeit, sondern für manche Menschen ein Problem.')


class ZeichenAusDatenTest(SimpleTestCase):
    """Ein Datenwert muss durch den Baustein, sonst steht sein NAME auf der Seite.

    DER BEFUND (E2.42, Gegenprüfung)

    `vertrag_detail.html` hatte in einem Zweig noch `{{ it.icon }}` stehen.
    Bis E2.41 war das eine Font-Awesome-Klasse und die Zeile lautete
    `<i class="fa-solid {{ it.icon }}">` — da ergab es Markup. Seit E2.41 ist
    `it.icon` ein Name wie `vertrag`, und `{{ it.icon }}` schreibt genau das
    als **Text** in die Kachel: ein 36×36-Kästchen mit dem Wort «vertrag».

    Kein bestehender Wächter sah das: Der eine sucht `<i class="fa-…">`, der
    andere prüft die Datenwerte im Python-Code — beide richtig, beide blind
    für die Ausgabestelle.
    """

    #: `{{ …icon… }}` ausserhalb der Admin-Vorlagen. Die haben eine eigene
    #: Hülle und ein eigenes Schema (dort sind es Emoji).
    MUSTER = re.compile(r'\{\{\s*[\w.]*icon[\w.]*\s*(?:\|[^}]*)?\}\}')

    def test_kein_datenwert_wird_roh_ausgegeben(self):
        funde = []
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            if 'admin' in p.parts:
                continue
            for nr, zeile in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
                if 'icon_cls' in zeile:
                    continue      # eine Farbklasse, kein Zeichenname
                if self.MUSTER.search(zeile):
                    funde.append(f'{p.relative_to(WURZEL).as_posix()}:{nr}')
        self.assertEqual(
            funde, [],
            f'Hier steht ein Zeichen-Datenwert roh in der Vorlage: {funde}. '
            f'Seit E2.41 ist das ein NAME, kein Markup — er erscheint als '
            f'Text auf der Seite. Richtig ist `{{% zeichen_wert … %}}`.')

    def test_die_pruefung_wuerde_einen_fall_erkennen(self):
        self.assertTrue(self.MUSTER.search('<div>{{ it.icon }}</div>'))
        self.assertTrue(self.MUSTER.search('{{ zeile.typ_icon }}'))
        self.assertIsNone(self.MUSTER.search("{% zeichen_wert it.icon %}"))


class KeineToteBedingungTest(SimpleTestCase):
    """Beide Zweige dasselbe Zeichen — dann ist die Bedingung Ballast.

    In E2.42 blieben zwei solche Stellen stehen: `liegenschaft_detail.html`
    prüfte auf `g.einheit` und zeichnete in beiden Fällen `liegenschaft`,
    `objekt_detail.html` unterschied Gewerbe von Wohnung und zeichnete
    ebenfalls beide Male dasselbe.

    Das ist nicht nur überflüssig. Es sieht beim Lesen aus, als würde
    unterschieden — der nächste sucht den Unterschied und findet keinen.
    """

    MUSTER = re.compile(
        r"\{%\s*if [^%]*%\}\{%\s*zeichen '([a-z]+)'[^%]*%\}"
        r"\{%\s*else\s*%\}\{%\s*zeichen '([a-z]+)'[^%]*%\}\{%\s*endif\s*%\}")

    def test_keine_bedingung_zeichnet_zweimal_dasselbe(self):
        funde = []
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            for nr, zeile in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
                for t in self.MUSTER.finditer(zeile):
                    if t.group(1) == t.group(2):
                        funde.append(
                            f'{p.relative_to(WURZEL).as_posix()}:{nr} '
                            f'(beide «{t.group(1)}»)')
        self.assertEqual(
            funde, [],
            f'Diese Bedingungen zeichnen in beiden Zweigen dasselbe: {funde}')

    def test_die_pruefung_wuerde_einen_fall_erkennen(self):
        t = self.MUSTER.search("{% if x %}{% zeichen 'gut' %}{% else %}{% zeichen 'gut' %}{% endif %}")
        self.assertIsNotNone(t)
        self.assertEqual(t.group(1), t.group(2))
