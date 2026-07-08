"""Serienbrief: erzeugt ein Sammel-PDF mit einem Brief pro Empfänger
(Fenstercouvert-Adressblock, Platzhalter-Ersetzung, ein Brief je Seite)."""
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def _wrap(text, breite):
    zeilen = []
    for absatz in (text or '').split('\n'):
        worte = absatz.split(' ')
        akt = ''
        for w in worte:
            if len(akt) + len(w) + 1 > breite:
                zeilen.append(akt); akt = w
            else:
                akt = (akt + ' ' + w).strip()
        zeilen.append(akt)
    return zeilen


def _ersetze(text, e):
    ort = f"{e.get('plz','')} {e.get('ort','')}".strip()
    ersatz = {
        '{name}': e.get('name', ''),
        '{anrede}': e.get('anrede', ''),
        '{strasse}': e.get('strasse', ''),
        '{plz}': e.get('plz', ''),
        '{ort}': e.get('ort', ''),
        '{adresse}': f"{e.get('strasse','')}, {ort}".strip(', '),
        '{objekt}': e.get('objekt', ''),
        '{liegenschaft}': e.get('liegenschaft', ''),
    }
    out = text or ''
    for k, v in ersatz.items():
        out = out.replace(k, v or '')
    return out


def generate_serienbrief_pdf(absender, betreff, text, empfaenger, logo_path=None):
    """absender: dict firma/strasse/plz/ort. empfaenger: Liste dicts."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    heute = datetime.date.today().strftime('%d.%m.%Y')
    ort_abs = absender.get('ort', '')

    for e in empfaenger:
        # Logo (optional, oben links)
        if logo_path:
            try:
                from reportlab.lib.utils import ImageReader
                img = ImageReader(logo_path)
                iw, ih = img.getSize()
                bh = 18 * mm
                bw = bh * (iw / ih) if ih else bh
                c.drawImage(img, 25 * mm, 265 * mm, width=bw, height=bh,
                            preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        # Absender-Zeile
        c.setFont("Helvetica", 8); c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(25 * mm, 272 * mm, f"{absender.get('firma','')} · {absender.get('strasse','')} · {absender.get('plz','')} {absender.get('ort','')}")
        c.setFillColorRGB(0, 0, 0)
        # Empfänger-Adressblock (Fenstercouvert rechts)
        c.setFont("Helvetica", 11)
        y = 250 * mm
        c.drawString(120 * mm, y, e.get('name', '')); y -= 5 * mm
        if e.get('strasse'):
            c.drawString(120 * mm, y, e['strasse']); y -= 5 * mm
        c.drawString(120 * mm, y, f"{e.get('plz','')} {e.get('ort','')}".strip())
        # Ort/Datum
        c.setFont("Helvetica", 10)
        c.drawRightString(185 * mm, 225 * mm, f"{ort_abs}, {heute}")
        # Betreff
        c.setFont("Helvetica-Bold", 11)
        c.drawString(25 * mm, 210 * mm, _ersetze(betreff, e))
        # Body
        c.setFont("Helvetica", 10.5)
        yy = 198 * mm
        for zeile in _wrap(_ersetze(text, e), 92):
            if yy < 40 * mm:
                break
            c.drawString(25 * mm, yy, zeile)
            yy -= 5.6 * mm
        # Grussformel
        yy -= 6 * mm
        c.drawString(25 * mm, yy, "Freundliche Grüsse")
        yy -= 12 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(25 * mm, yy, absender.get('firma', ''))
        c.showPage()

    c.save(); buf.seek(0)
    return buf.read()
