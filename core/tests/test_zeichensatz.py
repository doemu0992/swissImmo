"""Der Zeichensatz darf nicht weiter wachsen.

DER BEFUND (B8, Entscheid D5)

Gemessen: **207 verschiedene Font-Awesome-Klassen in 1136 Vorkommen**, davon
90 Zeichen genau einmal benutzt.

Das ist kein Zeichensatz, sondern eine Sammlung. `fa-trash` und `fa-trash-can`
stehen für dasselbe, ebenso `fa-list`/`fa-list-ol` und `fa-gauge`/
`fa-gauge-high`. Wer eine neue Seite baut, wählt aus zweitausend Zeichen und
trifft nie dieselbe Wahl wie der Vorgänger.

`docs/ZEICHEN.md` legt achtundvierzig Zeichen mit fester Bedeutung fest, plus
zwei, für die eine Entscheidung aussteht.

AN DREI ORTEN, NICHT AN EINEM

Ein Zeichen wird nicht nur in einer Vorlage gewählt. `core/views/fw/`
schreibt Kachellisten, Termin-Arten und Gewerke als Zeichenkette in den
Kontext (`'icon': 'fa-plug'`), und die Admin-Vorlagen unter `templates/`
haben eigene. Wer nur `core/templates/` misst, sieht 190 statt 207 — und
neue Zeichen liessen sich unbemerkt in View-Code nachlegen, wo die Sperre
nicht hinschaut.

WAS DIESER WÄCHTER TUT — UND WAS NICHT

Er stellt **nicht** um. Die Umstellung von 207 auf 42 ist Handarbeit mit
Sichtprüfung; ein Skript, das Zeichen nach Namensähnlichkeit ersetzt, trifft
genau die Fälle falsch, auf die es ankommt (`check` heisst je nach Ort
»erledigt« oder »speichern«).

Er hält die Zahl fest, damit sie **nicht weiter wächst**, und er prüft, dass
die Tabelle vollständig ist: Jede heute benutzte Klasse muss dort einer
Bedeutung zugeordnet sein — oder ausdrücklich unter »Noch ohne Bedeutung«
stehen. Sonst beschreibt die Tabelle einen Wunschzustand statt den Weg
dorthin.

Verglichen wird gegen die **genannten Namen in Rückstrichen**, nicht gegen
den Fliesstext. Der naheliegende Weg (`name in text`) lässt still durch, was
Namensteil eines anderen Eintrags ist: `fa-arrow-right` gilt dann als
abgedeckt, weil `arrow-right-long` in der Tabelle steht — und `fa-file`
wegen `file-lines`, `fa-tree` wegen `folder-tree`, `fa-code` wegen
`code-branch`. So blieben 11 der 23 fehlenden Klassen unbemerkt, und die
Prüfung wäre grün, während die Tabelle unvollständig ist.

Dieselbe Sperrklinke wie bei den Farbklassen in E2.1 — die hat 7'437 auf 325
gebracht, eine Etappe nach der anderen.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
TABELLE = WURZEL / 'docs' / 'ZEICHEN.md'

#: Gemessen bei Anlage der Tabelle (E2.35). Die Zahl darf sinken, nicht steigen.
#: E2.39: 207 -> 78. Die Vorlagen sind umgestellt; was bleibt, steht in
#: PYTHON-CODE (Kachellisten, Termin-Arten, Gewerke) und in den
#: Admin-Vorlagen. Das ist Schritt 4 und braucht einen anderen Weg: Dort
#: ist das Zeichen ein Datenwert, kein Markup.
#: 79 statt 78: Vier Zeichen sind in E2.39 ZURUECKGENOMMEN worden.
#: `stamp`, `bell`, `code` und `trend` stehen in `docs/ZEICHEN.md` unter
#: «Noch ohne Bedeutung» — bewusst nicht zugeordnet. Die Umstellung hat
#: sie beim Sortieren erfunden; genau davor warnt die Tabelle. Sie
#: bleiben bei Font Awesome, bis jemand die Bedeutung ENTSCHEIDET.
#: E2.41: 79 -> 11. Die DATENWERTE im Python-Code sind umgestellt
#: (Kachellisten, Termin-Arten, Gewerke) und die 29 Einsetzstellen in den
#: Vorlagen auf `{% templatetag openblock %} zeichen_wert … {% templatetag closeblock %}`.
#:
#: E2.43: 11 -> 3. Die Admin-Vorlage `dashboard_stats.html` ist ENTFERNT —
#: toter Code: kein Aufrufer, doppelt vorhanden, Font Awesome nie geladen.
#: Damit fielen sieben Zeichen und 82 Farbklassen weg, die niemand je sah.
#:
#: DIE DREI VERBLEIBENDEN, NACHGEZAEHLT — nicht die, die E2.43 nannte
#: («`share` und `share-from-square`»: das sind zwei Namen fuer drei
#: Vorkommen, und `fa-share` steht im Bestand gar nicht mehr):
#:
#:   fa-share-from-square   core/views/fw/dashboard.py — die letzte offene
#:                          Frage aus E2.40 («Weiterverrechnen» ist
#:                          Fachlogik, kein Teilen).
#:   fa-buildings           modern_base.html, nur im ERKLAERTEXT eines
#:                          Kommentarblocks. Kein gerendertes Zeichen; die
#:                          Sperrklinke zaehlt Erwaehnungen mit, damit auch
#:                          sie nicht wachsen.
#:
#: Der dritte, `fa-circle-notch` in fw/base.html, ist in der Gegenpruefung zu
#: E2.43 mit umgestellt worden — E2.42 hatte ihn uebersehen, und das
#: JavaScript daneben suchte `i.fa-solid`, was es seit E2.39 nicht mehr gibt.
#: KEIN Absendeknopf der Anwendung zeigte darum noch einen Spinner. Deshalb
#: steht hier 2, nicht die von E2.43 genannte 3.
STAND_ZEICHEN = 2
STAND_VORKOMMEN = 2

#: Anzahl Zeichen mit fester Bedeutung, aus `docs/ZEICHEN.md`.
#:
#: D5 sagt «~40». Es sind 42 geworden: `einstellungen` fehlte als Bedeutung
#: (`gear`), und die Trendpfeile zeigen die Richtung einer Zahl, nicht eine
#: Bewegung durch die Anwendung — unter `weiter`/`zurueck` gezwungen haetten
#: sie an zwei Orten Verschiedenes geheissen.
#: 45 seit E2.40. Vier Zeichen sind aus der Liste «Noch ohne Bedeutung»
#: nach oben gewandert, weil eine ENTSCHEIDUNG getroffen wurde:
#: `freigeben`, `storno`, `meldung`, `trend`. Keines liess sich auf ein
#: bestehendes abbilden — und ein falsch zugeordnetes Zeichen ist
#: schlechter als ein zusaetzliches.
#:
#: 46 seit der Gegenpruefung zu E2.40: `schliessen` fehlte. Die Umstellung
#: setzte `xmark` auf Schliessen-Knoepfen auf `mehr`, E2.38 eines davon auf
#: `loeschen` — ein Knopf mit Papierkorb, der nichts loescht. Wegklicken ist
#: eine eigene Bedeutung.
#:
#: D5 sagt «~40». Die Tilde traegt inzwischen sechs Zeichen; wer die
#: naechsten dazunimmt, sollte begruenden, warum die Bedeutung fehlte.
ZIEL_ZEICHEN = 48

#: Klassen, die in Gebrauch sind und bewusst noch keiner Bedeutung zugeordnet
#: wurden. Diese Liste darf schrumpfen, nicht wachsen — sonst wird «noch offen»
#: zum bequemen Ablageort fuer jedes neue Zeichen.
#: E2.40 hat `stamp`, `rotate-left` und `bell` entschieden (`freigeben`,
#: `storno`, `meldung`). Sie standen danach in BEIDEN Listen — entschieden
#: oben, offen unten — und dieser Waechter blieb gruen, weil er nur prueft,
#: dass jeder Name irgendwo im Dokument vorkommt. Aus der offenen Liste
#: entfernt; hier nachgefuehrt.
#: `code` ist in E2.42 ENTSCHIEDEN worden — nicht weil die Frage geklaert
#: waere, ob Rohdaten ein Zeichen tragen sollen, sondern weil die
#: Alternative war, fuer EINE Fundstelle 89 KB CSS und 119 KB Schrift zu
#: laden. Manche Fragen entscheidet der Preis.
OFFEN = ('share', 'share-from-square')
STAND_OFFEN = 2

#: In Vorlagen steht die Klasse hinter dem Stil: `class="fa-solid fa-plug"`.
MUSTER_VORLAGE = re.compile(r'fa-(?:solid|regular|brands)\s+(fa-[a-z0-9-]+)')
#: In Python steht sie allein in Anfuehrungszeichen: `'icon': 'fa-plug'`.
MUSTER_PYTHON = re.compile(r"""['"](fa-[a-z0-9-]+)['"]""")


def _quellen():
    """Alle Dateien, in denen ein Zeichen *gewaehlt* wird.

    Testdateien bleiben aussen vor: Was dort in einer Vorrichtung oder einer
    Zusicherung steht, ist keine Wahl der Anwendung.
    """
    # `templates/` gab es bis E2.43 — dort lag genau eine Datei, die tote
    # Admin-Statistik. Der Ordner ist mit ihr verschwunden; der Eintrag
    # bleibt, weil `DIRS` weiter dorthin zeigt und jemand ihn wieder
    # befuellen kann. `rglob` auf einen fehlenden Pfad liefert nichts.
    for ordner in ('core/templates', 'templates'):
        yield from ((p, MUSTER_VORLAGE) for p in sorted((WURZEL / ordner).rglob('*.html')))
    for p in sorted(WURZEL.rglob('*.py')):
        teile = p.parts
        if 'node_modules' in teile or 'migrations' in teile or p.name.startswith('test_'):
            continue
        yield p, MUSTER_PYTHON


def _zeichen_im_bestand():
    gefunden = {}
    for pfad, muster in _quellen():
        for treffer in muster.findall(pfad.read_text(encoding='utf-8')):
            gefunden[treffer] = gefunden.get(treffer, 0) + 1
    return gefunden


def _in_tabelle_genannt():
    """Die Namen, die in `docs/ZEICHEN.md` in Rückstrichen stehen.

    Genau diese gelten als abgedeckt — nicht jeder Namensteil im Fliesstext.
    """
    return set(re.findall(r'`([a-z0-9-]+)`', TABELLE.read_text(encoding='utf-8')))


class ZeichensatzTest(SimpleTestCase):

    def test_die_vielfalt_waechst_nicht(self):
        zeichen = _zeichen_im_bestand()
        self.assertLessEqual(
            len(zeichen), STAND_ZEICHEN,
            f'Es sind {len(zeichen)} verschiedene Zeichen geworden (Stand: '
            f'{STAND_ZEICHEN}). Wer ein neues braucht, trägt es in '
            f'docs/ZEICHEN.md ein — mit Begründung, warum keines der '
            f'zweiundvierzig passt.')

    def test_die_vorkommen_wachsen_nicht(self):
        zeichen = _zeichen_im_bestand()
        self.assertLessEqual(
            sum(zeichen.values()), STAND_VORKOMMEN,
            f'{sum(zeichen.values())} Vorkommen (Stand: {STAND_VORKOMMEN}).')

    def test_gesunkene_zahlen_werden_nachgefuehrt(self):
        """Sonst bliebe die Sperrklinke auf dem alten Stand stehen.

        Eine Obergrenze, die weit über dem Ist liegt, sperrt nichts: Sie
        erlaubt, das Erreichte wieder zu verlieren.
        """
        zeichen = _zeichen_im_bestand()
        self.assertGreaterEqual(
            len(zeichen), STAND_ZEICHEN - 5,
            f'Nur noch {len(zeichen)} Zeichen — bitte STAND_ZEICHEN auf '
            f'diesen Wert setzen, damit die Sperre wieder greift.')

    def test_die_tabelle_deckt_jedes_benutzte_zeichen_ab(self):
        """Sonst beschreibt sie einen Wunsch statt einen Weg.

        Jede heute benutzte Klasse muss in `docs/ZEICHEN.md` als Name in
        Rückstrichen vorkommen — in der Spalte »ersetzt heute« oder in der
        Liste »Noch ohne Bedeutung«. Wer eine neue einführt, ohne sie
        einzutragen, hinterlässt eine Lücke, die bei der Umstellung auffällt
        und dann geraten werden muss.
        """
        genannt = _in_tabelle_genannt()
        fehlend = sorted(k for k in _zeichen_im_bestand() if k[3:] not in genannt)
        self.assertEqual(
            fehlend, [],
            f'Diese Zeichen stehen nicht in docs/ZEICHEN.md: {fehlend[:12]}'
            + (f' (und {len(fehlend) - 12} weitere)' if len(fehlend) > 12 else '')
            + '\nBitte einer Bedeutung zuordnen oder unter »Noch ohne '
              'Bedeutung« aufnehmen.')

    def test_die_tabelle_nennt_zweiundvierzig_zeichen(self):
        """Die Zahl im Entscheid ist keine Schätzung.

        D5 sagt »~40 Zeichen«. Wird die Tabelle bei jeder Frage um eines
        länger, ist sie in einem Jahr wieder eine Sammlung.
        """
        text = TABELLE.read_text(encoding='utf-8')
        # Nur der Teil vor der Liste der ungeklaerten Zeichen — die hat
        # dieselbe Zeilenform, gehoert aber nicht zur Tabelle.
        marke = '## Noch ohne Bedeutung'
        self.assertIn(marke, text)
        text = text[:text.index(marke)]
        # Zeilen der Form `| `zeichen` | Bedeutung | ersetzt |`
        eintraege = re.findall(r'^\| `([a-z]+)` \|', text, re.M)
        self.assertEqual(
            len(eintraege), ZIEL_ZEICHEN,
            f'Die Tabelle führt {len(eintraege)} Zeichen statt '
            f'{ZIEL_ZEICHEN}: {eintraege}')
        self.assertEqual(
            len(set(eintraege)), len(eintraege),
            'Ein Zeichen steht zweimal in der Tabelle — dann hat es zwei '
            'Bedeutungen, und genau das soll die Tabelle verhindern.')

    def test_die_offene_liste_waechst_nicht(self):
        """»Noch zu entscheiden« darf kein Ablageort werden.

        Sechs ungeklärte Zeichen sind ein ehrlicher Rest. Wächst die Liste
        mit jedem neuen Zeichen mit, ist die Tabelle wieder eine Sammlung —
        nur mit einer Überschrift davor.
        """
        self.assertEqual(len(OFFEN), STAND_OFFEN)
        genannt = _in_tabelle_genannt()
        for name in OFFEN:
            self.assertIn(name, genannt,
                          f'`{name}` steht nicht mehr in docs/ZEICHEN.md — '
                          f'wenn es zugeordnet wurde, hier austragen.')

    def test_die_messung_findet_ueberhaupt_etwas(self):
        """Gegenprobe: Ein leeres Ergebnis wäre trivial grün."""
        zeichen = _zeichen_im_bestand()
        self.assertGreater(len(zeichen), 1,
                           'Die Suche findet fast nichts — dann prüfen die '
                           'Tests oben nichts.')
        self.assertGreater(sum(zeichen.values()), 1)

    def test_auch_in_python_gewaehlte_zeichen_werden_gesehen(self):
        """Sonst wäre die Sperre an der Stelle blind, wo sie gebraucht wird.

        17 Klassen stehen in keiner Vorlage, sondern nur in View-Code —
        `fa-plug` für »Integrationen«, `fa-paint-roller` für das Gewerk
        Maler. Misst der Wächter nur `core/templates/`, lassen sich neue
        Zeichen dort beliebig nachlegen.
        """
        zeichen = _zeichen_im_bestand()
        nur_vorlagen = {}
        for p in sorted((WURZEL / 'core' / 'templates').rglob('*.html')):
            for t in MUSTER_VORLAGE.findall(p.read_text(encoding='utf-8')):
                nur_vorlagen[t] = nur_vorlagen.get(t, 0) + 1
        self.assertGreater(
            len(zeichen), len(nur_vorlagen),
            'Der Wächter sieht nicht mehr als core/templates/ — dann greift '
            'er nicht für Zeichen, die in View-Code gewählt werden.')
        # KEINE festen Beispielwerte mehr.
        #
        # Bis E2.41 stand hier `assertIn('fa-plug', …)`. Der Test belegte die
        # Erfassung an einem konkreten Wert — und wurde rot, als genau dieser
        # Wert umgestellt wurde. Er meldete damit einen FORTSCHRITT als
        # Fehler.
        #
        # Geprueft wird jetzt die Aussage selbst: Es gibt Zeichen, die NUR in
        # Python gewaehlt werden. Solange das stimmt, greift der Waechter
        # dort; wenn nicht mehr, ist er ueberfluessig und sagt es.
        nur_python = set(zeichen) - set(nur_vorlagen)
        self.assertTrue(
            nur_python,
            'Kein Zeichen wird mehr ausschliesslich in Python gewaehlt. '
            'Entweder ist Schritt 4 fertig — dann darf dieser Test weg — '
            'oder die Suche findet den Python-Teil nicht mehr.')
