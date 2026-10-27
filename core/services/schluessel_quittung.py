"""Schlüsselquittung als PDF (Modul 2, 27.10.2026) — Ausgabe und Rücknahme.

Ein Beleg in derselben Bauart wie die Briefe in `mietprozess_briefe.py`
(reportlab, A4). Die Quittung hält fest, wer welche Schlüssel wann erhalten
oder zurückgegeben hat, mit der Unterschrift aus dem Zeichenfeld. Sie ist kein
Vertragstext: Haftung oder Kosten stehen bewusst NICHT darin (Entscheid E9 —
ein Verlust wird nicht automatisch verrechnet).

Der Text ist deutsch formuliert und entsteht deshalb fest auf Deutsch
(`nur_deutsch`, siehe core/services/dokumentsprache.py).
"""
import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from core.services.dokumentsprache import nur_deutsch

logger = logging.getLogger(__name__)

ART_TEXT = {'haupt': 'Hauptschlüssel', 'gruppe': 'Gruppenschlüssel', 'einzel': 'Einzelschlüssel'}


def _absender(liegenschaft):
    vw = liegenschaft.organisation if liegenschaft is not None else None
    if vw is None:
        return ['Immobilienverwaltung']
    return [z for z in (vw.firma, vw.strasse, f"{vw.plz or ''} {vw.ort or ''}".strip()) if z]


@nur_deutsch
def quittung_pdf(*, art, liegenschaft, empfaenger, datum, zeilen, rueckgabe_bis=None,
                 unterschrift_png=None, unterschrift_name='', notiz=''):
    """Die Quittung als PDF-Bytes.

    `art`: 'ausgabe' oder 'ruecknahme'. `zeilen`: Liste von dicts mit
    `anzahl`, `art` (haupt/gruppe/einzel), `typ`, `nummer`, `tueren` (Text)
    und bei der Rücknahme `status` ('zurueck' oder 'verloren')."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle('Schlüsselquittung')
    c.setFont('Helvetica', 8)
    c.drawString(20 * mm, 282 * mm, ' · '.join(_absender(liegenschaft)))

    titel = 'Schlüsselquittung · Ausgabe' if art == 'ausgabe' else 'Schlüsselquittung · Rücknahme'
    c.setFont('Helvetica-Bold', 15)
    c.drawString(20 * mm, 265 * mm, titel)
    c.setFont('Helvetica', 10)
    y = 255 * mm
    lg_text = f"{liegenschaft.strasse}, {liegenschaft.plz} {liegenschaft.ort}" if liegenschaft else ''
    for label, wert in (('Liegenschaft', lg_text),
                        ('Empfänger' if art == 'ausgabe' else 'Zurückgegeben von', empfaenger),
                        ('Datum', datum.strftime('%d.%m.%Y')),
                        ('Zurück bis', rueckgabe_bis.strftime('%d.%m.%Y') if rueckgabe_bis else '')):
        if not wert:
            continue
        c.setFillColor(colors.grey); c.drawString(20 * mm, y, label)
        c.setFillColor(colors.black); c.drawString(62 * mm, y, wert)
        y -= 6 * mm

    y -= 4 * mm
    c.setStrokeColor(colors.HexColor('#e2e8f0')); c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont('Helvetica-Bold', 8); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, 'Stück'); c.drawString(34 * mm, y, 'Schlüssel'); c.drawString(100 * mm, y, 'Öffnet')
    if art != 'ausgabe':
        c.drawString(168 * mm, y, 'Status')
    c.setFillColor(colors.black)
    y -= 5 * mm
    for z in zeilen:
        bezeichnung = f"{ART_TEXT.get(z.get('art'), '')} {z.get('typ') or ''} Nr. {z.get('nummer') or ''}".strip()
        teile = simpleSplit(bezeichnung, 'Helvetica', 9, 64 * mm)[:2] or ['']
        tueren = simpleSplit(z.get('tueren') or '–', 'Helvetica', 8, 66 * mm)[:3] or ['–']
        hoehe = max(len(teile), len(tueren)) * 4.4 * mm + 1.5 * mm
        if y - hoehe < 70 * mm:
            c.showPage(); y = 275 * mm
        c.setFont('Helvetica', 9)
        c.drawString(20 * mm, y, str(z.get('anzahl') or 0))
        for i, t in enumerate(teile):
            c.drawString(34 * mm, y - i * 4.4 * mm, t)
        c.setFont('Helvetica', 8)
        for i, t in enumerate(tueren):
            c.drawString(100 * mm, y - i * 4.4 * mm, t)
        if art != 'ausgabe':
            c.setFont('Helvetica-Bold', 8)
            c.drawString(168 * mm, y, 'verloren' if z.get('status') == 'verloren' else 'zurück')
        y -= hoehe

    y -= 6 * mm
    c.setFont('Helvetica', 9.5)
    if art == 'ausgabe':
        satz = 'Der Empfänger bestätigt mit seiner Unterschrift den Erhalt der aufgeführten Schlüssel.'
    else:
        satz = ('Die Verwaltung bestätigt die Rücknahme der als «zurück» aufgeführten Schlüssel. '
                'Als «verloren» aufgeführte Schlüssel wurden nicht zurückgegeben.')
    for zeile in simpleSplit(satz, 'Helvetica', 9.5, 170 * mm):
        c.drawString(20 * mm, y, zeile); y -= 5 * mm
    if notiz:
        y -= 2 * mm
        c.setFont('Helvetica', 8.5); c.setFillColor(colors.grey)
        for zeile in simpleSplit(f'Notiz: {notiz}', 'Helvetica', 8.5, 170 * mm)[:4]:
            c.drawString(20 * mm, y, zeile); y -= 4.5 * mm
        c.setFillColor(colors.black)

    # Unterschrift: Bild über der Linie, Name darunter. Ohne Bild steht
    # «nicht unterzeichnet» — ein Name auf der Linie sähe sonst wie eine
    # Unterschrift aus (wie im Abnahmeprotokoll).
    y = min(y - 8 * mm, 60 * mm)
    if unterschrift_png:
        try:
            c.drawImage(ImageReader(io.BytesIO(unterschrift_png)), 20 * mm, y + 1 * mm, width=70 * mm,
                        height=24 * mm, preserveAspectRatio=True, anchor='sw')
        except Exception:
            logger.exception('Schlüsselquittung: Unterschrift nicht lesbar')
    c.setStrokeColor(colors.black); c.line(20 * mm, y, 95 * mm, y)
    c.setFont('Helvetica', 8.5)
    unten = unterschrift_name or empfaenger
    if not unterschrift_png:
        unten = f'{unten} (nicht unterzeichnet)'
    c.drawString(20 * mm, y - 4.5 * mm, unten)
    c.drawString(115 * mm, y - 4.5 * mm, f"Ort, Datum: {liegenschaft.ort if liegenschaft else ''}, "
                                         f"{datum.strftime('%d.%m.%Y')}")
    c.showPage()
    c.save()
    return buf.getvalue()
