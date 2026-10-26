"""PDF des Wohnungsabnahme-Protokolls (Einzug/Auszug).

Seit 10/2026 (Produktionsreife der Abnahme):
- Der Mängeltext steht vollständig da und bricht um — vorher nach 44 Zeichen
  abgeschnitten, ausgerechnet dort, wo die Beschreibung Beweis ist.
- Fotos aus dem klassischen Formular erscheinen im Bildteil (vorher nur die
  der Abnahme vor Ort).
- Jede Seite trägt «Seite x von y»: Ein mehrseitiges Protokoll ohne Zählung
  lässt nicht erkennen, ob eine Seite fehlt.
- Wo keine Unterschrift vorliegt, steht «nicht unterzeichnet» — ein Name auf
  der Linie sah sonst aus wie eine Unterschrift.
- Nach der Abnahme entdeckte Mängel (Art. 267a Abs. 3 OR) stehen getrennt
  HINTER den Unterschriften: Sie waren nicht Teil dessen, was unterschrieben
  wurde.
"""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from core.services.abnahme_texte import schlussbestimmungen
from core.services.dokumentsprache import nur_deutsch


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


ZUSTAND_LABEL = {'': 'offen', 'io': 'Neu i.O.', 'normal': 'Normal', 'uebermaessig': 'Übermässig'}


def _kuerzen(text, groesse, breite):
    """Kürzt einen Text auf die Spaltenbreite (Helvetica), mit «…»."""
    text = str(text or '')
    if stringWidth(text, 'Helvetica', groesse) <= breite:
        return text
    while text and stringWidth(text + '…', 'Helvetica', groesse) > breite:
        text = text[:-1]
    return text.rstrip() + '…'


def _bildleser(feld):
    """Ein hochgeladenes Bild für reportlab; None, wenn keines da oder nicht lesbar
    (eine fehlende Datei darf das PDF nicht verhindern)."""
    if not feld:
        return None
    try:
        with feld.open('rb') as f:
            return ImageReader(io.BytesIO(f.read()))
    except Exception:
        return None


VERURS_LABEL = {'abnutzung': 'normale Abnutzung', 'mieter': 'Mieter (Schaden)', 'vermieter': 'Vermieter'}
NICHT_UNTERZEICHNET = 'nicht unterzeichnet'


class _GezaehlteSeiten(canvas.Canvas):
    """Canvas, der am Ende «Seite x von y» auf jede Seite schreibt.

    Die Gesamtzahl steht erst fest, wenn alles gezeichnet ist: Die Seiten
    werden deshalb zurückgehalten und beim Speichern nummeriert (das übliche
    Vorgehen mit reportlab)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seiten = []

    def showPage(self):
        self._seiten.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        gesamt = len(self._seiten)
        for zustand in self._seiten:
            self.__dict__.update(zustand)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.grey)
            self.drawRightString(190 * mm, 10 * mm, f"Seite {self._pageNumber} von {gesamt}")
            self.setFillColor(colors.black)
            super().showPage()
        super().save()


@nur_deutsch
def generate_abnahme_pdf(prot, verwaltung=None):
    from core.services.zeitwert import OHNE_LEBENSDAUER
    buf = io.BytesIO()
    c = _GezaehlteSeiten(buf, pagesize=A4)
    v = prot.vertrag
    e = v.einheit
    lg = e.liegenschaft
    c.setTitle(f"Abnahmeprotokoll {v.mieter.nachname}")
    UNTEN = 22 * mm                    # Platz für die Seitenzahl

    y = 280 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, y, f"Wohnungsabnahme — {prot.get_typ_display()}")
    y -= 7 * mm
    c.setFont("Helvetica", 10); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, f"{e.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Mieter: {v.mieter.vorname} {v.mieter.nachname} · Datum: {prot.datum.strftime('%d.%m.%Y')}")
    if not prot.abgeschlossen:
        y -= 5 * mm
        c.drawString(20 * mm, y, "Entwurf — noch nicht abgeschlossen")
    c.setFillColor(colors.black)
    y -= 10 * mm

    def zeile(label, wert):
        nonlocal y
        if not wert:
            return
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Helvetica", 9)
        teile = simpleSplit(str(wert), "Helvetica", 9, 128 * mm) or ['']
        for i, teil in enumerate(teile):
            c.drawString(62 * mm, y - i * 4.4 * mm, teil)
        y -= 5.5 * mm + 4.4 * mm * (len(teile) - 1)

    eig = getattr(lg, 'eigentuemer', None)
    zeile("Eigentümer", eig.firma_oder_name if eig else '')
    zeile("Mietverhältnis", f"ab {v.beginn:%d.%m.%Y}" + (f" bis {v.ende:%d.%m.%Y}" if v.ende else ''))
    zeile("Weitere Mieter", ', '.join(m.display_name for m in v.mitmieter_alle))
    zeile("Abnahme durch", prot.verwalter_name)
    zeile("Mieter anwesend", "Ja" if prot.mieter_anwesend else (
        "Nein" + (f" — {prot.mieter_abwesend_grund}" if prot.mieter_abwesend_grund else '')))
    zeile("Allgemeinzustand", prot.get_allgemein_zustand_display())
    zeile("Schlüssel zurück", prot.schluessel_anzahl)
    zeile("Zähler Strom", prot.zaehler_strom)
    zeile("Zähler Wasser", prot.zaehler_wasser)
    zeile("Zähler Gas/Wärme", prot.zaehler_gas)
    zeile("Neue Adresse", prot.neue_adresse)

    alle_maengel = list(prot.maengel.select_related('ausstattung'))
    maengel = [m for m in alle_maengel if m.entdeckt_am is None]
    nachmaengel = [m for m in alle_maengel if m.entdeckt_am is not None]
    mangel_nr = {m.id: f"M{i}" for i, m in enumerate(maengel, start=1)}
    mangel_nr.update({m.id: f"N{i}" for i, m in enumerate(nachmaengel, start=1)})

    # Spalten (mm): Nr 20, Raum 27–48, Mangel 50–116, Verursacher 118, Kosten …168, Anteil …190
    def maengel_kopf():
        nonlocal y
        c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
        c.drawString(20 * mm, y, "Nr"); c.drawString(27 * mm, y, "Raum"); c.drawString(50 * mm, y, "Mangel")
        c.drawString(118 * mm, y, "Verursacher")
        c.drawRightString(168 * mm, y, "Kosten"); c.drawRightString(190 * mm, y, "Anteil")
        c.setFillColor(colors.black)
        y -= 5 * mm

    def maengel_zeilen(liste, mit_entdeckt=False):
        nonlocal y
        for m in liste:
            text = m.beschreibung or ''
            if mit_entdeckt:
                text = f"[entdeckt {m.entdeckt_am:%d.%m.%Y}] " + text
            mangel_zeilen = simpleSplit(text, "Helvetica", 9, 66 * mm) or ['']
            raum_zeilen = simpleSplit(m.raum or '—', "Helvetica", 9, 21 * mm) or ['—']
            hinweis = (m.verursacher == 'mieter' and not m.vorsaetzlich
                       and m.zeitwert_grundlage == OHNE_LEBENSDAUER)
            n = max(len(mangel_zeilen) + (1 if hinweis else 0), len(raum_zeilen))
            hoehe = 4.4 * mm * n + 1.4 * mm
            if y - hoehe < UNTEN:
                c.showPage(); y = 280 * mm; maengel_kopf()
            c.setFont("Helvetica", 9)
            c.drawString(20 * mm, y, mangel_nr[m.id])
            for i, t in enumerate(raum_zeilen):
                c.drawString(27 * mm, y - i * 4.4 * mm, t)
            for i, t in enumerate(mangel_zeilen):
                c.drawString(50 * mm, y - i * 4.4 * mm, t)
            if hinweis:
                c.setFont("Helvetica", 7.5); c.setFillColor(colors.grey)
                c.drawString(50 * mm, y - len(mangel_zeilen) * 4.4 * mm,
                             "Voller Betrag: Alter/Lebensdauer des Bauteils nicht erfasst")
                c.setFillColor(colors.black); c.setFont("Helvetica", 9)
            c.drawString(118 * mm, y, VERURS_LABEL.get(m.verursacher, m.verursacher))
            basis = m.kostenschaetzung if m.kostenschaetzung is not None else m.neuwert
            if basis is not None:
                c.drawRightString(168 * mm, y, _fmt(basis))
            if m.verursacher == 'mieter':
                anteil = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
                if anteil is not None:
                    c.drawRightString(190 * mm, y, _fmt(anteil))
            y -= hoehe

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Festgestellte Mängel")
    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    maengel_kopf()
    if not maengel:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.grey); c.drawString(20 * mm, y, "Keine Mängel festgestellt."); c.setFillColor(colors.black); y -= 6 * mm
    maengel_zeilen(maengel)

    schluessel = list(prot.schluessel.all())
    schluessel_kosten = sum((z.kosten_mieter for z in schluessel), Decimal('0.00'))
    if y < 40 * mm:
        c.showPage(); y = 280 * mm
    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y); y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Kosten zulasten Mieter (Zeitwert)")
    # Ohne die später entdeckten Mängel: Diese Summe gehört zum unterzeichneten Teil.
    bei_abnahme = sum(((m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung) or Decimal('0.00')
                       for m in maengel if m.verursacher == 'mieter'), Decimal('0.00')) + schluessel_kosten
    c.drawRightString(190 * mm, y, f"CHF {_fmt(bei_abnahme)}")
    y -= 5 * mm
    if schluessel_kosten:
        c.setFont("Helvetica", 8.5)
        c.drawString(20 * mm, y, "davon Ersatz fehlender Schlüssel")
        c.drawRightString(190 * mm, y, f"CHF {_fmt(schluessel_kosten)}")
        y -= 5 * mm
    c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, "Anteil = Zeitwert nach paritätischer Lebensdauertabelle (Abzug 'neu für alt') bei verknüpftem Raumbuch-Element.")
    c.setFillColor(colors.black)
    y -= 8 * mm

    # Bewertete Bauteile (Abnahme vor Ort): alle Bauteile mit Zustand, bei
    # aufbauenden Protokollen zusätzlich der Vorzustand aus dem Vorgänger.
    # Die Nummer läuft durch Bauteile und Schlüssel (wie im Praxisprotokoll)
    # und verbindet die Tabelle mit den Bildern am Ende.
    positionen = list(prot.positionen.select_related('vorgaenger_position__protokoll'))
    nummern = {pos.id: i for i, pos in enumerate(positionen, start=1)}
    if positionen:
        vorg = prot.vorgaenger
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Bewertete Bauteile")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 5 * mm
        if vorg is not None:
            c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
            c.drawString(20 * mm, y, f"Baut auf: {vorg.get_typ_display()} vom {vorg.datum.strftime('%d.%m.%Y')} "
                                     f"({vorg.vertrag.mieter.nachname})")
            c.setFillColor(colors.black)
            y -= 6 * mm

        # Spalten (mm): Nr 20, Raum 28, Bauteil 45, Vorzustand 87, Zustand 110, Kommentar 134–190
        bauteil_breite = (40 if vorg is not None else 62) * mm

        def kopfzeile():
            nonlocal y
            c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
            c.drawString(20 * mm, y, "Nr"); c.drawString(28 * mm, y, "Raum"); c.drawString(45 * mm, y, "Bauteil")
            if vorg is not None:
                c.drawString(87 * mm, y, "Vorzustand")
            c.drawString(110 * mm, y, "Zustand"); c.drawString(134 * mm, y, "Kommentar")
            c.setFillColor(colors.black)
            y -= 5 * mm
        kopfzeile()
        for pos in positionen:
            bemerkung = pos.kommentar or ''
            if pos.vorbestand_entscheid == 'vorbestehend':
                bemerkung = ('[vorbestehend] ' + bemerkung).strip()
            elif pos.vorbestand_entscheid == 'mieter':
                bemerkung = ('[dem Mieter belastet] ' + bemerkung).strip()
            # Langer Kommentar: bis zu drei Zeilen, der Rest wird abgeschnitten.
            zeilen = (simpleSplit(bemerkung, "Helvetica", 8, 56 * mm)[:3]) or ['']
            hoehe = 4.2 * mm * len(zeilen) + 0.8 * mm
            if y - hoehe < UNTEN + 15 * mm:
                c.showPage(); y = 280 * mm; kopfzeile()
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, str(nummern[pos.id]))
            c.drawString(28 * mm, y, _kuerzen(pos.raum or '—', 8, 16 * mm))
            c.drawString(45 * mm, y, _kuerzen(pos.bezeichnung or '', 8, bauteil_breite))
            if vorg is not None:
                vp = pos.vorgaenger_position
                c.drawString(87 * mm, y, ZUSTAND_LABEL.get(vp.zustand, '—') if vp else '—')
            c.drawString(110 * mm, y, ZUSTAND_LABEL.get(pos.zustand, 'offen'))
            for i, zeile_text in enumerate(zeilen):
                c.drawString(134 * mm, y - i * 4.2 * mm, zeile_text)
            y -= hoehe
        y -= 4 * mm

    # Schlüsselverzeichnis: Soll gegen Ist, Nummern setzen die der Bauteile fort.
    if schluessel:
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Schlüsselverzeichnis")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 5 * mm
        c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
        c.drawString(20 * mm, y, "Nr"); c.drawString(28 * mm, y, "Schlüssel"); c.drawString(75 * mm, y, "Schliessanlage / Schlüsselnummer")
        c.drawRightString(138 * mm, y, "Soll"); c.drawRightString(150 * mm, y, "Ist"); c.drawRightString(166 * mm, y, "Fehlend")
        c.drawRightString(190 * mm, y, "Ersatz CHF")
        c.setFillColor(colors.black)
        y -= 5 * mm
        c.setFont("Helvetica", 8)
        for i, z in enumerate(schluessel, start=len(positionen) + 1):
            if y < UNTEN + 10 * mm:
                c.showPage(); y = 280 * mm; c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, str(i))
            c.drawString(28 * mm, y, _kuerzen(z.bezeichnung, 8, 44 * mm))
            c.drawString(75 * mm, y, _kuerzen(z.anlage or '—', 8, 50 * mm))
            c.drawRightString(138 * mm, y, str(z.soll))
            c.drawRightString(150 * mm, y, '—' if z.ist is None else str(z.ist))
            c.drawRightString(166 * mm, y, '—' if z.fehlend is None else str(z.fehlend))
            c.drawRightString(190 * mm, y, _fmt(z.kosten_mieter) if z.kosten_mieter else '—')
            y -= 5 * mm
        y -= 4 * mm

    if prot.bemerkungen:
        # Reicht der Platz nicht, geht es auf einer neuen Seite weiter.
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, "Bemerkungen:"); y -= 5 * mm
        c.setFont("Helvetica", 9)
        for line in prot.bemerkungen.split('\n'):
            for chunk in (simpleSplit(line, "Helvetica", 9, 170 * mm) or ['']):
                if y < UNTEN + 20 * mm:
                    c.showPage(); y = 280 * mm; c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, chunk); y -= 5 * mm
        y -= 3 * mm

    # Schlussbestimmungen (Standardtext der Verwaltung, siehe abnahme_texte)
    absaetze = schlussbestimmungen(prot)
    if absaetze:
        if y < 70 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Schlussbestimmungen")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 6 * mm
        for titel, text in absaetze:
            zeilen = simpleSplit(text, "Helvetica", 8.5, 170 * mm)
            if y - (len(zeilen) + 1) * 4.2 * mm < UNTEN + 5 * mm:
                c.showPage(); y = 280 * mm
            c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, titel); y -= 5 * mm
            c.setFont("Helvetica", 8.5)
            for zeile_text in zeilen:
                c.drawString(20 * mm, y, zeile_text); y -= 4.2 * mm
            y -= 3 * mm

    # Unterschriften: im Fluss hinter dem Inhalt, mit der gezeichneten Unterschrift über der Linie.
    # Ohne Bild steht «nicht unterzeichnet» unter der Linie — ein getippter oder
    # vorbelegter Name allein ist keine Unterschrift.
    if y < 75 * mm:
        c.showPage(); y = 280 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Unterschriften")
    y -= 3 * mm
    abwesend = ''
    if not prot.mieter_anwesend:
        abwesend = 'Mieter abwesend' + (f": {prot.mieter_abwesend_grund}" if prot.mieter_abwesend_grund else '')
    for x, bild, name, rolle, zusatz in (
            (20 * mm, prot.unterschrift_mieter_bild, prot.unterschrift_mieter, 'Mieter', abwesend),
            (115 * mm, prot.unterschrift_verwalter_bild, prot.unterschrift_verwalter, 'Verwaltung', '')):
        leser = _bildleser(bild)
        if leser is not None:
            c.drawImage(leser, x, y - 26 * mm, width=70 * mm, height=25 * mm, preserveAspectRatio=True, anchor='sw')
        c.setStrokeColor(colors.HexColor("#94a3b8"))
        c.line(x, y - 28 * mm, x + 70 * mm, y - 28 * mm)
        c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
        if leser is not None:
            c.drawString(x, y - 32 * mm, f"{rolle}{'  ' + name if name else ''}")
        else:
            c.drawString(x, y - 32 * mm, f"{rolle}: {NICHT_UNTERZEICHNET}")
            if zusatz:
                for i, t in enumerate(simpleSplit(zusatz, "Helvetica", 8, 70 * mm)[:3]):
                    c.drawString(x, y - 36 * mm - i * 4 * mm, t)
        c.setFillColor(colors.black)
    y -= 48 * mm

    # Nach der Abnahme entdeckte Mängel: getrennt und ausdrücklich nicht unterzeichnet.
    if nachmaengel:
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Nach der Abnahme entdeckte Mängel (Art. 267a Abs. 3 OR)")
        y -= 5 * mm
        c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
        c.drawString(20 * mm, y, "Nachträglich erfasst, nicht Teil der oben unterzeichneten Abnahme; separat gerügt.")
        c.setFillColor(colors.black)
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 6 * mm
        maengel_kopf()
        maengel_zeilen(nachmaengel, mit_entdeckt=True)
        y -= 4 * mm

    # Bilder: Fotos der Bauteile (Abnahme vor Ort), dann die der Mängel aus dem
    # klassischen Formular — nach Raum gruppiert, mit der Nummer der Tabelle.
    # Ein Mangel aus einem Bauteil teilt dessen Datei: Er erscheint nicht doppelt.
    aus_positionen = {pos.mangel_id for pos in positionen if pos.mangel_id}
    bilder = [(pos.raum, f"{nummern[pos.id]} {pos.bezeichnung}", pos.foto) for pos in positionen if pos.foto]
    bilder += [(m.raum, f"{mangel_nr[m.id]} {m.beschreibung}", m.foto)
               for m in maengel + nachmaengel if m.foto and m.id not in aus_positionen]
    if bilder:
        c.showPage()
        y = 280 * mm
        c.setFont("Helvetica-Bold", 13); c.drawString(20 * mm, y, "Bilder")
        y -= 3 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 8 * mm
        raum, spalte = None, 0
        zellen_hoehe, zellen_breite = 68 * mm, 82 * mm
        for bild_raum, beschriftung, foto in bilder:
            leser = _bildleser(foto)
            if leser is None:
                continue
            if bild_raum != raum:
                # Neuer Raum: neue Zeile mit Raumüberschrift
                if spalte == 1:
                    y -= zellen_hoehe
                    spalte = 0
                if y - 14 * mm - zellen_hoehe < UNTEN:
                    c.showPage(); y = 280 * mm
                raum = bild_raum
                c.setFont("Helvetica-Bold", 10); c.drawString(20 * mm, y, raum or '—')
                y -= 7 * mm
            if spalte == 0 and y - zellen_hoehe < UNTEN:
                c.showPage(); y = 280 * mm
            x = 20 * mm + spalte * 88 * mm
            c.setFont("Helvetica", 8)
            c.drawString(x, y, _kuerzen(beschriftung, 8, zellen_breite))
            c.drawImage(leser, x, y - 4 * mm - 56 * mm, width=zellen_breite, height=56 * mm,
                        preserveAspectRatio=True, anchor='nw')
            if spalte == 1:
                y -= zellen_hoehe
            spalte = 1 - spalte

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
