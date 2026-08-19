"""Die umgestellten Aktenseiten muessen strukturell heil sein.

WARUM

Beim Umbau des Aktenkopfs am 19.08.2026 blieb ein `</div>` aus: `fw-akte-oben`
wurde nie geschlossen, und die Kennzahlenleiste sass dadurch **innerhalb** des
Kopfblocks statt darunter. Django rendert das anstandslos, der Browser repariert
es nach eigenem Gutduenken, und kein einziger der damals 205 Tests merkte es.

Ein blosses Zaehlen von `<div>` gegen `</div>` findet nur die Anzahl, nicht die
Verschachtelung. Deshalb laeuft hier ein echter Parser darueber.
"""
import pathlib
import re
from html.parser import HTMLParser

from django.test import TestCase

from faelle.test_reiter_panels import TEMPLATES, UMGESTELLT, WURZEL

#: Tags, die ohne schliessendes Gegenstueck vorkommen duerfen.
LEER = {'br', 'img', 'input', 'hr', 'meta', 'link', 'i', 'source', 'path'}


class _Pruefer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stapel = []
        self.fehler = []

    def handle_starttag(self, tag, attrs):
        if tag not in LEER:
            self.stapel.append(tag)

    def handle_endtag(self, tag):
        if tag in LEER:
            return
        if self.stapel and self.stapel[-1] == tag:
            self.stapel.pop()
        elif tag in self.stapel:
            i = self.stapel.index(tag)
            self.fehler.append(
                f'</{tag}> schliesst uebersprungene Tags: {self.stapel[i + 1:]}')
            del self.stapel[i:]
        else:
            self.fehler.append(f'</{tag}> ohne oeffnendes Tag')


def pruefen(pfad):
    roh = (WURZEL / pfad).read_text(encoding='utf-8')
    # Django-Syntax entfernen: Der Parser soll HTML sehen, keine Template-Tags.
    rein = re.sub(r'\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}', '', roh, flags=re.S)
    p = _Pruefer()
    p.feed(rein)
    return p.stapel, p.fehler


class StrukturTests(TestCase):
    def test_umgestellte_seiten_sind_ausbalanciert(self):
        for typ in sorted(UMGESTELLT):
            pfad = TEMPLATES[typ][0]
            offen, fehler = pruefen(pfad)
            with self.subTest(typ=typ):
                self.assertEqual(
                    offen, [],
                    f'{pfad}: nie geschlossen — {", ".join(offen)}')
                self.assertEqual(
                    fehler, [],
                    f'{pfad}: falsch verschachtelt — {"; ".join(fehler[:3])}')

    def test_der_pruefer_erkennt_ein_fehlendes_tag(self):
        """Gegenprobe. Ein Pruefer, der nie anschlaegt, besteht jede Datei."""
        p = _Pruefer()
        p.feed('<div><span>Text</div>')
        self.assertTrue(p.stapel or p.fehler)
