"""Was am Tisch richtig ist, kann gestapelt falsch sein.

WARUM ES DIESEN TEST GIBT

Am 20.08.2026 meldete der Nutzer an der Objektliste einer Liegenschaft: «Fehler
beim Parkplatz.» Der Parkplatz stand zuunterst, und als einziger Eintrag fehlten
ihm im Innern alle Trennlinien — Typ, Fläche, Status und Mieter liefen ineinander,
während die Wohnungen darüber sauber getrennt waren.

Die Ursache steht nicht in der Liegenschaftsvorlage, sondern in der
Komponentenschicht:

    table.fw-table tbody tr:last-child td { border-bottom: 0 }

Am Tisch ist das richtig — die unterste Tabellenzeile braucht keine
Abschlusslinie. Unter 768 px stapelt `fwTabellenStapeln()` die Tabelle aber zu
Karten: Aus jeder ZELLE wird eine eigene Zeile. Dieselbe Regel löscht dann die
Linien ZWISCHEN den Feldern — aber nur beim letzten Eintrag, weshalb der Fehler
je nach Datenlage mal auftrat und mal nicht.

WAS DIESER TEST HÄLT

Beide Hälften. Er prüft, dass die Desktop-Regel noch da ist UND dass die mobile
Gegenregel sie zurücknimmt. Fällt die Desktop-Regel eines Tages weg, meldet er
die Gegenregel als überflüssig, statt sie stumm liegenzulassen — eine tote
Kompensation ist genauso irreführend wie eine fehlende.

WAS ER NICHT KANN

Er liest CSS als Text. Ob der Browser die Linie am Ende zeichnet, sagt er nicht;
dafür bräuchte es ein echtes Rendering. Er hält fest, dass die beiden Regeln
zusammen gepflegt werden — genau das war der Fehler.
"""
import pathlib
import re

from django.test import TestCase
from ._stil import ausgelieferter_stil


# Seit E2.10 stehen die Regeln in `fw/_schicht.html` (die Aussenseiten sollen
# sie auch sehen); `base.html` traegt weiterhin das Skript, das die Zellen
# beschriftet. Dieser Waechter braucht BEIDE Seiten derselben Sache — die
# Media-Query hier, die Beschriftung dort.
BASE = pathlib.Path('core/templates/fw/_schicht.html')
SKRIPT = pathlib.Path('core/templates/fw/base.html')

#: Die Desktop-Regel, die gestapelt zum Problem wird.
DESKTOP = re.compile(
    r'table\.fw-table\s+tbody\s+tr:last-child\s+td\s*\{[^}]*border-bottom\s*:\s*0')

#: Die Gegenregel. Muss INNERHALB der Stapel-Mediaquery stehen — ausserhalb
#: würde sie die Desktop-Regel auch am Tisch aufheben und dort eine Linie
#: zuviel zeichnen.
MOBIL = re.compile(
    r'table\[data-stack\]\.fw-table\s+tbody\s+tr:last-child\s+td\s*\{[^}]*'
    r'border-bottom\s*:\s*1px')


def ohne_kommentare(css):
    """CSS-Kommentare entfernen.

    Notwendig, nicht kosmetisch: Der Kommentar zur Gegenregel ZITIERT die
    Desktop-Regel, um sie zu erklären. Die erste Fassung dieses Tests suchte im
    Rohtext — und fand beim Löschen der echten Regel weiterhin das Zitat.
    `test_die_kompensation_ist_nicht_tot` blieb dadurch grün (Gegenprobe G3 vom
    20.08.2026). Ein Test, der die Erklärung eines Sachverhalts für den
    Sachverhalt hält, prüft nichts.
    """
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def stapel_mediaquery(quelle):
    """Der Inhalt des `@media (max-width: 767px)`-Blocks, in dem gestapelt wird."""
    start = quelle.find('@media (max-width: 767px)')
    if start < 0:
        return ''
    auf = quelle.index('{', start)
    tiefe, i = 1, auf + 1
    while tiefe and i < len(quelle):
        if quelle[i] == '{':
            tiefe += 1
        elif quelle[i] == '}':
            tiefe -= 1
        i += 1
    return quelle[auf + 1:i - 1]


class GestapelteTabellenTests(TestCase):
    def setUp(self):
        self.quelle = ohne_kommentare(BASE.read_text(encoding='utf-8'))

    def test_die_stapel_mediaquery_wird_gefunden(self):
        """Ohne sie prüfen die Tests darunter nichts.

        Wird der Umbruchpunkt geändert (767 px), schlägt dieser Test an —
        besser als zwei stumm grüne Prüfungen auf einem leeren Text.
        """
        self.assertTrue(stapel_mediaquery(self.quelle).strip(),
                        'Der Stapel-Block wurde nicht gefunden — Umbruchpunkt '
                        'geändert? Dann gehören die Muster hier nachgezogen.')

    def test_die_letzte_karte_behaelt_ihre_trennlinien(self):
        block = stapel_mediaquery(self.quelle)
        self.assertTrue(
            MOBIL.search(block),
            'Im gestapelten Zustand fehlt die Gegenregel zu '
            '«tbody tr:last-child td {border-bottom:0}». Ohne sie verliert der '
            'UNTERSTE Eintrag jeder Tabelle auf dem Handy alle Trennlinien '
            'zwischen seinen Feldern — real gemeldet an einem Parkplatz, der '
            'zuunterst in der Objektliste stand.')

    def test_die_gegenregel_steht_nicht_ausserhalb(self):
        """Ausserhalb der Mediaquery zöge sie am Tisch eine Linie zuviel."""
        ausserhalb = self.quelle.replace(stapel_mediaquery(self.quelle), '')
        self.assertIsNone(
            MOBIL.search(ausserhalb),
            'Die Gegenregel steht ausserhalb des Stapel-Blocks und wirkt damit '
            'auch am Tisch — dort bekäme die unterste Tabellenzeile eine '
            'Abschlusslinie, die sie nicht haben soll.')

    def test_die_kompensation_ist_nicht_tot(self):
        """Gegenprobe in die andere Richtung.

        Verschwindet die Desktop-Regel, kompensiert die mobile Regel nichts
        mehr und gehört ebenfalls weg. Eine Regel, die einen Fehler ausgleicht,
        den es nicht mehr gibt, liest sich beim nächsten Mal als Absicht.
        """
        self.assertTrue(
            DESKTOP.search(self.quelle),
            'Die Desktop-Regel «tbody tr:last-child td {border-bottom:0}» ist '
            'weg. Dann ist die mobile Gegenregel überflüssig — beide zusammen '
            'aufräumen, nicht nur eine.')

    def test_kommentare_zaehlen_nicht_als_regel(self):
        """Gegenprobe zu genau dem Fehler, den dieser Test selbst hatte."""
        zitat = ('/* siehe table.fw-table tbody tr:last-child td '
                 '{ border-bottom: 0 } weiter oben */')
        self.assertIsNone(DESKTOP.search(ohne_kommentare(zitat)))
        self.assertTrue(DESKTOP.search(zitat),
                        'Ohne Bereinigung traefe das Muster das Zitat — genau '
                        'so blieb die Pruefung anfangs blind.')

    def test_die_muster_treffen_wirklich_etwas(self):
        """Sonst wäre alles oben grün, weil nichts gesucht wird."""
        self.assertIsNone(DESKTOP.search('table.fw-table tbody td{border-bottom:1px}'))
        self.assertTrue(DESKTOP.search('table.fw-table tbody tr:last-child td{border-bottom:0}'))
        self.assertTrue(MOBIL.search(
            'table[data-stack].fw-table tbody tr:last-child td{border-bottom:1px solid red}'))
