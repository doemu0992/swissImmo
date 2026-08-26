"""Ein Zeichen aus dem Sprite einsetzen.

    {% load zeichen %}
    {% zeichen 'liegenschaft' %}
    {% zeichen 'kritisch' klasse='fw-kritisch' titel='Frist verletzt' %}

WARUM EIN BAUSTEIN UND NICHT EIN ROHES `<use>`

Damit ein falscher Name AUFFAELLT. `<use href="#z-tippfehler">` erzeugt ein
leeres Bild — die Seite sieht aus, als fehle nichts, und niemand merkt es.
Dieser Baustein prueft den Namen gegen `docs/ZEICHEN.md` und wirft im
Entwicklungsbetrieb; im Betrieb gibt er ein leeres Zeichen zurueck, damit eine
Seite nicht wegen eines Symbols abstuerzt.

GROESSE UND FARBE KOMMEN AUS DER UMGEBUNG

`width: 1em`, `stroke: currentColor` — ein Zeichen waechst mit der Schrift und
uebernimmt die Farbe der Zeile. Bei Font Awesome musste beides gesetzt werden,
und genau daraus entstanden die 1136 Vorkommen mit ihren
Groessen- und Farbklassen.

BARRIEREFREIHEIT

Ohne `titel` ist ein Zeichen `aria-hidden`: Es steht neben Text, der dasselbe
sagt, und ein Vorleseprogramm soll es nicht doppelt nennen. Mit `titel` wird
es zu einem `img` mit Beschriftung — fuer die Faelle, in denen es allein
steht (etwa ein Knopf ohne Beschriftung).
"""
import pathlib
import re

from django import template
from django.conf import settings
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_TABELLE = pathlib.Path(settings.BASE_DIR) / 'docs' / 'ZEICHEN.md'
_erlaubt = None


#: Ab hier stehen in `docs/ZEICHEN.md` die Zeichen, deren Bedeutung noch
#: NICHT entschieden ist. Sie haben dieselbe Zeilenform wie die Tabelle.
MARKE_OFFEN = '## Noch ohne Bedeutung'


def erlaubte_zeichen():
    """Die entschiedenen Namen aus `docs/ZEICHEN.md` — die Tabelle ist die Quelle.

    NUR BIS ZUR OFFENEN LISTE LESEN

    Die Liste »Noch ohne Bedeutung« benutzt dieselbe Zeilenform. Wer den
    ganzen Text durchsucht, laesst `stamp`, `bell` und `code` als gueltige
    Zeichen durch — und der Naechste entscheidet ihre Bedeutung durch
    Benutzung, statt sie einzutragen. `bell` steht heute schon fuer zwei
    Dinge; das ist der Grund, warum es dort steht.

    (Nebenbei traf die lose Lesart nur diese drei: `share, share-from-square`
    hat ein Komma, `rotate-left` einen Bindestrich, und beide fielen durch.
    Die Auswahl war also ein Zufall der Regex, keine Entscheidung.)
    """
    global _erlaubt
    if _erlaubt is None:
        text = _TABELLE.read_text(encoding='utf-8') if _TABELLE.exists() else ''
        if MARKE_OFFEN in text:
            text = text[:text.index(MARKE_OFFEN)]
        _erlaubt = set(re.findall(r'^\| `([a-z]+)` \|', text, re.M))
    return _erlaubt


@register.simple_tag
def zeichen(name, klasse='', titel=''):
    if name not in erlaubte_zeichen():
        if settings.DEBUG:
            raise template.TemplateSyntaxError(
                f'Unbekanntes Zeichen «{name}». Die erlaubten stehen in '
                f'docs/ZEICHEN.md; wer ein neues braucht, traegt es dort ein.')
        return mark_safe('')

    if titel:
        return format_html(
            '<svg class="fw-zeichen {}" role="img" aria-label="{}">'
            '<use href="#z-{}"/></svg>', klasse, titel, name)
    return format_html(
        '<svg class="fw-zeichen {}" aria-hidden="true"><use href="#z-{}"/></svg>',
        klasse, name)
