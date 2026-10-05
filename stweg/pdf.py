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


#: Referenzen von Mahnungen beginnen hinter diesem Offset (nie gleich einer Abrechnungs- oder Vorschreibungs-Referenz).
MAHNUNG_REFERENZ_OFFSET = 6_000_000_000


@nur_deutsch
def mahnung_pdf(mahnung):
    """Mahnung an einen Stockwerkeigentümer. KEINE Kündigungsandrohung (Art. 257d OR gilt nur für Mieter): Der Text
    läuft durch `inkasso.ohne_kuendigung`. Mit QR-Zahlteil, wenn die Gemeinschaft eine gültige IBAN hat."""
    from stweg import inkasso
    fall = mahnung.fall
    e = fall.einheit
    lg = e.liegenschaft
    eig = fall.eigentuemer or e.stockwerkeigentuemer
    s = _Seite(f"{mahnung.stufe}. Mahnung {lg}")
    org = lg.organisation
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)
    if eig is not None:
        s.zeile(eig.firma_oder_name)
        if eig.strasse:
            s.zeile(eig.strasse)
        s.zeile(f"{eig.plz} {eig.ort}".strip())
    s.luecke(6)
    zeilen = inkasso.mahntext(mahnung)
    s.zeile(zeilen[0], fett=True, gr=14, abstand=7)
    for z in zeilen[1:]:
        if z:
            s.absatz(z, gr=10, abstand=5)
        else:
            s.luecke(2)
    s.luecke(4)
    s.zeile(f"Datum: {mahnung.datum:%d.%m.%Y}")
    s.zeile("Freundliche Grüsse")
    s.zeile(org.firma or '')
    if eig is not None:
        qr = _qr_basis(lg, eig, mahnung.betrag, MAHNUNG_REFERENZ_OFFSET + mahnung.pk, eig.pk,
                       f'{mahnung.stufe}. Mahnung {e.bezeichnung} {lg.strasse}')
        if qr:
            _qr_zeichnen(s, qr, mahnung.betrag)
    return s.bytes()


@nur_deutsch
def retention_pdf(fall):
    """Mitteilung über die Ausübung des Retentionsrechts (Art. 712k ZGB) — rudimentär, zur Prüfung."""
    e = fall.einheit
    lg = e.liegenschaft
    eig = fall.eigentuemer or e.stockwerkeigentuemer
    org = lg.organisation
    s = _Seite(f"Retentionsrecht {lg}")
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(6)
    if eig is not None:
        s.zeile(eig.firma_oder_name)
    s.luecke(5)
    s.zeile("Mitteilung: Ausübung des Retentionsrechts (Art. 712k ZGB)", fett=True, gr=13, abstand=7)
    s.zeile(f"Stockwerkeigentümergemeinschaft {lg} · Einheit {e.bezeichnung}")
    s.luecke(3)
    s.absatz("Die Gemeinschaft macht wegen der offenen Beitragsforderungen das Retentionsrecht an den beweglichen "
             "Sachen geltend, die sich in den Räumen der Einheit befinden und zu deren Einrichtung oder Gebrauch "
             "dienen:", gr=10, abstand=5)
    s.luecke(2)
    s.absatz(fall.retention_gegenstaende, gr=10, abstand=5)
    s.luecke(3)
    if fall.retention_erklaert_am:
        s.zeile(f"Datum: {fall.retention_erklaert_am:%d.%m.%Y}")
    s.luecke(3)
    s.absatz("Entwurf zur Prüfung: Voraussetzungen und Umfang des Retentionsrechts sind im Einzelfall rechtlich zu "
             "beurteilen.", gr=8, abstand=4)
    s.luecke(4)
    s.zeile(org.firma or '')
    return s.bytes()


@nur_deutsch
def pfandrecht_pdf(pfandrecht):
    """Antrag auf Eintragung eines Gemeinschaftspfandrechts (Art. 712i ZGB) beim Grundbuchamt — rudimentär.

    Die Pfandsumme umfasst NUR die Beitragsforderungen der letzten 36 Monate; ältere offene Beträge stehen getrennt
    und gehen nicht in die Summe ein. Der Antrag ist ein Entwurf zur Prüfung und zur Unterschrift."""
    from stweg import inkasso
    pf = pfandrecht
    fall = pf.fall
    e = fall.einheit
    lg = e.liegenschaft
    eig = fall.eigentuemer or e.stockwerkeigentuemer
    org = lg.organisation
    s = _Seite(f"Pfandrecht {lg}")
    s.zeile(org.firma or '', fett=True, gr=11)
    s.zeile(f"{org.strasse}, {org.plz} {org.ort}".strip(', '), gr=9)
    s.luecke(5)
    s.zeile(f"Grundbuchamt {lg.ort or ''}{' (' + lg.kanton + ')' if lg.kanton else ''}".strip(), fett=True)
    s.luecke(5)
    s.zeile("Antrag auf Eintragung eines Gemeinschaftspfandrechts (Art. 712i ZGB)", fett=True, gr=13, abstand=7)
    s.luecke(2)
    s.zeile("Gläubigerin", fett=True)
    s.zeile(f"Stockwerkeigentümergemeinschaft {lg.strasse}, {lg.plz} {lg.ort}")
    s.zeile(f"vertreten durch die Verwaltung {org.firma or ''}")
    s.luecke(3)
    s.zeile("Schuldner (Stockwerkeigentümer)", fett=True)
    s.zeile(eig.firma_oder_name if eig else '— nicht erfasst —')
    if eig is not None and (eig.strasse or eig.ort):
        s.zeile(f"{eig.strasse}, {eig.plz} {eig.ort}".strip(', '))
    s.luecke(3)
    s.zeile("Pfandobjekt", fett=True)
    s.zeile(f"Stockwerkeinheit «{e.bezeichnung}»{' · ' + e.etage if e.etage else ''}, Wertquote "
            f"{zahl(e.wertquote)}/{lg.wertquote_total}")
    s.zeile(f"Liegenschaft {lg.strasse}, {lg.plz} {lg.ort}")
    s.zeile("Grundbuchblatt / EGRID: ______________________  (vom Grundbuchamt bzw. aus dem Grundbuchauszug zu ergänzen)", gr=9)
    s.luecke(4)
    s.zeile(f"Pfandsumme: CHF {_chf(pf.betrag_pfandberechtigt)}", fett=True, gr=12, abstand=6)
    s.absatz(f"Beitragsforderungen der Gemeinschaft der letzten drei Jahre vor dem Stichtag {pf.stichtag:%d.%m.%Y} "
             f"(Forderungsdatum nach dem {inkasso._plus_monate(pf.stichtag, -inkasso.PFANDRECHT_MONATE):%d.%m.%Y}).",
             gr=9, abstand=4)
    s.luecke(2)
    s.zeile("Aufstellung der pfandberechtigten Forderungen", fett=True)
    for z in pf.zeilen:
        if z['pfandberechtigt']:
            d = date_fromiso(z['datum'])
            s.zeile(f"{d:%d.%m.%Y}  {z['text'][:50]:<50}  CHF {_chf(Decimal(z['offen'])):>12}", gr=9, abstand=4)
    ausgeschlossen = [z for z in pf.zeilen if not z['pfandberechtigt']]
    if ausgeschlossen:
        s.luecke(3)
        s.zeile(f"Nicht pfandberechtigt (älter als drei Jahre), NICHT in der Pfandsumme: CHF "
                f"{_chf(pf.betrag_ausgeschlossen)}", fett=True, gr=9)
        for z in ausgeschlossen:
            d = date_fromiso(z['datum'])
            s.zeile(f"{d:%d.%m.%Y}  {z['text'][:50]:<50}  CHF {_chf(Decimal(z['offen'])):>12}", gr=8, abstand=4)
    s.luecke(4)
    s.absatz("Beilagen: Reglement bzw. Beschluss über die Beiträge, Mahnungen, Aufstellung der Forderungen.", gr=9,
             abstand=4)
    s.luecke(6)
    s.zeile(f"Ort, Datum: ____________________      Unterschrift Verwaltung: ____________________")
    s.luecke(4)
    s.absatz("Entwurf zur Prüfung und Unterschrift. Das System rechnet die Pfandsumme aus den Forderungen; ob und in "
             "welchem Umfang das Pfandrecht entsteht, ist rechtlich zu beurteilen.", gr=8, abstand=4)
    return s.bytes()


HINWEIS_RECHT = ("Achtung: Dieses Dokument ersetzt keine juristische Prüfung. Die Berechnung beruht auf den "
                 "Annahmen in der Dokumentation des Programms; Fristen, Zinsen und Anrechnungen sind vor Gebrauch von "
                 "einer Fachperson zu bestätigen.")


def handaenderung_pdf(wechsel, *, jahresbetrag=None):
    """Handänderungs-Abrechnung (pro rata temporis) zwischen Verkäufer und Käufer."""
    from stweg import handaenderung
    a = handaenderung.aufteilung(wechsel, jahresbetrag=jahresbetrag)
    e = wechsel.einheit
    lg = e.liegenschaft
    org = lg.organisation
    s = _Seite(f"Handänderung {lg}")
    s.zeile(org.firma or '', fett=True, gr=11)
    s.luecke(4)
    s.zeile(f"Handänderungs-Abrechnung {a['jahr']}", fett=True, gr=13, abstand=7)
    s.zeile(f"{lg.strasse}, {lg.plz} {lg.ort} — Einheit «{e.bezeichnung}»")
    s.zeile(f"Eigentumsübergang: {wechsel.datum:%d.%m.%Y} (erster Tag des Käufers)")
    s.zeile(f"Verkäufer: {a['verkaeufer'].firma_oder_name if a['verkaeufer'] else '— nicht erfasst —'}")
    s.zeile(f"Käufer: {a['kaeufer'].firma_oder_name}")
    s.luecke(4)
    s.zeile(f"Jahresbetrag CHF {_chf(a['jahresbetrag'])}  ({a['quelle']})", fett=True)
    s.zeile(f"Tage: Verkäufer {a['verkaeufer_tage']}, Käufer {a['kaeufer_tage']} von {a['jahrestage']}", gr=9)
    s.luecke(3)
    s.zeile(f"{'':<22}{'Verkäufer':>14}{'Käufer':>14}", fett=True, gr=9)
    for text, v, k in (("Kostenanteil (pro rata)", a['verkaeufer_anteil'], a['kaeufer_anteil']),
                       ("Akonto bezahlt", a['akonto_verkaeufer'], a['akonto_kaeufer']),
                       ("Saldo (− = zu viel bezahlt)", a['saldo_verkaeufer'], a['saldo_kaeufer'])):
        s.zeile(f"{text:<22}{_chf(v):>14}{_chf(k):>14}", gr=9, abstand=4)
    s.luecke(3)
    ausgleich = a['ausgleich_verkaeufer_an_kaeufer']
    if ausgleich >= 0:
        s.zeile(f"Ausgleich: Der Verkäufer erstattet dem Käufer CHF {_chf(ausgleich)}", fett=True)
    else:
        s.zeile(f"Ausgleich: Der Käufer erstattet dem Verkäufer CHF {_chf(-ausgleich)}", fett=True)
    s.luecke(3)
    s.zeile(f"Verzugszins bis zum Vortag des Übergangs: CHF {_chf(a['zins_bis_uebergang'])}; danach bis "
            f"{a['stichtag']:%d.%m.%Y}: CHF {_chf(a['zins_danach'])}", gr=9)
    s.zeile(f"Beiträge des Verkäufers, die am Vortag des Übergangs noch offen waren: CHF "
            f"{_chf(a['offen_verkaeufer_bei_uebergang'])}", gr=9)
    s.luecke(5)
    s.absatz(HINWEIS_RECHT, gr=8, abstand=4)
    return s.bytes()


def date_fromiso(text):
    from datetime import date
    return date.fromisoformat(text)
