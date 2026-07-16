"""Bewerber-Scoring für die Mieterwahl. Bewertet jede Mietbewerbung nach
objektiven Kriterien und liefert Einzelindikatoren + einen Eignungs-Score (0–100).

Kriterien (Schweizer Praxis):
- Tragbarkeit (Drittel-Regel): Jahreseinkommen ≥ 3× Jahres-Bruttomiete. 45 Pkt.
- Keine Betreibungen. 25 Pkt.
- Unbefristete Anstellung / gesicherte Erwerbssituation. 15 Pkt.
- Vollständige Unterlagen (Betreibungsauszug, Ausweis, Lohnausweis). 15 Pkt.

Der Score ist eine Entscheidungshilfe, keine automatische Zu-/Absage."""
import re
from decimal import Decimal


def parse_einkommen(text):
    """Extrahiert das Jahreseinkommen aus einer Freitext-/Spannenangabe, z. B.
    "80'000 – 100'000" → 80000. Robust gegen Stör-Zahlen: ein angehängter
    Rappen-Dezimalteil wird abgetrennt, Kalenderjahre (1900–2099) werden verworfen,
    und wenn plausible Jahresbeträge vorhanden sind, werden monatsgrosse Kleinwerte
    (< 12'000) ignoriert. Gibt None zurück, wenn nichts Plausibles erkennbar ist."""
    if not text:
        return None
    werte = []
    for m in re.finditer(r"\d[\d'’.\s]*\d|\d+", str(text)):
        roh = m.group(0)
        # Rappen-Dezimalteil (.dd / ,dd am Ende) abtrennen, damit "80'000.50" nicht
        # zu 8000050 verschmilzt.
        kern = re.sub(r"[.,]\d{2}$", "", roh)
        digits = re.sub(r"[^\d]", "", kern)
        if digits:
            werte.append(int(digits))
    # Kalenderjahre und Kleinstwerte raus (Jahreszahlen wie 2024 sind kein Einkommen).
    kandidaten = [w for w in werte if w >= 1000 and not (1900 <= w <= 2099)]
    if not kandidaten:
        return None
    # Existiert ein plausibler Jahresbetrag (≥ 12'000), sind kleinere Werte fast immer
    # Monatslöhne/Störzahlen → ignorieren. Sonst die untere Grenze der Spanne nehmen.
    jahres = [w for w in kandidaten if w >= 12000]
    return min(jahres) if jahres else min(kandidaten)


def _ampel(pkt, maxpkt):
    q = pkt / maxpkt if maxpkt else 0
    if q >= 0.75:
        return 'gut'
    if q >= 0.4:
        return 'mittel'
    return 'schlecht'


def bewerte_bewerbung(bewerbung, brutto_monat):
    """Gibt ein dict mit Einzelindikatoren + Gesamtscore für eine Bewerbung."""
    brutto_monat = Decimal(str(brutto_monat or 0))
    jahresmiete = brutto_monat * 12
    einkommen = parse_einkommen(bewerbung.einkommen_jahr)

    # --- Tragbarkeit (Drittel-Regel) ---
    if einkommen and jahresmiete > 0:
        faktor = Decimal(einkommen) / jahresmiete   # Ziel ≥ 3.0
        if faktor >= 3:
            trag_pkt, trag_txt = 45, "Gut (≥ 3×)"
        elif faktor >= Decimal('2.5'):
            trag_pkt, trag_txt = 30, "Knapp (2.5–3×)"
        elif faktor >= 2:
            trag_pkt, trag_txt = 15, "Grenzwertig (2–2.5×)"
        else:
            trag_pkt, trag_txt = 0, "Ungenügend (< 2×)"
        faktor_txt = f"{faktor.quantize(Decimal('0.1'))}×"
    else:
        trag_pkt, trag_txt, faktor = 0, "Einkommen unklar", None
        faktor_txt = "—"

    # --- Betreibungen ---
    if bewerbung.hat_betreibungen:
        betr_pkt, betr_txt = 0, "Betreibungen vorhanden"
    else:
        betr_pkt, betr_txt = 25, "Keine Betreibungen"

    # --- Anstellung / Erwerbssituation ---
    stabil_status = bewerbung.erwerbsstatus in ('angestellt', 'pensioniert', 'selbstaendig')
    if stabil_status and bewerbung.ist_unbefristet:
        anst_pkt, anst_txt = 15, "Unbefristet"
    elif stabil_status:
        anst_pkt, anst_txt = 8, "Befristet"
    else:
        anst_pkt, anst_txt = 0, bewerbung.get_erwerbsstatus_display()

    # --- Dokumente ---
    docs = [bool(bewerbung.betreibungsauszug), bool(bewerbung.ausweiskopie), bool(bewerbung.lohnausweis)]
    docs_n = sum(docs)
    dok_pkt = round(15 * docs_n / 3)
    dok_txt = f"{docs_n}/3 Dokumente"

    score = trag_pkt + betr_pkt + anst_pkt + dok_pkt
    indikatoren = [
        {'label': 'Tragbarkeit', 'wert': f"{faktor_txt} · {trag_txt}", 'ampel': _ampel(trag_pkt, 45)},
        {'label': 'Betreibungen', 'wert': betr_txt, 'ampel': 'gut' if betr_pkt else 'schlecht'},
        {'label': 'Anstellung', 'wert': anst_txt, 'ampel': _ampel(anst_pkt, 15)},
        {'label': 'Unterlagen', 'wert': dok_txt, 'ampel': _ampel(dok_pkt, 15)},
    ]
    return {
        'score': score,
        'ampel': _ampel(score, 100),
        'einkommen': einkommen,
        'tragbarkeit_faktor': faktor,
        'indikatoren': indikatoren,
    }
