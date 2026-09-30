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
   Lösung (freigegeben 30.09.2026): DejaVu Sans liegt unter
   `static/fonts/pdf/` (Lizenz daneben). Sie wird NUR für Zeichen verwendet,
   die Helvetica nicht kann — reportlab: als Ersatzschrift von Helvetica /
   Helvetica-Bold je Zeichen; HTML-Dokumente: das Dokument wechselt komplett
   auf DejaVu, sobald ein solches Zeichen vorkommt. Alles Übliche bleibt
   Helvetica. Was auch DejaVu nicht hat (Emoji, CJK), ersetzt `pdf_sicher()`
   durch das nächste lateinische Zeichen oder «?», damit sichtbar bleibt,
   dass etwas fehlt.

3. FEHLER. `PdfFehler` ist der EINE Ausnahmetyp der Erzeugung; die Aufrufer
   fangen ihn und zeigen eine saubere Meldung statt eines 500ers.
"""
import logging
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

logger = logging.getLogger(__name__)

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


SCHRIFT_ORDNER = Path(__file__).resolve().parents[2] / 'static' / 'fonts' / 'pdf'
_SCHRIFT_DATEIEN = {'DejaVuSans': 'DejaVuSans.ttf', 'DejaVuSans-Bold': 'DejaVuSans-Bold.ttf'}
_unicode_zeichen = None      # None = noch nicht geladen, frozenset() = Schrift fehlt


def schrift_pfad(name):
    return SCHRIFT_ORDNER / _SCHRIFT_DATEIEN[name]


def _unicode_schrift_laden():
    """Registriert DejaVu in reportlab; gibt die Zeichenmenge zurück (leer, wenn
    die Schriftdateien fehlen — dann gilt wie bisher nur cp1252)."""
    global _unicode_zeichen
    if _unicode_zeichen is not None:
        return _unicode_zeichen
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for name in _SCHRIFT_DATEIEN:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(schrift_pfad(name))))
        pdfmetrics.registerFontFamily('DejaVuSans', normal='DejaVuSans', bold='DejaVuSans-Bold',
                                      italic='DejaVuSans', boldItalic='DejaVuSans-Bold')
        normal = pdfmetrics.getFont('DejaVuSans')
        # Nur die Grundebene (BMP): xhtml2pdf und reportlab-TTF zerlegen Zeichen
        # darüber falsch (Emoji wurden zu «ὠ»).
        _unicode_zeichen = frozenset(chr(c) for c in normal.face.charToGlyph if c <= 0xFFFF)
    except Exception:
        logger.error("Unicode-Schrift für PDFs nicht ladbar — nur cp1252", exc_info=True)
        _unicode_zeichen = frozenset()
    return _unicode_zeichen


def _darstellbar(zeichen):
    return _cp1252_ok(zeichen) or zeichen in _unicode_schrift_laden()


def pdf_sicher(text):
    """Text für die Standardschriften: nur cp1252-Zeichen, sonst Ersatz."""
    if not isinstance(text, str) or text.isascii():
        return text
    aus = []
    for z in text:
        if z in '\n\r\t' or _darstellbar(z):
            aus.append(z)
            continue
        if z in _ERSATZ:
            aus.append(_ERSATZ[z])
            continue
        zerlegt = unicodedata.normalize('NFKD', z)
        basis = ''.join(c for c in zerlegt if not unicodedata.combining(c))
        if basis and all(_darstellbar(c) for c in basis):
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
    _unicode_schrift_laden()
    from reportlab.lib.rl_accel import fp_str
    from reportlab.pdfbase.pdfmetrics import getFont
    from reportlab.pdfgen import textobject

    original = textobject.PDFTextObject._formatText

    def _formatText(self, text):
        try:
            schrift = getFont(self._fontname)
        except Exception:
            schrift = None
        if schrift is None or schrift._dynamicFont or schrift._multiByte:
            return original(self, text)
        text = pdf_sicher(text)
        if isinstance(text, str) and not text.isascii() and any(not _cp1252_ok(z) for z in text):
            # Enthält Zeichen, die Helvetica nicht kann: dieses Textstück in
            # DejaVu setzen, danach zurück auf die Ausgangsschrift. reportlab
            # erlaubt TrueType nicht als Ersatzschrift je Zeichen.
            ausgang = self._fontname
            self._fontname = 'DejaVuSans-Bold' if 'Bold' in ausgang else 'DejaVuSans'
            try:
                code = original(self, text)
            finally:
                self._fontname = ausgang
            zurueck = '%s %s Tf %s TL' % (self._canvas._doc.getInternalFontName(ausgang),
                                          fp_str(self._fontsize), fp_str(self._leading))
            self._curSubset = -1          # der nächste TrueType-Text muss seine Schrift neu setzen
            return code + ' ' + zurueck
        return original(self, text)

    textobject.PDFTextObject._formatText = _formatText
    _installiert = True


def _mit_unicode_schrift(html):
    """Das Dokument wechselt auf DejaVu Sans, weil es ein Zeichen enthält, das
    Helvetica nicht kann. xhtml2pdf kennt keinen Ersatz je Zeichen."""
    css = (
        "<style>"
        "@font-face { font-family: DejaVuSans; src: url('%s'); }"
        "@font-face { font-family: DejaVuSans; font-weight: bold; src: url('%s'); }"
        "body, p, div, span, td, th, li, b, strong, h1, h2, h3, h4 { font-family: DejaVuSans; }"
        "</style>" % (schrift_pfad('DejaVuSans').as_posix(), schrift_pfad('DejaVuSans-Bold').as_posix()))
    if '</head>' in html:
        return html.replace('</head>', css + '</head>', 1)
    return css + html


def pdf_aus_html(html, *, link_callback=None, quelle='Dokument'):
    """HTML → PDF-Bytes (xhtml2pdf). Wirft ausschliesslich `PdfFehler`.

    Sanitiert den Zeichensatz vorab und prüft das Ergebnis: xhtml2pdf meldet
    Fehler teils nur über `status.err`, teils gar nicht und liefert dann eine
    leere Datei.
    """
    import io

    from xhtml2pdf import pisa

    html = pdf_sicher(html)
    if any(not _cp1252_ok(z) for z in html) and _unicode_schrift_laden():
        html = _mit_unicode_schrift(html)

    puffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(html, dest=puffer,
                                link_callback=link_callback, encoding='utf-8')
    except Exception as exc:
        raise PdfFehler(f"{quelle}: Renderer abgestürzt ({exc})") from exc
    if status.err:
        raise PdfFehler(f"{quelle}: {status.err} Fehler beim Rendern")
    pdf = puffer.getvalue()
    if not pdf.startswith(b'%PDF'):
        raise PdfFehler(f"{quelle}: Renderer lieferte kein PDF")
    return pdf
