"""Der Stil, den ein Besucher tatsächlich bekommt — aus allen Quellen.

WARUM ES DIESE HILFE GIBT

Bis E2.22 stand die Komponentenschicht als `<style>`-Block in jeder Seite.
Tests, die eine CSS-Regel prüfen wollten, suchten sie deshalb im gerenderten
HTML — naheliegend und richtig, solange sie dort steht.

Seit E2.22 liegt sie in `static/css/schicht.css` und wird über ein `<link>`
geladen. Zwölf Tests schlugen daraufhin an, obwohl sich an der Darstellung
nichts geändert hat: Sie suchten am alten Ort.

Diese Hilfe beantwortet die Frage, die sie eigentlich stellen: **Kommt diese
Regel beim Besucher an?** Dafür sammelt sie den Inline-Stil der Seite UND die
verlinkten Dateien aus `static/`. Wo eine Regel steht, ist eine Frage der
Bauweise; ob sie ankommt, ist die Frage des Tests.
"""
import pathlib
import re

from django.conf import settings

WURZEL = pathlib.Path(settings.BASE_DIR)


def ausgelieferter_stil(html):
    """Inline-Stil plus verlinkte Stylesheets aus `static/`.

    Fremde Adressen werden ignoriert — was von aussen kommt, ist nicht Teil
    des Bestands und wird von `test_keine_fremdquellen.py` geprüft.
    """
    teile = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)

    for treffer in re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', html):
        m = re.search(r'href=["\']([^"\']+)["\']', treffer)
        if not m:
            continue
        pfad = m.group(1)
        if pfad.startswith(('http://', 'https://', '//')):
            continue
        # `/static/css/schicht.css` -> `static/css/schicht.css`
        datei = WURZEL / pfad.lstrip('/')
        if not datei.exists():
            datei = WURZEL / 'static' / pfad.split('static/')[-1]
        if datei.exists():
            teile.append(datei.read_text(encoding='utf-8'))

    return '\n'.join(teile)
