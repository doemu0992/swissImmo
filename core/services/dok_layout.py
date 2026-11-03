"""Grundlayout der von Hand gezeichneten PDF-Dokumente (reportlab), Welle 2.

Das Gegenstück zu `core/templates/core/dok_base.html` (Welle 1, xhtml2pdf): derselbe
Briefkopf (Logo oder Firmenname links, Anschrift und Kontakt rechts, Linie in der Akzentfarbe
der Verwaltung), derselbe Seitenkopf ab Seite 2 (Titel links, Referenz rechts), dieselbe
Fusszeile («… · erstellt am …», «Seite x von y») und bei Briefen dasselbe Adressfenster
(Schweizer C5/6 mit Fenster RECHTS, SN 010130: 11.8 cm von links, 4.5 cm von oben).

Gebrauch: `DokCanvas(buf, organisation=org, titel='Mieterkonto', ref='…')` statt
`canvas.Canvas(buf, pagesize=A4)`. Alles Weitere (Inhalte, Texte, Beträge) bleibt beim Aufrufer.

* Briefe: `y = c.brief(empfaenger_zeilen, ort_datum, betreff)` zeichnet Fenster, Datum und Betreff
  und gibt die Höhe zurück, ab der der Text beginnt.
* Berichte, Abrechnungen, Verträge: `y = c.Y_INHALT` ist die Höhe unter dem Briefkopf der
  ersten Seite; ab Seite 2 beginnt der Inhalt bei `Y_FOLGE`.
* Der untere Rand des Inhalts ist `UNTEN` (die Fusszeile steht darunter).
* Seiten mit Einzahlungsschein (QR-Rechnung nach Swiss QR Bill) bekommen keine Fusszeile:
  `c.ohne_fuss()` vor dem Zeichnen — der Zahlteil füllt die untere Seitenhälfte.
* Sammel-PDF (eine Abrechnung je Mieter): `c.neues_dokument()` auf der ersten Seite jedes
  weiteren Dokuments, damit die Zählung «Seite x von y» je Dokument läuft.

Die Briefkopf-Werte kommen aus `core/services/briefkopf.briefkopf_kontext` (Organisation DES
Datensatzes, nie ein Singleton). Ist keine Organisation da (Eigentümer ohne Verwaltung, Mieter
als Absender), setzt der Aufrufer `absender=[name, strasse, plz_ort]`.
"""
from django.utils.translation import gettext as _
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from core.services.briefkopf import briefkopf_kontext
from core.zeit import datum_heute

#: Neutrales Dunkelgrau, wenn die Verwaltung keine Akzentfarbe hinterlegt hat (wie `_dok_stil.html`).
AKZENT_STANDARD = '#1f2937'
TEXT = HexColor('#111827')
GRAU = HexColor('#374151')
GRAU_HELL = HexColor('#4b5563')
LINIE = HexColor('#9ca3af')

LINKS = 20 * mm
RECHTS = 190 * mm
#: Obere Kante des Inhalts ab Seite 2 (unter dem Seitenkopf).
Y_FOLGE = 272 * mm
#: Unterkante des Inhalts (darunter steht die Fusszeile).
UNTEN = 26 * mm
#: Adressfenster C5/6 rechts: linke Kante und obere Kante (von oben gemessen).
FENSTER_X = 118 * mm
FENSTER_OBEN = 45 * mm


def _kuerzen(text, schrift, groesse, breite):
    """Kürzt `text` mit «…» auf `breite` (pt)."""
    text = text or ''
    if stringWidth(text, schrift, groesse) <= breite:
        return text
    while text and stringWidth(text + '…', schrift, groesse) > breite:
        text = text[:-1]
    return text.rstrip() + '…'


class DokCanvas(canvas.Canvas):
    def __init__(self, filename, *, organisation=None, absender=None, titel='', ref='', fuss=None,
                 logo=None, pagesize=A4, rand=LINKS, **kw):
        super().__init__(filename, pagesize=pagesize, **kw)
        self._saved = []
        self._flags = []
        self._flag = {}
        self.breite, self.hoehe = pagesize
        self.links = rand
        self.rand_rechts = self.breite - rand
        self.seite_nr = 1
        self.titel_kopf = titel
        self.ref_kopf = ref
        self.fuss_text = fuss
        bk = briefkopf_kontext(organisation) if organisation is not None else {}
        if not bk and absender:
            zeilen = [z for z in absender if z]
            bk = {'firma': zeilen[0] if zeilen else '', 'strasse': zeilen[1] if len(zeilen) > 1 else '',
                  'plz_ort': zeilen[2] if len(zeilen) > 2 else '', 'telefon': '', 'email': '',
                  'logo_pfad': '', 'logo_breite': 0, 'logo_hoehe': 0, 'farbe': '', 'fusszeile': ''}
        if logo and not bk.get('logo_pfad'):
            from core.services.briefkopf import _logo_masse
            breite, hoehe_logo = _logo_masse(logo)
            bk = dict(bk, logo_pfad=logo if hoehe_logo else '', logo_breite=breite, logo_hoehe=hoehe_logo)
        self.bk = bk
        self.akzent = HexColor(bk.get('farbe') or AKZENT_STANDARD)
        self._rechts = self._rechte_zeilen()
        logo_h = bk.get('logo_hoehe') or 0
        hoehe_kopf = max(logo_h or 20.0, len(self._rechts) * 11.5)
        #: y der Linie unter dem Briefkopf (Seite 1)
        self.y_linie = self.hoehe - 15 * mm - hoehe_kopf - 7
        #: obere Kante des Inhalts auf Seite 1 (Berichte, Abrechnungen, Verträge)
        self.Y_INHALT = self.y_linie - 9 * mm
        self.Y_FOLGE = Y_FOLGE if self.hoehe > 400 else self.hoehe - 25 * mm
        self.UNTEN = UNTEN
        self.LINKS = rand
        self.RECHTS = self.rand_rechts

    # ---- Seitenverwaltung -------------------------------------------------

    def ohne_fuss(self):
        """Diese Seite trägt keine Fusszeile (Einzahlungsschein füllt den Fuss)."""
        self._flag['ohne_fuss'] = True

    def neues_dokument(self):
        """Die aktuelle Seite beginnt ein neues Dokument (Seitenzählung und Briefkopf von vorn)."""
        self._flag['neu'] = True

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self.seite_nr += 1
        self._flags.append(self._flag)
        self._flag = {}
        self._startPage()

    def save(self):
        if self._code:
            self.showPage()
        # Dokumente (Folgen von Seiten ab einer mit `neu`) nummerieren
        gruppen = []
        for i, flags in enumerate(self._flags):
            if i == 0 or flags.get('neu'):
                gruppen.append([])
            gruppen[-1].append(i)
        nr, gesamt = {}, {}
        for g in gruppen:
            for k, i in enumerate(g, 1):
                nr[i], gesamt[i] = k, len(g)
        zustaende, flags_alle = self._saved, self._flags
        for i, zustand in enumerate(zustaende):
            self.__dict__.update(zustand)
            flags = flags_alle[i]
            if nr[i] == 1:
                self._briefkopf()
            else:
                self._seitenkopf()
            if not flags.get('ohne_fuss'):
                self._fuss(nr[i], gesamt[i])
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    # ---- Briefkopf, Seitenkopf, Fuss -----------------------------------------

    def _rechte_zeilen(self):
        bk = self.bk
        zeilen = []
        if bk.get('logo_pfad') and bk.get('firma'):
            zeilen.append(('b', bk['firma']))
        if bk.get('strasse'):
            zeilen.append(('n', bk['strasse']))
        if bk.get('plz_ort'):
            zeilen.append(('n', bk['plz_ort']))
        if bk.get('telefon'):
            zeilen.append(('n', bk['telefon']))
        if bk.get('email'):
            zeilen.append(('n', bk['email']))
        return zeilen

    def _briefkopf(self):
        bk, h = self.bk, self.hoehe
        if not bk:
            return
        oben = h - 15 * mm
        logo = bk.get('logo_pfad')
        gezeichnet = False
        if logo:
            try:
                b, hh = bk.get('logo_breite') or 0, bk.get('logo_hoehe') or 0
                if b and hh:
                    self.drawImage(logo, self.links, oben - hh, width=b, height=hh, mask='auto')
                else:
                    self.drawImage(logo, self.links, oben - 40, height=40, preserveAspectRatio=True, mask='auto')
                gezeichnet = True
            except Exception:  # noqa: BLE001 — unlesbares Logo: Firmenname statt kein Dokument
                gezeichnet = False
                self._rechts = self._rechte_zeilen()
        if not gezeichnet and bk.get('firma'):
            self.setFillColor(self.akzent)
            self.setFont('Helvetica-Bold', 14)
            self.drawString(self.links, oben - 14, bk['firma'])
        y = oben - 8.5
        for art, text in self._rechts:
            self.setFillColor(GRAU)
            self.setFont('Helvetica-Bold' if art == 'b' else 'Helvetica', 8.5)
            self.drawRightString(self.rand_rechts, y, text)
            y -= 11.5
        self.setStrokeColor(self.akzent)
        self.setLineWidth(1.5)
        self.line(self.links, self.y_linie, self.rand_rechts, self.y_linie)
        self.setFillColor(TEXT)
        self.setStrokeColor(TEXT)
        self.setLineWidth(1)

    def _seitenkopf(self):
        if not (self.titel_kopf or self.ref_kopf):
            return
        y = self.hoehe - 11 * mm
        self.setFillColor(GRAU)
        self.setFont('Helvetica', 8.5)
        gesamt = self.rand_rechts - self.links
        ref = _kuerzen(self.ref_kopf, 'Helvetica', 8.5, gesamt * 0.4)
        titel = _kuerzen(self.titel_kopf, 'Helvetica', 8.5, gesamt - stringWidth(ref, 'Helvetica', 8.5) - 12)
        self.drawString(self.links, y, titel)
        self.drawRightString(self.rand_rechts, y, ref)
        self.setStrokeColor(self.akzent)
        self.setLineWidth(0.75)
        self.line(self.links, y - 4, self.rand_rechts, y - 4)
        self.setFillColor(TEXT)
        self.setStrokeColor(TEXT)
        self.setLineWidth(1)

    def _fuss(self, nr, gesamt):
        bk = self.bk
        text = self.fuss_text
        if text is None:
            teile = [bk.get('firma', '')]
            adr = ', '.join(t for t in (bk.get('strasse', ''), bk.get('plz_ort', '')) if t)
            if adr:
                teile.append(adr)
            text = ' · '.join(t for t in teile if t)
        links = ' · '.join(t for t in (text, _('erstellt am %(datum)s') % {'datum': datum_heute().strftime('%d.%m.%Y')}) if t)
        seite = (_('Seite <pdf:pagenumber> von <pdf:pagecount>')
                 .replace('<pdf:pagenumber>', str(nr)).replace('<pdf:pagecount>', str(gesamt)))
        y = 13.5 * mm
        self.setStrokeColor(LINIE)
        self.setLineWidth(0.5)
        self.line(self.links, y + 9, self.rand_rechts, y + 9)
        self.setFillColor(GRAU_HELL)
        if bk.get('fusszeile'):
            self.setFont('Helvetica', 7.5)
            self.drawString(self.links, y + 13, _kuerzen(bk['fusszeile'], 'Helvetica', 7.5, self.rand_rechts - self.links))
        self.setFont('Helvetica', 7.5)
        self.drawString(self.links, y, _kuerzen(links, 'Helvetica', 7.5, self.rand_rechts - self.links - stringWidth(seite, 'Helvetica', 7.5) - 12))
        self.drawRightString(self.rand_rechts, y, seite)
        self.setFillColor(TEXT)
        self.setStrokeColor(TEXT)
        self.setLineWidth(1)

    # ---- Briefe -----------------------------------------------------------

    def fenster(self, zeilen, absenderzeile=None):
        """Empfängerfeld im Fenster rechts (C5/6). `absenderzeile` steht 7 pt klein darüber;
        Vorgabe: Firma · Strasse · PLZ Ort des Briefkopfs."""
        bk = self.bk
        if absenderzeile is None:
            absenderzeile = ' · '.join(t for t in (bk.get('firma', ''), bk.get('strasse', ''), bk.get('plz_ort', '')) if t)
        y = self.hoehe - FENSTER_OBEN - 8
        self.setFont('Helvetica', 7)
        self.setFillColor(GRAU_HELL)
        self.drawString(FENSTER_X, y, absenderzeile[:70])
        self.setStrokeColor(LINIE)
        self.setLineWidth(0.5)
        self.line(FENSTER_X, y - 2, FENSTER_X + 85 * mm, y - 2)
        self.setFillColor(TEXT)
        self.setFont('Helvetica', 10.5)
        y -= 14
        for z in [z for z in zeilen if z][:6]:
            self.drawString(FENSTER_X, y, z)
            y -= 12.5
        self.setStrokeColor(TEXT)
        self.setLineWidth(1)

    def brief(self, empfaenger, ort_datum, betreff, untertitel=None, einschreiben=False):
        """Fenster, Ort/Datum und Betreff. Gibt die Höhe zurück, ab der der Brieftext beginnt."""
        self.fenster(empfaenger)
        y = self.hoehe - 88 * mm
        if einschreiben:
            self.setFont('Helvetica-Bold', 10)
            self.drawString(self.links, self.hoehe - 55 * mm, einschreiben if isinstance(einschreiben, str) else 'Einschreiben')
        self.setFont('Helvetica', 9)
        self.setFillColor(GRAU)
        self.drawRightString(self.rand_rechts, y, ort_datum)
        self.setFillColor(TEXT)
        y -= 9 * mm
        self.setFont('Helvetica-Bold', 12)
        zeilen = simpleSplit(betreff, 'Helvetica-Bold', 12, self.rand_rechts - self.links) or ['']
        for i, z in enumerate(zeilen):
            if i:
                y -= 5.5 * mm
            self.drawString(self.links, y, z)
        if untertitel:
            y -= 6 * mm
            self.setFont('Helvetica-Bold', 10)
            self.drawString(self.links, y, untertitel)
        self.setFont('Helvetica', 10.5)
        return y - 9 * mm
