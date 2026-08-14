"""Kontokorrent Eigentümer: das Ergebnis der bewirtschafteten
Liegenschaften (Ertrag − Aufwand) abzüglich der bereits an den Eigentümer
ausbezahlten Beträge = offener Saldo (Verbindlichkeit gegenüber dem Eigentümer).

Bewusst als *berechnete* Verwaltungssicht aus dem Hauptbuch — die tatsächlichen
Auszahlungen werden über EigentuemerAuszahlung (Buchung Soll 2850 / Haben Bank)
geführt und hier abgezogen."""
from datetime import date
from decimal import Decimal


def kontokorrent(eigentuemer, jahr=None):
    """Gibt ein dict mit Ergebnis je Liegenschaft, Auszahlungen und offenem Saldo.

    jahr=None → kumulativ über alle Jahre. Sonst nur das Geschäftsjahr.
    """
    from finance.models import Buchung, Buchungskonto, EigentuemerAuszahlung
    from portfolio.models import Liegenschaft
    from django.db.models import Sum

    ertrag_konten = list(Buchungskonto.objects.filter(typ='ertrag'))
    aufwand_konten = list(Buchungskonto.objects.filter(typ='aufwand'))
    liegenschaften = Liegenschaft.objects.filter(eigentuemer=eigentuemer).order_by('strasse')

    von = date(jahr, 1, 1) if jahr else None
    bis = date(jahr, 12, 31) if jahr else None

    # Abschlussbuchungen ausklammern: sie saldieren alle Erfolgskonten per 31.12.
    # gegen 2970. Ohne den Ausschluss kippte das Eigentümer-Ergebnis nach dem
    # Jahresabschluss auf null bzw. ins Negative (Audit).
    from core.services.jahresabschluss import abschluss_buchungen_q

    zeilen = []
    sum_ertrag = sum_aufwand = Decimal('0.00')
    for lg in liegenschaften:
        bqs = Buchung.objects.filter(liegenschaft=lg).exclude(abschluss_buchungen_q())
        if von:
            bqs = bqs.filter(datum__gte=von, datum__lte=bis)
        ertrag = Decimal('0.00')
        for k in ertrag_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            ertrag += (h - s)
        aufwand = Decimal('0.00')
        for k in aufwand_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            aufwand += (s - h)
        if ertrag == 0 and aufwand == 0:
            continue
        zeilen.append({'lg': lg, 'ertrag': ertrag, 'aufwand': aufwand, 'ergebnis': ertrag - aufwand})
        sum_ertrag += ertrag
        sum_aufwand += aufwand
    ergebnis = sum_ertrag - sum_aufwand

    ausz = EigentuemerAuszahlung.objects.filter(eigentuemer=eigentuemer, status='verbucht')
    if von:
        ausz = ausz.filter(datum__gte=von, datum__lte=bis)
    ausz = list(ausz.select_related('konto').order_by('-datum', '-id'))
    ausbezahlt = sum((a.betrag for a in ausz), Decimal('0.00'))

    return {
        'zeilen': zeilen,
        'ertrag': sum_ertrag, 'aufwand': sum_aufwand, 'ergebnis': ergebnis,
        'auszahlungen': ausz, 'ausbezahlt': ausbezahlt,
        'offen': ergebnis - ausbezahlt,
        'liegenschaften_n': liegenschaften.count(),
    }


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_kontokorrent_pdf(eigentuemer, jahr, verwaltung=None):
    """Kontokorrent-Auszug für den Eigentümer: Ergebnis je Liegenschaft,
    Auszahlungen und offener Saldo — das Dokument für den Eigentümer."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    kk = kontokorrent(eigentuemer, jahr=jahr)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    periode = str(jahr) if jahr else "kumuliert (alle Jahre)"
    c.setTitle(f"Kontokorrent {eigentuemer.firma_oder_name} {periode}")

    # Absender
    if verwaltung:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, h - 20 * mm, verwaltung.firma or "")
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, h - 24 * mm, verwaltung.strasse or "")
        c.drawString(20 * mm, h - 28 * mm, f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip())
    # Empfänger
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, h - 48 * mm, eigentuemer.firma_oder_name)
    if eigentuemer.kontaktperson:
        c.drawString(20 * mm, h - 53 * mm, eigentuemer.kontaktperson)
    c.drawString(20 * mm, h - 58 * mm, eigentuemer.strasse or "")
    c.drawString(20 * mm, h - 63 * mm, f"{eigentuemer.plz or ''} {eigentuemer.ort or ''}".strip())

    # Titel
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 80 * mm, "Kontokorrent Eigentümer")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawString(20 * mm, h - 85 * mm, f"Periode: {periode}")
    c.setFillColor(colors.black)

    # Ergebnis je Liegenschaft
    y = h - 98 * mm
    c.setFillColor(colors.HexColor("#EEF0F5"))
    c.rect(18 * mm, y - 2 * mm, 174 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22 * mm, y, "Liegenschaft")
    c.drawRightString(120 * mm, y, "Ertrag")
    c.drawRightString(155 * mm, y, "Aufwand")
    c.drawRightString(188 * mm, y, "Ergebnis")
    y -= 9 * mm
    c.setFont("Helvetica", 9)
    for z in kk['zeilen']:
        if y < 60 * mm:
            c.showPage(); y = h - 30 * mm
        c.drawString(22 * mm, y, f"{z['lg'].strasse}, {z['lg'].ort}"[:52])
        c.drawRightString(120 * mm, y, _fmt(z['ertrag']))
        c.drawRightString(155 * mm, y, _fmt(z['aufwand']))
        c.drawRightString(188 * mm, y, _fmt(z['ergebnis']))
        y -= 6 * mm
    if not kk['zeilen']:
        c.setFillColor(colors.grey)
        c.drawString(22 * mm, y, "Keine verbuchten Bewegungen in der Periode.")
        c.setFillColor(colors.black); y -= 6 * mm

    y -= 1 * mm
    c.setLineWidth(0.6); c.line(18 * mm, y, 192 * mm, y); y -= 7 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22 * mm, y, "Ergebnis Total")
    c.drawRightString(120 * mm, y, _fmt(kk['ertrag']))
    c.drawRightString(155 * mm, y, _fmt(kk['aufwand']))
    c.drawRightString(188 * mm, y, _fmt(kk['ergebnis']))

    # Honorar-Transparenz: der Eigentümer sieht, wie das im Aufwand enthaltene
    # Verwaltungshonorar berechnet wurde (Satz × Mietertrag je Liegenschaft).
    if jahr and (eigentuemer.honorar_prozent or 0) > 0:
        from core.services.verwaltungshonorar import honorar_vorschau
        h_zeilen, _h_total, h_prozent = honorar_vorschau(eigentuemer, jahr)
        h_zeilen = [z for z in h_zeilen if z['honorar'] or z['mietertrag']]
        if h_zeilen:
            y -= 14 * mm
            c.setFont("Helvetica-Bold", 10)
            c.drawString(20 * mm, y, f"Verwaltungshonorar {jahr} ({h_prozent}% der Mieterträge)")
            y -= 7 * mm
            c.setFont("Helvetica", 9)
            h_sum = Decimal('0.00')
            for z in h_zeilen:
                if y < 45 * mm:
                    c.showPage(); y = h - 30 * mm
                status = "verbucht" if z['gebucht'] else "offen"
                c.drawString(22 * mm, y, f"{z['lg'].strasse}"[:40])
                c.setFillColor(colors.grey)
                c.drawString(105 * mm, y, f"{h_prozent}% von {_fmt(z['mietertrag'])} · {status}")
                c.setFillColor(colors.black)
                c.drawRightString(188 * mm, y, _fmt(z['honorar']))
                h_sum += z['honorar']
                y -= 6 * mm
            c.setLineWidth(0.6); c.line(120 * mm, y, 192 * mm, y); y -= 7 * mm
            c.setFont("Helvetica-Bold", 10)
            c.drawString(22 * mm, y, "Honorar Total")
            c.drawRightString(188 * mm, y, _fmt(h_sum))

    # Auszahlungen
    y -= 14 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Auszahlungen an den Eigentümer")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for a in kk['auszahlungen']:
        if y < 45 * mm:
            c.showPage(); y = h - 30 * mm
        txt = a.datum.strftime('%d.%m.%Y') + (f" · {a.bemerkung}" if a.bemerkung else "")
        c.drawString(22 * mm, y, txt[:60])
        c.drawRightString(188 * mm, y, _fmt(a.betrag))
        y -= 6 * mm
    if not kk['auszahlungen']:
        c.setFillColor(colors.grey)
        c.drawString(22 * mm, y, "Keine Auszahlungen in der Periode."); c.setFillColor(colors.black); y -= 6 * mm
    c.setLineWidth(0.6); c.line(120 * mm, y, 192 * mm, y); y -= 7 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22 * mm, y, "Ausbezahlt Total")
    c.drawRightString(188 * mm, y, _fmt(kk['ausbezahlt']))

    # Offener Saldo
    y -= 16 * mm
    offen = kk['offen']
    c.setFillColor(colors.HexColor("#ECFDF5") if offen >= 0 else colors.HexColor("#FEF2F2"))
    c.rect(18 * mm, y - 6 * mm, 174 * mm, 16 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    label = "Offener Saldo (Guthaben Eigentümer)" if offen >= 0 else "Überzahlung (Eigentümer schuldet)"
    c.drawString(22 * mm, y, label)
    c.drawRightString(188 * mm, y, f"CHF {_fmt(abs(offen))}")

    c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
    c.drawString(20 * mm, 18 * mm, "Ergebnis der bewirtschafteten Liegenschaften (inkl. Verwaltungshonorar) abzüglich der geleisteten Auszahlungen.")
    if eigentuemer.iban:
        c.drawString(20 * mm, 14 * mm, f"Auszahlung auf: {eigentuemer.iban}")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
