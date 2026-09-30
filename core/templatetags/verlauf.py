"""Die Verlaufslinie einer Kennzahl (konzept-v8, `spark()` im Mockup).

Serverseitig als SVG gerendert: Die Zahlen stehen schon im Kontext, und eine
Linie, die erst ein Skript zeichnet, fehlt im Druck und ohne JavaScript.
"""
from django import template
from django.utils.html import format_html

register = template.Library()

BREITE, HOEHE, RAND = 96, 34, 3


@register.filter
def verlaufslinie(werte, ton=''):
    """`{{ k.verlauf|verlaufslinie:k.ton }}` — leer bei weniger als zwei Werten.

    Die Farbe kommt aus der Klasse (`good`/`crit`, sonst Marke) über
    `currentColor`; so schaltet sie im Dunkelmodus mit.
    """
    try:
        werte = [float(w) for w in (werte or [])]
    except (TypeError, ValueError):
        return ''
    if len(werte) < 2:
        return ''
    klein, gross = min(werte), max(werte)
    spanne = (gross - klein) or 1.0
    punkte = [(RAND + i * (BREITE - 2 * RAND) / (len(werte) - 1),
               HOEHE - RAND - (w - klein) / spanne * (HOEHE - 2 * RAND))
              for i, w in enumerate(werte)]
    linie = ' '.join(f'{x:.1f},{y:.1f}' for x, y in punkte)
    fx, fy = punkte[-1]
    flaeche = f'{RAND},{HOEHE - RAND} {linie} {BREITE - RAND},{HOEHE - RAND}'
    return format_html(
        '<svg class="fw-spark {}" viewBox="0 0 {} {}" aria-hidden="true">'
        '<polygon points="{}" fill="currentColor" opacity=".10"/>'
        '<polyline points="{}" fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        '<circle cx="{}" cy="{}" r="2.8" fill="currentColor"/></svg>',
        ton if ton in ('good', 'crit') else '', BREITE, HOEHE, flaeche, linie, f'{fx:.1f}', f'{fy:.1f}')
