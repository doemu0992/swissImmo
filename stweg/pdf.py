"""PDF der Einladung und des Protokolls.

Rechtstext-nahe Dokumente: fest deutsch, bis ihr Wortlaut juristisch geprüft
übersetzt ist (Entscheid D11, `core/services/dokumentsprache.py`).
"""
import io
from decimal import Decimal

from core.services.dokumentsprache import nur_deutsch
from stweg.validierung import zahl


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
            f"Wertquoten {zahl(p['quoten'])} von {zahl(p['quoten_total'])}")
    from stweg import vorgaben
    bf = vorgaben.beschlussfaehigkeit(v)
    if bf is not None:
        s.zeile("Beschlussfähigkeit nach den Vorgaben der Gemeinschaft: "
                + ("erfüllt" if bf['beschlussfaehig'] else "NICHT erfüllt — " + ' '.join(bf['gruende'])),
                gr=9, abstand=4)
    s.luecke(5)
    for t in v.traktanden.all():
        s.zeile(f"{t.nr}. {t.titel}", fett=True, gr=11)
        if t.ohne_beschlussfaehigkeit:
            s.zeile("Festgestellt trotz fehlender Beschlussfähigkeit (ausdrückliche Bestätigung der Verwaltung).",
                    fett=True, gr=9, abstand=4)
        if t.mehrheitsart != 'kenntnisnahme':
            s.zeile(f"Ja {t.ja_koepfe} / Nein {t.nein_koepfe} / Enthaltung {t.enthaltung_koepfe} "
                    f"(Köpfe) · Ja {zahl(t.ja_quoten)} / Nein {zahl(t.nein_quoten)} / "
                    f"Enthaltung {zahl(t.enthaltung_quoten)} (Wertquoten)", gr=9, abstand=4)
        s.zeile(f"Ergebnis: {t.get_ergebnis_display()}", gr=10)
        if t.beschlusstext:
            s.absatz(t.beschlusstext, gr=9, abstand=4)
        s.luecke(3)
    if v.protokoll_text:
        s.luecke(2)
        s.zeile("Weitere Bemerkungen", fett=True)
        s.absatz(v.protokoll_text, gr=9, abstand=4)
    return s.bytes()


def _chf(betrag):
    return f"{betrag:,.2f}".replace(',', "'")


def _qr_basis(lg, eigentuemer, betrag, ref_a, ref_b, grund):
    from core.services.iban import ist_gueltige_iban, normalisiere_iban
    from core.utils.qr_code import qrr_referenz
    iban = normalisiere_iban(lg.iban)
    if not iban or not ist_gueltige_iban(iban) or betrag <= 0:
        return None
    creditor = {'name': f'Stockwerkeigentümergemeinschaft {lg.strasse}'[:70], 'line1': lg.strasse or '',
                'line2': f"{lg.plz or ''} {lg.ort or ''}".strip(), 'plz': lg.plz or '', 'ort': lg.ort or ''}
    debtor = {'name': eigentuemer.firma_oder_name, 'line1': eigentuemer.strasse or '',
              'line2': f"{eigentuemer.plz or ''} {eigentuemer.ort or ''}".strip(),
              'plz': eigentuemer.plz or '', 'ort': eigentuemer.ort or ''}
    # `qrr_referenz` nennt ihre Parameter noch nach dem Mietmodell (vertrag_id, rechnung_id),
    # rechnet aber nur mit den Zahlen.
    referenz, _ = qrr_referenz(ref_a, ref_b)
    return {'iban': iban, 'creditor': creditor, 'debtor': debtor, 'referenz': referenz, 'grund': grund[:140]}


def _qr_daten(abrechnung, eigentuemer, betrag):
    """Die Angaben für den QR-Zahlteil — oder None, wenn keiner möglich ist.

    Gezahlt wird auf das Konto der GEMEINSCHAFT (`Liegenschaft.iban`). Ohne gültige
    IBAN gibt es keinen Zahlteil; der Beleg nennt die Nachzahlung trotzdem. Eindeutig je
    Abrechnung und Eigentümer."""
    lg = abrechnung.liegenschaft
    return _qr_basis(lg, eigentuemer, betrag, abrechnung.pk, eigentuemer.pk,
                     f'Abrechnung {abrechnung.jahr} {lg.strasse}')


#: Vorschreibungs-Referenzen beginnen hinter diesem Offset, damit sie nie mit der Referenz
#: einer Abrechnung (kleine ID im selben Feld) zusammenfallen.
VORSCHREIBUNG_REFERENZ_OFFSET = 5_000_000_000


def _qr_zeichnen(seite, daten, betrag):
    from core.utils.qr_code import draw_qr_bill
    seite.c.showPage()
    draw_qr_bill(seite.c, daten['iban'], daten['creditor'], daten['debtor'], betrag,
                 daten['grund'], reference=daten['referenz'])


@nur_deutsch
def abrechnung_pdf(abrechnung, eigentuemer=None):
    """Jahresabrechnung. Ohne `eigentuemer`: die Gesamtübersicht für die Verwaltung;
    mit `eigentuemer`: nur dessen Einheiten (der Beleg für den Eigentümer)."""
    a = abrechnung
    lg = a.liegenschaft
    s = _Seite(f"Abrechnung {a.jahr} {lg}")
    org = lg.organisation
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)
    if eigentuemer is not None:
        s.zeile(eigentuemer.firma_oder_name)
        if eigentuemer.strasse:
            s.zeile(eigentuemer.strasse)
        s.zeile(f"{eigentuemer.plz} {eigentuemer.ort}".strip())
        s.luecke(6)
    s.zeile(f"Jahresabrechnung {a.jahr}", fett=True, gr=14, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {lg}", gr=11)
    if a.status != a.STATUS_ABGESCHLOSSEN:
        s.zeile("ENTWURF — noch nicht abgeschlossen", fett=True)
    s.luecke(5)
    s.zeile("Allgemeine Kosten", fett=True, gr=12, abstand=6)
    for k in a.kostenzeilen.all():
        text = ' · '.join(x for x in (k.lieferant, k.text) if x)
        datum = f"{k.datum:%d.%m.%Y}" if k.datum else '          '
        s.zeile(f"{datum}  {text[:60]:<60}  CHF {_chf(k.betrag):>12}", gr=9, abstand=4)
    s.zeile(f"Total Kosten: CHF {_chf(a.gesamtkosten)}", fett=True)
    s.luecke(5)
    s.zeile("Verteilung nach Schlüsseln", fett=True, gr=12, abstand=6)
    positionen = a.positionen.select_related('einheit', 'eigentuemer').prefetch_related('schluesselanteile')
    if eigentuemer is not None:
        positionen = positionen.filter(eigentuemer=eigentuemer)
    total_saldo = 0
    for p in positionen:
        s.zeile(f"{p.einheit.bezeichnung} · Wertquote {zahl(p.wertquote)}/{p.wertquote_total}"
                + (f" · {p.eigentuemer.firma_oder_name}" if eigentuemer is None and p.eigentuemer else ''),
                fett=True, gr=10)
        for t in p.schluesselanteile.all():
            s.zeile(f"  {t.schluessel_name}: {zahl(t.gewicht)}/{zahl(t.gewicht_total)} von CHF "
                    f"{_chf(t.kosten_total)} = CHF {_chf(t.betrag)}", gr=9, abstand=3)
        s.zeile(f"Kostenanteil CHF {_chf(p.kostenanteil)} − Akonto CHF {_chf(p.akonto)}", gr=9, abstand=4)
        s.zeile(("Nachzahlung (Zahllast)" if p.saldo > 0 else "Guthaben" if p.saldo < 0 else "Ausgeglichen")
                + f": CHF {_chf(abs(p.saldo))}", fett=True, gr=10)
        s.luecke(2)
        total_saldo += p.saldo
    if eigentuemer is not None:
        s.luecke(2)
        s.zeile(("Total Nachzahlung" if total_saldo > 0 else "Total Guthaben" if total_saldo < 0
                 else "Total ausgeglichen") + f": CHF {_chf(abs(total_saldo))}", fett=True, gr=11)
        if total_saldo > 0:
            # Der Zahlteil gehört nur an eine ABGESCHLOSSENE Abrechnung: Ein Entwurf darf
            # nicht zur Zahlung auffordern.
            qr = _qr_daten(a, eigentuemer, total_saldo) if a.status == a.STATUS_ABGESCHLOSSEN else None
            s.zeile("Zahlung mit dem QR-Zahlteil auf der folgenden Seite." if qr else
                    "Bitte überweisen Sie den Betrag auf das Konto der Gemeinschaft.", gr=9, abstand=4)
            if qr:
                _qr_zeichnen(s, qr, total_saldo)
    return s.bytes()


@nur_deutsch
def zirkular_pdf(z):
    """Antrag (laufend) bzw. Antrag mit Ergebnis (abgeschlossen)."""
    lg = z.liegenschaft
    s = _Seite(f"Zirkularbeschluss {z.titel}")
    org = lg.organisation
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)
    s.zeile("Zirkularbeschluss", fett=True, gr=14, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {lg}", gr=11)
    s.luecke(3)
    s.zeile(z.titel, fett=True, gr=12, abstand=6)
    s.zeile(f"Abstimmung bis: {z.frist_bis:%d.%m.%Y}")
    s.zeile(f"Erforderliche Mehrheit: {z.get_mehrheitsart_display()}")
    if z.rechtsgrundlage:
        s.zeile(f"Grundlage: {z.rechtsgrundlage}")
    s.luecke(4)
    s.zeile("Antrag", fett=True)
    s.absatz(z.antrag, gr=10, abstand=4)
    if z.begruendung:
        s.luecke(3)
        s.zeile("Begründung", fett=True)
        s.absatz(z.begruendung, gr=9, abstand=4)
    if z.status == z.ABGESCHLOSSEN:
        s.luecke(5)
        s.zeile(f"Ergebnis: {z.get_ergebnis_display()}", fett=True, gr=12, abstand=6)
        s.zeile(f"Köpfe: Ja {z.ja_koepfe} · Nein {z.nein_koepfe} · Enthaltung {z.enthaltung_koepfe}", gr=10)
        s.zeile(f"Wertquoten: Ja {zahl(z.ja_quoten)} · Nein {zahl(z.nein_quoten)} · Enthaltung {zahl(z.enthaltung_quoten)}", gr=10)
        if z.beschlusstext:
            s.luecke(2)
            s.absatz(z.beschlusstext, gr=10, abstand=4)
    return s.bytes()


@nur_deutsch
def vorschreibung_pdf(budget, eigentuemer):
    """Akonto-Rechnung eines Eigentümers für das genehmigte Budget: je Einheit die Aufteilung nach
    Schlüsseln und die Raten, danach ein QR-Zahlteil je Rate (ohne gültige IBAN entfällt er)."""
    from stweg.models import StwegVorschreibung
    lg = budget.liegenschaft
    s = _Seite(f"Akonto-Rechnung {budget.jahr} {lg}")
    org = lg.organisation
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)
    s.zeile(eigentuemer.firma_oder_name)
    if eigentuemer.strasse:
        s.zeile(eigentuemer.strasse)
    s.zeile(f"{eigentuemer.plz} {eigentuemer.ort}".strip())
    s.luecke(6)
    s.zeile(f"Akonto-Rechnung {budget.jahr}", fett=True, gr=14, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {lg}", gr=11)
    s.zeile("Grundlage: von der Versammlung genehmigtes Budget.", gr=9)
    s.luecke(4)
    vs = list(StwegVorschreibung.objects.filter(budget=budget, eigentuemer=eigentuemer)
              .select_related('einheit').order_by('einheit_id', 'rate_nr'))
    gesehen = []
    for v in vs:
        if v.einheit_id not in gesehen:
            gesehen.append(v.einheit_id)
            s.zeile(f"{v.einheit.bezeichnung} · Jahresbetrag CHF {_chf(v.jahresbetrag)}", fett=True, gr=10)
            for t in v.aufteilung:
                s.zeile(f"  {t['schluessel']}: CHF {_chf(Decimal(t['betrag']))}", gr=9, abstand=4)
    s.luecke(3)
    s.zeile("Raten", fett=True, gr=12, abstand=6)
    for v in vs:
        s.zeile(f"{v.einheit.bezeichnung} · Rate {v.rate_nr}/{v.rate_total} · fällig {v.faellig_am:%d.%m.%Y}"
                f" · CHF {_chf(v.betrag)}", gr=9, abstand=4)
    total = sum((v.betrag for v in vs), Decimal('0.00'))
    s.zeile(f"Total CHF {_chf(total)}", fett=True)
    for v in vs:
        qr = _qr_basis(lg, eigentuemer, v.betrag, VORSCHREIBUNG_REFERENZ_OFFSET + v.pk, eigentuemer.pk,
                       f'Akonto {budget.jahr} {v.einheit.bezeichnung} Rate {v.rate_nr}/{v.rate_total}')
        if qr:
            _qr_zeichnen(s, qr, v.betrag)
    return s.bytes()
