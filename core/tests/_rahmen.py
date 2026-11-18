"""Die Rahmen-Skripte der Anwendung als Text.

Bis 15.11.2026 standen sie als Inline-Skripte in `core/templates/fw/base.html`; viele Wächter lasen sie von dort.
Jetzt sind es Dateien unter `static/js/` (zwischengespeichert, Audit P15). Wer den Rahmen prüft, liest Vorlage UND
Skripte.
"""
from pathlib import Path

from django.conf import settings

SKRIPTE = ('fw-rahmen.js', 'fw-thema.js', 'fw-kapsel.js')


def rahmen_skripte():
    wurzel = Path(settings.BASE_DIR) / 'static' / 'js'
    return '\n'.join((wurzel / name).read_text(encoding='utf-8') for name in SKRIPTE)


def basis_mit_skripten():
    """`fw/base.html` samt der ausgelagerten Skripte — das, was früher in der einen Datei stand."""
    vorlage = Path(settings.BASE_DIR) / 'core' / 'templates' / 'fw' / 'base.html'
    return vorlage.read_text(encoding='utf-8') + '\n' + rahmen_skripte()
