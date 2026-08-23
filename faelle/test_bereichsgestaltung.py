"""Die Bereichsinhalte müssen die Komponentenschicht benutzen, nicht Tailwind.

WARUM

Bis 4b.4 prüfte nichts, **wie ein Reiterinhalt aussieht**. Die Wächter fragten,
ob jeder Reiter ein Panel findet, ob es sichtbar wird, ob der Aktenkopf steht,
ob keine Aktion verlorenging — alles Fragen zur Verdrahtung. «Umgestellt» hiess
in den Commits zu 4b.3 deshalb bloss: Reitersatz und Kopf. Das stand nirgends
dabei, und im Betrieb sah der Nutzer weiter indigoblaue Knöpfe in einer
petrolfarbenen Akte.

Eine Messung am 20.08.2026 ergab: **drei von achtzehn** Bereichen waren
gestalterisch umgestellt, **sechs** enthielten nicht eine einzige
Komponentenklasse. Genau das hält dieser Test künftig fest.

WAS ER MISST

Vorkommen alter Tailwind-Farbklassen (`bg-indigo-600`, `text-slate-400`, …) je
Bereich, gegen eine Obergrenze. Fertige Bereiche stehen auf 0 und dürfen nie
wieder steigen; die noch offenen tragen ihren heutigen Stand als Deckel, damit
sie schrumpfen, aber nicht wachsen.

**Farben, nicht Layout.** `flex`, `gap-2`, `lg:col-span-2` bleiben erlaubt: Die
Komponentenschicht regelt Farbe und Bausteine, nicht das Raster. Wer das ändern
will, ändert das Konzept (Abschnitt 16.2), nicht diesen Test.

GRENZE DIESER MESSUNG

Sie liest **eine Datei**, keine eingebundenen Bausteine. `fw/_einschreiben_
zugang.html` steckt in drei Seiten und zählt in keiner davon mit; deshalb steht
er unten in `BAUSTEINE` mit eigenem Deckel. Wer einen neuen `{% include %}`
einführt, muss ihn dort eintragen — sonst wandert alter Code aus der Messung
heraus, statt zu verschwinden.
"""
import pathlib
import re

from django.test import TestCase

WURZEL = pathlib.Path('core/templates/fw')

#: Farbklassen aus Tailwind. Bewusst auf die Farbfamilien beschränkt, die im
#: Bestand vorkommen — ein `\w+-\d+` würde `gap-2` und `col-span-2` mitzählen.
ALT = re.compile(
    r'\b(?:bg|text|border|hover:bg|hover:text|hover:border|ring|from|to)-'
    r'(?:indigo|slate|rose|emerald|amber|sky|violet|gray|red|green|blue|zinc|neutral)-\d{2,3}\b')

#: Datei → Reiterpräfix. Nur die Akten, die den neuen Reitersatz führen.
SEITEN = {
    'liegenschaft_detail.html': 'lg',
    'vertrag_detail.html': 'vt',
    'schaden_detail.html': 'sc',
    'person_detail.html': 'pd',
    # 4b.11: Die Objektakte fehlte hier, seit es sie als umgestellte Akte
    # gibt — der Wächter sah sie schlicht nicht an. Deshalb steht unten
    # `test_jede_umgestellte_akte_wird_hier_gemessen`: Ein Typ, der als
    # umgestellt gilt und in diesem Verzeichnis fehlt, ist ungemessen.
    'objekt_detail.html': 'obj',
    # 4b.12: von Anfang an auf der Komponentenschicht gebaut — die Deckel
    # stehen deshalb auf 0 und halten sie dort.
    'mandat_detail.html': 'md',
    'dienstleister_detail.html': 'dl',
}

#: (Datei, Bereich) → erlaubte Höchstzahl alter Farbklassen.
#: **0 heisst fertig.** Alles darüber ist der Stand vom 20.08.2026 und eine
#: Arbeitsliste: Jede Zahl darf nur sinken. Wer einen Bereich umstellt, setzt
#: sie hier auf 0 — dann hält der Test ihn dort fest.
DECKEL = {
    ('liegenschaft_detail.html', 'stammdaten'): 0,
    ('liegenschaft_detail.html', 'chronik'): 0,
    ('liegenschaft_detail.html', 'finanzen'): 0,
    ('liegenschaft_detail.html', 'dokumente'): 0,
    ('liegenschaft_detail.html', 'faelle'): 0,
    ('liegenschaft_detail.html', 'einheiten'): 0,

    ('person_detail.html', 'stammdaten'): 0,
    ('person_detail.html', 'rollen'): 0,
    ('person_detail.html', 'finanzen'): 0,
    ('person_detail.html', 'dokumente'): 0,
    ('person_detail.html', 'chronik'): 0,
    ('person_detail.html', 'faelle'): 0,

    # 4b.11: Von 109 auf 59 gesenkt — Felder, Beschriftungen, Knoepfe und
    # Menuezeilen kommen jetzt aus der Komponentenschicht. Was bleibt, sind
    # Einzelstuecke (Statusfarben in Bedingungen, Fototabellen), die eine
    # Zeile-fuer-Zeile-Durchsicht brauchen.
    ('schaden_detail.html', 'stammdaten'): 10,
    ('schaden_detail.html', 'chronik'): 16,
    ('schaden_detail.html', 'finanzen'): 0,
    ('schaden_detail.html', 'faelle'): 0,
    ('schaden_detail.html', 'handwerker'): 24,
    ('schaden_detail.html', 'dokumente'): 8,

    # 4b.11: Von 179 auf 98 gesenkt.
    ('vertrag_detail.html', 'stammdaten'): 42,
    ('vertrag_detail.html', 'chronik'): 1,
    ('vertrag_detail.html', 'finanzen'): 15,
    ('vertrag_detail.html', 'dokumente'): 21,
    ('vertrag_detail.html', 'faelle'): 10,
    ('vertrag_detail.html', 'nebenkosten'): 0,

    # 4b.11: Von 478 auf 164 gesenkt, und der Bereich «Fälle» ist neu und
    # deshalb von Anfang an auf 0. Die drei grossen Reste sind Tabellen mit
    # vielen Formularzeilen (Sollmietzins, Raumbuch, Geraete/Zaehler).
    ('objekt_detail.html', 'stammdaten'): 0,
    ('objekt_detail.html', 'chronik'): 0,
    ('objekt_detail.html', 'finanzen'): 0,
    ('objekt_detail.html', 'dokumente'): 0,
    ('objekt_detail.html', 'faelle'): 0,
    ('objekt_detail.html', 'ausstattung'): 0,

    ('mandat_detail.html', 'stammdaten'): 0,
    ('mandat_detail.html', 'liegenschaften'): 0,
    ('mandat_detail.html', 'finanzen'): 0,
    ('mandat_detail.html', 'dokumente'): 0,
    ('mandat_detail.html', 'faelle'): 0,
    ('mandat_detail.html', 'chronik'): 0,

    ('dienstleister_detail.html', 'stammdaten'): 0,
    ('dienstleister_detail.html', 'auftraege'): 0,
    ('dienstleister_detail.html', 'finanzen'): 0,
    ('dienstleister_detail.html', 'dokumente'): 0,
    ('dienstleister_detail.html', 'faelle'): 0,
    ('dienstleister_detail.html', 'chronik'): 0,
}

#: Eingebundene Bausteine zählen in keiner Seite mit — sie brauchen einen
#: eigenen Deckel, sonst verschwindet alter Code aus der Messung, indem man ihn
#: in ein `{% include %}` verschiebt.
BAUSTEINE = {
    '_einschreiben_zugang.html': 0,
}


def bereiche(datei, praefix):
    """Die Bereiche einer Aktenvorlage als {Name: Quelltext}."""
    quelle = (WURZEL / datei).read_text(encoding='utf-8')
    marken = [(m.start(), m.group(1)) for m in
              re.finditer(rf'<div data-panel="{praefix}" id="{praefix}-([a-z0-9_]+)"', quelle)]
    marken.append((len(quelle), None))
    return {name: quelle[a:marken[i + 1][0]]
            for i, (a, name) in enumerate(marken[:-1])}


class BereichsgestaltungTests(TestCase):
    def test_kein_bereich_faellt_hinter_seinen_deckel_zurueck(self):
        for datei, praefix in sorted(SEITEN.items()):
            for name, block in sorted(bereiche(datei, praefix).items()):
                gefunden = ALT.findall(block)
                erlaubt = DECKEL[(datei, name)]
                with self.subTest(datei=datei, bereich=name):
                    self.assertLessEqual(
                        len(gefunden), erlaubt,
                        f'{datei} · {name}: {len(gefunden)} alte Farbklassen, '
                        f'erlaubt sind {erlaubt}. Neu hinzugekommen ist z. B. '
                        f'{sorted(set(gefunden))[:5]}. Die Komponentenschicht in '
                        f'base.html deckt Karte, Zeile, Tabelle, Betrag, Feld und '
                        f'Knopf ab — bitte von dort nehmen.')

    def test_jede_umgestellte_akte_wird_hier_gemessen(self):
        """Der Wächter muss wissen, was er alles anzusehen hat.

        Bis 4b.11 fehlte `objekt_detail.html` in SEITEN. Der Test war grün und
        sagte damit nichts über die Objektakte — die mit 478 alten Farbklassen
        die schlechteste von allen war. Dieselbe Falle wie beim Aktenkopf am
        20.08.2026: Eine zweite, unabhängig gepflegte Liste, die still hinter
        der ersten zurückbleibt.
        """
        from faelle.test_reiter_panels import TEMPLATES, UMGESTELLT
        fehlend = sorted(
            typ for typ in UMGESTELLT
            if TEMPLATES[typ][0].removeprefix('fw/') not in SEITEN)
        self.assertEqual(
            fehlend, [],
            f'Diese Akten gelten als umgestellt, ihre Bereichsgestaltung wird '
            f'hier aber nie gemessen: {", ".join(fehlend)}')

    def test_die_deckel_sind_nicht_veraltet(self):
        """Ein zu hoher Deckel ist ein stiller Freibrief.

        Die Zahlen sind eine Sperrklinke: Sie dürfen nur sinken. Wer einen
        Bereich umbaut und den Deckel stehen lässt, gibt den frei gewordenen
        Abstand als Guthaben für neue Tailwind-Klassen weiter. Diese Prüfung
        verlangt, dass jeder Deckel dem Ist-Stand entspricht — bis auf eine
        kleine Reserve, damit nicht jede Zeile Formatierung den Test rot macht.
        """
        RESERVE = 3
        zu_hoch = []
        for datei, praefix in sorted(SEITEN.items()):
            for name, block in sorted(bereiche(datei, praefix).items()):
                ist = len(ALT.findall(block))
                deckel = DECKEL[(datei, name)]
                if deckel > ist + RESERVE:
                    zu_hoch.append(f'{datei}·{name}: Deckel {deckel}, ist {ist}')
        self.assertEqual(
            zu_hoch, [],
            'Diese Deckel liegen deutlich über dem Ist-Stand und geben den '
            'Abstand als Guthaben frei. Bitte auf den Ist-Wert setzen:\n  '
            + '\n  '.join(zu_hoch))

    def test_bausteine_zaehlen_ebenfalls(self):
        for datei, erlaubt in sorted(BAUSTEINE.items()):
            gefunden = ALT.findall((WURZEL / datei).read_text(encoding='utf-8'))
            with self.subTest(datei=datei):
                self.assertLessEqual(
                    len(gefunden), erlaubt,
                    f'{datei}: {len(gefunden)} alte Farbklassen, erlaubt {erlaubt}.')

    def test_der_deckel_beschreibt_wirklich_jeden_bereich(self):
        """Gegenprobe gegen die eigene Blindheit.

        Ein Bereich, der in `DECKEL` fehlt, würde oben mit `KeyError` auffallen
        — aber erst, wenn jemand die Schleife bis dorthin laufen lässt. Ein
        Bereich, der in `DECKEL` steht und in keiner Vorlage mehr existiert,
        fiele **gar nicht** auf: Der Eintrag stünde als erfüllte Bedingung
        herum, ohne je etwas zu messen. Beide Richtungen prüfen.
        """
        echt = {(d, n) for d, p in SEITEN.items() for n in bereiche(d, p)}
        self.assertEqual(
            sorted(echt - set(DECKEL)), [],
            'Diese Bereiche hat niemand eingetragen — sie werden nicht gemessen.')
        self.assertEqual(
            sorted(set(DECKEL) - echt), [],
            'Diese Einträge zeigen auf Bereiche, die es nicht mehr gibt.')

    def test_die_messung_findet_ueberhaupt_etwas(self):
        """Gegenprobe: Der Ausdruck muss alten Code auch erkennen.

        Stünde in `ALT` ein Tippfehler, wären alle Zahlen 0 und der Test grün
        — die teuerste Art von grün. Also an einem Bereich nachweisen, der
        nachweislich noch alt ist, und an einer erfundenen Zeile.
        """
        alt = bereiche('vertrag_detail.html', 'vt')['stammdaten']
        self.assertGreater(len(ALT.findall(alt)), 20)
        self.assertEqual(ALT.findall('class="flex gap-2 lg:col-span-2 mt-4"'), [])
        self.assertEqual(ALT.findall('class="bg-indigo-600 text-slate-400"'),
                         ['bg-indigo-600', 'text-slate-400'])
