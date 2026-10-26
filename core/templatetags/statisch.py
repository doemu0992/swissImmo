"""`{% statisch 'css/schicht.css' %}` — wie `{% static %}`, plus eine Versionskennung.

WARUM (26.10.2026, nach dem Ember-Deploy)
Die Stilschicht lag immer unter derselben Adresse `/static/css/schicht.css`.
Nach dem Deploy holte der Browser das neue HTML, nahm aber die alte CSS aus
seinem Zwischenspeicher: Das neue Logo-SVG hatte keine Grösse und füllte die
halbe Seite, die Kopfleiste war ungestaltet. Mit `?v=<Prüfsumme>` hat jede
Fassung ihre eigene Adresse — ändert sich die Datei, lädt der Browser neu.

Die Kennung kommt aus dem INHALT (nicht aus dem Deploy-Zeitpunkt): Bleibt eine
Datei gleich, bleibt die Adresse gleich, und der Zwischenspeicher hilft weiter.
Berechnet wird je Fassung einmal (Schlüssel: Pfad, Änderungszeit, Grösse).
"""
import hashlib
import os
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@lru_cache(maxsize=64)
def _pruefsumme(datei, _mtime, _groesse):
    with open(datei, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def kennung(pfad):
    """Die Versionskennung einer statischen Datei, '' wenn sie nicht gefunden wird."""
    datei = finders.find(pfad)
    if not datei:
        return ''
    st = os.stat(datei)
    return _pruefsumme(datei, st.st_mtime_ns, st.st_size)


@register.simple_tag
def statisch(pfad):
    url = static(pfad)
    v = kennung(pfad)
    return f'{url}?v={v}' if v else url
