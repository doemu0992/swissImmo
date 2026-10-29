"""Farben für Druck, PDF und E-Mail: Ember.

Die Anwendung trägt seit dem Redesign die Marke Ember (`--ds-brand` in
core/templates/fw/_schicht.html). Auf Papier und in der Mail stand bis Etappe 3
etwas anderes: sechs PDF-Erzeuger mit Indigo `#4F46E5`, zwei mit `#4338CA`, zwei mit
Marineblau, das Treppenhaus-Poster hellblau, die HTML-Mails indigo und blau
(DESIGN-16). Wer ein Dokument der Verwaltung öffnete, sah drei Blautöne und kein Ember.

Dieses Modul ist die EINE Stelle. Ein Test (`core/tests/test_druckfarben.py`) hält sie
gleich dem Token der Oberfläche und sucht in allen Erzeugern nach den alten Farben.

Verwendung in reportlab (Importe von reportlab bleiben lazy, damit die Mail-Pfade das
Modul ohne reportlab laden können)::

    from core.services.druckfarben import EMBER_RGB
    c.setFillColorRGB(*EMBER_RGB)

oder ``colors.HexColor(EMBER)``.
"""

#: Marke (`--ds-brand`, hell): Köpfe, Titel, Akzente. Weisse Schrift darauf 5.7:1 (AA).
EMBER = '#B04416'
#: Eine Stufe dunkler (`--ds-brand-600`): Hover, Rahmen, kleine Schrift auf Weiss.
EMBER_TIEF = '#8A3410'
#: Fläche (`--ds-brand-soft`): Hinterlegung für Hinweise und Summenzeilen.
EMBER_FLAECHE = '#FBE7DC'


def _rgb(hexwert):
    h = hexwert.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


#: Dasselbe als (r, g, b) mit 0..1, für `setFillColorRGB`/`setStrokeColorRGB`.
EMBER_RGB = _rgb(EMBER)
EMBER_TIEF_RGB = _rgb(EMBER_TIEF)
EMBER_FLAECHE_RGB = _rgb(EMBER_FLAECHE)
