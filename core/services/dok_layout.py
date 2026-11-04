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

# ---------------------------------------------------------------------------------------------------------------------
# ADRESSLAGE (Briefe für Fensterumschläge C5/6, Fenster rechts)
#
# HERKUNFT UND STAND DER PRÜFUNG, ehrlich:
# * ADRESSFELD (118 mm von links, 45 mm von oben): aus der Erinnerung an die Schweizer Briefnorm SN 010130 gesetzt,
#   NIE gegen die Norm oder einen echten Umschlag geprüft. Die Post-Spezifikation «Briefe – Gestaltung»
#   (post.ch/-/media/portal-opp/pm/dokumente/briefe-spezifikation-gestaltung.pdf) nennt keine Fensterkoordinaten für
#   C5/6; der Abruf war in der Umgebung der letzten Prüfung nicht möglich (403 des Proxys). Herstellerdatenblätter
#   (Couvert-Fabrik, Biella, Mayer-Bestpac) sind nicht eingesehen.
# * UMSCHLAGFENSTER (115 / 42 mm, 90 x 45 mm): eine ANNAHME, nicht gemessen. Sie liegt in der üblichen Spanne für
#   C5/6 mit Fenster rechts (links ca. 115–120 mm, oben ca. 42–50 mm, ca. 90–100 x 25–45 mm) und ist so gewählt, dass
#   das Adressfeld 3 mm Rand zum Fensterrand hat. Die Fensterprobe (`core/services/fensterprobe.py`) zeigt sie
#   zum Nachmessen am echten Umschlag; der Versatz in den Briefkopf-Einstellungen gleicht eine Abweichung aus.
# * Falzmarken bei 99 und 198 mm: A4 (297 mm) in drei gleiche Teile gefaltet, wie es in C5/6 (114 x 229 mm) passt.
#   (DIN 5008 kennt für C6/5 «Form B» 105/210 mm; das ist ein anderer Falz.)
# Alle Masse stehen hier und nur hier; `fenster()`, `brief()` und die Fensterprobe lesen sie.
# ---------------------------------------------------------------------------------------------------------------------
#: Adressfeld: linke Kante und obere Kante (von oben gemessen). Name bleibt FENSTER_*, weil Tests ihn kennen.
FENSTER_X = 118 * mm
FENSTER_OBEN = 45 * mm
#: Das Adressfeld endet am Textrand der Seite: Absenderlinie, Anschrift und Zustellvermerk sind gleich breit.
ADRESSFELD_BREITE = RECHTS - FENSTER_X
ADRESS_SCHRIFT = 10            # pt
ADRESS_SCHRIFT_MIN = 8         # pt: schmäler wird nicht geschrieben, darüber hinaus wird gekürzt
ADRESS_ZEILENABSTAND = 12      # pt
ADRESS_ZEILEN_MAX = 6          # mehr Zeilen passen nicht ins Fenster; weniger als 3 ist unüblich (Name, Strasse, Ort)
ADRESS_ZEILEN_MIN = 3
ABSENDER_SCHRIFT = 7           # pt: Rücksendeangabe über der Anschrift
#: Abstand der ersten Anschriftzeile unter der Oberkante des Adressfelds: Absenderzeile (8 pt), Linie, dann die Anschrift.
ABSENDER_GRUNDLINIE = 8        # pt unter FENSTER_OBEN
ADRESS_ERSTE_ZEILE = 22        # pt unter FENSTER_OBEN
#: Das Umschlagfenster (ANNAHME, siehe oben): links, oben, Breite, Höhe in mm.
UMSCHLAGFENSTER = (115.0, 42.0, 90.0, 45.0)
#: Mindestrand der Anschrift zum Fensterrand.
FENSTER_RAND_MIN = 3 * mm
#: Zustellvermerk («Einschreiben») über dem Adressfeld: Schrift, Grundlinie über der Oberkante des Adressfelds und
#: der geforderte Mindestabstand (Schriftunterkante) zur Briefkopflinie und zur Absenderzeile.
VERMERK_SCHRIFT = 10           # pt, fett
VERMERK_GRUNDLINIE = 5 * mm
VERMERK_ABSTAND_MIN = 4 * mm
#: Der Briefkopf eines Briefs reicht höchstens bis hierher (von oben gemessen): darunter ist der Streifen für den Vermerk.
KOPF_MAX_BRIEF = 30 * mm
LOGO_HOEHE_BRIEF = 32.0        # pt (ca. 11 mm); in Dokumenten ohne Adressfenster bleibt es bei 40 pt


def _versatz(organisation, feld):
    """Versatz der Adresslage in mm aus der Einstellung der Verwaltung; ohne Verwaltung oder Wert: 0."""
    try:
        return float(getattr(organisation, feld, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def adressfeld_masse(zeilen=ADRESS_ZEILEN_MAX, versatz_x=0.0, versatz_y=0.0):
    """Das Adressfeld (Absenderzeile bis letzte Anschriftzeile) in mm, von links oben: (links, oben, rechts, unten).

    Dieselben Konstanten wie `DokCanvas.fenster`; die Fensterprobe und die Tests rechnen damit."""
    links = FENSTER_X / mm + versatz_x
    oben = FENSTER_OBEN / mm + versatz_y
    letzte_grundlinie = ADRESS_ERSTE_ZEILE + (min(zeilen, ADRESS_ZEILEN_MAX) - 1) * ADRESS_ZEILENABSTAND
    unten = oben + (letzte_grundlinie + 0.22 * ADRESS_SCHRIFT) * 25.4 / 72     # Unterlänge ca. 0.22 der Schrift
    return links, oben, links + ADRESSFELD_BREITE / mm, unten


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
        self._basis_n = len(self._code)
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
        #: Versatz der Adresslage in mm (Einstellung der Verwaltung; 0 = Norm). x nach rechts, y nach unten.
        self.versatz_x = _versatz(organisation, 'adress_versatz_x_mm')
        self.versatz_y = _versatz(organisation, 'adress_versatz_y_mm')
        self._kompakt = False
        self._zeilenhoehe = 11.5
        self._rechts = self._rechte_zeilen()
        self._kopf_geometrie()
        self.Y_FOLGE = Y_FOLGE if self.hoehe > 400 else self.hoehe - 25 * mm
        self.UNTEN = UNTEN
        self.LINKS = rand
        self.RECHTS = self.rand_rechts

    def _kopf_geometrie(self):
        logo_h = self.bk.get('logo_hoehe') or 0
        hoehe_kopf = max(logo_h or 20.0, len(self._rechts) * self._zeilenhoehe)
        #: y der Linie unter dem Briefkopf (Seite 1)
        self.y_linie = self.hoehe - 15 * mm - hoehe_kopf - (6 if self._kompakt else 7)
        #: obere Kante des Inhalts auf Seite 1 (Berichte, Abrechnungen, Verträge)
        self.Y_INHALT = self.y_linie - 9 * mm

    def _kopf_fuer_brief(self):
        """Kompakter Briefkopf für Briefe mit Adressfenster.

        Unter der Linie des Briefkopfs muss über dem Adressfenster Platz für den Zustellvermerk bleiben (Abstand
        zur Linie UND zum Fenster, siehe `brief`). Mit 40-pt-Logo und vier Kontaktzeilen reichte der Kopf bis
        38 mm; jetzt reicht er höchstens bis `KOPF_MAX_BRIEF`: Logo auf `LOGO_HOEHE_BRIEF` skaliert, die Kontaktdaten
        in drei Zeilen (Name, Strasse und Ort, Telefon und E-Mail). Dokumente ohne Adressblock behalten den Kopf."""
        if self._kompakt:
            return
        self._kompakt = True
        self._zeilenhoehe = 11.0
        pfad = self.bk.get('logo_pfad')
        if pfad:
            from core.services.briefkopf import _logo_masse
            b, h = _logo_masse(pfad, hoehe=LOGO_HOEHE_BRIEF)
            if b and h:
                self.bk = dict(self.bk, logo_breite=b, logo_hoehe=h)
        self._rechts = self._rechte_zeilen()
        self._kopf_geometrie()

    # ---- Seitenverwaltung -------------------------------------------------

    def ohne_fuss(self):
        """Diese Seite trägt keine Fusszeile (Einzahlungsschein füllt den Fuss)."""
        self._flag['ohne_fuss'] = True

    def neues_dokument(self):
        """Die aktuelle Seite beginnt ein neues Dokument (Seitenzählung und Briefkopf von vorn)."""
        self._flag['neu'] = True

    def showPage(self):
        # Schrift, Farben und Linienstärke gelten auf der Folgeseite weiter: reportlab setzt sie mit jeder
        # neuen Seite auf Helvetica 12 / schwarz zurück, eine Tabelle über den Seitenumbruch bekäme sonst
        # auf Seite 2 eine andere Schrift als auf Seite 1.
        zustand = (self._fontname, self._fontsize, self._fillColorObj, self._strokeColorObj, self._lineWidth)
        self._saved.append(dict(self.__dict__))
        self.seite_nr += 1
        self._flags.append(self._flag)
        self._flag = {}
        self._startPage()
        self.setFont(zustand[0], zustand[1])
        self.setFillColor(zustand[2])
        self.setStrokeColor(zustand[3])
        self.setLineWidth(zustand[4])
        self._basis_n = len(self._code)         # was schon in der Seite steht, ist kein Inhalt

    def save(self):
        if len(self._code) > self._basis_n:
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
        if self._kompakt:
            adresse = ', '.join(t for t in (bk.get('strasse'), bk.get('plz_ort')) if t)
            kontakt = ' · '.join(t for t in (bk.get('telefon'), bk.get('email')) if t)
            return zeilen + [('n', t) for t in (adresse, kontakt) if t]
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
            y -= self._zeilenhoehe
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

    def adressfeld_oben(self):
        """Obere Kante des Adressfelds (y, reportlab-Koordinate) samt Versatz der Verwaltung."""
        return self.hoehe - FENSTER_OBEN - self.versatz_y * mm

    def adressfeld_links(self):
        return FENSTER_X + self.versatz_x * mm

    def fenster(self, zeilen, absenderzeile=None):
        """Empfängerfeld im Fenster rechts (C5/6). `absenderzeile` steht klein darüber;
        Vorgabe: Firma · Strasse · PLZ Ort des Briefkopfs.

        Alles liegt zwischen `FENSTER_X` und dem Textrand (`ADRESSFELD_BREITE`): die Linie unter der Absenderzeile
        endet am Textrand, eine zu breite Zeile wird schmaler gesetzt (nicht unter `ADRESS_SCHRIFT_MIN`), dann
        gekürzt. Höchstens `ADRESS_ZEILEN_MAX` Zeilen."""
        bk = self.bk
        if absenderzeile is None:
            absenderzeile = ' · '.join(t for t in (bk.get('firma', ''), bk.get('strasse', ''), bk.get('plz_ort', '')) if t)
        x = self.adressfeld_links()
        oben = self.adressfeld_oben()
        y = oben - ABSENDER_GRUNDLINIE
        self.setFont('Helvetica', ABSENDER_SCHRIFT)
        self.setFillColor(GRAU_HELL)
        self.drawString(x, y, _kuerzen(absenderzeile, 'Helvetica', ABSENDER_SCHRIFT, ADRESSFELD_BREITE))
        self.setStrokeColor(LINIE)
        self.setLineWidth(0.5)
        self.line(x, y - 2, x + ADRESSFELD_BREITE, y - 2)
        self.setFillColor(TEXT)
        y = oben - ADRESS_ERSTE_ZEILE
        for z in [z for z in zeilen if z][:ADRESS_ZEILEN_MAX]:
            groesse = ADRESS_SCHRIFT
            while groesse > ADRESS_SCHRIFT_MIN and stringWidth(z, 'Helvetica', groesse) > ADRESSFELD_BREITE:
                groesse -= 0.5
            self.setFont('Helvetica', groesse)
            self.drawString(x, y, _kuerzen(z, 'Helvetica', groesse, ADRESSFELD_BREITE))
            y -= ADRESS_ZEILENABSTAND
        self.setStrokeColor(TEXT)
        self.setLineWidth(1)

    def brief(self, empfaenger, ort_datum, betreff, untertitel=None, einschreiben=False):
        """Fenster, Ort/Datum und Betreff. Gibt die Höhe zurück, ab der der Brieftext beginnt.

        `einschreiben` (True oder der Text des Vermerks): Der Zustellvermerk steht in einem freien Streifen ÜBER dem
        Adressfeld (Schweizer Briefnorm), bündig mit der Anschrift, `VERMERK_GRUNDLINIE` über deren Oberkante — mit
        Abstand zur Linie des Briefkopfs (kompakter Kopf, `_kopf_fuer_brief`) und zur Absenderzeile."""
        self._kopf_fuer_brief()
        self.fenster(empfaenger)
        y = self.hoehe - 88 * mm
        if einschreiben:
            self.setFont('Helvetica-Bold', VERMERK_SCHRIFT)
            self.setFillColor(TEXT)
            self.drawString(self.adressfeld_links(), self.adressfeld_oben() + VERMERK_GRUNDLINIE,
                            einschreiben if isinstance(einschreiben, str) else 'Einschreiben')
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
