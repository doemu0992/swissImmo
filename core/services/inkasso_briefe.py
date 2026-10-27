"""Inkasso-Dokumente als PDF (reportlab): Zahlungsvereinbarung mit Schuldanerkennung
und Daten für das Betreibungsbegehren.

Gebaut wie die übrigen Geschäftsbriefe (`mietprozess_briefe`, `mahnbrief`):
reportlab-Canvas, Absender aus der Organisation DES Datensatzes (nie ein
Singleton), fest deutsch (`nur_deutsch`) bis zur geprüften Übersetzung — die Texte
sind Rechtstexte. Beide Dokumente sind länger als ein Brief und brechen deshalb
über `_Seite` auf eine Folgeseite um, statt unten aus dem Blatt zu laufen.

WAS DIESE DOKUMENTE NICHT SIND

* Die Zahlungsvereinbarung ist eine Vorlage der Verwaltung. Ihr Wortlaut ist
  nicht juristisch geprüft; Verzugsfolgen und Vorbehalt Art. 257d OR stehen
  so, wie die Anwendung sie umsetzt (`core/services/zahlungsvereinbarung.py`).
* Das Betreibungsbegehren ist KEIN amtliches Formular. Das Begehren stellt der
  Gläubiger auf dem Formular des Betreibungsamts bzw. über eSchKG. Dieses Blatt
  sammelt die Angaben dafür und sagt das in Titel und Fusszeile.
"""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.services.dokumentsprache import nur_deutsch
from core.services.mietprozess_briefe import _fr, _kontext, _wrap

LINKS = 25 * mm
RECHTS = 185 * mm
UNTEN = 25 * mm


class _Seite:
    """Schreibkopf mit Zeilenvorschub und Seitenumbruch."""

    def __init__(self, c, y=270 * mm):
        self.c, self.y = c, y

    def platz(self, hoehe):
        if self.y - hoehe < UNTEN:
            self.c.showPage()
            self.y = 270 * mm

    def zeile(self, text, *, fett=False, groesse=10, x=LINKS, abstand=5 * mm):
        self.platz(abstand)
        self.c.setFont("Helvetica-Bold" if fett else "Helvetica", groesse)
        self.c.drawString(x, self.y, text)
        self.y -= abstand

    def absatz(self, text, *, fett=False, groesse=10, breite=95, nach=2.5 * mm):
        for z in _wrap(text, breite):
            self.zeile(z, fett=fett, groesse=groesse, abstand=4.8 * mm)
        self.y -= nach

    def tabelle(self, kopf, zeilen, spalten, rechtsbuendig=()):
        """Einfache Tabelle; `spalten` sind x-Positionen, `rechtsbuendig` Spaltenindizes."""
        def reihe(werte, fett):
            self.platz(5 * mm)
            self.c.setFont("Helvetica-Bold" if fett else "Helvetica", 9.5)
            for i, (x, w) in enumerate(zip(spalten, werte)):
                if i in rechtsbuendig:
                    self.c.drawRightString(x, self.y, w)
                else:
                    self.c.drawString(x, self.y, w)
            self.y -= 4.8 * mm
        reihe(kopf, True)
        self.c.line(LINKS, self.y + 3.4 * mm, RECHTS, self.y + 3.4 * mm)
        for z in zeilen:
            reihe(z, False)
        self.y -= 2 * mm

    def unterschrift(self, links_text, rechts_text):
        self.platz(30 * mm)
        self.y -= 14 * mm
        self.c.line(LINKS, self.y, LINKS + 70 * mm, self.y)
        self.c.line(110 * mm, self.y, RECHTS, self.y)
        self.y -= 4.5 * mm
        self.c.setFont("Helvetica", 9)
        self.c.drawString(LINKS, self.y, links_text)
        self.c.drawString(110 * mm, self.y, rechts_text)
        self.y -= 6 * mm


def _datum(d):
    return d.strftime('%d.%m.%Y') if d else '—'


@nur_deutsch
def zahlungsvereinbarung_pdf(vb):
    """Zahlungsvereinbarung mit Schuldanerkennung für den Mieter (zweifach zu unterzeichnen)."""
    from core.services import zahlungsvereinbarung as zv
    from core.services.zahlungsverzug import aktive_fristen

    v = vb.vertrag
    mieter, einheit, lg, absender, ort, empf, objekt, _name, (eig, vw) = _kontext(v, v.organisation)
    vermieter = (eig.firma_oder_name if eig else (vw.firma if vw else 'Die Vermieterschaft'))
    vertreten = (vw.firma if (eig and vw) else '')

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Zahlungsvereinbarung mit Schuldanerkennung")
    c.setFont("Helvetica", 8)
    c.drawString(LINKS, 280 * mm, ' · '.join(z for z in absender if z))
    s = _Seite(c, 255 * mm)
    for z in empf:
        s.zeile(z, x=120 * mm, groesse=11, abstand=5.2 * mm)
    s.y -= 6 * mm
    from django.utils import timezone
    s.zeile(f"{ort}, {_datum(timezone.localtime(vb.erfasst_am).date() if vb.erfasst_am else None)}", x=120 * mm)
    s.y -= 6 * mm
    s.zeile("Zahlungsvereinbarung mit Schuldanerkennung", fett=True, groesse=13, abstand=8 * mm)

    s.zeile("Parteien", fett=True)
    s.absatz(f"Vermieterin / Gläubigerin: {vermieter}"
             + (f", vertreten durch {vertreten}" if vertreten else ''), nach=0)
    adr = mieter.zustelladresse() if hasattr(mieter, 'zustelladresse') else (mieter.strasse, '', mieter.plz, mieter.ort)
    s.absatz(f"Mieter / Schuldner: {mieter.display_name}, {adr[0] or ''}, {adr[2] or ''} {adr[3] or ''}".strip(', '),
             nach=0)
    s.absatz(f"Mietobjekt: {objekt}" if objekt else "Mietobjekt: —")

    s.zeile("1. Schuldanerkennung", fett=True)
    s.absatz(f"Der Mieter anerkennt, der Vermieterin aus dem Mietverhältnis für das obige Mietobjekt "
             f"den Betrag von CHF {_fr(vb.betrag_total)} zu schulden (Rückstand der bis "
             f"{_datum(vb.gedeckt_bis)} fälligen Mietzinse und Nebenkosten). Die Forderungen im Einzelnen:")
    forderungen = zv.gedeckte_forderungen(vb)
    s.tabelle(["Forderung", "Fällig am", "Offen (CHF)"],
              [[r.titel[:60], _datum(r.faellig_am or r.datum), _fr(offen)] for r, offen in forderungen]
              + [["Total", "", _fr(sum((o for _r, o in forderungen), Decimal('0.00')))]],
              [LINKS, 125 * mm, RECHTS], rechtsbuendig=(2,))

    s.zeile("2. Ratenplan", fett=True)
    s.absatz(f"Der Mieter bezahlt den anerkannten Betrag in {vb.anzahl_raten} Raten "
             f"im Abstand von {vb.intervall_monate} Monat(en):")
    s.tabelle(["Rate", "Fällig am", "Betrag (CHF)"],
              [[f"{nr}.", _datum(f), _fr(b)] for nr, f, b in zv.raten_plan(vb)],
              [LINKS, 125 * mm, RECHTS], rechtsbuendig=(2,))
    s.absatz("Die laufenden Mietzinse und Nebenkosten sind daneben unverändert und pünktlich zu bezahlen; "
             "sie sind nicht Teil dieser Vereinbarung.")

    s.zeile("3. Folgen eines Zahlungsverzugs", fett=True)
    s.absatz(f"Ist eine Rate mehr als {zv.TOLERANZ_TAGE} Tage nach ihrer Fälligkeit nicht vollständig "
             f"bezahlt, fällt der Ratenplan dahin. Der ganze noch offene Betrag ist dann sofort zur Zahlung "
             f"fällig, und die Vermieterin setzt das Mahnverfahren fort. Sie kann die Forderung in "
             f"Betreibung setzen und die gesetzlichen Rechte bei Zahlungsrückstand geltend machen "
             f"(Art. 257d OR).")
    if aktive_fristen(v).exists():
        s.absatz("Eine bereits angesetzte Zahlungsfrist nach Art. 257d OR wird durch diese Vereinbarung "
                 "nicht gehemmt, es sei denn, die Vermieterin verzichte ausdrücklich darauf.")

    s.zeile("4. Hinweis", fett=True)
    s.absatz("Eine unterzeichnete Schuldanerkennung ist ein provisorischer Rechtsöffnungstitel "
             "(Art. 82 SchKG): Erhebt der Mieter in einer Betreibung Rechtsvorschlag, kann die Vermieterin "
             "gestützt auf diese Urkunde die provisorische Rechtsöffnung verlangen.")
    if vb.notiz:
        s.absatz(f"Bemerkung: {vb.notiz}")

    s.zeile("Ort, Datum: ______________________________", abstand=6 * mm)
    s.unterschrift(f"Mieter: {mieter.display_name}"[:48],
                   (f"Vermieterin: {vermieter}" + (f" (vertr. durch {vertreten})" if vertreten else ''))[:58])
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


@nur_deutsch
def betreibungsbegehren_pdf(b):
    """Datenblatt (Vorlage) für das Betreibungsbegehren — nicht das amtliche Formular."""
    from core.services.betreibung import glaeubiger

    vertrag = b.vertrag or b.debitoren_rechnung.vertrag
    mieter = vertrag.mieter if vertrag is not None else None
    gl, vertreter = glaeubiger(b)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Betreibungsbegehren - Daten (Vorlage)")
    s = _Seite(c, 275 * mm)
    s.zeile("Betreibungsbegehren — Daten für das amtliche Formular", fett=True, groesse=13, abstand=6 * mm)
    s.absatz("Vorlage: Diese Seite ist NICHT das amtliche Betreibungsbegehren. Sie fasst die Angaben "
             "zusammen, die auf dem Formular des Betreibungsamts bzw. in eSchKG einzutragen sind.",
             groesse=9)
    if b.betreibungsamt:
        s.absatz(f"Betreibungsamt: {b.betreibungsamt}", fett=True)

    s.zeile("Gläubiger", fett=True)
    for z in gl:
        if z:
            s.zeile(z)
    s.y -= 2 * mm
    if vertreter:
        s.zeile("Vertreter des Gläubigers", fett=True)
        for z in vertreter:
            if z:
                s.zeile(z)
        s.y -= 2 * mm

    s.zeile("Schuldner", fett=True)
    if mieter is not None:
        adr = mieter.zustelladresse() if hasattr(mieter, 'zustelladresse') else (mieter.strasse, '', mieter.plz, mieter.ort)
        s.zeile(mieter.display_name)
        if adr[0]:
            s.zeile(adr[0])
        if adr[1]:
            s.zeile(adr[1])
        s.zeile(f"{adr[2] or ''} {adr[3] or ''}".strip())
        geb = getattr(mieter, 'geburtsdatum', None)
        if geb:
            s.zeile(f"Geburtsdatum: {_datum(geb)}")
    else:
        s.zeile("—")
    s.y -= 2 * mm

    s.zeile("Forderung", fett=True)
    s.zeile(f"Forderungsbetrag: CHF {_fr(b.forderung)}")
    if b.zinssatz and b.zins_ab:
        s.zeile(f"Zins: {b.zinssatz.normalize():f} % seit {_datum(b.zins_ab)}")
    elif b.zinssatz:
        s.zeile(f"Zins: {b.zinssatz.normalize():f} % — Zinsbeginn noch eintragen")
    s.y -= 1 * mm
    s.zeile("Forderungsurkunde / Grund der Forderung:", fett=True)
    s.absatz(b.forderungsgrund or "—")
    s.tabelle(["Forderung", "Fällig am", "Offen (CHF)"],
              [[r.titel[:60], _datum(r.faellig_am or r.datum), _fr(r.offener_betrag)] for r in b.rechnungen()],
              [LINKS, 125 * mm, RECHTS], rechtsbuendig=(2,))
    if b.bemerkung:
        s.zeile("Bemerkung", fett=True)
        s.absatz(b.bemerkung)

    c.setFont("Helvetica", 8)
    c.drawString(LINKS, 15 * mm, "Vorlage der Verwaltung, kein amtliches Formular. Massgebend ist das "
                                 "Betreibungsbegehren auf dem Formular des Betreibungsamts.")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
