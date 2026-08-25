"""Die gebaute Schicht muss zu ihrer Quelle passen.

WARUM ES DIESEN WÄCHTER BRAUCHT

Seit E2.22 gibt es die Komponentenschicht dreimal:

  `core/templates/fw/_schicht.html`  Quelle — hier wird geändert.
  `static/css/schicht.src.css`       zum Lesen, mit Erklärungen.
  `static/css/schicht.css`           ausgeliefert, ohne Kommentare.

Damit entsteht dieselbe Lücke wie beim Tailwind-Bau in E0.2: Wer die Quelle
ändert und `python manage.py schicht_bauen` vergisst, hat eine **richtige
Quelle und eine falsche Anwendung**. Die Regeln stehen da, wirken aber nicht —
und niemand sieht es, weil die Datei ja existiert.

Der Vorlagen-Zähler merkt davon nichts: Er liest die Quelle, und die stimmt.

WAS DIESER TEST PRÜFT

Dass beide gebauten Dateien Zeichen für Zeichen dem entsprechen, was der
Befehl aus der Quelle erzeugen würde. Er ruft dafür dieselbe Funktion auf, die
auch der Befehl benutzt — keine zweite Fassung derselben Logik, die
auseinanderlaufen kann.
"""
import pathlib

from django.conf import settings
from django.test import SimpleTestCase

from core.management.commands.schicht_bauen import (
    KOPF_SRC, MIT, OHNE, QUELLE, css_aus_quelle, ohne_kommentare)

WURZEL = pathlib.Path(settings.BASE_DIR)


class SchichtGebautTest(SimpleTestCase):

    def _soll(self):
        css = css_aus_quelle((WURZEL / QUELLE).read_text(encoding='utf-8'))
        return KOPF_SRC + css, ohne_kommentare(css)

    def test_die_ausgelieferte_datei_ist_aktuell(self):
        _mit, soll = self._soll()
        ist = (WURZEL / OHNE).read_text(encoding='utf-8')
        self.assertEqual(
            ist, soll,
            f'{OHNE} entspricht nicht mehr der Quelle. Die Anwendung zeigt '
            f'eine ältere Schicht, während {QUELLE} die neue behauptet — '
            f'`python manage.py schicht_bauen` ausführen.')

    def test_die_lesbare_fassung_ist_aktuell(self):
        soll, _ohne = self._soll()
        ist = (WURZEL / MIT).read_text(encoding='utf-8')
        self.assertEqual(
            ist, soll,
            f'{MIT} ist veraltet. Sie ist die Fassung zum Nachlesen; läuft '
            f'sie der Quelle davon, führt sie den Nächsten in die Irre.')

    def test_die_ausgelieferte_fassung_traegt_keine_kommentare(self):
        """Der eigentliche Zweck der Trennung.

        CSS-Kommentare werden ausgeliefert. In der eingebetteten Fassung waren
        es 25 KB Erklärtext bei JEDEM Seitenaufruf — und jedes Wort darin stand
        im Quelltext auch der öffentlichen Seiten. Zwei Sicherheitstests haben
        deshalb schon einmal angeschlagen.
        """
        ist = (WURZEL / OHNE).read_text(encoding='utf-8')
        self.assertNotIn('/*', ist, 'Kommentare in der ausgelieferten Datei.')
        self.assertGreater(len(ist), 10000,
                           'Die ausgelieferte Datei ist verdächtig klein.')

    def test_die_ersparnis_ist_messbar(self):
        """Gegenprobe: Ohne echte Ersparnis wäre die Trennung Aufwand ohne Nutzen."""
        mit, ohne = self._soll()
        self.assertGreater(
            len(mit) - len(ohne), 15000,
            'Die Trennung spart kaum etwas — dann ist sie den zusätzlichen '
            'Bauschritt nicht wert.')

    def test_keine_vorlage_bettet_die_schicht_noch_ein(self):
        """Sonst liefe beides parallel: statische Datei UND 61 KB im HTML."""
        funde = []
        for p in (WURZEL / 'core' / 'templates').rglob('*.html'):
            if p.name in ('_schicht.html', '_schicht_link.html'):
                continue
            if "include 'fw/_schicht.html'" in p.read_text(encoding='utf-8'):
                funde.append(p.relative_to(WURZEL).as_posix())
        self.assertEqual(
            funde, [],
            f'Diese Vorlagen betten die Schicht noch ein: {funde}. '
            f'Sie gehört über `fw/_schicht_link.html` geladen.')
