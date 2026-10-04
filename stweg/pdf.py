"""PDF der Einladung und des Protokolls.

Rechtstext-nahe Dokumente: fest deutsch, bis ihr Wortlaut juristisch geprüft
übersetzt ist (Entscheid D11, `core/services/dokumentsprache.py`).
"""
import io

from core.services.dokumentsprache import nur_deutsch


def _umbruch(text, breite=95):
    zeilen = []
    for absatz in (text or '').split('\n'):
        akt = ''
        for wort in absatz.split(' '):
            if len(akt) + len(wort) + 1 > breite:
                zeilen.append(akt)
                akt = wort
            else:
                akt = (akt + ' ' + wort).strip()
        zeilen.append(akt)
    return zeilen


class _Seite:
    """Schreibt Zeilen und blättert selbst um."""

    def __init__(self, titel):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        self.mm = mm
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle(titel)
        self.w, self.h = A4
        self.y = self.h - 25 * mm

    def zeile(self, text, *, fett=False, gr=10, abstand=5):
        if self.y < 25 * self.mm:
            self.c.showPage()
            self.y = self.h - 25 * self.mm
        self.c.setFont('Helvetica-Bold' if fett else 'Helvetica', gr)
        self.c.drawString(20 * self.mm, self.y, text)
        self.y -= abstand * self.mm

    def absatz(self, text, **kw):
        for z in _umbruch(text):
            self.zeile(z, **kw)

    def luecke(self, mm=3):
        self.y -= mm * self.mm

    def bytes(self):
        self.c.save()
        return self.buf.getvalue()


def _kopf(s, v):
    org = v.liegenschaft.organisation
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)


@nur_deutsch
def einladung_pdf(versammlung, eigentuemer=None):
    v = versammlung
    s = _Seite(f"Einladung {v.titel}")
    _kopf(s, v)
    if eigentuemer is not None:
        s.zeile(eigentuemer.firma_oder_name)
        if eigentuemer.strasse:
            s.zeile(eigentuemer.strasse)
        s.zeile(f"{eigentuemer.plz} {eigentuemer.ort}".strip())
        s.luecke(6)
    s.zeile(f"Einladung zur {v.get_art_display()}", fett=True, gr=14, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {v.liegenschaft}", gr=11)
    s.luecke(4)
    s.zeile(f"Datum: {v.datum:%d.%m.%Y}, {v.datum:%H:%M} Uhr")
    if v.ort:
        s.zeile(f"Ort: {v.ort}")
    s.luecke(5)
    s.zeile("Traktanden", fett=True, gr=12, abstand=6)
    for t in v.traktanden.all():
        s.zeile(f"{t.nr}. {t.titel}", fett=True)
        if t.beschreibung:
            s.absatz(t.beschreibung, gr=9, abstand=4)
        if t.antrag:
            s.absatz(f"Antrag: {t.antrag}", gr=9, abstand=4)
        s.luecke(2)
    s.luecke(4)
    s.absatz("Wer nicht teilnehmen kann, lässt sich vertreten; eine schriftliche Vollmacht "
             "ist vor Beginn der Versammlung abzugeben.", gr=9, abstand=4)
    s.luecke(4)
    s.zeile("Freundliche Grüsse")
    s.zeile(v.liegenschaft.organisation.firma or '')
    return s.bytes()


@nur_deutsch
def protokoll_pdf(versammlung):
    from stweg.beschluss import praesenz
    v = versammlung
    s = _Seite(f"Protokoll {v.titel}")
    _kopf(s, v)
    s.zeile(f"Protokoll der {v.get_art_display()}", fett=True, gr=14, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {v.liegenschaft}", gr=11)
    s.zeile(f"{v.datum:%d.%m.%Y}, {v.datum:%H:%M} Uhr" + (f" · {v.ort}" if v.ort else ''))
    if v.leitung:
        s.zeile(f"Leitung: {v.leitung}")
    if v.protokollfuehrung:
        s.zeile(f"Protokoll: {v.protokollfuehrung}")
    p = praesenz(v)
    s.luecke(3)
    s.zeile(f"Vertreten: {p['koepfe']} von {p['koepfe_total']} Eigentümern, "
            f"Wertquoten {p['quoten']:g} von {p['quoten_total']:g}")
    s.luecke(5)
    for t in v.traktanden.all():
        s.zeile(f"{t.nr}. {t.titel}", fett=True, gr=11)
        if t.mehrheitsart != 'kenntnisnahme':
            s.zeile(f"Ja {t.ja_koepfe} / Nein {t.nein_koepfe} / Enthaltung {t.enthaltung_koepfe} "
                    f"(Köpfe) · Ja {t.ja_quoten:g} / Nein {t.nein_quoten:g} / "
                    f"Enthaltung {t.enthaltung_quoten:g} (Wertquoten)", gr=9, abstand=4)
        s.zeile(f"Ergebnis: {t.get_ergebnis_display()}", gr=10)
        if t.beschlusstext:
            s.absatz(t.beschlusstext, gr=9, abstand=4)
        s.luecke(3)
    if v.protokoll_text:
        s.luecke(2)
        s.zeile("Weitere Bemerkungen", fett=True)
        s.absatz(v.protokoll_text, gr=9, abstand=4)
    return s.bytes()
