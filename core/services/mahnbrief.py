"""Das Schreiben der automatischen Mahnstufen — ehrlich beschriftet.

WARUM ES DAS GIBT (Stresstest 30.09.2026, Punkte 5–7)

Der Mahnlauf legte bei JEDER Stufe — schon der ersten nach 14 Tagen — ein PDF
«Zahlungsverzug gemäss Art. 257d OR – Kündigungsandrohung, 30 Tage» in der
Akte ab. Zugestellt wurde nur eine einfache Zahlungserinnerung per E-Mail. Die
Akte behauptete damit eine Fristansetzung, die nie stattgefunden hat, und nannte
für die Dezembermiete «Monat Februar», weil der Kalendermonat von heute
eingesetzt wurde.

Eine 257d-Fristansetzung ist ein eingeschriebener, unterschriebener Brief mit
Kündigungsandrohung (`fw_verzug_257d`). Die Mahnstufen davor sind Mahnungen,
nichts weiter. Dieses Modul erzeugt sie: mit dem Monat der Forderung, dem
offenen Betrag und — auf der letzten Stufe — dem ausdrücklichen Hinweis, dass die
formelle Fristansetzung separat folgt.

ÄNDERUNG 01.10.2026 (Entscheid der Verwaltung): Eine Stufe mit dem
Art.-257d-Häkchen verschickt GENAU das Schreiben «Zahlungsverzug gemäss
Art. 257d OR – Kündigungsandrohung» (Einschreiben, 30 Tage) — siehe
`mahnbrief_pdf`. Die Vorgabe aus dem Stresstest bleibt für die Stufen OHNE
Häkchen: Sie sind Mahnungen und drohen nichts an.
"""
import io

from core.services.dokumentsprache import nur_deutsch

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def monat_text(d):
    """«Dezember 2025» für ein Datum — der Monat der FORDERUNG, nicht der von heute."""
    return f"{MONATE[d.month - 1]} {d.year}"


def forderungs_monat(rechnung):
    """Monat der Forderung: Fälligkeit, sonst Rechnungsdatum."""
    d = rechnung.faellig_am or rechnung.datum
    return monat_text(d) if d else ''


#: Titel des Schreibens mit Kündigungsandrohung (steht so in `generate_mahnung_combined_pdf_bytes`).
TITEL_257D = "Zahlungsverzug gemäss Art. 257d OR – Kündigungsandrohung"


def _ist_erste_stufe(vertrag, stufe):
    """Ist `stufe` die niedrigste Stufe der Organisation — also die erste Mahnung?

    Der Ton des Schreibens hängt davon ab, nicht von der Nummer: Hat die Verwaltung
    nur EINE Stufe (oder die Stufe 1 gelöscht), ist die niedrigste trotzdem die erste."""
    from crm.models import MahnStufe
    return not (MahnStufe.alle_organisationen
                .filter(organisation_id=vertrag.organisation_id, stufe__lt=stufe).exists())


def titel_fuer(vertrag, stufe, letzte_stufe=False):
    """Titel des Mahnschreibens (auch Betreff der Kopie per E-Mail, Text der QR-Rechnung).

    * Stufe mit Art.-257d-Häkchen: der Titel des 257d-Schreibens, unveränderbar
      (das Schreiben selbst ist fest, siehe `mahnbrief_pdf`);
    * sonst der Titel der Verwaltung (`MahnStufe.brief_titel`);
    * sonst die erste Stufe «Zahlungserinnerung», alle weiteren «N. Mahnung».
    """
    if letzte_stufe:
        return TITEL_257D
    eigene = _eigener_brief(vertrag, stufe)
    if eigene and eigene.brief_titel:
        return eigene.brief_titel
    return "Zahlungserinnerung" if _ist_erste_stufe(vertrag, stufe) else f"{stufe}. Mahnung"


def _eigener_brief(vertrag, stufe):
    """Die Stufe der Organisation des Vertrags (Titel/Text der Verwaltung) — oder None."""
    from crm.models import MahnStufe
    # alle_organisationen mit ausdrücklichem Organisationsfilter: Das Schreiben
    # entsteht auch im Scheduler ohne Anfrage; die Grenze steht im Ausdruck.
    return (MahnStufe.alle_organisationen
            .filter(organisation_id=vertrag.organisation_id, stufe=stufe).first())


class _Platzhalter(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def _eigener_text(vorlage, **werte):
    """Setzt {monat} {betrag} {gebuehr} {mieter} ein; unbekannte Platzhalter bleiben stehen.
    Absätze bleiben erhalten, lange Zeilen werden auf Seitenbreite umbrochen."""
    import textwrap
    try:
        text = vorlage.format_map(_Platzhalter(werte))
    except (ValueError, IndexError):
        text = vorlage      # kaputte Klammern: Text unverändert statt Fehler beim Versand
    zeilen = []
    for absatz in text.splitlines():
        zeilen += textwrap.wrap(absatz, width=88) or [""]
    return zeilen


@nur_deutsch
def mahnbrief_pdf(vertrag, verwaltung, *, stufe, monat, betrag, datum,
                  gebuehr=None, letzte_stufe=False, rechnung=None):
    """Mahnschreiben der Stufe `stufe` als PDF-Bytes (Brief + QR-Rechnung).

    `letzte_stufe`: Die Stufe trägt das Art.-257d-Häkchen. Ihr Schreiben ist dann
    GENAU das bestehende Schreiben «Zahlungsverzug gemäss Art. 257d OR –
    Kündigungsandrohung» (Einschreiben, Zahlungsfrist 30 Tage, Kündigungsandrohung,
    mit QR-Rechnung) — `core.views.email_views.generate_mahnung_combined_pdf_bytes`,
    dieselbe Funktion wie beim Knopf «Mahnung mit Kündigungsandrohung». Der Wortlaut
    steht an EINER Stelle; er ist hier weder nachgebaut noch durch Titel/Text der
    Verwaltung (`brief_titel`, `brief_text`) veränderbar.
    """
    if letzte_stufe:
        # Ein als Mieter erfasster Stockwerkeigentümer bekommt nie das 257d-Schreiben: es wird ein gewöhnliches
        # Mahnschreiben der Stufe (siehe `core.services.zahlungsverzug.eigentuemer_als_mieter`).
        from core.services.zahlungsverzug import eigentuemer_als_mieter
        if eigentuemer_als_mieter(vertrag) is not None:
            letzte_stufe = False
    if letzte_stufe:
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        # Die Mahngebühr der Stufe steht im Brief und hat einen eigenen Einzahlungsschein;
        # dessen QRR ist die der Gebührenforderung (`stammrechnung` = die gemahnte Forderung).
        # Gibt es sie noch nicht (Vorschau vor «Erfassen»), bleibt die Referenz leer.
        gebuehr_ref = None
        if gebuehr and gebuehr > 0 and rechnung is not None:
            folge = (rechnung.folgeforderungen.filter(titel__icontains='Mahngebühr').exclude(status='storniert')
                     .order_by('-id').first())
            gebuehr_ref = (folge.qr_referenz if folge else None) or None
        return generate_mahnung_combined_pdf_bytes(
            vertrag, verwaltung, monat, betrag, datum,
            reference=getattr(rechnung, 'qr_referenz', None) or None,
            gebuehr=gebuehr, gebuehr_reference=gebuehr_ref)

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from core.utils.qr_code import draw_qr_bill

    m = vertrag.mieter
    eigene = _eigener_brief(vertrag, stufe)
    erste = _ist_erste_stufe(vertrag, stufe)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    links = 25 * mm
    fenster = 120 * mm

    if verwaltung:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(links, 280 * mm, verwaltung.firma)
        c.setFont("Helvetica", 9)
        c.drawString(links, 275 * mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")

    y = 250 * mm
    c.setFont("Helvetica", 11)
    if getattr(m, 'firma', None):
        c.drawString(fenster, y, m.firma); y -= 5 * mm
    c.drawString(fenster, y, f"{m.vorname} {m.nachname}".strip())
    c.drawString(fenster, y - 5 * mm, m.strasse or '')
    c.drawString(fenster, y - 10 * mm, f"{m.plz} {m.ort}")

    c.setFont("Helvetica", 10)
    c.drawString(links, 210 * mm, f"{verwaltung.ort if verwaltung else ''}, {datum:%d.%m.%Y}")
    c.setFont("Helvetica-Bold", 12)
    titel = titel_fuer(vertrag, stufe, letzte_stufe)
    c.drawString(links, 195 * mm, titel)
    c.setFont("Helvetica-Bold", 10)
    e = vertrag.einheit
    c.drawString(links, 189 * mm, f"Mietobjekt: {e.bezeichnung}, {e.liegenschaft.strasse}")

    anrede = getattr(m, 'anrede', '')
    if anrede == "Herr":
        gruss = f"Sehr geehrter Herr {m.nachname},"
    elif anrede == "Frau":
        gruss = f"Sehr geehrte Frau {m.nachname},"
    else:
        gruss = "Sehr geehrte Damen und Herren,"

    zeilen = [gruss, ""]
    if eigene and eigene.brief_text.strip():
        # Wortlaut der Verwaltung (crm.MahnStufe.brief_text) statt des Standardtexts.
        zeilen += _eigener_text(eigene.brief_text, monat=monat, betrag=betrag,
                                gebuehr=f"{gebuehr:.2f}" if gebuehr else "0.00",
                                mieter=f"{m.vorname} {m.nachname}".strip())
    elif erste:
        zeilen += [f"bei der Kontrolle unserer Zahlungseingänge haben wir festgestellt, dass für",
                   f"{monat} noch CHF {betrag} ausstehend sind.", "",
                   "Sicher haben Sie die Zahlung nur übersehen. Wir bitten Sie, den Betrag",
                   "in den nächsten Tagen zu überweisen."]
    else:
        zeilen += [f"trotz unserer früheren Schreiben ist die Forderung für {monat} über",
                   f"CHF {betrag} weiterhin offen.", "",
                   "Wir bitten Sie, den Betrag umgehend zu überweisen."]
    if gebuehr and gebuehr > 0:
        zeilen += ["", f"Für diese Mahnung stellen wir eine Mahngebühr von CHF {gebuehr:.2f} in Rechnung."]
    zeilen += ["", "Hat sich Ihre Zahlung mit diesem Schreiben gekreuzt, betrachten Sie es",
               "bitte als gegenstandslos.", "", "Freundliche Grüsse", "",
               verwaltung.firma if verwaltung else "Die Vermieterschaft"]

    ty = 175 * mm
    for zeile in zeilen:
        c.setFont("Helvetica", 11)
        c.drawString(links, ty, zeile)
        ty -= 5.5 * mm

    lg = e.liegenschaft
    iban = getattr(lg, 'iban', None) or getattr(verwaltung, 'iban', None)
    if iban:
        try:
            c.showPage()
            if verwaltung:
                creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse,
                            'line2': f"{verwaltung.plz} {verwaltung.ort}",
                            'plz': verwaltung.plz or '', 'ort': verwaltung.ort or ''}
            else:
                creditor = {'name': "Verwaltung", 'line1': lg.strasse,
                            'line2': f"{lg.plz} {lg.ort}"}
            debtor = {'name': (getattr(m, 'firma', None) or f"{m.vorname} {m.nachname}").strip(),
                      'line1': m.strasse or '', 'line2': f"{m.plz} {m.ort}"}
            draw_qr_bill(c, iban, creditor, debtor, float(str(betrag).replace(',', '.')),
                         f"{titel} {monat} {e.bezeichnung}",
                         reference=getattr(rechnung, 'qr_referenz', None) or None)
        except Exception:
            pass
    c.save()
    buffer.seek(0)
    return buffer.getvalue()
