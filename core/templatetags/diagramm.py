"""Diagramme der Berichtsseite (konzept-v8, `pageBerichte` im Mockup).

Serverseitig gerendert wie `verlauf.py`: Die Zahlen stehen schon im Kontext,
und ein Diagramm, das erst ein Skript zeichnet, fehlt im Druck und ohne
JavaScript.

WARUM DIE BESCHRIFTUNG HTML IST UND NICHT SVG

Das Mockup legt Achsentexte ins SVG (`viewBox` 640 breit). Am Telefon wird
das SVG auf rund 330 Pixel verkleinert — und die Schrift mit ihm, auf etwa
sechs Pixel. Hier zeichnet das SVG nur Linie, Fläche und Raster (gedehnt mit
`preserveAspectRatio="none"`, Strichstärke fest über
`vector-effect="non-scaling-stroke"`); Achsen, Endwert und Punkt sind
HTML-Elemente, prozentual platziert. So bleibt die Schrift bei 390 Pixel
lesbar.

LÜCKEN BLEIBEN LÜCKEN. Ein Monat ohne Sollstellung ist `None` — die Linie
setzt dort aus, statt eine Null zu zeichnen (`None` heisst nicht erfasst).
"""
import math

from django import template
from django.utils.formats import number_format
from django.utils.html import format_html, format_html_join, mark_safe

from .chf import chf

register = template.Library()


def _zahl(w):
    try:
        return None if w is None else float(w)
    except (TypeError, ValueError):
        return None


def _prozent(w):
    # Nach Sprache formatiert («90,1» auf Deutsch) — wie die übrigen Prozente der Seite.
    return number_format(w, 1)


def _achse(klein, gross):
    """Runde Grenzen und Schrittweite, höchstens fünf Rasterlinien."""
    spanne = max(gross - klein, 1.0)
    for schritt in (1, 2, 5, 10, 20, 25, 50):
        if spanne / schritt <= 4:
            break
    unten = math.floor(klein / schritt) * schritt
    oben = math.ceil(gross / schritt) * schritt
    if oben == unten:
        oben = unten + schritt
    if unten == klein and unten - schritt >= 0:
        unten -= schritt           # die Linie liegt nicht auf dem Boden
    return unten, oben, schritt


@register.simple_tag
def linien_diagramm(werte, beschriftungen, titel='', einheit=' %'):
    """Linie über Monate. `werte` mit `None` für ungemessene Monate.

    Leer, wenn weniger als zwei Werte gemessen sind — die Vorlage zeigt dann
    ihren Leerzustand.
    """
    werte = [_zahl(w) for w in (werte or [])]
    gemessen = [w for w in werte if w is not None]
    if len(gemessen) < 2 or len(werte) < 2:
        return ''
    beschriftungen = list(beschriftungen or [])
    unten, oben, schritt = _achse(min(gemessen), max(gemessen))
    n = len(werte)

    def x(i):
        return i * 100 / (n - 1)

    def y(w):
        return (oben - w) / (oben - unten) * 100

    # Raster und y-Achse
    raster, y_text = [], []
    stufe = unten
    while stufe <= oben + 1e-9:
        raster.append(format_html(
            '<line x1="0" x2="100" y1="{0}" y2="{0}" class="fw-kurve-raster" '
            'vector-effect="non-scaling-stroke"/>', f'{y(stufe):.2f}'))
        y_text.append(format_html('<span class="fw-kurve-y" style="top:{}%">{}{}</span>',
                                  f'{y(stufe):.2f}', number_format(stufe, 0) if float(stufe).is_integer() else number_format(stufe, 1), einheit))
        stufe += schritt

    # Linie und Fläche je zusammenhängendem Stück
    stuecke, aktuell = [], []
    for i, w in enumerate(werte):
        if w is None:
            if aktuell:
                stuecke.append(aktuell)
            aktuell = []
        else:
            aktuell.append((x(i), y(w)))
    if aktuell:
        stuecke.append(aktuell)
    formen = []
    for st in stuecke:
        punkte = ' '.join(f'{px:.2f},{py:.2f}' for px, py in st)
        if len(st) > 1:
            formen.append(format_html(
                '<polygon points="{} {} {}" class="fw-kurve-flaeche"/>',
                f'{st[0][0]:.2f},100', punkte, f'{st[-1][0]:.2f},100'))
            formen.append(format_html(
                '<polyline points="{}" class="fw-kurve-strich" '
                'vector-effect="non-scaling-stroke"/>', punkte))

    # Endpunkt: der letzte gemessene Wert, beschriftet
    letzter = max(i for i, w in enumerate(werte) if w is not None)
    lw = werte[letzter]
    ende = format_html(
        '<span class="fw-kurve-punkt" style="left:{0}%;top:{1}%"></span>'
        '<span class="fw-kurve-wert" style="left:{0}%;top:{1}%">{2}{3}</span>',
        f'{x(letzter):.2f}', f'{y(lw):.2f}', _prozent(lw), einheit)

    # Treffer je Monat: Titel als Tooltip (die Zahl steht auch in der Tabelle)
    breite = 100 / (n - 1)
    treffer = format_html_join('', '<span class="fw-kurve-treffer" style="left:{}%;width:{}%" title="{}"></span>', (
        (f'{max(x(i) - breite / 2, 0):.2f}', f'{breite:.2f}',
         f'{beschriftungen[i] if i < len(beschriftungen) else ""}: '
         + (f'{_prozent(w)}{einheit}' if w is not None else '–'))
        for i, w in enumerate(werte)))

    x_text = format_html_join('', '<span class="fw-kurve-x{}" style="left:{}%">{}</span>', (
        (' fw-kurve-x-neben' if (n - 1 - i) % 2 else '', f'{x(i):.2f}', b)
        for i, b in enumerate(beschriftungen[:n])))

    return format_html(
        '<div class="fw-kurve" role="img" aria-label="{}">'
        '<div class="fw-kurve-plot">{}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{}{}</svg>'
        '{}{}</div>'
        '<div class="fw-kurve-achse">{}</div></div>',
        titel, mark_safe(''.join(y_text)), mark_safe(''.join(raster)),
        mark_safe(''.join(formen)), ende, treffer, x_text)


@register.simple_tag
def balken_liste(zeilen):
    """Horizontale Balken, grösster Wert = volle Spur.

    `zeilen`: Folge von dicts mit `lab`, `wert` (Decimal/Zahl) und optional
    `url`. Null zeigt «–» ohne Balken — der Wert ist gemessen, es gibt nur
    nichts zu zeigen.
    """
    zeilen = list(zeilen or [])
    if not zeilen:
        return ''
    groesster = max((_zahl(z.get('wert')) or 0 for z in zeilen), default=0) or 1
    teile = []
    for z in zeilen:
        w = _zahl(z.get('wert')) or 0
        lab = (format_html('<a href="{}" class="fw-hbar-lab">{}</a>', z['url'], z['lab'])
               if z.get('url') else format_html('<span class="fw-hbar-lab">{}</span>', z['lab']))
        spur = (format_html('<span class="fw-hbar-spur"><i style="width:{}%"></i></span>',
                            f'{w / groesster * 100:.1f}')
                if w > 0 else mark_safe('<span class="fw-hbar-spur"></span>'))
        wert = (format_html('<span class="fw-hbar-v">{}</span>', chf(z.get('wert'), 0)) if w > 0
                else mark_safe('<span class="fw-hbar-v fw-faint">–</span>'))
        teile.append(format_html('<div class="fw-hbar">{}{}{}</div>', lab, spur, wert))
    return mark_safe(''.join(teile))


@register.simple_tag
def cashflow_diagramm(ertrag, aufwand, beschriftungen, titel=''):
    """Zwei Linien über Monate: Ertrag (Marke, mit Fläche) und Aufwand (gestrichelt).

    Beide teilen EINE Achse in Tausend Franken — zwei Achsen würden jedes
    Verhältnis behaupten, das man will. `None`-Monate setzen aus. Leer, wenn
    keine zwei Ertragswerte vorliegen.
    """
    e = [_zahl(w) for w in (ertrag or [])]
    a = [_zahl(w) for w in (aufwand or [])]
    n = len(e)
    if n < 2 or sum(1 for w in e if w is not None) < 2:
        return ''
    a = (a + [None] * n)[:n]
    alle = [w for w in e + a if w is not None]
    unten, oben, schritt = _achse(min(0, min(alle)) / 1000, max(alle) / 1000)
    unten, oben = unten * 1000, oben * 1000
    schritt = schritt * 1000
    beschriftungen = list(beschriftungen or [])

    def x(i):
        return i * 100 / (n - 1)

    def y(w):
        return (oben - w) / (oben - unten) * 100

    raster, y_text, stufe = [], [], unten
    while stufe <= oben + 1e-6:
        raster.append(format_html('<line x1="0" x2="100" y1="{0}" y2="{0}" class="fw-kurve-raster" '
                                  'vector-effect="non-scaling-stroke"/>', f'{y(stufe):.2f}'))
        y_text.append(format_html('<span class="fw-kurve-y" style="top:{}%">{}k</span>',
                                  f'{y(stufe):.2f}', number_format(round(stufe / 1000), 0)))
        stufe += schritt

    def stuecke_von(reihe):
        out, aktuell = [], []
        for i, w in enumerate(reihe):
            if w is None:
                if aktuell:
                    out.append(aktuell)
                aktuell = []
            else:
                aktuell.append((x(i), y(w)))
        if aktuell:
            out.append(aktuell)
        return out

    formen = []
    for st in stuecke_von(e):
        punkte = ' '.join(f'{px:.2f},{py:.2f}' for px, py in st)
        if len(st) > 1:
            formen.append(format_html('<polygon points="{} {} {}" class="fw-kurve-flaeche"/>',
                                      f'{st[0][0]:.2f},{y(max(unten, 0)):.2f}', punkte,
                                      f'{st[-1][0]:.2f},{y(max(unten, 0)):.2f}'))
            formen.append(format_html('<polyline points="{}" class="fw-kurve-strich" '
                                      'vector-effect="non-scaling-stroke"/>', punkte))
    for st in stuecke_von(a):
        if len(st) > 1:
            formen.append(format_html('<polyline points="{}" class="fw-kurve-strich zwei" '
                                      'vector-effect="non-scaling-stroke"/>',
                                      ' '.join(f'{px:.2f},{py:.2f}' for px, py in st)))

    breite = 100 / (n - 1)
    treffer = format_html_join('', '<span class="fw-kurve-treffer" style="left:{}%;width:{}%" title="{}"></span>', (
        (f'{max(x(i) - breite / 2, 0):.2f}', f'{breite:.2f}',
         f'{beschriftungen[i] if i < len(beschriftungen) else ""}: '
         + ('CHF ' + chf(e[i], 0) if e[i] is not None else '–')
         + ' / ' + ('CHF ' + chf(a[i], 0) if a[i] is not None else '–'))
        for i in range(n)))
    x_text = format_html_join('', '<span class="fw-kurve-x{}" style="left:{}%">{}</span>', (
        (' fw-kurve-x-neben' if (n - 1 - i) % 2 else '', f'{x(i):.2f}', b)
        for i, b in enumerate(beschriftungen[:n])))
    return format_html(
        '<div class="fw-kurve" role="img" aria-label="{}"><div class="fw-kurve-plot">{}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{}{}</svg>{}</div>'
        '<div class="fw-kurve-achse">{}</div></div>',
        titel, mark_safe(''.join(y_text)), mark_safe(''.join(raster)), mark_safe(''.join(formen)),
        treffer, x_text)


@register.simple_tag
def donut_diagramm(teile, mitte_wert='', mitte_text='', titel=''):
    """Ring aus Anteilen. `teile`: dicts mit `lab` und `wert`.

    Die Farben sind Abstufungen EINER Marke (kein Regenbogen): wer die Teile
    unterscheiden muss, liest die Legende — die Farbe trägt keine Bedeutung.
    Der Ring nutzt `pathLength=100`, die Anteile sind also direkt Prozent.
    """
    teile = [(t.get('lab', ''), _zahl(t.get('wert')) or 0) for t in (teile or [])]
    teile = [(l, w) for l, w in teile if w > 0]
    summe = sum(w for _, w in teile)
    if not teile or summe <= 0:
        return ''
    kreise, offset = [], 0.0
    for i, (lab, w) in enumerate(teile):
        pct = w / summe * 100
        luecke = 0.8 if len(teile) > 1 else 0
        kreise.append(format_html(
            '<circle cx="21" cy="21" r="15.9155" pathLength="100" class="fw-donut-teil t{}" '
            'stroke-dasharray="{} {}" stroke-dashoffset="{}"><title>{}: {} %</title></circle>',
            i % 6, f'{max(pct - luecke, 0.01):.2f}', f'{100 - max(pct - luecke, 0.01):.2f}',
            f'{25 - offset:.2f}', lab, _prozent(pct)))
        offset += pct
    return format_html(
        '<div class="fw-donut" role="img" aria-label="{}">'
        '<svg viewBox="0 0 42 42" aria-hidden="true"><circle cx="21" cy="21" r="15.9155" class="fw-donut-spur"/>{}</svg>'
        '<div class="fw-donut-mitte"><b>{}</b><span>{}</span></div></div>',
        titel, mark_safe(''.join(kreise)), mitte_wert, mitte_text)
