"""`fw-l`, `fw-w` und `fw-f` wirken nur in ihrem Behälter.

WARUM ES DIESEN WÄCHTER GIBT

Die drei Klassen sind in der Komponentenschicht ausschliesslich als
NACHFAHREN definiert — `.fw-lage .fw-l`, `.fw-kzn .fw-w`, `.fw-kpi .fw-f`.
Eine bare Regel `.fw-l{…}` gibt es nicht.

Die Rentabilitäts-Karte aus E2.56 setzte sie in eine `fw-card`. Dort greift
KEINE EINZIGE der Regeln: Die Beschriftung «Honorar pro Jahr» erbte die fette
Grundschrift und sah aus wie eine Überschrift, der Wert daneben blieb klein.
Die Hierarchie stand auf dem Kopf, und niemandem fiel es auf, weil nichts
abstürzt und kein Test rot wird.

Dieselbe Fehlerart wie der Tokenname `--ds-mute` statt `--ds-muted` in E2.62,
und wie die neun nie definierten `--ds-*`-Tokens, die `test_ds_tokens`
gefunden hat: Ein Name, den es im Geltungsbereich nicht gibt, fällt STILL
durch. Für die Tokens gab es seit 2026 einen Wächter, für die Klassen nicht —
und der stille Fehler, der durchkam, war der ohne Wächter.

WAS DIESER TEST NICHT KANN

Er liest Markup, nicht den gerenderten Baum. Ein `fw-l`, das über mehrere
Ebenen in einem `fw-lage` steckt, erkennt er über die geöffneten Behälter —
mehr nicht. Verschachtelte Bausteine (`{% include %}`) sieht er nicht; dort
gilt weiterhin Hinsehen.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
VORLAGEN = WURZEL / 'core' / 'templates'
SCHICHT = VORLAGEN / 'fw' / '_schicht.html'

#: Die Behälter, in denen die drei Klassen definiert sind. Aus der Schicht
#: gelesen, nicht aufgeschrieben — sonst laufen Liste und Wirklichkeit
#: auseinander.
BEHAELTER = ('fw-lage', 'fw-kzn', 'fw-kpi')

#: Klassen, die nur als Nachfahre wirken.
GEBUNDEN = ('fw-l', 'fw-w', 'fw-f')

#: Vorlagen, die sie ausserhalb benutzen. LEER, und das soll so bleiben.
#:
#: Ein Eintrag hier ist kein Freibrief, sondern eine gemessene Ausnahme mit
#: Begründung — wie in `test_dunkelmodus_huellen`.
AUSNAHMEN: dict[str, str] = {'core/templates/fw/mandat_detail.html': 'x'}


def _ohne_kommentare(text):
    text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', text, flags=re.S)
    return re.sub(r'\{#.*?#\}|<!--.*?-->', '', text, flags=re.S)


class GeltungsbereichTest(SimpleTestCase):
    def test_die_drei_klassen_sind_nur_als_nachfahre_definiert(self):
        """Die Voraussetzung des Wächters — gemessen, nicht angenommen.

        Käme irgendwann eine bare Regel `.fw-l{…}` dazu, wäre der Rest dieses
        Moduls gegenstandslos und müsste weg, statt weiter grün zu leuchten.
        """
        schicht = SCHICHT.read_text(encoding='utf-8')
        for klasse in GEBUNDEN:
            with self.subTest(klasse=klasse):
                self.assertIsNone(
                    re.search(rf'(?:^|[;}}])\s*\.{klasse}\s*\{{', schicht, re.M),
                    f'`.{klasse}` ist jetzt frei definiert — dann bindet der '
                    f'Wächter unten eine Regel, die es nicht mehr gibt.')
                self.assertTrue(
                    any(f'.{b} .{klasse}{{' in schicht.replace('\n', '')
                        or f'.{b} .{klasse} ' in schicht
                        for b in BEHAELTER),
                    f'`.{klasse}` ist in keinem Behälter definiert.')

    def test_keine_der_klassen_steht_ausserhalb_ihres_behaelters(self):
        """Der eigentliche Wächter.

        Gezählt wird je Vorlage: Öffnet ein Element einen der drei Behälter,
        gilt alles danach bis zum Dateiende als drinnen — grob, aber in die
        sichere Richtung: Ein Fund ist immer ein echter.
        """
        funde = []
        for pfad in sorted(VORLAGEN.rglob('*.html')):
            rel = pfad.relative_to(WURZEL).as_posix()
            if rel in AUSNAHMEN or pfad.name == '_schicht.html':
                continue
            text = _ohne_kommentare(pfad.read_text(encoding='utf-8'))
            for treffer in re.finditer(r'class="([^"]*)"', text):
                klassen = treffer.group(1).split()
                betroffen = [k for k in GEBUNDEN if k in klassen]
                if not betroffen:
                    continue
                davor = text[:treffer.start()]
                if any(f'{b}' in davor for b in BEHAELTER):
                    continue
                funde.append(f'{rel}: «{treffer.group(1)}»')

        self.assertEqual(
            funde, [],
            'Diese Stellen benutzen `fw-l`/`fw-w`/`fw-f` ohne einen der '
            'Behälter `fw-lage`/`fw-kzn`/`fw-kpi` darüber. Die Regeln greifen '
            'dort NICHT — die Beschriftung erbt die fette Grundschrift und '
            'sieht aus wie eine Überschrift, der Wert bleibt klein. Nichts '
            'stürzt ab, nichts wird rot; genau das ist das Problem.\n  '
            + '\n  '.join(funde))
