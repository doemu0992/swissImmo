"""Kontokorrent Eigentümer: das Ergebnis der bewirtschafteten
Liegenschaften (Ertrag − Aufwand) abzüglich der bereits an den Eigentümer
ausbezahlten Beträge = offener Saldo (Verbindlichkeit gegenüber dem Eigentümer).

Bewusst als *berechnete* Verwaltungssicht aus dem Hauptbuch — die tatsächlichen
Auszahlungen werden über EigentuemerAuszahlung (Buchung Soll 2850 / Haben Bank)
geführt und hier abgezogen."""
from datetime import date
from decimal import Decimal
from core.services.dokumentsprache import nur_deutsch


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


class AuszahlungNichtMoeglich(Exception):
    """Die Auszahlung wird abgewiesen; die Meldung ist für den Benutzer bestimmt."""


#: Konten, auf denen Geld liegt, das noch keiner Forderung zugeordnet ist:
#: Durchlaufkonto (ungeklärte Zahlungen) und Mieterguthaben. Ordnet jemand eine
#: solche Zahlung einer Mietforderung zu (`1190/2030 an 1100`), ist das der
#: Zeitpunkt, ab dem sie als eingegangene Miete zählt.
_PARKKONTEN = ('1190', '2030')


def liquiditaet(eigentuemer):
    """Was dem Eigentümer aus dem tatsächlich eingegangenen Geld zusteht.

    DIE LIQUIDITÄTSBASIS — und warum es sie neben dem Kontokorrent braucht:

    `kontokorrent()` rechnet Ertrag − Aufwand aus dem Journal. Das ist eine
    Verwaltungssicht auf Sollbasis: Die Sollstellung bucht `1100 an 3000`, sobald
    die Miete FÄLLIG ist, nicht wenn sie bezahlt wird, und eine Lieferantenrechnung
    ist Aufwand bei der Freigabe, nicht bei der Zahlung. Wer daraus ableitet, was
    er überweisen kann, zahlt dem Eigentümer Mieten aus, die nie eingegangen sind
    (Audit FUNK-01/FIN-03: Maske nannte CHF 21'700 «auszahlbar», das Bankkonto
    stand auf null; zwei Auszahlungen à 15'000 liessen die Bank auf −30'000 fallen).

    Die Liquiditätsbasis zählt deshalb nur Bewegungen, bei denen Geld geflossen ist,
    für die Liegenschaften DIESES Eigentümers:

      eingegangen   Zahlungen auf Mietforderungen (`Bank/Durchlauf/Guthaben an 1100`)
                    und direkt gebuchte Erträge (`Bank an Ertragskonto`), abzüglich
                    ihrer Stornos
      bezahlt       Zahlungen an Lieferanten (`2000 an Bank`) und direkt bezahlter
                    Aufwand (`Aufwand an Bank`), abzüglich ihrer Stornos
      ausbezahlt    frühere Auszahlungen an diesen Eigentümer
      verfuegbar  = eingegangen − bezahlt − ausbezahlt

    AUSGESCHLOSSEN, weil es nicht dem Eigentümer gehört oder nicht fliesst:
      · Kautionen (Konten 1015/2010) — Geld der Mieter, Art. 257e OR
      · Mieterguthaben und ungeklärte Zahlungen, bis sie einer Forderung zugeordnet
        sind (Konten 2030/1190)
      · nicht bezahlte Mieten und nicht bezahlte Rechnungen
      · Abschlussbuchungen (Jahresabschluss ändert nichts am Geld)

    Die ERTRAGSBASIS bleibt als zweite, strengere Grenze erhalten: Auszahlbar ist
    `min(verfuegbar, Saldo des Kontokorrents)`. Sie fängt ab, was die Liquidität nicht
    sieht, aber der Eigentümer bereits trägt — gebuchtes Verwaltungshonorar,
    Einlagen in den Erneuerungsfonds, freigegebene, noch unbezahlte Rechnungen.
    Sie kann den Betrag nur senken, nie erhöhen.

    WAS FACHLICH OFFEN IST (nicht geraten, siehe Bericht):
      · MWST: In einer bezahlten Miete steckt die geschuldete Steuer (Konto 2200). Sie
        wird hier nicht abgezogen; die Ertragsbasis begrenzt nur, soweit der Aufwand
        sie nicht deckt. Ob die Verwaltung sie vor einer Auszahlung zurückstellen muss,
        ist eine Entscheidung der Treuhandstelle.
      · Fremdgelder: Wie viel Reserve eine Verwaltung zurückbehalten muss (Treuhandpflicht,
        Instandhaltung), ist nicht im Gesetz, sondern im Mandatsvertrag festgelegt.
      · Zahlungen ohne Liegenschaft (manuelle Bankbuchungen) zählen nicht — zu wenig
        ist hier die sichere Richtung.

    Gibt ein dict zurück: `eingegangen`, `bezahlt`, `ausbezahlt`, `verfuegbar`,
    `kontokorrent_offen`, `auszahlbar` (nie negativ).
    """
    from django.db.models import Sum
    from finance.booking import ist_bankkonto
    from finance.models import Buchung, Buchungskonto, EigentuemerAuszahlung
    from portfolio.models import Liegenschaft
    from core.services.jahresabschluss import abschluss_buchungen_q

    lg_ids = list(Liegenschaft.objects.filter(eigentuemer=eigentuemer).values_list('pk', flat=True))
    konten = list(Buchungskonto.objects.all())
    bank = {k.pk for k in konten if ist_bankkonto(k)}
    park = {k.pk for k in konten if k.nummer in _PARKKONTEN}
    forderung = {k.pk for k in konten if k.nummer == '1100'}
    kreditor = {k.pk for k in konten if k.nummer == '2000'}
    ertrag = {k.pk for k in konten if k.typ == 'ertrag'}
    aufwand = {k.pk for k in konten if k.typ == 'aufwand'}

    bank_oder_park = bank | park
    eingegangen = bezahlt = Decimal('0.00')
    zeilen = (Buchung.objects.filter(liegenschaft_id__in=lg_ids)
              .exclude(abschluss_buchungen_q())
              .order_by().values('soll_konto_id', 'haben_konto_id').annotate(t=Sum('betrag')))
    for z in zeilen:
        s, h, t = z['soll_konto_id'], z['haben_konto_id'], z['t']
        if s in bank_oder_park and h in forderung:
            eingegangen += t
        elif s in forderung and h in bank_oder_park:
            eingegangen -= t
        elif s in bank and h in ertrag:
            eingegangen += t
        elif s in ertrag and h in bank:
            eingegangen -= t
        elif s in kreditor and h in bank:
            bezahlt += t
        elif s in bank and h in kreditor:
            bezahlt -= t
        elif s in aufwand and h in bank:
            bezahlt += t
        elif s in bank and h in aufwand:
            bezahlt -= t

    ausbezahlt = (EigentuemerAuszahlung.objects.filter(eigentuemer=eigentuemer, status='verbucht')
                  .aggregate(t=Sum('betrag'))['t'] or Decimal('0.00'))
    verfuegbar = eingegangen - bezahlt - ausbezahlt
    kk_offen = kontokorrent(eigentuemer)['offen']
    return {
        'eingegangen': eingegangen, 'bezahlt': bezahlt, 'ausbezahlt': ausbezahlt,
        'verfuegbar': verfuegbar, 'kontokorrent_offen': kk_offen,
        'auszahlbar': max(Decimal('0.00'), min(verfuegbar, kk_offen)),
    }


def auszahlungs_stand(eigentuemer):
    """Fingerabdruck der bisherigen Auszahlungen (Anzahl und letzte Nummer).

    Die Maske schickt ihn mit; stimmt er beim Absenden nicht mehr, hat jemand
    inzwischen ausbezahlt — meist die eigene erste Anfrage eines Doppelklicks."""
    from django.db.models import Count, Max
    from finance.models import EigentuemerAuszahlung
    a = EigentuemerAuszahlung.objects.filter(eigentuemer=eigentuemer).aggregate(n=Count('id'), m=Max('id'))
    return f"{a['n']}-{a['m'] or 0}"


def buche_auszahlung(eigentuemer, betrag, *, bank, datum, bemerkung='', user=None, stand=None):
    """Bucht eine Auszahlung an den Eigentümer: Soll 2850 / Haben Bank.

    Atomar und gesperrt (Audit FIN-03): Die Deckungsprüfung und die Buchung laufen
    unter derselben Sperre, die alle Auszahlungen dieser Verwaltung hintereinander
    stellt — das Bankkonto ist ein gemeinsames. Zwei parallele Auszahlungen à 15'000
    liessen es vorher auf −30'000 fallen.

    Geprüft wird, in dieser Reihenfolge:
      · das Konto ist ein Bankkonto und nicht das Kautionssperrkonto 1015
      · der Stand der Maske stimmt noch (Doppelklick)
      · der Betrag liegt innerhalb von `liquiditaet()['auszahlbar']`
      · das Bankkonto deckt den Betrag

    Wirft `AuszahlungNichtMoeglich` mit einer Meldung für den Benutzer, oder
    `PermissionError` bei gesperrter Buchungsperiode. Gibt die Buchung zurück.
    """
    from django.db import transaction
    from django.utils.translation import gettext as _
    from core.sperren import sperre_organisation
    from finance.booking import buche, ist_bankkonto, kontosaldo
    from finance.models import EigentuemerAuszahlung

    if betrag <= 0:
        raise AuszahlungNichtMoeglich(_('Betrag muss grösser als 0 sein.'))
    if not ist_bankkonto(bank):
        raise AuszahlungNichtMoeglich(_(
            'Konto %(nummer)s ist kein Bankkonto für Auszahlungen. Das Kautionssperrkonto (1015) '
            'gehört den Mietern und kann nicht für Eigentümerauszahlungen benutzt werden.')
            % {'nummer': bank.nummer})
    with transaction.atomic():
        sperre_organisation('eigentuemer_auszahlung', eigentuemer.organisation_id)
        if stand is not None and stand != auszahlungs_stand(eigentuemer):
            raise AuszahlungNichtMoeglich(_(
                'Seit dem Öffnen der Maske wurde für diesen Eigentümer eine Auszahlung erfasst — '
                'vermutlich dieselbe. Bitte die Seite neu laden; es wurde nichts doppelt gebucht.'))
        liq = liquiditaet(eigentuemer)
        if betrag > liq['auszahlbar']:
            raise AuszahlungNichtMoeglich(_(
                'Auszahlbar sind höchstens CHF %(auszahlbar)s (eingegangene Mittel abzüglich bezahlter '
                'Kosten und bisheriger Auszahlungen). Verlangt: CHF %(betrag)s.')
                % {'auszahlbar': liq['auszahlbar'], 'betrag': betrag})
        saldo = kontosaldo(bank)
        if betrag > saldo:
            raise AuszahlungNichtMoeglich(_(
                'Das Bankkonto %(nummer)s deckt die Auszahlung nicht: Saldo CHF %(saldo)s, '
                'verlangt CHF %(betrag)s.') % {'nummer': bank.nummer, 'saldo': saldo, 'betrag': betrag})
        # VIER-AUGEN-PRINZIP (Etappe 4): Ab der Freigabelimite braucht die Auszahlung die Freigabe
        # einer zweiten Person. Die Freigabe wird in dieser Transaktion verbraucht; fehlt sie, wird
        # nichts gebucht (`AuszahlungGesperrt`). Die Prüfung steht im Dienst, damit auch ein Command
        # oder eine andere Ansicht sie trifft.
        from finance.freigabe import auszahlung_pruefen
        auszahlung_pruefen('eigentuemer', eigentuemer.pk, betrag, eigentuemer.iban,
                           organisation=eigentuemer.organisation, bezug_text=eigentuemer.firma_oder_name)
        buchung = buche('2850', bank, betrag,
                        f"Auszahlung Eigentümer {eigentuemer.firma_oder_name}"
                        + (f" — {bemerkung}" if bemerkung else ""),
                        datum=datum, user=user)
        EigentuemerAuszahlung.objects.create(
            eigentuemer=eigentuemer, betrag=betrag, datum=datum, konto=bank,
            bemerkung=bemerkung, erstellt_von=user)
    return buchung


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


@nur_deutsch
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
