"""Reparaturauftrag (PDF) an einen Handwerker — das formelle Auftragsdokument
zum Schadensfall: Objekt, Schadenbeschreibung, Zutritt/Kontakt, Kostenrahmen.
Ergänzt die automatische Auftrags-E-Mail um einen sauberen Beleg."""
import io
from decimal import Decimal


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_auftrag_pdf(auftrag, verwaltung=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    t = auftrag.ticket
    hw = auftrag.handwerker
    lg = t.liegenschaft if t else None
    einheit = t.betroffene_einheit if t else None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setTitle(f"Reparaturauftrag #{auftrag.id} — {hw.firma if hw else ''}")
    indigo = colors.HexColor("#4F46E5")

    # Absender
    if verwaltung:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, h - 20 * mm, verwaltung.firma or "")
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, h - 24 * mm, verwaltung.strasse or "")
        c.drawString(20 * mm, h - 28 * mm, f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip())

    # Empfänger (Handwerker)
    c.setFont("Helvetica", 11)
    y = h - 46 * mm
    if hw:
        c.drawString(20 * mm, y, hw.firma or "")
        if hw.kontaktperson:
            c.drawString(20 * mm, y - 5 * mm, hw.kontaktperson)

    # Titel
    c.setFillColor(indigo)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(20 * mm, h - 72 * mm, "Reparaturauftrag")
    c.setFillColor(colors.grey)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 78 * mm, f"Auftrag Nr. {auftrag.id} · Ticket #{t.id if t else '—'} · {auftrag.beauftragt_am:%d.%m.%Y}")
    c.setFillColor(colors.black)

    def block(label, y0):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y0, label)
        return y0 - 6 * mm

    def zeile(text, y0, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9.5)
        for line in _wrap(text, 100):
            c.drawString(24 * mm, y0, line)
            y0 -= 5.2 * mm
        return y0

    y = h - 92 * mm
    # Objekt
    y = block("Objekt", y)
    if lg:
        y = zeile(f"{lg.strasse}, {lg.plz} {lg.ort}", y)
    if einheit:
        y = zeile(f"Einheit: {einheit.bezeichnung}" + (f" · {t.raum}" if t and t.raum else ""), y)
    elif t and t.raum:
        y = zeile(f"Raum: {t.raum}", y)

    # Schaden
    y -= 3 * mm
    y = block("Schaden / Auftrag", y)
    if t:
        y = zeile(t.titel, y, bold=True)
        if t.kategorie:
            y = zeile(f"Kategorie: {t.kategorie}", y)
        if t.beschreibung:
            y = zeile(t.beschreibung, y)
    if auftrag.bemerkung:
        y -= 1 * mm
        y = zeile(auftrag.bemerkung, y)

    # Zutritt / Kontakt
    y -= 3 * mm
    y = block("Zutritt & Kontakt vor Ort", y)
    if t:
        y = zeile(f"Zutritt: {t.get_zutritt_display()}", y)
        melder = f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip()
        kontakt = " · ".join([x for x in [melder, t.tel_melder or '', t.email_melder or ''] if x])
        if kontakt:
            y = zeile(kontakt, y)

    # Kostenrahmen
    if auftrag.kosten_geschaetzt:
        y -= 3 * mm
        y = block("Kostenrahmen", y)
        y = zeile(f"Kostenschätzung: CHF {_fmt(auftrag.kosten_geschaetzt)}", y)
        c.setFont("Helvetica-Oblique", 8.5); c.setFillColor(colors.grey)
        c.drawString(24 * mm, y, "Bei absehbarer Überschreitung bitte vorgängig Rücksprache mit der Verwaltung.")
        c.setFillColor(colors.black); y -= 6 * mm

    # Fotos-Hinweis
    n_fotos = t.fotos.count() if t else 0
    if n_fotos or (t and t.foto):
        y -= 2 * mm
        c.setFont("Helvetica", 9)
        c.drawString(24 * mm, y, f"Fotos zum Schaden: {n_fotos + (1 if t and t.foto else 0)} (auf Anfrage bei der Verwaltung).")

    # Fussbox
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.rect(0, 0, w, 24 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, 15 * mm, "Rechnung bitte mit Angabe von Auftrags- und Ticketnummer an die Verwaltung.")
    if verwaltung and getattr(verwaltung, 'email', ''):
        c.drawString(20 * mm, 10 * mm, f"Rückfragen: {verwaltung.email}" + (f" · {verwaltung.telefon}" if getattr(verwaltung, 'telefon', '') else ""))

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


def _wrap(text, width):
    from textwrap import wrap
    out = []
    for para in str(text).splitlines() or ['']:
        out.extend(wrap(para, width) or [''])
    return out
