"""Erfolgsrechnung und Bilanz als PDF.

Der Berichte-Hub trug für «Erfolgsrechnung & Bilanz» seit jeher ein PDF-Abzeichen,
es gab aber nur einen CSV-Journal-Export. Für die Übergabe ans Treuhandbüro und
für die Ablage beim Eigentümer braucht es den Abschluss auf Papier.

Die Zahlen stammen aus `core.views.fw._erfolg_bilanz` — derselben Quelle wie die
Bildschirmansicht. Ein Abschluss, der je nach Ausgabeweg anders aussieht, wäre
wertlos.
"""
import io
from decimal import Decimal


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_abschluss_pdf(daten, jahr, lg_name, verwaltung=None, erstellt_am=None):
    """Zweiseitiger Abschluss: Erfolgsrechnung, dann Bilanz.

    `daten` ist das Dict aus `_erfolg_bilanz`. Gibt PDF-Bytes zurück.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    indigo = colors.HexColor("#4F46E5")
    grau = colors.HexColor("#64748B")
    rose = colors.HexColor("#E11D48")
    jahr_txt = "alle Jahre" if jahr == 'alle' else str(jahr)
    c.setTitle(f"Erfolgsrechnung und Bilanz {jahr_txt}")

    def kopf(titel):
        c.setFillColor(indigo)
        c.rect(0, h - 26 * mm, w, 26 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(20 * mm, h - 13 * mm, titel)
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, h - 20 * mm, f"Geschäftsjahr {jahr_txt} · {lg_name}")
        if verwaltung is not None:
            c.setFont("Helvetica", 9)
            c.drawRightString(w - 20 * mm, h - 13 * mm, getattr(verwaltung, 'firma', '') or "")
        if erstellt_am is not None:
            c.setFont("Helvetica", 8)
            c.drawRightString(w - 20 * mm, h - 20 * mm,
                              f"erstellt {erstellt_am.strftime('%d.%m.%Y')}")
        c.setFillColor(colors.black)

    def zeilen_block(titel, zeilen, total_label, total, y0, negativ_rot=False):
        """Kontenliste mit Nummer, Bezeichnung und Saldo; gibt neues y zurück."""
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.black)
        c.drawString(20 * mm, y0, titel)
        y0 -= 3 * mm
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(20 * mm, y0, w - 20 * mm, y0)
        y0 -= 6 * mm
        if not zeilen:
            c.setFont("Helvetica-Oblique", 9); c.setFillColor(grau)
            c.drawString(20 * mm, y0, "keine Bewegungen")
            c.setFillColor(colors.black)
            y0 -= 6 * mm
        for z in zeilen:
            if y0 < 30 * mm:
                c.showPage(); kopf(titel + " (Fortsetzung)"); y0 = h - 40 * mm
            c.setFont("Helvetica", 9); c.setFillColor(grau)
            c.drawString(20 * mm, y0, str(z['nummer']))
            c.setFillColor(colors.black)
            c.drawString(34 * mm, y0, str(z['bezeichnung'])[:52])
            wert = z['saldo']
            c.setFillColor(rose if (negativ_rot and wert < 0) else colors.black)
            c.drawRightString(w - 20 * mm, y0, _fmt(wert))
            c.setFillColor(colors.black)
            y0 -= 5.6 * mm
        # Summenzeile
        y0 -= 1 * mm
        c.setStrokeColor(colors.HexColor("#94A3B8"))
        c.line(120 * mm, y0 + 3 * mm, w - 20 * mm, y0 + 3 * mm)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y0 - 1 * mm, total_label)
        c.drawRightString(w - 20 * mm, y0 - 1 * mm, _fmt(total))
        return y0 - 10 * mm

    # ---------- Seite 1: Erfolgsrechnung ----------
    kopf("Erfolgsrechnung")
    y = h - 40 * mm
    y = zeilen_block("Ertrag", daten['ertraege'], "Total Ertrag",
                     daten['total_ertrag'], y)
    y = zeilen_block("Aufwand", daten['aufwaende'], "Total Aufwand",
                     daten['total_aufwand'], y)

    erfolg = daten['erfolg']
    if y < 40 * mm:
        c.showPage(); kopf("Erfolgsrechnung"); y = h - 40 * mm
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.rect(20 * mm, y - 4 * mm, w - 40 * mm, 12 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(24 * mm, y, "Gewinn" if erfolg >= 0 else "Verlust")
    c.setFillColor(rose if erfolg < 0 else colors.HexColor("#047857"))
    c.drawRightString(w - 24 * mm, y, f"CHF {_fmt(erfolg)}")
    c.setFillColor(colors.black)

    # ---------- Seite 2: Bilanz ----------
    c.showPage()
    kopf("Bilanz")
    y = h - 40 * mm
    y = zeilen_block("Aktiven", daten['aktiven'], "Total Aktiven",
                     daten['total_aktiven'], y, negativ_rot=True)
    y = zeilen_block("Passiven", daten['passiven'], "Total Passiven",
                     daten['total_passiven'], y, negativ_rot=True)

    if y < 46 * mm:
        c.showPage(); kopf("Bilanz"); y = h - 40 * mm
    # Eigenkapital-Herleitung: Vortrag + Jahresergebnis. Ohne diese Zeilen ist
    # nicht nachvollziehbar, warum die Bilanz aufgeht.
    c.setFont("Helvetica", 9); c.setFillColor(grau)
    c.drawString(20 * mm, y, "Ergebnisvortrag aus Vorjahren")
    c.setFillColor(colors.black)
    c.drawRightString(w - 20 * mm, y, _fmt(daten['erfolg_vortrag']))
    y -= 5.6 * mm
    c.setFillColor(grau)
    c.drawString(20 * mm, y, "Ergebnis der Periode")
    c.setFillColor(colors.black)
    c.drawRightString(w - 20 * mm, y, _fmt(daten['erfolg']))
    y -= 8 * mm

    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.rect(20 * mm, y - 4 * mm, w - 40 * mm, 12 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(24 * mm, y, "Passiven inkl. kumuliertem Ergebnis")
    c.drawRightString(w - 24 * mm, y, f"CHF {_fmt(daten['passiven_mit_erfolg'])}")
    y -= 12 * mm

    diff = daten['bilanz_differenz']
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(rose if diff else colors.HexColor("#047857"))
    c.drawString(20 * mm, y,
                 "Bilanz geht auf (Differenz 0.00)" if not diff
                 else f"Differenz Aktiven − Passiven: CHF {_fmt(diff)}")
    c.setFillColor(colors.black)

    c.setFont("Helvetica", 7.5); c.setFillColor(grau)
    c.drawString(20 * mm, 12 * mm,
                 "Erfolgsrechnung ohne Abschlussbuchungen (Saldierung gegen 2970); "
                 "Bilanz kumulativ bis Jahresende.")
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    return buf.getvalue()
