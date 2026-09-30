"""Gemeinsame Bausteine der PDF-Erzeugung: Betragsformat, Zeichensatz, Fehlerfang.

WARUM ES DAS GIBT (Prüfung vom 30.09.2026)

1. BETRÄGE. Die Vertragsvorlagen nutzten teils `|floatformat:2`. Das folgt der
   aktiven Sprache — und `@nur_deutsch` schaltet auf `de` (nicht `de-ch`):
   Dort wird daraus «1250,50». Dieselbe Seite zeigte im Kopf «CHF 1'250.50».
   Der Schweizer Standard ist EINER: `CHF 1'250.50`. Er steht jetzt hier,
   und `{% load chf %}`, `_fr()`, `_fmt()` usw. rufen ihn auf.
   Gerundet wird kaufmännisch (HALF_UP); `format(Decimal('0.125'), '.2f')`
   ergäbe 0.12.

2. ZEICHENSATZ. reportlab setzt Helvetica/Helvetica-Bold (Standardschriften,
   WinAnsi = cp1252). Deckt: ä ö ü é è à ç ì ò ù ñ ß Ø œ € ’ – • usw. — also
   alles Deutsche, Französische, Italienische. Nicht gedeckt: Ł ż Ş ő č ☃,
   Emoji, Kyrillisch. Die Standardschrift macht daraus STILL Buchstabensalat
   («Łukasz» → «nukasz») — auf einem Rechtsdokument, ohne Fehlermeldung.
   `pdf_sicher()` ersetzt solche Zeichen vorab durch das nächste lateinische
   Zeichen (Ł→L, Ş→S, ő→o) und sonst durch «?», damit sichtbar bleibt, dass
   etwas fehlt. Eine eingebettete Unicode-Schrift wäre die vollständige
   Lösung; sie verlangt eine mitgelieferte Schriftdatei und ist deshalb
   freigabepflichtig (siehe PR).

3. FEHLER. `PdfFehler` ist der EINE Ausnahmetyp der Erzeugung; die Aufrufer
   fangen ihn und zeigen eine saubere Meldung statt eines 500ers.
"""
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

LEERER_BETRAG = '–'


class PdfFehler(Exception):
    """Die PDF-Erzeugung ist gescheitert (Vorlage, Daten oder Renderer)."""


def format_chf(wert, dezimalstellen=2, *, leer=''):
    """Schweizer Betrag ohne Währung: 1250.5 → «1'250.50», -3 → «-3.00».

    `None`/leer/nicht numerisch → `leer` (Standard: leere Zeichenkette), nie
    «None» und nie ein Abbruch: ein fehlender Betrag darf ein Dokument nicht
    verhindern, und `0` ist ein Wert (gemessen), `None` eine Lücke (nicht erfasst).
    """
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        return leer
    try:
        zahl = Decimal(str(wert).strip().replace("'", '').replace('’', ''))
    except (InvalidOperation, ValueError):
        return leer
    if not zahl.is_finite():
        return leer
    stellen = int(dezimalstellen)
    zahl = zahl.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP)
    if zahl == 0:          # «-0.00» vermeiden
        zahl = abs(zahl)
    return f"{zahl:,.{stellen}f}".replace(',', "'")


# Zeichen, die NFKD nicht auf ASCII zerlegt, aber eine klare lateinische Entsprechung haben.
_ERSATZ = {
    'Ł': 'L', 'ł': 'l', 'Đ': 'D', 'đ': 'd', 'Ħ': 'H', 'ħ': 'h', 'ı': 'i',
    'Ŋ': 'N', 'ŋ': 'n', 'Ð': 'D', 'ð': 'd', 'Þ': 'Th', 'þ': 'th',
    ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', '​': '',
    '‑': '-', '−': '-', '﻿': '', '‍': '', '️': '',
}


def _cp1252_ok(zeichen):
    try:
        zeichen.encode('cp1252')
        return True
    except UnicodeEncodeError:
        return False


def pdf_sicher(text):
    """Text für die Standardschriften: nur cp1252-Zeichen, sonst Ersatz."""
    if not isinstance(text, str) or text.isascii():
        return text
    aus = []
    for z in text:
        if z in '\n\r\t' or _cp1252_ok(z):
            aus.append(z)
            continue
        if z in _ERSATZ:
            aus.append(_ERSATZ[z])
            continue
        zerlegt = unicodedata.normalize('NFKD', z)
        basis = ''.join(c for c in zerlegt if not unicodedata.combining(c))
        if basis and all(_cp1252_ok(c) for c in basis):
            aus.append(basis)
        elif unicodedata.category(z) in ('Mn', 'Me', 'Cf', 'Cc'):
            continue                      # unsichtbar: weglassen
        else:
            aus.append('?')
    return ''.join(aus)


_installiert = False


def installiere_reportlab_schutz():
    """Filtert ALLEN Text der Standardschriften einmalig zentral (idempotent).

    Alle ~35 reportlab-Generatoren laufen über `PDFTextObject._formatText`;
    eine Stelle statt 35 Aufrufstellen. TrueType-Schriften bleiben unberührt.
    """
    global _installiert
    if _installiert:
        return
    from reportlab.pdfbase.pdfmetrics import getFont
    from reportlab.pdfgen import textobject

    original = textobject.PDFTextObject._formatText

    def _formatText(self, text):
        try:
            schrift = getFont(self._fontname)
        except Exception:
            schrift = None
        if schrift is not None and not schrift._dynamicFont and not schrift._multiByte:
            text = pdf_sicher(text)
        return original(self, text)

    textobject.PDFTextObject._formatText = _formatText
    _installiert = True


def html_zu_pdf(html, *, link_callback=None, quelle='Dokument'):
    """HTML → PDF-Bytes (xhtml2pdf). Wirft ausschliesslich `PdfFehler`.

    Sanitiert den Zeichensatz vorab und prüft das Ergebnis: xhtml2pdf meldet
    Fehler teils nur über `status.err`, teils gar nicht und liefert dann eine
    leere Datei.
    """
    import io

    from xhtml2pdf import pisa

    puffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(pdf_sicher(html), dest=puffer,
                                link_callback=link_callback, encoding='utf-8')
    except Exception as exc:
        raise PdfFehler(f"{quelle}: Renderer abgestürzt ({exc})") from exc
    if status.err:
        raise PdfFehler(f"{quelle}: {status.err} Fehler beim Rendern")
    pdf = puffer.getvalue()
    if not pdf.startswith(b'%PDF'):
        raise PdfFehler(f"{quelle}: Renderer lieferte kein PDF")
    return pdf
