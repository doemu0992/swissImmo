"""Die Fensterprobe: eine A4-Seite zum Ausdrucken, Falten und Einlegen in den Fensterumschlag.

WARUM ES DAS GIBT: Die Adresslage der Briefe (Adressfeld 118 mm von links, 45 mm von oben) wurde aus der Erinnerung
gesetzt und nie gegen einen echten Umschlag geprüft (Masse und Herkunft: `core/services/dok_layout.py`). Statt zu
raten, kann die Verwaltung es selbst prüfen: Die Seite zeigt die AKTUELLE Adresslage (samt Versatz aus den
Briefkopf-Einstellungen), den angenommenen Fensterumriss, die Falzmarken und ein Mass-Raster. Auf Papier gedruckt und
gefaltet muss die Adresse im Fenster des Umschlags stehen. Sitzt sie nicht richtig, stellt die Verwaltung den Versatz
ein (x nach rechts, y nach unten, in mm) und druckt noch einmal.

Seite 1: eine übliche Anschrift mit Zustellvermerk. Seite 2: der ungünstigste Fall (sechs lange Zeilen).
Der Fensterumriss ist die ANNAHME `UMSCHLAGFENSTER`, nicht ein gemessener Wert — das steht auch auf dem Blatt.
"""
import io

from django.utils.translation import gettext as _
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit

from core.services import dok_layout as dl
from core.services.dok_layout import DokCanvas, adressfeld_masse

#: Falzmarken von oben: A4 (297 mm) in drei gleiche Teile, wie es in C5/6 (114 x 229 mm) passt.
FALZMARKEN_MM = (99, 198)
#: Länge der Strecke zur Kontrolle des Druckmassstabs.
MASSSTAB_MM = 100

_ROT = HexColor('#c0392b')
_BLAU = HexColor('#2563eb')
_RASTER = Color(0.91, 0.91, 0.91)
_RASTER_FETT = Color(0.75, 0.75, 0.75)


def _raster(c):
    """Mass-Raster: alle 10 mm eine feine, alle 50 mm eine kräftigere Linie; Beschriftung am Rand alle 20 mm."""
    breite, hoehe = c.breite, c.hoehe
    c.saveState()
    c.setFont('Helvetica', 5.5)
    for x_mm in range(0, 211, 10):
        c.setStrokeColor(_RASTER_FETT if x_mm % 50 == 0 else _RASTER)
        c.setLineWidth(0.4 if x_mm % 50 == 0 else 0.2)
        c.line(x_mm * mm, 0, x_mm * mm, hoehe)
        if x_mm % 20 == 0:
            c.setFillColor(_RASTER_FETT)
            c.drawString(x_mm * mm + 1, hoehe - 6, str(x_mm))
    for y_mm in range(0, 298, 10):
        y = hoehe - y_mm * mm
        c.setStrokeColor(_RASTER_FETT if y_mm % 50 == 0 else _RASTER)
        c.setLineWidth(0.4 if y_mm % 50 == 0 else 0.2)
        c.line(0, y, breite, y)
        if y_mm % 20 == 0 and y_mm:
            c.setFillColor(_RASTER_FETT)
            c.drawString(1.5, y + 1, str(y_mm))
    c.restoreState()


def _umrisse(c):
    """Fensterumriss (Annahme), Adressfeld (aktuelle Lage), Falzmarken, Massstabsstrecke."""
    c.saveState()
    links, oben, breite, hoehe = dl.UMSCHLAGFENSTER
    c.setStrokeColor(_ROT)
    c.setLineWidth(0.9)
    c.setDash(3, 2)
    c.rect(links * mm, c.hoehe - (oben + hoehe) * mm, breite * mm, hoehe * mm, stroke=1, fill=0)
    c.setFillColor(_ROT)
    c.setFont('Helvetica', 6)
    c.drawString((links + 1) * mm, c.hoehe - (oben + hoehe - 2) * mm,
                 _('Umschlagfenster (Annahme, %(b)s × %(h)s mm)') % {'b': int(breite), 'h': int(hoehe)})
    # Adressfeld mit der aktuellen Lage und höchstens sechs Zeilen
    a_links, a_oben, a_rechts, a_unten = adressfeld_masse(dl.ADRESS_ZEILEN_MAX, c.versatz_x, c.versatz_y)
    c.setStrokeColor(_BLAU)
    c.setLineWidth(0.5)
    c.setDash(1, 2)
    c.rect(a_links * mm, c.hoehe - a_unten * mm, (a_rechts - a_links) * mm, (a_unten - a_oben) * mm, stroke=1, fill=0)
    c.setDash()
    # Falzmarken am linken und rechten Rand
    c.setStrokeColor(HexColor('#111827'))
    c.setLineWidth(0.8)
    c.setFillColor(HexColor('#111827'))
    c.setFont('Helvetica', 6)
    for y_mm in FALZMARKEN_MM:
        y = c.hoehe - y_mm * mm
        c.line(0, y, 8 * mm, y)
        c.line(c.breite - 8 * mm, y, c.breite, y)
        c.drawRightString(c.breite - 9 * mm, y + 1.2, _('Falzmarke %(mm)s mm') % {'mm': y_mm})
    c.restoreState()


def _massstab(c, y):
    """Eine Strecke von genau 100 mm: Wer nachmisst, sieht, ob mit 100 % gedruckt wurde."""
    c.saveState()
    c.setStrokeColor(HexColor('#111827'))
    c.setLineWidth(0.8)
    x = dl.LINKS
    c.line(x, y, x + MASSSTAB_MM * mm, y)
    c.line(x, y - 1.5 * mm, x, y + 1.5 * mm)
    c.line(x + MASSSTAB_MM * mm, y - 1.5 * mm, x + MASSSTAB_MM * mm, y + 1.5 * mm)
    c.setFont('Helvetica', 8)
    c.setFillColor(HexColor('#111827'))
    c.drawString(x + (MASSSTAB_MM + 3) * mm, y - 1, _('= %(mm)s mm (Massstab-Kontrolle)') % {'mm': MASSSTAB_MM})
    c.restoreState()


def _hinweis(c, y, versatz_text):
    texte = [
        _('Auf Papier drucken (Massstab 100 %, nicht «An Seite anpassen»), an den Falzmarken in drei Teile falten '
          'und in den Fensterumschlag legen: Die Adresse muss im Fenster stehen.'),
        _('Mindestens %(mm)s mm Rand zum Fensterrand; der Zustellvermerk darf nicht im Fenster stehen.')
        % {'mm': int(dl.FENSTER_RAND_MIN / mm)},
        _('Der rote Umriss ist eine Annahme, kein gemessener Wert: Massgebend ist Ihr Umschlag. '
          'Sitzt die Adresse nicht richtig, stellen Sie den Versatz in den Briefkopf-Einstellungen ein.'),
        versatz_text,
    ]
    c.setFont('Helvetica', 10)
    for text in texte:
        for zeile in simpleSplit(text, 'Helvetica', 10, c.rand_rechts - c.links):
            c.drawString(c.links, y, zeile)
            y -= 5 * mm
        y -= 1.5 * mm
    return y


def fensterprobe_pdf(organisation=None):
    """Die Fensterprobe als PDF-Bytes. Die Adresslage ist die der Verwaltung (Versatz eingerechnet)."""
    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=organisation, absender=['Verwaltung', '', ''], titel=_('Fensterprobe'))
    versatz = _('Aktuelle Adresslage: Versatz x = %(x)s mm (nach rechts), y = %(y)s mm (nach unten).') % {
        'x': f'{c.versatz_x:g}', 'y': f'{c.versatz_y:g}'}

    # Seite 1: übliche Anschrift mit Zustellvermerk
    _raster(c)
    y = c.brief(['Frau Maria Muster', 'Beispielstrasse 12', '8000 Zürich'], '', _('Fensterprobe'),
                einschreiben=True)
    _umrisse(c)
    y = _hinweis(c, y, versatz)
    _massstab(c, y - 4 * mm)
    c.showPage()

    # Seite 2: der ungünstigste Fall
    c.neues_dokument()
    _raster(c)
    c.brief(['Immobilien Treuhand Muster & Partner Aktiengesellschaft Zürich', 'z. H. Frau Dr. Maria Beispiel-Muster',
             'Abteilung Liegenschaftsverwaltung und Vermietung', 'Musterstrasse 123 b', 'Postfach 4567', '8000 Zürich'],
            '', _('Fensterprobe: sechs lange Zeilen'), einschreiben=True)
    _umrisse(c)
    c.showPage()
    c.save()
    return buf.getvalue()
