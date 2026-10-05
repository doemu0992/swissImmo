"""Nebenkostenabrechnung an die Mieter: Kontext je Mieter und Versand per E-Mail.

Der Kontext (Adresse, Positionen, Anteil, Akonto, Saldo) ist dasselbe Dictionary, das
`generate_nk_pdf_einzeln` und `generate_nk_pdf_sammel` brauchen. Er entstand bis zum
Phase-1-Audit inline in `fw_nebenkosten_versand`; er liegt jetzt hier, damit Sammel-PDF und
E-Mail-Versand aus derselben Quelle rechnen und nicht zwei Kopien auseinanderlaufen.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def mieter_kontexte(p, result):
    """Je abzurechnendem Mietverhältnis: {'vertrag', 'mieter', 'k'} — ohne Leerstand.

    `result` ist die kanonische Ausgabe von `core.utils.billing.hole_abrechnung` (bei einer
    verbuchten Periode der eingefrorene Stand). Absender ist die Verwaltung DER PERIODE.
    """
    from rentals.models import Mietvertrag

    vw = p.organisation
    lg = p.liegenschaft
    periode_str = f"{p.bezeichnung} ({p.start_datum:%d.%m.%Y}–{p.ende_datum:%d.%m.%Y})"
    positionen = result.get('belege_details', [])
    total_kosten = result.get('total_kosten', Decimal('0.00'))

    eintraege = []
    for a in result.get('abrechnungen', []):
        vid = a.get('vertrag_id')
        if not vid or a.get('typ') == 'leerstand':
            continue
        v = (Mietvertrag.objects.filter(id=vid)
             .select_related('mieter', 'mitmieter', 'einheit__liegenschaft').first())
        if not v:
            continue
        m = v.mieter
        namen = m.display_name
        zweit = (v.mitmieter.display_name if v.mitmieter_id else (v.mitmieter_name or '')).strip()
        if zweit:
            namen += f" & {zweit}"
        adresse = [namen]
        if m.strasse:
            adresse.append(m.strasse)
        if m.plz or m.ort:
            adresse.append(f"{m.plz or ''} {m.ort or ''}".strip())
        k = {
            'verwaltung': vw, 'periode': periode_str,
            'objekt': f"{lg.strasse}, {lg.plz} {lg.ort} · {v.einheit.bezeichnung}" if lg and v.einheit_id else (v.einheit.bezeichnung if v.einheit_id else ''),
            'adresse': adresse, 'positionen': positionen, 'total_kosten': total_kosten,
            'kosten_anteil': a.get('kosten_anteil', 0), 'akonto': a.get('akonto', 0),
            'saldo': a.get('saldo', 0), 'nachzahlung': a.get('nachzahlung', False),
        }
        eintraege.append({'vertrag': v, 'mieter': m, 'k': k})
    return eintraege


def antwortadresse(organisation_id):
    """Antwortadresse der Verwaltung: ihr aktives «Antworten»-Postfach, sonst None (globale Adresse).

    Dieselbe Regel wie `tickets.workflow.reply_to`, nur am Mandanten statt am Ticket: Eine Antwort
    des Mieters auf die Abrechnung landet im Bestand der richtigen Verwaltung.
    """
    from core.models import Postfach
    pf = (Postfach.alle_organisationen
          .filter(organisation_id=organisation_id, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True)
          .order_by('pk').first())
    return pf.benutzer if pf and '@' in (pf.benutzer or '') else None


def mail_text(k, periode_bezeichnung):
    """Begleittext der Mail (HTML). Deutsch, wie das angehängte Dokument (`nk_abrechnung` ist fest deutsch)."""
    from html import escape
    saldo = Decimal(str(k.get('saldo') or 0))
    if saldo > 0:
        ergebnis = f"Es ergibt sich eine <b>Nachzahlung von CHF {saldo:.2f}</b>; die Rechnung mit Einzahlungsschein finden Sie im Mieterportal bzw. folgt separat."
    elif saldo < 0:
        ergebnis = f"Es ergibt sich ein <b>Guthaben von CHF {abs(saldo):.2f}</b>, das wir Ihnen gutschreiben."
    else:
        ergebnis = "Die Abrechnung geht auf; es ergibt sich weder eine Nachzahlung noch ein Guthaben."
    vw = k['verwaltung']
    absender = escape(getattr(vw, 'firma', '') or 'Ihre Verwaltung')
    return (f"<p>Guten Tag</p>"
            f"<p>im Anhang finden Sie die Nebenkostenabrechnung <b>{escape(periode_bezeichnung)}</b> "
            f"für {escape(k.get('objekt') or '')}.</p><p>{ergebnis}</p>"
            f"<p>Sie können die Abrechnung und die Belege bei uns einsehen; Einwendungen teilen Sie uns bitte "
            f"innert 30 Tagen nach Erhalt mit. Antworten Sie dazu einfach auf diese Mail.</p>"
            f"<p>Freundliche Grüsse<br>{absender}</p>")
